"""Story 3.1 — ``run_food_seed`` 단위 테스트 (AC #4).

식약처 OpenAPI 어댑터 + ``embed_texts`` monkeypatch — 실제 외부 호출 X.
케이스:
  1. 1차 1500건 성공 → DB row 1500 + 임베딩 NOT NULL
  2. 1차 fail → ZIP fallback CSV → 1차 0건이므로 fallback만
  3. 두 경로 모두 fail + dev environment → graceful 0건 + main returns success
  4. 두 경로 모두 fail + strict mode → ``FoodSeedAdapterError``
  5. 멱등 — 두 번째 호출 → ON CONFLICT UPDATE → DB row 동일 count, updated > 0
  6. 임베딩 batch 실패 → NULL embedding INSERT (graceful)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters import mfds_openapi as mfds_module
from app.adapters import openai_adapter as openai_module
from app.adapters.mfds_openapi import FoodNutritionRaw
from app.core.config import settings
from app.core.exceptions import FoodSeedAdapterError, FoodSeedSourceUnavailableError
from app.main import app
from app.rag.food import seed as food_seed


def _build_raw(idx: int, *, source: str = "MFDS_FCDB") -> FoodNutritionRaw:
    return FoodNutritionRaw.model_validate(
        {
            "name": f"음식{idx}",
            "category": "면류",
            "source_id": f"K-{idx:04d}",
            "source": source,
            "energy_kcal": 350.0,
            "carbohydrate_g": 55.0,
            "protein_g": 12.0,
            "fat_g": 8.0,
        }
    )


async def _truncate_food_nutrition(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        await session.execute(text("TRUNCATE food_nutrition RESTART IDENTITY"))
        await session.commit()


@pytest.fixture(autouse=True)
def _disable_strict_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """``RUN_FOOD_SEED_STRICT`` 환경변수가 외부에서 set돼있어도 테스트별로 reset."""
    monkeypatch.delenv("RUN_FOOD_SEED_STRICT", raising=False)


async def test_run_food_seed_primary_success(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1차 200건 정상 → 200건 INSERT (target_count=200으로 축소)."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_nutrition(session_maker)

    sample_items = [_build_raw(i) for i in range(200)]

    async def fake_fetch(
        target_count: int = 1500, *, page_size: int = 100
    ) -> list[FoodNutritionRaw]:
        return sample_items[:target_count]

    async def fake_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        return [[0.0] * 1536 for _ in texts]

    monkeypatch.setattr(mfds_module, "fetch_food_items", fake_fetch)
    monkeypatch.setattr(openai_module, "embed_texts", fake_embed)

    async with session_maker() as session:
        result = await food_seed.run_food_seed(session, target_count=200)
        await session.commit()

    assert result.inserted == 200
    assert result.updated == 0
    assert result.total == 200
    assert "primary" in result.source

    # 임베딩 NOT NULL 검증.
    async with session_maker() as session:
        non_null_result = await session.execute(
            text("SELECT count(*) AS n FROM food_nutrition WHERE embedding IS NOT NULL")
        )
        row = non_null_result.first()
        assert row is not None
        assert row.n == 200


async def test_run_food_seed_zip_fallback_when_primary_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """1차 ``FoodSeedSourceUnavailableError`` → ZIP fallback CSV → fallback만."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_nutrition(session_maker)

    # 1차 어댑터 fail.
    async def fake_fetch(
        target_count: int = 1500, *, page_size: int = 100
    ) -> list[FoodNutritionRaw]:
        raise FoodSeedSourceUnavailableError("MFDS key missing — test")

    async def fake_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        return [[0.1] * 1536 for _ in texts]

    monkeypatch.setattr(mfds_module, "fetch_food_items", fake_fetch)
    monkeypatch.setattr(openai_module, "embed_texts", fake_embed)

    # 임시 ZIP fallback CSV 작성 + 경로 monkeypatch.
    csv_path = tmp_path / "mfds_food_nutrition_seed.csv"
    csv_path.write_text(
        "name,category,energy_kcal,carbohydrate_g,protein_g,fat_g,saturated_fat_g,sugar_g,fiber_g,sodium_mg,cholesterol_mg,serving_size_g,serving_unit,source_id\n"
        "테스트음식,면류,300,50,10,5,,,,,,,,ZIP-001\n"
        "테스트음식2,밥류,400,60,15,8,,,,,,,,ZIP-002\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(food_seed, "_SEED_CSV_PATH", csv_path)

    async with session_maker() as session:
        result = await food_seed.run_food_seed(session, target_count=10)
        await session.commit()

    assert result.inserted == 2
    assert result.total == 2
    assert "fallback" in result.source


async def test_run_food_seed_total_failure_dev_graceful(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """1차 fail + ZIP placeholder(헤더만) → dev environment graceful 0건."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_nutrition(session_maker)

    async def fake_fetch(
        target_count: int = 1500, *, page_size: int = 100
    ) -> list[FoodNutritionRaw]:
        raise FoodSeedSourceUnavailableError("no key")

    monkeypatch.setattr(mfds_module, "fetch_food_items", fake_fetch)
    # 빈 placeholder CSV (헤더만)
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text(
        "name,category,energy_kcal,carbohydrate_g,protein_g,fat_g,saturated_fat_g,sugar_g,fiber_g,sodium_mg,cholesterol_mg,serving_size_g,serving_unit,source_id\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(food_seed, "_SEED_CSV_PATH", csv_path)
    monkeypatch.setattr(settings, "environment", "dev", raising=False)

    async with session_maker() as session:
        result = await food_seed.run_food_seed(session, target_count=10)
        await session.commit()

    assert result.inserted == 0
    assert result.total == 0
    assert result.source == "none"


async def test_run_food_seed_total_failure_strict_mode_raises(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``RUN_FOOD_SEED_STRICT=1`` + dev → prod 동등 fail-fast → ``FoodSeedAdapterError``."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_nutrition(session_maker)

    async def fake_fetch(
        target_count: int = 1500, *, page_size: int = 100
    ) -> list[FoodNutritionRaw]:
        raise FoodSeedSourceUnavailableError("no key")

    monkeypatch.setattr(mfds_module, "fetch_food_items", fake_fetch)
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text(
        "name,category,energy_kcal,carbohydrate_g,protein_g,fat_g,saturated_fat_g,sugar_g,fiber_g,sodium_mg,cholesterol_mg,serving_size_g,serving_unit,source_id\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(food_seed, "_SEED_CSV_PATH", csv_path)
    monkeypatch.setattr(settings, "environment", "dev", raising=False)
    monkeypatch.setenv("RUN_FOOD_SEED_STRICT", "1")

    async with session_maker() as session:
        with pytest.raises(FoodSeedAdapterError):
            await food_seed.run_food_seed(session, target_count=10)
        await session.rollback()


async def test_run_food_seed_idempotent(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """두 번째 호출 → ON CONFLICT UPDATE → DB count 동일 + updated > 0."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_nutrition(session_maker)

    sample = [_build_raw(i) for i in range(50)]

    async def fake_fetch(
        target_count: int = 1500, *, page_size: int = 100
    ) -> list[FoodNutritionRaw]:
        return sample[:target_count]

    async def fake_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        return [[0.0] * 1536 for _ in texts]

    monkeypatch.setattr(mfds_module, "fetch_food_items", fake_fetch)
    monkeypatch.setattr(openai_module, "embed_texts", fake_embed)

    async with session_maker() as session:
        first = await food_seed.run_food_seed(session, target_count=50)
        await session.commit()

    async with session_maker() as session:
        second = await food_seed.run_food_seed(session, target_count=50)
        await session.commit()

    assert first.inserted == 50
    assert second.inserted == 0
    assert second.updated == 50
    assert first.total == second.total == 50


async def test_run_food_seed_embedding_failure_graceful(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """embed_texts 전체 실패 → batch NULL embedding INSERT (D4 graceful)."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_nutrition(session_maker)

    sample = [_build_raw(i) for i in range(10)]

    async def fake_fetch(
        target_count: int = 1500, *, page_size: int = 100
    ) -> list[FoodNutritionRaw]:
        return sample[:target_count]

    async def failing_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        raise FoodSeedAdapterError("embeddings transient retry exhausted")

    monkeypatch.setattr(mfds_module, "fetch_food_items", fake_fetch)
    monkeypatch.setattr(openai_module, "embed_texts", failing_embed)

    async with session_maker() as session:
        result = await food_seed.run_food_seed(session, target_count=10)
        await session.commit()

    assert result.inserted == 10
    # NULL embedding 검증.
    async with session_maker() as session:
        null_result = await session.execute(
            text("SELECT count(*) AS n FROM food_nutrition WHERE embedding IS NULL")
        )
        row = null_result.first()
        assert row is not None
        assert row.n == 10
