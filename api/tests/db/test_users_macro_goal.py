"""Story 4.4 AC1 — 0015_users_macro_goal 마이그레이션 검증.

본 모듈은 *DB 레벨* 검증 — alembic이 실제로 ``macro_goal`` JSONB 컬럼 + CHECK 제약
``ck_users_macro_goal_shape``를 박는지, default 값이 ``NULL``인지, 잘못된 shape
(범위 외, 잘못된 타입)이 ``IntegrityError`` raise하는지 회귀 가드.

ORM 레벨(Pydantic) 검증은 ``test_macro_goal.py`` SOT — 본 모듈은 *마이그레이션 SOT*가
변경됐을 때 즉시 fail.
"""

from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.main import app


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    """``app.state.session_maker``는 lifespan에서 init — `client` fixture가 lifespan 활성."""
    _ = client
    return app.state.session_maker


@pytest.mark.asyncio
async def test_macro_goal_default_null(session_maker: async_sessionmaker) -> None:
    """Story 4.4 AC1 — ``users`` 신규 row 생성 시 ``macro_goal`` default NULL."""
    async with session_maker() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, google_sub, email, email_verified) "
                "VALUES (:id, :sub, :email, true)"
            ),
            {
                "id": uuid.uuid4(),
                "sub": f"google-sub-{uuid.uuid4()}",
                "email": f"{uuid.uuid4().hex}@example.com",
            },
        )
        await session.commit()

        result = await session.execute(
            text("SELECT macro_goal FROM users ORDER BY created_at DESC LIMIT 1")
        )
        row = result.first()
        assert row is not None
        assert row[0] is None


@pytest.mark.asyncio
async def test_macro_goal_check_rejects_out_of_range(
    session_maker: async_sessionmaker,
) -> None:
    """Story 4.4 AC1 — CHECK 제약이 범위 위반 shape 거부.

    ``daily_calorie_target_kcal=400`` (< 800) — IntegrityError raise.
    """
    async with session_maker() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO users (id, google_sub, email, email_verified, macro_goal) "
                    "VALUES (:id, :sub, :email, true, CAST(:mg AS jsonb))"
                ),
                {
                    "id": uuid.uuid4(),
                    "sub": f"google-sub-{uuid.uuid4()}",
                    "email": f"{uuid.uuid4().hex}@example.com",
                    "mg": json.dumps({"daily_calorie_target_kcal": 400}),
                },
            )
            await session.commit()


@pytest.mark.asyncio
async def test_macro_goal_check_accepts_valid_shape(
    session_maker: async_sessionmaker,
) -> None:
    """Story 4.4 AC1 — 정상 shape는 INSERT 성공."""
    user_id = uuid.uuid4()
    valid_mg = {
        "daily_calorie_target_kcal": 1800,
        "protein_target_g_per_meal": 25,
        "macro_ratio_carb_pct": 50,
        "macro_ratio_protein_pct": 25,
        "macro_ratio_fat_pct": 25,
    }
    async with session_maker() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, google_sub, email, email_verified, macro_goal) "
                "VALUES (:id, :sub, :email, true, CAST(:mg AS jsonb))"
            ),
            {
                "id": user_id,
                "sub": f"google-sub-{uuid.uuid4()}",
                "email": f"{uuid.uuid4().hex}@example.com",
                "mg": json.dumps(valid_mg),
            },
        )
        await session.commit()

        result = await session.execute(
            text("SELECT macro_goal FROM users WHERE id = :id"),
            {"id": user_id},
        )
        row = result.first()
        assert row is not None
        assert row[0] == valid_mg
