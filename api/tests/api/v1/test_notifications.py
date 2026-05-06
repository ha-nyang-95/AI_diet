"""Story 4.1 AC5 / AC15 — `/v1/notifications` router 6건 단위 테스트.

- GET /settings: 200 + 인증만 (동의 게이트 X)
- PATCH /settings: 200 + require_basic_consents 통과
- PATCH /settings: 400 + ``notification_time`` invalid format ("25:00")
- POST /devices: 200 + token 검증 통과
- POST /devices: 400 + token invalid ("foo")
- DELETE /devices: 204 idempotent (이미 NULL)
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_get_settings_auth_only_no_consent_gate(client: AsyncClient, user_factory) -> None:
    """Story 4.1 AC5 — GET은 인증만, 동의 게이트 X (PIPA Art.35 정합)."""
    user = await user_factory()  # consent 미생성 — basic consents 통과 X 시나리오
    response = await client.get(
        "/v1/notifications/settings",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["notifications_enabled"] is True
    assert body["notification_time"] == "20:00"
    assert body["notification_timezone"] == "Asia/Seoul"
    assert body["has_push_token"] is False


@pytest.mark.asyncio
async def test_patch_settings_with_consent_passes(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """Story 4.1 AC5 — PATCH는 require_basic_consents 통과 후 200."""
    user = await user_factory()
    await consent_factory(user)  # 4종 동의 부여
    response = await client.patch(
        "/v1/notifications/settings",
        json={"notifications_enabled": False, "notification_time": "07:30"},
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["notifications_enabled"] is False
    assert body["notification_time"] == "07:30"


@pytest.mark.asyncio
async def test_patch_settings_invalid_time_format(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """Story 4.1 AC5 — ``"25:00"`` 입력 시 400 + ``code=notification.time.invalid_format``.

    CR P1 — Pydantic은 type 가드만 수행하고, 형식 검증은 라우터에서
    ``NotificationTimeInvalidFormatError`` raise → 글로벌 ``BalanceNoteError`` 핸들러가
    spec 카탈로그 ``code`` 발화.
    """
    user = await user_factory()
    await consent_factory(user)
    response = await client.patch(
        "/v1/notifications/settings",
        json={"notification_time": "25:00"},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "notification.time.invalid_format"


@pytest.mark.asyncio
async def test_post_devices_with_valid_token(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """Story 4.1 AC5 — POST /devices 200 + token 검증 통과."""
    user = await user_factory()
    await consent_factory(user)
    token = f"ExponentPushToken[{uuid.uuid4().hex}]"
    response = await client.post(
        "/v1/notifications/devices",
        json={"expo_push_token": token, "platform": "ios"},
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["registered"] is True


@pytest.mark.asyncio
async def test_post_devices_invalid_token(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """Story 4.1 AC5 — ``"foo"`` token 거부 시 400 + spec 카탈로그 ``code``.

    CR P1 — 라우터에서 ``NotificationTokenInvalidError`` raise →
    ``code=notification.token.invalid`` 발화 (Pydantic ValidationError 평탄화 회피).
    """
    user = await user_factory()
    await consent_factory(user)
    response = await client.post(
        "/v1/notifications/devices",
        json={"expo_push_token": "foo", "platform": "ios"},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "notification.token.invalid"


@pytest.mark.asyncio
async def test_delete_devices_idempotent(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """Story 4.1 AC5 — DELETE는 token이 이미 NULL이어도 204 (멱등)."""
    user = await user_factory()
    await consent_factory(user)
    response = await client.delete(
        "/v1/notifications/devices",
        headers=auth_headers(user),
    )
    assert response.status_code == 204
    # 재호출 — 여전히 204 (멱등)
    response = await client.delete(
        "/v1/notifications/devices",
        headers=auth_headers(user),
    )
    assert response.status_code == 204
