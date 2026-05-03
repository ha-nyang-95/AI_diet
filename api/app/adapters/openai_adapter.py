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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.exceptions import (
    FoodSeedAdapterError,
    MealOCRPayloadInvalidError,
    MealOCRUnavailableError,
)
from app.graph.state import ClarificationOption

logger = structlog.get_logger(__name__)

# Vision 모델 — `gpt-4o-mini`는 한식 정확도 부족(영업 데모는 짜장면+군만두 사진에서
# 정확 추출 필수). Story 8 cost polish 시점에 `gpt-4o-mini` 또는 snapshot pin 검토.
VISION_MODEL: Final[str] = "gpt-4o"

# Story 3.1 — text-embedding-3-small (1536 dim, $0.02/1M tokens, 8K context).
# `text-embedding-3-large`(3072 dim)는 architecture vector(1536) 컬럼 변경 + 비용 5배로 OUT (D2).
EMBEDDING_MODEL: Final[str] = "text-embedding-3-small"
EMBEDDING_DIMENSIONS: Final[int] = 1536
# 300건 batch — OpenAI embeddings API 한계(2048건/요청 + 8K context 토큰 합산) 안전치.
# 음식명 평균 ~10 토큰 × 300건 = 3K 토큰. 1500건 시드 = 5 batches → cold start latency ↓
# (100건 batch 대비 round-trip 1/3) — D6 결정.
EMBEDDING_BATCH_SIZE: Final[int] = 300

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


# ---------------------------------------------------------------------------
# Story 3.1 — embeddings (food RAG 시드)
# ---------------------------------------------------------------------------


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(_TRANSIENT_RETRY_TYPES),
    reraise=True,
)
async def _call_embedding(client: AsyncOpenAI, batch: list[str]) -> list[list[float]]:
    """Embeddings API 단일 batch 호출 + tenacity 1회 retry — *transient*만 retry.

    영구 오류(``openai.AuthenticationError`` / ``openai.BadRequestError`` 등)는
    ``_TRANSIENT_RETRY_TYPES``에 미포함 → 즉시 fail (retry 무효 + cost 낭비 차단).
    Story 2.3 OCR Vision 패턴 정합.
    """
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=batch,
    )
    return [item.embedding for item in response.data]


async def embed_texts(
    texts: list[str], *, batch_size: int = EMBEDDING_BATCH_SIZE
) -> list[list[float]]:
    """텍스트 리스트 → 1536-dim 임베딩 리스트 — Story 3.1 음식 영양 RAG 시드 입력.

    - 빈 입력 — 빈 리스트 즉시 반환 (API 호출 X / cost 0).
    - ``len(texts) > batch_size`` — 자동 chunk + 결과 concat (1500건 → 5 batches).
    - SDK singleton 공유 — Vision OCR ``_get_client()`` 재활용 (D7 connection pool 공유).
    - 차원 검증 — 응답 임베딩 길이가 ``EMBEDDING_DIMENSIONS``(1536) 미일치 시
      ``FoodSeedAdapterError`` (모델 변경 회귀 차단).

    오류 매핑:
    - ``OPENAI_API_KEY`` 미설정 — ``_get_client()``가 ``MealOCRUnavailableError(503)``
      raise — 시드 컨텍스트에서는 그대로 전파(상위 503 의미 동등 + 별 변환 X — AC3 명시).
    - tenacity retry 후 transient 실패 / 영구 오류 — ``FoodSeedAdapterError(503)``.

    NFR-S5 마스킹 — ``texts`` raw 출력 X (잠재 raw_text 포함 가능 — Story 2.3 정합).
    """
    if not texts:
        return []

    client = _get_client()
    start = time.monotonic()
    embeddings: list[list[float]] = []

    for chunk_start in range(0, len(texts), batch_size):
        batch = texts[chunk_start : chunk_start + batch_size]
        try:
            batch_embeddings = await _call_embedding(client, batch)
        except _TRANSIENT_RETRY_TYPES as exc:
            # tenacity retry 후 최종 transient 실패 — 503 변환.
            raise FoodSeedAdapterError(
                f"OpenAI embeddings transient failure after retry: {type(exc).__name__}"
            ) from exc
        except openai.APIError as exc:
            # 영구 오류(AuthenticationError, BadRequestError 등) — retry 무효 + 즉시 fail.
            raise FoodSeedAdapterError(
                f"OpenAI embeddings API failure: {type(exc).__name__}"
            ) from exc

        for i, vector in enumerate(batch_embeddings):
            if len(vector) != EMBEDDING_DIMENSIONS:
                raise FoodSeedAdapterError(
                    f"OpenAI embeddings: dimension mismatch "
                    f"(expected {EMBEDDING_DIMENSIONS}, got {len(vector)} at batch index {i})"
                )
        embeddings.extend(batch_embeddings)

    latency_ms = int((time.monotonic() - start) * 1000)
    # NFR-S5 — texts raw 노출 X. count + model + latency만.
    logger.info(
        "openai.embeddings.batch",
        texts_count=len(texts),
        batch_count=(len(texts) + batch_size - 1) // batch_size,
        model=EMBEDDING_MODEL,
        latency_ms=latency_ms,
    )
    return embeddings


