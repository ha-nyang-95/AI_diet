"""``/v1/admin/*`` — 관리자 사용자 검색/이력/수정/삭제 (Story 7.2 FR36).

Story 7.1 ``auth.py:GET /v1/auth/admin/whoami``와 *책임 분리* — 7.1은 인증 정보
*echo*(읽기 전용 smoke), 본 모듈은 *business action* (사용자 검색/조회/수정/삭제 6
endpoint).

엔드포인트:
- ``GET /v1/admin/users?q=...&limit=&cursor=``       — 사용자 검색 (마스킹 + cursor 페이지)
- ``GET /v1/admin/users/{user_id}``                  — 사용자 상세 (마스킹 PII)
- ``GET /v1/admin/users/{user_id}/meals``            — 식단 이력 (soft-deleted 포함)
- ``GET /v1/admin/users/{user_id}/meal-analyses``    — 피드백 로그 (fit_score + summary)
- ``PATCH /v1/admin/users/{user_id}``                — 프로필 수정 (Story 5.1 SOT 재사용)
- ``DELETE /v1/admin/users/{user_id}/meals/{meal_id}`` — 식단 soft delete

설계 SOT:
- ``Depends(current_admin)`` 1줄 wire — Story 7.1 CR W4 transitive 체인(IP 가드 + JWT +
  DB role 재확인 자동 적용).
- 모든 마스킹은 ``app/core/masking.py`` 단일 SOT(Story 7.2 신규) — Sentry/structlog
  forward 정합.
- ``users.py:HealthProfilePatchRequest``(Story 5.1) + ``meals.py:delete_meal``(Story 2.1)
  패턴 재사용 — admin이 *대상 user_id*만 다르고 흐름 동일.

Story 7.3 forward stub: ``Depends(audit_admin_action)`` dep + ``audit_logs`` 테이블 +
admin endpoint audit 기록 모두 7.3 본격 신설. 본 스토리는 audit *지점만* 코드 코멘트
명시(각 endpoint docstring).

Story 7.4 forward stub: 원문 보기 토글(FR39 plaintext 응답) + 5분 비활동 자동 복원 —
본 스토리는 *기본 마스킹*만, 7.4가 토글 endpoint 추가.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import uuid
from datetime import datetime, time
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import String, desc, func, or_, select, update
from sqlalchemy.orm import selectinload

from app.adapters.r2 import resolve_public_url
from app.api.deps import DbSession, current_admin
from app.api.v1.users import HealthProfilePatchRequest  # Story 5.1 SOT 재사용
from app.core.exceptions import (
    AdminCursorInvalidError,
    AdminUserNotFoundError,
    MealNotFoundError,
)
from app.core.masking import (
    mask_allergies_count,
    mask_email,
    mask_height,
    mask_weight,
)
from app.db.models.meal import Meal
from app.db.models.meal_analysis import MealAnalysis
from app.db.models.user import User
from app.domain.health_profile import ActivityLevel, HealthGoal

logger = structlog.get_logger(__name__)

router = APIRouter()

__all__ = ["router"]


# --- Pydantic 응답 모델 (extra=forbid 일관) -----------------------------


class AdminUserListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    email_masked: str
    role: Literal["user", "admin"]
    created_at: datetime
    deleted_at: datetime | None
    profile_completed_at: datetime | None
    onboarded_at: datetime | None


class AdminUserSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    users: list[AdminUserListItem]
    next_cursor: str | None


class AdminUserDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    email_masked: str
    display_name: str | None
    picture_url: str | None
    role: Literal["user", "admin"]
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None
    deleted_at: datetime | None
    deletion_reason: str | None
    onboarded_at: datetime | None
    profile_completed_at: datetime | None
    profile_updated_at: datetime | None

    age: int | None
    weight_kg_masked: str | None
    height_cm_masked: str | None
    activity_level: ActivityLevel | None
    health_goal: HealthGoal | None
    allergies_count_masked: str | None
    macro_goal: dict[str, int] | None

    # 알림 설정 — spec line 175-178 (Story 4.1 컬럼 SOT, DB nullable=False+server_default).
    notifications_enabled: bool
    notification_time: time
    notification_timezone: str


class AdminMealAnalysisInline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fit_score: int
    fit_score_label: Literal["allergen_violation", "low", "moderate", "good", "excellent"]
    feedback_summary: str
    used_llm: Literal["gpt-4o-mini", "claude", "stub"]


class AdminMealItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meal_id: uuid.UUID
    raw_text_length: int
    ate_at: datetime
    created_at: datetime
    deleted_at: datetime | None
    image_url: str | None
    parsed_items_count: int | None
    analysis_summary: AdminMealAnalysisInline | None


class AdminMealListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meals: list[AdminMealItem]
    next_cursor: str | None


class AdminMealAnalysisItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meal_analysis_id: uuid.UUID
    meal_id: uuid.UUID
    fit_score: int
    fit_score_label: Literal["allergen_violation", "low", "moderate", "good", "excellent"]
    fit_reason: Literal["ok", "allergen_violation", "incomplete_data"]
    feedback_summary: str
    used_llm: Literal["gpt-4o-mini", "claude", "stub"]
    created_at: datetime
    updated_at: datetime


class AdminMealAnalysisListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 명명 일관성 — ``AdminUserSearchResponse.users`` / ``AdminMealListResponse.meals`` 패턴
    # 정합 (Gemini CR G2). ``items`` generic 명명 회피.
    analyses: list[AdminMealAnalysisItem]
    next_cursor: str | None


# --- cursor / LIKE escape helper ---------------------------------------


_CURSOR_SEPARATOR = "|"


def _encode_cursor(value_dt: datetime, value_id: uuid.UUID) -> str:
    """``base64url(iso_datetime "|" hex_uuid)`` — keyset pagination opaque token.

    Story 6.2 ``PaymentHistoryCursorInvalidError`` 패턴 정합 — 클라이언트는 cursor를
    *opaque*로 취급. ``isoformat()``은 timezone 보존(``+00:00`` suffix 포함).
    """
    payload = f"{value_dt.isoformat()}{_CURSOR_SEPARATOR}{value_id.hex}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(token: str) -> tuple[datetime, uuid.UUID]:
    """cursor decode 실패 시 ``AdminCursorInvalidError(400)`` 통합 raise.

    분기:
    - ``base64.urlsafe_b64decode`` 실패 (Padding/Binary error)
    - ``|`` 분리 실패 (단일 토큰)
    - ``datetime.fromisoformat`` ValueError
    - ``uuid.UUID`` ValueError
    """
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        dt_str, _, id_str = decoded.partition(_CURSOR_SEPARATOR)
        if not dt_str or not id_str:
            raise ValueError("missing separator")
        return datetime.fromisoformat(dt_str), uuid.UUID(id_str)
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise AdminCursorInvalidError("admin cursor invalid") from exc


def _escape_like_pattern(value: str) -> str:
    """LIKE wildcards (``%``/``_``) + escape char (``\\``) 리터럴 변환.

    사용자가 ``%user`` 송신 시 ILIKE wildcard 우회로 모든 row hit 차단. 호출처는
    ``func.lower(value).like(escaped + "%", escape="\\\\")``로 사용.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_user_detail_response(user: User) -> AdminUserDetailResponse:
    """User ORM → AdminUserDetailResponse — 마스킹 단일 지점."""
    return AdminUserDetailResponse(
        user_id=user.id,
        email_masked=mask_email(user.email),
        display_name=user.display_name,
        picture_url=user.picture_url,
        role=user.role,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
        deleted_at=user.deleted_at,
        deletion_reason=user.deletion_reason,
        onboarded_at=user.onboarded_at,
        profile_completed_at=user.profile_completed_at,
        profile_updated_at=user.profile_updated_at,
        age=user.age,
        weight_kg_masked=mask_weight(user.weight_kg),
        height_cm_masked=mask_height(user.height_cm),
        activity_level=user.activity_level,
        health_goal=user.health_goal,
        allergies_count_masked=mask_allergies_count(user.allergies),
        macro_goal=user.macro_goal,
        notifications_enabled=user.notifications_enabled,
        notification_time=user.notification_time,
        notification_timezone=user.notification_timezone,
    )


