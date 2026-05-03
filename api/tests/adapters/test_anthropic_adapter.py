"""Story 3.6 — `app.adapters.anthropic_adapter` 단위 테스트 (4 케이스, AC8).

`_call_claude` 내부 SDK 호출은 monkeypatch — 실 SDK 호출 X. tenacity retry는 inline에
전파(영구 오류 즉시 raise / transient 후 RetryError).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest

import app.adapters.anthropic_adapter as anthropic_adapter
from app.adapters.anthropic_adapter import call_claude_feedback
from app.core.exceptions import LLMRouterPayloadInvalidError
from app.graph.state import FeedbackLLMOutput

_AA_MODULE = sys.modules["app.adapters.anthropic_adapter"]


@pytest.fixture(autouse=True)
def _reset_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """매 테스트마다 anthropic adapter singleton 리셋 + API key set."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    anthropic_adapter._reset_client_for_tests()
    yield
    anthropic_adapter._reset_client_for_tests()


def _make_response(text: str) -> Any:
    """Anthropic messages.create 응답 stub — `content[0].text`."""

    class _Block:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Response:
        def __init__(self, text: str) -> None:
            self.content = [_Block(text)]

    return _Response(text)


async def test_normal_response_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """정상 응답 — JSON fence 포함 → ``FeedbackLLMOutput`` 반환."""
    payload = '```json\n{"text": "hello", "cited_chunk_indices": [0]}\n```'

    async def fake_create(**kwargs: Any) -> Any:
        return _make_response(payload)

    fake_messages = AsyncMock()
    fake_messages.create = fake_create
    fake_client = AsyncMock()
    fake_client.messages = fake_messages
    monkeypatch.setattr(_AA_MODULE, "_get_client", lambda: fake_client)

    out = await call_claude_feedback(system="s", user="u", response_format=FeedbackLLMOutput)
    assert out.text == "hello"
    assert out.cited_chunk_indices == [0]


async def test_transient_retry_then_final_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """transient 3회 실패(monkeypatch raise) 후 마지막 예외가 그대로 reraise(`reraise=True`)."""
    call_count = {"n": 0}
    fake_request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    async def fake_create(**kwargs: Any) -> Any:
        call_count["n"] += 1
        raise anthropic.APITimeoutError(request=fake_request)

    fake_messages = AsyncMock()
    fake_messages.create = fake_create
    fake_client = AsyncMock()
    fake_client.messages = fake_messages
    monkeypatch.setattr(_AA_MODULE, "_get_client", lambda: fake_client)

    # tenacity reraise=True — 최종 실패는 마지막 예외를 그대로 raise (RetryError 미사용).
    # router 측은 transient subset을 직접 catch.
    with pytest.raises(anthropic.APITimeoutError):
        await call_claude_feedback(system="s", user="u", response_format=FeedbackLLMOutput)
    assert call_count["n"] == 3  # tenacity stop_after_attempt(3)


async def test_permanent_error_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """영구 오류(BadRequestError) — retry 없이 1회 호출 후 ``LLMRouterPayloadInvalidError``로 변환.

    CR D1 — adapter boundary에서 SDK 영구 오류를 router-typed 예외로 translate해야
    router의 ``_ANTHROPIC_HANDLED_TYPES``가 catch 가능 + Anthropic 인증 누락 등이 dual
    exhausted까지 진행하도록.
    """
    call_count = {"n": 0}
    fake_request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    fake_response = httpx.Response(status_code=400, request=fake_request)

    async def fake_create(**kwargs: Any) -> Any:
        call_count["n"] += 1
        raise anthropic.BadRequestError(message="bad", response=fake_response, body=None)

    fake_messages = AsyncMock()
    fake_messages.create = fake_create
    fake_client = AsyncMock()
    fake_client.messages = fake_messages
    monkeypatch.setattr(_AA_MODULE, "_get_client", lambda: fake_client)

    with pytest.raises(LLMRouterPayloadInvalidError):
        await call_claude_feedback(system="s", user="u", response_format=FeedbackLLMOutput)
    assert call_count["n"] == 1  # retry 미포함 — 1회만


async def test_parsing_failure_payload_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """잘못된 JSON → ``LLMRouterPayloadInvalidError``."""

    async def fake_create(**kwargs: Any) -> Any:
        return _make_response("not a json")

    fake_messages = AsyncMock()
    fake_messages.create = fake_create
    fake_client = AsyncMock()
    fake_client.messages = fake_messages
    monkeypatch.setattr(_AA_MODULE, "_get_client", lambda: fake_client)

    with pytest.raises(LLMRouterPayloadInvalidError):
        await call_claude_feedback(system="s", user="u", response_format=FeedbackLLMOutput)
