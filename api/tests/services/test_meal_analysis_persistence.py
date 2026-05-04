"""Story 3.7 — meal_analyses UPSERT helper 단위 테스트 (Task 16.8 / AC17)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.meals import MealMacros
from app.db.models.meal import Meal
from app.db.models.meal_analysis import MealAnalysis
from app.db.models.user import User
from app.graph.state import Citation
from app.main import app
from app.services.meal_analysis_persistence import upsert_meal_analysis
from app.services.sse_emitter import AnalysisDonePayload
from tests.conftest import UserFactory

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session(client: AsyncClient) -> AsyncIterator[AsyncSession]:
    _ = client
    session_maker = app.state.session_maker
    async with session_maker() as session:
        yield session


def _make_payload(
    meal_id: uuid.UUID, *, score: int = 75, llm: str = "gpt-4o-mini"
) -> AnalysisDonePayload:
    return AnalysisDonePayload(
        meal_id=meal_id,
        final_fit_score=score,
        fit_score_label="good",
        macros=MealMacros(carbohydrate_g=80.5, protein_g=25.2, fat_g=15.0, energy_kcal=580.0),
        feedback_text="## 평가\n단백질이 부족해요.\n## 다음 행동\n닭가슴살 100g 추가",
        citations_count=1,
        used_llm=llm,
    )


async def _ensure_user_meal(user: User) -> Meal:
    session_maker = app.state.session_maker
    async with session_maker() as session:
        meal = Meal(user_id=user.id, raw_text="테스트")
        session.add(meal)
        await session.commit()
        await session.refresh(meal)
        return meal


async def test_upsert_inserts_new_row(user_factory: UserFactory, db_session: AsyncSession) -> None:
    """첫 호출 — INSERT + commit + True 반환."""
    user = await user_factory()
    meal = await _ensure_user_meal(user)
    payload = _make_payload(meal.id, score=75)

    persisted = await upsert_meal_analysis(
        db_session,
        meal_id=meal.id,
        user_id=user.id,
        payload=payload,
        fit_reason="ok",
        citations=[Citation(source="MFDS", doc_title="알레르기 22종", published_year=2022)],
    )
    assert persisted is True

    # 별도 session으로 검증(commit이 정상 fire 됐는지 확인).
    session_maker = app.state.session_maker
    async with session_maker() as verify:
        rows = (
            (await verify.execute(select(MealAnalysis).where(MealAnalysis.meal_id == meal.id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].fit_score == 75
    assert rows[0].used_llm == "gpt-4o-mini"
    assert rows[0].citations == [
        {"source": "MFDS", "doc_title": "알레르기 22종", "published_year": 2022}
    ]
    # feedback_summary derive — "## 평가" 첫 문장 추출.
    assert rows[0].feedback_summary == "단백질이 부족해요."


async def test_upsert_updates_existing_row(
    user_factory: UserFactory, db_session: AsyncSession
) -> None:
    """동일 meal_id 재호출 — UPDATE 분기 + row count 1 유지."""
    user = await user_factory()
    meal = await _ensure_user_meal(user)
    # 1차 insert.
    await upsert_meal_analysis(
        db_session,
        meal_id=meal.id,
        user_id=user.id,
        payload=_make_payload(meal.id, score=50, llm="stub"),
        fit_reason="incomplete_data",
        citations=[],
    )
    # 2차 — score/llm 변경.
    persisted = await upsert_meal_analysis(
        db_session,
        meal_id=meal.id,
        user_id=user.id,
        payload=_make_payload(meal.id, score=85, llm="claude"),
        fit_reason="ok",
        citations=[Citation(source="KDA", doc_title="당뇨 가이드", published_year=2024)],
    )
    assert persisted is True

    session_maker = app.state.session_maker
    async with session_maker() as verify:
        rows = (
            (await verify.execute(select(MealAnalysis).where(MealAnalysis.meal_id == meal.id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].fit_score == 85
    assert rows[0].used_llm == "claude"
    assert rows[0].fit_reason == "ok"


async def test_upsert_preserves_created_at(
    user_factory: UserFactory, db_session: AsyncSession
) -> None:
    """CR Wave 1 #25 — UPSERT 시 created_at 보존(첫 분석 시점 영속) + updated_at은 갱신."""
    user = await user_factory()
    meal = await _ensure_user_meal(user)

    await upsert_meal_analysis(
        db_session,
        meal_id=meal.id,
        user_id=user.id,
        payload=_make_payload(meal.id, score=60),
        fit_reason="ok",
        citations=[],
    )
    session_maker = app.state.session_maker
    async with session_maker() as verify:
        first = (
            (await verify.execute(select(MealAnalysis).where(MealAnalysis.meal_id == meal.id)))
            .scalars()
            .one()
        )
    first_created_at = first.created_at
    first_updated_at = first.updated_at

    # 재분석 — UPSERT 분기 진입.
    await upsert_meal_analysis(
        db_session,
        meal_id=meal.id,
        user_id=user.id,
        payload=_make_payload(meal.id, score=80),
        fit_reason="ok",
        citations=[],
    )
    async with session_maker() as verify:
        second = (
            (await verify.execute(select(MealAnalysis).where(MealAnalysis.meal_id == meal.id)))
            .scalars()
            .one()
        )
    # created_at은 *불변*, updated_at은 *증가*.
    assert second.created_at == first_created_at
    assert second.updated_at >= first_updated_at


