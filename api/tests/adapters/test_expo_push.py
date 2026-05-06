"""Story 4.2 — `app.adapters.expo_push` 단위 테스트 (6 케이스, AC1).

`PushClient.publish_multiple` / `check_receipts`는 monkeypatch — 실 SDK/네트워크 호출 X.
tenacity retry는 transient 분기에서 재시도 횟수까지 검증.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from exponent_server_sdk import PushMessage, PushReceipt, PushServerError, PushTicket

import app.adapters.expo_push as expo_push
from app.adapters.expo_push import (
    fetch_receipts,
    send_nudge,
    send_nudges_bulk,
)
from app.core.exceptions import ExpoPushAuthError, ExpoPushError, ExpoPushUnavailableError

_EP_MODULE = sys.modules["app.adapters.expo_push"]


def _make_ticket(*, status: str = "ok", details: dict[str, Any] | None = None) -> PushTicket:
    """``PushTicket`` namedtuple stub — push_message는 검증 무관이라 None."""
    return PushTicket(
        push_message=None,
        status=status,
        message="",
        details=details,
        id="ticket-id-1",
    )


def _make_http_error(status_code: int) -> requests.exceptions.HTTPError:
    """``requests.HTTPError`` stub — `response.status_code`만 사용."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    err = requests.exceptions.HTTPError("http error", response=response)
    return err


@pytest.fixture(autouse=True)
def _reset_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """매 테스트마다 expo_push adapter singleton 리셋 + access token set."""
    monkeypatch.setenv("EXPO_ACCESS_TOKEN", "test-token")
    expo_push._reset_client_for_tests()
    yield
    expo_push._reset_client_for_tests()


async def test_send_nudge_ticket_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """정상 응답 — ticket.status == 'ok' + ticket id 반환."""
    fake_client = MagicMock()
    fake_client.publish_multiple.return_value = [_make_ticket(status="ok")]
    monkeypatch.setattr(_EP_MODULE, "_get_client", lambda: fake_client)

    ticket = await send_nudge(
        token="ExponentPushToken[abc]",
        title="title",
        body="body",
        data={"url": "balancenote://meals/input"},
    )
    assert ticket.status == "ok"
    assert ticket.id == "ticket-id-1"
    fake_client.publish_multiple.assert_called_once()
    sent_messages = fake_client.publish_multiple.call_args[0][0]
    assert len(sent_messages) == 1
    msg: PushMessage = sent_messages[0]
    assert msg.to == "ExponentPushToken[abc]"
    assert msg.title == "title"
    assert msg.body == "body"
    assert msg.priority == "high"  # AC1 — Android HIGH 채널 정합
    assert msg.channel_id == "default"
    assert msg.data == {"url": "balancenote://meals/input"}


async def test_send_nudge_401_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """401 영구 인증 오류 — retry 0회, ``ExpoPushAuthError`` 즉시 raise."""
    call_count = {"n": 0}

    def fake_publish(messages: list[PushMessage]) -> list[PushTicket]:
        call_count["n"] += 1
        raise _make_http_error(401)

    fake_client = MagicMock()
    fake_client.publish_multiple = fake_publish
    monkeypatch.setattr(_EP_MODULE, "_get_client", lambda: fake_client)

    with pytest.raises(ExpoPushAuthError):
        await send_nudge(token="t", title="t", body="b", data={})
    # 영구 4xx — `_TRANSIENT_RETRY_TYPES` 미포함 → 1회만 호출.
    assert call_count["n"] == 1


async def test_send_nudge_503_retries_then_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """503 transient — tenacity 3회 시도 후 ``ExpoPushUnavailableError`` reraise."""
    call_count = {"n": 0}

    def fake_publish(messages: list[PushMessage]) -> list[PushTicket]:
        call_count["n"] += 1
        raise _make_http_error(503)

    fake_client = MagicMock()
    fake_client.publish_multiple = fake_publish
    monkeypatch.setattr(_EP_MODULE, "_get_client", lambda: fake_client)
    # tenacity wait를 0으로 만들어 테스트 시간 단축.
    monkeypatch.setattr(_EP_MODULE, "_RETRY_MIN_WAIT_SECONDS", 0)
    monkeypatch.setattr(_EP_MODULE, "_RETRY_MAX_WAIT_SECONDS", 0)

    with pytest.raises(ExpoPushUnavailableError):
        await send_nudge(token="t", title="t", body="b", data={})
    assert call_count["n"] == 3  # tenacity stop_after_attempt(3)


