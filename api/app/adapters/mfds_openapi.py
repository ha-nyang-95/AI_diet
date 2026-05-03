"""식약처 식품영양성분 DB OpenAPI 어댑터 — Story 3.1 (음식 영양 RAG 시드).

공공데이터포털 데이터셋 ID 15127578 (식약처 식품영양성분 DB) — httpx async 어댑터 +
페이지네이션 + 한식 우선 카테고리 필터 + tenacity 1회 retry + 503/quota 분기.

P1 — Story 2.2 ``r2.py`` / Story 2.3 ``openai_adapter.py`` 정합 — ``httpx.AsyncClient``
lazy singleton + ``threading.Lock`` double-checked locking. 매 호출 새 instance는
connection pool 재구성 비용.

오류 매핑:
- ``settings.mfds_openapi_key`` 미설정 — ``FoodSeedSourceUnavailableError(503)`` 즉시
  raise (cost 0 / fail-fast — retry 무효).
- HTTP 429 또는 응답 본문 quota error code — ``FoodSeedQuotaExceededError(503)``
  (시드 스크립트가 ZIP fallback 분기 트리거 신호).
- HTTP 401/403 — API key 무효, 즉시 ``FoodSeedAdapterError(503)`` (retry 무효).
- ``httpx.HTTPError`` / ``httpx.TimeoutException`` *transient* — tenacity 1회 retry 후
  최종 ``FoodSeedAdapterError(503)``.

NFR-S5 마스킹 — API key는 logger 출력 X. URL에 query 파라미터로 전송되지만 raw URL
출력 X — ``mfds.openapi.fetch_page`` event-style 1줄(page_index/items_count/latency_ms).

DS 검증 의무 — 본 모듈 const(``MFDS_API_BASE_URL``/``MFDS_RAW_KEY_MAP``/
``MFDS_KOREAN_FOOD_CATEGORIES``)는 *추정값* — 데이터셋 15127578 OpenAPI 문서 또는
샘플 응답으로 *최종 키 명 확정* 필요. 누락 키는 jsonb omission으로 graceful 처리.
docstring에 *"확인일자 2026-XX-XX"* 명시 후 운영 부팅 시 검증 권장.

본 어댑터는 *시드 시점*만 사용 — Story 3.3+ retrieve_nutrition 노드는 DB 검색만
(어댑터 미사용).
"""

from __future__ import annotations

import threading
import time
import unicodedata
from typing import Any, Final

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.exceptions import (
    FoodSeedAdapterError,
    FoodSeedQuotaExceededError,
    FoodSeedSourceUnavailableError,
)

logger = structlog.get_logger(__name__)

# 식약처 식품영양성분 DB OpenAPI v2 base URL.
# 검증일자: 2026-05-03 — data.go.kr 활용신청 상세보기 "End Point" 필드 + sub-path
# `/getFoodNtrCpntDbInq02`. 식품의약품안전처_식품영양성분DB정보 (1471000 = 식약처
# 부처 코드, FoodNtrCpntDbInfo02 = 영양성분DB v2).
MFDS_API_BASE_URL: Final[str] = (
    "https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo02/getFoodNtrCpntDbInq02"
)
MFDS_PAGE_KEY: Final[str] = "pageNo"  # 1471000/FoodNtrCpntDbInfo02는 구 표준 사용.
MFDS_SIZE_KEY: Final[str] = "numOfRows"  # 구 표준 (신 표준 페이지네이션 미지원).
MFDS_AUTH_KEY: Final[str] = "serviceKey"
MFDS_DEFAULT_PAGE_SIZE: Final[int] = 100
MFDS_RESPONSE_TYPE_KEY: Final[str] = "type"  # 본 endpoint는 `type=json` (구 표준).
MFDS_RESPONSE_TYPE_JSON: Final[str] = "json"
MFDS_TIMEOUT_SECONDS: Final[float] = 30.0

