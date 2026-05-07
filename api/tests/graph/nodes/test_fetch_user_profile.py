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


# Story 5.1 — FR3 즉시 반영 sha256 mismatch 가드 (AC7)


async def test_fetch_user_profile_after_weight_change_changes_profile_hash(
    user_factory: UserFactory,
    db_deps: NodeDeps,
) -> None:
    """Story 5.1 AC7 — PATCH 시뮬레이션 후 ``_build_profile_hash`` sha256 mismatch.

    *Why*: PATCH endpoint가 ``users.weight_kg``을 갱신하면 다음 분석 호출 시
    ``fetch_user_profile`` 노드가 fresh DB SELECT로 새 weight를 로드하고, 그 결과
    ``_build_profile_hash``의 sha256이 자동 변경되어 LLM cache miss → 새 LLM 호출
    트리거. 별도 ``redis.delete`` 없이 6 필드 SOT만으로 자동 invalidate되는 회귀 가드.

    weight_kg 80.0 → 75.0 (1 kg 단위 변동도 hash mismatch 보장).
    """
    from decimal import Decimal

    from sqlalchemy import update

    from app.db.models.user import User
    from app.graph.nodes.generate_feedback import _build_profile_hash

    user = await user_factory(
        profile_completed=True,
        weight_kg=Decimal("80.0"),
    )

    snap_before = (await fetch_user_profile(_state(user.id), deps=db_deps))["user_profile"]
    hash_before = _build_profile_hash(snap_before)

    # PATCH 시뮬레이션 — weight_kg 80 → 75. profile_updated_at도 set.
    from sqlalchemy import func

    async with db_deps.session_maker() as session:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                weight_kg=Decimal("75.0"),
                profile_updated_at=func.now(),
                updated_at=func.now(),
            )
        )
        await session.commit()

    snap_after = (await fetch_user_profile(_state(user.id), deps=db_deps))["user_profile"]
    hash_after = _build_profile_hash(snap_after)

    assert snap_before.weight_kg == 80.0
    assert snap_after.weight_kg == 75.0
    assert hash_before != hash_after, (
        "profile hash must change after weight_kg PATCH — "
        "LLM cache miss 자동 트리거 회귀 가드(redis.delete 미필요 SOT)."
    )
