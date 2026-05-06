"""Story 4.2 AC3/AC6/AC8 — `app.workers.nudge_scheduler` 단위 테스트 (10건).

Real Postgres + monkeypatched Expo adapter — sweep query / ticket 분기 / 멱등 가드 /
DeviceNotRegistered 분기 / 자정 cross 매칭을 통합 검증.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, time
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from exponent_server_sdk import PushTicket
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.workers.nudge_scheduler as nudge_module
from app.adapters import expo_push
from app.core.exceptions import ExpoPushUnavailableError
from app.db.models.meal import Meal
from app.db.models.notification import Notification
from app.db.models.user import User
from app.main import app
from app.workers.nudge_scheduler import sweep_unrecorded_meals

_KST = ZoneInfo("Asia/Seoul")


def _make_ticket(
    *, status: str = "ok", details: dict[str, Any] | None = None, ticket_id: str = "t-1"
) -> PushTicket:
    return PushTicket(
        push_message=None,
        status=status,
        message="",
        details=details,
        id=ticket_id,
    )


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    _ = client
    return app.state.session_maker


async def _create_eligible_user(
    session_maker: async_sessionmaker,
    *,
    notification_time: time,
    expo_push_token: str = "ExponentPushToken[abc]",
    notifications_enabled: bool = True,
    deleted: bool = False,
) -> User:
    """본 테스트가 직접 SQL ``UPDATE``로 컬럼을 set — Story 4.1 4컬럼 default(``true`` /
    ``20:00:00`` / ``Asia/Seoul`` / NULL) 가 적용된 row를 본 테스트 시나리오에 맞춰 변경.
    """
    async with session_maker() as session:
        user = User(
            google_sub=f"google-sub-{uuid.uuid4()}",
            email=f"{uuid.uuid4().hex}@example.com",
            email_verified=True,
            last_login_at=datetime.now(UTC),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        # 시나리오별 4컬럼 패치.
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                notification_time=notification_time,
                notifications_enabled=notifications_enabled,
                expo_push_token=expo_push_token,
                deleted_at=datetime.now(UTC) if deleted else None,
            )
        )
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
def mock_now_kst(monkeypatch: pytest.MonkeyPatch) -> Iterator[datetime]:
    """``datetime.now(KST)`` 픽스 — 20:30 KST 시점에 cron이 fire한 시뮬레이션.

    notification_time=19:30이면 +30min=20:00이 [20:00, 20:30] 윈도우에 포함되어 sweep
    매칭. 다른 시각이 필요하면 monkeypatch로 override.
    """
    fixed_now = datetime(2026, 5, 6, 20, 30, 0, tzinfo=_KST)

    class _FakeDatetime:
        @staticmethod
        def now(tz: Any = None) -> datetime:
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(nudge_module, "datetime", _FakeDatetime)
    yield fixed_now


@pytest_asyncio.fixture
async def patch_send_nudge_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncMock]:
    """Expo send_nudge → status=ok ticket 반환 mock."""
    mock = AsyncMock(return_value=_make_ticket(status="ok", ticket_id="ticket-ok"))
    monkeypatch.setattr(expo_push, "send_nudge", mock)
    yield mock


# ---------------------------------------------------------------------------
# 1) sweep query — 적격 0건 → 발사 0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_no_eligible_users(
    session_maker: async_sessionmaker,
    mock_now_kst: datetime,
    patch_send_nudge_ok: AsyncMock,
) -> None:
    """DB에 적격 사용자 0건 — Expo send_nudge 호출 0회 + stats 0."""
    stats = await sweep_unrecorded_meals(session_maker)
    assert stats["users_eligible_count"] == 0
    assert stats["nudges_sent_count"] == 0
    patch_send_nudge_ok.assert_not_called()


# ---------------------------------------------------------------------------
# 2) happy path — 적격 1건 + ticket.ok → notifications row INSERT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_happy_path_eligible_user(
    session_maker: async_sessionmaker,
    mock_now_kst: datetime,
    patch_send_nudge_ok: AsyncMock,
) -> None:
    """notification_time=19:30 → +30min=20:00 → cron 20:30 cycle 윈도우 매칭."""
    user = await _create_eligible_user(session_maker, notification_time=time(19, 30))

    stats = await sweep_unrecorded_meals(session_maker)

    assert stats["users_eligible_count"] == 1
    assert stats["nudges_sent_count"] == 1
    patch_send_nudge_ok.assert_awaited_once()
    # notifications row 검증.
    async with session_maker() as session:
        result = await session.execute(select(Notification).where(Notification.user_id == user.id))
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].kind == "unrecorded_meal"
        assert rows[0].kst_date == date(2026, 5, 6)
        assert rows[0].expo_ticket_id == "ticket-ok"


# ---------------------------------------------------------------------------
# 3) notifications_enabled=false → 제외
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_excludes_notifications_disabled(
    session_maker: async_sessionmaker,
    mock_now_kst: datetime,
    patch_send_nudge_ok: AsyncMock,
) -> None:
    await _create_eligible_user(
        session_maker,
        notification_time=time(19, 30),
        notifications_enabled=False,
    )
    stats = await sweep_unrecorded_meals(session_maker)
    assert stats["users_eligible_count"] == 0
    patch_send_nudge_ok.assert_not_called()


# ---------------------------------------------------------------------------
# 4) expo_push_token IS NULL → 제외
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_excludes_no_push_token(
    session_maker: async_sessionmaker,
    mock_now_kst: datetime,
    patch_send_nudge_ok: AsyncMock,
) -> None:
    user = await _create_eligible_user(
        session_maker,
        notification_time=time(19, 30),
        expo_push_token="ExponentPushToken[xxx]",
    )
    # token NULL set
    async with session_maker() as session:
        await session.execute(update(User).where(User.id == user.id).values(expo_push_token=None))
        await session.commit()

    stats = await sweep_unrecorded_meals(session_maker)
    assert stats["users_eligible_count"] == 0
    patch_send_nudge_ok.assert_not_called()


# ---------------------------------------------------------------------------
# 5) deleted_at IS NOT NULL → 제외
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_excludes_soft_deleted(
    session_maker: async_sessionmaker,
    mock_now_kst: datetime,
    patch_send_nudge_ok: AsyncMock,
) -> None:
    await _create_eligible_user(session_maker, notification_time=time(19, 30), deleted=True)
    stats = await sweep_unrecorded_meals(session_maker)
    assert stats["users_eligible_count"] == 0
    patch_send_nudge_ok.assert_not_called()


# ---------------------------------------------------------------------------
# 6) 당일 KST meals 1건 이상 → 제외
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_excludes_user_with_meal_today(
    session_maker: async_sessionmaker,
    mock_now_kst: datetime,
    patch_send_nudge_ok: AsyncMock,
) -> None:
    user = await _create_eligible_user(session_maker, notification_time=time(19, 30))
    async with session_maker() as session:
        meal = Meal(
            user_id=user.id,
            raw_text="짜장면 1인분",
            ate_at=mock_now_kst.astimezone(UTC).replace(tzinfo=UTC),
        )
        session.add(meal)
        await session.commit()

    stats = await sweep_unrecorded_meals(session_maker)
    assert stats["users_eligible_count"] == 0
    patch_send_nudge_ok.assert_not_called()


# ---------------------------------------------------------------------------
# 7) 동일 날 동일 kind 멱등 row 존재 → 제외
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_excludes_user_with_existing_notification_today(
    session_maker: async_sessionmaker,
    mock_now_kst: datetime,
    patch_send_nudge_ok: AsyncMock,
) -> None:
    user = await _create_eligible_user(session_maker, notification_time=time(19, 30))
    async with session_maker() as session:
        existing = Notification(
            user_id=user.id,
            kind="unrecorded_meal",
            kst_date=date(2026, 5, 6),
        )
        session.add(existing)
        await session.commit()

    stats = await sweep_unrecorded_meals(session_maker)
    assert stats["users_eligible_count"] == 0
    patch_send_nudge_ok.assert_not_called()


# ---------------------------------------------------------------------------
# 8) DeviceNotRegistered ticket → revoke_push_token 호출 + token NULL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_device_not_registered_revokes_token(
    session_maker: async_sessionmaker,
    mock_now_kst: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_eligible_user(session_maker, notification_time=time(19, 30))
    mock_send = AsyncMock(
        return_value=_make_ticket(
            status="error",
            details={"error": "DeviceNotRegistered"},
            ticket_id="t-dnr",
        )
    )
    monkeypatch.setattr(expo_push, "send_nudge", mock_send)

    stats = await sweep_unrecorded_meals(session_maker)

    assert stats["device_not_registered_count"] == 1
    assert stats["nudges_sent_count"] == 0
    mock_send.assert_awaited_once()

    # token NULL 검증.
    async with session_maker() as session:
        refreshed = await session.get(User, user.id)
        assert refreshed is not None
        assert refreshed.expo_push_token is None

    # notifications row INSERT 안 함.
    async with session_maker() as session:
        rows = (
            (await session.execute(select(Notification).where(Notification.user_id == user.id)))
            .scalars()
            .all()
        )
        assert rows == []


# ---------------------------------------------------------------------------
# 9) Expo adapter transient 실패 → swallow + Sentry capture + transient count++
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_transient_expo_failure_swallowed(
    session_maker: async_sessionmaker,
    mock_now_kst: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_eligible_user(session_maker, notification_time=time(19, 30))
    mock_send = AsyncMock(side_effect=ExpoPushUnavailableError("503 transient"))
    monkeypatch.setattr(expo_push, "send_nudge", mock_send)
    capture_calls: list[Any] = []
    monkeypatch.setattr(
        nudge_module.sentry_sdk,
        "capture_exception",
        lambda exc: capture_calls.append(exc),
    )

    stats = await sweep_unrecorded_meals(session_maker)

    assert stats["transient_error_count"] == 1
    assert stats["nudges_sent_count"] == 0
    # Sentry capture 호출 검증.
    assert len(capture_calls) == 1
    assert isinstance(capture_calls[0], ExpoPushUnavailableError)
    # notifications row INSERT 안 함 (다음 cycle 재시도 정합).
    async with session_maker() as session:
        rows = (
            (await session.execute(select(Notification).where(Notification.user_id == user.id)))
            .scalars()
            .all()
        )
        assert rows == []


# ---------------------------------------------------------------------------
# 10) 자정 cross — notification_time=23:30 + 30min = 0:00 → 0:00 cycle 매칭
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_midnight_cross_matches_2330_at_midnight_cycle(
    session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    patch_send_nudge_ok: AsyncMock,
) -> None:
    """now=00:00 KST cycle. notification_time=23:30 +30min=00:00 매칭(BETWEEN wrap)."""
    user = await _create_eligible_user(session_maker, notification_time=time(23, 30))
    fixed_now = datetime(2026, 5, 7, 0, 0, 0, tzinfo=_KST)

    class _FakeDatetime:
        @staticmethod
        def now(tz: Any = None) -> datetime:
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(nudge_module, "datetime", _FakeDatetime)

    stats = await sweep_unrecorded_meals(session_maker)
    assert stats["users_eligible_count"] == 1
    assert stats["nudges_sent_count"] == 1
    patch_send_nudge_ok.assert_awaited_once()
    # today_kst는 발사 cycle 기준 — 2026-05-07.
    async with session_maker() as session:
        rows = (
            (await session.execute(select(Notification).where(Notification.user_id == user.id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].kst_date == date(2026, 5, 7)


# ---------------------------------------------------------------------------
# 11) CR P2 — ticket.status가 "ok"/"error"가 아닌 unknown 값(SDK 미래 버전 대비)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_unknown_ticket_status_handled_explicitly(
    session_maker: async_sessionmaker,
    mock_now_kst: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ticket.status="warning"`` 같은 unknown 값이 fall-through로 error 분기 진입하지
    않고 명시 ``unknown_status`` 분기에서 처리 + capture_message ``warning`` 레벨.
    """
    user = await _create_eligible_user(session_maker, notification_time=time(19, 30))
    mock_send = AsyncMock(return_value=_make_ticket(status="warning", ticket_id="t-w"))
    monkeypatch.setattr(expo_push, "send_nudge", mock_send)
    capture_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        nudge_module.sentry_sdk,
        "capture_message",
        lambda msg, level=None: capture_calls.append((msg, level or "")),
    )

    stats = await sweep_unrecorded_meals(session_maker)

    assert stats["transient_error_count"] == 1
    assert stats["nudges_sent_count"] == 0
    # capture_message 호출 — message에 unknown_status 라벨 + level=warning.
    assert len(capture_calls) == 1
    assert "nudge.ticket_unknown_status" in capture_calls[0][0]
    assert capture_calls[0][1] == "warning"
    # notifications row INSERT 안 함 — 다음 cycle 재시도 정합.
    async with session_maker() as session:
        rows = (
            (await session.execute(select(Notification).where(Notification.user_id == user.id)))
            .scalars()
            .all()
        )
        assert rows == []


