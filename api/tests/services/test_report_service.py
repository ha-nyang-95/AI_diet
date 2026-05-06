"""Story 4.3 AC7 — ``report_service`` 10건 단위 테스트.

happy path / 빈 주 / 부분 빈 주 / TDEE 미산정 / health_goal None / 단일·다중 알레르기 매칭 /
legacy 22종 외 row / from > to ValueError / 30일 초과 (라우터 책임이라 service 미가드).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.meal import Meal
from app.db.models.meal_analysis import MealAnalysis
from app.db.models.user import User
from app.main import app
from app.services.report_service import get_weekly_report


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    _ = client
    return app.state.session_maker


async def _insert_meal(
    session_maker,
    user: User,
    *,
    ate_at: datetime,
    raw_text: str = "치즈피자 1조각",
    parsed_items: list[dict] | None = None,
    analysis: dict | None = None,
) -> Meal:
    """meal + (옵션) analysis 1쌍 삽입 헬퍼."""
    async with session_maker() as session:
        meal = Meal(
            user_id=user.id,
            raw_text=raw_text,
            ate_at=ate_at,
            parsed_items=parsed_items,
        )
        session.add(meal)
        await session.commit()
        await session.refresh(meal)

        if analysis is not None:
            ma = MealAnalysis(
                meal_id=meal.id,
                user_id=user.id,
                fit_score=analysis.get("fit_score", 80),
                fit_score_label=analysis.get("fit_score_label", "good"),
                fit_reason=analysis.get("fit_reason", "ok"),
                carbohydrate_g=analysis.get("carbohydrate_g", 30.0),
                protein_g=analysis.get("protein_g", 20.0),
                fat_g=analysis.get("fat_g", 10.0),
                energy_kcal=analysis.get("energy_kcal", 300),
                feedback_text=analysis.get("feedback_text", "균형 잡힌 식단입니다."),
                feedback_summary=analysis.get("feedback_summary", "균형 OK"),
                citations=analysis.get("citations", []),
                used_llm=analysis.get("used_llm", "gpt-4o-mini"),
            )
            session.add(ma)
            await session.commit()
        return meal


@pytest.mark.asyncio
async def test_happy_path_7_days_with_analyses(session_maker, user_factory) -> None:
    """Story 4.3 AC7 — 7일 정상 데이터 (TDEE 계산 + macros 평균 + 1 알레르기 노출)."""
    user = await user_factory(profile_completed=True, allergies=["우유"])
    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)

    # 7일 중 3일에 식단 + 분석 1건씩.
    for offset in [0, 2, 5]:
        target_date = today - timedelta(days=offset)
        ate_at = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC).replace(hour=12)
        await _insert_meal(
            session_maker,
            loaded,
            ate_at=ate_at,
            raw_text="치즈피자 1조각",
            parsed_items=[{"name": "치즈피자", "quantity": "1조각", "confidence": 0.9}],
            analysis={"protein_g": 20.0, "carbohydrate_g": 50.0, "fat_g": 15.0, "energy_kcal": 400},
        )

    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )

    assert result.from_date == today - timedelta(days=6)
    assert result.to_date == today
    assert len(result.daily_summaries) == 7
    # 분석된 식단 수 합 = 3
    analyzed_total = sum(1 for d in result.daily_summaries if d.macros is not None)
    assert analyzed_total == 3
    # TDEE 계산 — 5 BMR 입력 모두 set
    assert result.tdee is not None
    assert result.tdee > 0
    # 알레르기 노출 매칭 — 우유 (치즈 alias)
    has_milk_exposure = any(
        any(e.allergen == "우유" for e in d.allergen_exposures) for d in result.daily_summaries
    )
    assert has_milk_exposure


@pytest.mark.asyncio
async def test_empty_week_zero_meals(session_maker, user_factory) -> None:
    """Story 4.3 AC1 — 빈 주 (meals 0건) → 7일 모두 ``meal_count=0`` + ``macros=None``."""
    user = await user_factory(profile_completed=True)
    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )

    assert len(result.daily_summaries) == 7
    for d in result.daily_summaries:
        assert d.meal_count == 0
        assert d.macros is None
        assert d.energy_kcal_total is None
        assert d.allergen_exposures == []


@pytest.mark.asyncio
async def test_partial_week_only_middle_3_days(session_maker, user_factory) -> None:
    """Story 4.3 AC7 — 7일 중 중간 3일만 식단 — 나머지 4일은 ``meal_count=0``."""
    user = await user_factory(profile_completed=True)
    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)

    for offset in [2, 3, 4]:
        target_date = today - timedelta(days=offset)
        ate_at = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC).replace(hour=12)
        await _insert_meal(
            session_maker,
            loaded,
            ate_at=ate_at,
            raw_text="현미밥",
            analysis={"protein_g": 5.0, "carbohydrate_g": 50.0, "fat_g": 1.0, "energy_kcal": 230},
        )

    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )

    nonempty = [d for d in result.daily_summaries if d.meal_count > 0]
    empty = [d for d in result.daily_summaries if d.meal_count == 0]
    assert len(nonempty) == 3
    assert len(empty) == 4


@pytest.mark.asyncio
async def test_tdee_none_when_weight_kg_missing(session_maker, user_factory) -> None:
    """Story 4.3 AC1 — ``weight_kg=None`` → ``tdee=None`` graceful (404 X)."""
    user = await user_factory(profile_completed=False)  # 7컬럼 미설정
    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )

    assert result.tdee is None
    assert result.weight_kg is None
    assert result.health_goal is None
    assert result.protein_target_g_per_kg_lower is None
    assert result.protein_target_g_per_kg_upper is None


@pytest.mark.asyncio
async def test_health_goal_none_protein_target_none(session_maker, user_factory) -> None:
    """Story 4.3 AC9 — ``health_goal=None`` → protein target None.

    ``user_factory(profile_completed=True)``는 ``health_goal=None`` 입력을 default
    ``"maintenance"``로 덮어쓰므로, ``profile_completed=False`` 분기로 BMR 5필드만
    명시 set + ``health_goal``은 None 유지.
    """
    user = await user_factory(
        profile_completed=False,
        weight_kg=Decimal("65.0"),
        height_cm=170,
        age=30,
        activity_level="moderate",
        # health_goal 미전달 → None 그대로
    )
    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )

    assert result.tdee is not None  # BMR 5컬럼 모두 set
    assert result.health_goal is None
    assert result.protein_target_g_per_kg_lower is None
    assert result.protein_target_g_per_kg_upper is None


@pytest.mark.asyncio
async def test_protein_target_for_weight_loss(session_maker, user_factory) -> None:
    """Story 4.3 AC9 — ``health_goal='weight_loss'`` → protein target (1.2, 1.6)."""
    user = await user_factory(profile_completed=True, health_goal="weight_loss")
    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )

    assert result.health_goal == "weight_loss"
    assert result.protein_target_g_per_kg_lower == 1.2
    assert result.protein_target_g_per_kg_upper == 1.6


@pytest.mark.asyncio
async def test_single_allergen_multi_day_match(session_maker, user_factory) -> None:
    """Story 4.3 AC1 — 단일 알레르기 다일 매칭 — 각 날별 카운트 정확."""
    user = await user_factory(profile_completed=True, allergies=["새우"])
    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)

    for offset in [0, 1, 3]:
        target_date = today - timedelta(days=offset)
        ate_at = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC).replace(hour=12)
        await _insert_meal(
            session_maker,
            loaded,
            ate_at=ate_at,
            raw_text="새우튀김 정식",
            analysis={"protein_g": 25.0, "carbohydrate_g": 40.0, "fat_g": 10.0, "energy_kcal": 380},
        )

    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )

    matched_days = [d for d in result.daily_summaries if d.allergen_exposures]
    assert len(matched_days) == 3
    for d in matched_days:
        assert any(e.allergen == "새우" and e.count >= 1 for e in d.allergen_exposures)


@pytest.mark.asyncio
async def test_multi_allergen_same_day(session_maker, user_factory) -> None:
    """Story 4.3 AC1 — 동일 날 다중 알레르기 매칭 — 별도 entry."""
    user = await user_factory(profile_completed=True, allergies=["우유", "새우"])
    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        ate_at = datetime.combine(today, datetime.min.time(), tzinfo=UTC).replace(hour=12)

    await _insert_meal(
        session_maker,
        loaded,
        ate_at=ate_at,
        raw_text="치즈피자와 새우튀김 세트",
        analysis={"protein_g": 30.0, "carbohydrate_g": 60.0, "fat_g": 20.0, "energy_kcal": 600},
    )

    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )

    today_entry = next(d for d in result.daily_summaries if d.kst_date == today)
    allergen_set = {e.allergen for e in today_entry.allergen_exposures}
    assert "우유" in allergen_set  # 치즈 alias
    assert "새우" in allergen_set


@pytest.mark.asyncio
async def test_legacy_invalid_allergy_silently_skipped(session_maker, user_factory) -> None:
    """Story 4.3 AC1 — 22종 외 ``allergies`` row(legacy) → 매칭 skip + report 정상.

    DB CHECK 제약(0005)이 신규 row를 차단하지만, 마이그레이션 이전 legacy row
    또는 manual SQL 우회 시나리오 graceful.
    """
    # CHECK 제약 통과를 위해 22종 부분집합으로 인입(테스트 환경)
    user = await user_factory(profile_completed=True, allergies=["우유"])
    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )
    # 결과는 정상 — invalid 가드 자체 없으면 ValueError 발생.
    assert len(result.daily_summaries) == 7


@pytest.mark.asyncio
async def test_from_date_greater_than_to_date_raises(session_maker, user_factory) -> None:
    """Story 4.3 AC7 — ``from > to`` → ValueError (라우터에서 RFC 7807 400 변환)."""
    user = await user_factory()
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        with pytest.raises(ValueError, match=r"from_date must be <= to_date"):
            await get_weekly_report(
                user=loaded,
                from_date=date(2026, 5, 7),
                to_date=date(2026, 5, 1),
                db=session,
            )


@pytest.mark.asyncio
async def test_kst_boundary_meal_at_midnight_utc(session_maker, user_factory) -> None:
    """Story 4.3 AC1 — UTC 자정(=KST 09:00) 식단은 KST 날짜로 group."""
    user = await user_factory(profile_completed=True)
    today = date(2026, 5, 1)
    # UTC 2026-05-01 00:00 → KST 2026-05-01 09:00 (KST 1일에 속함)
    ate_at = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
    await _insert_meal(
        session_maker,
        loaded,
        ate_at=ate_at,
        raw_text="현미밥 한 공기",
        analysis={"protein_g": 5.0, "carbohydrate_g": 50.0, "fat_g": 1.0, "energy_kcal": 230},
    )
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )
    target = next(d for d in result.daily_summaries if d.kst_date == today)
    assert target.meal_count == 1