# 식약처 OpenAPI 응답 키 → 식약처 표준 키 매핑 (검증일자 2026-05-03, 실 응답 sample 기반).
# 원본 키(`AMT_NUM*`)는 식약처 변동 위험으로 어댑터 내부 격리.
MFDS_RAW_KEY_MAP: Final[dict[str, str]] = {
    "FOOD_NM_KR": "name",
    "FOOD_CAT1_NM": "category",  # 1차 식품군 (밥류/면류/...) — 화이트리스트 비교 입력.
    "AMT_NUM1": "energy_kcal",
    "AMT_NUM3": "carbohydrate_g",
    "AMT_NUM4": "protein_g",
    "AMT_NUM5": "fat_g",
    "AMT_NUM6": "sugar_g",
    "AMT_NUM7": "fiber_g",
    "AMT_NUM8": "sodium_mg",
    "AMT_NUM9": "cholesterol_mg",
    "AMT_NUM21": "saturated_fat_g",
    "SERVING_SIZE": "serving_size_g",
    "FOOD_CD": "source_id",
}

# 한식 우선 카테고리 화이트리스트 (식약처 식품군 분류 19종 — DS 검증 의무).
MFDS_KOREAN_FOOD_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "밥류",
        "면류",
        "죽 및 스프류",
        "국 및 탕류",
        "찌개 및 전골류",
        "찜류",
        "구이류",
        "전·적 및 부침류",
        "볶음류",
        "조림류",
        "튀김류",
        "나물·숙채류",
        "김치류",
        "장아찌·절임류",
        "젓갈류",
        "회류",
        "떡류",
        "한과류",
        "음청류",
    }
)


def _normalize_category(value: str | None) -> str | None:
    """카테고리 명 비교 정규화 — NFC + 공백 제거 + middle-dot 변종(U+30FB ``・`` /
    U+318D ``ㆍ``) → U+00B7 ``·`` 통일.

    공공데이터포털 응답은 인코딩 변종이 잦음 — exact-match 비교 시 silent zero-rows
    위험. 본 정규화는 화이트리스트와 응답 양쪽에 적용해 일관 비교.
    """
    if not value:
        return None
    normalized = unicodedata.normalize("NFC", value).strip()
    normalized = normalized.replace("・", "·").replace("ㆍ", "·")
    return normalized or None


_NORMALIZED_KOREAN_FOOD_CATEGORIES: Final[frozenset[str]] = frozenset(
    {_normalize_category(c) or c for c in MFDS_KOREAN_FOOD_CATEGORIES}
)

# 모듈 lazy singleton — Story 2.2/2.3 P1 정합. httpx.AsyncClient는 thread-safe +
# connection pool 내부 보유. 매 호출 새 instance는 ~50ms 오버헤드.
_client: httpx.AsyncClient | None = None
_client_lock = threading.Lock()


class _TransientServerError(Exception):
    """5xx 서버 오류 — tenacity retry 입력. ``FoodSeedAdapterError`` 변환 전 internal marker."""


_TRANSIENT_RETRY_TYPES: Final[tuple[type[BaseException], ...]] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    _TransientServerError,
)
"""Transient 오류만 retry — ``httpx.HTTPError`` 전체를 catch하면 ``HTTPStatusError``
(영구 401/403/404)도 retry 대상이 되어 cost 낭비. 명시 transient subset만 열거 —
Story 2.3 OCR Vision 어댑터 P1 패턴 정합. 5xx는 internal marker로 격리."""


class FoodNutritionRaw(BaseModel):
    """식약처 OpenAPI 응답 → 식약처 표준 키 매핑 결과.

    ``MFDS_RAW_KEY_MAP``의 *식약처 표준 키* 그대로 — 하부 시드 코드는 본 모델만 사용.
    원본 키(``AMT_NUM1`` 등) leak 차단 — 식약처 변동에 대한 1차 격리.

    결측치는 키 omission(None) 보존 — DB jsonb에서 키 누락으로 저장(NULL 채움 X).
    영양 수치는 ``float | None`` — ``None``은 응답 누락.
    """

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    category: str | None = None
    energy_kcal: float | None = None
    carbohydrate_g: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    saturated_fat_g: float | None = None
    sugar_g: float | None = None
    fiber_g: float | None = None
    sodium_mg: float | None = None
    cholesterol_mg: float | None = None
    serving_size_g: float | None = None
    serving_unit: str | None = None
    source_id: str
    source: str = "MFDS_FCDB"


