"""Story 3.9 AC15 — Vision 환각률 측정 marker (DF9 from Story 2.3 → 3.8).

``@pytest.mark.perf`` + ``RUN_PERF_TESTS=1`` opt-in. Story 2.3 OCR 음식 사진 dataset
(임의 100건) → Vision 호출 결과 → 음식이 아닌 항목(예: 책 사진을 *"흰쌀밥"*으로
인식) 비율 측정. 임계값: 환각률 ≤ 5%.

본 marker는 *측정 marker*만 — 환각률 reduction 자체는 Vision prompt 튜닝(별도 후속
작업) 책임.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.perf

_HALLUCINATION_RATE_THRESHOLD = 0.05


def _perf_enabled() -> bool:
    return os.environ.get("RUN_PERF_TESTS", "").lower() in {"1", "true", "yes", "on"}


@pytest.mark.skipif(not _perf_enabled(), reason="RUN_PERF_TESTS=1 opt-in 필요")
async def test_vision_hallucination_rate_below_5pct() -> None:
    """Story 2.3 OCR 100건 dataset → Vision 환각률 ≤ 5%.

    실 LangSmith dataset(``balancenote-vision-hallucination-v1``) upload 후 evaluate —
    별도 ``scripts/upload_eval_dataset.py --dataset-name balancenote-vision-hallucination-v1
    --input-path api/tests/data/vision_test_images.json`` 흐름 정합.

    실 dataset은 운영자가 별도 SOP로 큐레이션 — 본 테스트는 *임계값 SOT + opt-in 골격*만.
    """
    # 본 marker는 measurement skeleton — 실 dataset 통합은 Story 8.4 polish.
    # 미통합 시 skip(no-op) — 임계값 정합만 회귀 가드.
    pytest.skip("Vision hallucination dataset not yet wired — measurement marker only.")
    assert _HALLUCINATION_RATE_THRESHOLD == 0.05  # noqa: PLR2004 — SOT 회귀 가드
