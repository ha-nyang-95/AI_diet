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
    """AC5 케이스 ③ — 이미 NULL row는 no-op (UPDATE WHERE IS NOT NULL 가드).

    CR P16 (2026-05-06) — 기존 ``rows >= 0`` vacuous assertion 강화. (a) 동일 user에
    대한 30일 경과 NULL row + 30일 경과 non-NULL row 동시 생성, (b) cleanup 후 (i)
    NULL row는 그대로 NULL, (ii) non-NULL row는 NULL set, (iii) ``rows`` 카운트가
    *오로지 non-NULL → NULL 전환 카운트*만 반영(이미 NULL은 카운트 X) 직접 단언.
    """
    _ = client
    user = await user_factory()
    null_meal_id = await _insert_meal_with_age(user, days_ago=31, idempotency_key=None)
    nonnull_key = str(uuid.uuid4())
    nonnull_meal_id = await _insert_meal_with_age(user, days_ago=31, idempotency_key=nonnull_key)

    rows_before_other = await cleanup_idempotency_keys(ttl_days=30)
    # 위 호출은 본 user의 non-NULL row 1건 + 다른 테스트 데이터 일부 포함 가능.
    # 핵심 — 이미 NULL row는 카운트되지 않아 *전체 카운트가 무한 누적되지 않음*.

    rows_idempotent = await cleanup_idempotency_keys(ttl_days=30)
    # 두 번째 호출은 *모든* row가 NULL이므로 본 user 영역에서는 0건이어야 함.
    # 다른 테스트가 동시에 새 non-NULL row를 만들 수도 있으나, 본 user의 row 직접 단언.

    from app.main import app

    session_maker = app.state.session_maker
    async with session_maker() as session:
        null_row = (await session.execute(select(Meal).where(Meal.id == null_meal_id))).scalar_one()
        nonnull_row = (
            await session.execute(select(Meal).where(Meal.id == nonnull_meal_id))
        ).scalar_one()

    # (i) NULL row는 그대로 NULL.
    assert null_row.idempotency_key is None
    # (ii) non-NULL row는 NULL로 전환됨.
    assert nonnull_row.idempotency_key is None
    # (iii) 첫 cleanup은 ≥1 row 처리(본 user의 non-NULL row 포함). 두 번째는 ≤ 첫 번째
    # (모든 row NULL — 본 user 영역에서 추가 갱신 없음).
    assert rows_before_other >= 1
    assert rows_idempotent <= rows_before_other


@pytest.mark.asyncio
async def test_graceful_db_failure_logs_and_raises(monkeypatch) -> None:
    """AC5 케이스 ④ — DB 장애 시 graceful raise + (P7 정합) 사후 ``completed`` 로그 미발생.

    CR P22 (2026-05-06) — log 객체를 직접 spy해 ``error`` 호출만 발생하고 ``info``
    추가 호출이 따라오지 않음을 단언(Story 3.5의 capture_logs는 lifespan-bound logger
    에서 작동하나, 본 script는 module-bound logger라 spy로 검증).
    """
    from unittest.mock import patch

    from sqlalchemy.exc import OperationalError

    class _FailingEngine:
        def begin(self):  # type: ignore[no-untyped-def]
            raise OperationalError("connection refused", None, Exception("simulated"))

        async def dispose(self) -> None:
            return None

    def _fake_create_engine(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _FailingEngine()

    monkeypatch.setattr("cleanup_idempotency_keys.create_async_engine", _fake_create_engine)

    with patch("cleanup_idempotency_keys.log") as mock_log, pytest.raises(OperationalError):
        await cleanup_idempotency_keys(ttl_days=30)

    # ``log.error("idempotency.cleanup.failed", ...)`` 1회 + (P7) ``log.info`` 미호출.
    assert mock_log.error.call_count >= 1
    error_event = mock_log.error.call_args_list[0].args[0]
    assert error_event == "idempotency.cleanup.failed"
    # 사후 ``cleanup.completed`` 정보 로그가 같이 발화되지 않음을 직접 단언.
    info_completed_calls = [
        c
        for c in mock_log.info.call_args_list
        if c.args and c.args[0] == "idempotency.cleanup.completed"
    ]
    assert info_completed_calls == [], (
        f"cleanup.completed 사후 emit 발생(P7 회귀): {info_completed_calls}"
    )


@pytest.mark.asyncio
async def test_negative_ttl_days_raises_value_error() -> None:
    """CR P8 (2026-05-06) — ``ttl_days <= 0``은 모든 row 클리어 가능성 차단."""
    with pytest.raises(ValueError, match="positive"):
        await cleanup_idempotency_keys(ttl_days=0)
    with pytest.raises(ValueError, match="positive"):
        await cleanup_idempotency_keys(ttl_days=-5)
