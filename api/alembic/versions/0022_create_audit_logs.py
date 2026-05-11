"""0022_create_audit_logs — Story 7.3 (관리자 audit log 자동 기록).

본 revision은 *3건 변경*:

1. ``audit_logs_action_enum`` Postgres ENUM 신규 (7 값).
2. ``audit_logs`` 테이블 신규 (13 컬럼 + 3 인덱스).
3. ``audit_logs_append_only_guard`` PL/pgSQL function + BEFORE UPDATE/DELETE
   트리거 신규 — epics.md:917 *"audit log는 변경 불가 — INSERT 외 권한 없음"* 정합.

설계 결정:

- **append-only enforcement: trigger 채택**. 대안 *DB role 분리*(audit_logs INSERT
  only role + app 일반 role)는 Railway managed Postgres에서 role 운영 SOT 별도 셋업
  + connection 분리(dual session_maker) 의무로 1인 8주 ROI 0. 트리거가 동일 invariant
  을 단일 DDL로 달성 + 회귀 테스트가 SQL-level 검증 가능. DB role 분리는 Story 8.4/8.5
  운영 polish forward(README *키 회전 SOP*와 동일 분류).
- **``actor_id ON DELETE RESTRICT``**: admin hard delete 시 audit 행 보존 invariant
  차단 + 운영 이벤트로 신호. ``users.deleted_at`` soft delete + 30일 grace +
  ``soft_delete_purge`` cron(Story 5.2)이 hard delete 시점에 RESTRICT 위반 →
  cron 실패 신호 → 운영자 인지 → 사전 audit archival SOP 트리거(Story 8 forward).
- **``target_user_id ON DELETE SET NULL``**: 대상 사용자 hard delete 시 audit 행 보존 +
  target_user_id NULL로 *"삭제된 사용자에 대한 audit"* 식별 가능.
- **``INET`` type for ip column**: Postgres native INET(IPv4 + IPv6 + CIDR notation 통합
  타입) — ``get_real_client_ip``가 IPv4-mapped IPv6(``::ffff:203.0.113.42``) 형태도
  반환 가능(Story 7.1 CR 정합)이라 INET이 자연 표현. 별 CHECK 제약 미적용 — INET 자체
  parsing이 invariant.

prod-scale lock 주의 (0020/0021 패턴 정합): 본 ``op.create_table`` + ``op.create_index``는
비-CONCURRENTLY 실행. baseline sandbox라 영향 0. 미래 prod 트래픽 후 alembic CONCURRENTLY
SOP는 Story 8.4 운영 polish forward.

회귀 0건: 신규 테이블 + ENUM + 트리거만 추가. 기존 컬럼/CHECK/인덱스 변경 없음.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022_create_audit_logs"
down_revision: str | None = "0021_admin_users_search_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_NAME = "audit_logs"
_INDEX_OCCURRED_AT = "idx_audit_logs_occurred_at"
_INDEX_ACTOR_ID_OCCURRED_AT = "idx_audit_logs_actor_id_occurred_at"
_INDEX_TARGET_USER_ID_OCCURRED_AT = "idx_audit_logs_target_user_id_occurred_at"

_ENUM_NAME = "audit_logs_action_enum"
_ENUM_VALUES = (
    "user_search",
    "user_profile_view",
    "user_meal_history_view",
    "user_feedback_history_view",
    "user_profile_edit",
    "admin_meal_delete",
    "user_pii_view",
)

_TRIGGER_FUNCTION = "audit_logs_append_only_guard"
_TRIGGER_NAME = "audit_logs_append_only"

# PL/pgSQL function — UPDATE/DELETE는 RAISE EXCEPTION으로 차단.
# SECURITY DEFINER 미적용 — 함수가 호출자 권한으로 실행(Railway DB는 단일 owner라
# 영향 0). 미래 DB role 분리(Story 8) 시점에 권한 boundary 재검토.
_CREATE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {_TRIGGER_FUNCTION}() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only: % operation forbidden', TG_OP
        USING ERRCODE = 'P0001';
END;
$$ LANGUAGE plpgsql;
"""

_DROP_FUNCTION_SQL = f"DROP FUNCTION IF EXISTS {_TRIGGER_FUNCTION}();"

_CREATE_TRIGGER_SQL = f"""
CREATE TRIGGER {_TRIGGER_NAME}
BEFORE UPDATE OR DELETE ON {_TABLE_NAME}
FOR EACH ROW EXECUTE FUNCTION {_TRIGGER_FUNCTION}();
"""

_DROP_TRIGGER_SQL = f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON {_TABLE_NAME};"


def _enum_literals(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(
        f"DO $$ BEGIN "
        f"  CREATE TYPE {_ENUM_NAME} AS ENUM "
        f"  ({_enum_literals(_ENUM_VALUES)}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; "
        f"END $$;"
    )

    op.create_table(
        _TABLE_NAME,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_email_masked", sa.Text(), nullable=False),
        sa.Column(
            "action",
            postgresql.ENUM(*_ENUM_VALUES, name=_ENUM_NAME, create_type=False),
            nullable=False,
        ),
        sa.Column(
            "target_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target_resource", sa.Text(), nullable=True),
        sa.Column("target_resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )

    op.create_index(
        _INDEX_OCCURRED_AT,
        _TABLE_NAME,
        [sa.text("occurred_at DESC")],
    )
    op.create_index(
        _INDEX_ACTOR_ID_OCCURRED_AT,
        _TABLE_NAME,
        ["actor_id", sa.text("occurred_at DESC")],
    )
    op.create_index(
        _INDEX_TARGET_USER_ID_OCCURRED_AT,
        _TABLE_NAME,
        ["target_user_id", sa.text("occurred_at DESC")],
        postgresql_where=sa.text("target_user_id IS NOT NULL"),
    )

    op.execute(_CREATE_FUNCTION_SQL)
    op.execute(_CREATE_TRIGGER_SQL)


def downgrade() -> None:
    op.execute(_DROP_TRIGGER_SQL)
    op.execute(_DROP_FUNCTION_SQL)
    op.drop_index(_INDEX_TARGET_USER_ID_OCCURRED_AT, table_name=_TABLE_NAME)
    op.drop_index(_INDEX_ACTOR_ID_OCCURRED_AT, table_name=_TABLE_NAME)
    op.drop_index(_INDEX_OCCURRED_AT, table_name=_TABLE_NAME)
    op.drop_table(_TABLE_NAME)
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_NAME}")
