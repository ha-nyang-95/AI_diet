"""`/v1/users/me/consents` POST/GET 라우터 테스트 (Story 1.3 AC #3, #9, #15)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.db.models.user import User
from app.domain.legal_documents import CURRENT_VERSIONS
from tests.conftest import auth_headers

UserFactory = Callable[..., Awaitable[User]]


def _payload(*, version: str | None = None) -> dict[str, str]:
    v = version or CURRENT_VERSIONS["disclaimer"]
    return {
        "disclaimer_version": v,
        "terms_version": v,
        "privacy_version": v,
        "sensitive_personal_info_version": v,
    }


@pytest.mark.asyncio
async def test_post_consents_creates_new_row_with_201(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    response = await client.post(
        "/v1/users/me/consents", json=_payload(), headers=auth_headers(user)
    )
    assert response.status_code == 201
    body = response.json()
    assert body["basic_consents_complete"] is True
    assert body["disclaimer_acknowledged_at"] is not None
    assert body["terms_consent_at"] is not None
    assert body["privacy_consent_at"] is not None
    assert body["sensitive_personal_info_consent_at"] is not None
    assert body["disclaimer_version"] == CURRENT_VERSIONS["disclaimer"]


@pytest.mark.asyncio
async def test_post_consents_updates_existing_row_with_200(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    first = await client.post("/v1/users/me/consents", json=_payload(), headers=auth_headers(user))
    assert first.status_code == 201

    second = await client.post("/v1/users/me/consents", json=_payload(), headers=auth_headers(user))
    assert second.status_code == 200
    assert second.json()["basic_consents_complete"] is True


@pytest.mark.asyncio
async def test_post_consents_rejects_version_mismatch_with_409(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    response = await client.post(
        "/v1/users/me/consents",
        json=_payload(version="ko-1900-01-01"),
        headers=auth_headers(user),
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "consent.version_mismatch"


@pytest.mark.asyncio
async def test_post_consents_rejects_missing_field_with_400(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    incomplete = {
        "disclaimer_version": CURRENT_VERSIONS["disclaimer"],
        "terms_version": CURRENT_VERSIONS["terms"],
        # privacy_version, sensitive_personal_info_version 누락
    }
    response = await client.post(
        "/v1/users/me/consents", json=incomplete, headers=auth_headers(user)
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation.error"


@pytest.mark.asyncio
async def test_get_consents_returns_all_null_when_no_row(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    response = await client.get("/v1/users/me/consents", headers=auth_headers(user))
    assert response.status_code == 200
    body = response.json()
    assert body["basic_consents_complete"] is False
    assert body["disclaimer_acknowledged_at"] is None
    assert body["terms_consent_at"] is None
    assert body["privacy_consent_at"] is None
    assert body["sensitive_personal_info_consent_at"] is None


@pytest.mark.asyncio
async def test_get_consents_returns_complete_after_post(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    await client.post("/v1/users/me/consents", json=_payload(), headers=auth_headers(user))

    response = await client.get("/v1/users/me/consents", headers=auth_headers(user))
    assert response.status_code == 200
    body = response.json()
    assert body["basic_consents_complete"] is True


@pytest.mark.asyncio
async def test_consents_router_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/v1/users/me/consents")
    assert response.status_code == 401

    post_resp = await client.post("/v1/users/me/consents", json=_payload())
    assert post_resp.status_code == 401
