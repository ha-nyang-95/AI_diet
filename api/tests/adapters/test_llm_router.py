"""Story 3.6 (Story 8.5 갱신) — `app.adapters.llm_router.route_feedback` 단위 테스트.

Story 8.5에서 Anthropic fallback 제거 후 OpenAI 단독 router로 단순화. 테스트도 OpenAI 단일
호출 + cache + outer deadline + legacy 'claude' 캐시 row graceful miss로 재구성.

LLM 어댑터(`call_openai_feedback`) monkeypatch — 실 SDK 호출 X.
Sentry capture_message는 monkeypatch로 호출 횟수 검증.
"""

from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import AsyncMock

import httpx
import openai
import pytest

from app.adapters.llm_router import route_feedback
from app.core.exceptions import (
    LLMRouterExhaustedError,
    LLMRouterPayloadInvalidError,
    LLMRouterUnavailableError,
)
from app.graph.state import FeedbackLLMOutput

_LLM_ROUTER_MODULE = sys.modules["app.adapters.llm_router"]


@pytest.fixture
def fake_redis_hit() -> AsyncMock:
    """캐시 hit 시뮬레이션 — `redis.get`이 직렬화된 payload 반환 (현 valid label)."""
    redis = AsyncMock()
    payload = {
        "output": FeedbackLLMOutput(text="cached", cited_chunk_indices=[]).model_dump(mode="json"),
        "used_llm": "gpt-4o-mini",
    }
    redis.get = AsyncMock(return_value=json.dumps(payload))
    redis.set = AsyncMock()
    return redis


@pytest.fixture
def fake_redis_legacy_claude() -> AsyncMock:
    """legacy 캐시 row — used_llm='claude' (Anthropic 시절). graceful miss 정합."""
    redis = AsyncMock()
    payload = {
        "output": FeedbackLLMOutput(text="legacy", cited_chunk_indices=[]).model_dump(mode="json"),
        "used_llm": "claude",
    }
    redis.get = AsyncMock(return_value=json.dumps(payload))
    redis.set = AsyncMock()
    return redis


@pytest.fixture
def fake_redis_miss() -> AsyncMock:
    """캐시 miss + write 성공 — `redis.get` None / `redis.set` 정상."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    return redis


async def test_cache_hit_zero_llm_calls(
    fake_redis_hit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1) cache hit (valid label) → LLM 0회 호출 + 캐시 값 그대로 반환."""
    openai_mock = AsyncMock()
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)

    output, used_llm, cache_hit = await route_feedback(
        system="s", user="u", cache_key="k", redis=fake_redis_hit
    )
    assert cache_hit is True
    assert used_llm == "gpt-4o-mini"
    assert output.text == "cached"
    openai_mock.assert_not_called()


async def test_legacy_claude_cache_row_graceful_miss(
    fake_redis_legacy_claude: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story 8.5 — legacy 'claude' 캐시 row는 invalid label로 처리되어 graceful miss + 새 호출."""
    openai_mock = AsyncMock(return_value=FeedbackLLMOutput(text="fresh", cited_chunk_indices=[]))
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)

    output, used_llm, cache_hit = await route_feedback(
        system="s", user="u", cache_key="k", redis=fake_redis_legacy_claude
    )
    assert cache_hit is False
    assert used_llm == "gpt-4o-mini"
    assert output.text == "fresh"
    openai_mock.assert_awaited_once()


async def test_cache_miss_openai_success(
    fake_redis_miss: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2) cache miss → OpenAI 성공 → cache write + used_llm=gpt-4o-mini."""
    openai_mock = AsyncMock(return_value=FeedbackLLMOutput(text="primary", cited_chunk_indices=[]))
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)

    output, used_llm, cache_hit = await route_feedback(
        system="s", user="u", cache_key="k", redis=fake_redis_miss
    )
    assert cache_hit is False
    assert used_llm == "gpt-4o-mini"
    assert output.text == "primary"
    openai_mock.assert_awaited_once()
    fake_redis_miss.set.assert_awaited_once()


