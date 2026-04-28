"""Story 1.5 — `POST/GET /v1/users/me/profile` 라우터 통합 테스트 (AC #2, #3, #14).

12+ 케이스 커버: 정상 입력, 재입력, 동의 게이트(W14 wire), 검증 분기 (age/weight/
height/enum/22종 알레르기), dedup, 빈 배열, 401 인증, GET 미입력/입력 완료.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.db.models.consent import Consent
from app.db.models.user import User
from app.domain.allergens import KOREAN_22_ALLERGENS
from tests.conftest import auth_headers

UserFactory = Callable[..., Awaitable[User]]
ConsentFactory = Callable[..., Awaitable[Consent]]


def _valid_payload() -> dict[str, object]:
    """6 필드 모두 유효한 기본 payload — 각 테스트가 필요 시 부분 변형."""
    return {
        "age": 30,
        "weight_kg": 70.5,
        "height_cm": 175,
        "activity_level": "moderate",
        "health_goal": "maintenance",
        "allergies": ["우유"],
    }


# --- POST /me/profile (AC2) ---


async def test_post_profile_creates_initial_values_returns_200(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """동의 통과 사용자 + 6 필드 입력 → 200 + 7 필드 응답 + profile_completed_at set."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/users/me/profile",
        json=_valid_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["age"] == 30
    assert body["weight_kg"] == 70.5
    assert body["height_cm"] == 175
    assert body["activity_level"] == "moderate"
    assert body["health_goal"] == "maintenance"
    assert body["allergies"] == ["우유"]
    assert body["profile_completed_at"] is not None


