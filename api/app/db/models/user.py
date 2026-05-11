"""User ORM model — Story 1.2 (Google OAuth + JWT) 도입.

Story 1.5에서 건강 프로필 7컬럼(나이/체중/신장/활동/health_goal/22종 알레르기/
``profile_completed_at``) + Postgres ENUM 2종(``users_activity_level_enum`` /
``users_health_goal_enum``) + DB CHECK 제약 4건 추가.

Story 4.1에서 알림 설정 4컬럼(``notifications_enabled`` / ``notification_time`` /
``notification_timezone`` / ``expo_push_token``) + CHECK 제약 1건
(``ck_users_notification_time_kst_format``) 추가. partial UNIQUE index
``ux_users_expo_push_token_active``는 alembic 0013에서 생성 — ORM ``Index`` 미선언
(부분 index는 ORM 레벨에서 metadata 동기화 X — alembic SOT만 유지).

Story 5.1에서 ``profile_updated_at`` 컬럼 추가(0016 마이그레이션). 3 timestamp
컬럼 의미 분리(SOT):
- ``profile_completed_at`` — *최초 온보딩 완료 시점*. POST /me/profile 시 set,
  PATCH /me/profile 시 미터치(invariant — *최초 시점* 보존).
- ``profile_updated_at`` — *프로필을 명시적으로 마지막 수정한 시점*. PATCH /me/profile
  시 set. 본 컬럼은 ``POST /me/profile`` 흐름으로는 set X(의미 분리).
- ``updated_at`` — *행 단위 마지막 변경 시점*. ``onupdate=now()``로 모든 컬럼
  변경 시 자동 bump (macro_goal/notification/profile 등 모두 포함).

Story 5.2에서 ``deletion_reason`` Text nullable 컬럼 + ``idx_users_deleted_at_pending_purge``
partial index 추가(0017 마이그레이션). 본 컬럼은 사용자 탈퇴 시점에 ``DELETE
/v1/users/me`` 엔드포인트가 set(선택, 빈/미송신 시 NULL), 30일 grace 후 cascade
hard delete와 함께 사라짐. partial index는 ``soft_delete_purge`` cron worker의
eligible SELECT(``WHERE deleted_at IS NOT NULL AND deleted_at < cutoff``)를 위해
존재 — 활성 사용자(``deleted_at IS NULL``) 색인 미진입으로 hot path INSERT/UPDATE
비용 0.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import ARRAY, CheckConstraint, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Boolean, DateTime, Time

from app.db.base import Base
from app.domain.allergens import KOREAN_22_ALLERGENS
from app.domain.health_profile import (
    ACTIVITY_LEVEL_VALUES,
    HEALTH_GOAL_VALUES,
    ActivityLevel,
    HealthGoal,
)
from app.domain.macro_goal import MACRO_GOAL_CHECK_SQL

# 22종 도메인 CHECK 제약 SQL — alembic 0005 revision의 SQL과 *동일 SOT*.
# 변경 시 ``app/domain/allergens.py:KOREAN_22_ALLERGENS`` 만 갱신 → 본 식 + alembic
# CHECK 제약이 자동 동기 → 새 alembic revision으로 drop+recreate.
#
# Single-quote escape 적용 (defense-in-depth) — 현 22종은 ``'`` 미포함이나, 미래
# SOT에 apostrophe 라벨이 들어가도 SQL CHECK 깨지지 않도록 ``' → ''`` 변환.


def _quote_label(value: str) -> str:
    if "\x00" in value or "\\" in value:
        raise ValueError(
            f"unsafe character in allergen literal: {value!r} "
            "(NUL or backslash not allowed in SQL CHECK literal)"
        )
    return "'" + value.replace("'", "''") + "'"


_ALLERGEN_LITERALS = ", ".join(_quote_label(a) for a in KOREAN_22_ALLERGENS)
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
    # Story 5.2 — 사용자가 탈퇴 시 선택한 자유 텍스트 사유(0017 마이그레이션). ``DELETE
    # /v1/users/me`` 엔드포인트가 set, 미송신/빈 string 시 NULL. 30일 grace 후 cascade
    # hard delete와 함께 사라짐. enum 미사용(MVP — 카테고리 분류는 polish 스토리 forward).
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # Story 5.1 — 프로필을 *명시적으로* 마지막 수정한 시점(0016 마이그레이션).
    # ``PATCH /v1/users/me/profile`` 첫 호출 시점에 set — 그전까지는 NULL. POST 흐름
    # 으로는 set X(의미 분리, docstring SOT). 회귀 0건: 기존 사용자 row는 NULL default.
    profile_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Story 4.1 — 알림 설정 4 컬럼. alembic 0013과 동일 SOT(server_default + nullable).
    # 변경 시 새 alembic revision 추가로 drop+recreate (Story 1.5 R8 SOP 정합).
    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # ``timezone=False`` — TZ-naive ``datetime.time``. TZ는 ``notification_timezone`` 별 SOT.
    notification_time: Mapped[time] = mapped_column(
        Time(timezone=False),
        nullable=False,
        server_default=text("'20:00:00'"),
    )
    notification_timezone: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'Asia/Seoul'")
    )
    # ``ExponentPushToken[xxx]`` 형식 — 라우터 Pydantic field_validator가 검증. partial
    # UNIQUE index ``ux_users_expo_push_token_active``(alembic 0013 SOT)가 동일 device의
    # 사용자 swap 회귀 차단.
    expo_push_token: Mapped[str | None] = mapped_column(String, nullable=True)

    # Story 4.4 — 사용자 매크로 목표 JSONB 컬럼(0015 마이그레이션). nullable — 기존
    # 사용자는 모두 NULL(default). DB CHECK ``ck_users_macro_goal_shape``가 shape 가드,
    # Pydantic ``MacroGoal`` 모델이 ratio sum 가드(double gate). 변경 시
    # ``app/domain/macro_goal.py:MACRO_GOAL_CHECK_SQL`` SOT만 갱신 → 새 alembic
    # revision drop+recreate(Story 1.5 R8 SOP 정합).
    macro_goal: Mapped[dict[str, int] | None] = mapped_column(JSONB, nullable=True)

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
        # Story 4.1 — 분 단위 정렬 강제(초·분초 자유 입력 차단, APScheduler 일별 잡 안정성).
        # alembic 0013 SQL과 동일 SOT (regex가 SQLAlchemy text parser와 충돌 — EXTRACT
        # 기반 표현으로 의미 동등 변환. 0013 docstring deviation 메모 참조).
        CheckConstraint(
            "notification_time IS NULL OR EXTRACT(SECOND FROM notification_time) = 0",
            name="ck_users_notification_time_kst_format",
        ),
        # Story 4.4 — macro_goal JSONB shape 가드(0015 alembic SQL과 *동일 SOT*).
        # ratio all-or-none + sum=100은 Pydantic 1차 가드만(SQL JSONB 다중 키 expression
        # 복잡성 회피).
        CheckConstraint(MACRO_GOAL_CHECK_SQL, name="ck_users_macro_goal_shape"),
        # admin 사용자는 소수 — partial index로 lookup 비용 최소화 (Story 7.1+에서 활용).
        Index(
            "idx_users_role_admin",
            "role",
            postgresql_where=text("role = 'admin'"),
        ),
        # Story 5.2 — soft-deleted 사용자만 색인. ``soft_delete_purge`` cron worker의
        # eligible SELECT(``WHERE deleted_at IS NOT NULL AND deleted_at < cutoff``) hit.
        # 활성 사용자(``deleted_at IS NULL``) hot path INSERT/UPDATE 비용 0.
        Index(
            "idx_users_deleted_at_pending_purge",
            "deleted_at",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
        # Story 7.2 — admin 사용자 검색 ``GET /v1/admin/users?q=...`` email ILIKE prefix
        # SOT. ``func.lower(email) LIKE 'lower_q%'`` 매칭 시 본 expression index hit
        # (NFR-P9 1만 건 ≤ 1초). soft-deleted 포함 색인(거버넌스 가시화). alembic 0021
        # SOT 동기 — Story 1.5 R8 SOP 정합.
        Index(
            "idx_users_email_lower",
            func.lower(text("email")),
        ),
    )
