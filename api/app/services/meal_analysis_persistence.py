"""Story 3.7 — meal_analyses UPSERT helper (AC17 graceful degradation).

설계:
- ``INSERT ... ON CONFLICT (meal_id) DO UPDATE`` 단일 SQL — Postgres atomic UPSERT.
- 호출 측은 SSE generator의 ``event: done`` emit *직전* fresh session으로 호출.
  메인 라우터 ``DbSession``은 SSE generator 진입 후 일찍 release되므로 ``request.app.
  state.session_maker()``로 분리.
- 실패는 *fatal X* — Sentry capture + log warning + bool 반환. 사용자에게 결과는 보임,
  다음 재진입 시 다시 분석(graceful degradation per AC17).

UNIQUE(meal_id) 제약 → 1 meal = 1 analysis. 재분석은 같은 meal_id로 UPDATE.
"""

from __future__ import annotations

import contextlib
import math
import uuid
from typing import Any

import sentry_sdk
import structlog
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.meal_analysis import MealAnalysis
from app.graph.state import Citation
from app.services.feedback_summary import derive_feedback_summary
from app.services.sse_emitter import AnalysisDonePayload

log = structlog.get_logger(__name__)


async def upsert_meal_analysis(
    session: AsyncSession,
    *,
    meal_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: AnalysisDonePayload,
    fit_reason: str,
    citations: list[Citation],
) -> bool:
    """``INSERT ... ON CONFLICT (meal_id) DO UPDATE`` UPSERT 단일 SQL (AC17).

    설계:
    - 성공 → ``True`` 반환 + commit. 실패 → Sentry capture + log warning + ``False``
      (예외 전파 X — SSE 종료 흐름 보호 / graceful degradation).
    - ``feedback_summary``는 ``derive_feedback_summary``로 결정성 derive(LLM 추가 호출 0).
    - ``citations``는 jsonb 배열 — Pydantic ``model_dump(mode="json")``으로 직렬화.
    - ``updated_at``은 PostgreSQL `now()` 명시 갱신(``onupdate`` ORM hook은 ``UPDATE``
      문 발행 시점만 트리거 — INSERT ... ON CONFLICT DO UPDATE는 별 path).

    호출 측은 *fresh session*(``request.app.state.session_maker()``) + ``async with``
    blocking으로 lifecycle 관리. 본 함수는 commit 책임을 지님(graceful 흐름 정합).
    """
    try:
        # CR Wave 1 #2 — NaN/Inf macros guard. aggregate_meal_macros은 일반 흐름에서
        # finite를 반환하나, 상류 노드 버그 또는 corrupt state round-trip 시 NaN/Inf
        # 가능. `int(round(nan))` ValueError 후 broad except → 영구 persist 실패가
        # 사용자에게는 보이지 않는 silent loss. 사전 가드로 drop + Sentry capture.
        macro_values = (
            payload.macros.carbohydrate_g,
            payload.macros.protein_g,
            payload.macros.fat_g,
            payload.macros.energy_kcal,
        )
        if not all(math.isfinite(v) for v in macro_values):
            log.warning(
                "meal_analyses.upsert_skipped",
                meal_id=str(meal_id),
                reason="macros_not_finite",
            )
            return False

        feedback_summary = derive_feedback_summary(payload.feedback_text, max_chars=120)
        citations_json = [c.model_dump(mode="json") for c in citations]

        values: dict[str, Any] = {
            "meal_id": meal_id,
            "user_id": user_id,
            "fit_score": payload.final_fit_score,
            "fit_score_label": payload.fit_score_label,
            "fit_reason": fit_reason,
            "carbohydrate_g": payload.macros.carbohydrate_g,
            "protein_g": payload.macros.protein_g,
            "fat_g": payload.macros.fat_g,
            # MealMacros.energy_kcal는 float — DB는 int CHECK이라 round.
            "energy_kcal": int(round(payload.macros.energy_kcal)),
            "feedback_text": payload.feedback_text,
            "feedback_summary": feedback_summary,
            "citations": citations_json,
            "used_llm": payload.used_llm,
        }

        stmt = insert(MealAnalysis).values(**values)
        # ON CONFLICT (meal_id) — UNIQUE 제약 정합. SET은 *meta + 결과 컬럼 전부* — re-analysis
        # 시 score/macros/feedback 모두 갱신. created_at은 보존(첫 분석 시점 영속).
        stmt = stmt.on_conflict_do_update(
            index_elements=["meal_id"],
            set_={
                "user_id": stmt.excluded.user_id,
                "fit_score": stmt.excluded.fit_score,
                "fit_score_label": stmt.excluded.fit_score_label,
                "fit_reason": stmt.excluded.fit_reason,
                "carbohydrate_g": stmt.excluded.carbohydrate_g,
                "protein_g": stmt.excluded.protein_g,
                "fat_g": stmt.excluded.fat_g,
                "energy_kcal": stmt.excluded.energy_kcal,
                "feedback_text": stmt.excluded.feedback_text,
                "feedback_summary": stmt.excluded.feedback_summary,
                "citations": stmt.excluded.citations,
                "used_llm": stmt.excluded.used_llm,
                "updated_at": func.now(),
            },
        )
        await session.execute(stmt)
        await session.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — graceful 분기, 모든 예외 swallow.
        # NFR-S5 — meal_id만 raw, 본문/예외 stack은 Sentry 핸들러가 mask_event로 1차 가드.
        log.warning(
            "meal_analyses.upsert_failed",
            meal_id=str(meal_id),
            error_class=type(exc).__name__,
        )
        sentry_sdk.capture_exception(exc)
        with contextlib.suppress(Exception):
            await session.rollback()
        return False


__all__ = ["upsert_meal_analysis"]
