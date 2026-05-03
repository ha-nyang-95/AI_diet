"""Story 3.4 — `tests/data/korean_foods_100.json` 데이터셋 검증 (AC11).

검증:
1. JSON schema — 100 행, 각 행 4 필드(input/expected_canonical/expected_path/category).
2. expected_path 분류 분포 — alias ≥ 25, exact ≥ 25, embedding ≥ 20, clarification ≥ 5.
3. 시드된 ``food_nutrition.name``에 ``expected_canonical`` 모두 존재 — orphan 차단
   (CI 시드 후 강제, dev/test 환경에선 옵션 — Story 3.1 시드 의존 통합 테스트).
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest

DATASET_PATH = Path(__file__).parent / "data" / "korean_foods_100.json"
EXPECTED_PATHS = {"alias", "exact", "embedding", "clarification"}
EXPECTED_FIELDS = {"input", "expected_canonical", "expected_path", "category"}

# 분포 임계값(스펙 정합 — alias ≥ 25, exact ≥ 25, embedding ≥ 20, clarification ≥ 5).
MIN_DISTRIBUTION = {
    "alias": 25,
    "exact": 25,
    "embedding": 20,
    "clarification": 5,
}


@pytest.fixture(scope="module")
def dataset() -> list[dict[str, str]]:
    with DATASET_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def test_dataset_has_100_rows(dataset: list[dict[str, str]]) -> None:
    """spec line 123 — 100건 정합."""
    assert len(dataset) == 100


def test_dataset_each_row_has_required_fields(dataset: list[dict[str, str]]) -> None:
    """각 행 4 필드 — 잘못된 schema 회귀 차단."""
    for i, row in enumerate(dataset):
        assert set(row.keys()) == EXPECTED_FIELDS, f"row {i} fields mismatch: {row}"
        assert isinstance(row["input"], str) and row["input"]
        assert isinstance(row["expected_canonical"], str) and row["expected_canonical"]
        assert row["expected_path"] in EXPECTED_PATHS
        assert isinstance(row["category"], str) and row["category"]


def test_dataset_path_distribution(dataset: list[dict[str, str]]) -> None:
    """expected_path 분포 — 다양성 보장 (T3 KPI 회귀 데이터셋)."""
    counts = Counter(row["expected_path"] for row in dataset)
    for path, min_count in MIN_DISTRIBUTION.items():
        assert counts[path] >= min_count, (
            f"path '{path}' count {counts[path]} below minimum {min_count}"
        )


def test_dataset_inputs_unique(dataset: list[dict[str, str]]) -> None:
    """input 중복 차단 — accuracy 측정 데이터셋 무결성."""
    inputs = [row["input"] for row in dataset]
    assert len(set(inputs)) == len(inputs), (
        f"duplicates: {[item for item, c in Counter(inputs).items() if c > 1]}"
    )


@pytest.mark.skipif(
    os.environ.get("RUN_DATASET_SEED_CHECK", "").strip() not in {"1", "true", "True"},
    reason="dataset seed orphan check skipped by default — set RUN_DATASET_SEED_CHECK=1",
)
async def test_dataset_canonical_names_exist_in_food_nutrition(
    dataset: list[dict[str, str]],
    client: object,  # noqa: ARG001 - 사용 안 하지만 lifespan 활성화 필요
) -> None:
    """시드된 ``food_nutrition.name``에 ``expected_canonical`` 모두 존재 검증.

    ``RUN_DATASET_SEED_CHECK=1``로 게이트 — Story 3.1 시드 후 CI에서만 강제.
    dev/test에서는 시드 부재 또는 부분 시드라 skip 디폴트.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models.food_nutrition import FoodNutrition
    from app.main import app

    canonicals = {row["expected_canonical"] for row in dataset}
    session_maker: async_sessionmaker = app.state.session_maker

    async with session_maker() as session:
        stmt = select(FoodNutrition.name).where(FoodNutrition.name.in_(canonicals))
        result = await session.execute(stmt)
        existing = {r[0] for r in result.all()}

    missing = canonicals - existing
    assert not missing, f"orphan canonicals (not seeded): {sorted(missing)[:10]}"
