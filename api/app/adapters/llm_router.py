"""Story 3.6 — 듀얼 LLM router (OpenAI primary + Anthropic fallback + Redis cache, AC8/AC9/AC10).

설계 (architecture line 199, 528 정합):
1. Redis 캐시 lookup (`cache_key`/`redis` 둘 다 non-None) → hit 시 LLM 호출 0회.
2. OpenAI `gpt-4o-mini` primary 호출 (3회 backoff). 실패 시 Anthropic fallback 진입.
3. Anthropic `claude-haiku-4-5-20251001` fallback (3회 backoff). 실패 시 양쪽 exhausted —
   Sentry capture_message + ``LLMRouterExhaustedError`` raise.
4. LLM 성공 시 Redis 캐시 write (graceful — 실패 시 log warning + 진행).
5. 전체 호출은 ``asyncio.wait_for(settings.llm_router_total_budget_seconds=25)`` outer
   deadline로 wrapping (CR MJ-7+MJ-22 — 30s × 3 × 2 = 189s worst-case 차단).

반환 3-tuple ``(FeedbackLLMOutput, used_llm_label, cache_hit)``. ``used_llm_label`` ∈
``{"gpt-4o-mini", "claude"}`` (cache hit 시 캐시 생성 시점의 라벨 보존).

NFR-S5 — prompt / response 본문 raw 출력 X. used_llm + cache_hit + latency_ms만.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Final

import sentry_sdk
import structlog

from app.adapters.anthropic_adapter import (
    _TRANSIENT_RETRY_TYPES as _ANTHROPIC_TRANSIENT,
)
from app.adapters.anthropic_adapter import (
    call_claude_feedback,
)
from app.adapters.openai_adapter import (
    _TRANSIENT_RETRY_TYPES as _OPENAI_TRANSIENT,
)
from app.adapters.openai_adapter import (
    call_openai_feedback,
)
from app.core.config import settings
from app.core.exceptions import (
    LLMRouterExhaustedError,
    LLMRouterPayloadInvalidError,
    LLMRouterUnavailableError,
)
from app.graph.state import FeedbackLLMOutput

if TYPE_CHECKING:
    import redis.asyncio as redis_asyncio

log = structlog.get_logger(__name__)


# CR MJ-1+MJ-12 — `RetryError`는 `reraise=True` adapter에서 raise되지 않음(dead code 제거).
# `MealOCRUnavailableError` cross-domain 예외는 openai_adapter boundary에서
# `LLMRouterUnavailableError`로 translate (CR D1 정합) → router는 typed router 예외와
# transient subset만 catch.
_OPENAI_HANDLED_TYPES: Final[tuple[type[BaseException], ...]] = (
    LLMRouterUnavailableError,
    LLMRouterPayloadInvalidError,
    *_OPENAI_TRANSIENT,
)
_ANTHROPIC_HANDLED_TYPES: Final[tuple[type[BaseException], ...]] = (
    LLMRouterUnavailableError,
    LLMRouterPayloadInvalidError,
    *_ANTHROPIC_TRANSIENT,
)

_USED_LLM_OPENAI: Final[str] = "gpt-4o-mini"
_USED_LLM_CLAUDE: Final[str] = "claude"
_VALID_USED_LLM_LABELS: Final[frozenset[str]] = frozenset({_USED_LLM_OPENAI, _USED_LLM_CLAUDE})

# CR mn-5 — Redis network partition 시 indefinite hang 차단. ``redis.get``/``redis.set``
# 자체 timeout이 SDK 레벨에서 보장되지 않을 수 있어 router 차원에서 명시적 cap.
_REDIS_OP_TIMEOUT_SECONDS: Final[float] = 2.0


async def _try_cache_get(
    redis: redis_asyncio.Redis, cache_key: str
) -> tuple[FeedbackLLMOutput, str] | None:
    """캐시 lookup — graceful (예외 시 None 반환 + log warning).

    CR MJ-4 — ``used_llm`` 필드를 ``_VALID_USED_LLM_LABELS``로 validate. cache poisoning /
    schema drift 시 ValidationError로 노드가 폭발하지 않도록 graceful miss로 fallthrough.
    CR mn-5 — ``redis.get`` 자체에 ``asyncio.wait_for`` 외부 timeout 적용.
    """
    try:
        cached_raw = await asyncio.wait_for(redis.get(cache_key), timeout=_REDIS_OP_TIMEOUT_SECONDS)
    except (TimeoutError, Exception) as exc:  # noqa: BLE001
        log.warning("llm_router.cache_read_failed", error=type(exc).__name__)
        return None
    if cached_raw is None:
        return None
    try:
        payload = json.loads(cached_raw)
        output = FeedbackLLMOutput.model_validate(payload["output"])
        used_llm = payload["used_llm"]
    except Exception as exc:  # noqa: BLE001
        # 캐시 corruption 또는 schema drift — graceful miss.
        log.warning("llm_router.cache_deserialize_failed", error=type(exc).__name__)
        return None
    if not isinstance(used_llm, str) or used_llm not in _VALID_USED_LLM_LABELS:
        log.warning(
            "llm_router.cache_used_llm_invalid",
            value_class=type(used_llm).__name__,
        )
        return None
    return output, used_llm


async def _try_cache_set(
    redis: redis_asyncio.Redis,
    cache_key: str,
    output: FeedbackLLMOutput,
    used_llm: str,
) -> bool:
    """캐시 write — graceful. 성공 시 True / 실패 시 False (log warning).

    CR mn-4 — ``ensure_ascii=False`` 적용 → 한국어 본문이 ``\\uXXXX`` 이스케이프되어 cache
    value ~3× 부풀던 회귀 차단(Redis 메모리 + payload 비용).
    CR mn-5 — ``redis.set`` 자체에 ``asyncio.wait_for`` 외부 timeout 적용.
    """
    try:
        payload = {
            "output": output.model_dump(mode="json"),
            "used_llm": used_llm,
        }
        await asyncio.wait_for(
            redis.set(
                cache_key,
                json.dumps(payload, ensure_ascii=False),
                ex=settings.llm_cache_ttl_seconds,
            ),
            timeout=_REDIS_OP_TIMEOUT_SECONDS,
        )
        return True
    except (TimeoutError, Exception) as exc:  # noqa: BLE001
        log.warning("llm_router.cache_write_failed", error=type(exc).__name__)
        return False


async def _openai_then_anthropic(system: str, user: str) -> tuple[FeedbackLLMOutput, str]:
    """OpenAI primary → Anthropic fallback. 양쪽 실패 시 ``LLMRouterExhaustedError``.

    CR mn-21 — 이전 ``output: FeedbackLLMOutput | None = None`` + ``assert``-pattern을
    helper로 분리해 control flow상 None 가능성 자체 제거(타입 narrowing 명확화 +
    ``python -O`` 안전).
    """
    openai_exc: BaseException | None = None
    try:
        primary = await call_openai_feedback(
            system=system, user=user, response_format=FeedbackLLMOutput
        )
    except _OPENAI_HANDLED_TYPES as exc:
        openai_exc = exc
        sentry_sdk.capture_exception(exc)
    else:
        return primary, _USED_LLM_OPENAI

    # OpenAI 실패 → Anthropic fallback.
    try:
        fallback = await call_claude_feedback(
            system=system, user=user, response_format=FeedbackLLMOutput
        )
    except _ANTHROPIC_HANDLED_TYPES as anthropic_exc:
        sentry_sdk.capture_exception(anthropic_exc)
        sentry_sdk.capture_message(
            "dual_llm_router.exhausted",
            level="error",
            tags={"component": "llm_router", "stage": "final"},
        )
        openai_class = type(openai_exc).__name__ if openai_exc else "n/a"
        raise LLMRouterExhaustedError(
            f"dual_llm_router_exhausted (openai={openai_class}, "
            f"anthropic={type(anthropic_exc).__name__})"
        ) from anthropic_exc

    return fallback, _USED_LLM_CLAUDE


async def _route_feedback_inner(
    *,
    system: str,
    user: str,
    cache_key: str | None,
    redis: redis_asyncio.Redis | None,
) -> tuple[FeedbackLLMOutput, str, bool]:
    """Outer deadline 적용 전 inner 본 흐름 — cache + dual-LLM + cache write."""
    start = time.monotonic()

    # 1. Cache lookup (graceful)
    if cache_key is not None and redis is not None:
        cached = await _try_cache_get(redis, cache_key)
        if cached is not None:
            cached_output, cached_used_llm = cached
            latency_ms = int((time.monotonic() - start) * 1000)
            log.info(
                "llm_router.complete",
                used_llm=cached_used_llm,
                cache_hit=True,
                latency_ms=latency_ms,
                cache_write_ok=False,
            )
            return cached_output, cached_used_llm, True

    # 2-3. OpenAI primary → Anthropic fallback (raises LLMRouterExhaustedError on dual fail)
    output, used_llm = await _openai_then_anthropic(system, user)

    # 4. Cache write (graceful)
    cache_write_ok = False
    if cache_key is not None and redis is not None:
        cache_write_ok = await _try_cache_set(redis, cache_key, output, used_llm)

    latency_ms = int((time.monotonic() - start) * 1000)
    log.info(
        "llm_router.complete",
        used_llm=used_llm,
        cache_hit=False,
        latency_ms=latency_ms,
        cache_write_ok=cache_write_ok,
    )
    return output, used_llm, False


async def route_feedback(
    *,
    system: str,
    user: str,
    cache_key: str | None,
    redis: redis_asyncio.Redis | None,
) -> tuple[FeedbackLLMOutput, str, bool]:
    """듀얼 LLM router — cache lookup → OpenAI primary → Anthropic fallback → cache write.

    반환 3-tuple ``(output, used_llm, cache_hit)``. cache_hit 시 ``used_llm``은 캐시 생성
    시점 라벨(현재 호출이 OpenAI 가용해도 캐시가 ``"claude"``이면 그대로 반환 — Story 3.8
    LangSmith 분석 정합).

    오류 분기:
    - 양쪽 LLM 실패 → ``LLMRouterExhaustedError`` raise + Sentry ``capture_message``.
    - 한쪽 LLM 성공 → ``capture_exception(other)`` breadcrumb 보존(failed LLM 별도 알림).
    - cache 실패 → graceful pass-through(LLM 직접 호출 + write skip).
    - Outer deadline 초과(``settings.llm_router_total_budget_seconds=25``) →
      ``LLMRouterExhaustedError`` raise + Sentry ``capture_message`` (CR MJ-7+MJ-22).
    """
    try:
        return await asyncio.wait_for(
            _route_feedback_inner(system=system, user=user, cache_key=cache_key, redis=redis),
            timeout=settings.llm_router_total_budget_seconds,
        )
    except TimeoutError as exc:
        sentry_sdk.capture_message(
            "dual_llm_router.outer_timeout",
            level="error",
            tags={"component": "llm_router", "stage": "outer_deadline"},
        )
        raise LLMRouterExhaustedError(
            f"dual_llm_router_outer_timeout ({settings.llm_router_total_budget_seconds}s)"
        ) from exc


__all__ = ["route_feedback"]
