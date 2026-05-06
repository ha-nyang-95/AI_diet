"""0014_create_notifications — Story 4.2 (APScheduler nudge 미기록 푸시 + 멱등 가드).

신규 테이블 ``notifications`` — 사용자별 push 발송 이력 + 멱등 가드. Story 4.2 nudge cron이
*동일 날 동일 kind 1회 발사* 보장하는 SOT.

8 컬럼:

- ``id``                    ``BIGSERIAL`` PRIMARY KEY
- ``user_id``               ``UUID NOT NULL`` FK ``users(id) ON DELETE CASCADE``
- ``kind``                  ``TEXT NOT NULL`` — 알림 종류(현재 ``unrecorded_meal`` 단일 enum)
- ``kst_date``              ``DATE NOT NULL`` — KST 자정 기준 발사 날짜(자정 cross 처리 SOT)
- ``sent_at``               ``TIMESTAMPTZ NOT NULL DEFAULT now()`` — 실 발사 시각(UTC)
- ``expo_ticket_id``        ``TEXT NULL`` — Expo publish_multiple ticket id (receipts polling 입력)
- ``expo_receipt_status``   ``TEXT NULL`` — receipts 후속 polling 도입 시 update(Story 4.4 forward)
- ``expo_receipt_error``    ``TEXT NULL`` — receipts error code (`DeviceNotRegistered` 등)

CHECK 제약 1건:

- ``ck_notifications_kind`` ``kind IN ('unrecorded_meal')`` — 미래 ``weekly_report_ready`` /
  ``account_deletion_grace`` 등 추가 kind는 본 CHECK drop+recreate(Story 1.5 R8 SOP 정합).

UNIQUE 제약 1건:

- ``ux_notifications_user_kind_date`` ``(user_id, kind, kst_date)`` — *동일 날 동일 kind 1회
  발사 SOT*. INSERT race 시 IntegrityError → cron이 swallow + warn(다음 cycle 재시도 시
  이미 row 존재라 skip — 멱등 정합).

인덱스 1건:

- ``idx_notifications_user_kst_date`` ``(user_id, kst_date)`` — Story 4.4 인사이트 카드의
  *최근 7일 발사 이력 조회*(forward use). UNIQUE 인덱스로 lookup 가능하지만 별도 비-UNIQUE
  index가 user-by-date range scan에 더 효율적.

downgrade는 인덱스 → CHECK → UNIQUE → 테이블 drop 역순 — Story 1.5 패턴 정합.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_create_notifications"
down_revision: str | None = "0013_users_notification_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_NAME = "notifications"
_CHECK_KIND_NAME = "ck_notifications_kind"
_CHECK_KIND_SQL = "kind IN ('unrecorded_meal')"
_UNIQUE_NAME = "ux_notifications_user_kind_date"
_INDEX_NAME = "idx_notifications_user_kst_date"


def upgrade() -> None:
    op.create_table(
        _TABLE_NAME,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("kst_date", sa.Date(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expo_ticket_id", sa.Text(), nullable=True),
        sa.Column("expo_receipt_status", sa.Text(), nullable=True),
        sa.Column("expo_receipt_error", sa.Text(), nullable=True),
        sa.CheckConstraint(_CHECK_KIND_SQL, name=_CHECK_KIND_NAME),
        sa.UniqueConstraint("user_id", "kind", "kst_date", name=_UNIQUE_NAME),
    )
    op.create_index(
        _INDEX_NAME,
        _TABLE_NAME,
        ["user_id", "kst_date"],
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME)
    op.drop_table(_TABLE_NAME)
