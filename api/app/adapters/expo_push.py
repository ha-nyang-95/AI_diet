"""Expo push adapter — Story 4.2 (APScheduler nudge 미기록 푸시 + 딥링크).

`exponent-server-sdk>=2.2`(expo-community maintained) wrap. SDK는 sync(`requests.Session`
기반)이라 FastAPI async 흐름에는 ``asyncio.to_thread`` 위임. ``openai_adapter.py`` /
``anthropic_adapter.py`` 패턴 정합 — lazy singleton(``threading.Lock`` double-checked
locking) + tenacity 3회 backoff + transient subset 명시.

오류 매핑 (CR D1+MJ-12 — adapter boundary에서 typed 변환 — Story 3.6 ``llm_router`` 패턴 정합):

- ``requests.exceptions.ConnectionError`` / ``Timeout`` — *transient*: 3회 retry →
  ``ExpoPushUnavailableError``.
- ``requests.exceptions.HTTPError`` 5xx / ``PushServerError`` 5xx — *transient*: 3회 retry.
- ``requests.exceptions.HTTPError`` 401 — 영구 인증/토큰 회전 → ``ExpoPushAuthError`` (retry X).
- ``requests.exceptions.HTTPError`` 그 외 4xx — 영구 페이로드 → ``ExpoPushError`` (retry X).
- ``settings.expo_access_token`` 빈 문자열은 *허용* — Expo SDK 자체 dev 무인증 모드 정합.
  prod에서는 EAS Console *enhanced security mode* 활성 시점에 401 → ``ExpoPushAuthError``로
  운영자 신호.

NFR-S5 마스킹 정합: push payload(`title`/`body`/`data`)에 raw PII 미포함(일반 카피 + URL deep
link만). ``expo_push_token``은 Expo 자체 식별자(사용자 신원과 결합 X) — Sentry/LangSmith
룰셋 추가 X.

DeviceNotRegistered 처리: 본 어댑터는 *raw ticket/receipt 반환만*. 호출 측
(``app/workers/nudge_scheduler.py``)이 ticket.details.error == 'DeviceNotRegistered' 분기
검사 후 ``notification_service.revoke_push_token`` 호출(Story 4.1 SOT 재사용).
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Final

import requests
import structlog
from exponent_server_sdk import (
    PushClient,
    PushMessage,
    PushReceipt,
    PushServerError,
    PushTicket,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.exceptions import (
    ExpoPushAuthError,
    ExpoPushError,
    ExpoPushUnavailableError,
)

logger = structlog.get_logger(__name__)

# 30초 hard cap — `openai_adapter` / `anthropic_adapter` 정합. EAS Push API는 대형
# 요청에서 최대 ~10초가 일반적. 기본 retry 3회 × 30s wait_exponential = ~7s ~ 20s
# worst case wall-time.
_TIMEOUT_SECONDS: Final[float] = 30.0

# Story 4.2 NFR-P 정합 — APScheduler 30분 sweep 안에서 1-2초 완료 권장. tenacity는
# 1s/2s/4s backoff(``llm_router`` 패턴 정합).
_RETRY_MIN_WAIT_SECONDS: Final[float] = 1.0
_RETRY_MAX_WAIT_SECONDS: Final[float] = 4.0

# Transient subset — 영구 4xx는 미포함(retry 무효 + cost 낭비 차단). ``llm_router``
# CR P1 fix 패턴 정합.
_TRANSIENT_RETRY_TYPES: Final[tuple[type[BaseException], ...]] = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    ExpoPushUnavailableError,
)


_client: PushClient | None = None
_client_lock = threading.Lock()


def _build_session(access_token: str) -> requests.Session:
    """``requests.Session`` build + Expo 표준 헤더 + Authorization Bearer (있으면).

    SDK 디폴트 헤더(`accept: application/json` + `accept-encoding` + `content-type:
    application/json`)는 ``PushClient.__init__``이 자체 설정하나, 본 어댑터는 *명시 session*을
    주입해 (a) Authorization 헤더 + (b) ``timeout`` 지원 흐름을 단일 SOT로 유지.
    """
    session = requests.Session()
    session.headers.update(
        {
            "accept": "application/json",
            "accept-encoding": "gzip, deflate",
            "content-type": "application/json",
        }
    )
    if access_token:
        session.headers["Authorization"] = f"Bearer {access_token}"
    return session


def _get_client() -> PushClient:
    """``PushClient`` lazy singleton — `openai_adapter._get_client` 정합.

    double-checked locking으로 concurrent 첫 호출 race 차단. ``timeout``은 SDK ``**kwargs``
    경로로 주입(``PushClient.__init__``의 ``self.timeout``).
    """
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client

        session = _build_session(settings.expo_access_token)
        _client = PushClient(session=session, timeout=_TIMEOUT_SECONDS)
        return _client


def _reset_client_for_tests() -> None:
    """테스트 hook — ``settings.expo_access_token`` 변경 후 singleton 무효화."""
    global _client
    _client = None


def _classify_http_error(exc: requests.exceptions.HTTPError) -> ExpoPushError:
    """``requests.HTTPError`` → typed adapter 예외 매핑.

    - 401 → ``ExpoPushAuthError`` (영구, 운영자 토큰 회전 신호).
    - 5xx → ``ExpoPushUnavailableError`` (transient, retry 권장 — 호출 측이 retry 의미 결정).
    - 그 외 4xx → ``ExpoPushError`` base(영구 페이로드).
    """
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 401:
        return ExpoPushAuthError(f"expo_push.auth.{status_code}")
    if isinstance(status_code, int) and 500 <= status_code < 600:
        return ExpoPushUnavailableError(f"expo_push.server_error.{status_code}")
    # Gemini Code Assist (PR #30) — ``status_code``가 ``None``인 경우 ``http_error.None``
    # 같은 비유익 라벨 대신 ``unknown`` fallback. ``_classify_server_error``의
    # ``status_code or 'unknown'`` 패턴과 정합.
    return ExpoPushError(f"expo_push.http_error.{status_code or 'unknown'}")


def _classify_server_error(exc: PushServerError) -> ExpoPushError:
    """``PushServerError`` → typed adapter 예외 매핑.

    SDK는 응답 본문에 ``errors`` 키가 있거나 형식이 깨졌을 때 본 예외를 raise.
    HTTP status가 5xx면 ``ExpoPushUnavailableError`` transient — retry 정합. 그 외는
    ``ExpoPushError`` base 영구 분류.
    """
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int) and 500 <= status_code < 600:
        return ExpoPushUnavailableError(f"expo_push.server_error.{status_code}")
    return ExpoPushError(f"expo_push.server_error.{status_code or 'unknown'}")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=_RETRY_MIN_WAIT_SECONDS, max=_RETRY_MAX_WAIT_SECONDS),
    retry=retry_if_exception_type(_TRANSIENT_RETRY_TYPES),
    reraise=True,
)
async def _publish_multiple_with_retry(messages: list[PushMessage]) -> list[PushTicket]:
    """``client.publish_multiple([...])`` async wrap + tenacity retry — ``llm_router`` 정합.

    SDK가 sync(``requests.Session``)라 ``asyncio.to_thread`` 위임. 영구 4xx는 retry X
    (``_classify_http_error`` 후 raise — ``_TRANSIENT_RETRY_TYPES``에 미포함).
    """
    client = _get_client()
    try:
        return await asyncio.to_thread(client.publish_multiple, messages)
    except requests.exceptions.HTTPError as exc:
        raise _classify_http_error(exc) from exc
    except PushServerError as exc:
        raise _classify_server_error(exc) from exc


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=_RETRY_MIN_WAIT_SECONDS, max=_RETRY_MAX_WAIT_SECONDS),
    retry=retry_if_exception_type(_TRANSIENT_RETRY_TYPES),
    reraise=True,
)
async def _check_receipts_with_retry(tickets: list[PushTicket]) -> list[PushReceipt]:
    """``client.check_receipts([...])`` async wrap + tenacity retry."""
    client = _get_client()
    try:
        return await asyncio.to_thread(client.check_receipts, tickets)
    except requests.exceptions.HTTPError as exc:
        raise _classify_http_error(exc) from exc
    except PushServerError as exc:
        raise _classify_server_error(exc) from exc


async def send_nudge(
    *,
    token: str,
    title: str,
    body: str,
    data: dict[str, str],
) -> PushTicket:
    """단일 token 푸시 발송 — ticket 1건 반환.

    ``priority="high"``는 Android *"미기록 알림"* 채널(Story 4.1 AC6 ``AndroidImportance.HIGH``)
    정합. ``channel_id="default"``는 모바일이 등록한 채널 SOT.

    ticket 응답 분기는 호출 측(``nudge_scheduler``) 책임 — DeviceNotRegistered 시
    ``revoke_push_token`` 호출(Story 4.1 SOT 재사용).
    """
    start = time.monotonic()
    message = PushMessage(
        to=token,
        title=title,
        body=body,
        data=data,
        sound="default",
        priority="high",
        channel_id="default",
    )
    tickets = await _publish_multiple_with_retry([message])
    if not tickets:
        raise ExpoPushUnavailableError("expo_push.empty_ticket_response")
    ticket = tickets[0]
    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "expo_push.send_nudge",
        ticket_status=ticket.status,
        ticket_id=ticket.id,
        latency_ms=latency_ms,
        token_prefix=token[:20],
    )
    return ticket


async def send_nudges_bulk(messages: list[PushMessage]) -> list[PushTicket]:
    """다건 발송 — SDK가 100건씩 자동 chunking(``DEFAULT_MAX_MESSAGE_COUNT``).

    본 어댑터는 단일 호출만 wrap. nudge_scheduler는 사용자별 단일 ``send_nudge``
    호출이 기본 — bulk는 forward use(Story 4.4 인사이트 카드 등 일괄 발송 가능성).
    """
    if not messages:
        return []
    return await _publish_multiple_with_retry(messages)


async def fetch_receipts(tickets: list[PushTicket]) -> dict[str, PushReceipt]:
    """ticket → receipt 매핑 — 1-15분 후 receipt 조회.

    sync 흐름(send 직후 ticket → 다음 sweep cycle에서 1회 조회)으로 단순화 — MVP cron
    30분 주기가 자연 polling. ticket이 비어있으면 빈 dict 반환(SDK는 빈 list에서 빈
    응답을 반환하지만 명시 가드).
    """
    if not tickets:
        return {}
    receipts = await _check_receipts_with_retry(tickets)
    return {receipt.id: receipt for receipt in receipts}


def get_expo_adapter() -> PushClient:
    """공개 헬퍼 — 호출 측이 ``client``를 직접 다룰 일은 거의 없으나, monkeypatch 테스트
    용도 + cron 잡 자체가 어댑터 인스턴스 의존성을 명시할 수 있게 export."""
    return _get_client()


__all__ = [
    "fetch_receipts",
    "get_expo_adapter",
    "send_nudge",
    "send_nudges_bulk",
]
