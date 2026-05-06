"""Story 4.1 AC4 / AC15 — notification_service 8건 단위 테스트.

- get_settings: 기본값 정확
- update_settings: partial(``notifications_enabled`` 단독 / ``notification_time`` 단독 /
  둘 다 / 빈 update no-op) 4 분기.
- register_push_token: 신규 / 사용자 swap (다른 user의 동일 token NULL set 후 새 user에 set)
  2 분기.
- revoke_push_token: 멱등 (이미 NULL인 케이스도 OK).

DB CHECK 위반(``notification_time`` invalid)은 ``test_user_notification_columns.py``에서
1차 가드 — 본 모듈은 service 흐름.
"""

from __future__ import annotations

import uuid
from datetime import time

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.user import User
from app.main import app
from app.services.notification_service import (
    NotificationSettings,
    get_settings,
    register_push_token,
    revoke_push_token,
    update_settings,
)


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    _ = client
    return app.state.session_maker


@pytest.mark.asyncio
async def test_get_settings_returns_defaults(session_maker, user_factory) -> None:
    """Story 4.1 AC4 — 신규 user는 default 4컬럼 그대로 반환."""
    user = await user_factory()
    async with session_maker() as session:
        # ORM 객체 재로드 (factory가 commit 후 refresh)
        loaded = await session.get(User, user.id)
        assert loaded is not None
        result = await get_settings(session, loaded)
    assert isinstance(result, NotificationSettings)
    assert result.notifications_enabled is True
    assert result.notification_time == time(20, 0, 0)
    assert result.notification_timezone == "Asia/Seoul"
    assert result.has_push_token is False
    assert result.permission_likely_granted is False


@pytest.mark.asyncio
async def test_update_settings_partial_notifications_enabled(session_maker, user_factory) -> None:
    """Story 4.1 AC4 — ``notifications_enabled`` 단독 PATCH (시간 보존)."""
    user = await user_factory()
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await update_settings(session, loaded, notifications_enabled=False)
    assert result.notifications_enabled is False
    assert result.notification_time == time(20, 0, 0)  # 보존


@pytest.mark.asyncio
async def test_update_settings_partial_notification_time(session_maker, user_factory) -> None:
    """Story 4.1 AC4 — ``notification_time`` 단독 PATCH (enabled 보존)."""
    user = await user_factory()
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await update_settings(session, loaded, notification_time=time(21, 30, 0))
    assert result.notifications_enabled is True  # 보존
    assert result.notification_time == time(21, 30, 0)


@pytest.mark.asyncio
async def test_update_settings_both_fields(session_maker, user_factory) -> None:
    """Story 4.1 AC4 — 두 필드 동시 PATCH."""
    user = await user_factory()
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await update_settings(
            session,
            loaded,
            notifications_enabled=False,
            notification_time=time(7, 0, 0),
        )
    assert result.notifications_enabled is False
    assert result.notification_time == time(7, 0, 0)


@pytest.mark.asyncio
async def test_update_settings_empty_no_op(session_maker, user_factory) -> None:
    """Story 4.1 AC4 — 빈 PATCH(둘 다 None)는 no-op + 200 (현 상태 반환)."""
    user = await user_factory()
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await update_settings(session, loaded)
    # 변경 없음
    assert result.notifications_enabled is True
    assert result.notification_time == time(20, 0, 0)


@pytest.mark.asyncio
async def test_register_push_token_new_user(session_maker, user_factory) -> None:
    """Story 4.1 AC4 — 신규 token 등록 (사용자 row에 token set)."""
    user = await user_factory()
    token = f"ExponentPushToken[{uuid.uuid4().hex}]"
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        await register_push_token(session, loaded, token=token, platform="ios")

    # 다른 세션에서 재조회
    async with session_maker() as session:
        reloaded = await session.get(User, user.id)
        assert reloaded is not None
        assert reloaded.expo_push_token == token


@pytest.mark.asyncio
async def test_register_push_token_user_swap(session_maker, user_factory) -> None:
    """Story 4.1 AC4 — 사용자 A의 token이 사용자 B로 옮겨가는 swap.

    *Why*: 동일 device(token)에서 사용자 A 로그아웃 → 사용자 B 로그인 시점. 본 함수가
    A의 row를 NULL set 후 B에 set — partial UNIQUE 위반 회피 + nudge가 잘못된 사람에게
    발송되는 회귀 차단.
    """
    user_a = await user_factory()
    user_b = await user_factory()
    token = f"ExponentPushToken[{uuid.uuid4().hex}]"

    # 1) A에 token 박기
    async with session_maker() as session:
        loaded_a = await session.get(User, user_a.id)
        await register_push_token(session, loaded_a, token=token, platform="ios")

    # 2) B로 swap
    async with session_maker() as session:
        loaded_b = await session.get(User, user_b.id)
        await register_push_token(session, loaded_b, token=token, platform="ios")

    # 3) A는 NULL, B는 token
    async with session_maker() as session:
        reloaded_a = await session.get(User, user_a.id)
        reloaded_b = await session.get(User, user_b.id)
        assert reloaded_a is not None
        assert reloaded_b is not None
        assert reloaded_a.expo_push_token is None
        assert reloaded_b.expo_push_token == token


@pytest.mark.asyncio
async def test_revoke_push_token_idempotent(session_maker, user_factory) -> None:
    """Story 4.1 AC4 — revoke는 멱등 (이미 NULL이어도 OK)."""
    user = await user_factory()
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        await revoke_push_token(session, loaded)  # 이미 NULL
        await revoke_push_token(session, loaded)  # 재호출 — no-op

    async with session_maker() as session:
        reloaded = await session.get(User, user.id)
        assert reloaded is not None
        assert reloaded.expo_push_token is None
