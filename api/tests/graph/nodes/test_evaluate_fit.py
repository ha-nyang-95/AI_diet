"""Story 3.5 — `evaluate_fit` 노드 단위 테스트 (AC7).

결정성 알고리즘 + 알레르기 단락 + incomplete_data graceful + checkpointer round-trip
안전(model_dump) + NFR-S5 마스킹 검증.
"""

from __future__ import annotations

import uuid

import structlog.testing as structlog_testing

from app.graph.deps import NodeDeps
from app.graph.nodes import evaluate_fit
from app.graph.state import (
    FoodItem,
    MealAnalysisState,
    RetrievalResult,
    RetrievedFood,
    UserProfileSnapshot,
)


def _profile(*, allergies: list[str] | None = None) -> UserProfileSnapshot:
    return UserProfileSnapshot(
        user_id=uuid.uuid4(),
        health_goal="weight_loss",
        age=30,
        weight_kg=60.0,
        height_cm=165.0,
        activity_level="light",
        allergies=allergies or [],
    )


def _retrieval(foods: list[RetrievedFood], conf: float = 0.85) -> RetrievalResult:
    return RetrievalResult(retrieved_foods=foods, retrieval_confidence=conf)


def _state(
    *,
    profile: UserProfileSnapshot | None = None,
    parsed_items: list[FoodItem] | None = None,
    retrieval: RetrievalResult | None = None,
) -> MealAnalysisState:
    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "짜장면",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    if profile is not None:
        state["user_profile"] = profile
    if parsed_items is not None:
        state["parsed_items"] = parsed_items
    if retrieval is not None:
        state["retrieval"] = retrieval
    return state


async def test_evaluate_fit_happy_path_returns_ok_with_band(fake_deps: NodeDeps) -> None:
    """*지수* persona + 짜장면 → fit_reason=ok + fit_label band."""
    profile = _profile()
    items = [FoodItem(name="짜장면", quantity="1인분", confidence=0.9)]
    foods = [
        RetrievedFood(
            name="짜장면",
            food_id=None,
            score=0.9,
            nutrition={
                "energy_kcal": 600,
                "carbohydrate_g": 85,
                "protein_g": 15,
                "fat_g": 20,
                "fiber_g": 3,
            },
        )
    ]
    state = _state(profile=profile, parsed_items=items, retrieval=_retrieval(foods))
    out = await evaluate_fit(state, deps=fake_deps)
    fe = out["fit_evaluation"]
    assert fe["fit_reason"] == "ok"
    assert fe["fit_label"] in {"good", "caution", "needs_adjust"}
    assert 0 <= fe["fit_score"] <= 100
    assert fe["components"]["allergen"] == 20  # 위반 없음 → 만점


async def test_evaluate_fit_missing_user_profile_returns_incomplete_data(
    fake_deps: NodeDeps,
) -> None:
    state = _state(parsed_items=[FoodItem(name="짜장면", confidence=0.9)])
    out = await evaluate_fit(state, deps=fake_deps)
    fe = out["fit_evaluation"]
    assert fe["fit_score"] == 0
    assert fe["fit_reason"] == "incomplete_data"
    assert fe["fit_label"] == "needs_adjust"


async def test_evaluate_fit_missing_parsed_items_returns_incomplete_data(
    fake_deps: NodeDeps,
) -> None:
    state = _state(profile=_profile(), parsed_items=[])
    out = await evaluate_fit(state, deps=fake_deps)
    fe = out["fit_evaluation"]
    assert fe["fit_score"] == 0
    assert fe["fit_reason"] == "incomplete_data"


async def test_evaluate_fit_allergen_short_circuit(fake_deps: NodeDeps) -> None:
    """user 우유 알레르기 + 우유라떼 → fit_score=0 + reason='allergen_violation'."""
    profile = _profile(allergies=["우유"])
    items = [FoodItem(name="우유라떼", confidence=0.9)]
    state = _state(profile=profile, parsed_items=items)
    out = await evaluate_fit(state, deps=fake_deps)
    fe = out["fit_evaluation"]
    assert fe["fit_score"] == 0
    assert fe["fit_reason"] == "allergen_violation"
    assert fe["fit_label"] == "allergen_violation"
    assert fe["reasons"][0].startswith("알레르기 위반:")
    assert "우유" in fe["reasons"][0]


