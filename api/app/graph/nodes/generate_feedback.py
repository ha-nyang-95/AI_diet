"""Story 3.6 — `generate_feedback` 노드 실 인용형 피드백 + 광고 가드 + 듀얼 LLM router.

Story 3.3 stub(``text="(분석 준비 중)"``) 폐지 → 12단계 실 흐름:
1. profile / parsed_items / fit_evaluation coerce + 부재 시 safe fallback.
2. 가이드라인 검색 (HNSW + applicable_health_goals 필터).
3. cache_key 빌드 (NFC raw_text + profile_hash + model + chunks fingerprint).
4. system + user 프롬프트 빌드.
5. router 호출 (cache lookup → OpenAI primary → Anthropic fallback).
6. 인용 검증 + 누락 시 1회 재생성 + 최종 누락 시 안전 워딩 치환.
7. 광고 가드 + 위반 시 1회 재생성 + 최종 위반 시 안전 워딩 치환.
8. 출력 구조 검증 + 부재 시 1회 재생성 + 최종 부재 시 fallback append.
9. 매 regen 후 잔존 위반은 non-regen fallback(append_safe_citation / apply_replacements /
   append_safe_action_section)으로 정리 — text/llm_out divergence 차단(CR A2).
10. citations 리스트 빌드 (cited_chunk_indices → Citation).
11. used_llm Literal pre-validate (CR mn-23).
12. FeedbackOutput 반환.

NFR-S5 — 진입/완료 INFO 로그 1줄. raw_text / parsed_items name / allergies / weight /
height / 인용 본문 raw 출력 X.
"""

from __future__ import annotations

import hashlib
import math
import time
import unicodedata
from typing import Any, cast

import sentry_sdk
import structlog
from pydantic import ValidationError

from app.adapters.llm_router import route_feedback
from app.core.config import settings
from app.core.exceptions import LLMRouterExhaustedError
from app.domain.ad_expression_guard import (
    apply_replacements as _ad_apply_replacements,
)
from app.domain.ad_expression_guard import (
    find_violations as _ad_find_violations,
)
from app.graph.deps import NodeDeps
from app.graph.nodes._feedback_postprocess import (
    SAFE_ACTION_FALLBACK_TEXT,
    append_safe_action_section,
    append_safe_citation,
    has_required_sections,
    validate_citations,
)
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.prompts.feedback import build_system_prompt, build_user_prompt
from app.graph.state import (
    Citation,
    FeedbackLLMOutput,
    FeedbackOutput,
    FitEvaluation,
    FoodItem,
    KnowledgeChunkContext,
    MealAnalysisState,
    UserProfileSnapshot,
)
from app.rag.guidelines.search import search_guideline_chunks

log = structlog.get_logger()

_VALID_USED_LLM_LABELS = frozenset({"gpt-4o-mini", "claude"})


# ---------------------------------------------------------------------------
# state coerce 헬퍼 (Story 3.5 evaluate_fit 패턴 정합)
#
# CR MJ-15 — 이전 ``except Exception``은 ValidationError(예상)와 unexpected error(버그)를
# 동일하게 stub fallback으로 mask해 schema 마이그레이션 류 회귀를 silent로 처리. 분리:
# - ValidationError → log.warning + return None (정상 fallback 분기).
# - 그 외 Exception → ``sentry_sdk.capture_exception`` 후 None (alerting 가능).
# ---------------------------------------------------------------------------


def _coerce_profile(raw: object) -> UserProfileSnapshot | None:
    if raw is None:
        return None
    if isinstance(raw, UserProfileSnapshot):
        return raw
    if isinstance(raw, dict):
        try:
            return UserProfileSnapshot(**raw)
        except ValidationError as exc:
            log.warning(
                "generate_feedback.coerce_failed",
                kind="profile",
                error=type(exc).__name__,
            )
            return None
        except Exception as exc:  # noqa: BLE001 — unexpected → alert
            sentry_sdk.capture_exception(exc)
            log.warning(
                "generate_feedback.coerce_unexpected",
                kind="profile",
                error=type(exc).__name__,
            )
            return None
    return None


