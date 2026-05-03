"""Story 3.3 + 3.4 — `compile_pipeline` 컴파일 + 종단 테스트 (AC5).

Story 3.4 변경: parse_meal/retrieve_nutrition/rewrite_query/request_clarification이
실 비즈니스 로직으로 채워짐 → LLM/임베딩 어댑터 mock 필수. sentinel(``__test_low_confidence__``)
입력을 사용해 retrieve_nutrition의 결정성 분기로 진입(LLM 호출 없는 경로).
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
    """Story 3.4 — parse_meal_text/rewrite_food_query/generate_clarification_options
    어댑터 deterministic mock(OPENAI_API_KEY 부재 환경 호환).
    """
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


async def test_compile_pipeline_no_exception(db_deps: NodeDeps) -> None:
    """컴파일 정상 — Mermaid spec에 8 노드 모두 포함 (Story 3.4 — request_clarification 추가)."""
    checkpointer, pool = await build_checkpointer(settings.database_url)
    try:
        graph = compile_pipeline(checkpointer, db_deps)
        mermaid = graph.get_graph().draw_mermaid()
        for node in [
            "parse_meal",
            "retrieve_nutrition",
            "evaluate_retrieval_quality",
            "rewrite_query",
            "request_clarification",
            "fetch_user_profile",
            "evaluate_fit",
            "generate_feedback",
        ]:
            assert node in mermaid, f"node {node!r} missing in compiled graph"
    finally:
        await dispose_checkpointer(pool)


async def test_pipeline_high_confidence_no_rewrite(
    user_factory: UserFactory,
    db_deps: NodeDeps,
    _mock_llm_adapters: None,
) -> None:
    """high-confidence(sentinel + rewrite_attempts=1 시뮬레이션) — `rewrite_query` 미발동."""
    user = await user_factory(profile_completed=True)
    checkpointer, pool = await build_checkpointer(settings.database_url)
    try:
        graph = compile_pipeline(checkpointer, db_deps)
        thread_id = f"test-thread-{uuid.uuid4()}"
        # sentinel + rewrite_attempts=1 → 0.85 boost → confidence_ok → continue
        result = await graph.ainvoke(
            {
                "meal_id": uuid.uuid4(),
                "user_id": user.id,
                "raw_text": "__test_low_confidence__",
                "rewrite_attempts": 1,  # 이미 재검색 후 — sentinel boost 진입
                "node_errors": [],
                "needs_clarification": False,
                "clarification_options": [],
            },
            config={"configurable": {"thread_id": thread_id}},
        )
        assert result["rewrite_attempts"] == 1  # 증가 X
        # Story 3.6 — generate_feedback 노드는 가이드라인 chunks 부재 시 safe fallback
        # ("## 평가\n한국 1차 출처 가이드라인을 찾지 못해 ..." + "## 다음 행동") 반환
        # used_llm="stub". 본 통합 테스트는 guideline 시드 없이 호출되므로 stub fallback 정합.
        feedback = result["feedback"]
        assert feedback["used_llm"] == "stub"
        assert "## 평가" in feedback["text"]
        assert "## 다음 행동" in feedback["text"]
        # Story 3.5 — 실 결정성 알고리즘. checkpointer round-trip 후 dict 형태.
        fe = result["fit_evaluation"]
        assert fe["fit_reason"] == "ok"
        assert fe["fit_label"] in {"good", "caution", "needs_adjust"}
        assert 0 <= fe["fit_score"] <= 100
        assert result["user_profile"].user_id == user.id
    finally:
        await dispose_checkpointer(pool)


async def test_pipeline_low_confidence_triggers_self_rag(
    user_factory: UserFactory,
    db_deps: NodeDeps,
    _mock_llm_adapters: None,
) -> None:
    """low-confidence sentinel → Self-RAG 1회 재검색 → 신뢰도 boost 0.85 → continue 분기."""
    user = await user_factory(profile_completed=True)
    checkpointer, pool = await build_checkpointer(settings.database_url)
    try:
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
        # Self-RAG 1회 재검색 발동 → rewrite_attempts == 1
        assert result["rewrite_attempts"] == 1
        # boost 후 confidence 0.85
        assert result["retrieval"].retrieval_confidence == 0.85
        # Story 3.6 — guideline chunks 부재 시 safe fallback (used_llm="stub").
        feedback = result["feedback"]
        assert feedback["used_llm"] == "stub"
        assert "## 평가" in feedback["text"]
        # Story 3.5 — 실 결정성 알고리즘 — sentinel 흐름은 알레르기 X + nutrition 미포함.
        fe = result["fit_evaluation"]
        assert fe["fit_reason"] == "ok"
        assert 0 <= fe["fit_score"] <= 100
    finally:
        await dispose_checkpointer(pool)


async def test_pipeline_user_not_found_terminates_at_fetch_user_profile(
    db_deps: NodeDeps,
    _mock_llm_adapters: None,
) -> None:
    """user 미존재 → `fetch_user_profile`에서 `AnalysisNodeError` → 치명적 종료."""
    checkpointer, pool = await build_checkpointer(settings.database_url)
    try:
        graph = compile_pipeline(checkpointer, db_deps)
        thread_id = f"test-thread-{uuid.uuid4()}"
        result = await graph.ainvoke(
            {
                "meal_id": uuid.uuid4(),
                "user_id": uuid.uuid4(),  # 미존재
                "raw_text": "__test_low_confidence__",
                "rewrite_attempts": 1,  # high confidence boost branch — fetch_user_profile 도달
                "node_errors": [],
                "needs_clarification": False,
                "clarification_options": [],
            },
            config={"configurable": {"thread_id": thread_id}},
        )
        errs = result.get("node_errors", [])
        assert len(errs) >= 1
        assert any(
            e.node_name == "fetch_user_profile" and "user_not_found" in e.message for e in errs
        )
        assert result.get("user_profile") is None
        assert result.get("fit_evaluation") is None
        assert result.get("feedback") is None
    finally:
        await dispose_checkpointer(pool)


async def test_pipeline_persists_to_checkpointer(
    user_factory: UserFactory,
    db_deps: NodeDeps,
    _mock_llm_adapters: None,
) -> None:
    """`AsyncPostgresSaver` 영속화 — 같은 thread_id로 `aget_state` 시 state 보존."""
    user = await user_factory(profile_completed=True)
    checkpointer, pool = await build_checkpointer(settings.database_url)
    try:
        graph = compile_pipeline(checkpointer, db_deps)
        thread_id = f"test-thread-{uuid.uuid4()}"
        config = {"configurable": {"thread_id": thread_id}}
        await graph.ainvoke(
            {
                "meal_id": uuid.uuid4(),
                "user_id": user.id,
                "raw_text": "__test_low_confidence__",
                "rewrite_attempts": 1,
                "node_errors": [],
                "needs_clarification": False,
                "clarification_options": [],
            },
            config=config,
        )
        snapshot = await graph.aget_state(config)
        assert snapshot is not None
        assert snapshot.values["user_profile"].user_id == user.id
    finally:
        await dispose_checkpointer(pool)
