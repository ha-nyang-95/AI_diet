"""건강 프로필 도메인 enum SOT — Story 1.5 (``health_goal`` 4종 / ``activity_level`` 5종).

본 모듈 ``HEALTH_GOAL_VALUES`` / ``ACTIVITY_LEVEL_VALUES`` tuple은 alembic
마이그레이션 ``CREATE TYPE users_*_enum AS ENUM (...)`` 라벨과 *문자열 1:1 동일*.
변경 시 양쪽(본 tuple + alembic revision) 동시 갱신 필수.

응용:
- ``app/db/models/user.py``: ``PG_ENUM(*HEALTH_GOAL_VALUES, name="users_health_goal_enum")``.
- ``app/api/v1/users.py:HealthProfileSubmitRequest``: ``health_goal: HealthGoal``
  Literal 타입 직접 활용 — Pydantic이 enum 검증.
- Story 3.5 ``domain/fit_score.py`` KDRIs AMDR 매크로 룰 lookup table 키.
- Story 3.x ``domain/bmr.py`` Mifflin-St Jeor 계수 lookup(``activity_level`` 5단계).

Literal vs str Enum — Literal 채택. 사유: SQLAlchemy ``Mapped[ActivityLevel | None]`` +
Pydantic 둘 다 Literal 친화적. Story 1.4 ``LegalDocType`` Literal 패턴 정합.
"""

from __future__ import annotations

from typing import Literal

# KDRIs AMDR + 대한당뇨학회 매크로 룰 매핑(research 2.3). Story 3.5 fit_score lookup
# 의 키. snake_case lowercase — Postgres ENUM 라벨 + Pydantic Literal 동일.
HealthGoal = Literal["weight_loss", "muscle_gain", "maintenance", "diabetes_management"]
HEALTH_GOAL_VALUES: tuple[HealthGoal, ...] = (
    "weight_loss",
    "muscle_gain",
    "maintenance",
    "diabetes_management",
)

# Mifflin-St Jeor + Harris-Benedict 활동 계수 표준 5단계 (Story 3.x BMR/TDEE 기반).
ActivityLevel = Literal["sedentary", "light", "moderate", "active", "very_active"]
ACTIVITY_LEVEL_VALUES: tuple[ActivityLevel, ...] = (
    "sedentary",
    "light",
    "moderate",
    "active",
    "very_active",
)
