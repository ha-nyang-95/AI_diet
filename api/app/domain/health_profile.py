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

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal

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


# Story 4.3 — 단백질 일일 권장 범위 (g/kg/day) lookup SOT. 4 health_goal × (lower,
# upper). 출처:
#
# - **weight_loss** (1.2 - 1.6) — 대한비만학회 2024 비만치료지침 §단백질
#   *"감량 중 근손실 방지 위해 1.2-1.6 g/kg/day"*. KDRIs 2020 일반 성인 EAR
#   0.91 g/kg + 25-50% 상향분.
# - **muscle_gain** (1.6 - 2.2) — 국제스포츠영양학회(ISSN) 2017 position stand.
#   대한스포츠의학회 가이드 정합.
# - **maintenance** (0.8 - 1.2) — KDRIs 2020 EAR 0.91 / RDA 1.0 기준 + 보수적
#   상한 1.2(고령자 sarcopenia 보호 — 대한노인병학회).
# - **diabetes_management** (0.8 - 1.2) — 대한당뇨학회 2023 진료지침 §단백질
#   *"신증 미발현 환자 0.8-1.2 g/kg/day"*. 신증 발현 환자(0.6-0.8)는 별도 의료진
#   상담 — 본 SOT는 *일반 권장 baseline*만 노출(disclaimer FR7 정합).
#
# ``MappingProxyType`` — runtime 변경 차단. 신규 enum 추가 시 본 dict 갱신 강제
# (import-time SOT drift 가드 — 아래 ``if`` 블록 참조).
PROTEIN_TARGET_BY_GOAL: Final[Mapping[HealthGoal, tuple[float, float]]] = MappingProxyType(
    {
        "weight_loss": (1.2, 1.6),
        "muscle_gain": (1.6, 2.2),
        "maintenance": (0.8, 1.2),
        "diabetes_management": (0.8, 1.2),
    }
)

# SOT drift fail-fast — 미래 ``HEALTH_GOAL_VALUES`` 신규 enum 추가 시 본 dict 매핑
# 누락이면 import 시점 즉시 실패. ``assert``는 ``python -O``에서 strip되므로 explicit
# ``raise`` (Story 4.3 CR P7/P18 정합).
if set(PROTEIN_TARGET_BY_GOAL.keys()) != set(HEALTH_GOAL_VALUES):
    raise RuntimeError(
        "PROTEIN_TARGET_BY_GOAL keys mismatch with HEALTH_GOAL_VALUES — "
        f"goals={set(HEALTH_GOAL_VALUES)} vs lookup={set(PROTEIN_TARGET_BY_GOAL.keys())}"
    )


def get_protein_target(health_goal: HealthGoal | None) -> tuple[float, float] | None:
    """``health_goal`` → ``(lower, upper)`` g/kg/day 권장 범위 또는 ``None``.

    Story 4.3 ``ProteinChart``의 ``ReferenceArea`` 입력 SOT. ``health_goal`` 미설정
    (사용자 프로필 미완성)이면 ``None`` 반환 — 차트는 권장 영역 미렌더 + 캡션 *"권장
    범위는 프로필 + 목표 설정 후 노출"*.

    Story 4.3 CR P18 — ``.get()`` graceful: import-time SOT 가드가 정합성 보장하지만
    legacy DB 데이터에서 unknown enum이 들어오면 endpoint 500 회피(``None`` 반환 →
    차트 빈 영역).
    """
    if health_goal is None:
        return None
    return PROTEIN_TARGET_BY_GOAL.get(health_goal)
