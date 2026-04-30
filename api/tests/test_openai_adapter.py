"""Story 2.3 — `app/adapters/openai_adapter.py` Vision OCR adapter 단위 테스트 (AC2/AC5/AC11).

5+ 케이스:
- ``test_parse_meal_image_returns_parsed_meal_pydantic`` — `AsyncOpenAI.beta.chat.completions.parse`
  mock → ParsedMeal(2 items) → 정확 역직렬화 검증.
- ``test_parse_meal_image_empty_items_supported`` — mock 빈 items → 정상 반환(빈 배열).
- ``test_parse_meal_image_timeout_raises_unavailable`` — `httpx.TimeoutException` mock →
  tenacity retry 후 `MealOCRUnavailableError` raise.
- ``test_parse_meal_image_rate_limit_retried`` — `openai.RateLimitError` 1회 mock 후 정상
  응답 → retry 후 성공.
- ``test_parse_meal_image_unconfigured_raises_unavailable`` — `openai_api_key=""` 환경 →
  `MealOCRUnavailableError` raise (settings 검증).
- ``test_parse_meal_image_payload_invalid_when_parsed_none`` — `message.parsed=None` →
  `MealOCRPayloadInvalidError(502)` raise.

monkeypatch fixture로 `_get_client` mock — 실제 OpenAI 도달 X (cost 0 + offline 안전).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest

from app.adapters import openai_adapter
from app.core.config import settings as _settings
from app.core.exceptions import MealOCRPayloadInvalidError, MealOCRUnavailableError


@pytest.fixture(autouse=True)
def _reset_openai_client_singleton() -> None:
    """매 테스트 전 AsyncOpenAI client singleton 무효화 — settings monkeypatch 반영."""
    openai_adapter._reset_client_for_tests()


@pytest.fixture
def _openai_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """test settings에 OpenAI API 키 주입."""
    monkeypatch.setattr(_settings, "openai_api_key", "sk-test-key")


def _build_mock_response(items: list[dict[str, Any]]) -> MagicMock:
    """`AsyncOpenAI.beta.chat.completions.parse` 응답 mock — `choices[0].message.parsed`에
    ``ParsedMeal`` 인스턴스 직접 주입(SDK 자동 Pydantic 역직렬화 시뮬레이션).

    CR P4 정합(2026-04-30) — `message.refusal=None` 명시 (MagicMock auto-attribute가
    truthy 평가되어 refusal 분기 오발 방지).
    """
    parsed_meal = openai_adapter.ParsedMeal(
        items=[openai_adapter.ParsedMealItem.model_validate(item) for item in items]
    )
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed_meal
    response.choices[0].message.refusal = None
    return response


def _install_mock_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    parse_side_effect: Any = None,
    parse_return: Any = None,
) -> AsyncMock:
    """`_get_client()` mock — `beta.chat.completions.parse`를 AsyncMock으로 stub."""
    mock_parse = AsyncMock(side_effect=parse_side_effect, return_value=parse_return)
    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse = mock_parse
    monkeypatch.setattr(openai_adapter, "_get_client", lambda: mock_client)
    return mock_parse


async def test_parse_meal_image_returns_parsed_meal_pydantic(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """정상 호출 — 2 items → 정확 역직렬화."""
    items = [
        {"name": "짜장면", "quantity": "1인분", "confidence": 0.92},
        {"name": "군만두", "quantity": "4개", "confidence": 0.88},
    ]
    response = _build_mock_response(items)
    _install_mock_client(monkeypatch, parse_return=response)

    result = await openai_adapter.parse_meal_image(
        "https://cdn.example.com/meals/foo/bar.jpg",
        image_key="meals/foo/bar.jpg",
    )

    assert isinstance(result, openai_adapter.ParsedMeal)
    assert len(result.items) == 2
    assert result.items[0].name == "짜장면"
    assert result.items[0].quantity == "1인분"
    assert result.items[0].confidence == pytest.approx(0.92)
    assert result.items[1].name == "군만두"


async def test_parse_meal_image_empty_items_supported(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """빈 items — 풍경/사물 사진 케이스. 정상 반환(빈 배열)."""
    response = _build_mock_response([])
    _install_mock_client(monkeypatch, parse_return=response)

    result = await openai_adapter.parse_meal_image(
        "https://cdn.example.com/meals/foo/bar.jpg",
    )

    assert isinstance(result, openai_adapter.ParsedMeal)
    assert result.items == []


async def test_parse_meal_image_timeout_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """`httpx.TimeoutException` — tenacity 1회 retry 후 `MealOCRUnavailableError(503)`."""
    timeout = httpx.TimeoutException("read timeout")
    mock_parse = _install_mock_client(monkeypatch, parse_side_effect=timeout)

    with pytest.raises(MealOCRUnavailableError):
        await openai_adapter.parse_meal_image("https://cdn.example.com/meals/foo/bar.jpg")

    # retry 1회 = stop_after_attempt(2) → 총 2회 호출.
    assert mock_parse.await_count == 2


async def test_parse_meal_image_rate_limit_retried(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """`openai.RateLimitError` 1회 → retry → 정상 응답 → 최종 성공."""
    items = [{"name": "비빔밥", "quantity": "1인분", "confidence": 0.95}]
    success_response = _build_mock_response(items)
    rate_limit = openai.RateLimitError(
        message="rate limit",
        response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")),
        body=None,
    )
    mock_parse = _install_mock_client(
        monkeypatch,
        parse_side_effect=[rate_limit, success_response],
    )

    result = await openai_adapter.parse_meal_image("https://cdn.example.com/meals/foo/bar.jpg")

    assert len(result.items) == 1
    assert result.items[0].name == "비빔밥"
    assert mock_parse.await_count == 2


async def test_parse_meal_image_unconfigured_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`OPENAI_API_KEY` 미설정 — `MealOCRUnavailableError(503)` raise."""
    monkeypatch.setattr(_settings, "openai_api_key", "")

    with pytest.raises(MealOCRUnavailableError):
        await openai_adapter.parse_meal_image("https://cdn.example.com/meals/foo/bar.jpg")


async def test_parse_meal_image_payload_invalid_when_parsed_none(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """`message.parsed=None` (null content) — `MealOCRPayloadInvalidError(502)`."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = None
    response.choices[0].message.refusal = None
    _install_mock_client(monkeypatch, parse_return=response)

    with pytest.raises(MealOCRPayloadInvalidError):
        await openai_adapter.parse_meal_image("https://cdn.example.com/meals/foo/bar.jpg")
