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

from datetime import UTC
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
        await openai_adapter.generate_clarification_options("포케볼")


# ---------------------------------------------------------------------------
# Story 3.9 AC6/AC7 — Vision 캐시 + cost cap (6 케이스)
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Redis stub — async get/set/incrbyfloat/expire + pipeline."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.cost_counter: float = 0.0

    async def get(self, key: str) -> str | None:
        if key.startswith("cost:vision:daily:"):
            return str(self.cost_counter) if self.cost_counter else None
        return self.store.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        _ = ex
        self.store[key] = value

    def pipeline(self, transaction: bool = False) -> _FakePipeline:  # type: ignore[no-untyped-def]
        _ = transaction
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self.redis = redis
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    def incrbyfloat(self, key: str, value: float) -> None:
        self._ops.append(("incrbyfloat", (key, value)))

    def expire(self, key: str, ttl: int, nx: bool = False) -> None:  # noqa: ARG002
        self._ops.append(("expire", (key, ttl)))

    async def execute(self) -> list[Any]:
        results: list[Any] = []
        for op, args in self._ops:
            if op == "incrbyfloat":
                key, value = args
                if key.startswith("cost:vision:daily:"):
                    self.redis.cost_counter += float(value)
                results.append(self.redis.cost_counter)
            else:
                results.append(True)
        return results

    async def __aenter__(self) -> _FakePipeline:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


async def test_vision_cache_hit_skips_openai_call(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """AC6 케이스 ① — cache hit 시 OpenAI 호출 0회 + 캐시된 ParsedMeal 반환."""
    redis = _FakeRedis()
    image_key = "meals/userA/abc.jpg"
    cached_meal = openai_adapter.ParsedMeal(
        items=[openai_adapter.ParsedMealItem(name="피자", quantity="1조각", confidence=0.9)],
        model_used="gpt-4o",
    )
    redis.store[openai_adapter._vision_cache_key(image_key)] = cached_meal.model_dump_json()

    mock_parse = _install_mock_client(monkeypatch, parse_return=_build_mock_response([]))

    result = await openai_adapter.parse_meal_image(
        "https://cdn.example.com/meals/userA/abc.jpg",
        image_key=image_key,
        redis_client=redis,
    )

    assert mock_parse.await_count == 0
    assert result.items[0].name == "피자"


async def test_vision_cache_miss_calls_openai_and_sets_cache(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """AC6 케이스 ② — cache miss 시 OpenAI 호출 + 응답 cache set."""
    redis = _FakeRedis()
    image_key = "meals/userB/def.jpg"
    items = [{"name": "샐러드", "quantity": "1인분", "confidence": 0.85}]
    response = _build_mock_response(items)
    mock_parse = _install_mock_client(monkeypatch, parse_return=response)

    result = await openai_adapter.parse_meal_image(
        "https://cdn.example.com/meals/userB/def.jpg",
        image_key=image_key,
        redis_client=redis,
    )

    assert mock_parse.await_count == 1
    assert result.items[0].name == "샐러드"
    # cache set 확인.
    cache_key = openai_adapter._vision_cache_key(image_key)
    assert cache_key in redis.store


async def test_vision_cache_deserialize_failure_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """AC6 케이스 ③ — deserialize 실패 시 graceful fallback(cache miss로 처리)."""
    redis = _FakeRedis()
    image_key = "meals/userC/ghi.jpg"
    redis.store[openai_adapter._vision_cache_key(image_key)] = "not-json{{{"

    items = [{"name": "초밥", "quantity": "10pcs", "confidence": 0.92}]
    response = _build_mock_response(items)
    mock_parse = _install_mock_client(monkeypatch, parse_return=response)

    result = await openai_adapter.parse_meal_image(
        "https://cdn.example.com/meals/userC/ghi.jpg",
        image_key=image_key,
        redis_client=redis,
    )

    # OpenAI 호출 1회(graceful fallback) — Sentry warning은 capture만 검증.
    assert mock_parse.await_count == 1
    assert result.items[0].name == "초밥"


async def test_vision_cap_reached_downgrades_to_mini(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """AC7 케이스 ④ — cap 도달 시 ``gpt-4o-mini`` 다운그레이드 + ``model_used`` metadata."""
    redis = _FakeRedis()
    redis.cost_counter = 5.0  # vision_daily_cost_cap_usd 도달

    items = [{"name": "스무디", "quantity": "300ml", "confidence": 0.8}]
    response = _build_mock_response(items)
    mock_parse = _install_mock_client(monkeypatch, parse_return=response)

    result = await openai_adapter.parse_meal_image(
        "https://cdn.example.com/meals/userD/jkl.jpg",
        image_key="meals/userD/jkl.jpg",
        redis_client=redis,
    )

    # 다운그레이드 모델로 호출 — model_used 갱신.
    assert result.model_used == "gpt-4o-mini"
    assert mock_parse.await_count == 1
    # 모델 인자 — call_args에서 추출.
    call_kwargs = mock_parse.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"


async def test_vision_fallback_cap_reached_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """AC7 케이스 ⑤ — fallback cap도 초과 시 ``MealOCRUnavailableError`` raise."""
    redis = _FakeRedis()
    redis.cost_counter = 6.5  # 5.0 + 1.0(fallback) cap도 초과

    response = _build_mock_response([])
    mock_parse = _install_mock_client(monkeypatch, parse_return=response)

    with pytest.raises(MealOCRUnavailableError) as exc_info:
        await openai_adapter.parse_meal_image(
            "https://cdn.example.com/meals/userE/mno.jpg",
            image_key="meals/userE/mno.jpg",
            redis_client=redis,
        )

    assert mock_parse.await_count == 0  # OpenAI 호출 0회
    assert "한도" in str(exc_info.value)


async def test_vision_kst_midnight_resets_counter(
    monkeypatch: pytest.MonkeyPatch,
    _openai_configured: None,
) -> None:
    """AC7 케이스 ⑥ — KST 자정 cross 시 카운터 키가 새 YYYY-MM-DD로 리셋(키 분리)."""
    from datetime import datetime

    _ = _FakeRedis()  # presence sanity

    # KST 자정 직전(May 4 23:59) — 기존 키.
    fake_now_late = datetime(2026, 5, 4, 14, 59, 0, tzinfo=UTC)  # UTC 14:59 = KST 23:59

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):  # type: ignore[no-untyped-def]
            return fake_now_late.astimezone(tz) if tz else fake_now_late

    monkeypatch.setattr(openai_adapter, "datetime", _FakeDatetime)
    key_late = openai_adapter._vision_cost_counter_key()

    # KST 자정 cross — 새 키 생성.
    fake_now_early = datetime(2026, 5, 4, 15, 1, 0, tzinfo=UTC)  # UTC 15:01 = KST 00:01 (May 5)

    class _FakeDatetime2:
        @staticmethod
        def now(tz=None):  # type: ignore[no-untyped-def]
            return fake_now_early.astimezone(tz) if tz else fake_now_early

    monkeypatch.setattr(openai_adapter, "datetime", _FakeDatetime2)
    key_early = openai_adapter._vision_cost_counter_key()

    # 키가 다른 날짜로 분리 — 카운터 자연 리셋.
    assert key_late != key_early
    assert "2026-05-04" in key_late
    assert "2026-05-05" in key_early
