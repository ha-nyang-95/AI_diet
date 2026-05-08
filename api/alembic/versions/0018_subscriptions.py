"""0018_subscriptions — Story 6.1 (정기결제 sandbox 신청).

신규 테이블 ``subscriptions`` — Epic 6 결제 도메인 *active 구독* SOT. 한 사용자에 1
active subscription invariant를 partial UNIQUE(``WHERE status='active'``)로 강제한다.

ENUM 3종 (architecture.md:396 ``<table>_<col>_enum`` 정합):

- ``subscriptions_status_enum``    ``active`` / ``cancelled`` / ``expired``
- ``subscriptions_plan_enum``      ``monthly`` (단일값, ALTER TYPE ADD VALUE 자연 확장)
- ``subscriptions_provider_enum``  ``toss`` / ``stripe`` (6.1은 ``toss``만 INSERT,
                                   ``stripe``은 forward-compat 등재)

12 컬럼: id / user_id / status / plan / plan_price_krw / started_at / cancelled_at
/ expires_at / provider / provider_billing_key / created_at / updated_at.

partial UNIQUE 1건: ``idx_subscriptions_user_id_active_unique`` ``(user_id) WHERE
status = 'active'``.

FK ondelete=CASCADE — Story 5.2 30일 grace 후 hard-delete cascade 정합.

downgrade는 partial UNIQUE → 테이블 → ENUM 3종 역순 — 의존성 cascade 보호.

ENUM 생성은 ``op.execute(CREATE TYPE ... IF NOT EXISTS)``로 idempotent — 0005 패턴 정합.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_subscriptions"
down_revision: str | None = "0017_users_deletion_reason_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_NAME = "subscriptions"
_INDEX_ACTIVE_UNIQUE = "idx_subscriptions_user_id_active_unique"

_ENUM_STATUS_NAME = "subscriptions_status_enum"
_ENUM_STATUS_VALUES = ("active", "cancelled", "expired")
_ENUM_PLAN_NAME = "subscriptions_plan_enum"
_ENUM_PLAN_VALUES = ("monthly",)
_ENUM_PROVIDER_NAME = "subscriptions_provider_enum"
_ENUM_PROVIDER_VALUES = ("toss", "stripe")


def _enum_literals(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # 1) Postgres ENUM 타입 3종 CREATE (테이블 생성 *전*에 타입 존재 보장).
    # idempotent: 같은 transaction에서 부분 실패 후 재실행 시 ENUM이 이미 존재할 수 있음.
    op.execute(
        f"DO $$ BEGIN "
        f"  CREATE TYPE {_ENUM_STATUS_NAME} AS ENUM ({_enum_literals(_ENUM_STATUS_VALUES)}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; "
        f"END $$;"
    )
    op.execute(
        f"DO $$ BEGIN "
        f"  CREATE TYPE {_ENUM_PLAN_NAME} AS ENUM ({_enum_literals(_ENUM_PLAN_VALUES)}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; "
        f"END $$;"
    )
    op.execute(
        f"DO $$ BEGIN "
        f"  CREATE TYPE {_ENUM_PROVIDER_NAME} AS ENUM ({_enum_literals(_ENUM_PROVIDER_VALUES)}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; "
        f"END $$;"
    )

    # 2) 테이블 생성 — 컬럼 ENUM 매핑은 ``create_type=False``로 ENUM 생성 책임 분리.
    op.create_table(
        _TABLE_NAME,
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.dialects.postgresql.ENUM(
                *_ENUM_STATUS_VALUES,
                name=_ENUM_STATUS_NAME,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "plan",
            sa.dialects.postgresql.ENUM(
                *_ENUM_PLAN_VALUES,
                name=_ENUM_PLAN_NAME,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("plan_price_krw", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "provider",
            sa.dialects.postgresql.ENUM(
                *_ENUM_PROVIDER_VALUES,
                name=_ENUM_PROVIDER_NAME,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("provider_billing_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # 3) partial UNIQUE — 한 사용자 1 active subscription invariant.
    op.create_index(
        _INDEX_ACTIVE_UNIQUE,
        _TABLE_NAME,
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_ACTIVE_UNIQUE, table_name=_TABLE_NAME)
    op.drop_table(_TABLE_NAME)
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_PROVIDER_NAME}")
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_PLAN_NAME}")
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_STATUS_NAME}")
