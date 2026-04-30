"""Story 3.1 — ``seed_food_aliases`` 단위 테스트 (AC #5).

DB session monkeypatch — 실제 OpenAI / 식약처 OpenAPI 도달 X.
케이스:
  1. 시드 성공 → DB row ≥ 50 + UNIQUE 제약 만족
  2. 멱등 — 두 번째 시드 → ON CONFLICT UPDATE → DB row 동일 count
  3. ``count < 50`` → ``FoodSeedAdapterError`` (FOOD_ALIASES const monkeypatch로 simulate)
  4. 단일 dict 출처 — 중복 alias entry는 dict 자체에서 차단(literal-level)
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import FoodSeedAdapterError
from app.main import app
from app.rag.food import aliases_data, aliases_seed


async def _truncate_food_aliases(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        await session.execute(text("TRUNCATE food_aliases RESTART IDENTITY"))
        await session.commit()


async def test_seed_food_aliases_success(client: AsyncClient) -> None:
    """50+ alias 시드 → DB count ≥ 50 + 모두 INSERT (첫 실행)."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_aliases(session_maker)

    async with session_maker() as session:
        result = await aliases_seed.seed_food_aliases(session)
        await session.commit()

    assert result.total >= aliases_data.ALIASES_MIN_COUNT
    assert result.inserted == len(aliases_data.FOOD_ALIASES)
    assert result.updated == 0


async def test_seed_food_aliases_idempotent(client: AsyncClient) -> None:
    """두 번째 시드 → ON CONFLICT UPDATE → row count 동일."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_aliases(session_maker)

    async with session_maker() as session:
        first = await aliases_seed.seed_food_aliases(session)
        await session.commit()

    async with session_maker() as session:
        second = await aliases_seed.seed_food_aliases(session)
        await session.commit()

    assert second.total == first.total
    assert second.updated == len(aliases_data.FOOD_ALIASES)
    assert second.inserted == 0


async def test_seed_food_aliases_count_below_threshold_raises(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FOOD_ALIASES dict가 49건으로 줄면 ``FoodSeedAdapterError`` raise."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_aliases(session_maker)

    # 49 entries simulate
    short_dict = dict(list(aliases_data.FOOD_ALIASES.items())[:49])
    monkeypatch.setattr(aliases_seed, "FOOD_ALIASES", short_dict)

    async with session_maker() as session:
        with pytest.raises(FoodSeedAdapterError) as exc_info:
            await aliases_seed.seed_food_aliases(session)
        await session.rollback()
    assert "insufficient" in str(exc_info.value)


async def test_food_aliases_dict_no_duplicate_keys() -> None:
    """``FOOD_ALIASES`` dict는 중복 alias entry 없음 (literal level — Python dict 자체 차단).

    Python dict literal에서 같은 key를 두 번 작성하면 마지막 값만 살아남는다.
    그러나 본 회귀 테스트는 *구현 의도*(50+ unique alias) 단언 — count ≥ 50이고
    keys()가 모두 unique임을 명시 검증.
    """
    keys = list(aliases_data.FOOD_ALIASES.keys())
    assert len(keys) == len(set(keys)), "FOOD_ALIASES has duplicate alias keys"
    assert len(keys) >= aliases_data.ALIASES_MIN_COUNT
