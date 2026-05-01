"""Story 3.3 — `fetch_user_profile` 노드 (*실 DB 조회* — D6, AC3).

단순 SELECT라 본 스토리 안에서 완성. 단계:
1. `deps.session_maker()` 컨텍스트로 `select(User).where(id == state["user_id"])`,
2. `scalar_one_or_none()` — None 시 즉시 `AnalysisNodeError` raise (retry skip
   — wrapper의 `retry_if_exception_type`이 `AnalysisNodeError` 제외),
3. `UserProfileSnapshot` Pydantic 매핑 후 dict 반환.

`allergies`는 `user.allergies or []` (Story 1.5 `text[]` nullable 정합).
`weight_kg`/`height_cm`는 DB Numeric → float (Pydantic이 Decimal/int 모두 수용).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.exceptions import AnalysisNodeError
from app.db.models.user import User
from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import MealAnalysisState, UserProfileSnapshot


@_node_wrapper("fetch_user_profile")
async def fetch_user_profile(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
    user_id = state["user_id"]
    async with deps.session_maker() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if user is None:
        raise AnalysisNodeError("fetch_user_profile.user_not_found")

    if user.health_goal is None or user.activity_level is None:
        raise AnalysisNodeError("fetch_user_profile.profile_incomplete")
    if user.age is None or user.weight_kg is None or user.height_cm is None:
        raise AnalysisNodeError("fetch_user_profile.profile_incomplete")

    snapshot = UserProfileSnapshot(
        user_id=user.id,
        health_goal=user.health_goal,
        age=user.age,
        weight_kg=float(user.weight_kg),
        height_cm=float(user.height_cm),
        activity_level=user.activity_level,
        allergies=list(user.allergies or []),
    )
    return {"user_profile": snapshot}
