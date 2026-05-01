"""Story 3.2 — ``seed_guidelines.py`` entry point.

Docker ``seed`` 컨테이너 + 로컬 dev에서 호출. ``data/guidelines/*.md`` 6 파일 + 50+
chunks 멱등 시드(``ON CONFLICT DO UPDATE``).

종료 코드:
- 0 — 시드 성공 또는 dev/ci/test graceful (embedding NULL chunks 시드 진행).
- 1 — prod/staging 또는 ``RUN_GUIDELINE_SEED_STRICT=1`` strict 모드에서 실패.

stdout 통계 — ``[seed_guidelines] knowledge_chunks: inserted={n} updated={n} total={n} files_processed={n}``
+ 조건부 ``WARN — embeddings skipped`` 1줄.
"""

from __future__ import annotations

import asyncio
import sys
import traceback

import sentry_sdk
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.exceptions import GuidelineSeedError
from app.rag.guidelines.seed import GuidelineSeedResult, run_guideline_seed


async def _run_seeds() -> GuidelineSeedResult:
    """단일 engine에서 가이드라인 시드 실행."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_maker() as session:
            result = await run_guideline_seed(session)
        return result
    finally:
        await engine.dispose()


def main() -> int:
    try:
        result = asyncio.run(_run_seeds())
        # NFR-S5 — count + files만 stdout (raw chunk text 노출 X).
        print(
            f"[seed_guidelines] knowledge_chunks: inserted={result.inserted} "
            f"updated={result.updated} total={result.total} "
            f"files_processed={result.files_processed}"
        )
        if result.embeddings_skipped:
            print(
                "[seed_guidelines] WARN — embeddings skipped "
                "(OPENAI_API_KEY missing or graceful env)"
            )
        return 0
    except GuidelineSeedError as exc:
        # prod/staging 또는 strict 모드 fail — Sentry capture + 비-zero exit.
        print(
            f"[seed_guidelines] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr
        )
        traceback.print_exc(file=sys.stderr)
        if settings.sentry_dsn:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("seed", "guidelines_total_failure")
                sentry_sdk.capture_exception(exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(
            f"[seed_guidelines] UNEXPECTED FAILURE: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        if settings.sentry_dsn:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("seed", "guidelines_unexpected_failure")
                sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
