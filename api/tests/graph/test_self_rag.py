"""Story 3.3 — Self-RAG 분기 + 1회 한도 회귀 가드 (AC5, D5).

`compile_pipeline`을 통한 종단 흐름에서 Self-RAG 분기와 1회 한도가 정확히 작동하는지
검증. 무한 루프 차단 SOT — `evaluate_retrieval_quality.stub`을 monkey-patch로
*항상 낮음* 강제 시 `rewrite_attempts == 1`에서 멈추고 `"continue"` 반환.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

from app.core.config import settings
from app.graph.checkpointer import build_checkpointer, dispose_checkpointer
from app.graph.deps import NodeDeps
from app.graph.pipeline import compile_pipeline
from tests.conftest import UserFactory


async def test_self_rag_one_attempt_limit_under_persistent_low_confidence(
    user_factory: UserFactory,
    db_deps: NodeDeps,
) -> None:
    """`retrieve_nutrition`을 *항상 낮음* 강제 — `rewrite_attempts == 1`에서 멈춤.

    무한 루프 회귀 가드. `evaluate_retrieval_quality`가 `rewrite_attempts < 1` 가드로
    1회 한도 강제 + 2회 도달 시 강제 `"continue"` → `fetch_user_profile` 분기.
    """
    user = await user_factory(profile_completed=True)
    checkpointer, pool = await build_checkpointer(settings.database_url)

    from app.graph.state import RetrievalResult

    async def _always_low(state: dict[str, object], **_: object) -> dict[str, object]:
        return {"retrieval": RetrievalResult(retrieved_foods=[], retrieval_confidence=0.1)}

    try:
        # pipeline.py가 `from app.graph.nodes import retrieve_nutrition`로 함수를
        # 컴파일 시점에 캡처 — `app.graph.pipeline.retrieve_nutrition` reference를
        # patch해야 partial 묶기 직전에 교체된다. 새 graph를 patch 컨텍스트 내부에서
        # 빌드해야 부분.
        with patch("app.graph.pipeline.retrieve_nutrition", new=_always_low):
            graph = compile_pipeline(checkpointer, db_deps)
            thread_id = f"test-thread-{uuid.uuid4()}"
            result = await graph.ainvoke(
                {
                    "meal_id": uuid.uuid4(),
                    "user_id": user.id,
                    "raw_text": "low_confidence_food",
                    "rewrite_attempts": 0,
                    "node_errors": [],
                    "needs_clarification": False,
                },
                config={"configurable": {"thread_id": thread_id}},
            )
            # 1회 한도 도달 — 정확히 1
            assert result["rewrite_attempts"] == 1
            # rewrite_limit_reached 분기 — `evaluate_retrieval_quality`가 강제 "continue"
            assert result["evaluation_decision"].route == "continue"
            assert result["evaluation_decision"].reason == "rewrite_limit_reached"
            # 종단 — fit_evaluation/feedback이 stub으로 진행
            assert result["fit_evaluation"].fit_score == 50
    finally:
        await dispose_checkpointer(pool)


async def test_self_rag_high_confidence_skips_rewrite(
    user_factory: UserFactory,
    db_deps: NodeDeps,
) -> None:
    """high-confidence(0.7) — `rewrite_query` 미발동, 분기는 `"continue"`."""
    user = await user_factory(profile_completed=True)
    checkpointer, pool = await build_checkpointer(settings.database_url)
    try:
        graph = compile_pipeline(checkpointer, db_deps)
        thread_id = f"test-thread-{uuid.uuid4()}"
        result = await graph.ainvoke(
            {
                "meal_id": uuid.uuid4(),
                "user_id": user.id,
                "raw_text": "짜장면",
                "rewrite_attempts": 0,
                "node_errors": [],
                "needs_clarification": False,
            },
            config={"configurable": {"thread_id": thread_id}},
        )
        assert result["rewrite_attempts"] == 0
        assert result["evaluation_decision"].route == "continue"
        assert result["evaluation_decision"].reason == "confidence_ok"
    finally:
        await dispose_checkpointer(pool)
