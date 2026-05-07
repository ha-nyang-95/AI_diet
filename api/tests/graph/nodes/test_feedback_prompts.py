"""Story 4.4 — `app.graph.prompts.feedback` 테스트 (AC8).

`format_macro_goal_summary` 헬퍼 + `build_user_prompt` macro_goal conditional 블록.
"""

from __future__ import annotations

import uuid

from app.domain.macro_goal import MacroGoal
from app.graph.prompts.feedback import (
    build_user_prompt,
    format_macro_goal_summary,
)
from app.graph.state import FitEvaluation, FoodItem, UserProfileSnapshot


def _make_profile(macro_goal: MacroGoal | None = None) -> UserProfileSnapshot:
    return UserProfileSnapshot(
        user_id=uuid.uuid4(),
        health_goal="weight_loss",
        age=30,
        weight_kg=65.0,
        height_cm=170.0,
        activity_level="moderate",
        allergies=[],
        macro_goal=macro_goal,
    )


def _make_fit() -> FitEvaluation:
    return FitEvaluation(
        fit_score=75,
        reasons=["탄수화물 비중 다소 높음"],
        fit_reason="ok",
        fit_label="caution",
    )


def test_format_macro_goal_summary_full() -> None:
    """5 필드 모두 set + ratio sum=100 — 한 줄 요약."""
    summary = format_macro_goal_summary(
        MacroGoal(
            daily_calorie_target_kcal=1800,
            protein_target_g_per_meal=25,
            macro_ratio_carb_pct=50,
            macro_ratio_protein_pct=25,
            macro_ratio_fat_pct=25,
        )
    )
    assert "하루 1800 kcal" in summary
    assert "매끼 단백질 25g" in summary
    assert "탄단지 50/25/25" in summary


def test_format_macro_goal_summary_partial() -> None:
    """일부 필드만 set — 나머지 omit."""
    summary = format_macro_goal_summary(MacroGoal(protein_target_g_per_meal=25))
    assert summary == "매끼 단백질 25g"


def test_format_macro_goal_summary_empty_returns_dash() -> None:
    """모든 필드 None — placeholder ``-``."""
    # MacroGoal()은 빈 인스턴스 가능(MacroGoalPatchRequest가 at-least-one 가드).
    summary = format_macro_goal_summary(MacroGoal())
    assert summary == "-"


def test_build_user_prompt_no_macro_goal_block_when_none() -> None:
    """Story 4.4 AC8 회귀 가드 — macro_goal=None 사용자 prompt에 블록 미포함."""
    profile = _make_profile(macro_goal=None)
    prompt = build_user_prompt(
        fit_evaluation=_make_fit(),
        parsed_items=[FoodItem(name="짜장면", confidence=0.9)],
        user_profile=profile,
        raw_text="짜장면",
    )
    assert "사용자 매크로 목표" not in prompt


def test_build_user_prompt_includes_macro_goal_block_when_set() -> None:
    """Story 4.4 AC8 — macro_goal set 시 prompt에 ``사용자 매크로 목표:`` 블록 포함."""
    profile = _make_profile(macro_goal=MacroGoal(protein_target_g_per_meal=25))
    prompt = build_user_prompt(
        fit_evaluation=_make_fit(),
        parsed_items=[FoodItem(name="짜장면", confidence=0.9)],
        user_profile=profile,
        raw_text="짜장면",
    )
    assert "사용자 매크로 목표:" in prompt
    assert "매끼 단백질 25g" in prompt
    assert "사용자가 설정" in prompt
