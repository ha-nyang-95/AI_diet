"""`/v1/users/me` — 현재 로그인 사용자 조회 + 건강 프로필 입력/조회/수정.

- ``GET /v1/users/me`` (Story 1.2): 자기 정보 조회. 인증만 — 동의 게이트 X.
  Story 1.5에서 ``profile_completed_at`` 필드 응답 모델 추가(4번째 가드용 분기).
- ``POST /v1/users/me/profile`` (Story 1.5 AC2): 건강 프로필 *최초* 입력 — 7컬럼 update +
  ``profile_completed_at`` set. ``Depends(require_basic_consents)`` 첫 wire.
- ``GET /v1/users/me/profile`` (Story 1.5 AC3): 프로필 값 조회 — 인증만(자기 정보).
  미입력 사용자도 200 + 6 필드 NULL + ``allergies=[]`` 응답(404 X — 사용자는 항상
  존재). prefill 흐름 forward-hook.
- ``PATCH /v1/users/me/profile`` (Story 5.1 AC2): 건강 프로필 *수정* — 6 필드 partial +
  at-least-one + ``profile_updated_at`` set. ``profile_completed_at`` 미터치(invariant).
"""

from __future__ import annotations

import contextlib
import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Self

import structlog
from fastapi import APIRouter, Depends
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import func, text, update

from app.api.deps import DbSession, current_user, require_basic_consents
from app.core.exceptions import MacroGoalInvalidError
from app.db.models.user import User
from app.domain.allergens import normalize_allergens
from app.domain.health_profile import ActivityLevel, HealthGoal
from app.domain.macro_goal import MacroGoal, MacroGoalPatchRequest

logger = structlog.get_logger(__name__)

router = APIRouter()


# --- Pydantic 스키마 (snake_case 양방향) -----------------------------------


class UserMeResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    picture_url: str | None
    role: str
    created_at: datetime
    last_login_at: datetime | None
    onboarded_at: datetime | None
    # Story 1.5 — 4번째 가드 분기에 사용. ``users.profile_completed_at`` 그대로 forward.
    profile_completed_at: datetime | None


class HealthProfileSubmitRequest(BaseModel):
    """``POST /v1/users/me/profile`` body — 6 입력 필드 (profile_completed_at은 backend-managed).

    범위 검증은 Pydantic ``Field(ge=, le=)``로 1차, DB CHECK 제약이 2차(double gate).
    ``allergies`` 22종 검증은 ``field_validator``에서 ``normalize_allergens()`` 호출 —
    invalid 항목 발견 시 ``ValueError`` raise → Pydantic ``ValidationError`` →
    글로벌 핸들러가 RFC 7807 400 + ``code=validation.error``.
    """

    model_config = ConfigDict(extra="forbid")

    age: int = Field(ge=1, le=150)
    # ``allow_inf_nan=False`` — NaN/Infinity wire format을 명시 거부 → DB Numeric(5,1)
    # DataError(500) 회피하고 RFC 7807 400 + ``code=validation.error`` 정상 분기.
    weight_kg: float = Field(ge=1.0, le=500.0, allow_inf_nan=False)
    height_cm: int = Field(ge=50, le=300)
    activity_level: ActivityLevel
    health_goal: HealthGoal
    # ``max_length=22`` — 도메인 상한과 일치, 1M-element duplicate DoS 차단.
    allergies: list[str] = Field(default_factory=list, max_length=22)

    @field_validator("weight_kg")
    @classmethod
    def _validate_weight_precision(cls, v: float) -> float:
        """소수 첫째 자리까지만 허용 — DB ``Numeric(5,1)``의 silent rounding 차단.

        70.55 같은 값이 백엔드에서 70.6으로 무성 반올림 후 응답되면 사용자가 입력한
        값과 응답이 불일치 (Story 5.1 prefill UX). 1자리 초과 정밀도는 명시 거부.
        """
        if round(v, 1) != v:
            raise ValueError("weight_kg must have at most 1 decimal place")
        return v

    @field_validator("allergies")
    @classmethod
    def _validate_allergens(cls, v: list[str]) -> list[str]:
        """22종 부분집합 검증 + dedup + NFC 정규화 + 정의 순 정렬.

        invalid 항목 → ``ValueError("unknown allergen: '<value>'; ...")`` raise.
        Pydantic이 ValidationError로 wrap → ``main.py:validation_exception_handler``가
        RFC 7807 400 + ``errors`` 배열에 ``msg`` 필드로 메시지 forward (top-level
        ``detail``은 정적 "Request validation failed" — 글로벌 핸들러 회귀 차단).
        """
        return normalize_allergens(v)


