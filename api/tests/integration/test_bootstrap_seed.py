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


def _import_seed_guidelines() -> ModuleType:
    """scripts/seed_guidelines 모듈 import — Story 3.2."""
    sys.modules.pop("seed_guidelines", None)
    import seed_guidelines  # type: ignore[import-not-found]

    module: ModuleType = seed_guidelines
    return module


def _import_bootstrap_seed() -> ModuleType:
    """scripts/bootstrap_seed 모듈 import — Story 3.1 baseline + Story 3.2 갱신."""
    sys.modules.pop("bootstrap_seed", None)
    import bootstrap_seed  # type: ignore[import-not-found]

    module: ModuleType = bootstrap_seed
    return module


async def _truncate_knowledge_chunks_table(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await session.execute(text("TRUNCATE knowledge_chunks RESTART IDENTITY"))
        await session.commit()


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


def test_bootstrap_seed_prod_fail_fast(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """environment=prod + 두 경로 실패 → ``main()`` exit 1 + Sentry capture (AC #6 case 3)."""
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
    monkeypatch.setattr(settings, "environment", "prod", raising=False)
    monkeypatch.setattr(settings, "sentry_dsn", "https://example@sentry.local/1", raising=False)
    monkeypatch.setattr(food_seed, "SEED_TARGET_COUNT", 50)

    sfd = _import_seed_food_db()
    captured: list[BaseException] = []
    captured_tags: list[tuple[str, str]] = []
    monkeypatch.setattr(sfd.sentry_sdk, "capture_exception", lambda exc: captured.append(exc))

    class _ScopeStub:
        def __enter__(self) -> _ScopeStub:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def set_tag(self, key: str, value: str) -> None:
            captured_tags.append((key, value))

    monkeypatch.setattr(sfd.sentry_sdk, "push_scope", lambda: _ScopeStub())

    exit_code = sfd.main()

    assert exit_code == 1
    assert any(v == "food_db_total_failure" for _, v in captured_tags)
    assert captured, "Sentry capture_exception was not called"


def test_bootstrap_seed_dev_strict_opt_in(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """environment=dev + RUN_FOOD_SEED_STRICT=1 → graceful 무효 → exit 1 (AC #6 case 4)."""
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
    monkeypatch.setenv("RUN_FOOD_SEED_STRICT", "1")
    monkeypatch.setattr(food_seed, "SEED_TARGET_COUNT", 50)

    sfd = _import_seed_food_db()
    exit_code = sfd.main()

    assert exit_code == 1


# --- Story 3.2 — bootstrap_seed food → guidelines 순차 호출 (AC #4) ---
#
# bootstrap_seed.main()은 sync wrapper(asyncio.run을 내부에서 호출)이므로 async test에서
# 직접 호출하면 "asyncio.run() cannot be called from a running event loop"로 실패한다.
# Story 3.1 패턴 정합 — async core(_run_seeds())를 *직접* await + sync 래퍼는 별도
# sync test에서 검증.


async def test_bootstrap_seed_food_and_guidelines_normal(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """정상 시드 — food + guidelines async core 순차 await → 두 테이블 모두 시드 성공.

    bootstrap_seed.main()은 sync wrapper로 *별 sync test에서만 검증* — async test에서
    asyncio.run() 호출 시 "running event loop" 충돌 회피.
    """
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_tables(session_maker)
    await _truncate_knowledge_chunks_table(session_maker)

    sample = [_build_raw(i) for i in range(50)]

    async def fake_fetch(
        target_count: int = 1500, *, page_size: int = 100
    ) -> list[FoodNutritionRaw]:
        return sample[:target_count]

    async def fake_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(mfds_module, "fetch_food_items", fake_fetch)
    monkeypatch.setattr(openai_module, "embed_texts", fake_embed)
    monkeypatch.setattr(food_seed, "SEED_TARGET_COUNT", 50)

    sfd = _import_seed_food_db()
    sgd = _import_seed_guidelines()

    food_result = await sfd._run_seeds()
    guideline_result = await sgd._run_seeds()

    assert food_result[2] >= 50  # food_total
    assert guideline_result.total >= 40
    assert guideline_result.embeddings_skipped is False

    async with session_maker() as session:
        food_count = (
            await session.execute(text("SELECT count(*) AS n FROM food_nutrition"))
        ).first()
        kc_count = (
            await session.execute(text("SELECT count(*) AS n FROM knowledge_chunks"))
        ).first()
    assert food_count is not None and food_count.n >= 50
    assert kc_count is not None and kc_count.n >= 40


async def test_bootstrap_seed_guidelines_graceful_when_no_openai_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """food OK + guidelines OPENAI_API_KEY 미설정 + dev → knowledge_chunks ≥ 40 (NULL embedding).

    fixture 분리 — food와 guidelines 임베딩을 별도 컨트롤(food는 정상, guidelines는 raise).
    """
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_food_tables(session_maker)
    await _truncate_knowledge_chunks_table(session_maker)

    sample = [_build_raw(i) for i in range(50)]

    async def fake_fetch(
        target_count: int = 1500, *, page_size: int = 100
    ) -> list[FoodNutritionRaw]:
        return sample[:target_count]

    async def food_only_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        # food 시드는 정상 임베딩 / guidelines 시드는 별도 monkeypatch에서 raise.
        return [[0.01] * 1536 for _ in texts]

    async def guidelines_no_key_embed(
        texts: list[str], *, batch_size: int = 300
    ) -> list[list[float]]:
        from app.core.exceptions import MealOCRUnavailableError

        raise MealOCRUnavailableError("OPENAI_API_KEY not configured (test)")

    monkeypatch.setattr(mfds_module, "fetch_food_items", fake_fetch)
    monkeypatch.setattr(food_seed, "SEED_TARGET_COUNT", 50)
    monkeypatch.setattr(settings, "environment", "dev", raising=False)

    # food 시드 — 정상 임베딩 fixture.
    monkeypatch.setattr(openai_module, "embed_texts", food_only_embed)
    sfd = _import_seed_food_db()
    food_result = await sfd._run_seeds()
    assert food_result[2] >= 50  # food_total

    # guidelines 시드 — OPENAI_API_KEY 미설정 모사로 graceful.
    monkeypatch.setattr(openai_module, "embed_texts", guidelines_no_key_embed)
    sgd = _import_seed_guidelines()
    guideline_result = await sgd._run_seeds()
    assert guideline_result.total >= 40
    assert guideline_result.embeddings_skipped is True

    async with session_maker() as session:
        kc_total = (
            await session.execute(text("SELECT count(*) AS n FROM knowledge_chunks"))
        ).first()
        kc_null = (
            await session.execute(
                text("SELECT count(*) AS n FROM knowledge_chunks WHERE embedding IS NULL")
            )
        ).first()
    assert kc_total is not None and kc_total.n >= 40
    # graceful이면 모든 guideline chunks가 NULL embedding.
    assert kc_null is not None and kc_null.n == kc_total.n
