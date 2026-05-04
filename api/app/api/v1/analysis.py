"""``/v1/analysis`` — 모바일 SSE 분석 + polling fallback + clarify resume (Story 3.7).

3 endpoint:
- ``POST /v1/analysis/stream``    — SSE 스트림 (progress/token/citation/clarify/done/error)
- ``GET  /v1/analysis/{meal_id}`` — polling fallback (status discriminator envelope)
- ``POST /v1/analysis/clarify``   — Story 3.4 needs_clarification resume (SSE 응답)

핵심 결정:
- 3 게이트 (current_user + require_basic_consents + require_automated_decision_consent)
  — 분석 호출 비대칭(작성/생성 의미). polling은 *조회*라 automated_decision 미요구
  (PIPA Art.35 정보주체 권리 정합 — deps.py:182-187 SOT).
- meals 소유권 검증 — 미존재/비소유/soft-deleted 모두 동일 404 + ``analysis.meal.not_found``
  (enumeration 차단).
- ``app.state.analysis_service is None`` → 503 + ``analysis.checkpointer.unavailable``
  (Story 3.3 lifespan D10 graceful 정합).
- per-IP rate limit ``10/minute`` — Redis 분산 fixed-window 카운터(burst 1차 가드).
  미설정/장애 시 graceful skip(test/dev fallback).
- SSE 본문 청킹 — ``chunk_text_for_streaming(text, chunk_chars=24)`` + 30ms 간격
  (D1 결정 — pseudo-streaming + post-processing 회귀 0). True LLM-token streaming은
  Story 8.4 polish.
- ``done``/``clarify``/``error`` 정확히 1회 emit 후 generator 종료 (AC3).
- meal_analyses UPSERT — ``event: done`` emit *직전* fresh session으로 호출(AC17).
  실패 swallow + Sentry capture + log warning(graceful — 사용자에게 결과는 보임).
- NFR-S5 마스킹 — meal_id/mode/phase_count/token_count/citation_count/used_llm/
  final_fit_score/latency_ms/persisted만 log. raw_text/feedback 본문 X (Story 3.6 anchor).
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Final, Literal

import sentry_sdk
import structlog
from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette import ServerSentEvent
from sse_starlette.sse import EventSourceResponse
from starlette.responses import JSONResponse

from app.api.deps import (
    DbSession,
    require_automated_decision_consent,
    require_basic_consents,
)
from app.api.v1.meals import MealMacros
from app.core.config import settings
from app.core.exceptions import (
    AnalysisCheckpointerUnavailableError,
    AnalysisClarifyValidationError,
    AnalysisMealNotFoundError,
    AnalysisRateLimitExceededError,
    BalanceNoteError,
    ProblemDetail,
)
from app.db.models.meal import Meal
from app.db.models.user import User
from app.domain.fit_score import aggregate_meal_macros, to_summary_label
from app.graph.state import (
    Citation,
    ClarificationOption,
    FeedbackOutput,
    FitEvaluation,
    FoodItem,
    MealAnalysisState,
    RetrievedFood,
    get_state_field,
)
from app.services.analysis_service import AnalysisService
from app.services.meal_analysis_persistence import upsert_meal_analysis
from app.services.sse_emitter import (
    AnalysisDonePayload,
    chunk_text_for_streaming,
    event_citation,
    event_clarify,
    event_done,
    event_error,
    event_progress,
    event_token,
)

log = structlog.get_logger(__name__)

# 라우터 outer budget — Story 3.6 router 25s + chunking margin(5s). 실 timeout은 Story
# 3.6 ``llm_router_total_budget_seconds=25``가 1차 가드 — 본 라우터의 30s는 안전망.
_DONE_EVENT_TIMEOUT_SECONDS: Final[float] = 30.0

# Rate limit — RATE_LIMIT_LANGGRAPH(10/minute) per-IP for stream/clarify, 60/minute for poll.
_RATE_LIMIT_PER_MINUTE: Final[int] = 10
_RATE_LIMIT_POLL_PER_MINUTE: Final[int] = 60
_RATE_LIMIT_REDIS_PREFIX: Final[str] = "rl:analysis:langgraph"
_RATE_LIMIT_POLL_REDIS_PREFIX: Final[str] = "rl:analysis:poll"

# SSE 첫 emit phase — TTFT 보장(NFR-P3 p50 ≤ 1.5s, p95 ≤ 3s).
_INITIAL_PROGRESS_PHASE: Final[str] = "parse"

# AC2 SOT — 6 SSE event types (progress/token/citation/done/clarify/error).
_SSE_EVENT_TYPES = Literal["progress", "token", "citation", "done", "clarify", "error"]

# SSE keepalive — proxy(ALB/CDN) idle timeout(보통 60s) 회피용 comment ping(15s).
_SSE_PING_INTERVAL_SECONDS: Final[int] = 15


router = APIRouter()


# --- Pydantic Request 스키마 ----------------------------------------------------


class AnalysisStreamRequest(BaseModel):
    """``POST /v1/analysis/stream`` body — extra="forbid"로 silent unknown 차단."""

    model_config = ConfigDict(extra="forbid")

    meal_id: uuid.UUID


class AnalysisClarifyRequest(BaseModel):
    """``POST /v1/analysis/clarify`` body — Story 3.4 ``ClarificationOption.value`` 정합.

    ``selected_value``는 ``min_length=1`` + ``max_length=80``(Story 3.4 SOT). Pydantic이
    1차 게이트, ``aresume`` 호출 시점에 빈 값 catch(``AnalysisClarifyValidationError``)는
    *adapter-level defensive double-gate*.
    """

    model_config = ConfigDict(extra="forbid")

    meal_id: uuid.UUID
    selected_value: str = Field(min_length=1, max_length=80)


# --- Helper: rate limit (Redis 분산 fixed-window 카운터) ----------------------


async def _redis_fixed_window_incr(request: Request, *, prefix: str, limit: int) -> None:
    """Redis 분산 fixed-window 카운터 — `prefix:ip:minute_bucket` key.

    CR Wave 1 fix: incr + expire를 *pipeline atomic* 단일 round-trip로 발행
    (이전 구현은 incr 성공 후 expire가 silently 실패해 permanent counter 누적
    DoS가 가능 — 같은 키가 TTL 없이 영구 잔존하는 시나리오 차단).

    Redis 미설정/장애 시 graceful skip(test/dev fallback). NFR-S5 — IP는 raw 출력 X.
    """
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    from slowapi.util import get_remote_address

    ip = get_remote_address(request)
    minute_bucket = int(time.time() // 60)
    key = f"{prefix}:{ip}:{minute_bucket}"

    try:
        # pipeline으로 incr + expire atomic 실행 — expire 실패 시 incr도 함께 실패하도록.
        # +5s 안전 margin(시계 skew 가드). NX 옵션으로 already-set TTL 보존.
        async with redis_client.pipeline(transaction=False) as pipe:
            pipe.incr(key)
            pipe.expire(key, 65, nx=True)
            results = await asyncio.wait_for(pipe.execute(), timeout=2.0)
        count = int(results[0])
    except (TimeoutError, Exception):  # noqa: BLE001 — Redis 장애 graceful skip.
        log.warning("analysis.rate_limit.redis_unavailable")
        return

    if count > limit:
        raise AnalysisRateLimitExceededError("분석 요청이 너무 많아요. 1분 후 다시 시도해주세요")


async def enforce_langgraph_rate_limit(request: Request) -> None:
    """per-IP 10/minute rate limit for `/stream` + `/clarify` (RATE_LIMIT_LANGGRAPH).

    Redis 분산 fixed-window 카운터 — 동일 IP의 1분 내 11번째 요청부터 429 raise.
    slowapi의 module-level decorator 패턴이 lifespan-init limiter와 호환되지 않아,
    본 helper는 hand-rolled Redis fixed-window로 대체(D1 결정 — Story 8.4 polish
    시 sliding-window 또는 slowapi 정합 재검토).
    """
    await _redis_fixed_window_incr(
        request, prefix=_RATE_LIMIT_REDIS_PREFIX, limit=_RATE_LIMIT_PER_MINUTE
    )


async def enforce_poll_rate_limit(request: Request) -> None:
    """per-IP 60/minute rate limit for `GET /v1/analysis/{id}` polling.

    CR D8 결정 — mobile 1.5초 setInterval × 30회 cap이 client-side 가드이나, 악의적
    클라이언트의 polling barrage가 `aget_state` Postgres round-trip을 부하시킬 수
    있어 server-side 60/min cap 추가(여유 cap — 정상 30회 polling은 통과, 악성
    burst만 차단). 동일 helper 재사용으로 Redis 미설정 시 graceful skip 정합.
    """
    await _redis_fixed_window_incr(
        request, prefix=_RATE_LIMIT_POLL_REDIS_PREFIX, limit=_RATE_LIMIT_POLL_PER_MINUTE
    )


# --- Helper: meal 소유권 / service 가용성 검증 -------------------------------


async def _resolve_meal(
    db: AsyncSession,
    *,
    meal_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Meal:
    """meals row 소유권 + ``deleted_at IS NULL`` 검증. 미일치 시 404 일원화."""
    result = await db.execute(
        select(Meal).where(
            Meal.id == meal_id,
            Meal.user_id == user_id,
            Meal.deleted_at.is_(None),
        )
    )
    meal = result.scalar_one_or_none()
    if meal is None:
        raise AnalysisMealNotFoundError("식단을 찾을 수 없습니다")
    return meal


def _get_analysis_service(request: Request) -> AnalysisService:
    """``app.state.analysis_service`` None 가드(Story 3.3 D10 graceful 정합)."""
    service: AnalysisService | None = getattr(request.app.state, "analysis_service", None)
    if service is None:
        raise AnalysisCheckpointerUnavailableError(
            "analysis service not available — checkpointer init failed"
        )
    return service


def _unexpected_problem(*, instance: str) -> ProblemDetail:
    """예상 외 예외 fallback ProblemDetail — 내부 stack/메시지 leak 차단(NFR-S5).

    detail은 일반화된 한국어 메시지 — 사용자에게 *"분석을 완료하지 못했어요"* 안내.
    """
    return ProblemDetail(
        title="Analysis Stream Unexpected Error",
        status=500,
        detail="분석을 완료하지 못했어요",
        instance=instance,
        code="analysis.unexpected",
    )


def _state_to_macros(state: MealAnalysisState) -> MealMacros:
    """state.parsed_items + state.retrieval → ``MealMacros`` (api.v1.meals 정합).

    domain ``MealMacros``(kcal/carb_g/protein_g/fat_g/fiber_g/coverage_ratio/
    has_vegetable_or_fruit)와 *분리* — 응답 schema는 식약처 OpenAPI 키
    (carbohydrate_g/protein_g/fat_g/energy_kcal). ``aggregate_meal_macros`` 출력에서
    값 매핑.

    parsed_items 또는 retrieval 부재 시 *zero macros* — incomplete_data 정합.
    """
    parsed_items_raw = get_state_field(state, "parsed_items", default=None)
    retrieval_raw = get_state_field(state, "retrieval", default=None)

    parsed_items: list[FoodItem] = []
    if parsed_items_raw and isinstance(parsed_items_raw, list):
        for raw in parsed_items_raw:
            try:
                parsed_items.append(
                    raw if isinstance(raw, FoodItem) else FoodItem.model_validate(raw)
                )
            except Exception as exc:  # noqa: BLE001 — corrupt item skip(graceful).
                log.warning(
                    "analysis.state_to_macros.skipped",
                    item_class=type(raw).__name__,
                    error_class=type(exc).__name__,
                )
                continue

    retrieved_foods: list[RetrievedFood] = []
    if retrieval_raw is not None:
        retrieved_raw = get_state_field(retrieval_raw, "retrieved_foods", default=None)
        if retrieved_raw and isinstance(retrieved_raw, list):
            for raw in retrieved_raw:
                try:
                    retrieved_foods.append(
                        raw if isinstance(raw, RetrievedFood) else RetrievedFood.model_validate(raw)
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "analysis.state_to_macros.skipped",
                        item_class=type(raw).__name__,
                        error_class=type(exc).__name__,
                    )
                    continue

    if not parsed_items:
        return MealMacros(
            carbohydrate_g=0.0,
            protein_g=0.0,
            fat_g=0.0,
            energy_kcal=0.0,
        )

    domain_macros = aggregate_meal_macros(parsed_items, retrieved_foods)
    return MealMacros(
        carbohydrate_g=domain_macros.carb_g,
        protein_g=domain_macros.protein_g,
        fat_g=domain_macros.fat_g,
        energy_kcal=domain_macros.kcal,
    )


def _state_to_done_payload(state: MealAnalysisState, *, meal_id: uuid.UUID) -> AnalysisDonePayload:
    """state.fit_evaluation + state.feedback → ``AnalysisDonePayload`` (AC2 done schema)."""
    fit_eval_raw = get_state_field(state, "fit_evaluation", default=None)
    feedback_raw = get_state_field(state, "feedback", default=None)

    if fit_eval_raw is None or feedback_raw is None:
        # 정상 흐름에서는 도달 X(generator 분기에서 사전 차단). defensive fallback.
        raise BalanceNoteError("state missing fit_evaluation or feedback")

    fit_eval = (
        fit_eval_raw
        if isinstance(fit_eval_raw, FitEvaluation)
        else FitEvaluation.model_validate(fit_eval_raw)
    )
    feedback = (
        feedback_raw
        if isinstance(feedback_raw, FeedbackOutput)
        else FeedbackOutput.model_validate(feedback_raw)
    )

    summary_label = to_summary_label(fit_eval.fit_label, fit_eval.fit_score)
    macros = _state_to_macros(state)

    try:
        return AnalysisDonePayload(
            meal_id=meal_id,
            final_fit_score=fit_eval.fit_score,
            fit_score_label=summary_label,
            macros=macros,
            feedback_text=feedback.text,
            citations_count=len(feedback.citations),
            used_llm=feedback.used_llm,
        )
    except ValidationError as exc:
        # CR Wave 1 — feedback.text 빈 문자열(min_length=1) 등 Pydantic 위반은 typed
        # `BalanceNoteError`로 변환(이전 구현은 broad except → unexpected 500). 호출
        # 측 generator의 BalanceNoteError 분기가 RFC 7807 정합 코드로 emit.
        raise BalanceNoteError(
            f"AnalysisDonePayload validation failed: {exc.errors()[0]['type']}"
        ) from exc


def _state_citations(state: MealAnalysisState) -> list[Citation]:
    """state.feedback.citations 안전 추출 — Pydantic round-trip(dict/instance 양 형태)."""
    feedback_raw = get_state_field(state, "feedback", default=None)
    if feedback_raw is None:
        return []
    citations_raw = get_state_field(feedback_raw, "citations", default=None) or []
    citations: list[Citation] = []
    if not isinstance(citations_raw, list):
        return []
    for raw in citations_raw:
        try:
            citations.append(raw if isinstance(raw, Citation) else Citation.model_validate(raw))
        except Exception:  # noqa: BLE001 — corrupt citation skip.
            continue
    return citations


def _state_fit_reason(state: MealAnalysisState) -> str:
    """state.fit_evaluation.fit_reason 안전 추출 — incomplete_data 기본 fallback."""
    fit_eval_raw = get_state_field(state, "fit_evaluation", default=None)
    if fit_eval_raw is None:
        return "incomplete_data"
    reason = get_state_field(fit_eval_raw, "fit_reason", default="incomplete_data")
    if reason in {"ok", "allergen_violation", "incomplete_data"}:
        return str(reason)
    return "incomplete_data"


def _state_clarification_options(state: MealAnalysisState) -> list[ClarificationOption]:
    """state.clarification_options 안전 추출."""
    raw_list = get_state_field(state, "clarification_options", default=None) or []
    options: list[ClarificationOption] = []
    if not isinstance(raw_list, list):
        return []
    for raw in raw_list:
        try:
            options.append(
                raw
                if isinstance(raw, ClarificationOption)
                else ClarificationOption.model_validate(raw)
            )
        except Exception:  # noqa: BLE001
            continue
    return options


# --- SSE generator (공통 helper — stream + clarify 재사용) ---------------------


async def _persist_done_payload(
    request: Request,
    *,
    meal_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: AnalysisDonePayload,
    fit_reason: str,
    citations: list[Citation],
) -> bool:
    """``meal_analyses`` UPSERT — fresh session으로 분리 호출(graceful 흐름 정합).

    CR Wave 1 — `session_maker()` 자체 raise 가드(engine disposed 등 edge) 추가.
    이전 구현은 session_maker raise 시 generator의 broad except로 fall-through →
    `event: done` skip + `event: error` emit하여 *분석은 완료됐는데 UI는 error*
    안정성 침해. 본 helper는 모든 예외를 swallow + False 반환으로 차단.
    """
    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        log.warning("meal_analyses.upsert_skipped", reason="session_maker_unavailable")
        return False
    try:
        async with session_maker() as persist_session:
            return await upsert_meal_analysis(
                persist_session,
                meal_id=meal_id,
                user_id=user_id,
                payload=payload,
                fit_reason=fit_reason,
                citations=citations,
            )
    except Exception as exc:  # noqa: BLE001 — graceful, generator 흐름 보호.
        log.warning(
            "meal_analyses.upsert_skipped",
            reason="session_maker_raised",
            error_class=type(exc).__name__,
        )
        sentry_sdk.capture_exception(exc)
        return False


async def _run_and_stream(
    request: Request,
    *,
    service: AnalysisService,
    meal_id: uuid.UUID,
    user_id: uuid.UUID,
    raw_text: str | None,
    clarify_value: str | None,
    log_event: str,
) -> AsyncIterator[ServerSentEvent]:
    """SSE generator 공통 흐름 — POST /stream + POST /clarify 재사용.

    분기:
    - clarify_value 미지정 → ``service.run(meal_id, user_id, raw_text)`` 신규 호출.
    - clarify_value 지정    → ``service.aresume(thread_id, user_input)`` resume.

    종료 1회: ``done`` 또는 ``clarify`` 또는 ``error`` 정확히 1회 emit 후 return.
    """
    start = time.monotonic()
    token_count = 0
    citation_count = 0
    phase_count = 0
    used_llm = "stub"
    final_fit_score = 0
    persisted = False
    instance_path = str(request.url.path)

    # CR Wave 1 D3 — Sentry transaction(`op="analysis.sse.complete"` + tag mode=sse)
    # NFR-P3 latency p50/p95 attribution용. SSE generator 종단까지 transaction이
    # 살아 있어 chunking sleep + persist까지 span 누적. 단, exception 발생 시도 hub
    # 자동 캡처 — 본 generator의 except가 typed Sentry capture를 책임지므로
    # transaction은 timing 박는 용도만.
    transaction = sentry_sdk.start_transaction(
        op="analysis.sse.complete",
        name=log_event,
    )
    transaction.set_tag("mode", "sse")
    transaction.set_data("meal_id", str(meal_id))

    try:
        # ① TTFT 보장 — 라우터 진입 직후 progress emit (Story spec D1 정합).
        yield event_progress(
            _INITIAL_PROGRESS_PHASE,
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )
        phase_count += 1

        # ② 파이프라인 호출 — outer wait_for로 30s 안전망(Story 3.6 25s가 1차 가드).
        if clarify_value is not None:
            try:
                state = await asyncio.wait_for(
                    service.aresume(
                        thread_id=f"meal:{meal_id}",
                        user_input={"selected_value": clarify_value},
                    ),
                    timeout=_DONE_EVENT_TIMEOUT_SECONDS,
                )
            except ValueError as exc:
                # 빈 selected_value 등 — Pydantic이 1차 차단하나 adapter-level fallback.
                raise AnalysisClarifyValidationError(str(exc)) from exc
        else:
            # CR Wave 1 #3 — `assert`는 `python -O` 시 strip되므로 runtime check.
            if raw_text is None:
                raise BalanceNoteError("raw_text required for non-clarify path")
            state = await asyncio.wait_for(
                service.run(meal_id=meal_id, user_id=user_id, raw_text=raw_text),
                timeout=_DONE_EVENT_TIMEOUT_SECONDS,
            )

        # ③ 결과 분기 — clarify > error > done 우선순위.
        needs_clarification = bool(get_state_field(state, "needs_clarification", default=False))
        feedback_present = get_state_field(state, "feedback", default=None) is not None
        node_errors = get_state_field(state, "node_errors", default=None) or []

        if needs_clarification:
            options = _state_clarification_options(state)
            yield event_clarify(options)
            return

        if node_errors and not feedback_present:
            # 노드 fallback edge 진입 — RFC 7807 503 ``analysis.node.failed``.
            from app.core.exceptions import AnalysisNodeError

            first_error = node_errors[0] if isinstance(node_errors, list) else None
            error_class = (
                get_state_field(first_error, "error_class", default="unknown")
                if first_error is not None
                else "unknown"
            )
            problem = AnalysisNodeError(str(error_class)).to_problem(instance=instance_path)
            yield event_error(problem)
            return

        # ④ feedback 정상 — 본문 청킹 + citation + done.
        payload = _state_to_done_payload(state, meal_id=meal_id)
        used_llm = payload.used_llm
        final_fit_score = payload.final_fit_score
        feedback_text = payload.feedback_text

        for chunk in chunk_text_for_streaming(
            feedback_text, chunk_chars=settings.analysis_token_chunk_chars
        ):
            yield event_token(chunk)
            token_count += 1
            await asyncio.sleep(settings.analysis_token_chunk_interval_ms / 1000.0)

        citations = _state_citations(state)
        for idx, citation in enumerate(citations):
            yield event_citation(idx, citation)
            citation_count += 1

        # ⑤ UPSERT *직전* — graceful(실패 swallow + persisted=False).
        fit_reason = _state_fit_reason(state)
        persisted = await _persist_done_payload(
            request,
            meal_id=meal_id,
            user_id=user_id,
            payload=payload,
            fit_reason=fit_reason,
            citations=citations,
        )

        yield event_done(payload)

    except TimeoutError:
        # outer wait_for 초과 — 사용자에게 일반화된 메시지(Story 3.6 패턴 정합).
        problem = ProblemDetail(
            title="Analysis Stream Timeout",
            status=504,
            detail="분석에 시간이 너무 오래 걸려요. 잠시 후 다시 시도해주세요",
            instance=instance_path,
            code="analysis.timeout",
        )
        yield event_error(problem)
    except BalanceNoteError as exc:
        yield event_error(exc.to_problem(instance=instance_path))
    except Exception as exc:  # noqa: BLE001 — 예상 외 예외 generator 안에서 차단.
        sentry_sdk.capture_exception(exc)
        yield event_error(_unexpected_problem(instance=instance_path))
    finally:
        # NFR-S5 — meal_id/mode/카운터/used_llm/score/latency/persisted만 forward.
        latency_ms = int((time.monotonic() - start) * 1000)
        log.info(
            log_event,
            meal_id=str(meal_id),
            mode="sse",
            phase_count=phase_count,
            token_count=token_count,
            citation_count=citation_count,
            used_llm=used_llm,
            final_fit_score=final_fit_score,
            latency_ms=latency_ms,
            persisted=persisted,
        )
        transaction.set_data("latency_ms", latency_ms)
        transaction.set_data("token_count", token_count)
        transaction.set_data("used_llm", used_llm)
        transaction.set_data("persisted", persisted)
        transaction.finish()


# --- Endpoints -----------------------------------------------------------------


@router.post(
    "/stream",
    responses={
        200: {"description": "SSE 스트림 응답 (text/event-stream)"},
        403: {"description": "PIPA basic 또는 automated_decision consent 미통과"},
        404: {"description": "meal 미존재 / 비소유 / soft-deleted (analysis.meal.not_found)"},
        429: {"description": "rate limit 초과 (analysis.rate_limit.exceeded)"},
        503: {"description": "checkpointer 미가동 (analysis.checkpointer.unavailable)"},
    },
    dependencies=[Depends(enforce_langgraph_rate_limit)],
)
async def stream_analysis(
    request: Request,
    body: AnalysisStreamRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
    _consent: Annotated[User, Depends(require_automated_decision_consent)],
) -> EventSourceResponse:
    """``POST /v1/analysis/stream`` — SSE 분석 스트림.

    흐름: 3 게이트 통과 → meal 소유권 검증 → analysis_service 가용성 확인 → SSE generator
    진입(progress → service.run → token chunk → citation → UPSERT → done).

    rate limit ``10/minute`` per-IP은 ``Depends(enforce_langgraph_rate_limit)``으로 wire.
    """
    meal = await _resolve_meal(db, meal_id=body.meal_id, user_id=user.id)
    service = _get_analysis_service(request)

    return EventSourceResponse(
        _run_and_stream(
            request,
            service=service,
            meal_id=meal.id,
            user_id=user.id,
            raw_text=meal.raw_text,
            clarify_value=None,
            log_event="analysis.sse.complete",
        ),
        headers={"X-Stream-Mode": "sse"},
        ping=_SSE_PING_INTERVAL_SECONDS,
    )


@router.post(
    "/clarify",
    responses={
        200: {"description": "SSE 스트림 응답 (clarify resume)"},
        403: {"description": "PIPA consent 미통과"},
        404: {"description": "meal 미존재 / 비소유"},
        422: {"description": "selected_value 빈 값 또는 형식 위반 (analysis.clarify.invalid)"},
        429: {"description": "rate limit 초과"},
        503: {"description": "checkpointer 미가동"},
    },
    dependencies=[Depends(enforce_langgraph_rate_limit)],
)
async def resume_clarification(
    request: Request,
    body: AnalysisClarifyRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
    _consent: Annotated[User, Depends(require_automated_decision_consent)],
) -> EventSourceResponse:
    """``POST /v1/analysis/clarify`` — Story 3.4 needs_clarification resume (SSE 응답).

    동일 ChatStreaming UI 재사용 위해 SSE 응답. ``analysis_service.aresume(thread_id,
    user_input={"selected_value": ...})`` 호출(Story 3.4 SOT). aresume 내부
    ``force_llm_parse=True`` 자동 주입.
    """
    meal = await _resolve_meal(db, meal_id=body.meal_id, user_id=user.id)
    service = _get_analysis_service(request)

    return EventSourceResponse(
        _run_and_stream(
            request,
            service=service,
            meal_id=meal.id,
            user_id=user.id,
            raw_text=None,
            clarify_value=body.selected_value,
            log_event="analysis.clarify.resume",
        ),
        headers={"X-Stream-Mode": "sse"},
    )


@router.get(
    "/{meal_id}",
    responses={
        200: {"description": "분석 상태 envelope (status: done|needs_clarification|error)"},
        202: {"description": "분석 진행 중 (status: in_progress) + Retry-After hint"},
        403: {"description": "PIPA basic consent 미통과 (automated_decision은 미요구)"},
        404: {"description": "meal 미존재 / 비소유"},
        429: {"description": "polling rate limit 초과 (analysis.rate_limit.exceeded)"},
        503: {"description": "checkpointer 미가동"},
    },
    dependencies=[Depends(enforce_poll_rate_limit)],
)
async def poll_analysis(
    request: Request,
    meal_id: Annotated[uuid.UUID, Path()],
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
) -> JSONResponse:
    """``GET /v1/analysis/{meal_id}`` — polling fallback (status discriminator envelope).

    응답 분기:
    - state.feedback 존재 → 200 + ``{"status": "done", "result": {...}}``
    - state.needs_clarification → 200 + ``{"status": "needs_clarification", "options": [...]}``
    - state.node_errors → 200 + ``{"status": "error", "problem": {...RFC 7807}}``
    - state empty + meal 존재 → 202 + ``{"status": "in_progress", "phase": "queued"}``

    *PIPA 자동화 의사결정 동의는 미요구* — polling = 단순 *조회*. PIPA Art.35 정보주체
    권리 정합(deps.py:182-187 SOT). 정상 분석 *호출*만 자동화 의사결정 동의 강제.
    """
    start = time.monotonic()
    # CR Wave 1 D3 — Sentry transaction for polling latency tracking(NFR-P1 attribution).
    transaction = sentry_sdk.start_transaction(
        op="analysis.sse.complete",
        name="analysis.poll.fetch",
    )
    transaction.set_tag("mode", "polling")
    try:
        meal = await _resolve_meal(db, meal_id=meal_id, user_id=user.id)
        service = _get_analysis_service(request)

        state = await service.aget_state(thread_id=f"meal:{meal.id}")

        needs_clarification = bool(get_state_field(state, "needs_clarification", default=False))
        feedback_present = get_state_field(state, "feedback", default=None) is not None
        node_errors = get_state_field(state, "node_errors", default=None) or []

        headers = {"X-Stream-Mode": "polling"}

        payload: dict[str, Any]
        status_code = 200

        if feedback_present and not needs_clarification:
            done_payload = _state_to_done_payload(state, meal_id=meal.id)
            payload = {"status": "done", "result": done_payload.model_dump(mode="json")}
        elif needs_clarification:
            options = _state_clarification_options(state)
            payload = {
                "status": "needs_clarification",
                "options": [{"label": o.label, "value": o.value} for o in options],
            }
        elif node_errors:
            from app.core.exceptions import AnalysisNodeError

            first_error = node_errors[0] if isinstance(node_errors, list) else None
            error_class = (
                get_state_field(first_error, "error_class", default="unknown")
                if first_error is not None
                else "unknown"
            )
            problem = AnalysisNodeError(str(error_class)).to_problem(instance=str(request.url.path))
            payload = {"status": "error", "problem": problem.to_response_dict()}
        else:
            # state empty(thread_id 미존재) + meal 존재 → in_progress(분석 미시작 또는 진행 중).
            # Retry-After 헤더 — settings polling interval(1.5초)을 math.ceil 정합 ceiling.
            # CR Wave 1 #4 — 이전 `int(x+0.5)` rounding bug 수정 (e.g. 2.4 → 2 undershoot).
            retry_after = max(1, math.ceil(settings.analysis_polling_interval_seconds))
            headers["Retry-After"] = str(retry_after)
            payload = {"status": "in_progress", "phase": "queued"}
            status_code = 202

        latency_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "analysis.poll.fetch",
            meal_id=str(meal.id),
            mode="polling",
            state_status=payload["status"],
            latency_ms=latency_ms,
        )
        transaction.set_data("latency_ms", latency_ms)
        transaction.set_data("state_status", payload["status"])
        return JSONResponse(content=payload, status_code=status_code, headers=headers)
    finally:
        transaction.finish()


__all__ = [
    "AnalysisClarifyRequest",
    "AnalysisStreamRequest",
    "enforce_langgraph_rate_limit",
    "enforce_poll_rate_limit",
    "router",
]
