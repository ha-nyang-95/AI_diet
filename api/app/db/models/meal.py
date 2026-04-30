"""Meal ORM model — Story 2.1 (식단 텍스트 입력) + 2.2 (사진) + 2.3 (OCR Vision).

Epic 2 단일 출처 ``meals`` 테이블 — 9컬럼 (id/user_id/raw_text/ate_at/created_at/
updated_at/deleted_at + image_key + parsed_items). ``meal_analyses``(Epic 3) 같은
후속 테이블은 본 스토리에서 추가하지 않는다 (yagni / dead column 회피).

Story 2.2 — ``image_key`` TEXT NULL (R2 object key). Story 2.3 — ``parsed_items``
JSONB NULL — Vision OCR 추출 결과(`[{"name":"짜장면","quantity":"1인분","confidence":0.92}]`)
영속화 단일 지점. NOT NULL 부여 X — 텍스트-only 또는 parse 미호출 사진-only 호환.
``raw_text`` NOT NULL invariant 유지 — 사진-only 입력 시 서버가 ``"(사진 입력)"`` placeholder
fallback / parse 흐름에서는 ``_format_parsed_items_to_raw_text`` 자동 변환으로 placeholder
collision(DF2) 자연 해소.

soft delete 패턴: ``deleted_at`` set 시 read query에서 제외 (`WHERE deleted_at IS
NULL` partial index hit). 30일 grace 후 물리 파기는 Story 5.2 책임 (architecture
line 297 — *FR5 + C6 데이터 보존 정책*).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    # Story 2.2 — R2 object key (`meals/{user_id}/{uuid}.{ext}`). nullable — 텍스트-only
    # 식단 호환 + 사진-only 입력은 ``raw_text`` placeholder fallback로 NOT NULL 유지.
    image_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Story 2.3 — Vision OCR 추출 결과(`[{"name","quantity","confidence"}, ...]`) 영속화.
    # nullable — 텍스트-only / 사진+텍스트(parse 미호출) 호환. 추가 인덱스 X — meal_id lookup
    # 시점에만 fetch (jsonb path 인덱스는 Story 8 perf hardening).
    parsed_items: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

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
