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
    """기본 동의 4종 페이로드 생성 — 각 키는 ``CURRENT_VERSIONS``의 *per-doc* version.

    Story 3.8 CR DN-1 — version SOT가 doc-key별 dict로 분리됐기 때문에 ``disclaimer``/
    ``terms``는 baseline ``ko-2026-04-28``, ``privacy``/``sensitive_personal_info``는
    ``ko-2026-05-04``로 서로 다르다. 단일 ``version`` override 인자는 *전체 mismatch*
    테스트(version_mismatch_with_409)에만 사용 — 정상 흐름은 키별 SOT 정확 매핑.
    """
    if version is not None:
        return {
            "disclaimer_version": version,
            "terms_version": version,
            "privacy_version": version,
            "sensitive_personal_info_version": version,
        }
    return {
        "disclaimer_version": CURRENT_VERSIONS["disclaimer"],
        "terms_version": CURRENT_VERSIONS["terms"],
        "privacy_version": CURRENT_VERSIONS["privacy"],
        "sensitive_personal_info_version": CURRENT_VERSIONS["sensitive_personal_info"],
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
async def test_delete_automated_decision_404_when_already_revoked(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """이미 철회된 사용자가 DELETE 재호출 시 404 — 두 번째 호출이 200 으로 통과하면
    원본 ``automated_decision_revoked_at`` 이 새 ``now()`` 로 덮어써져 PIPA audit 손상."""
    user = await user_factory()
    await consent_factory(user, automated_decision=True)
    # 첫 번째 DELETE — 정상 철회.
    first = await client.delete(
        "/v1/users/me/consents/automated-decision", headers=auth_headers(user)
    )
    assert first.status_code == 200
    original_revoked_at = first.json()["automated_decision_revoked_at"]
    assert original_revoked_at is not None

    # 두 번째 DELETE — 이미 철회된 상태이므로 404.
    second = await client.delete(
        "/v1/users/me/consents/automated-decision", headers=auth_headers(user)
    )
    assert second.status_code == 404
    assert second.json()["code"] == "consent.automated_decision.not_granted"

    # GET 으로 원본 revoked_at 가 보존되었는지 확인.
    status_resp = await client.get("/v1/users/me/consents", headers=auth_headers(user))
    assert status_resp.json()["automated_decision_revoked_at"] == original_revoked_at


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


# ---------------------------------------------------------------------------
# Story 3.9 AC4 — 약관 major / minor bump 분기 (5 케이스)
# ---------------------------------------------------------------------------


async def _update_consent_version(user: User, *, field: str, value: str) -> None:
    """test 헬퍼 — consents row의 단일 ``*_version`` 컬럼만 갱신.

    ``consent_factory``는 4 version을 동시 set만 지원 — 본 헬퍼로 mixed mismatch 시나리오
    (e.g. terms major bump + privacy 정합) 구성. ``app.state.session_maker`` 직접 사용.
    """
    from sqlalchemy import update

    from app.main import app as _app

    session_maker = _app.state.session_maker
    async with session_maker() as session:
        await session.execute(
            update(Consent).where(Consent.user_id == user.id).values({field: value})
        )
        await session.commit()


@pytest.mark.asyncio
async def test_basic_consents_major_bump_blocks_with_403(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """AC4 케이스 ① — disclaimer (major) version mismatch는 403 차단."""
    user = await user_factory()
    await consent_factory(user)
    # disclaimer 버전을 stale로 강제(major 분류).
    await _update_consent_version(user, field="disclaimer_version", value="ko-1900-01-01")

    # ``require_basic_consents`` wire 라우터 호출 — POST /v1/meals 사용.
    response = await client.post(
        "/v1/meals",
        json={"raw_text": "사과 1개"},
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "consent.basic.missing"


@pytest.mark.asyncio
async def test_basic_consents_minor_bump_passes_with_header(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """AC4 케이스 ② — privacy (minor) version mismatch만 있을 때 통과 + 헤더 첨부."""
    user = await user_factory()
    await consent_factory(user)
    # privacy 버전을 stale로 강제(minor 분류). disclaimer/terms/sensitive_personal_info는 정합.
    await _update_consent_version(user, field="privacy_version", value="ko-1900-01-01")
    # Note: sensitive_personal_info는 privacy version을 공유 — 정합 유지를 위해 함께 stale.
    await _update_consent_version(
        user, field="sensitive_personal_info_version", value="ko-1900-01-01"
    )

    response = await client.post(
        "/v1/meals",
        json={"raw_text": "사과 1개"},
        headers=auth_headers(user),
    )
    assert response.status_code == 201
    # ``X-Consent-Update-Available`` 헤더에 stale doc_key=latest_version 인코딩.
    update_header = response.headers.get("x-consent-update-available", "")
    assert "privacy=" in update_header
    assert CURRENT_VERSIONS["privacy"] in update_header


@pytest.mark.asyncio
async def test_legal_document_default_version_type_is_major() -> None:
    """AC4 케이스 ③ — ``LegalDocument`` default ``version_type``는 안전 측 ``"major"``."""
    from app.domain.legal_documents import LegalDocument

    doc = LegalDocument(
        type="terms",
        lang="ko",
        version="ko-test",
        title="t",
        body="b",
        updated_at=__import__("datetime").datetime(2026, 5, 5, tzinfo=__import__("datetime").UTC),
    )
    assert doc.version_type == "major"


@pytest.mark.asyncio
async def test_basic_consents_ko_en_bump_symmetric() -> None:
    """AC4 ④ — 한·영 동기 bump 시 KO/EN 모두 동일 ``version_type``."""
    from app.domain.legal_documents import LEGAL_DOCUMENTS

    for doc_type in ("disclaimer", "terms", "privacy", "automated-decision"):
        ko = LEGAL_DOCUMENTS[(doc_type, "ko")]  # type: ignore[index]
        en = LEGAL_DOCUMENTS[(doc_type, "en")]  # type: ignore[index]
        # 한·영 양쪽 ``version_type`` 일치 — bump 시 양 언어 동기 갱신 강제.
        assert ko.version_type == en.version_type


@pytest.mark.asyncio
async def test_basic_consents_existing_user_unaffected_baseline(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """AC4 케이스 ⑤ — 현 baseline 사용자는 회귀 0건(헤더 부재 + 200/201)."""
    user = await user_factory()
    await consent_factory(user)  # current SOT 정합 — mismatch 0건
    response = await client.post(
        "/v1/meals",
        json={"raw_text": "사과 1개"},
        headers=auth_headers(user),
    )
    assert response.status_code == 201
    # 모든 doc 정합이라 헤더 *부재*.
    assert "x-consent-update-available" not in response.headers
