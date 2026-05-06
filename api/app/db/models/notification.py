"""Notification ORM model — Story 4.2 (APScheduler nudge 미기록 푸시 + 멱등 가드).

``notifications`` 테이블 = Story 4.2 nudge cron의 *동일 날 동일 kind 1회 발사 SOT*. UNIQUE
``(user_id, kind, kst_date)``가 INSERT race 시 IntegrityError raise → cron swallow + 다음
cycle skip(멱등 정합).

스키마 (8 컬럼):
- ``id``                  ``BIGSERIAL``     PRIMARY KEY
- ``user_id``             ``UUID NOT NULL`` FK ``users.id ON DELETE CASCADE``
- ``kind``                ``TEXT NOT NULL`` CHECK IN ('unrecorded_meal')
- ``kst_date``            ``DATE NOT NULL`` — KST 자정 기준 발사 날짜
- ``sent_at``             ``TIMESTAMPTZ NOT NULL DEFAULT now()``
- ``expo_ticket_id``      ``TEXT NULL``     — Expo publish_multiple ticket id
- ``expo_receipt_status`` ``TEXT NULL``     — receipts polling forward use(Story 4.4)
- ``expo_receipt_error``  ``TEXT NULL``     — receipts error code

UNIQUE — ``ux_notifications_user_kind_date`` ON ``(user_id, kind, kst_date)``.
인덱스 — ``idx_notifications_user_kst_date`` ON ``(user_id, kst_date)`` — Story 4.4 forward.
CHECK — ``ck_notifications_kind`` IN('unrecorded_meal') — 미래 kind 추가는 drop+recreate.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.db.base import Base

# Story 4.4 forward — ``weekly_report_ready`` / ``account_deletion_grace`` 등 추가 kind 추가
# 시 본 frozenset 갱신 + alembic 신규 revision으로 CHECK drop+recreate.
NOTIFICATION_KINDS: frozenset[str] = frozenset({"unrecorded_meal"})


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    kst_date: Mapped[date] = mapped_column(Date, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    expo_ticket_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    expo_receipt_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    expo_receipt_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # 동일 날 동일 kind 1회 발사 SOT — alembic SQL과 동일 SOT.
        UniqueConstraint("user_id", "kind", "kst_date", name="ux_notifications_user_kind_date"),
        # CHECK — DB-level fail-fast(SQL 우회 차단).
        CheckConstraint("kind IN ('unrecorded_meal')", name="ck_notifications_kind"),
        # Story 4.4 forward — user별 최근 N일 발사 이력 lookup.
        Index("idx_notifications_user_kst_date", "user_id", "kst_date"),
    )
