"""Story 3.9 AC12 — SSE T5 KPI perf marker (DF115 from Story 3.7→3.8).

``@pytest.mark.perf`` + ``RUN_PERF_TESTS=1`` opt-in. 50회 SSE stream simulation +
``EventSource.onerror`` 카운터 ≤ 1 단언. LangSmith dataset(``balancenote-korean-foods-v1``)
50건 evaluate run의 끊김 카운트 통계 활용 가능.

본 marker는 *measurement skeleton* — 실 dataset evaluation 통합은 LangSmith CI
``langsmith-eval-regression`` job(workflow_dispatch + ``langsmith-eval`` 라벨)이 책임.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.perf

_T5_KPI_DROP_THRESHOLD = 1
_T5_KPI_RUN_COUNT = 50


def _perf_enabled() -> bool:
    return os.environ.get("RUN_PERF_TESTS", "").lower() in {"1", "true", "yes", "on"}


@pytest.mark.skipif(not _perf_enabled(), reason="RUN_PERF_TESTS=1 opt-in 필요")
async def test_sse_t5_kpi_drop_count_under_threshold() -> None:
    """T5 KPI — 50회 SSE stream simulation 끊김 ≤ 1.

    실 SSE stream 50회 실행은 lifespan + LangGraph + Redis + 모바일 SSE 클라이언트
    full stack 구성 필요. LangSmith dataset 50건 evaluate run으로 대체 가능 — `dataset
    run.error_count` ≤ 1 단언.
    """
    pytest.skip(
        "SSE T5 KPI dataset wire-up은 langsmith-eval-regression job(workflow_dispatch "
        "+ langsmith-eval 라벨)으로 위임 — measurement marker only."
    )
    assert _T5_KPI_DROP_THRESHOLD == 1  # noqa: PLR2004 — SOT 회귀 가드
    assert _T5_KPI_RUN_COUNT == 50  # noqa: PLR2004
