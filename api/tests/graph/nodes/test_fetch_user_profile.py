"""Story 3.3 — `fetch_user_profile` 노드 통합 테스트 (실 DB 조회, AC3)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.graph.deps import NodeDeps
from app.graph.nodes import fetch_user_profile
from app.graph.state import MealAnalysisState
from tests.conftest import UserFactory


def _state(user_id: uuid.UUID) -> MealAnalysisState:
    return {
        "meal_id": uuid.uuid4(),
        "user_id": user_id,
        "raw_text": "짜장면",
        "rewrite_attempts": 0,
        "node_errors": [],
    }


async def test_fetch_user_profile_real_db(
    user_factory: UserFactory,
    db_deps: NodeDeps,
) -> None:
    user = await user_factory(
        profile_completed=True,
        age=29,
        weight_kg=Decimal("65.5"),
        height_cm=170,
        activity_level="moderate",
        health_goal="weight_loss",
        allergies=["땅콩"],
    )
    out = await fetch_user_profile(_state(user.id), deps=db_deps)
    snap = out["user_profile"]
    assert snap.user_id == user.id
    assert snap.health_goal == "weight_loss"
    assert snap.age == 29
    assert snap.weight_kg == 65.5
    assert snap.height_cm == 170.0
    assert snap.activity_level == "moderate"
    assert snap.allergies == ["땅콩"]


async def test_fetch_user_profile_user_not_found_appends_node_error(
    db_deps: NodeDeps,
) -> None:
    """존재 X user_id → wrapper가 AnalysisNodeError를 swallow하고 NodeError append.

    `retry_if_exception_type`이 `AnalysisNodeError` 제외 — retry skip + 즉시
    fallback. wrapper는 raise X(다음 노드 진행).
    """
    out = await fetch_user_profile(_state(uuid.uuid4()), deps=db_deps)
    assert "node_errors" in out
    errs = out["node_errors"]
    assert len(errs) == 1
    assert errs[0].node_name == "fetch_user_profile"
    assert errs[0].error_class == "AnalysisNodeError"
    assert "user_not_found" in errs[0].message


async def test_fetch_user_profile_incomplete_profile_appends_node_error(
    user_factory: UserFactory,
    db_deps: NodeDeps,
) -> None:
    user = await user_factory(profile_completed=False)
    out = await fetch_user_profile(_state(user.id), deps=db_deps)
    errs = out["node_errors"]
    assert len(errs) == 1
    assert "profile_incomplete" in errs[0].message


# Story 4.4 — macro_goal JSONB 변환 분기 (AC8)


async def test_fetch_user_profile_macro_goal_set(
    user_factory: UserFactory,
    db_deps: NodeDeps,
) -> None:
    """Story 4.4 AC8 — ``users.macro_goal`` JSONB → MacroGoal Pydantic 변환."""
    from sqlalchemy import update

    from app.db.models.user import User

    user = await user_factory(profile_completed=True)
    # macro_goal SET — 직접 SQL UPDATE.
    async with db_deps.session_maker() as session:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                macro_goal={
                    "daily_calorie_target_kcal": 1800,
                    "protein_target_g_per_meal": 25,
                }
            )
        )
        await session.commit()

    out = await fetch_user_profile(_state(user.id), deps=db_deps)
    snap = out["user_profile"]
    assert snap.macro_goal is not None
    assert snap.macro_goal.daily_calorie_target_kcal == 1800
    assert snap.macro_goal.protein_target_g_per_meal == 25


async def test_fetch_user_profile_macro_goal_none_default(
    user_factory: UserFactory,
    db_deps: NodeDeps,
) -> None:
    """Story 4.4 AC8 — macro_goal=NULL 사용자(기존)는 snapshot.macro_goal=None."""
    user = await user_factory(profile_completed=True)
    out = await fetch_user_profile(_state(user.id), deps=db_deps)
    snap = out["user_profile"]
    assert snap.macro_goal is None