# ---------------------------------------------------------------------------
# 12) CR P2 — ticket.details가 dict가 아닐 때(``None`` / 미래 객체) AttributeError 차단
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_ticket_details_non_dict_isinstance_guard(
    session_maker: async_sessionmaker,
    mock_now_kst: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ticket.status="error"`` + ``ticket.details=None`` 시 ``error_code``가 ``None``으로
    안전 fall-through. 기존 ``(ticket.details or {}).get(...)``는 동작하지만, 미래 SDK가
    str/객체를 details에 박는 경우(타입 stub 부재) AttributeError 발생 가능 — isinstance
    가드로 명시 차단. ``error_code or 'unknown'`` 라벨도 함께 검증.
    """
    user = await _create_eligible_user(session_maker, notification_time=time(19, 30))
    mock_send = AsyncMock(
        return_value=_make_ticket(status="error", details=None, ticket_id="t-none")
    )
    monkeypatch.setattr(expo_push, "send_nudge", mock_send)
    capture_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        nudge_module.sentry_sdk,
        "capture_message",
        lambda msg, level=None: capture_calls.append((msg, level or "")),
    )

    stats = await sweep_unrecorded_meals(session_maker)

    assert stats["transient_error_count"] == 1
    assert stats["nudges_sent_count"] == 0
    # ``error_code or 'unknown'`` 라벨이 message에 박힘.
    assert len(capture_calls) == 1
    assert "nudge.ticket_error: unknown" in capture_calls[0][0]
    assert capture_calls[0][1] == "error"
    async with session_maker() as session:
        rows = (
            (await session.execute(select(Notification).where(Notification.user_id == user.id)))
            .scalars()
            .all()
        )
        assert rows == []


# ---------------------------------------------------------------------------
# 13) CR P4 — _record_notification DB transient(OperationalError) → sweep loop 보존
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_record_notification_db_transient_does_not_break_loop(
    session_maker: async_sessionmaker,
    mock_now_kst: datetime,
    monkeypatch: pytest.MonkeyPatch,
    patch_send_nudge_ok: AsyncMock,
) -> None:
    """post-send 단계에서 DB transient(OperationalError 등 ``IntegrityError`` 외)가 raise
    되면 한 사용자만 skip + ``transient_error_count`` 증가하고 sweep loop 자체는 다른
    사용자로 진행. 본 테스트는 적격 1건이지만 raise 후 stats 갱신 + Sentry capture만
    검증.
    """
    from sqlalchemy.exc import OperationalError

    await _create_eligible_user(session_maker, notification_time=time(19, 30))

    async def _raising_record_notification(*args: object, **kwargs: object) -> bool:
        raise OperationalError("statement", {}, Exception("connection reset"))

    monkeypatch.setattr(nudge_module, "_record_notification", _raising_record_notification)
    capture_calls: list[Any] = []
    monkeypatch.setattr(
        nudge_module.sentry_sdk,
        "capture_exception",
        lambda exc: capture_calls.append(exc),
    )

    # CR P4 — sweep_unrecorded_meals이 OperationalError로 중단되지 않아야 함.
    stats = await sweep_unrecorded_meals(session_maker)

    assert stats["users_eligible_count"] == 1
    assert stats["nudges_sent_count"] == 0  # _record_notification raise → INSERT 실패
    assert stats["transient_error_count"] == 1
    assert len(capture_calls) == 1
    assert isinstance(capture_calls[0], OperationalError)
