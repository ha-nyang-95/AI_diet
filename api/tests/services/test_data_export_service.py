"""Story 5.3 AC1/AC7/AC9 — ``app.services.data_export_service`` 단위 테스트.

10건+ 시나리오:

1. ``_serialize_value`` Decimal scientific notation 차단(``format("f")``).
2. ``_serialize_value`` UUID/datetime/None pass-through.
3. ``_serialize_row`` ORM 객체 → flat dict 변환.
4. ``collect_user_export_payload`` user 미발견 → None.
5. ``collect_user_export_payload`` happy-path — 5 entity 매핑 + ``meals[i].analysis`` nested.
6. ``include_soft_deleted_meals=False`` → soft-deleted meal 제외.
7. ``include_soft_deleted_meals=True`` → soft-deleted meal 포함.
8. ``serialize_payload_to_json_bytes`` ensure_ascii=False(한국어 보존) + UTF-8.
9. ``stream_csv_rows`` 헤더 BOM + 한국어 6 컬럼 + LF.
10. ``stream_csv_rows`` row escape (RFC 4180 doublequote).
11. CSV ``날짜`` KST ``YYYY-MM-DD HH:MM`` 변환 회귀 가드.
12. CSV Decimal 결정성 회귀 가드(``0.000001`` → ``"0.000001"`` not scientific).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.meal import Meal
from app.db.models.meal_analysis import MealAnalysis
from app.db.models.notification import Notification
from app.db.models.user import User
from app.main import app
from app.services.data_export_service import (
    _csv_escape,
    _format_meal_date_kst,
    _serialize_row,
    _serialize_value,
    collect_user_export_payload,
    serialize_payload_to_json_bytes,
    stream_csv_rows,
)


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    _ = client
    return app.state.session_maker


# --- _serialize_value -------------------------------------------------------


def test_serialize_value_decimal_uses_format_f_not_scientific() -> None:
    """Story 5.2 CR P10 SOT — Decimal은 ``format(d, 'f')``로 scientific notation 차단.

    *Why*: ``str(Decimal("0.000001"))``는 ``"0.000001"``이지만, ``json.dumps`` 시 ``default=str``
    fallback과 별 무관하게 본 함수 SOT가 명시 변환. 회귀 시 외부 도구가 ``1e-6`` 같은
    scientific 표기를 numeric으로 인식 못하면 식단 데이터 분석 실패.
    """
    assert _serialize_value(Decimal("0.000001")) == "0.000001"
    assert _serialize_value(Decimal("70.5")) == "70.5"
    assert _serialize_value(Decimal("1234567890.123")) == "1234567890.123"


def test_serialize_value_uuid_to_string() -> None:
    """UUID → 표준 hex-with-hyphens string."""
    u = uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert _serialize_value(u) == "00000000-0000-0000-0000-000000000001"


def test_serialize_value_datetime_to_isoformat() -> None:
    """datetime tz-aware → isoformat, naive는 그대로 isoformat(tz suffix 없음)."""
    aware = datetime(2026, 5, 7, 15, 0, 0, tzinfo=UTC)
    assert _serialize_value(aware) == "2026-05-07T15:00:00+00:00"

    naive = datetime(2026, 5, 7, 15, 0, 0)
    # naive는 tz suffix 부재.
    assert _serialize_value(naive) == "2026-05-07T15:00:00"


def test_serialize_value_pass_through_primitives() -> None:
    """int/float/str/bool/None/list/dict 모두 pass-through(타입 변환 X)."""
    assert _serialize_value(None) is None
    assert _serialize_value(42) == 42
    assert _serialize_value(3.14) == 3.14
    assert _serialize_value("짜장면") == "짜장면"
    assert _serialize_value(True) is True
    assert _serialize_value([1, 2, 3]) == [1, 2, 3]
    assert _serialize_value({"a": 1}) == {"a": 1}


# --- _serialize_row ---------------------------------------------------------


async def test_serialize_row_user_orm_to_flat_dict(
    session_maker: async_sessionmaker,
    user_factory,
) -> None:
    """User ORM → flat dict (relationship 컬럼은 미포함 — ``__table__.columns`` only)."""
    user = await user_factory()
    async with session_maker() as session:
        loaded = await session.get(User, user.id)
        assert loaded is not None
        row = _serialize_row(loaded)
    # 핵심 컬럼 존재 + 타입 변환 정합.
    assert row["id"] == str(user.id)
    assert row["email"] == user.email
    assert isinstance(row["created_at"], str)  # datetime → isoformat string.
    # relationship 컬럼(meals/consents 등) 미포함 — __table__.columns만 iterate.
    assert "meals" not in row
    assert "analysis" not in row


# --- collect_user_export_payload --------------------------------------------


async def test_collect_user_export_payload_user_not_found_returns_none(
    session_maker: async_sessionmaker,
) -> None:
    """존재하지 않는 user_id → None(graceful, race로 hard-deleted 시 호출 분기)."""
    async with session_maker() as session:
        payload = await collect_user_export_payload(session, uuid.uuid4())
    assert payload is None


async def test_collect_user_export_payload_happy_full_set(
    session_maker: async_sessionmaker,
    user_factory,
    consent_factory,
) -> None:
    """5 entity(user/consents/meals + nested analysis/notifications) 모두 매핑.

    schema_version + exported_at + user_id 메타 동시 검증.
    """
    user = await user_factory(profile_completed=True)
    await consent_factory(user)

    async with session_maker() as session:
        meal = Meal(
            user_id=user.id,
            raw_text="짜장면 1인분",
            ate_at=datetime(2026, 5, 7, 12, 0, 0, tzinfo=UTC),
        )
        session.add(meal)
        await session.flush()
        analysis = MealAnalysis(
            meal_id=meal.id,
            user_id=user.id,
            fit_score=72,
            fit_score_label="good",
            fit_reason="ok",
            carbohydrate_g=Decimal("120.5"),
            protein_g=Decimal("18.0"),
            fat_g=Decimal("12.0"),
            energy_kcal=650,
            feedback_text="탄수가 다소 많습니다.",
            feedback_summary="탄수 비중 주의",
            citations=[{"source": "kdris", "doc_title": "KDRIs 2020", "published_year": 2020}],
            used_llm="gpt-4o-mini",
        )
        session.add(analysis)
        from datetime import date as _date

        notif = Notification(
            user_id=user.id,
            kind="unrecorded_meal",
            kst_date=_date(2026, 5, 7),
        )
        session.add(notif)
        await session.commit()

    async with session_maker() as session:
        payload = await collect_user_export_payload(session, user.id)

    assert payload is not None
    assert payload["schema_version"] == "1.0"
    assert payload["user_id"] == str(user.id)
    assert "exported_at" in payload
    # user flat dict.
    assert payload["user"]["email"] == user.email
    # consents 1건.
    assert len(payload["consents"]) == 1
    # meals 1건 + nested analysis.
    assert len(payload["meals"]) == 1
    meal_row = payload["meals"][0]
    assert meal_row["raw_text"] == "짜장면 1인분"
    assert meal_row["analysis"] is not None
    assert meal_row["analysis"]["fit_score"] == 72
    assert meal_row["analysis"]["feedback_summary"] == "탄수 비중 주의"
    # Decimal serialization 결정성.
    assert meal_row["analysis"]["carbohydrate_g"] == "120.5"
    # notifications 1건.
    assert len(payload["notifications"]) == 1


async def test_collect_user_export_payload_default_excludes_soft_deleted_meals(
    session_maker: async_sessionmaker,
    user_factory,
) -> None:
    """default ``include_soft_deleted_meals=False`` → ``meals.deleted_at IS NULL`` 만 응답.

    *Why*: endpoint export는 *현재 활성 데이터*만 — 사용자가 명시 삭제한 식단은 응답 미포함.
    """
    user = await user_factory()
    async with session_maker() as session:
        active_meal = Meal(user_id=user.id, raw_text="active meal")
        deleted_meal = Meal(
            user_id=user.id,
            raw_text="deleted meal",
            deleted_at=datetime.now(UTC) - timedelta(days=1),
        )
        session.add_all([active_meal, deleted_meal])
        await session.commit()

    async with session_maker() as session:
        payload = await collect_user_export_payload(session, user.id)

    assert payload is not None
    raw_texts = [m["raw_text"] for m in payload["meals"]]
    assert raw_texts == ["active meal"]


async def test_collect_user_export_payload_include_soft_deleted_meals_for_worker(
    session_maker: async_sessionmaker,
    user_factory,
) -> None:
    """``include_soft_deleted_meals=True`` (worker dump 흐름) → 모든 meals 포함.

    *Why*: PIPA Art.21 30일 grace 사용자 *전체 history* 회복 권리. worker는 본 키워드를
    True로 호출.
    """
    user = await user_factory()
    async with session_maker() as session:
        active_meal = Meal(user_id=user.id, raw_text="active meal")
        deleted_meal = Meal(
            user_id=user.id,
            raw_text="deleted meal",
            deleted_at=datetime.now(UTC) - timedelta(days=1),
        )
        session.add_all([active_meal, deleted_meal])
        await session.commit()

    async with session_maker() as session:
        payload = await collect_user_export_payload(
            session, user.id, include_soft_deleted_meals=True
        )

    assert payload is not None
    raw_texts = sorted(m["raw_text"] for m in payload["meals"])
    assert raw_texts == ["active meal", "deleted meal"]


# --- serialize_payload_to_json_bytes ---------------------------------------


def test_serialize_payload_to_json_bytes_preserves_korean_and_utf8() -> None:
    """``ensure_ascii=False`` 한국어 raw_text 그대로 + UTF-8 encoding."""
    payload = {"user_id": "u_01234567", "raw_text": "짜장면 1인분"}
    body = serialize_payload_to_json_bytes(payload)
    assert isinstance(body, bytes)
    decoded = body.decode("utf-8")
    assert "짜장면 1인분" in decoded
    # ensure_ascii=True였다면 \uXXXX escape이라 한국어 raw 부재.
    parsed = json.loads(decoded)
    assert parsed["raw_text"] == "짜장면 1인분"


# --- stream_csv_rows --------------------------------------------------------


async def test_stream_csv_rows_header_has_bom_korean_columns_lf() -> None:
    """헤더 1행: BOM + ``"날짜,식사,매크로,fit_score,피드백 요약,출처\\n"``."""
    payload = {"meals": []}
    chunks = []
    async for chunk in stream_csv_rows(payload):
        chunks.append(chunk)
    # 헤더만 yield(meals 0).
    assert len(chunks) == 1
    header = chunks[0]
    assert header.startswith("﻿")  # UTF-8 BOM
    assert "날짜,식사,매크로,fit_score,피드백 요약,출처\n" in header
    # CRLF X — LF only(epics.md:820 + RFC 4180 LF subset 정합).
    assert "\r\n" not in header


async def test_stream_csv_rows_row_doublequote_escape_rfc4180() -> None:
    """raw_text에 ``,`` 또는 ``"`` 포함 시 ``"``로 감싸고 내부 ``"`` → ``""``.

    *Why*: RFC 4180 — Excel + Google Sheets 셀 분리 안전.
    """
    payload = {
        "meals": [
            {
                "raw_text": '짜장면, 군만두"',
                "ate_at": "2026-05-07T15:00:00+00:00",
                "analysis": None,
            }
        ]
    }
    chunks = []
    async for chunk in stream_csv_rows(payload):
        chunks.append(chunk)
    # 헤더 + row 1건 = 2 chunk.
    assert len(chunks) == 2
    row = chunks[1]
    # 짜장면, 군만두" → "짜장면, 군만두"""
    assert '"짜장면, 군만두""' in row