class HealthProfileResponse(BaseModel):
    """``POST/GET/PATCH /v1/users/me/profile`` 응답 — 8 필드.

    ``allergies``는 NULL → ``[]`` 빈 배열로 응답(클라이언트 분기 단순화).
    ``weight_kg``는 DB ``Decimal`` → JSON wire format ``float`` 직렬화.

    Story 5.1 — ``profile_updated_at`` 필드 추가(8번째). PATCH 호출 전까지는 NULL,
    PATCH 첫 호출 시 set. POST는 본 필드 미터치(``profile_completed_at`` SOT만 set).
    """

    age: int | None
    weight_kg: float | None
    height_cm: int | None
    activity_level: ActivityLevel | None
    health_goal: HealthGoal | None
    allergies: list[str]
    profile_completed_at: datetime | None
    profile_updated_at: datetime | None


class HealthProfilePatchRequest(BaseModel):
    """``PATCH /v1/users/me/profile`` body — 6 필드 partial + at-least-one 가드.

    Story 1.5 ``HealthProfileSubmitRequest``(POST 6 필드 required full-replace)와 *별
    모델*. 본 모델은 6 필드 모두 Optional + ``model_fields_set`` 기반 at-least-one
    + None 명시 송신은 *해당 컬럼 NULL set*(REST PATCH 표준 정합 — 6 필드 모두
    *원래 nullable*이라 *부재*와 *명시 null* 동작 일관 가능).

    Story 4.4 ``MacroGoalPatchRequest`` SOT 패턴 정합 — at-least-one 가드는 *명시
    송신* 기준(``model_fields_set``)으로, 빈 body ``{}`` 만 거부(6 필드 모두 None
    default + 빈 body는 ``model_fields_set``이 빈 set).
    """

    model_config = ConfigDict(extra="forbid")

    age: int | None = Field(default=None, ge=1, le=150)
    # ``allow_inf_nan=False`` — Story 1.5 SOT 정합(NaN/Infinity wire 거부).
    weight_kg: float | None = Field(default=None, ge=1.0, le=500.0, allow_inf_nan=False)
    height_cm: int | None = Field(default=None, ge=50, le=300)
    activity_level: ActivityLevel | None = None
    health_goal: HealthGoal | None = None
    allergies: list[str] | None = Field(default=None, max_length=22)

    @field_validator("weight_kg")
    @classmethod
    def _validate_weight_precision(cls, v: float | None) -> float | None:
        """Story 1.5 SOT 1:1 — 소수 1자리 silent rounding 차단. None pass-through."""
        if v is None:
            return None
        if round(v, 1) != v:
            raise ValueError("weight_kg must have at most 1 decimal place")
        return v

    @field_validator("allergies")
    @classmethod
    def _validate_allergens(cls, v: list[str] | None) -> list[str] | None:
        """Story 1.5 SOT 재사용 — 22종 부분집합 + dedup + NFC + 정의 순. None pass-through."""
        if v is None:
            return None
        return normalize_allergens(v)

    @model_validator(mode="after")
    def _validate_at_least_one(self) -> Self:
        """``model_fields_set``이 빈 set이면 empty PATCH — 거부.

        None 명시 송신은 *명시 송신*으로 분류(``model_fields_set``에 포함) → valid.
        Story 4.4 ``MacroGoalPatchRequest`` 패턴 정합.
        """
        if not self.model_fields_set:
            raise ValueError("at least one health profile field required")
        return self


def _build_profile_response(user: User) -> HealthProfileResponse:
    """User ORM → HealthProfileResponse 변환.

    - ``weight_kg`` ``Decimal | None → float | None`` 명시 변환 (wire format float 정합).
    - ``allergies`` ``None → []`` 빈 배열 fallback (``is not None`` 명시 분기 — DB의 *NULL*과
      *empty list*를 같은 ``[]`` 응답으로 통합. profile 입력 여부는 ``profile_completed_at``
      으로 판별).
    - Story 5.1 ``profile_updated_at`` forward — POST 흐름은 항상 NULL, PATCH 후 set.
    """
    return HealthProfileResponse(
        age=user.age,
        weight_kg=float(user.weight_kg) if user.weight_kg is not None else None,
        height_cm=user.height_cm,
        activity_level=user.activity_level,
        health_goal=user.health_goal,
        allergies=list(user.allergies) if user.allergies is not None else [],
        profile_completed_at=user.profile_completed_at,
        profile_updated_at=user.profile_updated_at,
    )


