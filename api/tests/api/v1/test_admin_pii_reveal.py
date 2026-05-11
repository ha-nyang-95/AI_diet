"""Story 7.4 AC2/AC6 — ``POST /v1/admin/users/{user_id}/pii-reveal`` PII unmask + audit.

테스트 분포 (14 케이스):
- AC2 plaintext 5 — active user / allergies list / unset / empty allergies / expires_at hint
- AC2 audit row 1 — user_pii_view 자동 기록 + 9 필드 SOT
- AC2 404/400 분기 3 — not_found / invalid uuid path / soft-deleted 200
- AC2 권한 3 — non-admin / no-token / no-audit-row when blocked
- AC6 이중 안전판 2 — structlog plaintext leak 0 / audit row plaintext 0
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.security import create_admin_token, create_user_token
from app.db.models.audit_log import AuditLog
from app.db.models.user import User
from app.main import app
from tests.conftest import UserFactory


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    _ = client
    return app.state.session_maker


def _admin_headers(admin: User) -> dict[str, str]:
    token = create_admin_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# AC2 plaintext 분기
# ============================================================================


@pytest.mark.asyncio
async def test_reveal_pii_returns_plaintext_for_active_user(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """active user — 200 + plaintext email/age/weight_kg/height_cm/allergies 노출."""
    admin = await user_factory(role="admin")
    target = await user_factory(
        role="user",
        email="alice.full@example.com",
        profile_completed=True,
        age=28,
        weight_kg=Decimal("62.5"),
        height_cm=170,
        allergies=["우유", "땅콩"],
    )

    response = await client.post(
        f"/v1/admin/users/{target.id}/pii-reveal",
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == str(target.id)
    assert body["email"] == "alice.full@example.com"
    assert body["age"] == 28
    assert float(body["weight_kg"]) == 62.5
    assert body["height_cm"] == 170
    assert body["allergies"] == ["우유", "땅콩"]
    # masking 형식 비포함
    assert "***" not in body["email"]
    assert "**kg" not in str(body["weight_kg"])
    assert "**cm" not in str(body["height_cm"])


@pytest.mark.asyncio
async def test_reveal_pii_returns_plaintext_allergies_list(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """plaintext allergies list — 마스킹 형식 (``*** 3건 등록``) 비포함."""
    admin = await user_factory(role="admin")
    target = await user_factory(
        role="user",
        profile_completed=True,
        allergies=["우유", "땅콩", "메밀"],
    )

    response = await client.post(
        f"/v1/admin/users/{target.id}/pii-reveal",
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["allergies"] == ["우유", "땅콩", "메밀"]
    assert "*** 3건 등록" not in str(body["allergies"])


@pytest.mark.asyncio
async def test_reveal_pii_returns_null_for_unset_profile(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """미입력 사용자 — weight_kg/height_cm/allergies/age는 null + email은 plaintext."""
    admin = await user_factory(role="admin")
    target = await user_factory(role="user", email="empty@example.com")

    response = await client.post(
        f"/v1/admin/users/{target.id}/pii-reveal",
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "empty@example.com"
    assert body["age"] is None
    assert body["weight_kg"] is None
    assert body["height_cm"] is None
    assert body["allergies"] is None


@pytest.mark.asyncio
async def test_reveal_pii_empty_allergies_list_returns_empty_list_not_null(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """``allergies=[]`` → 응답 ``allergies=[]`` (NULL과 명확 구분)."""
    admin = await user_factory(role="admin")
    target = await user_factory(role="user", profile_completed=True, allergies=[])

    response = await client.post(
        f"/v1/admin/users/{target.id}/pii-reveal",
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["allergies"] == []
    assert body["allergies"] is not None


@pytest.mark.asyncio
async def test_reveal_pii_includes_expires_at_5_minutes_after_revealed_at(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """응답 ``expires_at - revealed_at == timedelta(minutes=5)``."""
    admin = await user_factory(role="admin")
    target = await user_factory(role="user", profile_completed=True)

    response = await client.post(
        f"/v1/admin/users/{target.id}/pii-reveal",
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200
    body = response.json()
    revealed = datetime.fromisoformat(body["revealed_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert expires - revealed == timedelta(minutes=5)


# ============================================================================
# AC2 audit row 자동 기록
# ============================================================================


@pytest.mark.asyncio
async def test_reveal_pii_creates_audit_row_with_action_user_pii_view(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """호출 후 ``audit_logs`` 1건 + ``action=user_pii_view`` + 11 필드 SOT."""
    admin = await user_factory(role="admin", email="admin.pii@example.com")
    target = await user_factory(role="user", email="target.pii@example.com")

    response = await client.post(
        f"/v1/admin/users/{target.id}/pii-reveal",
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200

    async with session_maker() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_id == admin.id
    assert row.actor_email_masked == "a***@example.com"
    assert row.action == "user_pii_view"
    assert row.target_user_id == target.id
    assert row.target_resource == "users"
    assert row.path == f"/v1/admin/users/{target.id}/pii-reveal"
    assert row.method == "POST"
    assert row.request_id  # not empty
    # audit row 13 컬럼 SOT 정합 — plaintext PII 0
    assert "target.pii" not in (row.actor_email_masked or "")


# ============================================================================
# AC2 404/400 분기
# ============================================================================


@pytest.mark.asyncio
async def test_reveal_pii_user_not_found_returns_404(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """미존재 UUID → 404 ``code=admin.user.not_found``."""
    admin = await user_factory(role="admin")
    response = await client.post(
        f"/v1/admin/users/{uuid.uuid4()}/pii-reveal",
        headers=_admin_headers(admin),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "admin.user.not_found"


@pytest.mark.asyncio
async def test_reveal_pii_soft_deleted_user_returns_200_with_plaintext(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """soft-deleted 사용자 — 200 + plaintext 노출 (admin 거버넌스)."""
    admin = await user_factory(role="admin")
    target = await user_factory(
        role="user",
        email="deleted@example.com",
        profile_completed=True,
        deleted=True,
    )
    response = await client.post(
        f"/v1/admin/users/{target.id}/pii-reveal",
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200
    assert response.json()["email"] == "deleted@example.com"


@pytest.mark.asyncio
async def test_reveal_pii_invalid_uuid_path_returns_400(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """``/v1/admin/users/not-a-uuid/pii-reveal`` → 400 (uuid path 검증)."""
    admin = await user_factory(role="admin")
    response = await client.post(
        "/v1/admin/users/not-a-uuid/pii-reveal",
        headers=_admin_headers(admin),
    )
    assert response.status_code == 400


# ============================================================================
# AC2 권한 가드
# ============================================================================


@pytest.mark.asyncio
async def test_reveal_pii_blocked_for_non_admin_no_audit_row(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """user JWT → 401/403 + audit_logs 0건 (current_admin 단계 raise)."""
    user = await user_factory(role="user")
    target = await user_factory(role="user")
    token = create_user_token(user.id, role="user", platform="mobile")
    response = await client.post(
        f"/v1/admin/users/{target.id}/pii-reveal",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code in {401, 403}
    async with session_maker() as session:
        count = await session.scalar(select(func.count()).select_from(AuditLog))
    assert count == 0


@pytest.mark.asyncio
async def test_reveal_pii_blocked_when_token_missing_no_audit_row(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """token 부재 → 401 + audit 0건."""
    target = await user_factory(role="user")
    response = await client.post(f"/v1/admin/users/{target.id}/pii-reveal")
    assert response.status_code == 401
    async with session_maker() as session:
        count = await session.scalar(select(func.count()).select_from(AuditLog))
    assert count == 0


# ============================================================================
# AC6 이중 안전판 — plaintext PII leak 0
# ============================================================================


@pytest.mark.asyncio
async def test_reveal_pii_no_plaintext_in_structlog_when_logger_patched(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """logger.info kwargs에 user.email/weight_kg/height_cm/allergies plaintext 비포함."""
    admin = await user_factory(role="admin", email="audit.admin@example.com")
    target_email = "leak.check@example.com"
    target = await user_factory(
        role="user",
        email=target_email,
        profile_completed=True,
        age=33,
        weight_kg=Decimal("88.8"),
        height_cm=180,
        allergies=["우유", "땅콩"],
    )

    # admin.py의 module-level logger를 mock으로 가로채 호출 인자 검증.
    with patch("app.api.v1.admin.logger") as mocked_logger:
        info_mock = MagicMock()
        mocked_logger.info = info_mock
        response = await client.post(
            f"/v1/admin/users/{target.id}/pii-reveal",
            headers=_admin_headers(admin),
        )

    assert response.status_code == 200

    # 모든 logger.info 호출의 args + kwargs에 plaintext PII 비포함 invariant.
    # 마스킹된 ID kwargs(``admin_id`` / ``target_user_id`` — ``u_<hex8>`` 포맷)는
    # height(``180``) 등 짧은 plaintext와 우연 충돌 가능(예: ``u_180fab12``)이라
    # 의미있는 PII 누수 검출을 위해 사전 제외 후 잔여 필드만 검사.
    _MASKED_ID_KEYS = {"admin_id", "target_user_id"}
    for call in info_mock.call_args_list:
        args, kwargs = call.args, call.kwargs
        pii_relevant_values = [v for k, v in kwargs.items() if k not in _MASKED_ID_KEYS]
        joined = " ".join(str(v) for v in (*args, *pii_relevant_values))
        assert target_email not in joined, f"plaintext email leaked: {joined}"
        assert "88.8" not in joined, f"plaintext weight leaked: {joined}"
        assert "180" not in joined, f"plaintext height leaked (180): {joined}"
        assert "우유" not in joined, f"plaintext allergy leaked: {joined}"
        assert "땅콩" not in joined, f"plaintext allergy leaked: {joined}"


@pytest.mark.asyncio
async def test_reveal_pii_audit_row_does_not_contain_plaintext_pii(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """audit row 텍스트 컬럼에 user.email plaintext 부재 + 13 컬럼 SOT 보존."""
    admin = await user_factory(role="admin", email="aa@example.com")
    target = await user_factory(
        role="user",
        email="plaintext.audit.check@example.com",
        profile_completed=True,
        weight_kg=Decimal("99.9"),
        height_cm=190,
        allergies=["땅콩"],
    )
    response = await client.post(
        f"/v1/admin/users/{target.id}/pii-reveal",
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200

    async with session_maker() as session:
        row = (await session.execute(select(AuditLog))).scalars().one()

    text_cols = [
        row.actor_email_masked,
        row.target_resource,
        row.path,
        row.method,
        row.request_id,
        row.user_agent or "",
    ]
    joined = " ".join(text_cols)
    assert "plaintext.audit.check" not in joined
    assert "99.9" not in joined
    assert "땅콩" not in joined
