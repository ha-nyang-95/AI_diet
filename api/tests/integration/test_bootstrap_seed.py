"""Story 3.1 — bootstrap_seed.py + seed_food_db.py 통합 테스트 (AC #6).

scripts/seed_food_db.py 의 async core ``_run_seeds()`` + 환경별 분기 검증.
- 정상 시드 → DB row 생성.
- ``MFDS_OPENAPI_KEY`` 미설정 + dev environment → food_aliases만 + food_nutrition 0건.
- 멱등 — 두 번째 호출 → ON CONFLICT UPDATE → DB row 동일 count.

``main()`` wrapper는 ``asyncio.run`` glue + Sentry capture만 — pytest-asyncio
event loop와 충돌하므로 본 테스트는 *async core*만 직접 호출.

scripts/는 sys.path 외부 — 모듈 임포트를 위해 path 추가.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters import mfds_openapi as mfds_module
from app.adapters import openai_adapter as openai_module
from app.adapters.mfds_openapi import FoodNutritionRaw
from app.core.config import settings
from app.main import app
from app.rag.food import seed as food_seed

# scripts/ 모듈 import — sys.path 추가.
_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _build_raw(idx: int) -> FoodNutritionRaw:
    return FoodNutritionRaw.model_validate(
        {
            "name": f"음식{idx}",
            "category": "면류",
            "source_id": f"K-{idx:04d}",
            "source": "MFDS_FCDB",
            "energy_kcal": 350.0,
        }
    )


async def _truncate_food_tables(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        await session.execute(text("TRUNCATE food_nutrition, food_aliases RESTART IDENTITY"))
        await session.commit()


@pytest.fixture(autouse=True)
def _disable_strict_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUN_FOOD_SEED_STRICT", raising=False)


def _import_seed_food_db() -> ModuleType:
    """scripts/seed_food_db 모듈 import — sys.modules 캐시 회피로 매 테스트 fresh."""
    sys.modules.pop("seed_food_db", None)
    import seed_food_db  # type: ignore[import-not-found]

    module: ModuleType = seed_food_db
    return module


async def test_bootstrap_seed_normal(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """정상 시드 — async core 직접 호출 → food_nutrition + food_aliases 시드."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_tables(session_maker)

    sample = [_build_raw(i) for i in range(50)]

    async def fake_fetch(
        target_count: int = 1500, *, page_size: int = 100
    ) -> list[FoodNutritionRaw]:
        return sample[:target_count]

    async def fake_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        return [[0.0] * 1536 for _ in texts]

    monkeypatch.setattr(mfds_module, "fetch_food_items", fake_fetch)
    monkeypatch.setattr(openai_module, "embed_texts", fake_embed)
    monkeypatch.setattr(food_seed, "SEED_TARGET_COUNT", 50)

    sfd = _import_seed_food_db()
    (
        food_inserted,
        food_updated,
        food_total,
        alias_inserted,
        alias_updated,
        alias_total,
        source,
    ) = await sfd._run_seeds()

    assert food_total >= 50
    assert alias_total >= 50
    assert "primary" in source


async def test_bootstrap_seed_dev_graceful_when_no_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``MFDS_OPENAPI_KEY`` 미설정 + ZIP placeholder + dev → graceful + food_aliases만."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_tables(session_maker)

    from app.core.exceptions import FoodSeedSourceUnavailableError

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
    monkeypatch.setattr(food_seed, "SEED_TARGET_COUNT", 50)

    sfd = _import_seed_food_db()
    (
        food_inserted,
        food_updated,
        food_total,
        alias_inserted,
        alias_updated,
        alias_total,
        source,
    ) = await sfd._run_seeds()

    # dev graceful — food_nutrition 0건 + food_aliases는 정상.
    assert food_total == 0
    assert alias_total >= 50
    assert source == "none"


async def test_bootstrap_seed_idempotent(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """두 번째 호출 → ON CONFLICT UPDATE → DB row 동일 count + UPDATE 분기."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_tables(session_maker)

    sample = [_build_raw(i) for i in range(50)]

    async def fake_fetch(
        target_count: int = 1500, *, page_size: int = 100
    ) -> list[FoodNutritionRaw]:
        return sample[:target_count]

    async def fake_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        return [[0.0] * 1536 for _ in texts]

    monkeypatch.setattr(mfds_module, "fetch_food_items", fake_fetch)
    monkeypatch.setattr(openai_module, "embed_texts", fake_embed)
    monkeypatch.setattr(food_seed, "SEED_TARGET_COUNT", 50)

    sfd = _import_seed_food_db()
    await sfd._run_seeds()
    second = await sfd._run_seeds()

    second_food_inserted, second_food_updated, second_food_total = second[:3]
    assert second_food_inserted == 0
    assert second_food_updated == 50
    assert second_food_total == 50
