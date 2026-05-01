"""Story 3.1 — ``embed_texts`` 단위 테스트 (AC #3).

``AsyncOpenAI`` ``embeddings.create`` mock — 실제 OpenAI 도달 X (cost 0 + offline 안전).
케이스:
  1. 300건 입력 → 단일 batch 호출 → 300×1536 응답
  2. 700건 입력 → 3 batches(300+300+100) 합산 → 700×1536
  3. 차원 불일치(1024) → ``FoodSeedAdapterError``
  4. RateLimitError → 1회 retry → 최종 ``FoodSeedAdapterError``
  5. AuthenticationError → 즉시 ``FoodSeedAdapterError`` (retry 무효)
  6. 빈 리스트 → API 호출 0건 + 빈 리스트 응답
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest

from app.adapters import openai_adapter
from app.core.config import settings as _settings
from app.core.exceptions import FoodSeedAdapterError


@pytest.fixture(autouse=True)
def _reset_openai_client_singleton() -> None:
    openai_adapter._reset_client_for_tests()


@pytest.fixture
def _openai_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_settings, "openai_api_key", "sk-test-key")


def _build_embedding_response(count: int, *, dim: int = 1536) -> MagicMock:
    """``embeddings.create`` 응답 mock — count×dim 임베딩."""
    response = MagicMock()
    response.data = [MagicMock(embedding=[0.0] * dim) for _ in range(count)]
    return response


def _install_mock_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    create_side_effect: Any = None,
    create_return: Any = None,
) -> AsyncMock:
    mock_create = AsyncMock(side_effect=create_side_effect, return_value=create_return)
    mock_client = MagicMock()
    mock_client.embeddings.create = mock_create
    monkeypatch.setattr(openai_adapter, "_get_client", lambda: mock_client)
    return mock_create


async def test_embed_texts_single_batch(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """300건 입력 → 단일 batch 호출 → 300×1536."""
    response = _build_embedding_response(300)
    mock_create = _install_mock_client(monkeypatch, create_return=response)

    texts = [f"음식{i}" for i in range(300)]
    result = await openai_adapter.embed_texts(texts)

    assert len(result) == 300
    assert all(len(v) == 1536 for v in result)
    assert mock_create.call_count == 1


async def test_embed_texts_multi_batch(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """700건 입력 → 3 batches(300+300+100) 합산."""
    call_count = {"value": 0}

    def side_effect(*args: object, **kwargs: object) -> MagicMock:
        call_count["value"] += 1
        # 각 호출의 input 길이만큼 응답 생성
        input_list = kwargs.get("input")
        n = len(input_list) if isinstance(input_list, list) else 0
        return _build_embedding_response(n)

    mock_create = _install_mock_client(monkeypatch, create_side_effect=side_effect)
    texts = [f"음식{i}" for i in range(700)]
    result = await openai_adapter.embed_texts(texts)

    assert len(result) == 700
    assert mock_create.call_count == 3


async def test_embed_texts_dimension_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """차원 1024 응답 → ``FoodSeedAdapterError`` (모델 변경 회귀 차단)."""
    response = _build_embedding_response(1, dim=1024)
    _install_mock_client(monkeypatch, create_return=response)
    with pytest.raises(FoodSeedAdapterError) as exc_info:
        await openai_adapter.embed_texts(["테스트"])
    assert "dimension mismatch" in str(exc_info.value)


async def test_embed_texts_rate_limit_retried_then_fail(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """RateLimitError 2회 → tenacity retry 후 최종 ``FoodSeedAdapterError``."""
    rate_limit_error = openai.RateLimitError(
        message="rate limit exceeded",
        response=httpx.Response(
            429, request=httpx.Request("POST", "https://api.openai.com/v1/embeddings")
        ),
        body=None,
    )
    mock_create = _install_mock_client(monkeypatch, create_side_effect=rate_limit_error)
    with pytest.raises(FoodSeedAdapterError):
        await openai_adapter.embed_texts(["테스트"])
    # tenacity stop_after_attempt(2) — 첫 호출 + 1 retry = 2회.
    assert mock_create.call_count == 2


async def test_embed_texts_auth_error_immediate_fail(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """AuthenticationError → retry 무효 → 1회 호출 후 즉시 ``FoodSeedAdapterError``."""
    auth_error = openai.AuthenticationError(
        message="invalid api key",
        response=httpx.Response(
            401, request=httpx.Request("POST", "https://api.openai.com/v1/embeddings")
        ),
        body=None,
    )
    mock_create = _install_mock_client(monkeypatch, create_side_effect=auth_error)
    with pytest.raises(FoodSeedAdapterError):
        await openai_adapter.embed_texts(["테스트"])
    # retry 무효 — 1회만 호출.
    assert mock_create.call_count == 1


async def test_embed_texts_empty_input_no_api_call(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """빈 입력 → API 호출 0건 + 빈 리스트 응답 (cost 0)."""
    mock_create = _install_mock_client(monkeypatch, create_return=_build_embedding_response(0))
    result = await openai_adapter.embed_texts([])
    assert result == []
    assert mock_create.call_count == 0
