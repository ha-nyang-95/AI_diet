"""Consent ORM model — Story 1.3.

1 user 1 row (UNIQUE FK ON DELETE CASCADE). 컬럼 per 동의 타입 채택 — Story 1.4가
같은 row에 자동화 의사결정 동의 컬럼을 0004 마이그레이션으로 추가한다(scope 분리).

`*_at` 컬럼이 NOT NULL이고 `*_version`이 ``CURRENT_VERSIONS``와 모두 일치할 때만
`require_basic_consents` Depends가 통과시킨다(Story 1.5+에서 라우터별 wire).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.db.base import Base


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    disclaimer_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terms_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    privacy_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sensitive_personal_info_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    disclaimer_version: Mapped[str | None] = mapped_column(String, nullable=True)
    terms_version: Mapped[str | None] = mapped_column(String, nullable=True)
    privacy_version: Mapped[str | None] = mapped_column(String, nullable=True)
    sensitive_personal_info_version: Mapped[str | None] = mapped_column(String, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