# --- Endpoints -------------------------------------------------------------


@router.get("/me")
async def get_me(user: Annotated[User, Depends(current_user)]) -> UserMeResponse:
    return UserMeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        picture_url=user.picture_url,
        role=user.role,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        onboarded_at=user.onboarded_at,
        profile_completed_at=user.profile_completed_at,
    )


@router.post("/me/profile")
async def submit_health_profile(
    body: HealthProfileSubmitRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],  # ← Story 1.3 W14 첫 wire
) -> HealthProfileResponse:
    """프로필 입력 — 7컬럼 update + ``profile_completed_at = now()`` set.

    ``users`` row는 OAuth 시점(Story 1.2)에 이미 존재 — INSERT 분기 X. 항상 200.
    재입력(이미 입력된 사용자가 다시 POST)도 200 + 갱신값 반영 + ``profile_completed_at``
    갱신(*최신 프로필 기록 시점*. 과거 입력 history는 audit_logs Story 7.3 책임).

    ``UPDATE ... RETURNING``으로 race-free 응답 — commit 후 별도 SELECT 시
    동시 다른 device POST가 끼어들면 응답이 *방금 보낸 값*이 아닌 *마지막 commit
    값*이 되는 race를 차단. ``profile_completed_at`` / ``updated_at`` 양쪽 모두
    DB-side ``func.now()`` 단일 시계 — Python ``datetime.now()`` 와의 clock skew 회피.

    응답 build는 ``commit`` *이전*에 수행 — AsyncSession은 ``commit`` 후 모든 객체를
    expire 시키므로, expired 객체 속성 접근이 lazy-load를 trigger해
    ``sqlalchemy.exc.MissingGreenlet`` (async context lazy-load 금지) 가능.
    RETURNING으로 메모리에 이미 로드된 데이터를 commit 전에 직렬화 후 commit.

    Story 1.6 — ``onboarded_at = func.coalesce(User.onboarded_at, func.now())``로 단일
    UPDATE 안에서 *기존 NULL이면 now() set, 이미 set이면 그대로* (멱등). Story 5.1
    프로필 수정 시점에도 ``onboarded_at``은 변경되지 않아 *최초 온보딩 시점*이 보존됨.
    ``onboarded_first_time`` 로깅은 update 직전 ORM 객체 값으로 판별(NFR-S5: user_id만
    raw, 다른 민감정보 X).
    """
    onboarded_first_time = user.onboarded_at is None
    result = await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            age=body.age,
            weight_kg=body.weight_kg,
            height_cm=body.height_cm,
            activity_level=body.activity_level,
            health_goal=body.health_goal,
            allergies=body.allergies,
            profile_completed_at=func.now(),
            onboarded_at=func.coalesce(User.onboarded_at, func.now()),
            updated_at=func.now(),
        )
        .returning(User)
        .execution_options(populate_existing=True)
    )
    updated_user = result.scalar_one()
    response = _build_profile_response(updated_user)
    await db.commit()
    # 로깅은 commit 성공 후 best-effort — structlog processor 실패가 응답을 500으로
    # 전환하지 않도록 가드(클라이언트는 이미 DB write가 성공한 것을 응답으로 봐야 함.
    # retry 시 COALESCE는 멱등이라 데이터 중복 위험 X이나 사용자 경험 혼선만).
    with contextlib.suppress(Exception):
        logger.info(
            "users.profile.updated",
            user_id=str(user.id),
            onboarded_first_time=onboarded_first_time,
        )
    return response


@router.get("/me/profile")
async def get_health_profile(
    user: Annotated[User, Depends(current_user)],
) -> HealthProfileResponse:
    """프로필 조회 — 인증만(자기 정보 조회는 동의 무관, deps.py 주석 정합).

    미입력 사용자(``profile_completed_at IS NULL``) → 200 + 6 필드 NULL +
    ``allergies=[]`` + ``profile_completed_at=null``. 404 미사용.
    """
    return _build_profile_response(user)


