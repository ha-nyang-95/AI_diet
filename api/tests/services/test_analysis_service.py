"""Story 3.3 + 3.4 — `AnalysisService` 종단 + 인터페이스 테스트 (AC8 + AC10)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

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
from app.services.analysis_service import AnalysisService
from tests.conftest import UserFactory


@pytest.fixture(autouse=True)
def _mock_llm_adapters() -> Iterator[None]:
    """LLM 어댑터 deterministic mock — 모든 테스트에 적용 (parse_meal/rewrite/clarify)."""
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


@pytest_asyncio.fixture
async def analysis_service(client: AsyncClient) -> AsyncIterator[AnalysisService]:
    """별 checkpointer pool 빌드 + 컴파일된 graph로 service 인스턴스화."""
    _ = client  # ensure lifespan started
    from app.main import app

    deps = NodeDeps(
        session_maker=app.state.session_maker,
        redis=app.state.redis,
        settings=settings,
    )
    checkpointer, pool = await build_checkpointer(settings.database_url)
    graph = compile_pipeline(checkpointer, deps)
    service = AnalysisService(graph=graph, deps=deps)
    yield service
    await dispose_checkpointer(pool)


async def test_run_returns_state_with_stub_feedback(
    user_factory: UserFactory,
    analysis_service: AnalysisService,
) -> None:
    """sentinel 입력 — high conf branch + 종단 stub 도달."""
    user = await user_factory(profile_completed=True)
    state = await analysis_service.run(
        meal_id=uuid.uuid4(),
        user_id=user.id,
        raw_text="__test_low_confidence__",  # sentinel — DB lookup 회피, 0.85 boost
    )
    assert state["feedback"].used_llm == "stub"
    assert state["feedback"].text == "(분석 준비 중)"
    # Story 3.5 — 실 결정성 알고리즘 출력 + components 분해. dict 형태(model_dump).
    fe = state["fit_evaluation"]
    assert fe["fit_reason"] == "ok"
    assert 0 <= fe["fit_score"] <= 100
    assert fe["components"]["allergen"] == 20  # 위반 X → 만점


async def test_run_default_thread_id_uses_meal_prefix(
    user_factory: UserFactory,
    analysis_service: AnalysisService,
) -> None:
    """`thread_id` 미지정 시 `meal:{meal_id}` — checkpoint 멱등 가드."""
    user = await user_factory(profile_completed=True)
    meal_id = uuid.uuid4()
    await analysis_service.run(meal_id=meal_id, user_id=user.id, raw_text="__test_low_confidence__")
    snap = await analysis_service.aget_state(thread_id=f"meal:{meal_id}")
    assert snap["user_profile"].user_id == user.id


async def test_aget_state_unknown_thread_returns_empty(
    analysis_service: AnalysisService,
) -> None:
    snap = await analysis_service.aget_state(thread_id=f"unknown-{uuid.uuid4()}")
    assert snap == {} or snap.get("user_profile") is None


async def test_aresume_raises_when_user_input_empty(
    analysis_service: AnalysisService,
) -> None:
    """Story 3.4 AC10 — user_input에 raw_text_clarified/selected_value 없으면 ValueError."""
    with pytest.raises(ValueError):
        await analysis_service.aresume(thread_id="thread-x", user_input={})

    with pytest.raises(ValueError):
        await analysis_service.aresume(thread_id="thread-x", user_input={"selected_value": "  "})


async def test_aresume_resumes_from_parse_meal_with_clarified_text(
    user_factory: UserFactory,
    analysis_service: AnalysisService,
) -> None:
    """Story 3.4 AC10 — 실 clarification 시나리오 정합 resume 검증.

    CR fix #7 — 이전 vacuous OR assert(`feedback is not None or needs_clarification`)를
    명시 contract로 교체. 실제 라우터 시나리오는 (1) ``run`` 호출로 checkpoint에 user_id
    저장 → (2) clarification → END → (3) ``aresume``으로 사용자 정제 텍스트 주입. 본
    테스트는 (1)+(3)으로 단축 — checkpoint user_id를 보존한 상태에서 aresume이
    parse_meal부터 재진입해 종단 stub에 도달함을 검증.
    """
    user = await user_factory(profile_completed=True)
    thread_id = f"thread-{uuid.uuid4()}"

    fake_variants = ClarificationVariants(
        options=[ClarificationOption(label="짜장면", value="짜장면 1인분")]
    )

    # (1) 1차 run — checkpoint에 user_id 저장 + sentinel 흐름으로 종단 stub 도달.
    with patch(
        "app.graph.nodes.request_clarification.generate_clarification_options",
        new=AsyncMock(return_value=fake_variants),
    ):
        first_result = await analysis_service.run(
            meal_id=uuid.uuid4(),
            user_id=user.id,
            raw_text="__test_low_confidence__",
            thread_id=thread_id,
        )
        # 1차 흐름 sanity — sentinel 0.3 → rewrite +1 → 0.85 boost → continue → stub.
        assert first_result["rewrite_attempts"] == 1

        # (3) aresume — clean slate reset + force_llm_parse=True로 parse_meal 재진입.
        result = await analysis_service.aresume(
            thread_id=thread_id,
            user_input={"selected_value": "__test_low_confidence__"},
        )

    # 명시 contract — aresume이 Self-RAG 1회 한도 흐름을 다시 거쳐 종단 도달.
    feedback = result.get("feedback")
    assert feedback is not None, (
        "Self-RAG 1회 한도 후 sentinel 0.85 boost → continue → feedback 도달 기대"
    )
    assert feedback.used_llm == "stub"  # Story 3.5/3.6가 stub 보존
    # clarification 발동 X (sentinel boost로 clarify 분기 미진입).
    assert result.get("needs_clarification") is False
    # CR fix #1 BLOCKER 회귀 가드 — `force_llm_parse=True`가 정상 주입되어 parse_meal이
    # LLM 흐름을 거침. clean slate reset 후 정확히 1회 rewrite 발화.
    assert result.get("rewrite_attempts") == 1
    # node_errors 없음 — checkpoint의 user_id로 fetch_user_profile 정상 진행.
    assert result.get("node_errors", []) == []
    # CR m-9: AC10 — clarify→aresume 후 evaluate_fit이 정상 산출되어야 함
    # (fit_evaluation 미진행 incomplete_data가 아닌 정상 ok 경로).
    fe = result.get("fit_evaluation")
    assert fe is not None, "aresume 후 fit_evaluation 미산출 — incomplete_data 회귀"
    assert fe["fit_reason"] == "ok", f"aresume 후 fit_reason!=ok — {fe['fit_reason']}"
    assert fe["fit_label"] != "allergen_violation", (
        f"sentinel 흐름은 알레르기 X — fit_label={fe['fit_label']}"
    )
    assert 0 <= fe["fit_score"] <= 100


async def test_aresume_clean_slate_resets_state_fields(
    user_factory: UserFactory,
    analysis_service: AnalysisService,
) -> None:
    """Story 3.4 AC10 — aresume 시작 시 state가 clean slate로 reset 후 parse_meal 진입.

    CR fix #7 — 이전 `in (0, 1, 2)` (모든 가능값 포함) no-op assert를 정확한 값으로 교체.
    sentinel 입력으로 Self-RAG 1회 한도가 fire → 종단 도달 시 rewrite_attempts == 1
    (clean slate reset 후 정확히 1회 increment).
    """
    _ = await user_factory(profile_completed=True)
    thread_id = f"thread-clean-{uuid.uuid4()}"

    fake_variants = ClarificationVariants(options=[ClarificationOption(label="x", value="x")])

    with patch(
        "app.graph.nodes.request_clarification.generate_clarification_options",
        new=AsyncMock(return_value=fake_variants),
    ):
        # raw_text_clarified 키도 지원
        result = await analysis_service.aresume(
            thread_id=thread_id,
            user_input={"raw_text_clarified": "__test_low_confidence__"},
        )

    # 정확한 reset 검증: `aresume` 진입 시 rewrite_attempts=0 → sentinel 0.3 → rewrite +1
    # → sentinel 0.85 boost → continue. 종단 시 정확히 1.
    assert result.get("rewrite_attempts") == 1
    assert result.get("needs_clarification") is False
    assert result.get("clarification_options", []) == []
    # evaluation_decision 마지막 값 = "continue" (boost 후 종단).
    decision = result.get("evaluation_decision")
    assert decision is not None
    route = decision.route if hasattr(decision, "route") else decision.get("route")
    assert route == "continue"
