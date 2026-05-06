"""Story 3.9 AC5 — ``meals.idempotency_key`` 30일 TTL cleanup script.

Daily KST 02:00 cron(`.github/workflows/cleanup-idempotency-cron.yml`)에서 호출.

흐름:
1. ``UPDATE meals SET idempotency_key = NULL WHERE idempotency_key IS NOT NULL
   AND created_at < NOW() - INTERVAL '30 days'`` 실행.
2. ``rows_updated`` 카운트를 structlog INFO 로그로 출력.
3. graceful — DB 장애 / connection 거부 시 비-zero exit (cron continue-on-error true로
   운영 차단 X).

**재충돌 가드**: ``meals.idempotency_key`` partial UNIQUE index는
``WHERE idempotency_key IS NOT NULL``이므로 NULL clear 시 unique 제약 자동 해제.
TTL clear 후 같은 키로 재시도 시 새 row 생성 의도(중복 자체 의도된 동작 — 모바일 큐
14일 자동 폐기 대비 30일 안전 마진).
"""

from __future__ import annotations

import asyncio
import sys

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# scripts는 sys.path[0]에 자동 추가되지만, app 패키지 import용으로 명시 추가.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "api"))

from app.core.config import settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402

log = structlog.get_logger("cleanup_idempotency_keys")

_TTL_DAYS = 30


async def cleanup_idempotency_keys(*, ttl_days: int = _TTL_DAYS) -> int:
    """``meals.idempotency_key`` TTL 경과 row의 키를 NULL로 clear.

    Returns: ``rows_updated`` 카운트 (RowCountResult.rowcount).

    CR P8 (2026-05-06) — ``ttl_days <= 0`` 시 ``ValueError``. 음수/0 입력은 NOW() -
    음수 = 미래 시각이 되어 *모든* row의 키를 NULL로 만들어 30일 보호 자체를 깨뜨리므로
    명시적 거부.
    """
    if ttl_days <= 0:
        raise ValueError(f"ttl_days must be positive (got {ttl_days})")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE meals SET idempotency_key = NULL "
                    "WHERE idempotency_key IS NOT NULL "
                    "AND created_at < NOW() - (:ttl_days * INTERVAL '1 day')"
                ),
                {"ttl_days": ttl_days},
            )
            rows = int(result.rowcount or 0)
            log.info(
                "idempotency.cleanup.completed",
                rows_updated=rows,
                ttl_days=ttl_days,
            )
            return rows
    except Exception as exc:  # noqa: BLE001 — graceful — cron continue-on-error.
        # CR P7 (2026-05-06) — 실패 경로에서 ``cleanup.completed rows_updated=0``를
        # 추가 emit하면 metrics 대시보드가 *성공 + 실패 동시 발생*으로 오해. 실패 시
        # ``cleanup.failed``만 남기고 즉시 raise(호출자가 exit code 1로 cron 정합).
        log.error(
            "idempotency.cleanup.failed",
            error_class=type(exc).__name__,
            error=str(exc),
        )
        raise
    finally:
        await engine.dispose()


def main() -> int:
    configure_logging()
    try:
        rows = asyncio.run(cleanup_idempotency_keys())
        log.info("idempotency.cleanup.exit", rows_updated=rows)
        return 0
    except Exception:  # noqa: BLE001 — main level catch — cron exit code.
        return 1


if __name__ == "__main__":
    sys.exit(main())
