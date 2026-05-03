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

    CR fix #12 — `predicted_path` 측정 추가 (spec line 131 정합). retrieve_nutrition은
    path 분류를 직접 노출하지 않으므로 score + retrieved 결과로 추정:
    - retrieved 비어있음 → ``"none"`` (clarification 유도 케이스 baseline).
    - top-1 score == 1.0 → ``"alias_or_exact"`` (사전적 매칭).
    - top-1 score < 1.0 → ``"embedding"`` (HNSW fallback).
    expected_path와 비교한 분포 정확도는 *warn* 만 (90% 미달 fail X — 시드 분포 민감).

    Note — dev 환경에서는 mock LLM이라 accuracy 측정 불완전. staging/prod CI에서
    실 LLM + 실 food_nutrition 시드로 1회 측정 — 결과는 Story 3.8 LangSmith Dataset
    업로드 시 baseline.
    """
    import structlog

    from app.graph.deps import NodeDeps
    from app.graph.nodes.retrieve_nutrition import retrieve_nutrition
    from app.graph.state import FoodItem, MealAnalysisState
    from app.main import app

    logger = structlog.get_logger(__name__)

    deps = NodeDeps(
        session_maker=app.state.session_maker,
        redis=app.state.redis,
        settings=__import__("app.core.config", fromlist=["settings"]).settings,
    )

    correct = 0
    expected_path_counts: dict[str, int] = {}
    predicted_path_counts: dict[str, int] = {}
    path_match_counts: dict[str, int] = {}  # expected_path 별 path 일치 카운트
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
        retrieved = retrieval.retrieved_foods if retrieval is not None else []
        predicted_canonical = retrieved[0].name if retrieved else ""
        if predicted_canonical == row["expected_canonical"]:
            correct += 1

        # path 추정 — score 1.0이면 alias/exact, < 1.0이면 embedding, 빈 결과면 none.
        if not retrieved:
            predicted_path = "none"
        elif retrieved[0].score == 1.0:
            predicted_path = "alias_or_exact"
        else:
            predicted_path = "embedding"

        expected = row["expected_path"]
        expected_path_counts[expected] = expected_path_counts.get(expected, 0) + 1
        predicted_path_counts[predicted_path] = predicted_path_counts.get(predicted_path, 0) + 1
        # alias/exact는 같은 그룹으로 매칭(`alias_or_exact` 추정).
        normalized_expected = "alias_or_exact" if expected in ("alias", "exact") else expected
        if predicted_path == normalized_expected:
            path_match_counts[expected] = path_match_counts.get(expected, 0) + 1

    accuracy = correct / len(dataset) * 100.0

    # path 분포 정확도 — warn 로그만(KPI 외 — 시드 변화에 민감).
    path_accuracy = sum(path_match_counts.values()) / len(dataset) * 100.0 if dataset else 0.0
    logger.warning(
        "korean_foods_eval.path_distribution",
        expected=expected_path_counts,
        predicted=predicted_path_counts,
        path_accuracy_pct=round(path_accuracy, 1),
    )

    assert accuracy >= T3_ACCURACY_THRESHOLD, (
        f"T3 KPI 미달: accuracy {accuracy:.1f}% < {T3_ACCURACY_THRESHOLD}%. "
        f"expected: {expected_path_counts}, predicted: {predicted_path_counts}"
    )
