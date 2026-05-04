"""Sentry 초기화 + before_send hook (NFR-S5 마스킹 anchor — Story 8.4에서 정교화)."""

from __future__ import annotations

import re
from typing import Any, Final

import sentry_sdk
from sentry_sdk.types import Event, Hint

from app.core.config import settings

# Story 3.6 anchor — LLM router/Anthropic adapter capture_exception 시 prompt/response/
# raw_text 키가 extra/contexts에 leak될 가능성 차단. Story 8.4 polish가 정교화 — 본
# 단계는 *anchor*만(메모리 [feedback_distinguish_ceremony_from_anchor] 정합).
#
# CR Gemini G1 — ``_MESSAGE_LEAK_PATTERN``이 catch하는 키와 정합. ``content``/``messages``
# 가 structured ``extra``/``contexts`` dict에 들어와도 동일 마스킹 적용.
_MASKED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "prompt",
        "response_text",
        "raw_text",
        "system",
        "user_prompt",
        "content",
        "messages",
    }
)
_MASK_PLACEHOLDER: Final[str] = "***"

# CR C2 — SDK BadRequestError 등의 message에 raw_text/prompt 본문이 echo되는
# 패턴(`'content': "..."` / `"raw_text": "..."`)을 정규식으로 ``"***"`` 대체.
#
# CR Gemini G2 — 이전 ``(.*?)(\2)``는 escape된 따옴표(``\\"``) 발견 시 첫 closing quote
# 에서 끊겨 partial leak 회귀. ``((?:(?!\2).|\\.)*)``는 escape sequence를 토큰으로 소비
# 한 뒤 closing quote에 도달하므로 본문 전체 마스킹 보장.
_MESSAGE_LEAK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(['\"](?:content|raw_text|prompt|response_text|system|user_prompt|messages)['\"]\s*[:=]\s*)"
    r"(['\"])"  # Group 2: opening quote
    r"((?:(?!\2).|\\.)*)"  # Group 3: 본문 — escape 문자 토큰 우선 소비
    r"(\2)",  # Group 4: closing quote (== group 2)
    flags=re.DOTALL,
)


def _mask_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """dict 내부 ``_MASKED_KEYS`` value를 ``"***"``로 치환 (anchor 가드).

    CR Gemini G3 — list of dicts 처리 추가. Sentry event payload(`extra`/`contexts`/
    frame `vars`)는 list of dict 구조를 흔히 포함 — 이전 구현은 list 안의 dict를 통과시켜
    민감 키가 마스킹 우회되던 회귀.
    """
    if not isinstance(payload, dict):
        return payload
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _MASKED_KEYS:
            cleaned[key] = _MASK_PLACEHOLDER
        elif isinstance(value, dict):
            cleaned[key] = _mask_dict(value)
        elif isinstance(value, list):
            cleaned[key] = [_mask_dict(v) if isinstance(v, dict) else v for v in value]
        else:
            cleaned[key] = value
    return cleaned


def mask_event(event: Event, hint: Hint) -> Event | None:
    """Sentry before_send hook — 민감정보 마스킹 anchor.

    현재 가드:
    - ``extra`` / ``contexts.*`` dict 안의 ``prompt`` / ``response_text`` / ``raw_text`` /
      ``system`` / ``user_prompt`` 키 value → ``"***"``.
    - ``exception.values[*].stacktrace.frames[*].vars`` dict의 동일 키 마스킹
      (CR C2 — frame locals 통한 prompt/raw_text leak 차단).
    - ``exception.values[*].value`` 문자열의 ``raw_text``/``prompt``/``response`` 키워드
      뒤 따옴표 안 본문 ``"***"`` 대체 (CR C2 — SDK BadRequestError 메시지의 본문 echo 방어).

    Story 8.4 polish 시점에 정교화:
    - ``request.headers.Authorization`` / ``request.cookies`` → ``"***"``
    - JWT/secret 정규식 마스킹
    - structlog ``mask_processor`` 통합
    """
    _ = hint
    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = _mask_dict(extra)
    contexts = event.get("contexts")
    if isinstance(contexts, dict):
        cleaned_contexts: dict[str, Any] = {}
        for ctx_name, ctx_value in contexts.items():
            cleaned_contexts[ctx_name] = (
                _mask_dict(ctx_value) if isinstance(ctx_value, dict) else ctx_value
            )
        event["contexts"] = cleaned_contexts
    exception = event.get("exception")
    if isinstance(exception, dict):
        values = exception.get("values")
        if isinstance(values, list):
            for entry in values:
                if not isinstance(entry, dict):
                    continue
                value_str = entry.get("value")
                if isinstance(value_str, str):
                    entry["value"] = _mask_exception_message(value_str)
                stacktrace = entry.get("stacktrace")
                if isinstance(stacktrace, dict):
                    frames = stacktrace.get("frames")
                    if isinstance(frames, list):
                        for frame in frames:
                            if not isinstance(frame, dict):
                                continue
                            vars_dict = frame.get("vars")
                            if isinstance(vars_dict, dict):
                                frame["vars"] = _mask_dict(vars_dict)
    return event


def _mask_exception_message(message: str) -> str:
    """SDK 예외 메시지의 ``content/raw_text/prompt`` 등 키 뒤 본문을 ``"***"``로 대체."""
    return _MESSAGE_LEAK_PATTERN.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{_MASK_PLACEHOLDER}{m.group(4)}",
        message,
    )


def init_sentry() -> None:
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.1,
        send_default_pii=False,
        # CR C1 — frame locals를 통한 prompt/raw_text leak 차단.
        include_local_variables=False,
        # request body는 절대 첨부 X.
        max_request_body_size="never",
        # capture_message에 자동 stacktrace 첨부도 차단(MJ-29 변형 가드).
        attach_stacktrace=False,
        before_send=mask_event,
    )
