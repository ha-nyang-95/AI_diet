"""Story 3.9 AC5 — ``cleanup_idempotency_keys`` 30일 TTL 4 케이스 단위 테스트."""

from __future__ import annotations

import sys
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.db.models.meal import Meal
from app.db.models.user import User

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from cleanup_idempotency_keys import (  # type: ignore[import-not-found] # noqa: E402
    cleanup_idempotency_keys,
)

UserFactory = Callable[..., Awaitable[User]]


async def _insert_meal_with_age(
    user: User,
    *,
    days_ago: int,
    idempotency_key: str | None,
) -> uuid.UUID:
    """``created_at``을 임의 시각으로 강제 set한 meal row INSERT (test 헬퍼).

    SQLAlchemy ORM은 ``server_default=now()`` 강제 발화라 INSERT 후 직접 UPDATE.
    """
    from app.main import app

    session_maker = app.state.session_maker
    target_time = datetime.now(UTC) - timedelta(days=days_ago)
    meal_id = uuid.uuid4()
    async with session_maker() as session:
        meal = Meal(
            id=meal_id,
            user_id=user.id,
            raw_text="테스트 식단",
            idempotency_key=idempotency_key,
        )
        session.add(meal)
        await session.commit()
        # created_at 강제 갱신.
        await session.execute(
            text("UPDATE meals SET created_at = :ts WHERE id = :id"),
            {"ts": target_time, "id": meal_id},
        )
        await session.commit()
    return meal_id


@pytest.mark.asyncio
async def test_clears_idempotency_key_after_30_days(client, user_factory: UserFactory) -> None:
    """AC5 케이스 ① — 30일 경과 row의 idempotency_key가 NULL로 set."""
    _ = client
    user = await user_factory()
    meal_id = await _insert_meal_with_age(user, days_ago=31, idempotency_key=str(uuid.uuid4()))

    rows = await cleanup_idempotency_keys(ttl_days=30)
    assert rows >= 1

    from app.main import app

    session_maker = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(select(Meal).where(Meal.id == meal_id))
        row = result.scalar_one()
        assert row.idempotency_key is None


@pytest.mark.asyncio
async def test_preserves_recent_idempotency_key(client, user_factory: UserFactory) -> None:
    """AC5 케이스 ② — 30일 미만 row는 유지(NULL clear 회귀 차단)."""
    _ = client
    user = await user_factory()
    fresh_key = str(uuid.uuid4())
    meal_id = await _insert_meal_with_age(user, days_ago=15, idempotency_key=fresh_key)

    await cleanup_idempotency_keys(ttl_days=30)

    from app.main import app

    session_maker = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(select(Meal).where(Meal.id == meal_id))
        row = result.scalar_one()
        assert row.idempotency_key == fresh_key


@pytest.mark.asyncio
async def test_no_op_on_already_null_keys(client, user_factory: UserFactory) -> None:
    """AC5 케이스 ③ — 이미 NULL row는 no-op (UPDATE WHERE IS NOT NULL 가드)."""
    _ = client
    user = await user_factory()
    # idempotency_key=None으로 INSERT — 30일 경과여도 UPDATE 대상 아님.
    meal_id = await _insert_meal_with_age(user, days_ago=31, idempotency_key=None)

    rows = await cleanup_idempotency_keys(ttl_days=30)
    # 다른 테스트 row 영향은 받을 수 있으나, 본 row 갱신은 0건.
    from app.main import app

    session_maker = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(select(Meal).where(Meal.id == meal_id))
        row = result.scalar_one()
        assert row.idempotency_key is None
    # rows는 ≥ 0 (다른 테스트 데이터 영향 가능 — 본 row만 직접 단언).
    assert rows >= 0


@pytest.mark.asyncio
async def test_graceful_db_failure_logs_and_raises(monkeypatch) -> None:
    """AC5 케이스 ④ — DB 장애 시 graceful raise + structlog 카운트 0 로그."""
    from sqlalchemy.exc import OperationalError

    class _FailingEngine:
        def begin(self):  # type: ignore[no-untyped-def]
            raise OperationalError("connection refused", None, Exception("simulated"))

        async def dispose(self) -> None:
            return None

    def _fake_create_engine(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _FailingEngine()

    monkeypatch.setattr("cleanup_idempotency_keys.create_async_engine", _fake_create_engine)

    with pytest.raises(OperationalError):
        await cleanup_idempotency_keys(ttl_days=30)
