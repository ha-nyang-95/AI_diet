"""Story 4.3 AC1 — `/v1/reports/weekly` router 8건 단위 테스트.

- 401: 인증 토큰 부재
- 403: 기본 동의 미부여 (consent.basic.missing)
- 200: 빈 주 (meals 0건) + daily_summaries 7개 모두 빈 entry
- 200: happy path 부분 데이터 + macros / tdee / health_goal
- 400: from_date > to_date (reports.invalid_date_range)
- 400: (to-from) > 30일 초과 (reports.invalid_date_range)
- 422: from_date / to_date 누락 (Pydantic validation.error)
- 200: forward-compat — `insights` 필드는 항상 None
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.db.models.meal import Meal
from app.db.models.meal_analysis import MealAnalysis
from app.main import app
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_get_weekly_report_unauthenticated_401(client: AsyncClient) -> None:
    """인증 토큰 부재 → 401."""
    response = await client.get(
        "/v1/reports/weekly",
        params={"from_date": "2026-04-25", "to_date": "2026-05-01"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_weekly_report_no_consent_403(client: AsyncClient, user_factory) -> None:
    """기본 동의 미부여 사용자 → 403 + ``consent.basic.missing``."""
    user = await user_factory()
    response = await client.get(
        "/v1/reports/weekly",
        params={"from_date": "2026-04-25", "to_date": "2026-05-01"},
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "consent.basic.missing"


@pytest.mark.asyncio
async def test_get_weekly_report_empty_week_200(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """meals 0건 → 200 + 7-element ``daily_summaries`` 모두 빈 entry."""
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    response = await client.get(
        "/v1/reports/weekly",
        params={"from_date": "2026-04-25", "to_date": "2026-05-01"},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["from_date"] == "2026-04-25"
    assert body["to_date"] == "2026-05-01"
    assert len(body["daily_summaries"]) == 7
    for d in body["daily_summaries"]:
        assert d["meal_count"] == 0
        assert d["macros"] is None
        assert d["allergen_exposures"] == []
    # Story 4.4 type narrow — 빈 데이터 시 insights는 빈 list ([]), None 아님.
    assert body["insights"] == []
    # Story 4.3 CR DN-1 — ``users.sex`` 컬럼 부재로 TDEE 항상 None (Story 5.1 polish forward).
    assert body["tdee"] is None
    assert body["health_goal"] == "maintenance"


@pytest.mark.asyncio
async def test_get_weekly_report_happy_path_with_meals(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """일부 일자 식단 + 분석 → 200 + macros 평균 / energy_kcal 총합 노출."""
    user = await user_factory(profile_completed=True, allergies=["우유"])
    await consent_factory(user)

    today = date(2026, 5, 1)
    session_maker = app.state.session_maker
    async with session_maker() as session:
        ate_at = datetime.combine(today, datetime.min.time(), tzinfo=UTC).replace(hour=12)
        meal = Meal(
            user_id=user.id,
            raw_text="치즈피자 1조각",
            ate_at=ate_at,
            parsed_items=[{"name": "치즈피자", "quantity": "1조각", "confidence": 0.9}],
        )
        session.add(meal)
        await session.commit()
        await session.refresh(meal)
        ma = MealAnalysis(
            meal_id=meal.id,
            user_id=user.id,
            fit_score=70,
            fit_score_label="moderate",
            fit_reason="ok",
            carbohydrate_g=50.0,
            protein_g=20.0,
            fat_g=15.0,
            energy_kcal=400,
            feedback_text="치즈가 들어갔습니다.",
            feedback_summary="치즈 함유",
            citations=[],
            used_llm="gpt-4o-mini",
        )
        session.add(ma)
        await session.commit()

    response = await client.get(
        "/v1/reports/weekly",
        params={"from_date": str(today - timedelta(days=6)), "to_date": str(today)},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    today_str = str(today)
    today_entry = next(d for d in body["daily_summaries"] if d["kst_date"] == today_str)
    assert today_entry["meal_count"] == 1
    assert today_entry["macros"] is not None
    assert today_entry["macros"]["protein_g"] == 20.0
    assert today_entry["energy_kcal_total"] == 400.0
    # 알레르기 노출 — 우유(치즈 alias)
    assert any(
        e["allergen"] == "우유" and e["count"] == 1 for e in today_entry["allergen_exposures"]
    )


@pytest.mark.asyncio
async def test_get_weekly_report_invalid_date_range_400(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """``from_date > to_date`` → 400 + ``reports.invalid_date_range``."""
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    response = await client.get(
        "/v1/reports/weekly",
        params={"from_date": "2026-05-07", "to_date": "2026-05-01"},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "reports.invalid_date_range"


@pytest.mark.asyncio
async def test_get_weekly_report_range_exceeds_30_days_400(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """``(to-from) > 30일`` → 400 + ``reports.invalid_date_range``."""
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    response = await client.get(
        "/v1/reports/weekly",
        params={"from_date": "2026-01-01", "to_date": "2026-03-01"},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "reports.invalid_date_range"


@pytest.mark.asyncio
async def test_get_weekly_report_missing_query_params_400(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """``from_date``/``to_date`` 누락 → 400 (Pydantic ``validation.error``)."""
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    response = await client.get(
        "/v1/reports/weekly",
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation.error"


@pytest.mark.asyncio
async def test_get_weekly_report_insights_type_narrowed_to_list(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """Story 4.4 — ``insights`` 필드 type narrow ``list[InsightCard] | None``.

    빈 데이터 시 빈 list (None 아님). 정상 데이터 시 카드 list. None은 fetch 실패
    fallback(현 happy-path에서 미진입).
    """
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    response = await client.get(
        "/v1/reports/weekly",
        params={"from_date": "2026-04-25", "to_date": "2026-05-01"},
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert "insights" in body
    assert isinstance(body["insights"], list)
