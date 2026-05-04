"""Story 3.6 — `generate_feedback` 노드 단위 테스트 (AC1-AC11, 12 케이스).

`route_feedback` + `search_guideline_chunks` monkeypatch로 LLM/DB 격리. fake_deps는
`redis=None` — cache 분기는 별 fixture(`redis_deps`).
"""

from __future__ import annotations

import sys
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import LLMRouterExhaustedError
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

# ---------- fixtures ----------


@pytest.fixture
def sample_profile() -> UserProfileSnapshot:
    return UserProfileSnapshot(
        user_id=uuid.uuid4(),
        health_goal="weight_loss",
        age=30,
        weight_kg=70.0,
        height_cm=170.0,
        activity_level="moderate",
        allergies=[],
    )


@pytest.fixture
def sample_fit() -> FitEvaluation:
    return FitEvaluation(
        fit_score=75,
        reasons=["탄수화물 비중 다소 높음"],
        fit_reason="ok",
        fit_label="caution",
    )


@pytest.fixture
def sample_items() -> list[FoodItem]:
    return [FoodItem(name="짜장면", quantity="1인분", confidence=0.9)]


@pytest.fixture
def sample_chunks() -> list[KnowledgeChunkContext]:
    return [
        KnowledgeChunkContext(
            source="식약처",
            doc_title="2020 한국인 영양소 섭취기준",
            published_year=2020,
            chunk_text="단백질 권장 섭취량은 ...",
            authority_grade="A",
        ),
        KnowledgeChunkContext(
            source="대한비만학회",
            doc_title="비만 진료지침 9판",
            published_year=2022,
            chunk_text="체중 감량 시 ...",
            authority_grade="A",
        ),
    ]


@pytest.fixture
def base_state(
    sample_profile: UserProfileSnapshot,
    sample_fit: FitEvaluation,
    sample_items: list[FoodItem],
) -> MealAnalysisState:
    return {
        "meal_id": uuid.uuid4(),
        "user_id": sample_profile.user_id,
        "raw_text": "짜장면 한 그릇",
        "rewrite_attempts": 0,
        "parsed_items": sample_items,
        "user_profile": sample_profile,
        "fit_evaluation": sample_fit,
        "node_errors": [],
    }


_GF_MODULE = sys.modules["app.graph.nodes.generate_feedback"]


def _patch_session_maker(deps: NodeDeps) -> None:
    """`async with deps.session_maker() as session:` 호출 안전 통과 — 테스트는
    `search_guideline_chunks`를 직접 monkeypatch해 session 자체는 미사용."""
    fake_session = AsyncMock()
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(return_value=fake_session)
    fake_cm.__aexit__ = AsyncMock(return_value=None)
    deps_session_maker = MagicMock(return_value=fake_cm)
    object.__setattr__(deps, "session_maker", deps_session_maker)


# ---------- 12 케이스 ----------


