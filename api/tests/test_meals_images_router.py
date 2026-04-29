"""Story 2.2 — `POST /v1/meals/images/presign` endpoint 통합 테스트 (AC3 / AC12).

8 케이스:
- 정상 — 200 + 5 필드, image_key prefix `meals/<user_id>/`.
- content_type whitelist 위반 (Pydantic Literal 1차 게이트) → 400 validation.error.
- content_length 10 MB 초과 → 400 validation.error.
- content_length 0 byte → 400 validation.error.
- 인증 헤더 없음 → 401 auth.access_token.invalid.
- 동의 미통과 → 403 consent.basic.missing.
- R2 환경변수 미설정 → 503 meals.image.r2_unconfigured.
- extra field → 400 validation.error.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.adapters import r2 as r2_adapter
from app.core.config import settings as _settings
from app.db.models.consent import Consent
from app.db.models.user import User
from tests.conftest import auth_headers

UserFactory = Callable[..., Awaitable[User]]
ConsentFactory = Callable[..., Awaitable[Consent]]


@pytest.fixture(autouse=True)
def _reset_r2_client_singleton() -> None:
    """매 테스트 전 boto3 client singleton 무효화 — settings monkeypatch 반영."""
    r2_adapter._reset_client_for_tests()


@pytest.fixture
def _r2_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """test settings에 R2 환경변수 5종 주입."""
    monkeypatch.setattr(_settings, "r2_account_id", "test-account-id")
    monkeypatch.setattr(_settings, "r2_access_key_id", "test-access-key")
    monkeypatch.setattr(_settings, "r2_secret_access_key", "test-secret-key")
    monkeypatch.setattr(_settings, "r2_bucket", "test-bucket")
    monkeypatch.setattr(_settings, "r2_public_base_url", "https://cdn.example.com")


def _valid_payload() -> dict[str, object]:
    return {"content_type": "image/jpeg", "content_length": 1234567}


# --- 정상 흐름 -----------------------------------------------------------------


async def test_presign_returns_200_with_url_and_key(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals/images/presign",
        json=_valid_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body.keys()) == {
        "upload_url",
        "image_key",
        "public_url",
        "expires_at",
        "content_type",
    }
    assert body["image_key"].startswith(f"meals/{user.id}/")
    assert body["image_key"].endswith(".jpg")
    assert body["content_type"] == "image/jpeg"
    assert "X-Amz-Signature=" in body["upload_url"]
    assert body["public_url"] == f"https://cdn.example.com/{body['image_key']}"


# --- Pydantic 1차 게이트 (whitelist / Field bounds) ---------------------------


async def test_presign_unsupported_content_type_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals/images/presign",
        json={"content_type": "image/gif", "content_length": 1234},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_presign_oversize_content_length_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals/images/presign",
        json={"content_type": "image/jpeg", "content_length": 11 * 1024 * 1024},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_presign_zero_content_length_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals/images/presign",
        json={"content_type": "image/jpeg", "content_length": 0},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_presign_extra_field_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
) -> None:
    """`extra="forbid"` — silent unknown field 차단."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals/images/presign",
        json={"content_type": "image/jpeg", "content_length": 1234, "extra": "x"},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


# --- 인증·동의 게이트 ----------------------------------------------------------


async def test_presign_unauthenticated_returns_401(
    client: AsyncClient,
    _r2_configured: None,
) -> None:
    response = await client.post("/v1/meals/images/presign", json=_valid_payload())
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.invalid"


async def test_presign_blocks_user_without_basic_consents_returns_403(
    client: AsyncClient,
    user_factory: UserFactory,
    _r2_configured: None,
) -> None:
    user = await user_factory()
    response = await client.post(
        "/v1/meals/images/presign",
        json=_valid_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "consent.basic.missing"


# --- adapter-level 게이트 (R2 미설정) -----------------------------------------


async def test_presign_r2_unconfigured_returns_503(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """settings 환경변수 미설정 시 503 fail-fast — dev/CI 안전 흐름."""
    user = await user_factory()
    await consent_factory(user)
    # 명시적으로 envs 비움 (R2 client 생성 차단).
    monkeypatch.setattr(_settings, "r2_account_id", "")
    monkeypatch.setattr(_settings, "r2_access_key_id", "")
    monkeypatch.setattr(_settings, "r2_secret_access_key", "")
    monkeypatch.setattr(_settings, "r2_bucket", "")

    response = await client.post(
        "/v1/meals/images/presign",
        json=_valid_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 503
    assert response.json()["code"] == "meals.image.r2_unconfigured"
