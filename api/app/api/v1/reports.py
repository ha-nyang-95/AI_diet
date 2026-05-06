"""``/v1/reports`` — Web 주간 리포트 + (Story 4.4 forward-compat) 인사이트 API — Story 4.3.

1 endpoint:

- ``GET /weekly?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD`` — 7일 매크로/칼로리/단백질/
  알레르기 노출 aggregation. ``from_date``/``to_date`` 모두 필수(클라이언트가 KST
  ``today - 6일 ~ today``를 명시 송신).

핵심 결정:

- *조회 경로*이지만 ``Depends(require_basic_consents)``를 wire — 작성 경로의 실 데이터
  (``meals.parsed_items``, ``meal_analyses.feedback_text``)를 *aggregate해 노출*하므로
  PIPA Art.35 정보주체 권리 정합과 별개로 *기본 동의 미부여 사용자에게 가공된 통계가
  나가는 우회로*를 차단(자기 데이터 조회는 보장하되, *분석 결과 가공물*은 동의 후 노출).
- ``automated_decision`` 게이트는 *불필요* — 본 endpoint는 LLM 호출 0건. 이미 LLM
  호출 시점(Story 3.6 ``analysis_service``)에서 동의 검증 통과한 결과를 단순 aggregate
  (FR7 정합).
- 단일 SQL LEFT JOIN(``meals`` + ``meal_analyses``)로 N+1 회피(Story 3.7 ``selectinload``
  패턴 정합) — NFR-P8 1.5초 baseline.
- Pydantic 응답 모델(``WeeklyReportResponse`` 등)은 ``services/report_service.py`` SOT
  — 본 라우터는 import만(순환 의존성 회피).

신규 RFC 7807 ``code`` 카탈로그:

- ``reports.invalid_date_range`` — ``from_date > to_date`` 또는 (to-from)>30일 초과.

NFR-S5 마스킹: structlog 이벤트는 ``service/report_service.py``가 SOT — 본 라우터는
endpoint 진입/종료 로그 X(서비스 책임 분리).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_basic_consents
from app.core.exceptions import WeeklyReportInvalidDateRangeError
from app.db.models.user import User
from app.services.report_service import (
    WeeklyReportResponse,
    get_weekly_report,
)

router = APIRouter()


# Story 4.3 일반화 cap — 본 스토리는 7일 default, Story 4.4 인사이트가 14일 trailing
# window 활용 가능. 30일 초과는 Postgres index hit 효과 감소 + UX 가독성 저하 → 거부.
_MAX_REPORT_DAYS: Final[int] = 30


# --- Endpoints -----------------------------------------------------------------


@router.get(
    "/weekly",
    response_model=WeeklyReportResponse,
    responses={
        200: {"description": "주간 리포트 — 7일 매크로/칼로리/단백질/알레르기 노출"},
        400: {"description": "잘못된 날짜 범위 (`reports.invalid_date_range`)"},
        401: {"description": "인증 토큰 부재/만료"},
        403: {"description": "기본 동의 미부여 (`consent.basic.missing`)"},
    },
)
async def get_weekly_report_endpoint(
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
    from_date: Annotated[date, Query(description="시작 날짜 (KST, ISO 8601)")],
    to_date: Annotated[
        date,
        Query(description="종료 날짜 (KST, ISO 8601, ``from_date <= to_date``)"),
    ],
) -> WeeklyReportResponse:
    """7일 주간 리포트 — meals + meal_analyses LEFT JOIN aggregation.

    ``from_date``/``to_date`` 모두 필수(default X) — 클라이언트가 KST 7일 윈도우를
    명시 결정. (to-from)>30일 또는 from>to는 ``reports.invalid_date_range``(400).
    """
    if from_date > to_date:
        raise WeeklyReportInvalidDateRangeError(
            f"from_date ({from_date}) must be <= to_date ({to_date})"
        )
    if (to_date - from_date).days > _MAX_REPORT_DAYS:
        raise WeeklyReportInvalidDateRangeError(
            f"date range exceeds {_MAX_REPORT_DAYS} days (got {(to_date - from_date).days})"
        )

    return await get_weekly_report(
        user=user,
        from_date=from_date,
        to_date=to_date,
        db=db,
    )


__all__ = ["router"]
