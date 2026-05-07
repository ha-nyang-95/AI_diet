"""Story 5.1 — ``PATCH /v1/users/me/profile`` 라우터 통합 테스트 (AC #2, #3, #8).

10+ 케이스: 인증 401 / consent 403 / happy 1 필드 / happy 6 필드 / partial 3 필드 /
at-least-one 빈 body / range out / invalid allergen / extra forbid / weight precision /
profile_completed_at 보존 invariant / audit 미wire 가드.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.api.v1 import users as users_router
from app.db.models.consent import Consent
from app.db.models.user import User
from tests.conftest import auth_headers

UserFactory = Callable[..., Awaitable[User]]
ConsentFactory = Callable[..., Awaitable[Consent]]


def _full_payload() -> dict[str, object]:
    """6 필드 모두 유효한 partial body — 각 테스트가 부분 변형."""
    return {
        "age": 30,
        "weight_kg": 70.5,
        "height_cm": 175,
        "activity_level": "moderate",
        "health_goal": "maintenance",
        "allergies": ["우유"],
    }


# --- 인증/동의 게이트 -------------------------------------------------------


async def test_patch_profile_unauthenticated_returns_401(client: AsyncClient) -> None:
    """Authorization 헤더 미포함 → 401."""
    response = await client.patch("/v1/users/me/profile", json={"age": 35})
    assert response.status_code == 401


async def test_patch_profile_blocks_without_basic_consents_returns_403(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """기본 동의 미부여 사용자 → 403 + ``code=consent.basic.missing``.

    *Why*: ``Depends(require_basic_consents)`` wire 회귀 차단(자기 데이터 *작성* 라우트
    는 동의 게이트 SOT — Story 1.5 W14 정합).
    """
    user = await user_factory()
    response = await client.patch(
        "/v1/users/me/profile",
        json={"age": 35},
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "consent.basic.missing"


# --- happy-path -------------------------------------------------------------


async def test_patch_profile_single_field_returns_200_and_sets_profile_updated_at(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """Story 5.1 AC2 — 1 필드만 PATCH → 200 + 갱신값 + ``profile_updated_at`` set +
    ``profile_completed_at`` 보존.

    weight_kg 70.0 → 80.0. 다른 5 필드는 user_factory 기본값 보존(미터치 invariant).
    """
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    response = await client.patch(
        "/v1/users/me/profile",
        json={"weight_kg": 80.0},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["weight_kg"] == 80.0
    # 미송신 5 필드는 기본값(user_factory profile_completed=True default) 보존.
    assert body["age"] == 30
    assert body["height_cm"] == 170
    assert body["activity_level"] == "moderate"
    assert body["health_goal"] == "maintenance"
    assert body["allergies"] == []
    # profile_updated_at은 set, profile_completed_at은 미터치 invariant.
    assert body["profile_updated_at"] is not None
    assert body["profile_completed_at"] is not None


async def test_patch_profile_all_fields_returns_200(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """6 필드 모두 PATCH → 200 + 갱신값 응답(POST와 equiv-replace 동작)."""
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    payload = _full_payload()
    payload["age"] = 45
    payload["weight_kg"] = 80.0
    payload["health_goal"] = "weight_loss"

    response = await client.patch(
        "/v1/users/me/profile",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["age"] == 45
    assert body["weight_kg"] == 80.0
    assert body["height_cm"] == 175
    assert body["activity_level"] == "moderate"
    assert body["health_goal"] == "weight_loss"
    assert body["allergies"] == ["우유"]
    assert body["profile_updated_at"] is not None


async def test_patch_profile_partial_three_fields_preserves_unsent(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """allergies + age + activity_level 3 필드 PATCH → 미송신 3 필드(weight_kg/height_cm/
    health_goal) 보존."""
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    response = await client.patch(
        "/v1/users/me/profile",
        json={
            "age": 28,
            "activity_level": "active",
            "allergies": ["땅콩", "우유"],
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["age"] == 28
    assert body["activity_level"] == "active"
    assert sorted(body["allergies"]) == sorted(["땅콩", "우유"])
    # 미송신 3 필드 보존(user_factory 기본값).
    assert body["weight_kg"] == 70.0
    assert body["height_cm"] == 170
    assert body["health_goal"] == "maintenance"


# --- 검증 분기 --------------------------------------------------------------


async def test_patch_profile_empty_body_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """Story 5.1 AC2 — 빈 body ``{}`` → 400 + ``code=validation.error``.

    ``model_fields_set``이 빈 set이면 at-least-one 가드 fail. Story 4.4
    ``MacroGoalPatchRequest`` 패턴 정합.
    """
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    response = await client.patch(
        "/v1/users/me/profile",
        json={},
        headers=auth_headers(user),
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "validation.error"


async def test_patch_profile_range_out_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """weight_kg 600 (> 500) → 400 + ``code=validation.error``."""
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    response = await client.patch(
        "/v1/users/me/profile",
        json={"weight_kg": 600.0},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_patch_profile_invalid_allergen_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """22종 외 allergen → 400 + ``code=validation.error``.

    Story 1.5 ``normalize_allergens`` SOT 재사용 회귀 가드.
    """
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    response = await client.patch(
        "/v1/users/me/profile",
        json={"allergies": ["unknown_food"]},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_patch_profile_extra_field_forbidden_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """``extra="forbid"`` — unknown 필드 → 400 (Story 1.5 SOT 정합)."""
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    response = await client.patch(
        "/v1/users/me/profile",
        json={"age": 30, "unknown_field": "x"},
        headers=auth_headers(user),
    )
    assert response.status_code == 400


async def test_patch_profile_weight_precision_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """Story 1.5 ``_validate_weight_precision`` 회귀 가드 — 70.55 (소수 2자리) → 400.

    DB ``Numeric(5,1)`` silent rounding 차단(Story 5.1 prefill UX 정합).
    """
    user = await user_factory(profile_completed=True)
    await consent_factory(user)
    response = await client.patch(
        "/v1/users/me/profile",
        json={"weight_kg": 70.55},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


# --- AC3: profile_completed_at 보존 invariant -------------------------------


async def test_patch_profile_preserves_profile_completed_at(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """Story 5.1 AC3 — POST → PATCH chain시 ``profile_completed_at`` invariant 보존 +
    ``profile_updated_at``만 set.

    *Why*: epics.md:790 — *최초 입력 시점*과 *마지막 수정 시점*을 분리 SOT 유지.
    """
    user = await user_factory(profile_completed=True)
    await consent_factory(user)

    # 1) POST로 명시적 최초 입력(profile_completed_at = T0).
    post_response = await client.post(
        "/v1/users/me/profile",
        json=_full_payload(),
        headers=auth_headers(user),
    )
    assert post_response.status_code == 200
    completed_at_t0 = post_response.json()["profile_completed_at"]
    assert completed_at_t0 is not None
    # POST 후에는 profile_updated_at가 NULL — POST는 *최초 입력* SOT.
    assert post_response.json()["profile_updated_at"] is None

    # 2) PATCH로 수정(profile_updated_at = T1).
    patch_response = await client.patch(
        "/v1/users/me/profile",
        json={"weight_kg": 80.0},
        headers=auth_headers(user),
    )
    assert patch_response.status_code == 200
    body = patch_response.json()
    # profile_completed_at 보존(invariant).
    assert body["profile_completed_at"] == completed_at_t0
    # profile_updated_at set(처음 set).
    assert body["profile_updated_at"] is not None
    # T1 >= T0 (or strictly after) — clock skew 회피하려고 strict ordering 미강제.


# --- AC8: 일반 사용자 자기 수정은 audit_admin_action 미wire ----------------


async def test_patch_profile_endpoint_does_not_wire_audit_admin_action() -> None:
    """Story 5.1 AC8 — ``patch_health_profile`` endpoint signature에 ``audit_*`` Dependency
    미진입 가드.

    *Why*: epics.md:792 + PIPA Art.35 자기 데이터 권리 정합 — 일반 사용자 자기 수정은
    audit log 미기록(Epic 7 admin 수정만 audit). FR37 분리 SOT.

    ``inspect.signature``로 Depends 메타데이터를 검사 — ``audit_*`` 이름의 Dependency
    가 wire되어 있으면 fail. ``require_basic_consents`` 만 dependency 게이트로 OK.
    Epic 7이 ``audit_admin_action`` Dependency를 도입한 후 본 endpoint에 *실수로* wire
    되는 회귀를 차단하는 가드(현재 ``audit_*`` 함수는 deps.py에 미존재).
    """
    # ``from __future__ import annotations`` (PEP 563)이 활성화돼 있으면 ``param.annotation``
    # 은 string 형태 — ``get_type_hints(include_extras=True)``로 실 타입(Annotated 메타데이터
    # 포함) 해석.
    type_hints = typing.get_type_hints(users_router.patch_health_profile, include_extras=True)
    sig = inspect.signature(users_router.patch_health_profile)
    seen_dep_names: list[str] = []
    for param_name in sig.parameters:
        annotation = type_hints.get(param_name)
        metadata = getattr(annotation, "__metadata__", ())
        for meta in metadata:
            dep_callable = getattr(meta, "dependency", None)
            if dep_callable is None:
                continue
            dep_name = getattr(dep_callable, "__name__", str(dep_callable))
            seen_dep_names.append(dep_name)
            assert not dep_name.startswith("audit_"), (
                f"audit_* dependency must NOT wire to patch_health_profile "
                f"(param={param_name}, dep={dep_name}); "
                "PIPA Art.35 자기 데이터 권리 정합 — Epic 7 admin endpoint만 audit."
            )
    # 양성 가드 — ``require_basic_consents``는 wire되어 있어야 함(Story 1.5 W14 SOT).
    assert "require_basic_consents" in seen_dep_names, (
        f"require_basic_consents must wire to patch_health_profile (W14 SOT). seen={seen_dep_names}"
    )
