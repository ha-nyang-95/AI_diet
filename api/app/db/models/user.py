"""User ORM model — Story 1.2 (Google OAuth + JWT) 도입.

Story 1.5에서 건강 프로필 7컬럼(나이/체중/신장/활동/health_goal/22종 알레르기/
``profile_completed_at``) + Postgres ENUM 2종(``users_activity_level_enum`` /
``users_health_goal_enum``) + DB CHECK 제약 4건 추가.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ARRAY, CheckConstraint, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Boolean, DateTime

from app.db.base import Base
from app.domain.allergens import KOREAN_22_ALLERGENS
from app.domain.health_profile import (
    ACTIVITY_LEVEL_VALUES,
    HEALTH_GOAL_VALUES,
    ActivityLevel,
    HealthGoal,
)

# 22종 도메인 CHECK 제약 SQL — alembic 0005 revision의 SQL과 *동일 SOT*.
# 변경 시 ``app/domain/allergens.py:KOREAN_22_ALLERGENS`` 만 갱신 → 본 식 + alembic
# CHECK 제약이 자동 동기 → 새 alembic revision으로 drop+recreate.
_ALLERGEN_LITERALS = ", ".join(f"'{a}'" for a in KOREAN_22_ALLERGENS)
_ALLERGIES_CHECK_SQL = f"allergies IS NULL OR allergies <@ ARRAY[{_ALLERGEN_LITERALS}]::text[]"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    google_sub: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    picture_url: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'user'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Story 1.5 — 건강 프로필 7컬럼. 모두 nullable — Story 1.2 OAuth 시점에 미입력
    # 상태로 row 생성. ``POST /v1/users/me/profile``에서 입력 완료 시 set.
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activity_level: Mapped[ActivityLevel | None] = mapped_column(
        PG_ENUM(
            *ACTIVITY_LEVEL_VALUES,
            name="users_activity_level_enum",
            create_type=False,
        ),
        nullable=True,
    )
    health_goal: Mapped[HealthGoal | None] = mapped_column(
        PG_ENUM(
            *HEALTH_GOAL_VALUES,
            name="users_health_goal_enum",
            create_type=False,
        ),
        nullable=True,
    )
    # 컬럼 타입 ``text[]`` — DB CHECK 제약(``allergies <@ ARRAY[...]::text[]``)과 동일
    # 배열 타입 매칭 강제(varchar[] vs text[] type mismatch 회피).
    allergies: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    profile_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("role IN ('user','admin')", name="ck_users_role"),
        # Story 1.5 — 건강 프로필 도메인 CHECK 제약 4건.
        CheckConstraint(
            "age IS NULL OR (age >= 1 AND age <= 150)",
            name="ck_users_age",
        ),
        CheckConstraint(
            "weight_kg IS NULL OR (weight_kg >= 1.0 AND weight_kg <= 500.0)",
            name="ck_users_weight_kg",
        ),
        CheckConstraint(
            "height_cm IS NULL OR (height_cm >= 50 AND height_cm <= 300)",
            name="ck_users_height_cm",
        ),
        CheckConstraint(
            _ALLERGIES_CHECK_SQL,
            name="ck_users_allergies_domain",
        ),
        # admin 사용자는 소수 — partial index로 lookup 비용 최소화 (Story 7.1+에서 활용).
        Index(
            "idx_users_role_admin",
            "role",
            postgresql_where=text("role = 'admin'"),
        ),
    )
