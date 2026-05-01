"""Story 3.1 — ``seed_food_db.py`` entry point.

Docker ``seed`` 컨테이너 + 로컬 dev에서 호출. 1차 식약처 OpenAPI + 2차 ZIP fallback +
dev/ci/test graceful 분기. 모든 시드는 멱등(``ON CONFLICT DO UPDATE``).

종료 코드:
- 0 — 시드 성공 또는 dev graceful 0건 진행.
- 1 — prod/staging 또는 strict 모드에서 두 경로 모두 실패.

stdout 통계 — `[seed_food_db] inserted={n} updated={n} total={n} source={primary|fallback|primary+fallback|none}`.
"""

from __future__ import annotations

import asyncio
import sys
import traceback

import sentry_sdk
import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.exceptions import FoodSeedError
from app.rag.food.aliases_seed import seed_food_aliases
from app.rag.food.seed import run_food_seed

logger = structlog.get_logger(__name__)


async def _run_seeds() -> tuple[int, int, int, int, int, int, str]:
    """모든 시드를 단일 engine에서 순차 실행.

    Returns:
        ``(food_inserted, food_updated, food_total, alias_inserted, alias_updated, alias_total, source)``.
    """
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        # food_nutrition 시드 1차.
        async with session_maker() as session:
            food_result = await run_food_seed(session)
            await session.commit()

        # food_aliases 시드 2차 — food_nutrition과 독립(orphan canonical_name 허용).
        async with session_maker() as session:
            alias_result = await seed_food_aliases(session)
            await session.commit()

        return (
            food_result.inserted,
            food_result.updated,
            food_result.total,
            alias_result.inserted,
            alias_result.updated,
            alias_result.total,
            food_result.source,
        )
    finally:
        await engine.dispose()


def main() -> int:
    try:
        (
            food_inserted,
            food_updated,
            food_total,
            alias_inserted,
            alias_updated,
            alias_total,
            source,
        ) = asyncio.run(_run_seeds())
        # NFR-S5 — count + source만 stdout (raw 음식명 노출 X).
        print(
            f"[seed_food_db] food_nutrition: inserted={food_inserted} "
            f"updated={food_updated} total={food_total} source={source}"
        )
        print(
            f"[seed_food_db] food_aliases: inserted={alias_inserted} "
            f"updated={alias_updated} total={alias_total}"
        )
        if food_total == 0 and source == "none":
            # AC11 시나리오 2 — stdout warning(컨테이너 stdout 수집기 정합).
            print(
                f"[seed_food_db] WARN — food_nutrition seed unavailable "
                f"(MFDS_OPENAPI_KEY missing or ZIP empty), aliases-only mode for {settings.environment}"
            )
        return 0
    except FoodSeedError as exc:
        # prod/staging 또는 strict 모드 fail — Sentry capture + 비-zero exit.
        print(f"[seed_food_db] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        if settings.sentry_dsn:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("seed", "food_db_total_failure")
                sentry_sdk.capture_exception(exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[seed_food_db] UNEXPECTED FAILURE: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        if settings.sentry_dsn:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("seed", "food_db_unexpected_failure")
                sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
