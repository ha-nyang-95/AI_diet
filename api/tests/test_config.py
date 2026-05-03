"""Story 3.4 — `app/core/config.py` Settings env override 검증 (AC11)."""

from __future__ import annotations

import pytest

from app.core.config import Settings


def test_food_retrieval_top_k_default() -> None:
    s = Settings()
    assert s.food_retrieval_top_k == 3


def test_clarification_max_options_default() -> None:
    s = Settings()
    assert s.clarification_max_options == 4


def test_food_retrieval_top_k_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOOD_RETRIEVAL_TOP_K", "10")
    s = Settings()
    assert s.food_retrieval_top_k == 10


def test_clarification_max_options_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLARIFICATION_MAX_OPTIONS", "2")
    s = Settings()
    assert s.clarification_max_options == 2
