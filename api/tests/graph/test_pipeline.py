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
                "raw_text": "__test_low_confidence__",
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


async def test_pipeline_user_not_found_terminates_at_fetch_user_profile(
    db_deps: NodeDeps,
) -> None:
    """user 미존재 → `fetch_user_profile`에서 `AnalysisNodeError` → wrapper가 NodeError 누적
    → `route_after_node_error`가 `"end"` 분기 → 후속 노드 미진행 (치명적 케이스 종료).
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
        # 치명적 종료 — 후속 노드 미진행
        assert result.get("user_profile") is None
        assert result.get("fit_evaluation") is None
        assert result.get("feedback") is None
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
