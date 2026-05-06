"""Story 4.3 — ``app.domain.health_profile`` 단위 테스트 (AC #9).

``PROTEIN_TARGET_BY_GOAL`` SOT + ``get_protein_target`` 헬퍼 분기.
순수 lookup 모듈 — DB·HTTP 의존성 X.
"""

from __future__ import annotations

import pytest

from app.domain.health_profile import (
    HEALTH_GOAL_VALUES,
    PROTEIN_TARGET_BY_GOAL,
    get_protein_target,
)


def test_protein_target_by_goal_covers_all_health_goals() -> None:
    """4 enum 모두 lookup 커버 — SOT drift 가드."""
    for goal in HEALTH_GOAL_VALUES:
        assert goal in PROTEIN_TARGET_BY_GOAL
    assert len(PROTEIN_TARGET_BY_GOAL) == 4


@pytest.mark.parametrize(
    "goal,expected",
    [
        ("weight_loss", (1.2, 1.6)),
        ("muscle_gain", (1.6, 2.2)),
        ("maintenance", (0.8, 1.2)),
        ("diabetes_management", (0.8, 1.2)),
    ],
)
def test_get_protein_target_each_enum(goal: str, expected: tuple[float, float]) -> None:
    """각 enum → 정의된 (lower, upper) 범위 매핑."""
    assert get_protein_target(goal) == expected  # type: ignore[arg-type]


def test_get_protein_target_none() -> None:
    """``None`` 입력 → ``None`` 반환 (프로필 미완성 graceful)."""
    assert get_protein_target(None) is None


def test_protein_target_lower_lt_upper_invariant() -> None:
    """모든 entry — lower < upper 무결성."""
    for lower, upper in PROTEIN_TARGET_BY_GOAL.values():
        assert lower < upper, f"invalid range: ({lower}, {upper})"


def test_protein_target_mapping_is_immutable() -> None:
    """``MappingProxyType`` — runtime 변경 차단."""
    with pytest.raises(TypeError):
        PROTEIN_TARGET_BY_GOAL["weight_loss"] = (0.0, 0.0)  # type: ignore[index]
