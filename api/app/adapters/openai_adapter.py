"""OpenAI Vision 어댑터 — Story 2.3 (식단 사진 OCR Vision 추출).

GPT-4o + structured outputs (`response_format=ParsedMeal`) + tenacity retry +
30초 hard cap timeout으로 식단 사진에서 한국어 표준 음식명·추정 양·신뢰도를 추출.

architecture line 689 명시 ``app/adapters/openai.py`` 표기에서 *deviation* —
모듈명을 ``openai_adapter.py``로 채택. PyPI ``openai`` 패키지와 *import 사이클*
회피(`app/adapters/openai.py` 안에서 ``from openai import AsyncOpenAI`` 호출 시
local module이 PyPI 패키지를 가릴 위험). architecture 표기는 *abstract role*로
해석 — 실제 import 안전성 우선(AC10 deviation 명시).

P1 — Story 2.2 ``r2.py`` 정합 — boto3 client 모듈 lazy singleton + ``threading.Lock``
double-checked locking. ``AsyncOpenAI`` 자체는 native async + thread-safe httpx
client 보유 — 매 호출 새 instance는 connection pool 재구성 비용. ``_reset_client_for_tests``
helper로 monkeypatch 후 singleton 무효화.

오류 매핑(라우터에서 RFC 7807 변환):
- ``openai.AuthenticationError`` / ``openai.BadRequestError`` 등 *영구 오류* — 즉시
  raise (retry 무효 + cost 낭비 차단). 본 어댑터는 ``MealOCRUnavailableError(503)``으로
  통합 변환 — *영업 데모 환경에서 키 누락은 운영 장애*로 분류 (AC5 정합).
- ``httpx.TimeoutException`` / ``httpx.HTTPError`` / ``openai.APIError`` /
  ``openai.RateLimitError`` *transient* — tenacity 1회 retry 후 ``MealOCRUnavailableError(503)``.
- structured outputs 위반 (``response.choices[0].message.parsed is None`` 또는
  ``ValidationError``) — ``MealOCRPayloadInvalidError(502)``.
- ``settings.openai_api_key`` 미설정 — ``_get_client()`` 진입에서
  ``MealOCRUnavailableError(503)`` 즉시 raise(부팅 통과 + runtime fail-fast).

NFR-S5 마스킹: ``image_url``은 raw 출력 X — image_key forward로 단일화.
``parsed_items`` raw 내용도 로그 X(잠재 식습관 추론) — items_count + min/max
confidence + latency_ms + model만.
"""

from __future__ import annotations

import threading
import time
from typing import Final

import httpx
import openai
import structlog
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError, field_validator
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.exceptions import (
    MealOCRPayloadInvalidError,
    MealOCRUnavailableError,
)

logger = structlog.get_logger(__name__)

# Vision 모델 — `gpt-4o-mini`는 한식 정확도 부족(영업 데모는 짜장면+군만두 사진에서
# 정확 추출 필수). Story 8 cost polish 시점에 `gpt-4o-mini` 또는 snapshot pin 검토.
VISION_MODEL: Final[str] = "gpt-4o"

# 30초 hard cap — 모바일 4G + p95 4초 soft target + tenacity 1회 retry 여유.
VISION_TIMEOUT_SECONDS: Final[float] = 30.0

# items 20개 cap + 결정성 토큰 여유. structured outputs는 schema enforce하므로
# max_tokens는 *안전 cap*만 — items 다수 추출 시도 cost 폭발 방지.
VISION_MAX_TOKENS: Final[int] = 512

VISION_SYSTEM_PROMPT: Final[str] = (
    "당신은 한국 음식 사진을 분석하는 영양 분석 보조 시스템입니다. "
    "사진에서 보이는 음식 항목을 한국어 표준 음식명으로 추출하세요. "
    "각 항목에 추정 양(예: '1인분', '4개', '300g')과 0.0~1.0 신뢰도(confidence)를 부여하세요. "
    "보이지 않는 항목 추측·환각 금지 — 식별 가능한 항목만 출력하세요. "
    "음식이 아닌 사진(풍경/사물 등)은 빈 items 배열을 반환하세요."
)

# 사용자 메시지 텍스트 — 짧게 유지(시스템 프롬프트 우선).
_USER_TEXT_PROMPT: Final[str] = "이 사진의 음식을 분석하세요."

# 모듈 lazy singleton — Story 2.2 r2.py P1 패턴 정합. AsyncOpenAI는 thread-safe +
# httpx connection pool 내부 보유, 매 호출 재생성 시 ~50ms+ 오버헤드.
_client: AsyncOpenAI | None = None
_client_lock = threading.Lock()


class ParsedMealItem(BaseModel):
    """OCR Vision 추출 단일 항목.

    - ``name``: 한국어 표준 음식명 (예: ``"짜장면"``). 빈 문자열 거부 (Vision 출력
      신뢰 + 사용자 확인 카드 후 편집 가능). max_length 50 — DB jsonb + UI 표시
      합리적 상한. CR P7 fix(2026-04-30): 콤마 거부 — ``_format_parsed_items_to_raw_text``
      가 ``", "``로 항목을 join하므로 name 콤마 포함 시 raw_text boundary 모호 (예:
      ``"감자, 양파" + "500g"`` → ``"감자, 양파 500g"`` 잘못 분리). 사용자 편집 round-trip
      안정성 보장.
    - ``quantity``: 추정 양 (예: ``"1인분"`` / ``"4개"`` / ``"300g"``). 빈 quantity
      허용 (*"바나나"* 처럼 양 없는 항목 대응) — ``min_length=0``.
    - ``confidence``: 0.0~1.0 신뢰도 — 임계값 0.6 미만은 모바일 forced confirmation.
    """

    name: str = Field(min_length=1, max_length=50)
    quantity: str = Field(min_length=0, max_length=30)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("name")
    @classmethod
    def _reject_comma_in_name(cls, value: str) -> str:
        if "," in value:
            raise ValueError("name must not contain comma (raw_text boundary 모호 방지)")
        return value


