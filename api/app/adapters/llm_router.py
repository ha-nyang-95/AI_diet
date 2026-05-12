"""Story 3.6 (Story 8.5 갱신) — LLM router: OpenAI 단독 + Redis cache + tenacity retry.

설계:
1. Redis 캐시 lookup (`cache_key`/`redis` 둘 다 non-None) → hit 시 LLM 호출 0회.
2. OpenAI `gpt-4o-mini` primary 호출 (3회 backoff, ``call_openai_feedback`` 내부 tenacity).
   영구 실패 시 ``LLMRouterExhaustedError`` raise (이전 Anthropic fallback 분기는 Story 8.5
   에서 제거 — 포트폴리오 scope에서 단일 provider 운영).
3. LLM 성공 시 Redis 캐시 write (graceful — 실패 시 log warning + 진행).
4. 전체 호출은 ``asyncio.wait_for(settings.llm_router_total_budget_seconds=25)`` outer
   deadline로 wrapping.

반환 3-tuple ``(FeedbackLLMOutput, used_llm_label, cache_hit)``. ``used_llm_label`` ∈
``{"gpt-4o-mini", "gpt-4o", "stub"}`` (cache hit 시 캐시 생성 시점의 라벨 보존 — legacy
``"claude"``/``"claude-haiku-4-5"`` 캐시 row는 graceful miss로 떨어지고 새 OpenAI 호출).

NFR-S5 — prompt / response 본문 raw 출력 X. used_llm + cache_hit + latency_ms만.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Final

import sentry_sdk
import structlog

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


# OpenAI 호출에서 router가 catch할 예외 set — adapter boundary에서 typed로 변환된 것만.
_OPENAI_HANDLED_TYPES: Final[tuple[type[BaseException], ...]] = (
    LLMRouterUnavailableError,
    LLMRouterPayloadInvalidError,
    *_OPENAI_TRANSIENT,
)

# Story 8.5 — Anthropic 제거 후 OpenAI 단독 라벨 set. legacy ``"claude"``/``"claude-haiku-4-5"``
# 라벨은 캐시 row에서 *역호환 read*만 허용 (graceful miss로 처리 — 사용자 입력 직후 새 LLM 호출).
_USED_LLM_OPENAI: Final[str] = "gpt-4o-mini"
_VALID_USED_LLM_LABELS: Final[frozenset[str]] = frozenset({"gpt-4o-mini", "gpt-4o", "stub"})


def _resolve_used_llm(model: str) -> str:
    """``settings.llm_main_model`` raw string → Literal 매핑.

    - ``"gpt-4o-mini"`` 또는 ``"gpt-4o-mini-*"`` → ``"gpt-4o-mini"`` (snapshot pin 호환).
    - ``"gpt-4o"`` 또는 ``"gpt-4o-*"`` (mini 미포함) → ``"gpt-4o"``.
    - 매칭 실패 → ``"stub"`` (LangSmith trace에서 mismatch 식별 가능).
    """
    if not model:
        return "stub"
    lowered = model.lower()
    if lowered.startswith("gpt-4o-mini"):
        return "gpt-4o-mini"
    if lowered.startswith("gpt-4o"):
        return "gpt-4o"
    return "stub"


# Redis network partition 시 indefinite hang 차단. ``redis.get``/``redis.set`` 자체 timeout이
# SDK 레벨에서 보장되지 않을 수 있어 router 차원에서 명시적 cap.
_REDIS_OP_TIMEOUT_SECONDS: Final[float] = 2.0


async def _try_cache_get(
    redis: redis_asyncio.Redis, cache_key: str
) -> tuple[FeedbackLLMOutput, str] | None:
    """캐시 lookup — graceful (예외 시 None 반환 + log warning).

    ``used_llm`` 필드를 ``_VALID_USED_LLM_LABELS``로 validate. cache poisoning / schema drift
    시 ValidationError로 노드가 폭발하지 않도록 graceful miss로 fallthrough. legacy ``"claude"``
    / ``"claude-haiku-4-5"`` 캐시 row는 *invalid label*로 미스 처리되어 새 OpenAI 호출.
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
    """캐시 write — graceful. 성공 시 True / 실패 시 False (log warning)."""
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


async def _call_openai_once(system: str, user: str) -> tuple[FeedbackLLMOutput, str]:
    """OpenAI 단일 호출 — adapter 내부 tenacity 3회 backoff. 최종 실패 시
    ``LLMRouterExhaustedError`` raise.

    Story 8.5 — 이전 Anthropic fallback 분기는 제거됨. ``_OPENAI_HANDLED_TYPES`` 안에 잡힌 모든
    영구/transient 최종 실패는 즉시 exhausted 신호 + Sentry capture_message + LLMRouterExhausted
    Error로 변환. ``generate_feedback`` 노드가 본 예외 catch 후 safe fallback 텍스트로 graceful
    응답.
    """
    try:
        output = await call_openai_feedback(
            system=system, user=user, response_format=FeedbackLLMOutput
        )
    except _OPENAI_HANDLED_TYPES as exc:
        sentry_sdk.capture_exception(exc)
        sentry_sdk.capture_message(
            "llm_router.exhausted",
            level="error",
            tags={"component": "llm_router", "stage": "final"},
        )
        raise LLMRouterExhaustedError(
            f"llm_router_exhausted (openai={type(exc).__name__})"
        ) from exc

    return output, _resolve_used_llm(settings.llm_main_model)


async def _route_feedback_inner(
    *,
    system: str,
    user: str,
    cache_key: str | None,
    redis: redis_asyncio.Redis | None,
) -> tuple[FeedbackLLMOutput, str, bool]:
    """Outer deadline 적용 전 inner 본 흐름 — cache lookup + OpenAI 호출 + cache write."""
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

    # 2. OpenAI 호출 (raises LLMRouterExhaustedError on permanent failure)
    output, used_llm = await _call_openai_once(system, user)

    # 3. Cache write (graceful)
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
    """LLM router — cache lookup → OpenAI 단독 호출 → cache write.

    반환 3-tuple ``(output, used_llm, cache_hit)``. cache_hit 시 ``used_llm``은 캐시 생성
    시점 라벨(legacy ``"claude"`` 캐시 row는 validate 단계에서 graceful miss로 떨어지고 새
    OpenAI 호출).

    오류 분기:
    - OpenAI 영구 실패 → ``LLMRouterExhaustedError`` raise + Sentry ``capture_message``.
    - cache 실패 → graceful pass-through(LLM 직접 호출 + write skip).
    - Outer deadline 초과(``settings.llm_router_total_budget_seconds=25``) →
      ``LLMRouterExhaustedError`` raise + Sentry ``capture_message``.

    Story 8.5 — 이전 Anthropic fallback 분기 제거. 포트폴리오 scope에서 단일 provider(OpenAI)
    + tenacity 3회 retry로 transient 처리. 영구 장애는 ``generate_feedback`` 노드의 safe
    fallback 텍스트로 graceful 응답.
    """
    try:
        return await asyncio.wait_for(
            _route_feedback_inner(system=system, user=user, cache_key=cache_key, redis=redis),
            timeout=settings.llm_router_total_budget_seconds,
        )
    except TimeoutError as exc:
        sentry_sdk.capture_message(
            "llm_router.outer_timeout",
            level="error",
            tags={"component": "llm_router", "stage": "outer_deadline"},
        )
        raise LLMRouterExhaustedError(
            f"llm_router_outer_timeout ({settings.llm_router_total_budget_seconds}s)"
        ) from exc


__all__ = ["route_feedback"]