async def test_post_profile_updates_existing_returns_200(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """이미 입력된 사용자가 다시 POST → 200 + 갱신값 반영 + profile_completed_at 갱신."""
    user = await user_factory(profile_completed=True)
    await consent_factory(user)

    new_payload = _valid_payload()
    new_payload["age"] = 45
    new_payload["weight_kg"] = 80.0
    new_payload["health_goal"] = "weight_loss"

    response = await client.post(
        "/v1/users/me/profile",
        json=new_payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["age"] == 45
    assert body["weight_kg"] == 80.0
    assert body["health_goal"] == "weight_loss"
    assert body["profile_completed_at"] is not None


async def test_post_profile_blocks_user_without_basic_consents_returns_403(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """동의 미통과 사용자 → 403 + code=consent.basic.missing (W14 wire 회귀 차단)."""
    user = await user_factory()
    # consent_factory 호출 X — basic_consents_complete=false 상태.

    response = await client.post(
        "/v1/users/me/profile",
        json=_valid_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "consent.basic.missing"


async def test_post_profile_blocks_user_with_partial_consents_returns_403(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """4종 중 일부만 통과(sensitive 누락) → 403 — PIPA 23조 별도 동의 회귀 차단."""
    user = await user_factory()
    await consent_factory(user, sensitive=False)

    response = await client.post(
        "/v1/users/me/profile",
        json=_valid_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "consent.basic.missing"


async def test_post_profile_rejects_missing_field_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """필수 필드(age) 누락 → 400 + code=validation.error."""
    user = await user_factory()
    await consent_factory(user)
    payload = _valid_payload()
    del payload["age"]

    response = await client.post(
        "/v1/users/me/profile",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_post_profile_rejects_age_out_of_range_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """age 범위 초과 (-1, 0, 151) → 400."""
    user = await user_factory()
    await consent_factory(user)
    for invalid_age in (-1, 0, 151, 200):
        payload = _valid_payload()
        payload["age"] = invalid_age
        response = await client.post(
            "/v1/users/me/profile",
            json=payload,
            headers=auth_headers(user),
        )
        assert response.status_code == 400, f"age={invalid_age} should reject"
        assert response.json()["code"] == "validation.error"


async def test_post_profile_rejects_weight_out_of_range_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """weight_kg 범위 초과 (0.5, 500.1) → 400."""
    user = await user_factory()
    await consent_factory(user)
    for invalid_weight in (0.5, 0.0, -1.0, 500.1, 1000.0):
        payload = _valid_payload()
        payload["weight_kg"] = invalid_weight
        response = await client.post(
            "/v1/users/me/profile",
            json=payload,
            headers=auth_headers(user),
        )
        assert response.status_code == 400, f"weight_kg={invalid_weight} should reject"
        assert response.json()["code"] == "validation.error"


async def test_post_profile_rejects_height_out_of_range_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """height_cm 범위 초과 (49, 301) → 400."""
    user = await user_factory()
    await consent_factory(user)
    for invalid_height in (49, 0, -10, 301, 500):
        payload = _valid_payload()
        payload["height_cm"] = invalid_height
        response = await client.post(
            "/v1/users/me/profile",
            json=payload,
            headers=auth_headers(user),
        )
        assert response.status_code == 400, f"height_cm={invalid_height} should reject"
        assert response.json()["code"] == "validation.error"


async def test_post_profile_rejects_invalid_activity_level_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """activity_level 5 enum 외 값 → 400."""
    user = await user_factory()
    await consent_factory(user)
    payload = _valid_payload()
    payload["activity_level"] = "extreme"

    response = await client.post(
        "/v1/users/me/profile",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_post_profile_rejects_invalid_health_goal_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """health_goal 4 enum 외 값 → 400."""
    user = await user_factory()
    await consent_factory(user)
    payload = _valid_payload()
    payload["health_goal"] = "ketogenic"

    response = await client.post(
        "/v1/users/me/profile",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_post_profile_rejects_unknown_allergen_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """allergies 22종 외 항목 → 400 + detail/errors에 unknown allergen 메시지."""
    user = await user_factory()
    await consent_factory(user)
    payload = _valid_payload()
    payload["allergies"] = ["unknown_allergen"]

    response = await client.post(
        "/v1/users/me/profile",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation.error"
    # validation_exception_handler는 errors 배열에 msg 필드로 ValueError 메시지 forward.
    serialized = str(body)
    assert "unknown allergen" in serialized
    assert "unknown_allergen" in serialized


async def test_post_profile_dedups_duplicate_allergens(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """allergies 중복 dedup — ['우유', '우유', '메밀'] → ['우유', '메밀'] (정의 순)."""
    user = await user_factory()
    await consent_factory(user)
    payload = _valid_payload()
    payload["allergies"] = ["메밀", "우유", "메밀"]

    response = await client.post(
        "/v1/users/me/profile",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    # KOREAN_22_ALLERGENS 정의 순 — 우유(0번째) → 메밀(1번째).
    assert response.json()["allergies"] == ["우유", "메밀"]


async def test_post_profile_accepts_empty_allergies(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """allergies=[] → 200 + 응답 allergies=[] (알레르기 없음 의미)."""
    user = await user_factory()
    await consent_factory(user)
    payload = _valid_payload()
    payload["allergies"] = []

    response = await client.post(
        "/v1/users/me/profile",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    assert response.json()["allergies"] == []


async def test_post_profile_default_allergies_when_omitted(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """allergies 필드 미지정 → default_factory=list로 [] 처리 → 200."""
    user = await user_factory()
    await consent_factory(user)
    payload = _valid_payload()
    del payload["allergies"]

    response = await client.post(
        "/v1/users/me/profile",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    assert response.json()["allergies"] == []


async def test_post_profile_accepts_all_22_allergens(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """22종 모두 동시 입력 → 200 + 정의 순 정렬 응답."""
    user = await user_factory()
    await consent_factory(user)
    payload = _valid_payload()
    payload["allergies"] = list(KOREAN_22_ALLERGENS)

    response = await client.post(
        "/v1/users/me/profile",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    assert response.json()["allergies"] == list(KOREAN_22_ALLERGENS)


async def test_post_profile_requires_token_returns_401(
    client: AsyncClient,
) -> None:
    """JWT 누락 → 401 (current_user → require_basic_consents chain의 인증 단계)."""
    response = await client.post("/v1/users/me/profile", json=_valid_payload())
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.invalid"


async def test_post_profile_rejects_extra_field(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """extra='forbid' — 정의되지 않은 필드 보내면 400 (Pydantic ValidationError)."""
    user = await user_factory()
    await consent_factory(user)
    payload = _valid_payload()
    payload["unknown_field"] = "abc"

    response = await client.post(
        "/v1/users/me/profile",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


# --- GET /me/profile (AC3) ---


async def test_get_profile_unfilled_user_returns_200_with_nulls(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """미입력 사용자 → 200 + 6 필드 NULL + allergies=[] + profile_completed_at=null."""
    user = await user_factory()  # profile_completed=False (default)

    response = await client.get(
        "/v1/users/me/profile",
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["age"] is None
    assert body["weight_kg"] is None
    assert body["height_cm"] is None
    assert body["activity_level"] is None
    assert body["health_goal"] is None
    assert body["allergies"] == []  # NULL → 빈 배열 fallback
    assert body["profile_completed_at"] is None


async def test_get_profile_filled_user_returns_all_fields(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """입력 완료 사용자 → 200 + 모든 필드 prefilled."""
    user = await user_factory(
        profile_completed=True,
        allergies=["우유", "메밀"],
    )

    response = await client.get(
        "/v1/users/me/profile",
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["age"] == 30
    assert body["weight_kg"] == 70.0
    assert body["height_cm"] == 170
    assert body["activity_level"] == "moderate"
    assert body["health_goal"] == "maintenance"
    assert body["allergies"] == ["우유", "메밀"]
    assert body["profile_completed_at"] is not None


async def test_get_profile_no_consent_gate(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """GET은 require_basic_consents wire X — 동의 미통과 사용자도 200."""
    user = await user_factory()
    # consent_factory 미호출 — 동의 미통과 상태에서도 자기 정보 조회 허용.

    response = await client.get(
        "/v1/users/me/profile",
        headers=auth_headers(user),
    )
    assert response.status_code == 200


async def test_get_profile_requires_token_returns_401(
    client: AsyncClient,
) -> None:
    """JWT 누락 → 401."""
    response = await client.get("/v1/users/me/profile")
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.invalid"