@router.patch("/me/profile")
async def patch_health_profile(
    body: HealthProfilePatchRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],  # Story 1.5 W14 패턴 정합
) -> HealthProfileResponse:
    """프로필 수정 — 6 필드 partial update + ``profile_updated_at`` set.

    Story 1.5 ``POST /me/profile``(*최초 입력*)과 *별 endpoint*. 본 endpoint는
    *재방문 수정* 흐름 — ``profile_completed_at`` 미터치(invariant 보존), ``onboarded_at``
    미터치(Story 1.6 invariant). ``profile_updated_at``만 set(0016 마이그레이션 컬럼).

    흐름:
    1) Pydantic 1차 게이트(at-least-one + range + 22종 + weight precision).
    2) ``model_dump(exclude_unset=True)`` — *명시 송신* 필드만 처리. None 명시 송신은
       *해당 컬럼 NULL set*(REST PATCH 표준 + 6 필드 모두 *원래 nullable*이라 의미 일관).
    3) ``UPDATE ... RETURNING`` race-free — Story 1.5 SOT 패턴(``populate_existing=True``
       expired 객체 lazy-load 회피, commit 전 응답 build).
    4) ``profile_updated_at = func.now()`` set + ``updated_at = func.now()`` bump. DB-side
       single 시계.

    ``users.profile.patched`` structlog event(별 이벤트명 — POST는 ``users.profile.updated``):
    NFR-S5 정합 — ``user_id`` ``u_{8char}`` 마스킹 + ``keys_set`` only(*값* 본문 X).

    LLM cache invalidate: ``_build_profile_hash``(Story 3.6/4.4 SOT)가 6 필드 모두
    sha256 body에 포함 → PATCH 후 다음 분석 자동 cache miss → 새 LLM 호출.
    Redis profile cache(architecture.md:296 ``cache:user:{user_id}:profile``)는
    *현 프로젝트 미구현* — Story 8.4 polish forward.
    """
    # TODO Story 8.4: redis profile cache wire — invalidate on PATCH (cache miss after
    # write). 현 baseline은 미구현(architecture.md:296 forward-hook). LLM cache는
    # _build_profile_hash가 자동 invalidate.
    fields_dict = body.model_dump(exclude_unset=True)

    result = await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            **fields_dict,
            profile_updated_at=func.now(),
            updated_at=func.now(),
            # profile_completed_at 미터치 — Story 1.5 invariant 보존(*최초 온보딩 시점*).
            # onboarded_at 미터치 — Story 1.6 invariant 보존.
        )
        .returning(User)
        .execution_options(populate_existing=True)
    )
    updated_user = result.scalar_one()
    response = _build_profile_response(updated_user)
    await db.commit()

    # 로깅은 commit 성공 후 best-effort — Story 1.5 패턴 정합(structlog processor 실패가
    # 응답을 500으로 전환하지 않도록 가드).
    with contextlib.suppress(Exception):
        logger.info(
            "users.profile.patched",
            user_id=_mask_user_id(user.id),
            keys_set=sorted(fields_dict.keys()),  # 값 본문 X — NFR-S5
        )
    return response


# --- Story 4.4 — Macro Goal endpoints --------------------------------------


def _mask_user_id(user_id: object) -> str:
    """UUID → ``u_{8char}`` 마스킹 (Story 3.x/4.2/4.3 패턴 정합 — NFR-S5)."""
    return f"u_{str(user_id).replace('-', '')[:8]}"


def _build_macro_goal_response(raw: dict[str, Any] | None) -> MacroGoal:
    """User row의 macro_goal JSONB → MacroGoal 응답.

    미설정 사용자는 빈 ``MacroGoal()`` 반환(``model_dump(exclude_none=True)``로 ``{}``
    응답). 잘못된 legacy shape는 ValidationError → 빈 ``MacroGoal()`` graceful
    fallback(404 X — 사용자가 항상 존재).
    """
    if not raw:
        return MacroGoal()
    try:
        return MacroGoal.model_validate(raw)
    except ValidationError:
        return MacroGoal()


