"""Anthropic Claude 어댑터 — Story 3.6 (듀얼 LLM router 보조 LLM, AC8).

`openai_adapter.py` 패턴 정합 — lazy singleton(`AsyncAnthropic` + `threading.Lock`
double-checked locking) + tenacity 3회 backoff + transient subset 명시.

architecture line 689 표기 ``app/adapters/anthropic.py``에서 *deviation* — 모듈명을
``anthropic_adapter.py``로 채택. PyPI ``anthropic`` 패키지와 *import 사이클* 회피
(`app/adapters/anthropic.py` 안에서 ``from anthropic import AsyncAnthropic`` 호출 시
local module이 PyPI 패키지를 가릴 위험). ``openai_adapter.py``와 동일한 사유 + 정합.

오류 매핑(CR D1+MJ-12 — adapter boundary에서 typed 변환):
- ``anthropic.AuthenticationError`` / ``anthropic.PermissionDeniedError`` — 영구 인증/
  권한 → ``LLMRouterUnavailableError``.
- ``anthropic.BadRequestError`` / ``anthropic.NotFoundError`` /
  ``anthropic.UnprocessableEntityError`` — 영구 페이로드/모델 → ``LLMRouterPayloadInvalidError``.
- ``anthropic.APIConnectionError`` / ``anthropic.APITimeoutError`` /
  ``anthropic.RateLimitError`` / ``anthropic.InternalServerError`` *transient* — tenacity
  3회 retry. 최종 실패는 ``reraise=True``라 last underlying exception이 그대로
  propagate(CR MJ-1 — RetryError 아님 — router는 transient subset으로 catch).
- structured output prompt-driven JSON 파싱 실패 → ``LLMRouterPayloadInvalidError``
  (영구 — retry 미포함).
- ``settings.anthropic_api_key`` 미설정 — ``_get_client()`` 진입에서
  ``LLMRouterUnavailableError`` 즉시 raise.

NFR-S5 마스킹: prompt / response 본문은 raw 출력 X. model + total_tokens + latency_ms만.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Final

import anthropic
import httpx
import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.exceptions import (
    LLMRouterPayloadInvalidError,
    LLMRouterUnavailableError,
)
from app.graph.state import FeedbackLLMOutput

logger = structlog.get_logger(__name__)

# 30초 hard cap — `openai_adapter.VISION_TIMEOUT_SECONDS` 정합.
_TIMEOUT_SECONDS: Final[float] = 30.0
_MAX_TOKENS: Final[int] = 1024
_TEMPERATURE: Final[float] = 0.3

_TRANSIENT_RETRY_TYPES: Final[tuple[type[BaseException], ...]] = (
    # CR MJ-8 — `httpx.HTTPError` 부모는 `HTTPStatusError`(4xx 영구)도 포함 → 명시적
    # 네트워크/타임아웃/프로토콜 subset.
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)
"""Transient 오류만 retry — ``anthropic.AuthenticationError`` /
``anthropic.BadRequestError`` 같은 *영구 오류 서브클래스*는 미포함 → retry 무효 +
cost 낭비 차단. ``openai_adapter`` CR P1 fix 패턴 정합."""

_client: AsyncAnthropic | None = None
_client_lock = threading.Lock()

# CR MJ-5 — JSON 추출 regex. 이전 `^...$` strict 패턴은 chatty preamble("Here's:..." 등)
# 시 fail. 본 패턴은 *어디든* fenced block을 찾고, fence가 없으면 첫 balanced `{...}`를
# brace 계산으로 추출.
_JSON_FENCE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL
)


def _get_client() -> AsyncAnthropic:
    """``AsyncAnthropic`` lazy singleton — ``ANTHROPIC_API_KEY`` 미설정 시 503 fail-fast.

    `openai_adapter._get_client()` 정합 — double-checked locking으로 concurrent 첫
    호출 race 차단. ``timeout`` 30초 hard cap을 SDK 레벨에 주입.
    """
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client

        if not settings.anthropic_api_key:
            raise LLMRouterUnavailableError("anthropic_api_key_missing")

        _client = AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=_TIMEOUT_SECONDS,
        )
        return _client


def _reset_client_for_tests() -> None:
    """테스트 hook — settings env 변경 후 ``_client`` singleton 무효화."""
    global _client
    _client = None


def _extract_json_candidate(text: str) -> str:
    """Chatty preamble + fenced block + bare JSON 모두 처리하는 추출 strategy.

    CR MJ-5 — 이전 strict ``^...$`` 패턴은 Claude의 흔한 응답(*"여기 결과입니다:\n```json\n..."*)
    을 떨어뜨려 dual-LLM exhausted까지 도미노 fail. 다음 cascade로 견고화:

    1. fenced block ``` ```json ... ``` ``` (어디든) 추출.
    2. fence 부재 시 첫 ``{``부터 brace-balanced 매칭 ``}``까지 substring (string literal
       내 ``{`` ``}`` 무시).
    3. 모두 실패 시 원문 그대로 반환(json.loads가 실 오류 raise).
    """
    fence = _JSON_FENCE_PATTERN.search(text)
    if fence:
        return fence.group(1).strip()
    first_brace = text.find("{")
    if first_brace == -1:
        return text
    depth = 0
    in_string = False
    escape = False
    for i in range(first_brace, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[first_brace : i + 1]
    return text  # unbalanced — let json.loads emit the real error


def _parse_json_from_text(text_payload: str, model: type[BaseModel]) -> BaseModel:
    """Anthropic 응답 본문에서 JSON 추출 + Pydantic validate.

    Cascade(CR MJ-5):
    1. raw text에 직접 ``json.loads`` 시도 — JSON-only 응답 fast-path.
    2. 실패 시 ``_extract_json_candidate``로 fence/balanced-brace 추출 후 재시도.
    3. 모두 실패 → ``LLMRouterPayloadInvalidError`` (영구).
    """
    stripped = text_payload.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        candidate = _extract_json_candidate(stripped)
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise LLMRouterPayloadInvalidError(
                f"anthropic.payload.json_decode_failed ({type(exc).__name__})"
            ) from exc
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise LLMRouterPayloadInvalidError(
            f"anthropic.payload.validation_failed ({type(exc).__name__})"
        ) from exc


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(_TRANSIENT_RETRY_TYPES),
    reraise=True,
)
async def _call_claude(system: str, user: str) -> tuple[str, int]:
    """Claude messages.create 호출 + tenacity 3회 retry — *transient* 오류만 retry.

    영구 오류(``AuthenticationError`` / ``BadRequestError`` 등)는 ``_TRANSIENT_RETRY_TYPES``
    에 미포함 → 즉시 fail. tenacity 최종 실패는 ``reraise=True``라 last underlying
    exception(``anthropic.APITimeoutError`` 등)을 그대로 propagate (CR MJ-1 — RetryError
    아님).

    Returns ``(text, total_tokens)``. CR MJ-6 — multi-block 응답(thinking/tool_use
    block이 선행)을 처리하기 위해 ``response.content`` 전체 iterate, 첫 비어있지 않은
    text block 사용.
    """
    client = _get_client()
    response = await client.messages.create(
        model=settings.llm_fallback_model,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=_TEMPERATURE,
        max_tokens=_MAX_TOKENS,
    )
    if not response.content:
        raise LLMRouterPayloadInvalidError("anthropic.payload.empty_content")
    text_value: str | None = None
    for block in response.content:
        candidate = getattr(block, "text", None)
        if isinstance(candidate, str) and candidate:
            text_value = candidate
            break
    if text_value is None:
        raise LLMRouterPayloadInvalidError("anthropic.payload.text_missing")
    usage = getattr(response, "usage", None)
    total_tokens = 0
    if usage is not None:
        total_tokens = int(getattr(usage, "input_tokens", 0)) + int(
            getattr(usage, "output_tokens", 0)
        )
    return text_value, total_tokens


async def call_claude_feedback(
    *, system: str, user: str, response_format: type[BaseModel]
) -> FeedbackLLMOutput:
    """Claude messages.create → ``FeedbackLLMOutput`` Pydantic instance.

    ``response_format``은 Pydantic 모델 클래스(`FeedbackLLMOutput`만 사용 — schema
    parametric은 향후 확장 여지). prompt-driven JSON으로 LLM이 schema 따르도록 시스템
    프롬프트가 강제(`app.graph.prompts.feedback._JSON_SCHEMA_INSTRUCTION`).

    오류 매핑 (CR D1+MJ-12 — adapter boundary에서 typed 변환):
    - tenacity 3회 transient 최종 실패 (``reraise=True``라 last exc) — caller(router)가
      ``_ANTHROPIC_TRANSIENT`` subset에서 catch.
    - ``LLMRouterUnavailableError`` (API key 미설정 / AuthenticationError /
      PermissionDeniedError) — caller(router)에서 catch.
    - ``LLMRouterPayloadInvalidError`` (JSON / Pydantic 위반 / BadRequestError /
      NotFoundError / UnprocessableEntity) — caller(router)에서 catch.

    NFR-S5 — system / user / response 본문 raw 출력 X. model + total_tokens + latency_ms만
    (CR mn-26 — token_count 추가).
    """
    start = time.monotonic()
    try:
        text_value, total_tokens = await _call_claude(system=system, user=user)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        # CR D1 — 영구 인증/권한 오류 → router가 dual exhausted로 진행하도록 typed 변환.
        raise LLMRouterUnavailableError(f"anthropic.feedback.{type(exc).__name__}") from exc
    except (
        anthropic.BadRequestError,
        anthropic.NotFoundError,
        anthropic.UnprocessableEntityError,
    ) as exc:
        # CR D1 — 영구 페이로드/모델 오류.
        raise LLMRouterPayloadInvalidError(f"anthropic.feedback.{type(exc).__name__}") from exc

    parsed = _parse_json_from_text(text_value, response_format)
    if not isinstance(parsed, FeedbackLLMOutput):
        raise LLMRouterPayloadInvalidError(
            f"anthropic.payload.unexpected_model ({type(parsed).__name__})"
        )

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "anthropic.call_claude_feedback",
        model=settings.llm_fallback_model,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
    )
    return parsed


__all__ = [
    "call_claude_feedback",
]
