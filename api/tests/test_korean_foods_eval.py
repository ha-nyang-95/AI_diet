"""Story 3.4 — T3 KPI eval 테스트 (한식 100건 정확도 ≥ 90%, AC12).

`@pytest.mark.eval` 디폴트 skip — ``RUN_EVAL_TESTS=1`` opt-in. dev에서는 mock LLM 사용
(결정성 응답 — accuracy 측정 불완전), staging/prod CI에서 *실 LLM* + 실
``food_nutrition`` 시드로 1회 측정 — 결과는 LangSmith Dataset(Story 3.8) 업로드 시
baseline.

본 스토리의 *통과 기준*:
- 데이터셋 SOT 박힘 (`korean_foods_100.json` — AC11),
- 측정 인프라 박힘 (`@pytest.mark.eval` skip default + RUN_EVAL_TESTS 게이트),
- 실 90% 측정은 Story 3.8 W3 슬롯에서 LangSmith eval로 검증.

흐름:
1. ``korean_foods_100.json`` 로드,
2. 각 행 ``input``을 ``analysis_service.run`` 또는 ``retrieve_nutrition`` 직접 호출,
3. 예측 ``predicted_canonical`` + ``predicted_path`` 산출,
4. accuracy = sum(predicted_canonical == expected_canonical) / 100 * 100,
5. assert accuracy ≥ 90% (T3 KPI 정합).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

DATASET_PATH = Path(__file__).parent / "data" / "korean_foods_100.json"

T3_ACCURACY_THRESHOLD: float = 90.0
"""T3 KPI 통과 기준 — 정확도 ≥ 90% (prd.md line 157, 550-555 정합)."""


pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        os.environ.get("RUN_EVAL_TESTS", "").strip() not in {"1", "true", "True"},
        reason="eval test skipped by default — set RUN_EVAL_TESTS=1 to enable",
    ),
]


@pytest.fixture(scope="module")
def dataset() -> list[dict[str, str]]:
    with DATASET_PATH.open(encoding="utf-8") as f:
        return json.load(f)


async def test_korean_foods_t3_accuracy_threshold(
    dataset: list[dict[str, str]],
    client: object,  # noqa: ARG001 - lifespan 활성화 필요
) -> None:
    """100건 ``input`` → ``retrieve_nutrition`` 직접 호출 → ``predicted_canonical`` 산출 →
    accuracy ≥ 90% (T3 KPI 정합).

    Note — dev 환경에서는 mock LLM이라 accuracy 측정 불완전. staging/prod CI에서
    실 LLM + 실 food_nutrition 시드로 1회 측정 — 결과는 Story 3.8 LangSmith Dataset
    업로드 시 baseline.
    """
    from app.graph.deps import NodeDeps
    from app.graph.nodes.retrieve_nutrition import retrieve_nutrition
    from app.graph.state import FoodItem, MealAnalysisState
    from app.main import app

    deps = NodeDeps(
        session_maker=app.state.session_maker,
        redis=app.state.redis,
        settings=__import__("app.core.config", fromlist=["settings"]).settings,
    )

    correct = 0
    path_distribution: dict[str, int] = {}
    for row in dataset:
        state: MealAnalysisState = {
            "meal_id": __import__("uuid").uuid4(),
            "user_id": __import__("uuid").uuid4(),
            "raw_text": row["input"],
            "parsed_items": [FoodItem(name=row["input"], confidence=0.9)],
            "rewrite_attempts": 0,
            "node_errors": [],
        }
        out = await retrieve_nutrition(state, deps=deps)
        retrieval = out.get("retrieval")
        if retrieval is None:
            continue
        retrieved = retrieval.retrieved_foods
        predicted_canonical = retrieved[0].name if retrieved else ""
        if predicted_canonical == row["expected_canonical"]:
            correct += 1
        path_distribution[row["expected_path"]] = path_distribution.get(row["expected_path"], 0) + 1

    accuracy = correct / len(dataset) * 100.0
    assert accuracy >= T3_ACCURACY_THRESHOLD, (
        f"T3 KPI 미달: accuracy {accuracy:.1f}% < {T3_ACCURACY_THRESHOLD}%. "
        f"분포: {path_distribution}"
    )
