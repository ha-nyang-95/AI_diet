"""Story 3.3 — `AsyncPostgresSaver` factory + `lg_checkpoints` schema 격리 (AC2, D1/D2/D3).

design:
- `_to_psycopg_dsn`: SQLAlchemy `postgresql+asyncpg://...` URL → psycopg3 sync 표기.
  asyncpg(SQLAlchemy)와 psycopg3(checkpoint-postgres)는 binary protocol 호환 X — 별
  pool 격리 필요 (D2).
- `build_checkpointer`: lifespan에서 1회 호출 SOT. 단계:
  1. **schema 사전 생성** — `langgraph-checkpoint-postgres`는 schema 자동 생성 X. 별
     connection으로 `CREATE SCHEMA IF NOT EXISTS lg_checkpoints` 실행 (race 회피
     위해 single-flight — lifespan 1회 호출 정합).
  2. **`AsyncConnectionPool`** — `kwargs={"options": "-c search_path=..."}` 로 연결
     레벨 search_path 격리. `open=False` + 명시 `await pool.open()` (psycopg-pool 3.3
     deprecation 회피).
  3. **`AsyncPostgresSaver(pool)` + `await checkpointer.setup()`** — schema 내부
     `checkpoints`/`checkpoint_blobs`/`checkpoint_writes` 3 테이블 idempotent 생성.
- 에러 매핑: psycopg `OperationalError` / `InterfaceError` → `AnalysisCheckpointerError`
  (cause 보존 — Sentry stack trace 정상).
- 보안 — `_to_psycopg_dsn`은 password 포함 URL 변환만, raw DSN 로깅 X (NFR-S5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import psycopg
import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import errors as pg_errors
from psycopg_pool import AsyncConnectionPool

from app.core.exceptions import AnalysisCheckpointerError

if TYPE_CHECKING:  # pragma: no cover
    pass

log = structlog.get_logger()

_LG_SCHEMA = "lg_checkpoints"


def _to_psycopg_dsn(database_url: str) -> str:
    """SQLAlchemy `postgresql+asyncpg://...` 또는 `postgres://...` → psycopg3 표기.

    psycopg3는 `postgresql://` (또는 `postgres://`) scheme + 표준 5-tuple만 수용 —
    `+asyncpg` driver suffix는 `urllib.parse`로 분해 후 prefix swap. 비표준 scheme
    은 `ValueError`.
    """
    parts = urlsplit(database_url)
    scheme = parts.scheme
    if scheme.startswith("postgresql+") or scheme.startswith("postgres+"):
        scheme = scheme.split("+", 1)[0]
    if scheme not in {"postgresql", "postgres"}:
        raise ValueError(f"unsupported scheme for psycopg DSN: {parts.scheme!r}")
    # Normalize to postgresql:// (psycopg는 둘 다 수용하나 표준 형태로 통일)
    return urlunsplit(("postgresql", parts.netloc, parts.path, parts.query, parts.fragment))


async def _ensure_schema(dsn: str, schema: str) -> None:
    """schema 사전 생성 — single-flight, lifespan 1회 호출.

    pool 외부의 별 connection으로 실행 — pool open *전*에 schema가 존재해야 setup()
    이 안전. `IF NOT EXISTS`로 idempotent. `autocommit=True`로 broken-state rollback
    회피(`CREATE SCHEMA` 실패 시에도 connection close가 깨끗).
    """
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        # 식별자 SQL injection 방어 — `psycopg.sql.Identifier`로 quoting 위임.
        from psycopg import sql as _sql

        stmt = _sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(_sql.Identifier(schema))
        await conn.execute(stmt)


async def build_checkpointer(
    database_url: str,
    *,
    schema: str = _LG_SCHEMA,
    min_size: int = 1,
    max_size: int = 4,
) -> tuple[AsyncPostgresSaver, AsyncConnectionPool]:
    """`AsyncPostgresSaver` + `AsyncConnectionPool` 생성 + `lg_checkpoints` schema 격리.

    return tuple — caller(lifespan)가 `dispose_checkpointer(pool)` 호출 책임.
    """
    try:
        dsn = _to_psycopg_dsn(database_url)
        await _ensure_schema(dsn, schema)
        # `langgraph-checkpoint-postgres` 3.x `setup()`은 `CREATE INDEX CONCURRENTLY`
        # 호출 — transaction 외부 실행 필요. `autocommit=True` connection-level 설정
        # 이 SOT (psycopg 표준 패턴).
        pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={
                "autocommit": True,
                "options": f"-c search_path={schema},public",
            },
            open=False,
        )
        await pool.open()
        checkpointer = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
        await checkpointer.setup()
    except ValueError as exc:
        # `_to_psycopg_dsn`의 비표준 scheme 거부 — 앱 부팅 hard crash 방지.
        raise AnalysisCheckpointerError("checkpointer.setup_failed") from exc
    except (pg_errors.OperationalError, pg_errors.InterfaceError) as exc:
        raise AnalysisCheckpointerError("checkpointer.setup_failed") from exc
    except OSError as exc:
        # connection refused / DNS 실패 등 — psycopg 미통과 OSError
        raise AnalysisCheckpointerError("checkpointer.setup_failed") from exc

    log.info(
        "checkpointer.setup.complete",
        schema=schema,
        pool_min=min_size,
        pool_max=max_size,
    )
    return checkpointer, pool


async def dispose_checkpointer(pool: AsyncConnectionPool) -> None:
    """pool close — shutdown 경로 graceful (이미 close된 경우 idempotent)."""
    if getattr(pool, "closed", False):
        return
    try:
        await pool.close()
    except Exception:  # noqa: BLE001
        log.warning("checkpointer.dispose_failed", exc_info=True)


__all__ = [
    "_to_psycopg_dsn",
    "build_checkpointer",
    "dispose_checkpointer",
]
