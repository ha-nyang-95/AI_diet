"""Story 5.3 — PIPA Art.35 정보주체 권리(데이터 이전·열람권) 데이터 내보내기 SOT.

본 모듈은 *user-facing export*와 *purge dump*의 JSON shape SOT(Story 5.2 worker가
Story 5.3 시점에 본 service로 갈아끼움 — DF136 forward-hook 즉시 해소).

진입점:

1. ``collect_user_export_payload(session, user_id, *, include_soft_deleted_meals=False)``
   async function — 4 entity SELECT(user/consents/meals + selectinload analyses /
   notifications) + meals[i].analysis nested 매핑. user 미발견 시 ``None`` 반환
   (race로 hard-deleted 시 graceful).
2. ``serialize_payload_to_json_bytes(payload)`` — JSON wire bytes 변환
   (``ensure_ascii=False`` 한국어 보존, ``default=str`` fallback).
3. ``stream_csv_rows(payload)`` async generator — RFC 4180 escape + UTF-8 BOM
   + epics.md:820 한국어 헤더 SOT(*"날짜, 식사, 매크로, fit_score, 피드백 요약, 출처"*).

설계 정합:

- **JSON shape SOT 1지점** — Story 5.2 worker가 본 service ``collect_user_export_payload(
  ..., include_soft_deleted_meals=True)``를 호출(*전체 set* — meal_analyses 포함). endpoint는
  default ``False`` — 사용자 권리 행사는 *현재 활성 데이터*만(soft-deleted 명시 삭제 의도 정합).
- **N+1 회피** — meals SELECT에 ``selectinload(Meal.analysis)`` 명시(Story 4.3 SOT
  + Meal 모델 ``lazy="raise_on_sql"`` 가드와 호환). meals + analyses 단일 query 1세트.
- **Decimal 결정성** — ``format(d, 'f')`` scientific notation 차단(Story 5.2 CR P10 SOT).
- **CSV 결정성** — KST ``YYYY-MM-DD HH:MM`` 시각 + RFC 4180 doublequote escape +
  BOM 1회 prefix(첫 yield).

본 모듈은 *DB-only* — R2/외부 IO는 호출 측(worker는 별도 R2 upload 수행).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.consent import Consent
from app.db.models.meal import Meal
from app.db.models.notification import Notification
from app.db.models.user import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_KST = ZoneInfo("Asia/Seoul")

# epics.md:820 spec literal — 한국어 헤더 6 컬럼 SOT. CSV 첫 yield에 BOM과 함께 prefix.
_CSV_HEADER_COLUMNS: tuple[str, ...] = (
    "날짜",
    "식사",
    "매크로",
    "fit_score",
    "피드백 요약",
    "출처",
)
_UTF8_BOM = "﻿"

# Schema version — JSON dump 후속 호환성 SOT(외부 도구/외주 인수자가 shape 학습 시 단일 식별).
_SCHEMA_VERSION = "1.0"


def _serialize_value(v: Any) -> Any:
    """Decimal/UUID/datetime → JSON-safe primitive 변환 helper.

    Story 5.2 worker SOT 1:1 — 본 모듈로 이전 + worker는 import.

    - ``datetime`` → ``isoformat()`` (timezone-aware 그대로 보존).
    - ``uuid.UUID`` → ``str()``.
    - ``Decimal`` → ``format(d, 'f')`` (scientific notation 차단 — Story 5.2 CR P10).
    - 그 외(int/float/str/bool/None/list/dict/bytes 등) pass-through.
    """
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Decimal):
        return format(v, "f")
    return v


def _serialize_row(row: Any) -> dict[str, Any]:
    """ORM row → ``{column_name: serialized_value}`` 변환.

    ``row.__table__.columns`` iterate — relationship 컬럼은 skip(``__table__``은 컬럼만
    노출). 본 함수는 *flat row*만 직렬화 — nested(meal.analysis 등)는 호출 측에서 별도 매핑.
    """
    return {col.name: _serialize_value(getattr(row, col.name)) for col in row.__table__.columns}


async def collect_user_export_payload(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_soft_deleted_meals: bool = False,
) -> dict[str, Any] | None:
    """User 단일 export payload — 5 entity 매핑 (user/consents/meals + analyses/notifications).

    ``include_soft_deleted_meals``:
    - ``False`` (default — endpoint export): ``meals.deleted_at IS NULL`` 필터(현재 활성
      데이터만 — 사용자가 명시 삭제한 식단 제외).
    - ``True`` (worker purge dump): 모든 meals 포함(PIPA Art.21 30일 grace 사용자
      *전체 history* 회복 권리).

    User 미발견(race로 이미 hard-deleted) 시 ``None`` 반환 — caller가 dump skip + 명시
    경고 로그 분기. 빈 dict 반환은 truthy/falsy 가드와 의미 충돌 회피.

    payload shape — schema_version 1.0:
    ::
        {
            "user_id": "<uuid>",
            "exported_at": "<iso utc>",
            "schema_version": "1.0",
            "user": {<flat User row>},
            "consents": [{<flat Consent row>}, ...],
            "meals": [{...flat Meal row, "analysis": {...} | None}, ...],
            "notifications": [{<flat Notification row>}, ...]
        }
    """
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        return None

    consents = (
        (await session.execute(select(Consent).where(Consent.user_id == user_id))).scalars().all()
    )

    # Story 4.3 SOT 정합 — selectinload(Meal.analysis)로 N+1 회피. ``lazy="raise_on_sql"``
    # 가드와 호환(명시 selectinload 없으면 implicit lazy load 차단).
    meals_stmt = (
        select(Meal)
        .options(selectinload(Meal.analysis))
        .where(Meal.user_id == user_id)
        .order_by(Meal.ate_at)
    )
    if not include_soft_deleted_meals:
        meals_stmt = meals_stmt.where(Meal.deleted_at.is_(None))
    meals = (await session.execute(meals_stmt)).scalars().all()

    notifications = (
        (await session.execute(select(Notification).where(Notification.user_id == user_id)))
        .scalars()
        .all()
    )

    meals_serialized: list[dict[str, Any]] = []
    for meal in meals:
        row = _serialize_row(meal)
        # 1:1 nested — analysis row가 있으면 _serialize_row 변환, 없으면 None.
        analysis = meal.analysis  # selectinload으로 미리 로드됨(lazy load X).
        row["analysis"] = _serialize_row(analysis) if analysis is not None else None
        meals_serialized.append(row)

    return {
        "user_id": str(user.id),
        "exported_at": datetime.now(UTC).isoformat(),
        "schema_version": _SCHEMA_VERSION,
        "user": _serialize_row(user),
        "consents": [_serialize_row(c) for c in consents],
        "meals": meals_serialized,
        "notifications": [_serialize_row(n) for n in notifications],
    }


def serialize_payload_to_json_bytes(payload: dict[str, Any]) -> bytes:
    """Payload dict → UTF-8 JSON bytes.

    ``ensure_ascii=False`` — 한국어 raw_text/allergies/feedback_text 그대로 보존(외부
    도구 호환성 우선). ``default=str`` — Pydantic이 의외로 보낼 만한 타입(Decimal 등)도
    안전 fallback(이미 ``_serialize_value``가 1차 처리).
    """
    return json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")


# CSV formula injection 가드 — Excel/Google Sheets/LibreOffice가 첫 글자 ``=``/``+``/
# ``-``/``@``/``\t``/``\r``로 시작하는 셀을 *수식*으로 해석하는 클래식 CVE 패턴(CWE-1236).
# ``raw_text`` 등 사용자 입력이 직접 셀에 흐르므로 single-quote ``'`` prefix로 무력화 —
# OWASP 권고 mitigation. 복호화 시 사용자가 ``'`` 1글자만 인지(외부 도구에서 visible).
_CSV_FORMULA_TRIGGERS: frozenset[str] = frozenset({"=", "+", "-", "@", "\t", "\r"})


def _csv_escape(value: str) -> str:
    """RFC 4180 정합 escape + Excel formula injection 가드.

    1. 셀 첫 글자가 ``=``/``+``/``-``/``@``/``\\t``/``\\r``이면 ``'`` prefix(formula 무력화).
    2. ``,``/``"``/``\\n``/``\\r`` 포함 시 ``"``로 감싸고 내부 ``"``는 ``""`` escape.

    MS Excel + Google Sheets 호환 — 외부 도구 import 시점에 셀 분리/줄바꿈 안전 +
    악의 사용자 ``raw_text``로 인한 수식 실행 차단(CWE-1236, OWASP CSV injection).
    """
    if value and value[0] in _CSV_FORMULA_TRIGGERS:
        value = "'" + value
    if any(ch in value for ch in (",", '"', "\n", "\r")):
        escaped = value.replace('"', '""')
        return f'"{escaped}"'
    return value


def _format_meal_date_kst(ate_at_iso: str) -> str:
    """ISO datetime string → KST ``YYYY-MM-DD HH:MM``.

    ``_serialize_value``가 datetime을 ``isoformat()`` 문자열로 변환했으므로 본 함수도 string
    입력 — payload shape SOT 일관성 보존(JSON 직렬화 후 CSV 생성도 동일 분기).

    Naive datetime은 UTC로 가정(Postgres TZ-aware 컬럼이 UTC 저장 정합).
    """
    dt = datetime.fromisoformat(ate_at_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(_KST).strftime("%Y-%m-%d %H:%M")


def _format_macros(analysis: dict[str, Any] | None) -> str:
    """Analysis row → *"탄수 Cg·단백 Pg·지방 Fg·NNNkcal"* 한 줄 표현.

    analysis가 없거나 매크로 키 누락 시 빈 string. 매크로는 round int(외부 도구
    가독성 — 소수점 .0 노출 회피).
    """
    if analysis is None:
        return ""

    def _round(key: str) -> str:
        v = analysis.get(key)
        if v is None or v == "":
            return "0"
        try:
            return str(round(float(v)))
        except (TypeError, ValueError):
            return "0"

    return (
        f"탄수 {_round('carbohydrate_g')}g·"
        f"단백 {_round('protein_g')}g·"
        f"지방 {_round('fat_g')}g·"
        f"{_round('energy_kcal')}kcal"
    )


def _format_citations(analysis: dict[str, Any] | None) -> str:
    """Analysis row → ``"; "`` join citations(``doc_title (year)`` 형식).

    각 citation dict는 ``{source, doc_title, published_year}`` shape (Story 3.6 SOT).
    누락 키는 graceful skip — citations 배열 자체가 없으면 빈 string.
    """
    if analysis is None:
        return ""
    citations = analysis.get("citations") or []
    if not isinstance(citations, list):
        return ""
    parts: list[str] = []
    for c in citations:
        if not isinstance(c, dict):
            continue
        title = c.get("doc_title") or c.get("source") or ""
        year = c.get("published_year")
        if year is not None and year != "":
            parts.append(f"{title} ({year})")
        elif title:
            parts.append(str(title))
    return "; ".join(parts)


async def stream_csv_rows(payload: dict[str, Any]) -> AsyncIterator[str]:
    """payload → CSV row generator (BOM + 한국어 헤더 + meals 평면화 6 컬럼).

    epics.md:820 spec literal SOT — *"날짜, 식사, 매크로, fit_score, 피드백 요약, 출처"*
    헤더 + 줄바꿈 LF(``\\n`` not ``\\r\\n``). 1행 = 1 식단 입력(meal row), nested
    ``analysis``는 *flatten*(매크로/fit_score/feedback_summary/citations 4 컬럼으로 분해).

    첫 yield는 BOM(``\\ufeff``) + 헤더 — ``UTF-8 with BOM``으로 Excel 자동 인식. 이후
    meals 길이만큼 row yield(메모리 보호 — 1년치 ≥ 10K row도 memory profile 안전).
    meals가 없으면 헤더 1행 + 0 데이터 행.
    """
    header_line = ",".join(_CSV_HEADER_COLUMNS) + "\n"
    yield _UTF8_BOM + header_line

    meals = payload.get("meals") or []
    for meal in meals:
        if not isinstance(meal, dict):
            continue
        analysis = meal.get("analysis")  # dict | None
        ate_at = meal.get("ate_at") or ""
        date_str = _format_meal_date_kst(str(ate_at)) if ate_at else ""
        raw_text = str(meal.get("raw_text") or "")
        macros_str = _format_macros(analysis)
        fit_score_str = ""
        feedback_summary_str = ""
        if analysis is not None:
            fit_score_v = analysis.get("fit_score")
            fit_score_str = "" if fit_score_v is None else str(fit_score_v)
            feedback_summary_str = str(analysis.get("feedback_summary") or "")
        citations_str = _format_citations(analysis)

        row_cells = (
            _csv_escape(date_str),
            _csv_escape(raw_text),
            _csv_escape(macros_str),
            _csv_escape(fit_score_str),
            _csv_escape(feedback_summary_str),
            _csv_escape(citations_str),
        )
        yield ",".join(row_cells) + "\n"


__all__ = [
    "_serialize_row",
    "_serialize_value",
    "collect_user_export_payload",
    "serialize_payload_to_json_bytes",
    "stream_csv_rows",
]
