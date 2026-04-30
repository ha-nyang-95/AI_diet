"""Story 2.2 — `POST /v1/meals/images/presign` (8 케이스) +
Story 2.3 — `POST /v1/meals/images/parse` (10 케이스) endpoint 통합 테스트 (AC3 / AC11).

Story 2.2 케이스 (회귀 0건 유지):
- 정상 — 200 + 5 필드, image_key prefix `meals/<user_id>/`.
- content_type whitelist 위반 (Pydantic Literal 1차 게이트) → 400 validation.error.
- content_length 10 MB 초과 → 400 validation.error.
- content_length 0 byte → 400 validation.error.
- 인증 헤더 없음 → 401 auth.access_token.invalid.
- 동의 미통과 → 403 consent.basic.missing.
- R2 환경변수 미설정 → 503 meals.image.r2_unconfigured.
- extra field → 400 validation.error.

Story 2.3 케이스 (parse endpoint):
- 정상 — 200 + 5 필드, low_confidence=False.
- low_confidence True (mock confidence < 0.6).
- low_confidence True (빈 items).
- 인증 미통과 → 401.
- 동의 미통과 → 403.
- foreign image_key → 400 meals.image.foreign_key_rejected.
- image not uploaded → 400 meals.image.not_uploaded.
- Vision 503 → meals.image.ocr_unavailable.
- invalid image_key 형식 → 400 validation.error.
- extra field → 400 validation.error.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.adapters import openai_adapter
from app.adapters import r2 as r2_adapter
from app.core.config import settings as _settings
from app.core.exceptions import MealOCRUnavailableError
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


# --- Story 2.3 — POST /v1/meals/images/parse ---------------------------------


def _image_key_for(user: User, ext: str = "jpg") -> str:
    """user-scoped 유효한 image_key — `meals/{user_id}/{random_uuid}.{ext}`."""
    return f"meals/{user.id}/{uuid.uuid4()}.{ext}"


def _build_parse_response(items: list[dict[str, object]]) -> MagicMock:
    """`AsyncOpenAI.beta.chat.completions.parse` 응답 mock — `ParsedMeal` 직접 주입.

    CR P4 정합(2026-04-30) — `message.refusal=None` 명시 (MagicMock auto-attribute가
    truthy로 평가되어 refusal 분기 오발 방지).
    """
    parsed_meal = openai_adapter.ParsedMeal(
        items=[openai_adapter.ParsedMealItem.model_validate(item) for item in items]
    )
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed_meal
    response.choices[0].message.refusal = None
    return response


@pytest.fixture
def _vision_uploaded_and_configured(
    monkeypatch: pytest.MonkeyPatch,
    _r2_configured: None,
) -> None:
    """parse 흐름 fixture — R2 head_object_exists True mock + OpenAI client mock 자리.

    개별 테스트가 `monkeypatch.setattr(openai_adapter, "_get_client", ...)`로 client mock
    주입해 응답 시나리오 분기 (정상/장애).
    """
    monkeypatch.setattr(_settings, "openai_api_key", "sk-test-key")
    monkeypatch.setattr(r2_adapter, "head_object_exists", lambda image_key: True)
    openai_adapter._reset_client_for_tests()


def _install_vision_mock(
    monkeypatch: pytest.MonkeyPatch,
    *,
    items: list[dict[str, object]] | None = None,
    side_effect: Exception | None = None,
) -> None:
    """openai_adapter._get_client mock — items 지정 시 정상 응답, side_effect 지정 시 raise."""
    mock_parse = AsyncMock(
        return_value=_build_parse_response(items or []),
        side_effect=side_effect,
    )
    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse = mock_parse
    monkeypatch.setattr(openai_adapter, "_get_client", lambda: mock_client)


async def test_parse_returns_200_with_parsed_items(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    monkeypatch: pytest.MonkeyPatch,
    _vision_uploaded_and_configured: None,
) -> None:
    """정상 — 5 필드, low_confidence=False (모든 confidence ≥ 0.6)."""
    items = [
        {"name": "짜장면", "quantity": "1인분", "confidence": 0.92},
        {"name": "군만두", "quantity": "4개", "confidence": 0.88},
    ]
    _install_vision_mock(monkeypatch, items=items)

    user = await user_factory()
    await consent_factory(user)
    image_key = _image_key_for(user)

    response = await client.post(
        "/v1/meals/images/parse",
        json={"image_key": image_key},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body.keys()) == {
        "image_key",
        "parsed_items",
        "low_confidence",
        "model",
        "latency_ms",
    }
    assert body["image_key"] == image_key
    assert body["low_confidence"] is False
    assert body["model"] == openai_adapter.VISION_MODEL
    assert isinstance(body["latency_ms"], int)
    assert body["latency_ms"] >= 0
    assert len(body["parsed_items"]) == 2
    assert body["parsed_items"][0]["name"] == "짜장면"


async def test_parse_returns_low_confidence_true_when_below_threshold(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    monkeypatch: pytest.MonkeyPatch,
    _vision_uploaded_and_configured: None,
) -> None:
    """min(confidence) < 0.6 — low_confidence=True (모바일 forced confirmation 트리거)."""
    items = [{"name": "불명확", "quantity": "1개", "confidence": 0.55}]
    _install_vision_mock(monkeypatch, items=items)

    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals/images/parse",
        json={"image_key": _image_key_for(user)},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    assert response.json()["low_confidence"] is True


async def test_parse_returns_low_confidence_true_when_empty_items(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    monkeypatch: pytest.MonkeyPatch,
    _vision_uploaded_and_configured: None,
) -> None:
    """빈 items — low_confidence=True (음식 미인식 케이스)."""
    _install_vision_mock(monkeypatch, items=[])

    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals/images/parse",
        json={"image_key": _image_key_for(user)},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["low_confidence"] is True
    assert body["parsed_items"] == []


async def test_parse_unauthenticated_returns_401(
    client: AsyncClient,
    _vision_uploaded_and_configured: None,
) -> None:
    response = await client.post(
        "/v1/meals/images/parse",
        json={"image_key": "meals/" + str(uuid.uuid4()) + "/" + str(uuid.uuid4()) + ".jpg"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.invalid"


async def test_parse_blocks_user_without_basic_consents_returns_403(
    client: AsyncClient,
    user_factory: UserFactory,
    _vision_uploaded_and_configured: None,
) -> None:
    user = await user_factory()
    response = await client.post(
        "/v1/meals/images/parse",
        json={"image_key": _image_key_for(user)},
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "consent.basic.missing"


async def test_parse_foreign_image_key_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _vision_uploaded_and_configured: None,
) -> None:
    """다른 사용자 prefix — meals.image.foreign_key_rejected."""
    user_a = await user_factory()
    user_b = await user_factory()
    await consent_factory(user_a)

    response = await client.post(
        "/v1/meals/images/parse",
        json={"image_key": _image_key_for(user_b)},  # other user's key
        headers=auth_headers(user_a),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "meals.image.foreign_key_rejected"


async def test_parse_image_not_uploaded_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    monkeypatch: pytest.MonkeyPatch,
    _vision_uploaded_and_configured: None,
) -> None:
    """`head_object_exists` False — meals.image.not_uploaded."""
    monkeypatch.setattr(r2_adapter, "head_object_exists", lambda image_key: False)

    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals/images/parse",
        json={"image_key": _image_key_for(user)},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "meals.image.not_uploaded"


async def test_parse_ocr_unavailable_returns_503(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    monkeypatch: pytest.MonkeyPatch,
    _vision_uploaded_and_configured: None,
) -> None:
    """Vision adapter mock에서 `MealOCRUnavailableError` raise → 503."""

    # adapter.parse_meal_image 자체를 mock해서 변환된 503 예외 직행.
    async def _raise(*args: object, **kwargs: object) -> None:
        raise MealOCRUnavailableError("Vision API transient failure")

    monkeypatch.setattr(openai_adapter, "parse_meal_image", _raise)

    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals/images/parse",
        json={"image_key": _image_key_for(user)},
        headers=auth_headers(user),
    )
    assert response.status_code == 503
    assert response.json()["code"] == "meals.image.ocr_unavailable"


async def test_parse_invalid_image_key_format_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _vision_uploaded_and_configured: None,
) -> None:
    """malformed image_key — Pydantic regex 1차 게이트."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals/images/parse",
        json={"image_key": "../../etc/passwd"},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_parse_extra_field_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _vision_uploaded_and_configured: None,
) -> None:
    """`extra="forbid"` — silent unknown field 차단."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals/images/parse",
        json={"image_key": _image_key_for(user), "extra": "x"},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"