def _coerce_food_item(raw: object) -> FoodItem | None:
    if isinstance(raw, FoodItem):
        return raw
    if isinstance(raw, dict):
        try:
            return FoodItem(**raw)
        except ValidationError as exc:
            log.warning(
                "generate_feedback.coerce_failed",
                kind="food_item",
                error=type(exc).__name__,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            sentry_sdk.capture_exception(exc)
            log.warning(
                "generate_feedback.coerce_unexpected",
                kind="food_item",
                error=type(exc).__name__,
            )
            return None
    return None


def _coerce_fit_evaluation(raw: object) -> FitEvaluation | None:
    if raw is None:
        return None
    if isinstance(raw, FitEvaluation):
        return raw
    if isinstance(raw, dict):
        try:
            return FitEvaluation(**raw)
        except ValidationError as exc:
            log.warning(
                "generate_feedback.coerce_failed",
                kind="fit_evaluation",
                error=type(exc).__name__,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            sentry_sdk.capture_exception(exc)
            log.warning(
                "generate_feedback.coerce_unexpected",
                kind="fit_evaluation",
                error=type(exc).__name__,
            )
            return None
    return None


# ---------------------------------------------------------------------------
# 캐시 키 빌더
# ---------------------------------------------------------------------------


def _build_profile_hash(profile: UserProfileSnapshot) -> str:
    """프로필 해시 — Story 3.6 AC10 cache key 입력 (sha256). 입력 형식:
    ``f"{user_id}|{health_goal}|{age}|{weight_kg:.1f}|{height_cm:.1f}|{activity_level}|{sorted_allergies_csv}"``.

    CR MJ-10 — allergy 문자열 NFC 정규화 (NFD 입력의 cache miss 회귀 차단).
    """
    sorted_allergies = ",".join(sorted(unicodedata.normalize("NFC", a) for a in profile.allergies))
    body = (
        f"{profile.user_id}|{profile.health_goal}|{profile.age}|"
        f"{profile.weight_kg:.1f}|{profile.height_cm:.1f}|"
        f"{profile.activity_level}|{sorted_allergies}"
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _build_chunks_fingerprint(chunks: list[KnowledgeChunkContext]) -> str:
    """chunks 식별 지문 — sha256(sorted (source, doc_title, year))[:16].

    CR A1+MJ-20=a — chunks 변경(seed 갱신, retrieval 결과 shift) 시 cache 자동 invalidate
    → 과거 ``cited_chunk_indices``가 오늘 chunks와 misalign되는 회귀 차단.
    """
    parts = sorted(
        f"{c.source}|{c.doc_title}|{c.published_year if c.published_year is not None else 0}"
        for c in chunks
    )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def _build_cache_key(
    raw_text: str,
    profile: UserProfileSnapshot,
    chunks: list[KnowledgeChunkContext],
) -> str | None:
    """cache:llm:{sha256(NFC raw_text|profile_hash|model|chunks_fp)} — 빈 raw_text 시 None.

    CR MJ-11 — weight_kg / height_cm가 NaN/Inf인 경우 ``f"{x:.1f}"``가 ``"nan"``/``"inf"``
    문자열로 collide → 모든 비유한 프로필이 같은 key 공유. 본 함수에서 None 반환(캐시 우회)
    으로 차단.
    CR MJ-20=a — model id 추가 → env override로 model 갱신 시 stale-cache 차단.
    """
    raw_text_norm = unicodedata.normalize("NFC", raw_text or "").strip()
    if not raw_text_norm:
        return None
    if not (math.isfinite(profile.weight_kg) and math.isfinite(profile.height_cm)):
        log.warning(
            "generate_feedback.cache_key_skipped_non_finite",
            user_id=profile.user_id,
        )
        return None
    profile_hash = _build_profile_hash(profile)
    chunks_fp = _build_chunks_fingerprint(chunks)
    body = f"{raw_text_norm}|{profile_hash}|{settings.llm_main_model}|{chunks_fp}"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"cache:llm:{digest}"


# ---------------------------------------------------------------------------
# safe fallback 빌더
# ---------------------------------------------------------------------------


def _safe_fallback(
    text: str,
    *,
    citations: list[Citation] | None = None,
) -> dict[str, Any]:
    """`FeedbackOutput(used_llm="stub")` model_dump 반환 dict."""
    return {
        "feedback": FeedbackOutput(
            text=text,
            citations=citations if citations is not None else [],
            used_llm="stub",
        ).model_dump()
    }


def _build_citations(
    llm_out: FeedbackLLMOutput, chunks: list[KnowledgeChunkContext]
) -> list[Citation]:
    """LLM의 cited_chunk_indices → 실 Citation 리스트(out-of-range 인덱스 자동 제외)."""
    citations: list[Citation] = []
    for idx in llm_out.cited_chunk_indices:
        if 0 <= idx < len(chunks):
            chunk = chunks[idx]
            citations.append(
                Citation(
                    source=chunk.source,
                    doc_title=chunk.doc_title,
                    published_year=chunk.published_year,
                )
            )
    return citations


def _harden_after_regen(
    text: str,
    llm_out: FeedbackLLMOutput,
    chunks: list[KnowledgeChunkContext],
    *,
    skip_citation: bool = False,
    skip_ad: bool = False,
    skip_structure: bool = False,
) -> tuple[str, FeedbackLLMOutput, int]:
    """CR A2 — regen 후 다른 규칙의 잔존 위반을 *비-regen* fallback으로 정리.

    각 규칙당 1회 regen 한도(spec) 안에서, regen이 한 규칙은 고치고 다른 규칙을 회귀시키는
    경우 in-line fallback으로 정리. 반환 `(text, llm_out, ad_replaced_count)`.
    """
    ad_replaced = 0
    if not skip_ad:
        violations = _ad_find_violations(text)
        if violations:
            text = _ad_apply_replacements(text)
            ad_replaced = len(violations)
            llm_out = FeedbackLLMOutput(
                text=text,
                cited_chunk_indices=list(llm_out.cited_chunk_indices),
            )
    if not skip_citation and not validate_citations(text, chunks):
        text = append_safe_citation(text, chunks)
        # ``append_safe_citation``이 chunks 있을 때 chunks[0] 메타로 인용 본문을 만드므로
        # cited_chunk_indices=[0]이 본문 인용과 정합 (CR A3).
        llm_out = FeedbackLLMOutput(
            text=text,
            cited_chunk_indices=[0] if chunks else [],
        )
    if not skip_structure and not has_required_sections(text):
        text = append_safe_action_section(text)
        llm_out = FeedbackLLMOutput(
            text=text,
            cited_chunk_indices=list(llm_out.cited_chunk_indices),
        )
    return text, llm_out, ad_replaced


# ---------------------------------------------------------------------------
# 노드 본체
# ---------------------------------------------------------------------------


# CR E1 — dual_llm_exhausted safe fallback도 AC6 ## 평가 + ## 다음 행동 강제(이전 헤더
# 누락이 pipeline 테스트 우연 통과로 가려지던 회귀 차단).
_DUAL_EXHAUSTED_TEXT = (
    "## 평가\nAI 서비스 일시 장애가 발생해 식사 분석을 마치지 못했습니다.\n\n"
    f"## 다음 행동\n잠시 후 다시 시도해주세요. {SAFE_ACTION_FALLBACK_TEXT}"
)
_NO_GUIDELINE_FALLBACK_TEXT = (
    "## 평가\n한국 1차 출처 가이드라인을 찾지 못해 일반 식사 균형 안내만 제공합니다.\n\n"
    f"## 다음 행동\n{SAFE_ACTION_FALLBACK_TEXT}"
)
# CR mn-28=a — chunks=[] 분기에서 KDRIs 기본 cite 1줄 추가(spec Task 10.2.3 충실).
_NO_GUIDELINE_FALLBACK_CITATION = Citation(
    source="보건복지부",
    doc_title="2020 한국인 영양소 섭취기준",
    published_year=2020,
)


@_node_wrapper("generate_feedback")
async def generate_feedback(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
    start = time.monotonic()

    profile = _coerce_profile(state.get("user_profile"))
    fit_evaluation = _coerce_fit_evaluation(state.get("fit_evaluation"))
    parsed_raw = state.get("parsed_items") or []
    parsed_items: list[FoodItem] = [
        item for item in (_coerce_food_item(it) for it in parsed_raw) if item is not None
    ]
    raw_text = state.get("raw_text", "") or ""

    if profile is None or fit_evaluation is None or not parsed_items:
        latency_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "node.generate_feedback.complete",
            used_llm="stub",
            cache_hit=False,
            regen_attempts=0,
            violations_replaced_count=0,
            citations_count=0,
            text_length=0,
            latency_ms=latency_ms,
            reason="incomplete_state",
        )
        return _safe_fallback("식사 정보가 부족해 분석을 마치지 못했어요. 다시 입력해주세요.")

    # 가이드라인 검색
    query_text = f"{profile.health_goal} " + " ".join(it.name for it in parsed_items)
    chunks: list[KnowledgeChunkContext] = []
    try:
        async with deps.session_maker() as session:
            chunks = await search_guideline_chunks(
                session,
                health_goal=profile.health_goal,
                query_text=query_text,
                top_k=5,
            )
    except Exception as exc:  # noqa: BLE001
        # DB 장애 / 임베딩 어댑터 장애 → 가이드라인 미발견 fallback (LLM은 진행 X — 인용 보장 불가).
        log.warning(
            "generate_feedback.guideline_search_failed",
            error=type(exc).__name__,
        )
        chunks = []

    if not chunks:
        latency_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "node.generate_feedback.complete",
            used_llm="stub",
            cache_hit=False,
            regen_attempts=0,
            violations_replaced_count=0,
            citations_count=1,
            text_length=len(_NO_GUIDELINE_FALLBACK_TEXT),
            latency_ms=latency_ms,
            reason="no_guideline_chunks",
        )
        # CR mn-28=a — KDRIs 기본 1줄 cite를 본문에 append + Citation 카드도 채움.
        text_with_cite = (
            _NO_GUIDELINE_FALLBACK_TEXT + f"\n\n(출처: {_NO_GUIDELINE_FALLBACK_CITATION.source}, "
            f"{_NO_GUIDELINE_FALLBACK_CITATION.doc_title}, "
            f"{_NO_GUIDELINE_FALLBACK_CITATION.published_year})"
        )
        return _safe_fallback(
            text_with_cite,
            citations=[_NO_GUIDELINE_FALLBACK_CITATION],
        )

    # cache_key + 프롬프트
    cache_key = _build_cache_key(raw_text, profile, chunks)
    system = build_system_prompt(knowledge_chunks=chunks)
    user = build_user_prompt(
        fit_evaluation=fit_evaluation,
        parsed_items=parsed_items,
        user_profile=profile,
        raw_text=raw_text,
    )

    # router 호출
    regen_attempts = 0
    accumulated_notes: list[str] = []  # CR MJ-23=a — 누적 regen 지시
    try:
        llm_out, used_llm, cache_hit = await route_feedback(
            system=system, user=user, cache_key=cache_key, redis=deps.redis
        )
    except LLMRouterExhaustedError:
        # AC9 — 양쪽 LLM 실패 시 노드 정상 종료(safe fallback) + _node_wrapper fallback 미진입.
        latency_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "node.generate_feedback.complete",
            used_llm="stub",
            cache_hit=False,
            regen_attempts=0,
            violations_replaced_count=0,
            citations_count=0,
            text_length=len(_DUAL_EXHAUSTED_TEXT),
            latency_ms=latency_ms,
            reason="dual_llm_exhausted",
        )
        # CR E1 — ## 평가 + ## 다음 행동 헤더 보장.
        return _safe_fallback(_DUAL_EXHAUSTED_TEXT)

    text = llm_out.text

    def _accumulated_user(note: str) -> str:
        accumulated_notes.append(note)
        return user + "\n\n[재요청 누적]\n" + "\n".join(f"- {n}" for n in accumulated_notes)

    # AC2 — 인용 검증 + 1회 재생성 + 안전 워딩 fallback
    violations_replaced_count = 0
    if not validate_citations(text, chunks):
        regen_attempts += 1
        regen_user_citation = _accumulated_user(
            "이전 응답에 출처 인용이 누락되었습니다. 모든 권고에 (출처: 기관명, 문서명, 연도) "
            "3-tuple 패턴을 포함하세요."
        )
        try:
            # CR Gemini G4 — regen이 fallback LLM을 사용한 경우 final telemetry attribution
            # 정확화 (이전 ``_, _, _``는 used_llm을 폐기 → primary가 죽고 Anthropic이
            # 응답해도 log/FeedbackOutput에 ``gpt-4o-mini``가 박힘).
            regen_out, used_llm, _ = await route_feedback(
                system=system,
                user=regen_user_citation,
                cache_key=None,  # 재생성은 캐시 우회
                redis=deps.redis,
            )
            if validate_citations(regen_out.text, chunks):
                llm_out = regen_out
                text = regen_out.text
            else:
                text = append_safe_citation(regen_out.text, chunks)
                llm_out = FeedbackLLMOutput(
                    text=text,
                    cited_chunk_indices=[0] if chunks else [],
                )
        except LLMRouterExhaustedError:
            text = append_safe_citation(text, chunks)
            llm_out = FeedbackLLMOutput(
                text=text,
                cited_chunk_indices=[0] if chunks else [],
            )

    # AC4 — 광고 가드 + 1회 재생성 + 안전 워딩 치환
    violations = _ad_find_violations(text)
    if violations:
        regen_attempts += 1
        regen_user_ad = _accumulated_user(
            "이전 응답에 식약처 광고 금지 표현(진단/치료/예방/완화/처방)이 포함되었습니다. "
            "안전 워딩(안내/관리/도움이 될 수 있는/참고/권장)으로 다시 작성하세요."
        )
        try:
            # CR Gemini G5 — regen used_llm 캡처 (fallback 발동 시 attribution 정확화).
            regen_out, used_llm, _ = await route_feedback(
                system=system,
                user=regen_user_ad,
                cache_key=None,
                redis=deps.redis,
            )
            new_violations = _ad_find_violations(regen_out.text)
            if not new_violations:
                # CR A2 — regen success: text/llm_out 동기화 + 다른 규칙 잔존 가드.
                text, llm_out, _extra = _harden_after_regen(
                    regen_out.text, regen_out, chunks, skip_ad=True
                )
            else:
                # regen 후에도 위반 → in-line apply_replacements + 잔존 가드.
                replaced_text = _ad_apply_replacements(regen_out.text)
                violations_replaced_count += len(new_violations)
                text, llm_out, _extra = _harden_after_regen(
                    replaced_text,
                    FeedbackLLMOutput(
                        text=replaced_text,
                        cited_chunk_indices=list(regen_out.cited_chunk_indices),
                    ),
                    chunks,
                    skip_ad=True,
                )
        except LLMRouterExhaustedError:
            replaced_text = _ad_apply_replacements(text)
            violations_replaced_count += len(violations)
            text, llm_out, _extra = _harden_after_regen(
                replaced_text,
                FeedbackLLMOutput(
                    text=replaced_text,
                    cited_chunk_indices=list(llm_out.cited_chunk_indices),
                ),
                chunks,
                skip_ad=True,
            )

    # AC6 — 출력 구조 검증 + 1회 재생성 + fallback append
    if not has_required_sections(text):
        regen_attempts += 1
        regen_user_structure = _accumulated_user(
            "이전 응답에 ## 평가 또는 ## 다음 행동 섹션이 누락되었습니다. "
            "두 섹션을 모두 포함해 다시 작성하세요."
        )
        try:
            # CR Gemini G6 — regen used_llm 캡처 (fallback 발동 시 attribution 정확화).
            regen_out, used_llm, _ = await route_feedback(
                system=system,
                user=regen_user_structure,
                cache_key=None,
                redis=deps.redis,
            )
            if has_required_sections(regen_out.text):
                # CR A2 — regen success: text/llm_out 동기화 + 다른 규칙 잔존 가드.
                text, llm_out, extra_replaced = _harden_after_regen(
                    regen_out.text, regen_out, chunks, skip_structure=True
                )
                violations_replaced_count += extra_replaced
            else:
                text = append_safe_action_section(regen_out.text)
                llm_out = FeedbackLLMOutput(
                    text=text,
                    cited_chunk_indices=list(regen_out.cited_chunk_indices),
                )
                # 다른 규칙 잔존 가드(headers는 이제 보장).
                text, llm_out, extra_replaced = _harden_after_regen(
                    text, llm_out, chunks, skip_structure=True
                )
                violations_replaced_count += extra_replaced
        except LLMRouterExhaustedError:
            text = append_safe_action_section(text)
            llm_out = FeedbackLLMOutput(
                text=text,
                cited_chunk_indices=list(llm_out.cited_chunk_indices),
            )

    # citations 빌드
    citations = _build_citations(llm_out, chunks)

    # CR mn-23 — used_llm Literal pre-validate(``cast(Any)``가 type-check만 우회 — 런타임
    # ValidationError로 노드가 폭발하는 경로 차단).
    if used_llm not in _VALID_USED_LLM_LABELS:
        log.warning(
            "generate_feedback.used_llm_invalid",
            value=used_llm,
        )
        used_llm = "stub"

    feedback = FeedbackOutput(
        text=text,
        citations=citations,
        used_llm=cast(Any, used_llm),
    )

    latency_ms = int((time.monotonic() - start) * 1000)
    log.info(
        "node.generate_feedback.complete",
        used_llm=used_llm,
        cache_hit=cache_hit,
        regen_attempts=regen_attempts,
        violations_replaced_count=violations_replaced_count,
        citations_count=len(citations),
        text_length=len(text),
        latency_ms=latency_ms,
    )
    return {"feedback": feedback.model_dump()}
