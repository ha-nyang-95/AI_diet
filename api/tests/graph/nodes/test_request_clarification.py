"""Story 3.4 — `request_clarification` 노드 단위 테스트 (AC9).

mock generate_clarification_options — OpenAI 도달 X.

케이스:
1. parsed_items[0].name 기반 옵션 생성 + needs_clarification=True 반환,
2. 빈 parsed_items + raw_text fallback,
3. clarification_max_options 상한 truncate,
4. graceful 빈 옵션 → fallback 1건 강제.
"""

from __future__ import annotations

import sys
import uuid
from unittest.mock import AsyncMock

import pytest

from app.adapters.openai_adapter import ClarificationVariants
from app.graph.deps import NodeDeps
from app.graph.nodes.request_clarification import request_clarification
from app.graph.state import ClarificationOption, FoodItem, MealAnalysisState

request_module = sys.modules["app.graph.nodes.request_clarification"]


def _state(*, parsed: list[FoodItem] | None = None, raw_text: str = "") -> MealAnalysisState:
    return {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": raw_text,
        "parsed_items": parsed if parsed is not None else [],
        "rewrite_attempts": 1,
        "node_errors": [],
    }


async def test_request_clarification_generates_options_from_parsed_name(
    fake_deps: NodeDeps,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """parsed_items[0].name → 3 옵션 + needs_clarification=True."""
    variants = ClarificationVariants(
        options=[
            ClarificationOption(label="연어 포케", value="연어 포케 1인분"),
            ClarificationOption(label="참치 포케", value="참치 포케 1인분"),
            ClarificationOption(label="베지 포케", value="베지 포케 1인분"),
        ]
    )
    llm_mock = AsyncMock(return_value=variants)
    monkeypatch.setattr(request_module, "generate_clarification_options", llm_mock)

    state = _state(parsed=[FoodItem(name="포케볼", confidence=0.5)])
    out = await request_clarification(state, deps=fake_deps)

    assert out["needs_clarification"] is True
    assert len(out["clarification_options"]) == 3
    # dict 형태 (model_dump) — LangGraph dict-merge 정합.
    assert out["clarification_options"][0] == {
        "label": "연어 포케",
        "value": "연어 포케 1인분",
    }
    # parsed_items[0].name = "포케볼"이 LLM 입력으로 전달되었는지.
    assert llm_mock.await_args.args[0] == "포케볼"


async def test_request_clarification_fallback_to_raw_text_when_parsed_empty(
    fake_deps: NodeDeps,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """빈 parsed_items → raw_text 사용."""
    variants = ClarificationVariants(options=[ClarificationOption(label="x", value="x")])
    llm_mock = AsyncMock(return_value=variants)
    monkeypatch.setattr(request_module, "generate_clarification_options", llm_mock)

    state = _state(parsed=[], raw_text="포케볼")
    await request_clarification(state, deps=fake_deps)
    assert llm_mock.await_args.args[0] == "포케볼"


async def test_request_clarification_max_options_truncate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """settings.clarification_max_options=2로 monkeypatch — 4개 응답이라도 2개 truncate."""
    from unittest.mock import MagicMock

    from app.core.config import settings as _real

    settings_proxy = MagicMock(wraps=_real)
    settings_proxy.clarification_max_options = 2
    deps = NodeDeps(session_maker=MagicMock(), redis=None, settings=settings_proxy)

    variants = ClarificationVariants(
        options=[
            ClarificationOption(label="opt1", value="opt1"),
            ClarificationOption(label="opt2", value="opt2"),
            ClarificationOption(label="opt3", value="opt3"),
            ClarificationOption(label="opt4", value="opt4"),
        ]
    )
    monkeypatch.setattr(
        request_module, "generate_clarification_options", AsyncMock(return_value=variants)
    )

    state = _state(parsed=[FoodItem(name="포케볼", confidence=0.5)])
    out = await request_clarification(state, deps=deps)
    assert len(out["clarification_options"]) == 2
    assert out["clarification_options"][0]["label"] == "opt1"


async def test_request_clarification_graceful_empty_options_forces_fallback(
    fake_deps: NodeDeps,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM이 빈 옵션 응답 — Pydantic min_length=1로 인해 1건 강제 입력 가능.

    호출자 책임 케이스: max_options=0이거나 fall-through로 빈 리스트가 들어올 때
    fallback 1건 강제 (UI 깨짐 방지). max_options를 0으로 monkeypatch — 노드 자체가
    `max(1, max_options)`로 1건 강제.
    """
    from unittest.mock import MagicMock

    from app.core.config import settings as _real

    settings_proxy = MagicMock(wraps=_real)
    settings_proxy.clarification_max_options = 0  # 0 → max(1, 0) = 1로 강제
    deps = NodeDeps(session_maker=MagicMock(), redis=None, settings=settings_proxy)

    variants = ClarificationVariants(
        options=[ClarificationOption(label="something", value="something_v")]
    )
    monkeypatch.setattr(
        request_module, "generate_clarification_options", AsyncMock(return_value=variants)
    )

    state = _state(parsed=[FoodItem(name="포케볼", confidence=0.5)])
    out = await request_clarification(state, deps=deps)
    # max(1, 0) = 1 — 1건 truncate.
    assert len(out["clarification_options"]) == 1


# ---------------------------------------------------------------------------
# CR fix #4 — LLM 영구 실패 시 self-fallback (UI dead state 차단)
# ---------------------------------------------------------------------------


async def test_request_clarification_llm_failure_self_fallback(
    fake_deps: NodeDeps,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM이 영구 실패해도 노드 자체가 `needs_clarification=True` + 1건 옵션 contract
    를 보장. wrapper fallback이 신호 없는 dead state로 빠지지 않도록 self-guarantee.
    """
    from app.core.exceptions import MealOCRUnavailableError

    async def _raise(_: str) -> None:
        raise MealOCRUnavailableError("LLM permanent failure")

    monkeypatch.setattr(request_module, "generate_clarification_options", _raise)

    state = _state(parsed=[FoodItem(name="포케볼", confidence=0.5)])
    out = await request_clarification(state, deps=fake_deps)

    assert out["needs_clarification"] is True
    assert len(out["clarification_options"]) == 1
    # fallback option은 입력 name을 value로 보존 — UI에서 사용자가 재입력 유도.
    assert out["clarification_options"][0]["value"] == "포케볼"


# ---------------------------------------------------------------------------
# CR fix #6 — checkpointer round-trip 후 parsed_items가 list[dict] 형태일 때 안전 access
# ---------------------------------------------------------------------------


async def test_request_clarification_handles_dict_form_parsed_items(
    fake_deps: NodeDeps,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`parsed_items`가 LangGraph checkpointer round-trip 후 list[dict]로 deserialize
    되는 케이스 — `get_state_field` helper로 양 형태 안전 access (Story 3.3 SOT 정합).
    """
    variants = ClarificationVariants(
        options=[ClarificationOption(label="연어 포케", value="연어 포케 1인분")]
    )
    llm_mock = AsyncMock(return_value=variants)
    monkeypatch.setattr(request_module, "generate_clarification_options", llm_mock)

    # Pydantic instance가 아닌 *dict 형태* parsed_items — type ignore (TypedDict 우회)
    state: MealAnalysisState = {  # type: ignore[typeddict-item]
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "fallback",
        "parsed_items": [{"name": "포케볼", "quantity": "1인분", "confidence": 0.5}],  # type: ignore[list-item]
        "rewrite_attempts": 1,
        "node_errors": [],
    }
    out = await request_clarification(state, deps=fake_deps)
    # AttributeError 없이 정상 처리 + LLM에 "포케볼" 전달.
    assert out["needs_clarification"] is True
    assert llm_mock.await_args.args[0] == "포케볼"