async def test_send_nudge_4xx_permanent_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """그 외 4xx(예: 400 BadRequest) — retry 미포함 → ``ExpoPushError`` base 즉시 raise."""
    call_count = {"n": 0}

    def fake_publish(messages: list[PushMessage]) -> list[PushTicket]:
        call_count["n"] += 1
        raise _make_http_error(400)

    fake_client = MagicMock()
    fake_client.publish_multiple = fake_publish
    monkeypatch.setattr(_EP_MODULE, "_get_client", lambda: fake_client)

    with pytest.raises(ExpoPushError) as exc_info:
        await send_nudge(token="t", title="t", body="b", data={})
    # 401/503이 아니어야 base ExpoPushError로 분류.
    assert not isinstance(exc_info.value, (ExpoPushAuthError, ExpoPushUnavailableError))
    assert call_count["n"] == 1


async def test_send_nudges_bulk_delegates_to_publish_multiple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """bulk 송신 — 100건 chunking은 SDK 내부 위임. 본 어댑터는 단일 publish_multiple 호출만.

    SDK ``DEFAULT_MAX_MESSAGE_COUNT=100`` 정합. 빈 list는 SDK 호출 0회.
    """
    fake_tickets = [_make_ticket(status="ok") for _ in range(150)]
    fake_client = MagicMock()
    fake_client.publish_multiple.return_value = fake_tickets
    monkeypatch.setattr(_EP_MODULE, "_get_client", lambda: fake_client)

    messages = [
        PushMessage(to=f"ExponentPushToken[{i}]", title="t", body="b", data={}) for i in range(150)
    ]
    tickets = await send_nudges_bulk(messages)
    assert len(tickets) == 150
    fake_client.publish_multiple.assert_called_once()  # SDK 내부 chunking은 단일 호출에 위임.

    # 빈 list는 SDK 호출 0회.
    fake_client.publish_multiple.reset_mock()
    out = await send_nudges_bulk([])
    assert out == []
    fake_client.publish_multiple.assert_not_called()


async def test_fetch_receipts_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """receipts 조회 — ticket id → receipt mapping dict 반환.

    빈 list는 SDK 호출 0회 + 빈 dict 반환.
    """
    receipts = [
        PushReceipt(id="ticket-id-1", status="ok", message="", details=None),
        PushReceipt(
            id="ticket-id-2",
            status="error",
            message="",
            details={"error": "DeviceNotRegistered"},
        ),
    ]
    fake_client = MagicMock()
    fake_client.check_receipts.return_value = receipts
    monkeypatch.setattr(_EP_MODULE, "_get_client", lambda: fake_client)

    tickets = [_make_ticket()._replace(id="ticket-id-1"), _make_ticket()._replace(id="ticket-id-2")]
    out = await fetch_receipts(tickets)
    assert set(out.keys()) == {"ticket-id-1", "ticket-id-2"}
    assert out["ticket-id-2"].details == {"error": "DeviceNotRegistered"}

    # 빈 list — SDK 호출 0회 + 빈 dict.
    fake_client.check_receipts.reset_mock()
    out_empty = await fetch_receipts([])
    assert out_empty == {}
    fake_client.check_receipts.assert_not_called()


async def test_push_server_error_5xx_classified_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PushServerError`` 5xx — transient → tenacity retry 후 ``ExpoPushUnavailableError``.

    SDK 응답 본문에 ``errors`` 키가 있을 때 raise되는 표준 SDK 예외 — 5xx는 transient.
    """
    call_count = {"n": 0}
    fake_response = MagicMock()
    fake_response.status_code = 502

    def fake_publish(messages: list[PushMessage]) -> list[PushTicket]:
        call_count["n"] += 1
        raise PushServerError("upstream error", fake_response)

    fake_client = MagicMock()
    fake_client.publish_multiple = fake_publish
    monkeypatch.setattr(_EP_MODULE, "_get_client", lambda: fake_client)
    monkeypatch.setattr(_EP_MODULE, "_RETRY_MIN_WAIT_SECONDS", 0)
    monkeypatch.setattr(_EP_MODULE, "_RETRY_MAX_WAIT_SECONDS", 0)

    with pytest.raises(ExpoPushUnavailableError):
        await send_nudge(token="t", title="t", body="b", data={})
    assert call_count["n"] == 3
