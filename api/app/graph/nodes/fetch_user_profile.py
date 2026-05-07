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

import structlog
from pydantic import ValidationError
from sqlalchemy import select

from app.core.exceptions import AnalysisNodeError
from app.db.models.user import User
from app.domain.macro_goal import MacroGoal
from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import MealAnalysisState, UserProfileSnapshot

log = structlog.get_logger(__name__)


@_node_wrapper("fetch_user_profile", deterministic=True)
async def fetch_user_profile(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
    user_id = state["user_id"]
    async with deps.session_maker() as session:
        # soft-deleted user는 미존재 취급 — PII(allergies/age/weight) 누설 차단.
        result = await session.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()

    if user is None:
        raise AnalysisNodeError("fetch_user_profile.user_not_found")

    if user.health_goal is None or user.activity_level is None:
        raise AnalysisNodeError("fetch_user_profile.profile_incomplete")
    if user.age is None or user.weight_kg is None or user.height_cm is None:
        raise AnalysisNodeError("fetch_user_profile.profile_incomplete")

    # Story 4.4 — JSONB → MacroGoal 변환. legacy invalid shape는 ValidationError →
    # graceful None(기존 분석 흐름 보존). Pydantic 1차 게이트 + DB CHECK 2차 가드를
    # 통과한 row만 정상 instance, 그 외는 *None* fallback(기존 사용자 동작 그대로).
    macro_goal: MacroGoal | None = None
    if user.macro_goal:
        try:
            macro_goal = MacroGoal.model_validate(user.macro_goal)
        except ValidationError as exc:
            log.warning(
                "fetch_user_profile.macro_goal_invalid",
                user_id=str(user.id),
                error=type(exc).__name__,
            )
            macro_goal = None

    snapshot = UserProfileSnapshot(
        user_id=user.id,
        health_goal=user.health_goal,
        age=user.age,
        weight_kg=float(user.weight_kg),
        height_cm=float(user.height_cm),
        activity_level=user.activity_level,
        allergies=list(user.allergies or []),
        macro_goal=macro_goal,
    )
    return {"user_profile": snapshot}