async def test_upsert_graceful_on_constraint_violation(
    user_factory: UserFactory, db_session: AsyncSession
) -> None:
    """잘못된 fit_reason(CHECK 위반) → False 반환 + 예외 swallow(graceful degradation)."""
    user = await user_factory()
    meal = await _ensure_user_meal(user)
    payload = _make_payload(meal.id)

    persisted = await upsert_meal_analysis(
        db_session,
        meal_id=meal.id,
        user_id=user.id,
        payload=payload,
        fit_reason="invalid_reason_value",  # CHECK 제약 위반 — DB가 거부.
        citations=[],
    )
    assert persisted is False  # graceful — 예외 swallow.

    # row가 INSERT 되지 않았는지 검증.
    session_maker = app.state.session_maker
    async with session_maker() as verify:
        rows = (
            (await verify.execute(select(MealAnalysis).where(MealAnalysis.meal_id == meal.id)))
            .scalars()
            .all()
        )
    assert len(rows) == 0


async def test_upsert_citations_jsonb_roundtrip(
    user_factory: UserFactory, db_session: AsyncSession
) -> None:
    """citations JSONB 직렬화/역직렬화 정합 — published_year=None도 round-trip 가능."""
    user = await user_factory()
    meal = await _ensure_user_meal(user)
    citations = [
        Citation(source="MOHW", doc_title="2020 KDRIs", published_year=2020),
        Citation(source="KDCA", doc_title="식단 가이드", published_year=None),
    ]
    await upsert_meal_analysis(
        db_session,
        meal_id=meal.id,
        user_id=user.id,
        payload=_make_payload(meal.id),
        fit_reason="ok",
        citations=citations,
    )
    session_maker = app.state.session_maker
    async with session_maker() as verify:
        row = (
            await verify.execute(select(MealAnalysis).where(MealAnalysis.meal_id == meal.id))
        ).scalar_one()
    assert row.citations == [
        {"source": "MOHW", "doc_title": "2020 KDRIs", "published_year": 2020},
        {"source": "KDCA", "doc_title": "식단 가이드", "published_year": None},
    ]


async def test_upsert_feedback_summary_truncated_to_120_chars(
    user_factory: UserFactory, db_session: AsyncSession
) -> None:
    """feedback_summary 120자 cap — DB CHECK 통과 + derive helper truncate 정합."""
    user = await user_factory()
    meal = await _ensure_user_meal(user)
    long_text = "## 평가\n" + "가" * 200
    payload = AnalysisDonePayload(
        meal_id=meal.id,
        final_fit_score=60,
        fit_score_label="good",
        macros=MealMacros(carbohydrate_g=0, protein_g=0, fat_g=0, energy_kcal=0),
        feedback_text=long_text,
        citations_count=0,
        used_llm="stub",
    )

    persisted = await upsert_meal_analysis(
        db_session,
        meal_id=meal.id,
        user_id=user.id,
        payload=payload,
        fit_reason="ok",
        citations=[],
    )
    assert persisted is True

    session_maker = app.state.session_maker
    async with session_maker() as verify:
        row = (
            await verify.execute(select(MealAnalysis).where(MealAnalysis.meal_id == meal.id))
        ).scalar_one()
    assert len(row.feedback_summary) <= 120
    assert row.feedback_summary.endswith("...")
