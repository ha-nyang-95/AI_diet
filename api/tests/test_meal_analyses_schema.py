"""Story 3.7 — 0012_create_meal_analyses 마이그레이션 schema 테스트 (Task 17.6)."""

from __future__ import annotations

import asyncio

import pytest
from alembic.config import Config as AlembicConfig
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command as alembic_command
from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.asyncio


def _alembic_config() -> AlembicConfig:
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


async def test_alembic_0012_round_trip(client: AsyncClient) -> None:
    """alembic upgrade head → downgrade 0011 → upgrade head round-trip 정상 단언."""
    _ = client
    cfg = _alembic_config()
    await asyncio.to_thread(alembic_command.downgrade, cfg, "0011_knowledge_chunks")
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_name='meal_analyses'"
            )
        )
        rows = list(result.all())
    try:
        assert rows == [], f"meal_analyses table still exists after downgrade: {rows}"
    finally:
        # 다음 테스트에 영향 X — head로 복구.
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")


async def test_meal_analyses_check_constraints_enforce_band_validity(
    client: AsyncClient,
) -> None:
    """DB-level CHECK 제약 검증 — application Pydantic이 1차 게이트, DB가 2차 가드."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    # 검증 패턴: 잘못된 fit_score(101) INSERT 시도 → IntegrityError.
    # 직접 raw SQL로 validation 우회 후 DB CHECK가 catch하는지 확인.
    async with session_maker() as session:
        # 임시 user/meal 생성 (FK 제약 통과).
        await session.execute(
            text(
                "INSERT INTO users (id, google_sub, email, email_verified, role) "
                "VALUES (gen_random_uuid(), 'test-sub-meal-analyses', "
                "'meal-analyses@test.com', true, 'user') RETURNING id"
            )
        )
        await session.commit()
    async with session_maker() as session:
        user_row = (
            await session.execute(
                text("SELECT id FROM users WHERE google_sub = 'test-sub-meal-analyses'")
            )
        ).first()
        assert user_row is not None
        meal_row = (
            await session.execute(
                text(
                    "INSERT INTO meals (user_id, raw_text) "
                    "VALUES (:uid, '테스트 식단') RETURNING id"
                ),
                {"uid": user_row.id},
            )
        ).first()
        assert meal_row is not None
        await session.commit()

        # CHECK 제약 위반 시도 — fit_score=200(범위 초과). asyncpg/SQLAlchemy
        # 양쪽에서 IntegrityError 또는 DBAPIError로 raise.
        from sqlalchemy.exc import DBAPIError, IntegrityError

        with pytest.raises((IntegrityError, DBAPIError)):
            await session.execute(
                text(
                    "INSERT INTO meal_analyses ("
                    "meal_id, user_id, fit_score, fit_score_label, fit_reason, "
                    "carbohydrate_g, protein_g, fat_g, energy_kcal, "
                    "feedback_text, feedback_summary, used_llm) VALUES ("
                    ":mid, :uid, 200, 'good', 'ok', 0, 0, 0, 0, 'x', 'x', 'gpt-4o-mini')"
                ),
                {"mid": meal_row.id, "uid": user_row.id},
            )
            await session.commit()
        await session.rollback()

        # cleanup.
        await session.execute(text("DELETE FROM meals WHERE id = :mid"), {"mid": meal_row.id})
        await session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_row.id})
        await session.commit()
