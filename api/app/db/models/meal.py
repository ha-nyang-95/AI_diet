"""Meal ORM model — Story 2.1 (식단 텍스트 입력 + CRUD baseline).

Epic 2 단일 출처 ``meals`` 테이블 — 텍스트 전용 7컬럼 (id/user_id/raw_text/ate_at/
created_at/updated_at/deleted_at). ``image_key``(Story 2.2), ``meal_analyses``(Epic 3)
같은 후속 컬럼/테이블은 본 스토리에서 추가하지 않는다 (yagni / dead column 회피).

soft delete 패턴: ``deleted_at`` set 시 read query에서 제외 (`WHERE deleted_at IS
NULL` partial index hit). 30일 grace 후 물리 파기는 Story 5.2 책임 (architecture
line 297 — *FR5 + C6 데이터 보존 정책*).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.db.base import Base


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    ate_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Story 2.4 daily list 쿼리(`WHERE user_id = ? AND deleted_at IS NULL ORDER BY
        # ate_at DESC`) 입력 — partial index로 active row만 색인.
        Index(
            "idx_meals_user_id_ate_at_active",
            "user_id",
            text("ate_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
