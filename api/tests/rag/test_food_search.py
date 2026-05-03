"""Story 3.4 — `app/rag/food/search.py` 단위 테스트 (AC4).

mock AsyncSession + monkeypatch ``embed_texts`` 기반 단위 테스트 — 실제 OpenAI / DB
도달 X. 통합(실 PG + 시드)은 ``test_food_search_performance.py`` (Story 3.1) +
``test_food_search_perf.py`` (Story 3.4 perf, AC13) 분담.

케이스:
- search_by_name — exact hit + 미스 + 빈 입력 + score 1.0 검증.
- search_by_embedding — HNSW top-K + score 정규화 0~1 + 빈 입력 graceful.
- compute_retrieval_confidence — single top-1 / multi min / 빈 리스트 → 0.0.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters import openai_adapter
from app.graph.state import RetrievedFood
from app.rag.food import search as food_search

# ---------------------------------------------------------------------------
# search_by_name
# ---------------------------------------------------------------------------


def _build_session_with_first(row: object) -> tuple[MagicMock, AsyncMock]:
    session = MagicMock()
    result = MagicMock()
    result.first.return_value = row
    execute_mock = AsyncMock(return_value=result)
    session.execute = execute_mock
    return session, execute_mock


async def test_search_by_name_exact_hit_returns_score_1() -> None:
    """exact 매칭 → score=1.0 + nutrition 매핑."""
    food_id = uuid.uuid4()
    row = MagicMock()
    row.id = food_id
    row.name = "짜장면"
    row.nutrition = {"energy_kcal": 700, "protein_g": 25}
    session, execute = _build_session_with_first(row)

    result = await food_search.search_by_name(session, "짜장면")
    assert result is not None
    assert result.name == "짜장면"
    assert result.food_id == food_id
    assert result.score == 1.0
    assert result.nutrition == {"energy_kcal": 700, "protein_g": 25}
    assert execute.await_count == 1


async def test_search_by_name_miss_returns_none() -> None:
    session, _ = _build_session_with_first(None)

    result = await food_search.search_by_name(session, "임의의_음식_xyz")
    assert result is None


async def test_search_by_name_empty_input_skips_db() -> None:
    session, execute = _build_session_with_first(None)

    assert await food_search.search_by_name(session, "") is None
    assert await food_search.search_by_name(session, "   ") is None
    assert execute.await_count == 0


# ---------------------------------------------------------------------------
# search_by_embedding
# ---------------------------------------------------------------------------


def _build_session_with_all(rows: list[object]) -> tuple[MagicMock, AsyncMock]:
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = rows
    execute_mock = AsyncMock(return_value=result)
    session.execute = execute_mock
    return session, execute_mock


def _row(food_id: uuid.UUID, name: str, distance: float) -> MagicMock:
    row = MagicMock()
    row.id = food_id
    row.name = name
    row.nutrition = {"energy_kcal": 100}
    row.distance = distance
    return row


async def test_search_by_embedding_returns_top_k_with_normalized_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HNSW top-K 결과 → distance ASC ordering + score 정규화 0~1."""
    f1, f2, f3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rows = [
        _row(f1, "짜장면", 0.0),  # exact distance 0 → score 1.0
        _row(f2, "짜파게티", 0.4),  # score = 1 - 0.4/2 = 0.8
        _row(f3, "간자장", 1.0),  # score = 0.5
    ]
    session, _ = _build_session_with_all(rows)
    monkeypatch.setattr(
        food_search,
        "embed_texts",
        AsyncMock(return_value=[[0.1] * 1536]),
    )

    result = await food_search.search_by_embedding(session, "짜장면", top_k=3)
    assert len(result) == 3
    assert [r.name for r in result] == ["짜장면", "짜파게티", "간자장"]
    assert result[0].score == pytest.approx(1.0)
    assert result[1].score == pytest.approx(0.8)
    assert result[2].score == pytest.approx(0.5)


async def test_search_by_embedding_score_clipped_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """distance > 2.0(이상치) → score 하한 0.0 clip."""
    rows = [_row(uuid.uuid4(), "anomaly", 2.5)]
    session, _ = _build_session_with_all(rows)
    monkeypatch.setattr(
        food_search,
        "embed_texts",
        AsyncMock(return_value=[[0.1] * 1536]),
    )
    result = await food_search.search_by_embedding(session, "anomaly")
    assert result[0].score == 0.0


