"""Story 4.4 — ``PATCH/GET /v1/users/me/macro_goal`` 라우터 통합 테스트 (AC #2).

8+ 케이스: 인증 401 / consent 403 / GET 미설정 200 + ``{}`` / GET 설정 / PATCH happy
+ partial / PATCH ratio sum invalid 400 / PATCH null 송신 시 key 삭제.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.db.models.consent import Consent
from app.db.models.user import User
from tests.conftest import auth_headers

UserFactory = Callable[..., Awaitable[User]]
ConsentFactory = Callable[..., Awaitable[Consent]]


# --- GET /me/macro_goal ----------------------------------------------------


async def test_get_macro_goal_unauthenticated_returns_401(client: AsyncClient) -> None:
    response = await client.get("/v1/users/me/macro_goal")
    assert response.status_code == 401


async def test_get_macro_goal_unset_returns_empty_object(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """미설정 사용자 → 200 + 빈 ``{}`` (404 X)."""
    user = await user_factory()
    response = await client.get("/v1/users/me/macro_goal", headers=auth_headers(user))
    assert response.status_code == 200, response.text
    assert response.json() == {}


# --- PATCH /me/macro_goal --------------------------------------------------


async def test_patch_macro_goal_blocks_without_basic_consents(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """기본 동의 미부여 사용자 → 403."""
    user = await user_factory()
    response = await client.patch(
        "/v1/users/me/macro_goal",
        json={"protein_target_g_per_meal": 25},
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "consent.basic.missing"


async def test_patch_macro_goal_happy_path(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """5 필드 모두 set + ratio sum=100 → 200 + 갱신값 응답."""
    user = await user_factory()
    await consent_factory(user)
    payload = {
        "daily_calorie_target_kcal": 1800,
        "protein_target_g_per_meal": 25,
        "macro_ratio_carb_pct": 50,
        "macro_ratio_protein_pct": 25,
        "macro_ratio_fat_pct": 25,
    }
    response = await client.patch(
        "/v1/users/me/macro_goal",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["daily_calorie_target_kcal"] == 1800
    assert body["protein_target_g_per_meal"] == 25
    assert body["macro_ratio_carb_pct"] == 50

    # GET — 갱신값 그대로 조회.
    get_response = await client.get("/v1/users/me/macro_goal", headers=auth_headers(user))
    assert get_response.status_code == 200
    assert get_response.json() == payload


async def test_patch_macro_goal_partial_then_partial(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """첫 PATCH protein만 + 두 번째 PATCH calorie만 → JSONB merge 정합."""
    user = await user_factory()
    await consent_factory(user)
    r1 = await client.patch(
        "/v1/users/me/macro_goal",
        json={"protein_target_g_per_meal": 25},
        headers=auth_headers(user),
    )
    assert r1.status_code == 200, r1.text

    r2 = await client.patch(
        "/v1/users/me/macro_goal",
        json={"daily_calorie_target_kcal": 1800},
        headers=auth_headers(user),
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    # merge 정합: 두 키 모두 보존.
    assert body["protein_target_g_per_meal"] == 25
    assert body["daily_calorie_target_kcal"] == 1800


async def test_patch_macro_goal_ratio_sum_invalid_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """ratio sum != 100 → 400 + ``code=user.macro_goal.invalid``."""
    user = await user_factory()
    await consent_factory(user)
    response = await client.patch(
        "/v1/users/me/macro_goal",
        json={
            "macro_ratio_carb_pct": 50,
            "macro_ratio_protein_pct": 25,
            "macro_ratio_fat_pct": 20,
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "user.macro_goal.invalid"


async def test_patch_macro_goal_null_value_removes_key(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """null 송신 = key 삭제 분기. 첫 PATCH로 key set → 둘째 PATCH로 null 송신 → 응답에 미포함."""
    user = await user_factory()
    await consent_factory(user)
    # 첫 PATCH — protein + calorie set.
    await client.patch(
        "/v1/users/me/macro_goal",
        json={"protein_target_g_per_meal": 25, "daily_calorie_target_kcal": 1800},
        headers=auth_headers(user),
    )
    # 둘째 PATCH — protein만 null 송신(해당 키 삭제). calorie는 미송신이라 보존.
    response = await client.patch(
        "/v1/users/me/macro_goal",
        json={"protein_target_g_per_meal": None},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "protein_target_g_per_meal" not in body
    assert body["daily_calorie_target_kcal"] == 1800


async def test_patch_macro_goal_empty_body_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """빈 body ``{}`` → at-least-one 가드 400."""
    user = await user_factory()
    await consent_factory(user)
    response = await client.patch(
        "/v1/users/me/macro_goal",
        json={},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "user.macro_goal.invalid"


async def test_patch_macro_goal_null_removes_single_ratio_rejected_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """CR Patch #1 회귀 가드 — 3 ratio 모두 set된 상태에서 단 하나만 null 송신해 키 삭제
    시도 → merged 결과는 partial-set state(2 of 3) 위반 → 400 + 기존 row 보존(rollback).

    Pydantic 1차 게이트는 *patch payload*만 검증하므로 단일 null 송신은 통과(model_fields_set
    1건 + ratios 모두 None → all-null 분기). SQL UPDATE 후 merged macro_goal을
    ``MacroGoal.model_validate``로 재검증해 invariant 위반 시 rollback + 400.
    """
    user = await user_factory()
    await consent_factory(user)
    # 1) 첫 PATCH — 3 ratio 모두 set + protein/calorie 함께 저장.
    setup = await client.patch(
        "/v1/users/me/macro_goal",
        json={
            "macro_ratio_carb_pct": 50,
            "macro_ratio_protein_pct": 25,
            "macro_ratio_fat_pct": 25,
            "protein_target_g_per_meal": 25,
        },
        headers=auth_headers(user),
    )
    assert setup.status_code == 200, setup.text

    # 2) carb만 null 송신 → 단일 ratio 키 삭제 시도.
    response = await client.patch(
        "/v1/users/me/macro_goal",
        json={"macro_ratio_carb_pct": None},
        headers=auth_headers(user),
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "user.macro_goal.invalid"

    # 3) 기존 row가 그대로 보존됐는지 확인 — rollback 정합.
    after = await client.get("/v1/users/me/macro_goal", headers=auth_headers(user))
    assert after.status_code == 200
    body = after.json()
    assert body["macro_ratio_carb_pct"] == 50
    assert body["macro_ratio_protein_pct"] == 25
    assert body["macro_ratio_fat_pct"] == 25
    assert body["protein_target_g_per_meal"] == 25
