"""Story 7.3 AC4+AC5 — audit_logs append-only trigger + partial index 검증.

본 모듈은 *DB 레벨 SOT* — alembic 0022가 박은 ``audit_logs_append_only`` 트리거가
실제로 UPDATE/DELETE를 차단하고 INSERT는 통과시키는지 SQL-level 회귀 가드 +
``idx_audit_logs_target_user_id_occurred_at`` partial WHERE 인덱스가 EXPLAIN에서
hit되는지 검증.

epics.md:917 *"audit log는 변경 불가 — INSERT 외 권한 없음 (DB role 분리 또는 트리거)"*
의 트리거 분기 SOT.
epics.md:918 *"audit_logs 1만 건 가정 검색 — 시간/액터/대상별 인덱스로 응답 ≤ 1초"*의
*인덱스 자체 존재 + partial WHERE 정합*만 본 스토리에서 검증. 실 검색 endpoint(7.4)
시점에 1만 row synthetic data + EXPLAIN response time 가드 추가.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.audit_log import AuditLog
from app.db.models.user import User
from app.main import app


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    """``app.state.session_maker``는 lifespan에서 init — `client` fixture가 lifespan 활성."""
    _ = client
    return app.state.session_maker


async def _make_admin(session_maker: async_sessionmaker) -> User:
    """admin role 사용자 1건 생성."""
    async with session_maker() as session:
        admin = User(
            google_sub=f"google-sub-{uuid.uuid4()}",
            email=f"admin-{uuid.uuid4().hex}@example.com",
            email_verified=True,
            role="admin",
            last_login_at=datetime.now(UTC),
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        return admin


async def _insert_audit_row(
    session_maker: async_sessionmaker,
    *,
    actor_id: uuid.UUID,
    action: str = "user_search",
    target_user_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """audit_logs INSERT helper — 트리거 차단 분기 ARRANGE 단계."""
    audit_id = uuid.uuid4()
    async with session_maker() as session:
        await session.execute(
            insert(AuditLog).values(
                id=audit_id,
                actor_id=actor_id,
                actor_email_masked="a***@example.com",
                action=action,
                target_user_id=target_user_id,
                target_resource="users",
                path="/v1/admin/users",
                method="GET",
                request_id="test-req-id",
            )
        )
        await session.commit()
    return audit_id


@pytest.mark.asyncio
async def test_audit_log_insert_succeeds(session_maker: async_sessionmaker) -> None:
    """AC4 — INSERT는 trigger 미차단 (BEFORE UPDATE OR DELETE 명시)."""
    admin = await _make_admin(session_maker)
    audit_id = await _insert_audit_row(session_maker, actor_id=admin.id)

    async with session_maker() as session:
        result = await session.execute(
            text("SELECT id, action, request_id FROM audit_logs WHERE id = :id"),
            {"id": audit_id},
        )
        row = result.first()
        assert row is not None
        assert row.action == "user_search"
        assert row.request_id == "test-req-id"


@pytest.mark.asyncio
async def test_audit_log_update_raises_exception(session_maker: async_sessionmaker) -> None:
    """AC4 — UPDATE 시도 시 ``RAISE EXCEPTION ... ERRCODE 'P0001'`` 차단.

    epics.md:917 invariant — audit log는 *append-only*. SQL-level UPDATE 차단은
    application-level fail-open과 *직교* (애플리케이션이 audit를 신뢰할 수 있는 근거).
    """
    admin = await _make_admin(session_maker)
    audit_id = await _insert_audit_row(session_maker, actor_id=admin.id)

    async with session_maker() as session:
        with pytest.raises(DBAPIError) as exc_info:
            await session.execute(
                update(AuditLog).where(AuditLog.id == audit_id).values(action="user_profile_view")
            )
            await session.commit()
        # error message에 append-only + UPDATE 명시
        assert "append-only" in str(exc_info.value).lower() or "P0001" in str(exc_info.value)


@pytest.mark.asyncio
async def test_audit_log_delete_raises_exception(session_maker: async_sessionmaker) -> None:
    """AC4 — DELETE 시도 시 ``RAISE EXCEPTION ... ERRCODE 'P0001'`` 차단.

    UPDATE와 동일 패턴 — 같은 트리거 function이 ``TG_OP``로 분기 (메시지 내
    ``DELETE`` 노출).
    """
    admin = await _make_admin(session_maker)
    audit_id = await _insert_audit_row(session_maker, actor_id=admin.id)

    async with session_maker() as session:
        with pytest.raises(DBAPIError) as exc_info:
            await session.execute(delete(AuditLog).where(AuditLog.id == audit_id))
            await session.commit()
        assert "append-only" in str(exc_info.value).lower() or "P0001" in str(exc_info.value)


@pytest.mark.asyncio
async def test_audit_log_partial_index_excludes_null_target_user_id(
    session_maker: async_sessionmaker,
) -> None:
    """AC5 — ``idx_audit_logs_target_user_id_occurred_at`` partial WHERE invariant.

    target_user_id NULL row + NOT NULL row 혼합 INSERT 후 EXPLAIN 결과에 partial
    index 이름이 등장(=hit)하는지 검증. 검색(target_user_id NULL)은 partial 색인
    미진입으로 hot path INSERT 비용 0.

    실 1만 row + response time ≤ 1초 검증은 Story 7.4 책임 (검색 endpoint 신설
    시점에 synthetic data + EXPLAIN ANALYZE).
    """
    admin = await _make_admin(session_maker)
    target = await _make_admin(session_maker)  # 다른 admin을 target으로 (RESTRICT 충돌 회피)

    # NULL target 3건 (검색 endpoint 패턴) + NOT NULL target 2건 (detail 패턴)
    for _ in range(3):
        await _insert_audit_row(session_maker, actor_id=admin.id, target_user_id=None)
    for _ in range(2):
        await _insert_audit_row(
            session_maker, action="user_profile_view", actor_id=admin.id, target_user_id=target.id
        )

    async with session_maker() as session:
        # ARRANGE — Postgres planner가 small table에서는 인덱스 미사용으로 seq scan 우선이라
        # ``SET enable_seqscan = OFF``로 강제 분기. partial 인덱스가 *정의*만 정합하면
        # planner가 partial WHERE 매칭 시 선택 가능한지 확인 (실 hit 여부는 1만 row 시점에
        # 검증 — Story 7.4 forward).
        await session.execute(text("SET LOCAL enable_seqscan = OFF"))
        result = await session.execute(
            text(
                "EXPLAIN SELECT id, occurred_at FROM audit_logs "
                "WHERE target_user_id = :tid "
                "ORDER BY occurred_at DESC"
            ),
            {"tid": target.id},
        )
        plan = "\n".join(row[0] for row in result.all())

    # partial 인덱스 hit 또는 적어도 candidate plan에 등장 확인.
    # Postgres 14+는 partial 인덱스를 ``Index Scan using idx_audit_logs_target_user_id_occurred_at``
    # 형태로 표시. small row count에서는 BitmapHeapScan 또는 IndexScan 모두 후보.
    assert "idx_audit_logs_target_user_id_occurred_at" in plan, (
        f"partial 인덱스 후보 미진입 — plan:\n{plan}"
    )
