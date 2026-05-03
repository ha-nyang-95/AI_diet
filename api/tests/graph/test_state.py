"""Story 3.3 — `app/graph/state.py` Pydantic IO + TypedDict 검증 (AC1)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.graph.state import (
    Citation,
    ClarificationOption,
    EvaluationDecision,
    FeedbackOutput,
    FitEvaluation,
    FoodItem,
    MealAnalysisState,
    NodeError,
    ParseMealOutput,
    RetrievalResult,
    RetrievedFood,
    UserProfileSnapshot,
)


def test_food_item_confidence_bounds() -> None:
    FoodItem(name="짜장면", quantity="1인분", confidence=0.0)
    FoodItem(name="짜장면", quantity="1인분", confidence=1.0)
    with pytest.raises(ValidationError):
        FoodItem(name="짜장면", confidence=-0.1)
    with pytest.raises(ValidationError):
        FoodItem(name="짜장면", confidence=1.1)


def test_food_item_quantity_optional() -> None:
    item = FoodItem(name="짜장면", confidence=0.5)
    assert item.quantity is None


def test_parse_meal_output_empty_list_allowed() -> None:
    out = ParseMealOutput(parsed_items=[])
    assert out.parsed_items == []


def test_retrieved_food_score_bounds() -> None:
    RetrievedFood(name="짜장면", food_id=None, score=0.0, nutrition={"energy_kcal": 0})
    RetrievedFood(name="짜장면", food_id=None, score=1.0, nutrition={"energy_kcal": 0})
    with pytest.raises(ValidationError):
        RetrievedFood(name="짜장면", food_id=None, score=1.5, nutrition={})


def test_retrieved_food_food_id_optional() -> None:
    rf = RetrievedFood(name="짜장면", food_id=None, score=0.7, nutrition={"energy_kcal": 0})
    assert rf.food_id is None
    fid = uuid.uuid4()
    rf2 = RetrievedFood(name="짜장면", food_id=fid, score=0.7, nutrition={})
    assert rf2.food_id == fid


def test_retrieval_result_confidence_bounds() -> None:
    rr = RetrievalResult(retrieved_foods=[], retrieval_confidence=0.0)
    assert rr.retrieved_foods == []
    with pytest.raises(ValidationError):
        RetrievalResult(retrieved_foods=[], retrieval_confidence=1.5)


def test_evaluation_decision_route_literal() -> None:
    """Story 3.4 AC8 — `clarify` 분기 추가로 3-way Literal."""
    EvaluationDecision(route="rewrite", reason="low_confidence_0.30")
    EvaluationDecision(route="continue", reason="confidence_ok")
    EvaluationDecision(route="clarify", reason="rewrite_limit_reached_low_confidence")
    with pytest.raises(ValidationError):
        EvaluationDecision(route="other", reason="x")  # type: ignore[arg-type]


def test_clarification_option_label_value_constraints() -> None:
    """Story 3.4 AC1 — `ClarificationOption` Pydantic 검증."""
    opt = ClarificationOption(label="연어 포케", value="연어 포케 1인분")
    assert opt.label == "연어 포케"
    assert opt.value == "연어 포케 1인분"

    # 빈 label / value 거부
    with pytest.raises(ValidationError):
        ClarificationOption(label="", value="x")
    with pytest.raises(ValidationError):
        ClarificationOption(label="x", value="")

    # max_length 초과 거부
    with pytest.raises(ValidationError):
        ClarificationOption(label="가" * 51, value="x")
    with pytest.raises(ValidationError):
        ClarificationOption(label="x", value="가" * 81)


def test_clarification_option_extra_forbid() -> None:
    """Story 3.4 AC1 — `extra="forbid"` 정합 (drift 회귀 차단)."""
    with pytest.raises(ValidationError):
        ClarificationOption(  # type: ignore[call-arg]
            label="연어 포케",
            value="연어 포케 1인분",
            extra_field="rogue",
        )


def test_user_profile_snapshot_enums() -> None:
    snap = UserProfileSnapshot(
        user_id=uuid.uuid4(),
        health_goal="weight_loss",
        age=30,
        weight_kg=70.0,
        height_cm=170.0,
        activity_level="moderate",
        allergies=[],
    )
    assert snap.health_goal == "weight_loss"
    with pytest.raises(ValidationError):
        UserProfileSnapshot(
            user_id=uuid.uuid4(),
            health_goal="invalid",  # type: ignore[arg-type]
            age=30,
            weight_kg=70.0,
            height_cm=170.0,
            activity_level="moderate",
            allergies=[],
        )
    with pytest.raises(ValidationError):
        UserProfileSnapshot(
            user_id=uuid.uuid4(),
            health_goal="weight_loss",
            age=30,
            weight_kg=70.0,
            height_cm=170.0,
            activity_level="invalid",  # type: ignore[arg-type]
            allergies=[],
        )


def test_fit_evaluation_score_bounds() -> None:
    FitEvaluation(fit_score=0, reasons=[])
    FitEvaluation(fit_score=100, reasons=["대체로 적합"])
    with pytest.raises(ValidationError):
        FitEvaluation(fit_score=-1, reasons=[])
    with pytest.raises(ValidationError):
        FitEvaluation(fit_score=101, reasons=[])


def test_feedback_output_default_used_llm() -> None:
    out = FeedbackOutput(text="(분석 준비 중)", citations=[])
    assert out.used_llm == "stub"


def test_feedback_output_used_llm_literal() -> None:
    FeedbackOutput(text="...", citations=[], used_llm="gpt-4o-mini")
    FeedbackOutput(text="...", citations=[], used_llm="claude")
    with pytest.raises(ValidationError):
        FeedbackOutput(text="...", citations=[], used_llm="other")  # type: ignore[arg-type]


def test_citation_year_optional() -> None:
    c = Citation(source="식약처", doc_title="2020 한국인 영양소 섭취기준", published_year=2020)
    assert c.published_year == 2020
    c2 = Citation(source="WHO", doc_title="Nutrition Guideline", published_year=None)
    assert c2.published_year is None


def test_citation_empty_list_allowed_in_feedback_output() -> None:
    """AC1 line 46 — `Citation` 빈 리스트 허용 (stub 정합)."""
    out = FeedbackOutput(text="(분석 준비 중)", citations=[], used_llm="stub")
    assert out.citations == []
    assert isinstance(out.citations, list)


def test_node_error_fields() -> None:
    err = NodeError(
        node_name="parse_meal",
        error_class="ValidationError",
        message="...",
        attempts=2,
    )
    assert err.attempts == 2


def test_meal_analysis_state_partial_dict_total_false() -> None:
    """`MealAnalysisState`는 TypedDict total=False — 부분 dict 정합."""
    partial: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "짜장면 1인분",
        "rewrite_attempts": 0,
        "node_errors": [],
        "clarification_options": [],
    }
    assert partial["raw_text"] == "짜장면 1인분"
    assert partial["clarification_options"] == []


def test_meal_analysis_state_with_clarification_options() -> None:
    """Story 3.4 AC1 — `clarification_options` 1+개 필드 정합."""
    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "포케볼",
        "rewrite_attempts": 1,
        "node_errors": [],
        "needs_clarification": True,
        "clarification_options": [
            ClarificationOption(label="연어 포케", value="연어 포케 1인분"),
            ClarificationOption(label="참치 포케", value="참치 포케 1인분"),
        ],
    }
    assert state["needs_clarification"] is True
    assert len(state["clarification_options"]) == 2
    assert state["clarification_options"][0].label == "연어 포케"


def test_meal_analysis_state_full_shape() -> None:
    food_id = uuid.uuid4()
    user_id = uuid.uuid4()
    meal_id = uuid.uuid4()
    state: MealAnalysisState = {
        "meal_id": meal_id,
        "user_id": user_id,
        "raw_text": "짜장면",
        "parsed_items": [FoodItem(name="짜장면", quantity="1인분", confidence=0.9)],
        "retrieval": RetrievalResult(
            retrieved_foods=[
                RetrievedFood(
                    name="짜장면",
                    food_id=food_id,
                    score=0.7,
                    nutrition={"energy_kcal": 0},
                ),
            ],
            retrieval_confidence=0.7,
        ),
        "rewrite_attempts": 0,
        "rewritten_query": None,
        "user_profile": UserProfileSnapshot(
            user_id=user_id,
            health_goal="weight_loss",
            age=30,
            weight_kg=70.0,
            height_cm=170.0,
            activity_level="moderate",
            allergies=[],
        ),
        "fit_evaluation": FitEvaluation(fit_score=50, reasons=[]),
        "feedback": FeedbackOutput(text="", citations=[], used_llm="stub"),
        "node_errors": [],
        "needs_clarification": False,
    }
    assert state["meal_id"] == meal_id
    assert state["fit_evaluation"].fit_score == 50
