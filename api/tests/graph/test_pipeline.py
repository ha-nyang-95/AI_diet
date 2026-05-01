"""Story 3.3 — `compile_pipeline` 컴파일 + 종단 테스트 (AC5)."""

from __future__ import annotations

import uuid

from app.core.config import settings
from app.graph.checkpointer import build_checkpointer, dispose_checkpointer
from app.graph.deps import NodeDeps
from app.graph.pipeline import compile_pipeline
from tests.conftest import UserFactory


async def test_compile_pipeline_no_exception(db_deps: NodeDeps) -> None:
    """컴파일 정상 — Mermaid spec에 7 노드 모두 포함."""
    checkpointer, pool = await build_checkpointer(settings.database_url)
    try:
        graph = compile_pipeline(checkpointer, db_deps)
        mermaid = graph.get_graph().draw_mermaid()
        for node in [
            "parse_meal",
            "retrieve_nutrition",
            "evaluate_retrieval_quality",
            "rewrite_query",
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
) -> None:
    """high-confidence — `rewrite_query` 미발동, `rewrite_attempts == 0`."""
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
        assert result["feedback"].text == "(분석 준비 중)"
        assert result["feedback"].used_llm == "stub"
        assert result["fit_evaluation"].fit_score == 50
        assert result["user_profile"].user_id == user.id
    finally:
        await dispose_checkpointer(pool)


async def test_pipeline_low_confidence_triggers_self_rag(
    user_factory: UserFactory,
    db_deps: NodeDeps,
) -> None:
    """low-confidence → Self-RAG 1회 재검색 후 신뢰도 boost → `"continue"` 분기."""
    user = await user_factory(profile_completed=True)
    checkpointer, pool = await build_checkpointer(settings.database_url)
    try:
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
        # Self-RAG 1회 재검색 발동 → rewrite_attempts == 1
        assert result["rewrite_attempts"] == 1
        # boost 후 confidence 0.85
        assert result["retrieval"].retrieval_confidence == 0.85
        # 종단 noun
        assert result["feedback"].text == "(분석 준비 중)"
        assert result["fit_evaluation"].fit_score == 50
    finally:
        await dispose_checkpointer(pool)


async def test_pipeline_user_not_found_continues_with_node_error(
    db_deps: NodeDeps,
) -> None:
    """user 미존재 → `fetch_user_profile`에서 `AnalysisNodeError` → wrapper가 NodeError로
    swallow + state 누적. evaluate_fit/generate_feedback은 *그래프 정의상* 진행
    (라우팅은 add_edge linear). user_profile 없이 stub 진행 (FR45 정합).
    """
    checkpointer, pool = await build_checkpointer(settings.database_url)
    try:
        graph = compile_pipeline(checkpointer, db_deps)
        thread_id = f"test-thread-{uuid.uuid4()}"
        result = await graph.ainvoke(
            {
                "meal_id": uuid.uuid4(),
                "user_id": uuid.uuid4(),  # 미존재
                "raw_text": "짜장면",
                "rewrite_attempts": 0,
                "node_errors": [],
                "needs_clarification": False,
            },
            config={"configurable": {"thread_id": thread_id}},
        )
        # NodeError 누적
        errs = result.get("node_errors", [])
        assert len(errs) >= 1
        assert any(
            e.node_name == "fetch_user_profile" and "user_not_found" in e.message for e in errs
        )
    finally:
        await dispose_checkpointer(pool)


async def test_pipeline_persists_to_checkpointer(
    user_factory: UserFactory,
    db_deps: NodeDeps,
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
                "raw_text": "짜장면",
                "rewrite_attempts": 0,
                "node_errors": [],
                "needs_clarification": False,
            },
            config=config,
        )
        snapshot = await graph.aget_state(config)
        assert snapshot is not None
        assert snapshot.values["user_profile"].user_id == user.id
    finally:
        await dispose_checkpointer(pool)
