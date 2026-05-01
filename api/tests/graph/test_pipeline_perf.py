"""Story 3.3 — 성능 budget 골격 (AC12, NFR-P4 / NFR-P5 / T1 KPI).

`@pytest.mark.perf` skip 디폴트 — `RUN_PERF_TESTS=1` 또는 `pytest -m perf` opt-in.
stub 단계에서는 ≤ 100ms 일반적 — 본 스토리는 *budget 명시 + 인프라 박기*. 실측은
Story 3.6 진입(실 LLM/RAG 호출) 후. CI는 주간 cron 권장.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

from app.core.config import settings
from app.graph.checkpointer import build_checkpointer, dispose_checkpointer
from app.graph.deps import NodeDeps
from app.graph.pipeline import compile_pipeline
from tests.conftest import UserFactory

pytestmark = pytest.mark.perf

NFR_P4_BUDGET_SECONDS = 3.0
NFR_P5_BUDGET_DELTA_SECONDS = 2.0
T1_FAILURE_RATE_THRESHOLD = 0.02


def _perf_enabled() -> bool:
    return os.environ.get("RUN_PERF_TESTS", "").lower() in {"1", "true", "yes", "on"}


@pytest.mark.skipif(not _perf_enabled(), reason="RUN_PERF_TESTS=1 opt-in 필요")
async def test_nfr_p4_single_call_avg_under_3s(
    user_factory: UserFactory,
    db_deps: NodeDeps,
) -> None:
    """NFR-P4 — `analysis_service.run("짜장면")` 30회 평균 ≤ 3s."""
    user = await user_factory(profile_completed=True)
    checkpointer, pool = await build_checkpointer(settings.database_url)
    try:
        graph = compile_pipeline(checkpointer, db_deps)
        durations: list[float] = []
        for _ in range(30):
            start = time.perf_counter()
            await graph.ainvoke(
                {
                    "meal_id": uuid.uuid4(),
                    "user_id": user.id,
                    "raw_text": "짜장면",
                    "rewrite_attempts": 0,
                    "node_errors": [],
                    "needs_clarification": False,
                },
                config={"configurable": {"thread_id": f"perf-{uuid.uuid4()}"}},
            )
            durations.append(time.perf_counter() - start)
        avg = sum(durations) / len(durations)
        assert avg <= NFR_P4_BUDGET_SECONDS, (
            f"NFR-P4 budget 초과: avg={avg:.2f}s > {NFR_P4_BUDGET_SECONDS}s"
        )
    finally:
        await dispose_checkpointer(pool)


@pytest.mark.skipif(not _perf_enabled(), reason="RUN_PERF_TESTS=1 opt-in 필요")
async def test_nfr_p5_self_rag_within_plus_2s(
    user_factory: UserFactory,
    db_deps: NodeDeps,
) -> None:
    """NFR-P5 — Self-RAG 발동 호출(`low_confidence_food`) 30회 평균 ≤ NFR-P4 + 2s."""
    user = await user_factory(profile_completed=True)
    checkpointer, pool = await build_checkpointer(settings.database_url)
    try:
        graph = compile_pipeline(checkpointer, db_deps)
        durations: list[float] = []
        for _ in range(30):
            start = time.perf_counter()
            await graph.ainvoke(
                {
                    "meal_id": uuid.uuid4(),
                    "user_id": user.id,
                    "raw_text": "low_confidence_food",
                    "rewrite_attempts": 0,
                    "node_errors": [],
                    "needs_clarification": False,
                },
                config={"configurable": {"thread_id": f"perf-{uuid.uuid4()}"}},
            )
            durations.append(time.perf_counter() - start)
        avg = sum(durations) / len(durations)
        budget = NFR_P4_BUDGET_SECONDS + NFR_P5_BUDGET_DELTA_SECONDS
        assert avg <= budget, f"NFR-P5 budget 초과: avg={avg:.2f}s > {budget}s"
    finally:
        await dispose_checkpointer(pool)


@pytest.mark.skipif(not _perf_enabled(), reason="RUN_PERF_TESTS=1 opt-in 필요")
async def test_t1_kpi_100_calls_under_2pct_failure(
    user_factory: UserFactory,
    db_deps: NodeDeps,
) -> None:
    """T1 KPI — 100회 혼합 시나리오 호출 실패율 ≤ 2%."""
    user = await user_factory(profile_completed=True)
    checkpointer, pool = await build_checkpointer(settings.database_url)
    scenarios = ["짜장면", "low_confidence_food", ""]
    failures = 0
    try:
        graph = compile_pipeline(checkpointer, db_deps)
        for i in range(100):
            raw = scenarios[i % len(scenarios)]
            try:
                state = await graph.ainvoke(
                    {
                        "meal_id": uuid.uuid4(),
                        "user_id": user.id,
                        "raw_text": raw,
                        "rewrite_attempts": 0,
                        "node_errors": [],
                        "needs_clarification": False,
                    },
                    config={"configurable": {"thread_id": f"perf-{uuid.uuid4()}"}},
                )
                # *그래프가 종료* 했고 stub feedback이 있으면 성공으로 간주.
                if state.get("feedback") is None:
                    failures += 1
            except Exception:  # noqa: BLE001
                failures += 1
        rate = failures / 100
        assert rate <= T1_FAILURE_RATE_THRESHOLD, (
            f"T1 KPI 실패율 초과: {rate * 100:.1f}% > {T1_FAILURE_RATE_THRESHOLD * 100:.0f}%"
        )
    finally:
        await dispose_checkpointer(pool)