# ---------------------------------------------------------------------------
# Story 3.4 — 텍스트 LLM 함수 3종 (parse_meal_text + rewrite_food_query +
# generate_clarification_options)
# ---------------------------------------------------------------------------

# `gpt-4o-mini` — architecture line 509 정합 (메인 텍스트 LLM). Vision은 `gpt-4o`,
# 텍스트 parse/rewrite/clarify는 `gpt-4o-mini` (cost 1/15).
PARSE_MODEL: Final[str] = "gpt-4o-mini"

PARSE_SYSTEM_PROMPT: Final[str] = (
    "한국어 식단 텍스트에서 음식 항목을 추출하세요. "
    "각 항목 name(한국어 표준 음식명), quantity(자유 텍스트 — '1인분'/'200g'/null), "
    "confidence(0~1)를 반환하세요. "
    "음식이 아닌 텍스트(인사말/감정 등)는 빈 items 배열을 반환하세요. "
    "name에 콤마(,) 포함 금지 — 항목 boundary 모호 회피."
)

REWRITE_SYSTEM_PROMPT: Final[str] = (
    "한국어 음식명이 모호한 경우 가능한 변형 2-4건을 생성하세요. "
    "예: '포케볼' → ['연어 포케', '참치 포케', '베지 포케']. "
    "단순 동의어가 아닌 *세부 항목 분기* 형태로 생성하세요. "
    "변형은 한국어 표준 음식명으로, 짧고 명확하게."
)

CLARIFICATION_SYSTEM_PROMPT: Final[str] = (
    "사용자에게 '어떤 ◯◯인가요?' 형태로 물을 옵션 2-4건을 생성하세요. "
    "각 옵션의 label은 짧은 한국어(≤50자), value는 라벨 + 양 추정(예: '연어 포케 1인분', ≤80자). "
    "최대 4건. 변형은 *세부 항목 분기* 형태."
)


class RewriteVariants(BaseModel):
    """`rewrite_food_query` 응답 — 한국어 음식명 변형 2-4건."""

    model_config = ConfigDict(extra="forbid")

    variants: list[str] = Field(min_length=1, max_length=4)


class ClarificationVariants(BaseModel):
    """`generate_clarification_options` 응답 — 재질문 옵션 2-4건."""

    model_config = ConfigDict(extra="forbid")

    options: list[ClarificationOption] = Field(min_length=1, max_length=4)


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(_TRANSIENT_RETRY_TYPES),
    reraise=True,
)
async def _call_parse_meal_text(text_input: str) -> ParsedMeal:
    """식단 텍스트 → ParsedMeal 호출 + tenacity 1회 retry."""
    client = _get_client()
    response = await client.beta.chat.completions.parse(
        model=PARSE_MODEL,
        messages=[
            {"role": "system", "content": PARSE_SYSTEM_PROMPT},
            {"role": "user", "content": text_input},
        ],
        response_format=ParsedMeal,
        temperature=0.0,
        max_tokens=VISION_MAX_TOKENS,
    )
    if not response.choices:
        raise MealOCRPayloadInvalidError("parse_meal_text response: no choices returned")
    message = response.choices[0].message
    refusal = getattr(message, "refusal", None)
    if refusal:
        raise MealOCRPayloadInvalidError(f"parse_meal_text response: model refusal ({refusal})")
    parsed = message.parsed
    if parsed is None:
        raise MealOCRPayloadInvalidError("parse_meal_text response: parsed payload missing")
    return parsed