def _mask_user_id_for_log(user_id: uuid.UUID) -> str:
    """``u_{8char}`` — Story 3.x/4.x/5.x 패턴 정합(NFR-S5)."""
    return f"u_{user_id.hex[:8]}"


# --- AC1: GET /v1/admin/users (사용자 검색) ---------------------------


@router.get("/users")
async def search_users(
    db: DbSession,
    admin: Annotated[User, Depends(current_admin)],
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> AdminUserSearchResponse:
    """사용자 검색 — email ILIKE prefix(``q%``) OR user_id UUID prefix.

    결과는 *기본 마스킹*(NFR-S5 — 이메일 ``j***@example.com``). soft-deleted 사용자
    포함(admin 거버넌스 — ``deleted_at`` 필드로 명시). cursor pagination
    (``created_at_desc`` keyset).

    Story 7.3 forward: ``Depends(audit_admin_action)`` 추가 wire 시
    ``action="user_search"`` + ``target_resource="users"`` + ``path="/v1/admin/users"``
    자동 기록.

    Story 7.4 forward: ``?include_pii=true`` 쿼리 + 명시 *원문 보기* 액션 시 plaintext
    이메일 응답 + audit log ``action="user_pii_view"`` 추가 분기.
    """
    escaped_q = _escape_like_pattern(q)
    lower_q = escaped_q.lower()

    conditions = [
        # email prefix — ``idx_users_email_lower`` (alembic 0021) hit + LIKE escape.
        func.lower(User.email).like(f"{lower_q}%", escape="\\"),
        # user_id::text prefix — UUID v4 random distribution이라 인덱스 미생성, full
        # scan 허용(1만 row sub-second). Postgres ``uuid::text``는 항상 소문자라
        # case-insensitive 정합 위해 lower-cased pattern 사용 (대문자 prefix silent fail 방지).
        func.cast(User.id, String).like(f"{lower_q}%", escape="\\"),
    ]

    stmt = select(User).where(or_(*conditions))

    if cursor is not None:
        cursor_dt, cursor_id = _decode_cursor(cursor)
        # row-value compare for stable keyset (created_at DESC, id DESC).
        stmt = stmt.where(
            or_(
                User.created_at < cursor_dt,
                (User.created_at == cursor_dt) & (User.id < cursor_id),
            )
        )

    stmt = (
        stmt.order_by(desc(User.created_at), desc(User.id)).limit(
            limit + 1
        )  # over-fetch 1 — next_cursor 판단
    )

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    items = [
        AdminUserListItem(
            user_id=u.id,
            email_masked=mask_email(u.email),
            role=u.role,
            created_at=u.created_at,
            deleted_at=u.deleted_at,
            profile_completed_at=u.profile_completed_at,
            onboarded_at=u.onboarded_at,
        )
        for u in rows
    ]

    next_cursor: str | None = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    with contextlib.suppress(Exception):
        logger.info(
            "admin.users.searched",
            admin_id=_mask_user_id_for_log(admin.id),
            q_length=len(q),
            limit=limit,
            result_count=len(items),
        )

    return AdminUserSearchResponse(users=items, next_cursor=next_cursor)


# --- AC2: GET /v1/admin/users/{user_id} (사용자 상세) -----------------


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: uuid.UUID,
    db: DbSession,
    admin: Annotated[User, Depends(current_admin)],
) -> AdminUserDetailResponse:
    """사용자 상세 — 프로필 + 메타(가입/탈퇴/온보딩/프로필 갱신) + 마스킹 PII.

    soft-deleted 사용자도 200 응답(admin 거버넌스 — ``deleted_at`` 필드 포함). 미존재
    user_id → 404 ``code=admin.user.not_found``.

    Story 7.3 forward: ``action="user_profile_view"``.
    Story 7.4 forward: 원문 보기 토글 endpoint 별도 신설.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise AdminUserNotFoundError("user not found")

    with contextlib.suppress(Exception):
        logger.info(
            "admin.users.detail.viewed",
            admin_id=_mask_user_id_for_log(admin.id),
            target_user_id=_mask_user_id_for_log(user.id),
        )

    return _build_user_detail_response(user)


# --- AC3: GET /v1/admin/users/{user_id}/meals (식단 이력) -------------


@router.get("/users/{user_id}/meals")
async def list_user_meals(
    user_id: uuid.UUID,
    db: DbSession,
    admin: Annotated[User, Depends(current_admin)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> AdminMealListResponse:
    """타 사용자 식단 이력 조회 — soft-deleted 포함 + 분석 요약 join + raw_text length-only.

    이력 보존(NFR-S5 정합 — admin도 식단 raw_text plaintext는 마스킹 대상). 일반
    사용자 ``GET /v1/meals``와 *별 책임* — 사용자 자신의 raw_text는 평문, admin이 보는
    타인 식단 raw_text는 length-only.

    Story 7.3 forward: ``action="user_meal_history_view"``.
    Story 7.4 forward: 원문 보기 시 raw_text plaintext 분기.
    """
    user_exists = await db.execute(select(User.id).where(User.id == user_id))
    if user_exists.scalar_one_or_none() is None:
        raise AdminUserNotFoundError("user not found")

    stmt = select(Meal).where(Meal.user_id == user_id).options(selectinload(Meal.analysis))

    if cursor is not None:
        cursor_dt, cursor_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Meal.ate_at < cursor_dt,
                (Meal.ate_at == cursor_dt) & (Meal.id < cursor_id),
            )
        )

    stmt = stmt.order_by(desc(Meal.ate_at), desc(Meal.id)).limit(limit + 1)

    result = await db.execute(stmt)
    meals = list(result.scalars().all())

    has_more = len(meals) > limit
    if has_more:
        meals = meals[:limit]

    items: list[AdminMealItem] = []
    for meal in meals:
        analysis_summary: AdminMealAnalysisInline | None = None
        if meal.analysis is not None:
            analysis_summary = AdminMealAnalysisInline(
                fit_score=meal.analysis.fit_score,
                fit_score_label=meal.analysis.fit_score_label,
                feedback_summary=meal.analysis.feedback_summary,
                used_llm=meal.analysis.used_llm,
            )
        image_url = resolve_public_url(meal.image_key) if meal.image_key else None
        parsed_count = len(meal.parsed_items) if meal.parsed_items is not None else None
        items.append(
            AdminMealItem(
                meal_id=meal.id,
                raw_text_length=len(meal.raw_text),
                ate_at=meal.ate_at,
                created_at=meal.created_at,
                deleted_at=meal.deleted_at,
                image_url=image_url,
                parsed_items_count=parsed_count,
                analysis_summary=analysis_summary,
            )
        )

    next_cursor: str | None = None
    if has_more and meals:
        last = meals[-1]
        next_cursor = _encode_cursor(last.ate_at, last.id)

    with contextlib.suppress(Exception):
        logger.info(
            "admin.users.meals.listed",
            admin_id=_mask_user_id_for_log(admin.id),
            target_user_id=_mask_user_id_for_log(user_id),
            result_count=len(items),
        )

    return AdminMealListResponse(meals=items, next_cursor=next_cursor)


# --- AC4: GET /v1/admin/users/{user_id}/meal-analyses (피드백 로그) ----


@router.get("/users/{user_id}/meal-analyses")
async def list_user_meal_analyses(
    user_id: uuid.UUID,
    db: DbSession,
    admin: Annotated[User, Depends(current_admin)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> AdminMealAnalysisListResponse:
    """타 사용자 분석/피드백 로그 조회 — feedback_summary + fit_score + used_llm.

    AC3 식단 이력과 *별 endpoint*: meal_analyses는 *분석 결과 단독* 조회(meal 메타와
    분리). feedback_summary는 *사용자 식별 정보 부재*라 평문 노출. feedback_text(full
    body)는 본 list endpoint에서 *생략* — 별 detail endpoint는 본 스토리 OUT(7.4 원문
    보기 시점에 흡수).

    Story 7.3 forward: ``action="user_feedback_history_view"``.
    """
    user_exists = await db.execute(select(User.id).where(User.id == user_id))
    if user_exists.scalar_one_or_none() is None:
        raise AdminUserNotFoundError("user not found")

    stmt = select(MealAnalysis).where(MealAnalysis.user_id == user_id)

    if cursor is not None:
        cursor_dt, cursor_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                MealAnalysis.created_at < cursor_dt,
                (MealAnalysis.created_at == cursor_dt) & (MealAnalysis.id < cursor_id),
            )
        )

    stmt = stmt.order_by(desc(MealAnalysis.created_at), desc(MealAnalysis.id)).limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    items = [
        AdminMealAnalysisItem(
            meal_analysis_id=row.id,
            meal_id=row.meal_id,
            fit_score=row.fit_score,
            fit_score_label=row.fit_score_label,
            fit_reason=row.fit_reason,
            feedback_summary=row.feedback_summary,
            used_llm=row.used_llm,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]

    next_cursor: str | None = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    return AdminMealAnalysisListResponse(analyses=items, next_cursor=next_cursor)


# --- AC5: PATCH /v1/admin/users/{user_id} (관리자 프로필 수정) ---------


@router.patch("/users/{user_id}")
async def patch_user_profile(
    user_id: uuid.UUID,
    body: HealthProfilePatchRequest,
    db: DbSession,
    admin: Annotated[User, Depends(current_admin)],
) -> AdminUserDetailResponse:
    """타 사용자 프로필 수정 — ``users.py:patch_health_profile``(Story 5.1) 흐름 정합.

    핵심 차이:
    1. 대상 user_id가 admin 자기 자신이 아닌 *타 사용자*.
    2. ``require_basic_consents`` gate *미적용* — admin은 거버넌스 행위(PIPA 18조 처리
       위탁과 별개의 서비스 운영 정합).
    3. ``profile_updated_at = func.now()`` set + ``profile_completed_at`` 미터치 +
       ``onboarded_at`` 미터치(Story 5.1 invariant 동일).

    soft-deleted 사용자 수정 거부: ``deleted_at IS NOT NULL`` 사용자는 404 — 30일 grace
    후 cascade 삭제될 데이터에 손대는 거버넌스 위험 차단(Story 5.2 정합).

    Story 7.3 forward: ``action="user_profile_edit"`` + ``target_user_id={user_id}``.
    LLM cache 무효화: ``_build_profile_hash``(Story 3.6/4.4 SOT)가 sha256 input에 포함된
    6 필드 자동 invalidate.
    """
    fields_dict = body.model_dump(exclude_unset=True)

    result = await db.execute(
        update(User)
        .where(User.id == user_id, User.deleted_at.is_(None))
        .values(
            **fields_dict,
            profile_updated_at=func.now(),
            updated_at=func.now(),
        )
        .returning(User)
        .execution_options(populate_existing=True)
    )
    updated_user = result.scalar_one_or_none()
    if updated_user is None:
        raise AdminUserNotFoundError("user not found or deleted")
    response = _build_user_detail_response(updated_user)
    await db.commit()

    with contextlib.suppress(Exception):
        logger.info(
            "admin.users.profile.patched",
            admin_id=_mask_user_id_for_log(admin.id),
            target_user_id=_mask_user_id_for_log(user_id),
            keys_set=sorted(fields_dict.keys()),  # 값 본문 X — NFR-S5
        )
    return response


# --- AC6: DELETE /v1/admin/users/{user_id}/meals/{meal_id} -------------


@router.delete(
    "/users/{user_id}/meals/{meal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_meal(
    user_id: uuid.UUID,
    meal_id: uuid.UUID,
    db: DbSession,
    admin: Annotated[User, Depends(current_admin)],
) -> Response:
    """타 사용자 식단 soft delete — B2B 운영 케이스(예: 잘못된 식단 입력 사용자 요청).

    Story 2.1 ``meals.py:delete_meal`` SOT 정합 — 단일 SQL update + ``deleted_at IS
    NULL`` 필터 + ``RETURNING id``로 race-free + 소유권(``user_id`` 매칭) 검증 통합.

    이미 soft-deleted된 meal → 404 ``code=meals.not_found``(Story 2.1과 동일 enumeration
    차단). meal_id가 다른 사용자 소유 시도 → 404(같은 응답 — enumeration 차단).

    Story 7.3 forward: ``action="admin_meal_delete"`` + ``target_user_id={user_id}`` +
    ``target_resource="meals"`` + ``target_resource_id={meal_id}``.
    """
    result = await db.execute(
        update(Meal)
        .where(
            Meal.id == meal_id,
            Meal.user_id == user_id,
            Meal.deleted_at.is_(None),
        )
        .values(deleted_at=func.now())
        .returning(Meal.id)
    )
    deleted_id = result.scalar_one_or_none()
    if deleted_id is None:
        raise MealNotFoundError("meal not found")
    await db.commit()

    logger.info(
        "admin.meals.deleted",
        admin_id=_mask_user_id_for_log(admin.id),
        target_user_id=_mask_user_id_for_log(user_id),
        meal_id=str(meal_id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