async def test_stream_csv_rows_date_column_kst_format() -> None:
    """ate_at UTC ``2026-05-07T15:00:00+00:00`` → KST ``2026-05-08 00:00`` 변환.

    *Why*: 사용자 외부 도구 시각화는 KST 직관(epics.md:820 SOT).
    """
    payload = {
        "meals": [
            {
                "raw_text": "테스트 식사",
                "ate_at": "2026-05-07T15:00:00+00:00",
                "analysis": None,
            }
        ]
    }
    chunks = []
    async for chunk in stream_csv_rows(payload):
        chunks.append(chunk)
    row = chunks[1]
    # 2026-05-07 15:00 UTC = 2026-05-08 00:00 KST.
    assert "2026-05-08 00:00" in row


async def test_stream_csv_rows_macros_format_with_analysis() -> None:
    """analysis 있을 때 매크로 컬럼: ``"탄수 NNg·단백 NNg·지방 NNg·NNNkcal"``."""
    payload = {
        "meals": [
            {
                "raw_text": "테스트",
                "ate_at": "2026-05-07T03:00:00+00:00",
                "analysis": {
                    "carbohydrate_g": "120.6",
                    "protein_g": "18.0",
                    "fat_g": "12.0",
                    "energy_kcal": 650,
                    "fit_score": 72,
                    "feedback_summary": "탄수 비중 주의",
                    "citations": [{"doc_title": "KDRIs 2020", "published_year": 2020}],
                },
            }
        ]
    }
    chunks = []
    async for chunk in stream_csv_rows(payload):
        chunks.append(chunk)
    row = chunks[1]
    assert "탄수 121g·단백 18g·지방 12g·650kcal" in row  # Decimal "120.6" → round 121
    assert ",72," in row  # fit_score 컬럼.
    assert "탄수 비중 주의" in row
    assert "KDRIs 2020 (2020)" in row


# --- 추가 helper 가드 -------------------------------------------------------


def test_csv_escape_no_special_chars_pass_through() -> None:
    """특수문자 없는 일반 string은 quote 추가 없이 pass-through."""
    assert _csv_escape("짜장면") == "짜장면"
    assert _csv_escape("hello world") == "hello world"


def test_csv_escape_quote_doubles_internal_quote() -> None:
    assert _csv_escape('he said "hi"') == '"he said ""hi"""'


def test_format_meal_date_kst_naive_treated_as_utc() -> None:
    """naive datetime은 UTC 가정(Postgres TZ-aware 컬럼이 UTC 저장 정합)."""
    # naive 15:00 → UTC 15:00 → KST 24:00 = 익일 00:00.
    assert _format_meal_date_kst("2026-05-07T15:00:00") == "2026-05-08 00:00"