class ParsedMeal(BaseModel):
    """OCR Vision 응답 — items 배열만(``model``/``latency_ms``는 라우터에서 측정·forward)."""

    items: list[ParsedMealItem] = Field(max_length=20)


def _get_client() -> AsyncOpenAI:
    """``AsyncOpenAI`` lazy singleton — ``OPENAI_API_KEY`` 미설정 시 503 fail-fast.

    Story 2.2 ``r2._get_client()`` 정합 — double-checked locking으로 concurrent
    첫 호출 race 차단. ``timeout`` 30초 hard cap을 SDK 레벨에 주입 (httpx
    request timeout — Vision 호출당 단일 round-trip 보장).
    """
    global _client
    # Hot path — Lock 우회 (참조 set은 GIL 원자적).
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client

        if not settings.openai_api_key:
            raise MealOCRUnavailableError("OpenAI API key not configured (OPENAI_API_KEY missing)")

        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=VISION_TIMEOUT_SECONDS,
        )
        return _client


def _reset_client_for_tests() -> None:
    """테스트 hook — settings env 변경 후 ``_client`` singleton 무효화 (Story 2.2 정합)."""
    global _client
    _client = None


_TRANSIENT_RETRY_TYPES: Final[tuple[type[BaseException], ...]] = (
    httpx.HTTPError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)
"""Transient 오류만 retry — ``openai.APIError`` 전체를 catch하면 ``AuthenticationError``
/ ``BadRequestError`` 같은 *영구 오류 서브클래스*도 retry 대상이 되어 cost 낭비 + 영구
오류 mask. CR P1 fix(2026-04-30) — 명시적 transient subset만 열거."""


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(_TRANSIENT_RETRY_TYPES),
    reraise=True,
)
async def _call_vision(image_url: str) -> ParsedMeal:
    """Vision API 호출 + tenacity retry 1회 — *transient 5xx + RateLimitError +
    네트워크*만 retry. ``openai.AuthenticationError`` / ``openai.BadRequestError`` 등
    *영구 오류*는 ``_TRANSIENT_RETRY_TYPES``에 미포함 → 즉시 fail
    (retry 무효 + cost 낭비 차단).
    """
    client = _get_client()
    response = await client.beta.chat.completions.parse(
        model=VISION_MODEL,
        messages=[
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _USER_TEXT_PROMPT},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
        response_format=ParsedMeal,
        temperature=0.0,
        max_tokens=VISION_MAX_TOKENS,
    )
    # CR P3 fix(2026-04-30) — empty choices 가드 (rare API edge에서 IndexError → 500
    # 회피, 502로 정합).
    if not response.choices:
        raise MealOCRPayloadInvalidError("Vision response: no choices returned")
    message = response.choices[0].message
    # CR P4 fix(2026-04-30) — refusal 분기 distinct 처리. moderation block과 schema
    # fail이 동일 reason으로 surface되던 구조 → ops 진단 가능하도록 분리.
    refusal = getattr(message, "refusal", None)
    if refusal:
        raise MealOCRPayloadInvalidError(f"Vision response: model refusal ({refusal})")
    parsed = message.parsed
    if parsed is None:
        # OpenAI SDK가 schema 강제하나 *방어로* — null content 대응.
        raise MealOCRPayloadInvalidError("Vision response: parsed payload missing")
    return parsed


async def parse_meal_image(image_url: str, *, image_key: str | None = None) -> ParsedMeal:
    """식단 사진 URL → ``ParsedMeal`` (items list).

    ``image_url``은 R2 public CDN URL 직접 — base64 회피(메모리 + Railway egress).
    ``image_key``는 *로깅 용도*만 (NFR-S5 — image_url raw 출력 X). 호출자(라우터)가
    image_key를 forward해 1줄 로그에 통일.

    오류 변환 — tenacity retry 후 모든 transient 실패 → ``MealOCRUnavailableError(503)``.
    structured outputs 위반 → ``MealOCRPayloadInvalidError(502)``.
    """
    start = time.monotonic()
    try:
        parsed = await _call_vision(image_url)
    except (httpx.HTTPError, openai.APIError, openai.RateLimitError) as exc:
        # tenacity retry 후 최종 실패 — typed 503으로 변환.
        raise MealOCRUnavailableError(
            f"Vision API transient failure after retry: {type(exc).__name__}"
        ) from exc
    except ValidationError as exc:
        # SDK가 자동 Pydantic 역직렬화 시 schema 위반 ValidationError raise.
        raise MealOCRPayloadInvalidError(
            f"Vision response: schema validation failed ({exc})"
        ) from exc
    except MealOCRPayloadInvalidError:
        # _call_vision 내부에서 raise한 것은 그대로 전파(cost 낭비 차단 — retry X).
        raise

    latency_ms = int((time.monotonic() - start) * 1000)
    confidences = [item.confidence for item in parsed.items]
    logger.info(
        "ocr.vision.parsed",
        image_key=image_key,
        items_count=len(parsed.items),
        min_confidence=min(confidences) if confidences else None,
        max_confidence=max(confidences) if confidences else None,
        model=VISION_MODEL,
        latency_ms=latency_ms,
    )
    return parsed