async def test_evaluate_fit_low_coverage_ratio_in_reasons(fake_deps: NodeDeps) -> None:
    """parsed_items 일부만 매칭 → coverage_ratio < 0.5 + reasons '매칭 신뢰도 낮음'."""
    profile = _profile()
    items = [
        FoodItem(name="짜장면", confidence=0.9),
        FoodItem(name="알수없는음식1", confidence=0.4),
        FoodItem(name="알수없는음식2", confidence=0.4),
    ]
    foods = [
        RetrievedFood(
            name="짜장면",
            food_id=None,
            score=0.9,
            nutrition={"energy_kcal": 600, "carbohydrate_g": 85, "protein_g": 15, "fat_g": 20},
        )
    ]
    state = _state(profile=profile, parsed_items=items, retrieval=_retrieval(foods))
    out = await evaluate_fit(state, deps=fake_deps)
    fe = out["fit_evaluation"]
    assert fe["components"]["coverage_ratio"] < 0.5
    assert any("매칭 신뢰도 낮음" in r for r in fe["reasons"])


async def test_evaluate_fit_returns_dict_for_checkpointer_round_trip(
    fake_deps: NodeDeps,
) -> None:
    """반환은 ``model_dump()`` dict — checkpointer 직렬화 호환."""
    profile = _profile()
    items = [FoodItem(name="짜장면", confidence=0.9)]
    state = _state(profile=profile, parsed_items=items)
    out = await evaluate_fit(state, deps=fake_deps)
    fe = out["fit_evaluation"]
    assert isinstance(fe, dict)
    assert "fit_score" in fe
    assert "components" in fe
    assert isinstance(fe["components"], dict)


async def test_evaluate_fit_band_label_consistent_with_score(fake_deps: NodeDeps) -> None:
    """fit_label band가 fit_score와 정합."""
    profile = _profile()
    items = [FoodItem(name="짜장면", confidence=0.9)]
    foods = [
        RetrievedFood(
            name="짜장면",
            food_id=None,
            score=0.9,
            nutrition={"energy_kcal": 600, "carbohydrate_g": 85, "protein_g": 15, "fat_g": 20},
        )
    ]
    state = _state(profile=profile, parsed_items=items, retrieval=_retrieval(foods))
    out = await evaluate_fit(state, deps=fake_deps)
    fe = out["fit_evaluation"]
    score = fe["fit_score"]
    label = fe["fit_label"]
    if score >= 80:
        assert label == "good"
    elif score >= 60:
        assert label == "caution"
    else:
        assert label == "needs_adjust"


async def test_evaluate_fit_dict_state_for_checkpointer_replay(fake_deps: NodeDeps) -> None:
    """state[user_profile]이 dict로 역직렬화돼도 정상 동작 (round-trip 안전)."""
    profile_dict = {
        "user_id": str(uuid.uuid4()),
        "health_goal": "maintenance",
        "age": 35,
        "weight_kg": 70.0,
        "height_cm": 170.0,
        "activity_level": "moderate",
        "allergies": [],
    }
    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "짜장면",
        "rewrite_attempts": 0,
        "node_errors": [],
        "user_profile": profile_dict,  # type: ignore[typeddict-item]
        "parsed_items": [FoodItem(name="짜장면", confidence=0.9)],
    }
    out = await evaluate_fit(state, deps=fake_deps)
    fe = out["fit_evaluation"]
    assert fe["fit_reason"] == "ok"
    assert 0 <= fe["fit_score"] <= 100


def _profile_for_masking(*, allergies: list[str] | None = None) -> UserProfileSnapshot:
    """CR M-1: masking test 전용 — 비ambiguous 값(unique substrings)."""
    return UserProfileSnapshot(
        user_id=uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-000000000001"),
        health_goal="weight_loss",
        age=47,
        weight_kg=63.7,
        height_cm=171.5,
        activity_level="light",
        allergies=allergies or [],
    )