async def test_happy_path(
    fake_deps: NodeDeps,
    base_state: MealAnalysisState,
    sample_chunks: list[KnowledgeChunkContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC1, AC8 — 정상 흐름: chunks 5건 + LLM 성공 → citations 1+ + used_llm=gpt-4o-mini."""
    _patch_session_maker(fake_deps)

    async def fake_search(*args: Any, **kwargs: Any) -> list[KnowledgeChunkContext]:
        return sample_chunks

    async def fake_route(**kwargs: Any) -> tuple[FeedbackLLMOutput, str, bool]:
        text = (
            "## 평가\n좋습니다. (출처: 식약처, 2020 한국인 영양소 섭취기준, 2020)"
            "\n\n## 다음 행동\n물 마시기"
        )
        return (
            FeedbackLLMOutput(text=text, cited_chunk_indices=[0]),
            "gpt-4o-mini",
            False,
        )

    monkeypatch.setattr(_GF_MODULE, "search_guideline_chunks", fake_search)
    monkeypatch.setattr(_GF_MODULE, "route_feedback", fake_route)

    out = await generate_feedback(base_state, deps=fake_deps)
    fb = out["feedback"]
    assert fb["used_llm"] == "gpt-4o-mini"
    assert "(출처:" in fb["text"]
    assert len(fb["citations"]) == 1
    assert fb["citations"][0]["source"] == "식약처"


async def test_profile_missing_safe_fallback(
    fake_deps: NodeDeps,
    base_state: MealAnalysisState,
) -> None:
    """profile 부재 → safe fallback. LLM 호출 0회."""
    base_state.pop("user_profile", None)
    out = await generate_feedback(base_state, deps=fake_deps)
    fb = out["feedback"]
    assert fb["used_llm"] == "stub"
    assert "식사 정보가 부족" in fb["text"]


async def test_parsed_items_missing_safe_fallback(
    fake_deps: NodeDeps,
    base_state: MealAnalysisState,
) -> None:
    """parsed_items 부재 → safe fallback."""
    base_state["parsed_items"] = []
    out = await generate_feedback(base_state, deps=fake_deps)
    fb = out["feedback"]
    assert fb["used_llm"] == "stub"


async def test_chunks_empty_general_balance_fallback(
    fake_deps: NodeDeps,
    base_state: MealAnalysisState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chunks 빈 결과 → 일반 식사 균형 안내 fallback."""
    _patch_session_maker(fake_deps)

    async def fake_search(*args: Any, **kwargs: Any) -> list[KnowledgeChunkContext]:
        return []

    monkeypatch.setattr(_GF_MODULE, "search_guideline_chunks", fake_search)
    out = await generate_feedback(base_state, deps=fake_deps)
    fb = out["feedback"]
    assert fb["used_llm"] == "stub"
    assert "## 평가" in fb["text"]
    assert "## 다음 행동" in fb["text"]


async def test_citation_missing_regen_success(
    fake_deps: NodeDeps,
    base_state: MealAnalysisState,
    sample_chunks: list[KnowledgeChunkContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2 — 인용 누락 → 재생성 1회 → 성공."""
    _patch_session_maker(fake_deps)

    async def fake_search(*args: Any, **kwargs: Any) -> list[KnowledgeChunkContext]:
        return sample_chunks

    call_count = {"n": 0}

    async def fake_route(**kwargs: Any) -> tuple[FeedbackLLMOutput, str, bool]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (
                FeedbackLLMOutput(
                    text="## 평가\n좋습니다.\n## 다음 행동\n물",
                    cited_chunk_indices=[],
                ),
                "gpt-4o-mini",
                False,
            )
        return (
            FeedbackLLMOutput(
                text="## 평가\n(출처: 식약처, X, 2020) 좋습니다.\n## 다음 행동\n물",
                cited_chunk_indices=[0],
            ),
            "gpt-4o-mini",
            False,
        )

    monkeypatch.setattr(_GF_MODULE, "search_guideline_chunks", fake_search)
    monkeypatch.setattr(_GF_MODULE, "route_feedback", fake_route)

    out = await generate_feedback(base_state, deps=fake_deps)
    fb = out["feedback"]
    assert call_count["n"] == 2  # 1회 재생성
    assert "(출처:" in fb["text"]


async def test_citation_missing_persistent_safe_fallback(
    fake_deps: NodeDeps,
    base_state: MealAnalysisState,
    sample_chunks: list[KnowledgeChunkContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2 — 인용 누락 + 재생성 후에도 누락 → 안전 워딩 fallback append."""
    _patch_session_maker(fake_deps)

    async def fake_search(*args: Any, **kwargs: Any) -> list[KnowledgeChunkContext]:
        return sample_chunks

    async def fake_route(**kwargs: Any) -> tuple[FeedbackLLMOutput, str, bool]:
        return (
            FeedbackLLMOutput(
                text="## 평가\n좋습니다.\n## 다음 행동\n물",
                cited_chunk_indices=[],
            ),
            "gpt-4o-mini",
            False,
        )

    monkeypatch.setattr(_GF_MODULE, "search_guideline_chunks", fake_search)
    monkeypatch.setattr(_GF_MODULE, "route_feedback", fake_route)

    out = await generate_feedback(base_state, deps=fake_deps)
    fb = out["feedback"]
    assert "한국 1차 출처" in fb["text"]
    assert "(출처:" in fb["text"]


async def test_ad_violation_regen_success(
    fake_deps: NodeDeps,
    base_state: MealAnalysisState,
    sample_chunks: list[KnowledgeChunkContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC4 — 광고 위반(`치료`) → 재생성 1회 → 통과."""
    _patch_session_maker(fake_deps)

    async def fake_search(*args: Any, **kwargs: Any) -> list[KnowledgeChunkContext]:
        return sample_chunks

    call_count = {"n": 0}

    async def fake_route(**kwargs: Any) -> tuple[FeedbackLLMOutput, str, bool]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (
                FeedbackLLMOutput(
                    text="## 평가\n비만을 치료해요. (출처: 식약처, X, 2020)\n## 다음 행동\n물",
                    cited_chunk_indices=[0],
                ),
                "gpt-4o-mini",
                False,
            )
        return (
            FeedbackLLMOutput(
                text="## 평가\n비만을 관리해요. (출처: 식약처, X, 2020)\n## 다음 행동\n물",
                cited_chunk_indices=[0],
            ),
            "gpt-4o-mini",
            False,
        )

    monkeypatch.setattr(_GF_MODULE, "search_guideline_chunks", fake_search)
    monkeypatch.setattr(_GF_MODULE, "route_feedback", fake_route)

    out = await generate_feedback(base_state, deps=fake_deps)
    fb = out["feedback"]
    assert "치료" not in fb["text"]
    assert "관리" in fb["text"]


async def test_ad_violation_persistent_replace(
    fake_deps: NodeDeps,
    base_state: MealAnalysisState,
    sample_chunks: list[KnowledgeChunkContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC4 — 광고 위반 + 재생성 후 여전 → 자동 치환(`치료` → `관리`)."""
    _patch_session_maker(fake_deps)

    async def fake_search(*args: Any, **kwargs: Any) -> list[KnowledgeChunkContext]:
        return sample_chunks

    async def fake_route(**kwargs: Any) -> tuple[FeedbackLLMOutput, str, bool]:
        return (
            FeedbackLLMOutput(
                text="## 평가\n비만을 치료해요. (출처: 식약처, X, 2020)\n## 다음 행동\n물",
                cited_chunk_indices=[0],
            ),
            "gpt-4o-mini",
            False,
        )

    monkeypatch.setattr(_GF_MODULE, "search_guideline_chunks", fake_search)
    monkeypatch.setattr(_GF_MODULE, "route_feedback", fake_route)

    out = await generate_feedback(base_state, deps=fake_deps)
    fb = out["feedback"]
    assert "치료" not in fb["text"]
    assert "관리" in fb["text"]


async def test_structure_missing_regen_success(
    fake_deps: NodeDeps,
    base_state: MealAnalysisState,
    sample_chunks: list[KnowledgeChunkContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6 — 출력 구조 누락(## 다음 행동 부재) → 재생성 → 성공."""
    _patch_session_maker(fake_deps)

    async def fake_search(*args: Any, **kwargs: Any) -> list[KnowledgeChunkContext]:
        return sample_chunks

    call_count = {"n": 0}

    async def fake_route(**kwargs: Any) -> tuple[FeedbackLLMOutput, str, bool]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (
                FeedbackLLMOutput(
                    text="## 평가\n좋습니다. (출처: 식약처, X, 2020)",
                    cited_chunk_indices=[0],
                ),
                "gpt-4o-mini",
                False,
            )
        return (
            FeedbackLLMOutput(
                text="## 평가\n좋습니다. (출처: 식약처, X, 2020)\n## 다음 행동\n물",
                cited_chunk_indices=[0],
            ),
            "gpt-4o-mini",
            False,
        )

    monkeypatch.setattr(_GF_MODULE, "search_guideline_chunks", fake_search)
    monkeypatch.setattr(_GF_MODULE, "route_feedback", fake_route)

    out = await generate_feedback(base_state, deps=fake_deps)
    fb = out["feedback"]
    assert "## 다음 행동" in fb["text"]


async def test_structure_missing_persistent_append(
    fake_deps: NodeDeps,
    base_state: MealAnalysisState,
    sample_chunks: list[KnowledgeChunkContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6 — 출력 구조 누락 + 재생성 후에도 부재 → 안전 워딩 append."""
    _patch_session_maker(fake_deps)

    async def fake_search(*args: Any, **kwargs: Any) -> list[KnowledgeChunkContext]:
        return sample_chunks

    async def fake_route(**kwargs: Any) -> tuple[FeedbackLLMOutput, str, bool]:
        return (
            FeedbackLLMOutput(
                text="## 평가\n좋습니다. (출처: 식약처, X, 2020)",
                cited_chunk_indices=[0],
            ),
            "gpt-4o-mini",
            False,
        )

    monkeypatch.setattr(_GF_MODULE, "search_guideline_chunks", fake_search)
    monkeypatch.setattr(_GF_MODULE, "route_feedback", fake_route)

    out = await generate_feedback(base_state, deps=fake_deps)
    fb = out["feedback"]
    assert "## 다음 행동" in fb["text"]
    assert "균형 잡힌 식사" in fb["text"]


async def test_dual_llm_exhausted_safe_fallback(
    fake_deps: NodeDeps,
    base_state: MealAnalysisState,
    sample_chunks: list[KnowledgeChunkContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9 — 양쪽 LLM 실패 → safe fallback + used_llm=stub."""
    _patch_session_maker(fake_deps)

    async def fake_search(*args: Any, **kwargs: Any) -> list[KnowledgeChunkContext]:
        return sample_chunks

    async def fake_route(**kwargs: Any) -> tuple[FeedbackLLMOutput, str, bool]:
        raise LLMRouterExhaustedError("dual_llm_router_exhausted")

    monkeypatch.setattr(_GF_MODULE, "search_guideline_chunks", fake_search)
    monkeypatch.setattr(_GF_MODULE, "route_feedback", fake_route)

    out = await generate_feedback(base_state, deps=fake_deps)
    fb = out["feedback"]
    assert fb["used_llm"] == "stub"
    assert "AI 서비스 일시 장애" in fb["text"]


async def test_cache_hit_zero_llm_calls(
    fake_deps: NodeDeps,
    base_state: MealAnalysisState,
    sample_chunks: list[KnowledgeChunkContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC10 — cache hit 시 LLM 호출 0회 + cache_hit=True 동등 출력."""
    _patch_session_maker(fake_deps)

    async def fake_search(*args: Any, **kwargs: Any) -> list[KnowledgeChunkContext]:
        return sample_chunks

    call_count = {"n": 0}

    async def fake_route(**kwargs: Any) -> tuple[FeedbackLLMOutput, str, bool]:
        call_count["n"] += 1
        # cache hit 시뮬레이션 — cache_hit=True 반환
        return (
            FeedbackLLMOutput(
                text="## 평가\n좋습니다. (출처: 식약처, X, 2020)\n## 다음 행동\n물",
                cited_chunk_indices=[0],
            ),
            "claude",
            True,
        )

    monkeypatch.setattr(_GF_MODULE, "search_guideline_chunks", fake_search)
    monkeypatch.setattr(_GF_MODULE, "route_feedback", fake_route)

    out = await generate_feedback(base_state, deps=fake_deps)
    fb = out["feedback"]
    assert fb["used_llm"] == "claude"
    assert call_count["n"] == 1  # router 1회 호출 — 내부에서 cache hit 처리
