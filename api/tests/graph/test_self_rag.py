"""Story 3.3 + 3.4 — Self-RAG 분기 + 1회 한도 + 재질문 회귀 가드.

Story 3.4 갱신: low confidence + rewrite_attempts >= 1 → "clarify" → request_clarification
노드 → END (분석 일시 정지). fit_evaluation/generate_feedback 미진행.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.openai_adapter import (
    ClarificationVariants,
    ParsedMeal,
    ParsedMealItem,
    RewriteVariants,
)
from app.core.config import settings
from app.graph.checkpointer import build_checkpointer, dispose_checkpointer
from app.graph.deps import NodeDeps
from app.graph.pipeline import compile_pipeline
from app.graph.state import ClarificationOption
from tests.conftest import UserFactory


@pytest.fixture
def _mock_llm_adapters() -> Iterator[None]:
    """LLM 어댑터 deterministic mock — parse_meal/rewrite_query/request_clarification."""
    parsed = ParsedMeal(
        items=[ParsedMealItem(name="__test_low_confidence__", quantity="1인분", confidence=0.9)]
    )
    rewrite = RewriteVariants(variants=["__test_low_confidence___v1"])
    clarify = ClarificationVariants(options=[ClarificationOption(label="옵션", value="옵션 1인분")])
    with (
        patch(
            "app.graph.nodes.parse_meal.parse_meal_text",
            new=AsyncMock(return_value=parsed),
        ),
        patch(
            "app.graph.nodes.rewrite_query.rewrite_food_query",
            new=AsyncMock(return_value=rewrite),
        ),
        patch(
            "app.graph.nodes.request_clarification.generate_clarification_options",
            new=AsyncMock(return_value=clarify),
        ),
    ):
        yield


async def test_self_rag_one_attempt_limit_routes_to_clarify(
    user_factory: UserFactory,
    db_deps: NodeDeps,
    _mock_llm_adapters: None,
) -> None:
    """Story 3.4 — `retrieve_nutrition` 항상 낮음 → 1회 재검색 후 미달 → "clarify".

    rewrite_attempts == 1 도달 + low confidence 지속 → evaluate가 "clarify" 분기 →
    request_clarification 노드 → END (fit_score/feedback 미진행).
    """
    user = await user_factory(profile_completed=True)
    checkpointer, pool = await build_checkpointer(settings.database_url)

    from app.graph.state import RetrievalResult

    async def _always_low(state: dict[str, object], **_: object) -> dict[str, object]:
        return {"retrieval": RetrievalResult(retrieved_foods=[], retrieval_confidence=0.1)}

    # generate_clarification_options을 mock — request_clarification 노드 LLM 호출 격리.
    fake_variants = ClarificationVariants(
        options=[
            ClarificationOption(label="옵션1", value="옵션1 1인분"),
            ClarificationOption(label="옵션2", value="옵션2 1인분"),
        ]
    )

    try:
        with (
            patch("app.graph.pipeline.retrieve_nutrition", new=_always_low),
            patch(
                "app.graph.nodes.request_clarification.generate_clarification_options",
                new=AsyncMock(return_value=fake_variants),
            ),
        ):
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
                    "clarification_options": [],
                },
                config={"configurable": {"thread_id": thread_id}},
            )
            # 1회 한도 도달 — 정확히 1
            assert result["rewrite_attempts"] == 1
            decision = result["evaluation_decision"]
            assert decision["route"] == "clarify"
            assert "rewrite_limit_reached" in decision["reason"]
            # request_clarification 노드가 needs_clarification=True + options 박음.
            assert result["needs_clarification"] is True
            assert len(result["clarification_options"]) >= 1
            # END 도달 — fit_evaluation/feedback 미진행 (Story 3.5/3.6 stub 미실행).
            assert "fit_evaluation" not in result or result.get("fit_evaluation") is None
    finally:
        await dispose_checkpointer(pool)


async def test_self_rag_high_confidence_skips_rewrite(
    user_factory: UserFactory,
    db_deps: NodeDeps,
    _mock_llm_adapters: None,
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
                "raw_text": "__test_low_confidence__",  # sentinel — 실 DB 검색 회피
                "rewrite_attempts": 1,  # 이미 재검색 후 — sentinel + attempts > 0 → 0.85 boost
                "node_errors": [],
                "needs_clarification": False,
                "clarification_options": [],
            },
            config={"configurable": {"thread_id": thread_id}},
        )
        # rewrite_attempts=1 그대로(증가 X — high conf로 rewrite skip).
        assert result["rewrite_attempts"] == 1
        decision = result["evaluation_decision"]
        assert decision["route"] == "continue"
        assert decision["reason"] == "confidence_ok"
    finally:
        await dispose_checkpointer(pool)


async def test_self_rag_clarify_after_rewrite_query_persistent_failure(
    user_factory: UserFactory,
    db_deps: NodeDeps,
    _mock_llm_adapters: None,
) -> None:
    """무한 루프 회귀 가드 + Story 3.4 — `rewrite_query` 매번 실패 + low conf →
    `evaluate_retrieval_quality`가 ``node_errors`` 카운트로 attempts >= 1 인식 → "clarify".

    Story 3.3에서는 "continue"였으나 Story 3.4에서는 low conf 시 clarify로 분기.
    """
    import httpx

    from app.graph.nodes._wrapper import _node_wrapper

    user = await user_factory(profile_completed=True)
    checkpointer, pool = await build_checkpointer(settings.database_url)

    @_node_wrapper("rewrite_query")
    async def _wrapped_always_fail(state: dict[str, object], **_: object) -> dict[str, object]:
        raise httpx.TimeoutException("rewrite_query transient")

    fake_variants = ClarificationVariants(
        options=[ClarificationOption(label="옵션1", value="옵션1")]
    )

    try:
        with (
            patch("app.graph.pipeline.rewrite_query", new=_wrapped_always_fail),
            patch(
                "app.graph.nodes.request_clarification.generate_clarification_options",
                new=AsyncMock(return_value=fake_variants),
            ),
        ):
            graph = compile_pipeline(checkpointer, db_deps)
            thread_id = f"test-thread-{uuid.uuid4()}"
            result = await graph.ainvoke(
                {
                    "meal_id": uuid.uuid4(),
                    "user_id": user.id,
                    "raw_text": "__test_low_confidence__",
                    "rewrite_attempts": 0,
                    "node_errors": [],
                    "needs_clarification": False,
                    "clarification_options": [],
                },
                config={"configurable": {"thread_id": thread_id}},
            )
            errs = result.get("node_errors", [])
            assert any(e.node_name == "rewrite_query" for e in errs)
            decision = result["evaluation_decision"]
            assert decision["route"] == "clarify"
            assert "rewrite_limit_reached" in decision["reason"]
            assert result["needs_clarification"] is True
    finally:
        await dispose_checkpointer(pool)