async def test_search_by_embedding_empty_input_skips_db_and_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, execute = _build_session_with_all([])
    embed_mock = AsyncMock(return_value=[[0.1] * 1536])
    monkeypatch.setattr(food_search, "embed_texts", embed_mock)

    result = await food_search.search_by_embedding(session, "")
    assert result == []
    assert embed_mock.await_count == 0
    assert execute.await_count == 0


async def test_search_by_embedding_empty_index_graceful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _ = _build_session_with_all([])
    monkeypatch.setattr(
        food_search,
        "embed_texts",
        AsyncMock(return_value=[[0.1] * 1536]),
    )

    result = await food_search.search_by_embedding(session, "짜장면")
    assert result == []


async def test_search_by_embedding_uses_settings_top_k_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """top_k 미지정 → settings.food_retrieval_top_k 디폴트."""
    from app.core.config import settings as _settings

    monkeypatch.setattr(_settings, "food_retrieval_top_k", 5)
    session, execute = _build_session_with_all([])
    monkeypatch.setattr(
        food_search,
        "embed_texts",
        AsyncMock(return_value=[[0.1] * 1536]),
    )

    await food_search.search_by_embedding(session, "짜장면")
    # bindparams로 :k가 전달됨 — execute의 call_args에 5가 들어가는지 검증.
    call_args = execute.call_args
    bindparams = call_args.args[0].compile().params
    assert bindparams["k"] == 5


# ---------------------------------------------------------------------------
# compute_retrieval_confidence
# ---------------------------------------------------------------------------


def _rf(score: float) -> RetrievedFood:
    return RetrievedFood(name="x", food_id=None, score=score, nutrition={})


def test_compute_retrieval_confidence_empty_list_zero() -> None:
    assert food_search.compute_retrieval_confidence([]) == 0.0
    assert food_search.compute_retrieval_confidence([_rf(0.9)], expected_count=0) == 0.0


def test_compute_retrieval_confidence_single_item_top1() -> None:
    """expected_count=1 (디폴트) → matches[0].score (top-1)."""
    matches = [_rf(0.9), _rf(0.5), _rf(0.3)]
    assert food_search.compute_retrieval_confidence(matches) == pytest.approx(0.9)
    assert food_search.compute_retrieval_confidence(matches, expected_count=1) == pytest.approx(0.9)


def test_compute_retrieval_confidence_multi_item_min() -> None:
    """expected_count==len(matches)>1 → 최소값 (보수적)."""
    matches = [_rf(0.9), _rf(0.5), _rf(0.3)]
    assert food_search.compute_retrieval_confidence(matches, expected_count=3) == pytest.approx(0.3)


def test_compute_retrieval_confidence_missing_items_zero() -> None:
    """CR fix #3 — len(matches) < expected_count → 0.0 (missing implicit 0).

    multi-item meal에서 한 항목이 unmatched면 retrieved_foods 길이가 expected보다 작음
    → spec "보수적" 약속 준수: missing 항목의 0.0 confidence가 min 결정 → Self-RAG
    재검색 분기 보장.
    """
    matches = [_rf(0.95)]  # 1 matched, 2 expected → 1 missing
    assert food_search.compute_retrieval_confidence(matches, expected_count=2) == 0.0
    # 0 matched + N expected
    assert food_search.compute_retrieval_confidence([], expected_count=2) == 0.0


async def test_search_by_embedding_propagates_embedding_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """embed_texts가 raise — 본 함수는 그대로 propagate (호출자 wrapper 책임)."""
    session, _ = _build_session_with_all([])

    async def _raise(_: list[str]) -> list[list[float]]:
        from app.core.exceptions import MealOCRUnavailableError

        raise MealOCRUnavailableError("OPENAI_API_KEY missing")

    monkeypatch.setattr(food_search, "embed_texts", _raise)

    from app.core.exceptions import MealOCRUnavailableError

    with pytest.raises(MealOCRUnavailableError):
        await food_search.search_by_embedding(session, "짜장면")


# Re-export embed_texts module attribute reference — the test monkeypatches
# `food_search.embed_texts` to confirm the binding the module imported is what
# tests need to override.
def test_search_module_re_exports_embed_texts_alias() -> None:
    """sanity — search.py가 ``app.adapters.openai_adapter.embed_texts``를 모듈 attribute
    으로 보유 (monkeypatch 정합).
    """
    assert food_search.embed_texts is openai_adapter.embed_texts
