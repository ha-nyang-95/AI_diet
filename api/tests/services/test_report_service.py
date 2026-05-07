"""Story 4.3 AC7 — ``report_service`` 단위 테스트 + CR 회귀 가드.

happy path / 빈 주 / 부분 빈 주 / TDEE 미산정 / health_goal None / 단일·다중 알레르기 매칭 /
legacy 22종 외 row / from > to / 30일 초과 / SQL 윈도우 필터 / negation false-positive.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.exceptions import WeeklyReportInvalidDateRangeError
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
    # Story 4.3 CR DN-1 — ``users.sex`` 컬럼 부재로 TDEE 항상 None (Story 5.1까지).
    assert result.tdee is None
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

    # Story 4.3 CR DN-1 — ``users.sex`` 컬럼 부재로 TDEE 항상 None.
    assert result.tdee is None
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
            parsed_items=[{"name": "새우튀김", "quantity": "1인분", "confidence": 0.92}],
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
        parsed_items=[
            {"name": "치즈피자", "quantity": "1조각", "confidence": 0.9},
            {"name": "새우튀김", "quantity": "1인분", "confidence": 0.85},
        ],
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
    """Story 4.3 CR P20 — 22종 외 ``allergies`` row(legacy) → 매칭 skip + report 정상.

    DB CHECK 제약(0005)이 신규 row를 차단하지만, 마이그레이션 이전 legacy row 또는
    manual SQL 우회 시나리오 graceful 가드. ORM 객체에 직접 invalid 라벨을 주입해
    실제 ``user_allergies_valid`` 필터 path를 통과하는지 검증(이전 vacuous 테스트
    교체 — 22종 부분집합만 인입하면 필터 분기가 미동작).
    """
    user = await user_factory(profile_completed=True, allergies=["우유"])
    today = date(2026, 5, 1)
    # 1차 세션에서 user 로드 + detach — autoflush가 invalid 라벨을 DB CHECK에 commit
    # 시도하지 않도록 expunge 후 in-memory만 인젝션.
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        session.expunge(loaded)
    loaded.allergies = ["우유", "legacy_invalid_label"]
    # 2차 세션은 detached user를 그대로 받음 — service는 ``user.allergies``만 읽고
    # ``user_allergies_valid`` 필터에서 invalid 라벨 자체적 skip.
    async with session_maker() as session:
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )
    # invalid 라벨이 매칭 시도 path에 들어가면 ``contains_allergen`` ValueError로
    # 500 발생 — 정상 응답이 곧 silently skip 동작 증거.
    assert len(result.daily_summaries) == 7


@pytest.mark.asyncio
async def test_from_date_greater_than_to_date_raises(session_maker, user_factory) -> None:
    """Story 4.3 CR P16 — ``from > to`` → ``WeeklyReportInvalidDateRangeError`` SOT.

    검증 SOT는 service. 라우터는 wrapper — typed exception이 글로벌 핸들러를 거쳐
    RFC 7807 ``code=reports.invalid_date_range`` 400 응답으로 변환.
    """
    user = await user_factory()
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        with pytest.raises(WeeklyReportInvalidDateRangeError):
            await get_weekly_report(
                user=loaded,
                from_date=date(2026, 5, 7),
                to_date=date(2026, 5, 1),
                db=session,
            )


@pytest.mark.asyncio
async def test_range_exceeds_30_days_raises(session_maker, user_factory) -> None:
    """Story 4.3 CR P16 — (to-from)>30일 가드는 service SOT (라우터 중복 가드 제거)."""
    user = await user_factory()
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        with pytest.raises(WeeklyReportInvalidDateRangeError):
            await get_weekly_report(
                user=loaded,
                from_date=date(2026, 1, 1),
                to_date=date(2026, 3, 1),  # 59일
                db=session,
            )


@pytest.mark.asyncio
async def test_sql_window_filter_excludes_out_of_range_meals(session_maker, user_factory) -> None:
    """Story 4.3 CR P1 — SQL ``ate_at`` UTC bracket 필터 → 윈도우 외 식단 미반영.

    이전 회귀: 사용자 전체 history를 Python에서 후필터 → NFR-P8 1.5초 무력화 +
    메모리 폭증. 본 테스트는 윈도우 외 식단을 7일 윈도우 합산에서 정확히 제외하는지
    검증(SQL 측 필터가 동작해야 윈도우 외 row가 ``daily_summaries``에 누설되지 않음).
    """
    user = await user_factory(profile_completed=True)
    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)

    # 윈도우 내(today): 1건
    in_window = datetime.combine(today, datetime.min.time(), tzinfo=UTC).replace(hour=12)
    await _insert_meal(
        session_maker,
        loaded,
        ate_at=in_window,
        raw_text="현미밥",
        analysis={"protein_g": 5.0, "carbohydrate_g": 50.0, "fat_g": 1.0, "energy_kcal": 230},
    )
    # 윈도우 밖(60일 전): 1건 — Python 측 KST 가드도 통과해야 SQL 필터 무관 reach.
    out_of_window = datetime.combine(
        today - timedelta(days=60), datetime.min.time(), tzinfo=UTC
    ).replace(hour=12)
    await _insert_meal(
        session_maker,
        loaded,
        ate_at=out_of_window,
        raw_text="라면",
        analysis={"protein_g": 8.0, "carbohydrate_g": 70.0, "fat_g": 15.0, "energy_kcal": 500},
    )

    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )

    total_meals = sum(d.meal_count for d in result.daily_summaries)
    assert total_meals == 1, "윈도우 밖 식단이 응답에 반영됨 (SQL 필터 미동작)"


@pytest.mark.asyncio
async def test_negation_text_does_not_count_as_exposure(session_maker, user_factory) -> None:
    """Story 4.3 CR DN-2 — ``feedback_text`` 부정문은 노출 카운트 X.

    Story 3.6 LLM 본문이 "우유는 들어있지 않아 안심하세요" 같은 negation을 포함하면
    이전 substring 매칭은 phantom 노출 카운트(우유 1건) 발생. negation marker 윈도우
    가드로 차단.
    """
    user = await user_factory(profile_completed=True, allergies=["우유"])
    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        ate_at = datetime.combine(today, datetime.min.time(), tzinfo=UTC).replace(hour=12)

    await _insert_meal(
        session_maker,
        loaded,
        ate_at=ate_at,
        raw_text="아메리카노 한 잔",  # raw_text는 매칭 입력 X (P2)
        parsed_items=[{"name": "아메리카노", "quantity": "1잔", "confidence": 0.95}],
        analysis={
            "protein_g": 0.5,
            "carbohydrate_g": 0.0,
            "fat_g": 0.0,
            "energy_kcal": 5,
            "feedback_text": "우유는 들어있지 않아 안심하고 드세요. 카페인 적정 수준.",
        },
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
    assert today_entry.allergen_exposures == [], (
        "negation marker 통과로 phantom 노출 카운트 발생 (DN-2 회귀)"
    )


# --- Story 4.4 — 인사이트 통합 (AC #3, #7) ---


@pytest.mark.asyncio
async def test_insights_field_present_in_response(session_maker, user_factory) -> None:
    """Story 4.4 AC7 — ``insights`` 필드가 항상 list (None 아님)."""
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
    # 빈 데이터 → 빈 list (None 아님).
    assert result.insights == []


@pytest.mark.asyncio
async def test_insights_protein_deficit_card_generated(session_maker, user_factory) -> None:
    """Story 4.4 AC3 — user macro_goal protein 25g × 3끼 = 75g 대비 평균 미달 시 카드 생성."""
    user = await user_factory(
        profile_completed=True,
        weight_kg=Decimal("60.0"),
        health_goal="weight_loss",
    )
    # macro_goal SET — DB UPDATE.
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        loaded.macro_goal = {"protein_target_g_per_meal": 25}
        await session.commit()

    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
    # 7일 중 3일에 식단 + 분석 — 평균 protein 20g/끼 < 75g(80% 미달).
    for offset in [0, 2, 5]:
        target_date = today - timedelta(days=offset)
        ate_at = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC).replace(hour=12)
        await _insert_meal(
            session_maker,
            loaded,
            ate_at=ate_at,
            raw_text="샐러드",
            analysis={"protein_g": 20.0, "carbohydrate_g": 30.0, "fat_g": 5.0, "energy_kcal": 200},
        )

    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )
    assert result.insights is not None
    kinds = [c.kind for c in result.insights]
    assert "protein_deficit" in kinds


@pytest.mark.asyncio
async def test_insights_total_cap_4(session_maker, user_factory) -> None:
    """Story 4.4 AC3 — 카드 총 cap 4."""
    user = await user_factory(profile_completed=True, allergies=["우유", "새우", "메밀"])
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        loaded.macro_goal = {
            "daily_calorie_target_kcal": 1800,
            "protein_target_g_per_meal": 25,
            "macro_ratio_carb_pct": 50,
            "macro_ratio_protein_pct": 25,
            "macro_ratio_fat_pct": 25,
        }
        await session.commit()

    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
    # 알레르기 다중 + macro 모두 drift 시나리오.
    for offset in range(7):
        target_date = today - timedelta(days=offset)
        ate_at = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC).replace(hour=12)
        await _insert_meal(
            session_maker,
            loaded,
            ate_at=ate_at,
            raw_text="치즈피자 + 새우튀김 + 메밀국수",
            parsed_items=[
                {"name": "치즈피자", "quantity": "1조각", "confidence": 0.9},
                {"name": "새우튀김", "quantity": "1인분", "confidence": 0.85},
                {"name": "메밀국수", "quantity": "1인분", "confidence": 0.85},
            ],
            analysis={
                "protein_g": 10.0,
                "carbohydrate_g": 200.0,
                "fat_g": 30.0,
                "energy_kcal": 2500,
            },
        )

    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )
    assert result.insights is not None
    assert len(result.insights) <= 4


@pytest.mark.asyncio
async def test_insights_no_macro_goal_kdris_protein_card(session_maker, user_factory) -> None:
    """Story 4.4 AC3 — macro_goal 미설정 시 KDRIs 우선순위 ②로 단백질 카드 생성."""
    user = await user_factory(
        profile_completed=True,
        weight_kg=Decimal("60.0"),
        health_goal="weight_loss",
    )
    today = date(2026, 5, 1)
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
    # 평균 protein 30g/일 (목표 60×1.2=72g, 41% — 80% 미달).
    for offset in range(7):
        target_date = today - timedelta(days=offset)
        ate_at = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC).replace(hour=12)
        await _insert_meal(
            session_maker,
            loaded,
            ate_at=ate_at,
            raw_text="현미밥",
            analysis={"protein_g": 30.0, "carbohydrate_g": 50.0, "fat_g": 1.0, "energy_kcal": 230},
        )
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        result = await get_weekly_report(
            user=loaded,
            from_date=today - timedelta(days=6),
            to_date=today,
            db=session,
        )
    assert result.insights is not None
    protein_card = next((c for c in result.insights if c.kind == "protein_deficit"), None)
    assert protein_card is not None
    assert "보건복지부 2020 KDRIs" in protein_card.citation


@pytest.mark.asyncio
async def test_insights_ad_guard_pass_clean_templates(session_maker, user_factory) -> None:
    """Story 4.4 AC9 — 정상 흐름 카드는 광고 가드 trigger 0건 (replaced_count=0)."""
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
    # 정상 카드 본문 inspecting — 광고 표현 미포함.
    for card in result.insights or []:
        assert "치료" not in card.title and "치료" not in card.body
        assert "처방" not in card.title and "처방" not in card.body


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
