"""`/v1/users/me/consents` POST/GET 라우터 테스트 (Story 1.3 AC #3, #9, #15 +
Story 1.4 AC #3, #4, #5, #11, #15)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.db.models.consent import Consent
from app.db.models.user import User
from app.domain.legal_documents import CURRENT_VERSIONS
from tests.conftest import auth_headers

UserFactory = Callable[..., Awaitable[User]]
ConsentFactory = Callable[..., Awaitable[Consent]]


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
    # Story 1.4 W13 — 409 응답에 X-Consent-Latest-Version 헤더 첨부 회귀 차단.
    header = response.headers.get("x-consent-latest-version", "")
    # 첫 mismatch entry(disclaimer)만 인코딩 — _validate_versions 순서 정합.
    assert header == f"disclaimer={CURRENT_VERSIONS['disclaimer']}"


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


# ---------------------------------------------------------------------------
# Story 1.4 — 자동화 의사결정 동의 grant / revoke (AC #3, #4, #5, #11, #15)
# ---------------------------------------------------------------------------


def _ad_payload(*, version: str | None = None) -> dict[str, str]:
    return {"automated_decision_version": version or CURRENT_VERSIONS["automated-decision"]}


@pytest.mark.asyncio
async def test_post_automated_decision_grants_for_new_row(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """row 부재 사용자라도 INSERT — basic 4 컬럼은 NULL 유지(가드 false)."""
    user = await user_factory()
    response = await client.post(
        "/v1/users/me/consents/automated-decision",
        json=_ad_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["automated_decision_consent_at"] is not None
    assert body["automated_decision_revoked_at"] is None
    assert body["automated_decision_version"] == CURRENT_VERSIONS["automated-decision"]
    # basic 미통과 사용자라 결합 boolean은 false (AC4 결정).
    assert body["basic_consents_complete"] is False
    assert body["automated_decision_consent_complete"] is False


@pytest.mark.asyncio
async def test_post_automated_decision_grants_after_basic(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """basic 4종 통과 사용자가 grant 시 ``automated_decision_consent_complete=True``."""
    user = await user_factory()
    basic = await client.post("/v1/users/me/consents", json=_payload(), headers=auth_headers(user))
    assert basic.status_code == 201

    response = await client.post(
        "/v1/users/me/consents/automated-decision",
        json=_ad_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["basic_consents_complete"] is True
    assert body["automated_decision_consent_complete"] is True
    assert body["automated_decision_revoked_at"] is None


@pytest.mark.asyncio
async def test_post_automated_decision_resets_revoked_on_regrant(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """이전에 철회한 사용자가 재동의 시 ``automated_decision_revoked_at`` NULL reset."""
    user = await user_factory()
    await consent_factory(user, automated_decision=True, automated_decision_revoked=True)

    response = await client.post(
        "/v1/users/me/consents/automated-decision",
        json=_ad_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["automated_decision_revoked_at"] is None
    assert body["automated_decision_consent_at"] is not None


@pytest.mark.asyncio
async def test_post_automated_decision_rejects_version_mismatch_with_409(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """`X-Consent-Latest-Version: automated-decision=<SOT>` 헤더 첨부 검증."""
    user = await user_factory()
    response = await client.post(
        "/v1/users/me/consents/automated-decision",
        json=_ad_payload(version="ko-1900-01-01"),
        headers=auth_headers(user),
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "consent.automated_decision.version_mismatch"
    header = response.headers.get("x-consent-latest-version", "")
    assert header == f"automated-decision={CURRENT_VERSIONS['automated-decision']}"


@pytest.mark.asyncio
async def test_post_automated_decision_rejects_missing_field_with_400(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    response = await client.post(
        "/v1/users/me/consents/automated-decision",
        json={},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


@pytest.mark.asyncio
async def test_post_automated_decision_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/v1/users/me/consents/automated-decision", json=_ad_payload())
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_automated_decision_revokes_existing_consent(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user, automated_decision=True)

    response = await client.delete(
        "/v1/users/me/consents/automated-decision", headers=auth_headers(user)
    )
    assert response.status_code == 200
    body = response.json()
    # consent_at 보존 + revoked_at 기록 + complete=false.
    assert body["automated_decision_consent_at"] is not None
    assert body["automated_decision_revoked_at"] is not None
    assert body["automated_decision_consent_complete"] is False


@pytest.mark.asyncio
async def test_delete_automated_decision_404_when_no_row(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    response = await client.delete(
        "/v1/users/me/consents/automated-decision", headers=auth_headers(user)
    )
    assert response.status_code == 404
    assert response.json()["code"] == "consent.automated_decision.not_granted"


@pytest.mark.asyncio
async def test_delete_automated_decision_404_when_consent_at_null(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """basic만 통과(AD 미동의) 사용자가 DELETE 시 404."""
    user = await user_factory()
    await consent_factory(user)  # basic 4종만, AD False
    response = await client.delete(
        "/v1/users/me/consents/automated-decision", headers=auth_headers(user)
    )
    assert response.status_code == 404
    assert response.json()["code"] == "consent.automated_decision.not_granted"


@pytest.mark.asyncio
async def test_delete_automated_decision_requires_auth(client: AsyncClient) -> None:
    response = await client.delete("/v1/users/me/consents/automated-decision")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_consents_exposes_automated_decision_fields(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """GET 응답에 신규 4 필드 노출 + complete boolean 정합 검증."""
    user = await user_factory()
    await consent_factory(user, automated_decision=True)

    response = await client.get("/v1/users/me/consents", headers=auth_headers(user))
    assert response.status_code == 200
    body = response.json()
    assert "automated_decision_consent_at" in body
    assert "automated_decision_revoked_at" in body
    assert "automated_decision_version" in body
    assert "automated_decision_consent_complete" in body
    # basic + AD 둘 다 통과 → 결합 complete=true.
    assert body["basic_consents_complete"] is True
    assert body["automated_decision_consent_complete"] is True
    assert body["automated_decision_revoked_at"] is None


@pytest.mark.asyncio
async def test_get_consents_complete_false_when_only_basic(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)  # basic 4종만
    response = await client.get("/v1/users/me/consents", headers=auth_headers(user))
    body = response.json()
    assert body["basic_consents_complete"] is True
    assert body["automated_decision_consent_complete"] is False
