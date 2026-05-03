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


# ---------------------------------------------------------------------------
# Story 3.4 — parse_meal_text + rewrite_food_query + generate_clarification_options
# ---------------------------------------------------------------------------


def _build_parse_text_response(items: list[dict[str, Any]]) -> MagicMock:
    parsed = openai_adapter.ParsedMeal(
        items=[openai_adapter.ParsedMealItem.model_validate(item) for item in items]
    )
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed
    response.choices[0].message.refusal = None
    return response


def _build_rewrite_response(variants: list[str]) -> MagicMock:
    parsed = openai_adapter.RewriteVariants(variants=variants)
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed
    response.choices[0].message.refusal = None
    return response


def _build_clarification_response(options: list[dict[str, str]]) -> MagicMock:
    from app.graph.state import ClarificationOption

    parsed = openai_adapter.ClarificationVariants(
        options=[ClarificationOption(**o) for o in options]
    )
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed
    response.choices[0].message.refusal = None
    return response


# --- parse_meal_text ---


async def test_parse_meal_text_returns_parsed_meal(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """Story 3.4 AC2 — 정상 호출 → ParsedMeal 매핑."""
    response = _build_parse_text_response(
        [
            {"name": "짜장면", "quantity": "1인분", "confidence": 0.92},
            {"name": "군만두", "quantity": "4개", "confidence": 0.88},
        ]
    )
    _install_mock_client(monkeypatch, parse_return=response)

    result = await openai_adapter.parse_meal_text("짜장면 1인분, 군만두 4개")
    assert len(result.items) == 2
    assert result.items[0].name == "짜장면"


async def test_parse_meal_text_empty_input_skips_api(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """Story 3.4 AC2 — 빈 입력은 API 호출 X / cost 0."""
    mock_parse = _install_mock_client(monkeypatch, parse_return=_build_parse_text_response([]))

    result = await openai_adapter.parse_meal_text("")
    assert result.items == []
    assert mock_parse.await_count == 0

    result_ws = await openai_adapter.parse_meal_text("   ")
    assert result_ws.items == []
    assert mock_parse.await_count == 0


async def test_parse_meal_text_transient_retried(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """Story 3.4 AC2 — `httpx.TimeoutException` 1회 → retry → 정상 응답."""
    success = _build_parse_text_response(
        [{"name": "비빔밥", "quantity": "1인분", "confidence": 0.95}]
    )
    timeout = httpx.TimeoutException("read timeout")
    mock_parse = _install_mock_client(monkeypatch, parse_side_effect=[timeout, success])

    result = await openai_adapter.parse_meal_text("비빔밥 1인분")
    assert result.items[0].name == "비빔밥"
    assert mock_parse.await_count == 2


async def test_parse_meal_text_permanent_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """Story 3.4 AC2 — 영구 오류(`AuthenticationError`) → 즉시 `MealOCRUnavailableError`."""
    auth_err = openai.AuthenticationError(
        message="bad key",
        response=httpx.Response(401, request=httpx.Request("POST", "https://api.openai.com")),
        body=None,
    )
    mock_parse = _install_mock_client(monkeypatch, parse_side_effect=auth_err)

    with pytest.raises(MealOCRUnavailableError):
        await openai_adapter.parse_meal_text("짜장면")
    # retry 무효 — 1회 호출만(영구 오류 즉시 fail).
    assert mock_parse.await_count == 1


async def test_parse_meal_text_payload_invalid_when_parsed_none(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """Story 3.4 AC2 — `message.parsed=None` → `MealOCRPayloadInvalidError(502)`."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = None
    response.choices[0].message.refusal = None
    _install_mock_client(monkeypatch, parse_return=response)

    with pytest.raises(MealOCRPayloadInvalidError):
        await openai_adapter.parse_meal_text("짜장면")


# --- rewrite_food_query ---


async def test_rewrite_food_query_returns_variants(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """Story 3.4 AC2 — 정상 호출 → 2-4 변형 응답."""
    response = _build_rewrite_response(["연어 포케", "참치 포케", "베지 포케"])
    _install_mock_client(monkeypatch, parse_return=response)

    result = await openai_adapter.rewrite_food_query("포케볼")
    assert len(result.variants) == 3
    assert result.variants[0] == "연어 포케"


async def test_rewrite_food_query_empty_input_graceful(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """Story 3.4 AC2 — 빈 입력 → graceful fallback (API 호출 X)."""
    mock_parse = _install_mock_client(monkeypatch, parse_return=_build_rewrite_response(["dummy"]))

    result = await openai_adapter.rewrite_food_query("")
    assert result.variants == ["unknown"]
    assert mock_parse.await_count == 0


async def test_rewrite_food_query_transient_retried(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """Story 3.4 AC2 — RateLimit transient → retry."""
    success = _build_rewrite_response(["짜장면 곱빼기", "짜파게티"])
    rate_limit = openai.RateLimitError(
        message="rate limit",
        response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")),
        body=None,
    )
    mock_parse = _install_mock_client(monkeypatch, parse_side_effect=[rate_limit, success])

    result = await openai_adapter.rewrite_food_query("짜장면")
    assert mock_parse.await_count == 2
    assert result.variants[0] == "짜장면 곱빼기"


# --- generate_clarification_options ---


async def test_generate_clarification_options_returns_options(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """Story 3.4 AC2 — 정상 호출 → 2-4 옵션."""
    response = _build_clarification_response(
        [
            {"label": "연어 포케", "value": "연어 포케 1인분"},
            {"label": "참치 포케", "value": "참치 포케 1인분"},
            {"label": "채소 포케", "value": "베지 포케 1인분"},
        ]
    )
    _install_mock_client(monkeypatch, parse_return=response)

    result = await openai_adapter.generate_clarification_options("포케볼")
    assert len(result.options) == 3
    assert result.options[0].label == "연어 포케"
    assert result.options[0].value == "연어 포케 1인분"


async def test_generate_clarification_options_empty_input_graceful(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """Story 3.4 AC2 — 빈 입력 → fallback 1건 강제 (API 호출 X)."""
    mock_parse = _install_mock_client(
        monkeypatch,
        parse_return=_build_clarification_response([{"label": "dummy", "value": "dummy"}]),
    )

    result = await openai_adapter.generate_clarification_options("")
    assert len(result.options) == 1
    assert result.options[0].label == "알 수 없음"
    assert mock_parse.await_count == 0


async def test_generate_clarification_options_payload_invalid(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """Story 3.4 AC2 — refusal → MealOCRPayloadInvalidError."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = None
    response.choices[0].message.refusal = "moderation_blocked"
    _install_mock_client(monkeypatch, parse_return=response)

    with pytest.raises(MealOCRPayloadInvalidError):
        await openai_adapter.generate_clarification_options("xxxx")
