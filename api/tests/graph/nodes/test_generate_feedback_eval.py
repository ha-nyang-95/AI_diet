"""Story 3.6 — T4 KPI eval (`@pytest.mark.eval`, AC3).

100건 fixture(meal raw_text × profile health_goal) — mocked LLM이 5 종류 출력 변형 cycle.
처리 후 정규식 통과율 ≥ 99건.

`RUN_EVAL_TESTS=1` 환경 변수 시점에만 실행 — pyproject.toml `markers` SOT 정합.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.graph.deps import NodeDeps
from app.graph.nodes import generate_feedback
from app.graph.state import (
    FeedbackLLMOutput,
    FitEvaluation,
    FoodItem,
    KnowledgeChunkContext,
    MealAnalysisState,
    UserProfileSnapshot,
)

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        os.getenv("RUN_EVAL_TESTS") != "1",
        reason="T4 KPI eval — RUN_EVAL_TESTS=1 opt-in",
    ),
]

_GF_MODULE = sys.modules["app.graph.nodes.generate_feedback"]

# 5 종류 출력 변형:
# 1) ok citation × 80 — 정상 인용 + 두 섹션
# 2) missing citation × 15 — 인용 누락 → 재생성 후 fallback
# 3) ad-violation × 5 — `치료` 위반 → 재생성 후 치환
_OK_TEMPLATE = "## 평가\n좋습니다. (출처: 식약처, X, 2020)\n## 다음 행동\n물 마시기"
_MISSING_TEMPLATE = "## 평가\n좋습니다.\n## 다음 행동\n물 마시기"
_AD_TEMPLATE = "## 평가\n비만 치료를 도와요. (출처: 식약처, X, 2020)\n## 다음 행동\n물"

_CITATION_PATTERN = re.compile(r"\(출처:[^)]*\)")


def _patch_session_maker(deps: NodeDeps) -> None:
    fake_session = AsyncMock()
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(return_value=fake_session)
    fake_cm.__aexit__ = AsyncMock(return_value=None)
    object.__setattr__(deps, "session_maker", MagicMock(return_value=fake_cm))


async def test_t4_kpi_citation_format_pass_rate_ge_99(
    fake_deps: NodeDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """100건 fixture → 정규식 통과율 ≥ 99건."""
    _patch_session_maker(fake_deps)

    chunks = [
        KnowledgeChunkContext(
            source="식약처",
            doc_title="X",
            published_year=2020,
            chunk_text="t",
            authority_grade="A",
        )
    ]

    async def fake_search(*args: Any, **kwargs: Any) -> list[KnowledgeChunkContext]:
        return chunks

    # 80 ok + 15 missing + 5 ad-violation cycle (idx % 100 — 100 fixture × 1 sample).
    cycle_outputs = [_OK_TEMPLATE] * 80 + [_MISSING_TEMPLATE] * 15 + [_AD_TEMPLATE] * 5
    # CR mn-24 — 이전 ``call_state["is_regen"]`` toggle은 dead code였음(idx unconditional
    # advance). 단순 카운터로 정리. 재생성 호출도 같은 cycle 반복 — 후처리 fallback이 통과
    # 보장(인용 missing → safe append, 광고 위반 → 자동 치환).
    call_state = {"idx": 0}

    async def fake_route(**kwargs: Any) -> tuple[FeedbackLLMOutput, str, bool]:
        text = cycle_outputs[call_state["idx"] % 100]
        call_state["idx"] += 1
        return (
            FeedbackLLMOutput(text=text, cited_chunk_indices=[0] if "(출처:" in text else []),
            "gpt-4o-mini",
            False,
        )

    monkeypatch.setattr(_GF_MODULE, "search_guideline_chunks", fake_search)
    monkeypatch.setattr(_GF_MODULE, "route_feedback", fake_route)

    profile = UserProfileSnapshot(
        user_id=uuid.uuid4(),
        health_goal="weight_loss",
        age=30,
        weight_kg=70.0,
        height_cm=170.0,
        activity_level="moderate",
        allergies=[],
    )
    fit = FitEvaluation(fit_score=70, reasons=["ok"], fit_reason="ok", fit_label="caution")
    items = [FoodItem(name="짜장면", quantity="1인분", confidence=0.9)]

    pass_count = 0
    for i in range(100):
        state: MealAnalysisState = {
            "meal_id": uuid.uuid4(),
            "user_id": profile.user_id,
            "raw_text": f"테스트 식단 {i}",
            "rewrite_attempts": 0,
            "parsed_items": items,
            "user_profile": profile,
            "fit_evaluation": fit,
            "node_errors": [],
        }
        out = await generate_feedback(state, deps=fake_deps)
        text = out["feedback"]["text"]
        if _CITATION_PATTERN.search(text):
            pass_count += 1
    assert pass_count >= 99, f"T4 KPI: {pass_count}/100 < 99"
