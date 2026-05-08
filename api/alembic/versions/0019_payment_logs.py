"""0019_payment_logs — Story 6.1 (정기결제 sandbox 신청 + payment_logs audit-trail).

신규 테이블 ``payment_logs`` — Epic 6 결제 도메인 *audit-trail*. 모든 결제 시도(성공/
실패)와 forward-compat 이벤트를 추적. soft-delete 미적용 — audit-trail 성격이라 영구
보존(``ondelete="CASCADE"``로 사용자 삭제 시점에만 cascade).

ENUM 3종 (architecture.md:396 ``<table>_<col>_enum`` 정합):

- ``payment_logs_event_type_enum``  ``subscribe`` / ``cancel`` / ``renew`` /
                                    ``failed`` / ``refund`` (6.1은 ``subscribe``/
                                    ``failed``만 INSERT, 나머지는 forward-compat 등재)
- ``payment_logs_provider_enum``    ``toss`` / ``stripe``
- ``payment_logs_status_enum``      ``success`` / ``failed`` / ``pending`` (``pending``
                                    은 Story 6.3 webhook forward)

13 컬럼: id / user_id / subscription_id (SET NULL) / event_type / provider /
provider_payment_key / provider_order_id / amount_krw / status / idempotency_key /
raw_payload (JSONB) / occurred_at / created_at.

인덱스 3건:

- ``idx_payment_logs_user_id_occurred_at`` ``(user_id, occurred_at DESC)`` — Story
  6.2 history 조회 (시계열 sort).
- ``idx_payment_logs_provider_payment_key_unique`` ``(provider, provider_payment_key)
  WHERE provider_payment_key IS NOT NULL`` partial UNIQUE — Toss/Stripe paymentKey
  dedup (Story 6.3 webhook 멱등화 forward-compat).
- ``idx_payment_logs_user_id_idempotency_key_unique`` ``(user_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL`` partial UNIQUE — Story 2.5 0009 패턴 1:1 정합.

FK ondelete: ``user_id`` CASCADE / ``subscription_id`` SET NULL (환불/실패 결제 등
subscription 무관 이벤트 forward-compat).

downgrade는 인덱스 → 테이블 → ENUM 3종 역순.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_payment_logs"
down_revision: str | None = "0018_subscriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_NAME = "payment_logs"
_INDEX_USER_OCCURRED_AT = "idx_payment_logs_user_id_occurred_at"
_INDEX_PROVIDER_KEY_UNIQUE = "idx_payment_logs_provider_payment_key_unique"
_INDEX_IDEMPOTENCY_UNIQUE = "idx_payment_logs_user_id_idempotency_key_unique"

_ENUM_EVENT_TYPE_NAME = "payment_logs_event_type_enum"
_ENUM_EVENT_TYPE_VALUES = ("subscribe", "cancel", "renew", "failed", "refund")
_ENUM_PROVIDER_NAME = "payment_logs_provider_enum"
_ENUM_PROVIDER_VALUES = ("toss", "stripe")
_ENUM_STATUS_NAME = "payment_logs_status_enum"
_ENUM_STATUS_VALUES = ("success", "failed", "pending")


def _enum_literals(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(
        f"DO $$ BEGIN "
        f"  CREATE TYPE {_ENUM_EVENT_TYPE_NAME} AS ENUM "
        f"  ({_enum_literals(_ENUM_EVENT_TYPE_VALUES)}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; "
        f"END $$;"
    )
    op.execute(
        f"DO $$ BEGIN "
        f"  CREATE TYPE {_ENUM_PROVIDER_NAME} AS ENUM "
        f"  ({_enum_literals(_ENUM_PROVIDER_VALUES)}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; "
        f"END $$;"
    )
    op.execute(
        f"DO $$ BEGIN "
        f"  CREATE TYPE {_ENUM_STATUS_NAME} AS ENUM "
        f"  ({_enum_literals(_ENUM_STATUS_VALUES)}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; "
        f"END $$;"
    )

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
            "subscription_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "event_type",
            sa.dialects.postgresql.ENUM(
                *_ENUM_EVENT_TYPE_VALUES,
                name=_ENUM_EVENT_TYPE_NAME,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.dialects.postgresql.ENUM(
                *_ENUM_PROVIDER_VALUES,
                name=_ENUM_PROVIDER_NAME,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("provider_payment_key", sa.Text(), nullable=True),
        sa.Column("provider_order_id", sa.Text(), nullable=True),
        sa.Column("amount_krw", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.dialects.postgresql.ENUM(
                *_ENUM_STATUS_VALUES,
                name=_ENUM_STATUS_NAME,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "raw_payload",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        _INDEX_USER_OCCURRED_AT,
        _TABLE_NAME,
        ["user_id", sa.text("occurred_at DESC")],
    )
    op.create_index(
        _INDEX_PROVIDER_KEY_UNIQUE,
        _TABLE_NAME,
        ["provider", "provider_payment_key"],
        unique=True,
        postgresql_where=sa.text("provider_payment_key IS NOT NULL"),
    )
    op.create_index(
        _INDEX_IDEMPOTENCY_UNIQUE,
        _TABLE_NAME,
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_IDEMPOTENCY_UNIQUE, table_name=_TABLE_NAME)
    op.drop_index(_INDEX_PROVIDER_KEY_UNIQUE, table_name=_TABLE_NAME)
    op.drop_index(_INDEX_USER_OCCURRED_AT, table_name=_TABLE_NAME)
    op.drop_table(_TABLE_NAME)
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_STATUS_NAME}")
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_PROVIDER_NAME}")
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_EVENT_TYPE_NAME}")
