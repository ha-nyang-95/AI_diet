"""0005_users_health_profile — Story 1.5.

``users`` 테이블에 건강 프로필 7컬럼 + Postgres ENUM 2종 + DB CHECK 제약 4건 추가.

7 컬럼 (모두 nullable — Story 1.2 OAuth 시점 미입력 상태로 row 생성, Story 1.5
``POST /v1/users/me/profile``에서 입력 완료 시 set):
- ``age``                   ``integer``           CHECK ``1 <= age <= 150``
- ``weight_kg``             ``numeric(5,1)``       CHECK ``1.0 <= weight_kg <= 500.0``
- ``height_cm``             ``integer``           CHECK ``50 <= height_cm <= 300``
- ``activity_level``        ``users_activity_level_enum``
- ``health_goal``           ``users_health_goal_enum``
- ``allergies``             ``text[]``             CHECK ``allergies <@ ARRAY[22종]``
- ``profile_completed_at``  ``timestamptz``

Postgres ENUM 2종 (architecture line 396 naming ``<table>_<col>_enum`` 정합):
- ``users_activity_level_enum`` AS ENUM (5종)
- ``users_health_goal_enum``    AS ENUM (4종)

22종 알레르기 SOT — ``app.domain.allergens.KOREAN_22_ALLERGENS`` import 후 SQL 인라인.
변경 시 새 alembic revision으로 ``ck_users_allergies_domain`` drop+recreate (R8 SOP).

downgrade 순서 엄격 보존: CHECK 제약 drop → 컬럼 drop 7개 → ENUM TYPE drop 2개
(ENUM TYPE drop 시 dependent column이 없는 상태여야 — column drop 선행 필수).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.domain.allergens import KOREAN_22_ALLERGENS
from app.domain.health_profile import ACTIVITY_LEVEL_VALUES, HEALTH_GOAL_VALUES

revision: str = "0005_users_health_profile"
down_revision: str | None = "0004_consents_automated_decision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ACTIVITY_LEVEL_ENUM = "users_activity_level_enum"
_HEALTH_GOAL_ENUM = "users_health_goal_enum"


def _enum_literals(values: tuple[str, ...]) -> str:
    """ENUM 라벨을 SQL CREATE TYPE 리터럴로 변환 — single-quote escape 적용."""
    return ", ".join(_sql_quote(v) for v in values)


def _sql_quote(value: str) -> str:
    """SQL single-quote escape — ``' → ''`` (Postgres 표준 + ANSI SQL).

    추가로 NUL byte / backslash 등 위험 문자도 명시 거부 — module-load 시 fail-fast로
    SOT(``KOREAN_22_ALLERGENS``)에 위험 라벨 추가 시 즉시 마이그레이션 실패.
    """
    if "\x00" in value or "\\" in value:
        raise ValueError(
            f"unsafe character in allergen literal: {value!r} "
            "(NUL or backslash not allowed in SQL CHECK literal)"
        )
    return "'" + value.replace("'", "''") + "'"


def _allergens_array_sql() -> str:
    """22종 SOT를 SQL 리터럴 배열로 인라인 — single-quote escape 적용.

    현 22종은 한국어 라벨로 ``'`` 미포함이나, 미래 SOT 갱신 시 apostrophe 라벨이
    들어가도 SQL 깨지지 않도록 defense-in-depth escape. ``_sql_quote``가 위험 문자
    감지 시 ``ValueError`` raise → 마이그레이션 실패로 fail-fast.
    """
    literals = ", ".join(_sql_quote(a) for a in KOREAN_22_ALLERGENS)
    return f"ARRAY[{literals}]::text[]"


def upgrade() -> None:
    # 1) Postgres ENUM 타입 2종 CREATE (컬럼 추가 *전*에 타입 존재 보장).
    op.execute(
        f"CREATE TYPE {_ACTIVITY_LEVEL_ENUM} AS ENUM ({_enum_literals(ACTIVITY_LEVEL_VALUES)})"
    )
    op.execute(f"CREATE TYPE {_HEALTH_GOAL_ENUM} AS ENUM ({_enum_literals(HEALTH_GOAL_VALUES)})")

    # 2) 컬럼 7개 ADD — 모두 nullable.
    op.add_column("users", sa.Column("age", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("weight_kg", sa.Numeric(5, 1), nullable=True))
    op.add_column("users", sa.Column("height_cm", sa.Integer(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "activity_level",
            sa.dialects.postgresql.ENUM(
                *ACTIVITY_LEVEL_VALUES,
                name=_ACTIVITY_LEVEL_ENUM,
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "health_goal",
            sa.dialects.postgresql.ENUM(
                *HEALTH_GOAL_VALUES,
                name=_HEALTH_GOAL_ENUM,
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column("allergies", sa.dialects.postgresql.ARRAY(sa.Text()), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("profile_completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 3) CHECK 제약 4건.
    op.create_check_constraint(
        "ck_users_age",
        "users",
        "age IS NULL OR (age >= 1 AND age <= 150)",
    )
    op.create_check_constraint(
        "ck_users_weight_kg",
        "users",
        "weight_kg IS NULL OR (weight_kg >= 1.0 AND weight_kg <= 500.0)",
    )
    op.create_check_constraint(
        "ck_users_height_cm",
        "users",
        "height_cm IS NULL OR (height_cm >= 50 AND height_cm <= 300)",
    )
    op.create_check_constraint(
        "ck_users_allergies_domain",
        "users",
        f"allergies IS NULL OR allergies <@ {_allergens_array_sql()}",
    )


def downgrade() -> None:
    # CHECK 제약 drop 먼저(컬럼 drop 시 dependent constraint 자동 cascade되지만
    # 명시 drop으로 가독성 + idempotency).
    op.drop_constraint("ck_users_allergies_domain", "users", type_="check")
    op.drop_constraint("ck_users_height_cm", "users", type_="check")
    op.drop_constraint("ck_users_weight_kg", "users", type_="check")
    op.drop_constraint("ck_users_age", "users", type_="check")

    # 컬럼 drop 7개 — ENUM 타입 의존 컬럼(activity_level / health_goal)을 먼저 drop.
    op.drop_column("users", "profile_completed_at")
    op.drop_column("users", "allergies")
    op.drop_column("users", "health_goal")
    op.drop_column("users", "activity_level")
    op.drop_column("users", "height_cm")
    op.drop_column("users", "weight_kg")
    op.drop_column("users", "age")

    # ENUM 타입 drop 2종 — dependent column 모두 drop된 상태.
    op.execute(f"DROP TYPE {_HEALTH_GOAL_ENUM}")
    op.execute(f"DROP TYPE {_ACTIVITY_LEVEL_ENUM}")
