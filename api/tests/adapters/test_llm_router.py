"""Story 3.6 — `app.adapters.llm_router.route_feedback` 단위 테스트 (8 케이스, AC8-AC10).

LLM 어댑터(`call_openai_feedback`/`call_claude_feedback`) monkeypatch — 실 SDK 호출 X.
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
    """캐시 hit 시뮬레이션 — `redis.get`이 직렬화된 payload 반환."""
    redis = AsyncMock()
    payload = {
        "output": FeedbackLLMOutput(text="cached", cited_chunk_indices=[]).model_dump(mode="json"),
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
    """1) cache hit → LLM 0회 호출 + cache 값 그대로 반환."""
    openai_mock = AsyncMock()
    claude_mock = AsyncMock()
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_claude_feedback", claude_mock)

    output, used_llm, cache_hit = await route_feedback(
        system="s", user="u", cache_key="k", redis=fake_redis_hit
    )
    assert cache_hit is True
    assert used_llm == "claude"
    assert output.text == "cached"
    openai_mock.assert_not_called()
    claude_mock.assert_not_called()


async def test_cache_miss_openai_success(
    fake_redis_miss: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2) cache miss → OpenAI primary 성공 → cache write + used_llm=gpt-4o-mini."""
    openai_mock = AsyncMock(return_value=FeedbackLLMOutput(text="primary", cited_chunk_indices=[]))
    claude_mock = AsyncMock()
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_claude_feedback", claude_mock)

    output, used_llm, cache_hit = await route_feedback(
        system="s", user="u", cache_key="k", redis=fake_redis_miss
    )
    assert cache_hit is False
    assert used_llm == "gpt-4o-mini"
    assert output.text == "primary"
    openai_mock.assert_awaited_once()
    claude_mock.assert_not_called()
    fake_redis_miss.set.assert_awaited_once()


async def test_openai_transient_final_anthropic_fallback(
    fake_redis_miss: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3) OpenAI primary tenacity 최종 실패(transient — APITimeoutError) → Anthropic fallback.

    CR MJ-1 — adapter는 ``reraise=True``라 ``RetryError`` 미사용, 마지막 underlying
    예외(transient subset)가 그대로 propagate. router의 ``_OPENAI_TRANSIENT``에 포함되어
    catch + Anthropic fallback 진입.
    """
    fake_request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    openai_mock = AsyncMock(side_effect=openai.APITimeoutError(request=fake_request))
    claude_mock = AsyncMock(return_value=FeedbackLLMOutput(text="fallback", cited_chunk_indices=[]))
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_claude_feedback", claude_mock)

    output, used_llm, cache_hit = await route_feedback(
        system="s", user="u", cache_key=None, redis=None
    )
    assert cache_hit is False
    # Story 3.9 AC13 — env override 정확 attribution. settings.llm_fallback_model =
    # ``claude-haiku-4-5-20251001`` → ``"claude-haiku-4-5"`` (이전: ``"claude"`` baseline).
    assert used_llm == "claude-haiku-4-5"
    assert output.text == "fallback"


async def test_openai_payload_invalid_anthropic_fallback(
    fake_redis_miss: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """4) OpenAI 영구 오류(PayloadInvalid) → Anthropic fallback 성공."""
    openai_mock = AsyncMock(side_effect=LLMRouterPayloadInvalidError("openai.feedback.refusal"))
    claude_mock = AsyncMock(return_value=FeedbackLLMOutput(text="claude", cited_chunk_indices=[]))
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_claude_feedback", claude_mock)

    output, used_llm, _ = await route_feedback(system="s", user="u", cache_key=None, redis=None)
    assert used_llm == "claude-haiku-4-5"
    assert output.text == "claude"


async def test_openai_unavailable_anthropic_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5) OpenAI Unavailable(API key missing) → Anthropic fallback 성공."""
    openai_mock = AsyncMock(side_effect=LLMRouterUnavailableError("openai.api_key_missing"))
    claude_mock = AsyncMock(return_value=FeedbackLLMOutput(text="ok", cited_chunk_indices=[]))
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_claude_feedback", claude_mock)

    output, used_llm, _ = await route_feedback(system="s", user="u", cache_key=None, redis=None)
    assert used_llm == "claude-haiku-4-5"