async def test_openai_transient_final_raises_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3) OpenAI tenacity 최종 실패 (transient — APITimeoutError) → LLMRouterExhaustedError."""
    fake_request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    openai_mock = AsyncMock(side_effect=openai.APITimeoutError(request=fake_request))
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)

    with pytest.raises(LLMRouterExhaustedError):
        await route_feedback(system="s", user="u", cache_key=None, redis=None)


async def test_openai_payload_invalid_raises_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """4) OpenAI 영구 오류(PayloadInvalid — refusal/schema fail) → LLMRouterExhaustedError."""
    openai_mock = AsyncMock(side_effect=LLMRouterPayloadInvalidError("openai.feedback.refusal"))
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)

    with pytest.raises(LLMRouterExhaustedError):
        await route_feedback(system="s", user="u", cache_key=None, redis=None)


async def test_openai_unavailable_raises_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """5) OpenAI Unavailable (API key missing / 인증 실패) → LLMRouterExhaustedError."""
    openai_mock = AsyncMock(side_effect=LLMRouterUnavailableError("openai.api_key_missing"))
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)

    with pytest.raises(LLMRouterExhaustedError):
        await route_feedback(system="s", user="u", cache_key=None, redis=None)


async def test_exhausted_emits_sentry_capture_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """6) OpenAI 영구 실패 시 Sentry capture_message 1회 호출 (label='llm_router.exhausted')."""
    openai_mock = AsyncMock(side_effect=LLMRouterPayloadInvalidError("openai.feedback.refusal"))
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)

    capture_calls: list[dict[str, Any]] = []

    def fake_capture_message(message: str, **kwargs: Any) -> None:
        capture_calls.append({"message": message, **kwargs})

    monkeypatch.setattr(_LLM_ROUTER_MODULE.sentry_sdk, "capture_message", fake_capture_message)

    with pytest.raises(LLMRouterExhaustedError):
        await route_feedback(system="s", user="u", cache_key=None, redis=None)
    assert len(capture_calls) == 1
    assert capture_calls[0]["message"] == "llm_router.exhausted"
    assert capture_calls[0]["level"] == "error"


async def test_redis_none_skip_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """7) redis is None → cache lookup/write skip + LLM 직접 호출."""
    openai_mock = AsyncMock(return_value=FeedbackLLMOutput(text="ok", cited_chunk_indices=[]))
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)

    output, used_llm, cache_hit = await route_feedback(
        system="s", user="u", cache_key="k", redis=None
    )
    assert cache_hit is False
    assert used_llm == "gpt-4o-mini"
    assert output.text == "ok"


async def test_cache_write_failure_graceful(monkeypatch: pytest.MonkeyPatch) -> None:
    """8) cache write 실패(redis.set 예외) → graceful pass-through(예외 swallow + LLM 응답 유지)."""
    fake_redis = AsyncMock()
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.set = AsyncMock(side_effect=RuntimeError("redis_unreachable"))

    openai_mock = AsyncMock(return_value=FeedbackLLMOutput(text="ok", cited_chunk_indices=[]))
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)

    output, used_llm, cache_hit = await route_feedback(
        system="s", user="u", cache_key="k", redis=fake_redis
    )
    assert output.text == "ok"
    assert used_llm == "gpt-4o-mini"
    assert cache_hit is False


# ---------------------------------------------------------------------------
# _resolve_used_llm Literal 매핑 — Story 8.5 OpenAI 단독 정합
# ---------------------------------------------------------------------------


def test_resolve_used_llm_openai_variants() -> None:
    """env override 또는 snapshot pin 시 OpenAI 모델 라벨 정확 매핑."""
    from app.adapters.llm_router import _resolve_used_llm

    # baseline
    assert _resolve_used_llm("gpt-4o-mini") == "gpt-4o-mini"
    # env override → gpt-4o 승격
    assert _resolve_used_llm("gpt-4o") == "gpt-4o"
    # snapshot pin 호환
    assert _resolve_used_llm("gpt-4o-mini-2024-07-18") == "gpt-4o-mini"
    assert _resolve_used_llm("gpt-4o-2024-11-20") == "gpt-4o"


def test_resolve_used_llm_unknown_falls_back_to_stub() -> None:
    """미매칭 model id → ``"stub"`` fallback (LangSmith mismatch 식별)."""
    from app.adapters.llm_router import _resolve_used_llm

    assert _resolve_used_llm("llama-3-70b") == "stub"
    assert _resolve_used_llm("") == "stub"
    assert _resolve_used_llm("random-xxx") == "stub"
    # Story 8.5 — claude-* 모델 id는 'stub'으로 떨어짐(Anthropic 제거 후 legacy 라벨은 안 만듦).
    assert _resolve_used_llm("claude-haiku-4-5-20251001") == "stub"
    assert _resolve_used_llm("claude-sonnet-4-6") == "stub"


def test_resolve_used_llm_default_baseline_regression_zero() -> None:
    """settings 기본값(``gpt-4o-mini``) 회귀 가드."""
    from app.adapters.llm_router import _resolve_used_llm
    from app.core.config import settings

    assert _resolve_used_llm(settings.llm_main_model) in {"gpt-4o-mini", "gpt-4o"}