def _get_client() -> httpx.AsyncClient:
    """``httpx.AsyncClient`` lazy singleton — ``MFDS_OPENAPI_KEY`` 미설정 시 503 fail-fast.

    Story 2.2/2.3 정합 — double-checked locking으로 concurrent 첫 호출 race 차단.
    timeout 30초 hard cap을 client 레벨에 주입.
    """
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client

        if not settings.mfds_openapi_key:
            raise FoodSeedSourceUnavailableError(
                "MFDS OpenAPI key not configured (MFDS_OPENAPI_KEY missing)"
            )

        _client = httpx.AsyncClient(timeout=MFDS_TIMEOUT_SECONDS)
        return _client


def _reset_client_for_tests() -> None:
    """테스트 hook — settings env 변경 후 ``_client`` singleton 무효화 (Story 2.2/2.3 정합)."""
    global _client
    if _client is not None:
        # AsyncClient close는 async — 테스트에서는 일반 reset만 (close는 fixture가 책임).
        _client = None


def _to_float_or_none(value: Any) -> float | None:
    """식약처 OpenAPI는 영양 수치를 *문자열 또는 숫자*로 혼용 — graceful float 변환."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _raw_to_standard(item: dict[str, Any]) -> FoodNutritionRaw | None:
    """식약처 OpenAPI 응답 dict → ``FoodNutritionRaw`` 매핑.

    ``name`` / ``source_id`` 결측 시 ``None`` 반환(시드 row 1건 skip — graceful).
    영양 수치는 ``_to_float_or_none``으로 graceful 변환. ``category``는 한식 카테고리
    필터 입력(상위 ``fetch_food_items``가 적용).
    """
    name = item.get("FOOD_NM_KR") or item.get("name")
    source_id = item.get("FOOD_CD") or item.get("source_id")
    if not name or not source_id:
        return None

    payload: dict[str, Any] = {
        "name": str(name).strip(),
        "source_id": str(source_id).strip(),
        "source": "MFDS_FCDB",
        "category": item.get("FOOD_CAT1_NM") or item.get("FOOD_GROUP_NM") or item.get("category"),
        "energy_kcal": _to_float_or_none(item.get("AMT_NUM1") or item.get("energy_kcal")),
        "carbohydrate_g": _to_float_or_none(item.get("AMT_NUM3") or item.get("carbohydrate_g")),
        "protein_g": _to_float_or_none(item.get("AMT_NUM4") or item.get("protein_g")),
        "fat_g": _to_float_or_none(item.get("AMT_NUM5") or item.get("fat_g")),
        "sugar_g": _to_float_or_none(item.get("AMT_NUM6") or item.get("sugar_g")),
        "fiber_g": _to_float_or_none(item.get("AMT_NUM7") or item.get("fiber_g")),
        "sodium_mg": _to_float_or_none(item.get("AMT_NUM8") or item.get("sodium_mg")),
        "cholesterol_mg": _to_float_or_none(item.get("AMT_NUM9") or item.get("cholesterol_mg")),
        "saturated_fat_g": _to_float_or_none(item.get("AMT_NUM21") or item.get("saturated_fat_g")),
        "serving_size_g": _to_float_or_none(item.get("SERVING_SIZE") or item.get("serving_size_g")),
        "serving_unit": item.get("SERVING_UNIT") or item.get("serving_unit"),
    }
    return FoodNutritionRaw.model_validate(payload)


def _is_quota_exceeded(response: httpx.Response, body: dict[str, Any] | None) -> bool:
    """공공데이터포털 quota error 분기 — HTTP 429 또는 응답 본문 ``resultCode`` quota 코드.

    Envelope 패턴 지원:
    - 1471000/FoodNtrCpntDbInfo02: `{"header": {"resultCode": "..."}}` (top-level)
    - 신 표준: `{"response": {"header": {"resultCode": "..."}}}`
    - 단순: `{"resultCode": "..."}`
    """
    if response.status_code == 429:
        return True
    if not isinstance(body, dict):
        return False
    # quota 코드: "22" (LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR).
    # CR(Gemini) — `dict.get(k, {})`의 default는 키 missing 시만 적용. 값이 명시적 `None`
    # 으로 오면 `None`이 반환되어 다음 `.get()`에서 AttributeError. 각 단계마다 isinstance
    # 체크로 명시적 dict 가드.
    result_code: str | None = None
    header = body.get("header")
    if isinstance(header, dict):
        result_code = header.get("resultCode")

    if result_code is None:
        resp = body.get("response")
        if isinstance(resp, dict):
            inner_header = resp.get("header")
            if isinstance(inner_header, dict):
                result_code = inner_header.get("resultCode")

    if result_code is None:
        result_code = body.get("resultCode")
    return result_code in {"22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"}


def _filter_dict_items(raw: list[Any]) -> list[dict[str, Any]]:
    """list 안의 dict 항목만 추출 — 비-dict (null / str / int) silent skip 가시화 로그."""
    filtered = [item for item in raw if isinstance(item, dict)]
    if len(filtered) != len(raw):
        logger.warning(
            "mfds.openapi.non_dict_items_skipped",
            total=len(raw),
            filtered=len(filtered),
        )
    return filtered


def _extract_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    """공공데이터포털 응답 envelope에서 items 배열 추출.

    지원 envelope 패턴:
    - 1471000/FoodNtrCpntDbInfo02: `{"header": {...}, "body": {"items": [...]}}` (top-level body)
    - 신 표준: `{"response": {"body": {"items": [...]}}}` 또는 `{"data": [...]}`
    - 단순: `{"items": [...]}` 또는 single-result(`data`/`items`가 dict)도 list로 wrap.
    """
    data_value = body.get("data")
    if isinstance(data_value, list):
        return _filter_dict_items(data_value)
    if isinstance(data_value, dict):
        # single-result envelope — list로 wrap.
        return [data_value]
    # 1471000 endpoint: top-level `body.items` (response 래퍼 없음)
    top_body = body.get("body")
    if isinstance(top_body, dict):
        top_items = top_body.get("items")
        if isinstance(top_items, list):
            return _filter_dict_items(top_items)
        if isinstance(top_items, dict):
            return [top_items]
    response_block = body.get("response", {})
    body_block = response_block.get("body", {}) if isinstance(response_block, dict) else {}
    items = body_block.get("items") if isinstance(body_block, dict) else None
    if isinstance(items, list):
        return _filter_dict_items(items)
    if isinstance(items, dict):
        return [items]
    if isinstance(body.get("items"), list):
        return _filter_dict_items(body["items"])
    if isinstance(body.get("items"), dict):
        return [body["items"]]
    return []


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(_TRANSIENT_RETRY_TYPES),
    reraise=True,
)
async def _fetch_page(client: httpx.AsyncClient, page_index: int, page_size: int) -> dict[str, Any]:
    """단일 페이지 fetch — tenacity 1회 retry (transient만)."""
    start = time.monotonic()
    params: dict[str, str | int] = {
        MFDS_AUTH_KEY: settings.mfds_openapi_key,
        MFDS_PAGE_KEY: page_index,
        MFDS_SIZE_KEY: page_size,
        MFDS_RESPONSE_TYPE_KEY: MFDS_RESPONSE_TYPE_JSON,
    }
    response = await client.get(MFDS_API_BASE_URL, params=params)
    latency_ms = int((time.monotonic() - start) * 1000)

    body: dict[str, Any] | None
    try:
        body = response.json() if response.content else None
    except ValueError:
        body = None

    if _is_quota_exceeded(response, body):
        raise FoodSeedQuotaExceededError(
            f"MFDS OpenAPI quota exceeded (status={response.status_code})"
        )
    if response.status_code in {401, 403}:
        raise FoodSeedAdapterError(f"MFDS OpenAPI auth failure (status={response.status_code})")
    if response.status_code >= 500:
        # transient — tenacity retry 대상으로 internal marker 변환.
        raise _TransientServerError(f"MFDS OpenAPI server error (status={response.status_code})")
    if response.status_code >= 400:
        raise FoodSeedAdapterError(f"MFDS OpenAPI client error (status={response.status_code})")
    if body is None:
        raise FoodSeedAdapterError("MFDS OpenAPI returned empty body")

    items = _extract_items(body)
    logger.info(
        "mfds.openapi.fetch_page",
        page_index=page_index,
        items_count=len(items),
        latency_ms=latency_ms,
    )
    return {"items": items}


async def fetch_food_items(
    target_count: int = 1500, *, page_size: int = MFDS_DEFAULT_PAGE_SIZE
) -> list[FoodNutritionRaw]:
    """식약처 OpenAPI에서 한식 우선 음식 영양 ``target_count``건 fetch.

    페이지네이션 — page_size 단위 순차 fetch + 한식 카테고리 필터 적용 후
    ``target_count`` 도달까지. 응답 부족(전체 페이지 소진 후 < target_count)도
    *부분 결과* 반환(시드 스크립트가 ZIP fallback 분기 결정).

    오류:
    - ``MFDS_OPENAPI_KEY`` 미설정 — ``FoodSeedSourceUnavailableError`` (즉시 fail-fast).
    - quota / 401·403 / transient retry 실패 — 각 ``FoodSeed*Error`` 변환.
    """
    client = _get_client()
    collected: list[FoodNutritionRaw] = []
    page_index = 1
    max_pages = 100  # 무한 루프 방어 (3K건 / 100건 = 30 페이지 + 여유).
    rows_seen = 0

    while len(collected) < target_count and page_index <= max_pages:
        try:
            page_body = await _fetch_page(client, page_index, page_size)
        except (FoodSeedSourceUnavailableError, FoodSeedQuotaExceededError):
            # 도메인 예외는 그대로 전파 — 시드 스크립트가 분기.
            raise
        except FoodSeedAdapterError:
            raise
        except (httpx.HTTPError, _TransientServerError) as exc:
            # tenacity retry 후 최종 transient 실패 — 503으로 변환.
            raise FoodSeedAdapterError(
                f"MFDS OpenAPI transient failure after retry: {type(exc).__name__}"
            ) from exc

        raw_items = page_body["items"]
        if not raw_items:
            # 빈 페이지 — 전체 페이지 소진 신호.
            break

        rows_seen += len(raw_items)
        for item in raw_items:
            mapped = _raw_to_standard(item)
            if mapped is None:
                continue
            # 한식 카테고리 우선 필터 — 정규화(NFC + middle-dot 통일) 후 화이트리스트
            # 비교. 카테고리 None이면 한식 비분류로 분류 → skip (DS 시점 카테고리 명
            # 변동 가능성 — 운영 부팅 시 응답 샘플 검증 필요).
            normalized_category = _normalize_category(mapped.category)
            if normalized_category and normalized_category in _NORMALIZED_KOREAN_FOOD_CATEGORIES:
                collected.append(mapped)
            if len(collected) >= target_count:
                break

        # 부분 페이지 — 마지막 페이지 도달 신호 (서버는 빈 페이지를 보내지 않을 수도).
        if len(raw_items) < page_size:
            break
        page_index += 1

    # 응답은 있으나 화이트리스트가 모두 silent miss — 카테고리 명 변동 가능성. 빠른 진단
    # 신호 발생 (생산 부팅 시 OpenAPI 카테고리 명 검증 트리거).
    if rows_seen >= page_size * 5 and not collected:
        raise FoodSeedAdapterError(
            f"MFDS OpenAPI category whitelist matched zero rows after {rows_seen} rows "
            f"— verify MFDS_KOREAN_FOOD_CATEGORIES against current API response"
        )

    return collected