async def test_dual_llm_exhausted_raises_and_capture_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """6) 양쪽 LLM 실패 → LLMRouterExhaustedError raise + Sentry capture_message 1회."""
    openai_mock = AsyncMock(side_effect=LLMRouterPayloadInvalidError("openai.feedback.refusal"))
    claude_mock = AsyncMock(
        side_effect=LLMRouterPayloadInvalidError("anthropic.payload.json_decode_failed")
    )
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_claude_feedback", claude_mock)

    capture_calls: list[dict[str, Any]] = []

    def fake_capture_message(message: str, **kwargs: Any) -> None:
        capture_calls.append({"message": message, **kwargs})

    monkeypatch.setattr(_LLM_ROUTER_MODULE.sentry_sdk, "capture_message", fake_capture_message)

    with pytest.raises(LLMRouterExhaustedError):
        await route_feedback(system="s", user="u", cache_key=None, redis=None)
    assert len(capture_calls) == 1
    assert capture_calls[0]["message"] == "dual_llm_router.exhausted"
    assert capture_calls[0]["level"] == "error"


async def test_redis_none_skip_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """7) redis is None → cache lookup/write skip + LLM 직접 호출."""
    openai_mock = AsyncMock(return_value=FeedbackLLMOutput(text="ok", cited_chunk_indices=[]))
    claude_mock = AsyncMock()
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_claude_feedback", claude_mock)

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
    claude_mock = AsyncMock()
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_openai_feedback", openai_mock)
    monkeypatch.setattr(_LLM_ROUTER_MODULE, "call_claude_feedback", claude_mock)

    output, used_llm, cache_hit = await route_feedback(
        system="s", user="u", cache_key="k", redis=fake_redis
    )
    assert output.text == "ok"
    assert used_llm == "gpt-4o-mini"
    assert cache_hit is False


# ---------------------------------------------------------------------------
# Story 3.9 AC13 — _resolve_used_llm Literal 매핑 (3 케이스)
# ---------------------------------------------------------------------------


def test_resolve_used_llm_env_override_attribution() -> None:
    """AC13 케이스 ① — env override 시 used_llm 정확 매핑(Literal 정합)."""
    from app.adapters.llm_router import _resolve_used_llm

    # 기본 baseline
    assert _resolve_used_llm("gpt-4o-mini") == "gpt-4o-mini"
    # env override → gpt-4o 승격
    assert _resolve_used_llm("gpt-4o") == "gpt-4o"
    # snapshot pin 호환
    assert _resolve_used_llm("gpt-4o-mini-2024-07-18") == "gpt-4o-mini"
    assert _resolve_used_llm("gpt-4o-2024-11-20") == "gpt-4o"
    # claude haiku 4-5 명시
    assert _resolve_used_llm("claude-haiku-4-5-20251001") == "claude-haiku-4-5"
    assert _resolve_used_llm("claude-haiku-4-5") == "claude-haiku-4-5"


def test_resolve_used_llm_unknown_falls_back_to_stub() -> None:
    """AC13 케이스 ② — 미매칭 model id → ``"stub"`` fallback (LangSmith mismatch 식별)."""
    from app.adapters.llm_router import _resolve_used_llm

    assert _resolve_used_llm("llama-3-70b") == "stub"
    assert _resolve_used_llm("") == "stub"
    assert _resolve_used_llm("random-xxx") == "stub"
    # claude-* 변형은 "claude" baseline로 떨어짐(이전 캐시 row 호환).
    assert _resolve_used_llm("claude-sonnet-4-6-20251001") == "claude"


def test_resolve_used_llm_default_baseline_regression_zero() -> None:
    """AC13 케이스 ③ — settings 기본값(``gpt-4o-mini``/``claude-haiku-4-5``) 회귀 가드."""
    from app.adapters.llm_router import _resolve_used_llm
    from app.core.config import settings

    # 현 settings baseline 유지 — env override 없이도 정확 매핑.
    assert _resolve_used_llm(settings.llm_main_model) in {"gpt-4o-mini", "gpt-4o"}
    # default `claude-haiku-4-5-20251001` → "claude-haiku-4-5"
    assert _resolve_used_llm(settings.llm_fallback_model) == "claude-haiku-4-5"
