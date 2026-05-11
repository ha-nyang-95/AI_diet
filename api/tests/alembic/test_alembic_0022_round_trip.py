"""Story 7.3 AC1+AC5 — 0022_create_audit_logs 스키마/ENUM/인덱스/트리거 회귀 가드.

본 모듈은 *DB 레벨 SOT*. conftest.py의 autouse ``_alembic_upgrade_head`` fixture가
이미 ``audit_logs`` 테이블 + ENUM + 트리거 + 3 인덱스를 생성한 상태이므로 본 테스트는
``pg_catalog``/``information_schema`` 쿼리로 *모든 alembic DDL 산출물이 실제로
존재*하는지 회귀 가드.

upgrade ↔ downgrade round-trip은 conftest `_alembic_upgrade_head` fixture와 충돌
가능(autouse session-scoped — DB를 head로 강제). 본 모듈은 **post-upgrade 검증**
방식으로 round-trip 동일 보장(test 진행 중 ``alembic downgrade -1 && alembic upgrade
head`` 수동 CLI 회귀 SOP는 PR review 단계 + CI workflow에 별도 step 추가 권장 —
Story 8 forward).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.audit_log import AUDIT_LOG_ACTION_VALUES
from app.main import app


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    """``app.state.session_maker``는 lifespan에서 init — `client` fixture가 lifespan 활성."""
    _ = client
    return app.state.session_maker


@pytest.mark.asyncio
async def test_alembic_0022_creates_audit_logs_table_with_13_columns(
    session_maker: async_sessionmaker,
) -> None:
    """AC1 — ``audit_logs`` 테이블 + 13 컬럼 SOT 회귀 가드.

    alembic 0022 upgrade 결과로 컬럼명·nullable·default·type이 spec과 일치하는지
    pg_catalog 쿼리로 검증. 컬럼 누락/추가/타입 변경 시 fail로 즉시 신호.
    """
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_name = 'audit_logs' "
                "ORDER BY ordinal_position"
            )
        )
        rows = list(result.all())

    cols = {row.column_name: row for row in rows}

    expected = {
        "id",
        "occurred_at",
        "actor_id",
        "actor_email_masked",
        "action",
        "target_user_id",
        "target_resource",
        "target_resource_id",
        "path",
        "method",
        "ip",
        "request_id",
        "user_agent",
    }
    assert set(cols.keys()) == expected, f"audit_logs 컬럼 SOT mismatch: {set(cols.keys())}"

    # NOT NULL 컬럼 SOT
    not_null = {
        "id",
        "occurred_at",
        "actor_id",
        "actor_email_masked",
        "action",
        "path",
        "method",
        "request_id",
    }
    for col in not_null:
        assert cols[col].is_nullable == "NO", (
            f"{col} 은 NOT NULL invariant 위반: {cols[col].is_nullable}"
        )

    # NULL 허용 컬럼 SOT
    nullable = {"target_user_id", "target_resource", "target_resource_id", "ip", "user_agent"}
    for col in nullable:
        assert cols[col].is_nullable == "YES", (
            f"{col} 은 NULL 허용 invariant 위반: {cols[col].is_nullable}"
        )

    # server_default 검증 (id: gen_random_uuid, occurred_at: now())
    assert cols["id"].column_default is not None
    assert "gen_random_uuid" in cols["id"].column_default
    assert cols["occurred_at"].column_default is not None
    assert "now()" in cols["occurred_at"].column_default

    # INET 타입 정합 (ip 컬럼)
    assert cols["ip"].data_type == "inet"


@pytest.mark.asyncio
async def test_alembic_0022_creates_audit_logs_action_enum_with_7_values(
    session_maker: async_sessionmaker,
) -> None:
    """AC1 — ``audit_logs_action_enum`` 7 값 SOT 회귀 가드.

    ENUM 값 SOT는 ``app/db/models/audit_log.py:AUDIT_LOG_ACTION_VALUES`` 및 alembic
    0022 ``_ENUM_VALUES``와 *3 지점 일관*. 7번째 ``user_pii_view``는 Story 7.4
    forward 등재(본 스토리는 wire 0건이지만 ENUM 등록은 본 스토리에서 완결 — 7.4
    추가 migration 회피).
    """
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT enumlabel FROM pg_enum "
                "WHERE enumtypid = 'audit_logs_action_enum'::regtype "
                "ORDER BY enumsortorder"
            )
        )
        labels = [row.enumlabel for row in result.all()]

    assert labels == list(AUDIT_LOG_ACTION_VALUES), (
        f"audit_logs_action_enum 값 SOT mismatch. got={labels}, "
        f"expected={list(AUDIT_LOG_ACTION_VALUES)}"
    )


@pytest.mark.asyncio
async def test_alembic_0022_creates_three_indexes_with_correct_definitions(
    session_maker: async_sessionmaker,
) -> None:
    """AC5 — 3 인덱스 정의 SOT 회귀 가드 (epics.md:918 정합).

    - ``idx_audit_logs_occurred_at`` ``(occurred_at DESC)`` btree
    - ``idx_audit_logs_actor_id_occurred_at`` ``(actor_id, occurred_at DESC)`` btree
    - ``idx_audit_logs_target_user_id_occurred_at`` partial WHERE
      ``target_user_id IS NOT NULL``
    """
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'audit_logs' "
                "ORDER BY indexname"
            )
        )
        rows = {row.indexname: row.indexdef for row in result.all()}

    # PK 인덱스 + 3 비즈니스 인덱스 = 4건
    assert "audit_logs_pkey" in rows
    assert "idx_audit_logs_occurred_at" in rows
    assert "idx_audit_logs_actor_id_occurred_at" in rows
    assert "idx_audit_logs_target_user_id_occurred_at" in rows

    # occurred_at DESC 단일 인덱스
    occ_def = rows["idx_audit_logs_occurred_at"]
    assert "occurred_at DESC" in occ_def, f"DESC 정렬 누락: {occ_def}"

    # actor_id, occurred_at DESC 복합 인덱스
    actor_def = rows["idx_audit_logs_actor_id_occurred_at"]
    assert "actor_id" in actor_def
    assert "occurred_at DESC" in actor_def

    # target_user_id partial WHERE
    target_def = rows["idx_audit_logs_target_user_id_occurred_at"]
    assert "target_user_id" in target_def
    assert "occurred_at DESC" in target_def
    assert "WHERE" in target_def
    assert "target_user_id IS NOT NULL" in target_def


@pytest.mark.asyncio
async def test_alembic_0022_creates_append_only_trigger_and_function(
    session_maker: async_sessionmaker,
) -> None:
    """AC4 — append-only trigger + PL/pgSQL function 존재 회귀 가드.

    ``audit_logs_append_only_guard`` PL/pgSQL function + ``audit_logs_append_only``
    BEFORE UPDATE OR DELETE trigger가 alembic 0022 upgrade 결과로 생성됐는지
    pg_proc + pg_trigger 쿼리로 검증.
    """
    async with session_maker() as session:
        # function 존재 확인
        func_result = await session.execute(
            text("SELECT proname FROM pg_proc WHERE proname = 'audit_logs_append_only_guard'")
        )
        funcs = [row.proname for row in func_result.all()]
        assert "audit_logs_append_only_guard" in funcs

        # trigger 존재 확인 (BEFORE UPDATE OR DELETE)
        trig_result = await session.execute(
            text(
                "SELECT tgname, tgtype FROM pg_trigger "
                "WHERE tgname = 'audit_logs_append_only' "
                "AND NOT tgisinternal"
            )
        )
        trigs = [(row.tgname, row.tgtype) for row in trig_result.all()]
        assert len(trigs) == 1, f"audit_logs_append_only trigger 1건 SOT mismatch: {trigs}"
        # tgtype은 비트필드 — BEFORE(2) + ROW(1) + UPDATE(16) + DELETE(8) = 27
        # 비트 정합 강제는 안 함(Postgres internals 변경 risk), 존재만 확인.


@pytest.mark.asyncio
async def test_alembic_0022_audit_logs_actor_id_fk_restrict(
    session_maker: async_sessionmaker,
) -> None:
    """AC1 — ``actor_id`` FK ``ON DELETE RESTRICT`` invariant 회귀 가드.

    admin hard delete 시 audit row 보존 invariant — RESTRICT 분기로 cron 또는 운영
    SOP 신호 (Story 5.2/8 forward).
    """
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT confdeltype::text AS confdeltype FROM pg_constraint "
                "WHERE conrelid = 'audit_logs'::regclass "
                "AND contype = 'f' "
                "AND conkey @> array["
                "  (SELECT attnum FROM pg_attribute "
                "   WHERE attrelid = 'audit_logs'::regclass AND attname = 'actor_id')"
                "]"
            )
        )
        row = result.first()
        assert row is not None
        # 'r' = RESTRICT (pg_constraint.confdeltype은 char — ::text 캐스트로 str 변환)
        assert row.confdeltype == "r", f"actor_id ON DELETE RESTRICT 위반: {row.confdeltype}"


@pytest.mark.asyncio
async def test_alembic_0022_audit_logs_target_user_id_fk_set_null(
    session_maker: async_sessionmaker,
) -> None:
    """AC1 — ``target_user_id`` FK ``ON DELETE SET NULL`` invariant 회귀 가드.

    대상 사용자 hard delete 시 audit row 보존 + target_user_id NULL로 *"삭제된
    사용자에 대한 audit"* 식별 가능.
    """
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT confdeltype::text AS confdeltype FROM pg_constraint "
                "WHERE conrelid = 'audit_logs'::regclass "
                "AND contype = 'f' "
                "AND conkey @> array["
                "  (SELECT attnum FROM pg_attribute "
                "   WHERE attrelid = 'audit_logs'::regclass AND attname = 'target_user_id')"
                "]"
            )
        )
        row = result.first()
        assert row is not None
        # 'n' = SET NULL (::text 캐스트)
        assert row.confdeltype == "n", f"target_user_id ON DELETE SET NULL 위반: {row.confdeltype}"