# CR M-1: 마스킹되어야 하는 *키* 집합 — log entry dict에 *절대* 등장 금지.
_FORBIDDEN_LOG_KEYS: frozenset[str] = frozenset(
    {
        "weight_kg",
        "height_cm",
        "age",
        "user_id",
        "allergies",
        "parsed_items",
        "raw_text",
        "health_goal",
        "name",  # FoodItem.name / RetrievedFood.name 직접 노출 금지
        "profile",
        "user_profile",
    }
)


def _assert_no_pii_keys(captured: list[dict[str, object]]) -> None:
    """log entry dict들에 forbidden key가 노출되지 않았음을 검증."""
    for entry in captured:
        for forbidden_key in _FORBIDDEN_LOG_KEYS:
            assert forbidden_key not in entry, (
                f"forbidden key '{forbidden_key}' leaked in log entry: {entry}"
            )


async def test_evaluate_fit_log_masks_pii_allergen_short_circuit(
    fake_deps: NodeDeps,
) -> None:
    """CR M-1: NFR-S5 마스킹 — 알레르기 short-circuit 경로에서 PII 비노출.

    `caplog`(기존 테스트는 PrintLoggerFactory를 캡처 X — vacuous-pass) →
    `structlog.testing.capture_logs`로 교체. raw weight/height/age/user_id/
    allergen 라벨/parsed name/health_goal 모두 로그 entries에 노출 금지.
    """
    profile = _profile_for_masking(allergies=["땅콩"])
    items = [FoodItem(name="땅콩버터쿠키", confidence=0.9)]
    state = _state(profile=profile, parsed_items=items)

    with structlog_testing.capture_logs() as captured:
        await evaluate_fit(state, deps=fake_deps)

    # 1차 — forbidden key 절대 노출 금지 (key-level 검증).
    _assert_no_pii_keys(captured)

    # 2차 — value substring 검증 (fail-safe: 다른 키로 값이 leak되는 회귀 차단).
    log_text = " ".join(str(entry) for entry in captured)
    for forbidden_substr in (
        "63.7",  # weight_kg
        "171.5",  # height_cm
        "aaaaaaaa-bbbb-cccc-dddd",  # user_id prefix
        "땅콩버터쿠키",  # parsed name
        "weight_loss",  # health_goal value
    ):
        assert forbidden_substr not in log_text, (
            f"PII value '{forbidden_substr}' leaked — log={log_text}"
        )
    # 알레르기 라벨 자체 — reasons에 "알레르기 위반: 땅콩"이 *FitEvaluation*에 들어가지만
    # *로그 출력*은 violated_count 정수만이어야 함.
    assert "땅콩" not in log_text, f"allergen label leaked — log={log_text}"


async def test_evaluate_fit_log_masks_pii_happy_path_with_bmr_compute(
    fake_deps: NodeDeps,
) -> None:
    """CR M-1: NFR-S5 마스킹 — BMR/TDEE 계산 경로에서도 PII 비노출.

    allergen short-circuit가 아닌 정상 경로 — `compute_fit_score`가 weight/height/
    age로 BMR/TDEE 산출을 거치므로 마스킹 효과를 *실제로* 검증.
    """
    profile = _profile_for_masking()  # allergies=[]
    items = [FoodItem(name="짜장면", quantity="1인분", confidence=0.9)]
    foods = [
        RetrievedFood(
            name="짜장면",
            food_id=None,
            score=0.9,
            nutrition={"energy_kcal": 240, "carbohydrate_g": 32, "protein_g": 6, "fat_g": 8},
        )
    ]
    state = _state(profile=profile, parsed_items=items, retrieval=_retrieval(foods))

    with structlog_testing.capture_logs() as captured:
        out = await evaluate_fit(state, deps=fake_deps)

    # 정상 경로 — fit_reason="ok" 이어야 BMR/TDEE 계산을 거친 것.
    assert out["fit_evaluation"]["fit_reason"] == "ok"

    _assert_no_pii_keys(captured)

    log_text = " ".join(str(entry) for entry in captured)
    for forbidden_substr in (
        "63.7",
        "171.5",
        "aaaaaaaa-bbbb-cccc-dddd",
        "짜장면",
        "weight_loss",
    ):
        assert forbidden_substr not in log_text, (
            f"PII value '{forbidden_substr}' leaked — log={log_text}"
        )
