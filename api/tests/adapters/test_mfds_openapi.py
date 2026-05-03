"""Story 3.1 — 식약처 OpenAPI 어댑터 단위 테스트 (AC #2).

``httpx.MockTransport`` 기반 — respx 의존성 회피(yagni). 케이스:
  1. 정상 응답 + 한식 카테고리 필터 → 매핑 검증
  2. 페이지네이션 — 다중 페이지 합산
  3. API key 미설정 → ``FoodSeedSourceUnavailableError``
  4. HTTP 429 → ``FoodSeedQuotaExceededError``
  5. HTTP 500 → tenacity 1회 retry → 최종 ``FoodSeedAdapterError``
  6. 응답 키 매핑 — 누락된 영양 수치는 None 보존

NFR-S5 — API key는 logger 출력 X (어댑터 코드에서 차단). 테스트는 *동작* 검증만.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from app.adapters import mfds_openapi
from app.core.config import settings
from app.core.exceptions import (
    FoodSeedAdapterError,
    FoodSeedQuotaExceededError,
    FoodSeedSourceUnavailableError,
)


def _build_korean_item(
    name: str, source_id: str, *, category: str = "면류", **extras: object
) -> dict[str, object]:
    """식약처 OpenAPI 응답 row 모형 — 한식 카테고리(필터 통과)."""
    return {
        "FOOD_NM_KR": name,
        "FOOD_GROUP_NM": category,
        "FOOD_CD": source_id,
        "AMT_NUM1": "350",
        "AMT_NUM3": "55.0",
        "AMT_NUM4": "12.0",
        "AMT_NUM5": "8.0",
        **extras,
    }


def _envelope(items: list[dict[str, object]]) -> dict[str, object]:
    """공공데이터포털 표준 응답 envelope."""
    return {"data": items}


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    """singleton client를 MockTransport 기반으로 교체."""
    mfds_openapi._reset_client_for_tests()
    monkeypatch.setattr(settings, "mfds_openapi_key", "test-key", raising=False)
    mock_client = httpx.AsyncClient(transport=transport, timeout=mfds_openapi.MFDS_TIMEOUT_SECONDS)
    # singleton 직접 주입 — _get_client()가 재생성 회피.
    mfds_openapi._client = mock_client


@pytest.fixture(autouse=True)
def _reset_singleton() -> Iterator[None]:
    """매 테스트 후 singleton 무효화 — cross-test pollution 차단."""
    yield
    mfds_openapi._reset_client_for_tests()


async def test_fetch_food_items_normal_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """1페이지 100건 한식 — target_count=10 도달 시 즉시 종료."""
    items = [_build_korean_item(f"음식{i}", f"K-{i:03d}") for i in range(100)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope(items))

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    result = await mfds_openapi.fetch_food_items(target_count=10, page_size=100)
    assert len(result) == 10
    assert result[0].name == "음식0"
    assert result[0].source == "MFDS_FCDB"
    assert result[0].source_id == "K-000"
    assert result[0].category == "면류"
    assert result[0].energy_kcal == 350.0


async def test_fetch_food_items_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    """다중 페이지 합산 — page 2개를 거쳐 200건 → target 150건 충족."""
    pages: dict[int, list[dict[str, object]]] = {
        1: [_build_korean_item(f"P1-{i}", f"K-1-{i:03d}") for i in range(100)],
        2: [_build_korean_item(f"P2-{i}", f"K-2-{i:03d}") for i in range(100)],
    }
    call_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=_envelope(pages.get(page, [])))

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    result = await mfds_openapi.fetch_food_items(target_count=150, page_size=100)
    assert len(result) == 150
    assert call_count["value"] == 2  # 두 페이지 호출


async def test_fetch_food_items_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MFDS_OPENAPI_KEY`` 미설정 → ``FoodSeedSourceUnavailableError`` 즉시 raise."""
    mfds_openapi._reset_client_for_tests()
    monkeypatch.setattr(settings, "mfds_openapi_key", "", raising=False)
    with pytest.raises(FoodSeedSourceUnavailableError) as exc_info:
        await mfds_openapi.fetch_food_items(target_count=1)
    assert "MFDS_OPENAPI_KEY" in str(exc_info.value)


async def test_fetch_food_items_quota_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 429 → ``FoodSeedQuotaExceededError``."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"resultCode": "22"})

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    with pytest.raises(FoodSeedQuotaExceededError):
        await mfds_openapi.fetch_food_items(target_count=1)


async def test_fetch_food_items_500_retry_then_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 500 → tenacity 1회 retry → 최종 ``FoodSeedAdapterError``."""
    call_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        return httpx.Response(500, json={"error": "internal"})

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    with pytest.raises(FoodSeedAdapterError):
        await mfds_openapi.fetch_food_items(target_count=1)
    # tenacity stop_after_attempt(2) — 첫 호출 + 1 retry = 2회.
    assert call_count["value"] == 2


async def test_fetch_food_items_missing_nutrition_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """일부 영양 수치 누락 → ``None`` 보존 (jsonb omission 정합)."""
    items: list[dict[str, object]] = [
        {
            "FOOD_NM_KR": "단순음식",
            "FOOD_GROUP_NM": "밥류",
            "FOOD_CD": "K-999",
            "AMT_NUM1": "200",
            # AMT_NUM3-9 누락 → None 보존
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope(items))

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    result = await mfds_openapi.fetch_food_items(target_count=1, page_size=100)
    assert len(result) == 1
    assert result[0].name == "단순음식"
    assert result[0].energy_kcal == 200.0
    assert result[0].carbohydrate_g is None
    assert result[0].protein_g is None
    assert result[0].sodium_mg is None


def test_is_quota_exceeded_handles_null_intermediate_fields() -> None:
    """CR(Gemini) G1 회귀 가드 — `dict.get(k, {})`의 default는 키 missing 시만 적용.

    공공데이터포털 응답에서 중간 계층 필드(`response`/`header`)가 명시적 ``null``로
    오면 `.get(k, {})`이 None을 반환 → 다음 `.get()` 호출에서 AttributeError 크래시.
    각 단계 isinstance 가드로 안전 처리 검증.
    """
    fake_response = httpx.Response(200)

    # null 처리 — 모두 graceful False.
    assert mfds_openapi._is_quota_exceeded(fake_response, None) is False
    assert mfds_openapi._is_quota_exceeded(fake_response, {}) is False
    assert mfds_openapi._is_quota_exceeded(fake_response, {"header": None}) is False
    assert mfds_openapi._is_quota_exceeded(fake_response, {"response": None}) is False
    assert mfds_openapi._is_quota_exceeded(fake_response, {"response": {"header": None}}) is False
    assert mfds_openapi._is_quota_exceeded(fake_response, {"resultCode": None}) is False

    # 정상 quota detection — 3가지 envelope 패턴 모두.
    assert mfds_openapi._is_quota_exceeded(fake_response, {"header": {"resultCode": "22"}}) is True
    assert (
        mfds_openapi._is_quota_exceeded(
            fake_response, {"response": {"header": {"resultCode": "22"}}}
        )
        is True
    )
    assert mfds_openapi._is_quota_exceeded(fake_response, {"resultCode": "22"}) is True
    # 정상 코드 — quota 아님.
    assert mfds_openapi._is_quota_exceeded(fake_response, {"header": {"resultCode": "00"}}) is False
