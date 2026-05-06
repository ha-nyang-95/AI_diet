"""Notification settings + push token service — Story 4.1.

설정 조회/갱신 + Expo push token UPSERT/revoke 4 helper. ``app/api/v1/notifications.py``의
4 endpoint가 본 모듈을 호출. Story 4.2 APScheduler nudge cron이 ``notifications_enabled``
+ ``notification_time`` + ``notification_timezone`` + ``expo_push_token`` 4컬럼을 SOT로
소비.

설계 정합:

- ``update_settings`` — partial PATCH(``None`` field skip) + ``UPDATE ... RETURNING``
  race-free 응답(Story 1.5 ``submit_health_profile`` 패턴 정합).
- ``register_push_token`` — *사용자 swap* atomic 트랜잭션. 동일 token이 다른 user row에
  박혀 있으면 *해당 row*의 ``expo_push_token``을 NULL set 후 새 user에 set
  (``ux_users_expo_push_token_active`` partial UNIQUE 위반 회피 + 사용자 swap 정합).
  AsyncSession의 implicit auto-begin이 두 ``db.execute(update(...))``를 단일 트랜잭션으로
  묶고 마지막 ``db.commit()``으로 확정 — 프로젝트 컨벤션(`update_settings`/`revoke_push_token`/
  Story 1.5 ``submit_health_profile`` 정합)이라 별도 ``async with db.begin()`` 블록은 사용 X.
  *Race window*: 동시 등록으로 다른 세션이 같은 token으로 진입하면 partial UNIQUE 위반
  → IntegrityError(데이터 손상은 partial UNIQUE 안전망이 차단). MVP <100 user 규모에서
  발생 확률 극희박 — Story 8.4 polish에서 SELECT FOR UPDATE row-lock 또는 IntegrityError
  catch+retry로 hardening 가능.
- ``revoke_push_token`` — ``expo_push_token = NULL`` 멱등 set (이미 NULL이어도 OK).

NFR-S5 마스킹 정합 — 4 helper 모두 ``app/core/observability.py`` ``_LANGSMITH_MASKED_KEYS``
영향 없음. ``expo_push_token``은 Expo 자체 식별자(사용자 신원과 결합 X), ``notification_time``
/ ``notifications_enabled``는 PII 분류 외. Sentry/LangSmith 룰셋 추가 X.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Literal

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User


@dataclass(frozen=True)
class NotificationSettings:
    """Story 4.1 — 4컬럼 + ``permission_likely_granted`` 추정값.

    ``permission_likely_granted``는 ``expo_push_token IS NOT NULL`` 추정 — token이
    있으면 모바일이 *최근 등록 성공*이므로 OS 권한 likely granted. 정확한 OS 권한
    상태는 모바일 클라이언트가 별도 보고(``useNotificationPermission`` hook).
    """

    notifications_enabled: bool
    notification_time: time
    notification_timezone: str
    has_push_token: bool
    permission_likely_granted: bool


async def get_settings(db: AsyncSession, user: User) -> NotificationSettings:
    """현 사용자 알림 설정 4컬럼 + ``permission_likely_granted`` 추정.

    *Why*: ``GET /v1/notifications/settings``가 본 함수를 호출해 응답 모델 build.
    """
    has_token = user.expo_push_token is not None
    return NotificationSettings(
        notifications_enabled=user.notifications_enabled,
        notification_time=user.notification_time,
        notification_timezone=user.notification_timezone,
        has_push_token=has_token,
        permission_likely_granted=has_token,
    )


async def update_settings(
    db: AsyncSession,
    user: User,
    *,
    notifications_enabled: bool | None = None,
    notification_time: time | None = None,
) -> NotificationSettings:
    """partial PATCH — None field skip. ``UPDATE ... RETURNING`` race-free.

    *Why*: 모바일은 Switch 토글(``notifications_enabled`` 단독) 또는 TimePicker 변경
    (``notification_time`` 단독) 또는 둘 다 보낸다. 미지정 field는 보존.

    ``notification_timezone``은 본 스토리 OUT (MVP 한국 사용자 한정 — UI 미노출).
    Story 8.4 polish forward.

    Story 1.5 ``submit_health_profile`` 패턴 정합:
    1) ``UPDATE ... RETURNING``으로 commit 전에 응답 build.
    2) ``populate_existing=True``로 ORM cache 강제 갱신.
    3) commit.
    """
    values: dict[str, object] = {}
    if notifications_enabled is not None:
        values["notifications_enabled"] = notifications_enabled
    if notification_time is not None:
        values["notification_time"] = notification_time

    if not values:
        # 변경 사항 0건 — 현 상태 그대로 응답(no-op도 200 정합).
        return await get_settings(db, user)

    result = await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(**values)
        .returning(User)
        .execution_options(populate_existing=True)
    )
    updated_user = result.scalar_one()
    response = await get_settings(db, updated_user)
    await db.commit()
    return response


async def register_push_token(
    db: AsyncSession,
    user: User,
    *,
    token: str,
    platform: Literal["ios", "android", "web"],
) -> None:
    """INSERT-or-UPDATE — 사용자 swap atomic.

    *Why*: 동일 device가 사용자 A → 사용자 B 순으로 로그인하면 동일 token이 두 user
    row에 박혀 ``ux_users_expo_push_token_active`` partial UNIQUE 위반. 본 함수는:

    1) 다른 user의 동일 token row를 찾아 ``expo_push_token = NULL`` set.
    2) 본 user에게 token set.

    두 UPDATE 모두 단일 트랜잭션 atomic — race window에 token이 *떠 있는*(어느 user에도
    매핑 안 된) 순간이 있어도 partial UNIQUE는 NULL 허용이라 위반 X.

    ``platform`` 파라미터는 현재 미사용(향후 multi-device 시점에 device row 분리될
    가능성 — Story 8.4 polish forward). 본 스토리는 단일 token만 user row에 직접 박음.
    """
    # 1) 다른 user에 박힌 동일 token NULL set (token이 본인 row에 이미 있을 수도 있음 —
    #    그 경우 자기 row를 NULL set 후 다시 set하지만 결과는 동일).
    await db.execute(
        update(User)
        .where(User.expo_push_token == token, User.id != user.id)
        .values(expo_push_token=None)
    )

    # 2) 본 user에 token set.
    await db.execute(update(User).where(User.id == user.id).values(expo_push_token=token))
    await db.commit()


async def revoke_push_token(db: AsyncSession, user: User) -> None:
    """``expo_push_token = NULL`` 멱등 set.

    *Why*: 사용자 logout / 권한 거부 회복 / 명시 토큰 해제 시 호출. 이미 NULL이어도
    no-op (UPDATE는 row를 1개 set하지만 값 변동 X — 멱등). 모바일 클라이언트가
    중복 DELETE 호출해도 204.
    """
    await db.execute(update(User).where(User.id == user.id).values(expo_push_token=None))
    await db.commit()