async def parse_meal_text(text: str) -> ParsedMeal:
    """식단 텍스트 → ``ParsedMeal`` (items list).

    빈 입력(``text.strip() == ""``)은 즉시 ``ParsedMeal(items=[])`` 반환 — API 호출 X
    / cost 0. 그 외는 ``gpt-4o-mini`` structured output 호출 + tenacity 1회 retry.

    오류 매핑(Vision OCR 패턴 정합):
    - transient 후 → ``MealOCRUnavailableError(503)``,
    - schema 위반 → ``MealOCRPayloadInvalidError(502)``.

    NFR-S5 — text raw 출력 X. items_count + latency만.
    """
    if not text.strip():
        return ParsedMeal(items=[])

    start = time.monotonic()
    try:
        parsed = await _call_parse_meal_text(text)
    except (httpx.HTTPError, openai.APIError, openai.RateLimitError) as exc:
        raise MealOCRUnavailableError(
            f"parse_meal_text transient failure after retry: {type(exc).__name__}"
        ) from exc
    except ValidationError as exc:
        raise MealOCRPayloadInvalidError(
            f"parse_meal_text response: schema validation failed ({exc})"
        ) from exc
    except MealOCRPayloadInvalidError:
        raise

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "openai.parse_meal_text",
        items_count=len(parsed.items),
        model=PARSE_MODEL,
        latency_ms=latency_ms,
    )
    return parsed


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(_TRANSIENT_RETRY_TYPES),
    reraise=True,
)
async def _call_rewrite_food_query(query: str) -> RewriteVariants:
    """음식명 변형 생성 호출 + tenacity 1회 retry."""
    client = _get_client()
    response = await client.beta.chat.completions.parse(
        model=PARSE_MODEL,
        messages=[
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        response_format=RewriteVariants,
        temperature=0.0,
        max_tokens=VISION_MAX_TOKENS,
    )
    if not response.choices:
        raise MealOCRPayloadInvalidError("rewrite_food_query response: no choices returned")
    message = response.choices[0].message
    refusal = getattr(message, "refusal", None)
    if refusal:
        raise MealOCRPayloadInvalidError(f"rewrite_food_query response: model refusal ({refusal})")
    parsed = message.parsed
    if parsed is None:
        raise MealOCRPayloadInvalidError("rewrite_food_query response: parsed payload missing")
    return parsed


async def rewrite_food_query(query: str) -> RewriteVariants:
    """모호한 음식명 → ``RewriteVariants`` (변형 2-4건).

    빈 입력 시 graceful fallback ``RewriteVariants(variants=[query or "unknown"])``
    반환 — 호출자(`rewrite_query` 노드)가 빈 응답 cost 낭비 차단.

    NFR-S5 — query raw 출력 X. variants_count + latency만.
    """
    fallback_query = query.strip() or "unknown"
    if not query.strip():
        # 빈 입력 — API 호출 X / cost 0. 호출자 graceful 처리 신호.
        return RewriteVariants(variants=[fallback_query])

    start = time.monotonic()
    try:
        parsed = await _call_rewrite_food_query(query)
    except (httpx.HTTPError, openai.APIError, openai.RateLimitError) as exc:
        raise MealOCRUnavailableError(
            f"rewrite_food_query transient failure after retry: {type(exc).__name__}"
        ) from exc
    except ValidationError as exc:
        raise MealOCRPayloadInvalidError(
            f"rewrite_food_query response: schema validation failed ({exc})"
        ) from exc
    except MealOCRPayloadInvalidError:
        raise

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "openai.rewrite_food_query",
        variants_count=len(parsed.variants),
        model=PARSE_MODEL,
        latency_ms=latency_ms,
    )
    return parsed


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(_TRANSIENT_RETRY_TYPES),
    reraise=True,
)
async def _call_generate_clarification_options(query: str) -> ClarificationVariants:
    """재질문 옵션 생성 호출 + tenacity 1회 retry."""
    client = _get_client()
    response = await client.beta.chat.completions.parse(
        model=PARSE_MODEL,
        messages=[
            {"role": "system", "content": CLARIFICATION_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        response_format=ClarificationVariants,
        temperature=0.0,
        max_tokens=VISION_MAX_TOKENS,
    )
    if not response.choices:
        raise MealOCRPayloadInvalidError(
            "generate_clarification_options response: no choices returned"
        )
    message = response.choices[0].message
    refusal = getattr(message, "refusal", None)
    if refusal:
        raise MealOCRPayloadInvalidError(
            f"generate_clarification_options response: model refusal ({refusal})"
        )
    parsed = message.parsed
    if parsed is None:
        raise MealOCRPayloadInvalidError(
            "generate_clarification_options response: parsed payload missing"
        )
    return parsed


async def generate_clarification_options(query: str) -> ClarificationVariants:
    """모호한 음식명 → 재질문 ``ClarificationOption`` 옵션 2-4건.

    빈 입력 시 fallback ``[ClarificationOption(label="알 수 없음", value=query or "")]``
    1건 강제 — 호출자(`request_clarification` 노드)가 UI 깨짐 회피.

    상한 ``settings.clarification_max_options`` 적용은 *호출자 책임* — 본 함수는 LLM
    응답 그대로(2-4건). 호출자가 settings 상한으로 ``options[:max_options]`` truncate.

    NFR-S5 — query raw 출력 X. options_count + latency만.
    """
    if not query.strip():
        return ClarificationVariants(
            options=[ClarificationOption(label="알 수 없음", value=query or "unknown")]
        )

    start = time.monotonic()
    try:
        parsed = await _call_generate_clarification_options(query)
    except (httpx.HTTPError, openai.APIError, openai.RateLimitError) as exc:
        raise MealOCRUnavailableError(
            f"generate_clarification_options transient failure after retry: {type(exc).__name__}"
        ) from exc
    except ValidationError as exc:
        raise MealOCRPayloadInvalidError(
            f"generate_clarification_options response: schema validation failed ({exc})"
        ) from exc
    except MealOCRPayloadInvalidError:
        raise

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "openai.generate_clarification_options",
        options_count=len(parsed.options),
        model=PARSE_MODEL,
        latency_ms=latency_ms,
    )
    return parsed