@router.get("/me/macro_goal")
async def get_macro_goal(
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    """``users.macro_goal`` JSONB 조회 — 인증만(자기 데이터 조회는 동의 무관).

    미설정 사용자 → 200 + ``{}`` 빈 object(404 X). 폼 prefill 입력(AC4).
    응답은 ``model_dump(exclude_none=True)`` — None 필드 미포함.
    """
    response = _build_macro_goal_response(user.macro_goal)
    return response.model_dump(exclude_none=True)


@router.patch("/me/macro_goal")
async def patch_macro_goal(
    body: dict[str, Any],
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
) -> dict[str, Any]:
    """``users.macro_goal`` JSONB partial update — 5 필드 partial.

    ``MacroGoalPatchRequest`` Pydantic 1차 게이트(ratio all-or-none + sum=100 +
    at-least-one). DB CHECK ``ck_users_macro_goal_shape``가 2차 게이트(shape).
    Pydantic ``ValueError``는 ``MacroGoalInvalidError``로 변환 → RFC 7807 400 +
    ``code=user.macro_goal.invalid``.

    JSONB merge 룰: dict의 *not None* 필드만 ``COALESCE(macro_goal, '{}'::jsonb) ||
    :patch`` (set 또는 갱신). ``None`` 명시 송신은 *해당 키 삭제* 분기로 ``- 'key'``
    operator. 결과 응답은 갱신된 전체 ``MacroGoal``(빈 응답 가능 — 모든 필드 삭제).

    Profile cache invalidate: architecture.md:296 ``cache:user:{user_id}:profile``
    Redis 캐시 *미구현* — Story 8.4 polish forward. LLM cache invalidate는
    ``_build_profile_hash`` body 확장으로 자동(macro_goal 변경 → sha256 변경 → 다음
    분석 cache miss → 새 LLM 호출).
    """
    # 1) Pydantic 1차 게이트 — body raw dict를 MacroGoalPatchRequest로 검증.
    try:
        patch_req = MacroGoalPatchRequest.model_validate(body)
    except ValidationError as exc:
        raise MacroGoalInvalidError(detail=str(exc.errors()[0].get("msg", "invalid"))) from exc

    # 2) ``exclude_unset=True`` — *명시 송신* 필드만 처리. 미송신 필드는 기존 값 보존
    # (JSONB merge 정합). 명시 송신 ``None`` → key 삭제 SQL operator (``-``).
    raw_dump = patch_req.model_dump(exclude_unset=True)
    keys_to_remove = [k for k, v in raw_dump.items() if v is None]
    keys_to_set = {k: v for k, v in raw_dump.items() if v is not None}

    # 3) UPDATE ... RETURNING으로 race-free 갱신 + commit 전 응답 build.
    # 단계별 SQL: COALESCE → || patch → 각 key 삭제. 다중 keys_to_remove를 단일 SQL
    # 안에서 chained ``- 'key'`` 처리.
    set_jsonb_param = keys_to_set or {}
    sql_remove_chain = ""
    for k in keys_to_remove:
        # key 이름은 enum-like(MacroGoal field 5종)이라 SQL injection 안전. 명시 화이트리스트
        # 가드는 keys_to_remove가 model_dump 출력만 수용한다는 사실로 SOT.
        if k not in {
            "daily_calorie_target_kcal",
            "protein_target_g_per_meal",
            "macro_ratio_carb_pct",
            "macro_ratio_protein_pct",
            "macro_ratio_fat_pct",
        }:
            continue
        sql_remove_chain += f" - '{k}'"

    sql = text(
        f"UPDATE users SET macro_goal = ("
        f"COALESCE(macro_goal, '{{}}'::jsonb) || CAST(:patch AS jsonb)"
        f"){sql_remove_chain}, updated_at = now() "
        f"WHERE id = :user_id "
        f"RETURNING macro_goal"
    )
    result = await db.execute(
        sql,
        {
            "patch": json.dumps(set_jsonb_param),
            "user_id": user.id,
        },
    )
    updated_row = result.first()
    if updated_row is None:
        # current_user Dependency를 통과한 user는 항상 존재 — 본 분기는 race(soft-delete
        # 동시 발생) 외 미진입.
        await db.rollback()
        raise MacroGoalInvalidError(detail="user not found")
    updated_macro_goal: dict[str, Any] | None = updated_row[0]

    # 4) Merged 결과 invariant 재검증 — Pydantic 1차 게이트는 *patch payload*만 본다.
    # null-removal 단일 ratio 키 PATCH 시 DB가 partial-set state로 진행될 수 있으므로
    # 기존 row와 merge된 결과를 ``MacroGoal``로 재검증해 ratio all-or-none + sum=100
    # invariant를 사후 강제. 위반 시 commit 전 rollback + RFC 7807 400.
    if updated_macro_goal:
        try:
            MacroGoal.model_validate(updated_macro_goal)
        except ValidationError as exc:
            await db.rollback()
            raise MacroGoalInvalidError(
                detail=str(exc.errors()[0].get("msg", "merged macro_goal invalid"))
            ) from exc

    response = _build_macro_goal_response(updated_macro_goal)
    await db.commit()

    with contextlib.suppress(Exception):
        logger.info(
            "users.macro_goal.updated",
            user_id=_mask_user_id(user.id),
            keys_set=sorted(keys_to_set.keys()),
            keys_removed=sorted(keys_to_remove),
        )

    return response.model_dump(exclude_none=True)
