"""``/v1/notifications`` — 알림 설정 + Expo push token 등록·해제 (Story 4.1).

4 endpoint:

- ``GET /settings`` (`current_user` only — 자기 정보 조회는 동의 게이트 X, PIPA Art.35 정합)
- ``PATCH /settings`` (`require_basic_consents` — 작성 경로)
- ``POST /devices`` (`require_basic_consents` — 작성 경로)
- ``DELETE /devices`` (`require_basic_consents` — 작성 경로)

신규 RFC 7807 ``code`` 카탈로그:

- ``notification.time.invalid_format`` — ``HH:MM`` 24시간제 regex 위반 (Pydantic 1차 게이트).
- ``notification.token.invalid`` — Expo 표준 prefix 위반 (Pydantic 1차 게이트).
"""

from __future__ import annotations

import re
from datetime import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict

from app.api.deps import DbSession, current_user, require_basic_consents
from app.core.exceptions import (
    NotificationTimeInvalidFormatError,
    NotificationTokenInvalidError,
)
from app.db.models.user import User
from app.services.notification_service import (
    NotificationSettings,
    get_settings,
    register_push_token,
    revoke_push_token,
    update_settings,
)

router = APIRouter()


# --- 정규식 SOT ---
# 24시간제 ``HH:MM`` — wire format. DB 측은 ``HH:MM:00`` (CHECK 강제). 변환은 router 내부.
_NOTIFICATION_TIME_WIRE_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
# Expo 표준 prefix — ``ExponentPushToken[…]`` (legacy) + ``ExpoPushToken[…]`` (2026 SDK).
_EXPO_TOKEN_RE = re.compile(r"^Expo(nent)?PushToken\[[A-Za-z0-9\-_]{16,}\]$")


# --- Pydantic 스키마 ---


class NotificationSettingsResponse(BaseModel):
    """4 필드 + ``has_push_token`` boolean(token 노출 X — privacy 보호)."""

    notifications_enabled: bool
    notification_time: str  # ``HH:MM`` wire format (DB는 ``HH:MM:00``)
    notification_timezone: str
    has_push_token: bool


class NotificationSettingsUpdate(BaseModel):
    """partial PATCH body — 두 필드 모두 optional.

    형식 검증은 라우터(``patch_notification_settings``)에서 ``NotificationTimeInvalidFormatError``
    raise — Pydantic 1차 게이트는 *type 가드*에 한정. 이렇게 분리하는 이유: Pydantic
    field_validator의 ValueError는 글로벌 ``RequestValidationError`` 핸들러에서 ``code=
    validation.error``로 평탄화되어 spec 카탈로그(``notification.time.invalid_format``)
    노출이 불가능하기 때문.
    """

    model_config = ConfigDict(extra="forbid")

    notifications_enabled: bool | None = None
    notification_time: str | None = None  # ``HH:MM`` wire format — 라우터에서 regex 검증.


class PushTokenRegisterRequest(BaseModel):
    """device 등록 body — token + platform.

    ``expo_push_token`` 형식 검증은 라우터(``register_device``)에서
    ``NotificationTokenInvalidError`` raise(``NotificationSettingsUpdate``와 동일 사유 —
    typed code 카탈로그 노출).
    """

    model_config = ConfigDict(extra="forbid")

    expo_push_token: str
    platform: Literal["ios", "android", "web"]


# --- helpers ---


def _to_wire_time(t: time) -> str:
    """DB ``time(20,0,0)`` → wire ``"20:00"``. 초 정보는 wire에서 제거(분 단위 SOT)."""
    return f"{t.hour:02d}:{t.minute:02d}"


def _from_wire_time(wire: str) -> time:
    """wire ``"20:00"`` → DB ``time(20,0,0)`` (초는 0 강제 — CHECK 정합)."""
    hour, minute = wire.split(":")
    return time(int(hour), int(minute), 0)


def _to_response(settings: NotificationSettings) -> NotificationSettingsResponse:
    return NotificationSettingsResponse(
        notifications_enabled=settings.notifications_enabled,
        notification_time=_to_wire_time(settings.notification_time),
        notification_timezone=settings.notification_timezone,
        has_push_token=settings.has_push_token,
    )


# --- Endpoints ---


@router.get("/settings")
async def get_notification_settings(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> NotificationSettingsResponse:
    """자기 정보 조회 — 인증만 (동의 게이트 X, PIPA Art.35 정합)."""
    settings = await get_settings(db, user)
    return _to_response(settings)


@router.patch("/settings")
async def patch_notification_settings(
    body: NotificationSettingsUpdate,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
) -> NotificationSettingsResponse:
    """partial PATCH — `notifications_enabled` 단독, `notification_time` 단독, 둘 다 모두 200.

    *Why ``require_basic_consents``*: 작성 경로 — Story 1.5 ``submit_health_profile`` 정합.

    형식 검증 2단: (1) Pydantic 1차 type 가드(str | None) → (2) 라우터 regex 검증
    ``_NOTIFICATION_TIME_WIRE_RE`` → ``NotificationTimeInvalidFormatError`` raise(`code=
    notification.time.invalid_format`). DB CHECK ``ck_users_notification_time_kst_format``
    은 3차 방어선(seconds=0 강제, ORM SOT).
    """
    notification_time_db: time | None = None
    if body.notification_time is not None:
        if not _NOTIFICATION_TIME_WIRE_RE.fullmatch(body.notification_time):
            raise NotificationTimeInvalidFormatError(
                detail=(
                    f"notification_time must be 'HH:MM' (24-hour), got: {body.notification_time!r}"
                ),
            )
        notification_time_db = _from_wire_time(body.notification_time)

    settings = await update_settings(
        db,
        user,
        notifications_enabled=body.notifications_enabled,
        notification_time=notification_time_db,
    )
    return _to_response(settings)


@router.post("/devices")
async def register_device(
    body: PushTokenRegisterRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
) -> dict[str, bool]:
    """token 등록 — *사용자 swap* atomic (notification_service.register_push_token 정합).

    형식 검증: Pydantic type 가드 후 라우터에서 Expo regex 검증 →
    ``NotificationTokenInvalidError`` raise(`code=notification.token.invalid`).
    """
    if not _EXPO_TOKEN_RE.fullmatch(body.expo_push_token):
        raise NotificationTokenInvalidError(
            detail=(
                "expo_push_token must match Expo prefix (ExponentPushToken[…] or ExpoPushToken[…])"
            ),
        )
    await register_push_token(
        db,
        user,
        token=body.expo_push_token,
        platform=body.platform,
    )
    return {"registered": True}


@router.delete("/devices", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
) -> None:
    """token 해제 — 멱등 (이미 NULL이어도 204).

    *Why*: 모바일 logout flow(Story 4.1 AC13) / 권한 거부 회복 / 명시 토큰 해제.
    """
    await revoke_push_token(db, user)


# --- 도메인 예외 카탈로그 노출 (router 외부에서 import 시 typed 분기) ---
# 본 카탈로그(`notification.time.invalid_format` / `notification.token.invalid`)는
# 라우터에서 직접 raise — Pydantic 가드는 type 검증에 한정하여 글로벌 ``RequestValidationError``
# 핸들러의 ``code=validation.error`` 평탄화를 회피.
__all__ = [
    "NotificationSettingsResponse",
    "NotificationSettingsUpdate",
    "NotificationTimeInvalidFormatError",
    "NotificationTokenInvalidError",
    "PushTokenRegisterRequest",
    "router",
]
