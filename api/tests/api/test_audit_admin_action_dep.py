"""Story 7.3 AC2 — ``audit_admin_action`` factory Dependency 4 케이스.

factory invocation isolation + transitive ``Depends(current_admin)`` 자동 연쇄 검증
(admin 토큰 부재 / role!=admin / IP 가드 차단 모두 audit row 미발동 invariant).

epics.md:914 *"admin_user_jwt_required ↔ audit_admin_action 자동 연쇄 — admin 토큰
없으면 audit 미발동"* 정합 — 본 파일이 invariant SOT.
"""

from __future__ import annotations

import time
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt as jose_jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.deps import audit_admin_action
from app.core.config import JWT_ADMIN_AUDIENCE, settings
from app.core.security import JWT_ALGORITHM, create_admin_token
from app.db.models.audit_log import AuditLog
from app.main import app
from tests.conftest import UserFactory


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    _ = client
    return app.state.session_maker


def test_audit_admin_action_is_factory_returning_callable() -> None:
    """factory 호출은 callable 반환 + invocation 격리 (같은 인자 2회 호출 시 별 callable).

    factory closure가 매 호출마다 새 ``_dep`` 생성 — FastAPI dep cache 키는 callable
    identity가 아닌 dep tree path라 별 instance도 정상 분기.
    """
    dep_a = audit_admin_action(action="user_search", target_resource="users")
    dep_b = audit_admin_action(action="user_search", target_resource="users")

    assert callable(dep_a)
    assert callable(dep_b)
    # 별 invocation은 별 callable.
    assert dep_a is not dep_b


@pytest.mark.asyncio
async def test_audit_admin_action_propagates_admin_auth_failure_audit_not_fired(
    client: AsyncClient, session_maker: async_sessionmaker
) -> None:
    """admin 토큰 부재 → 401 + ``audit_logs`` 0건 (transitive ``current_admin`` raise).

    epics.md:914 *"admin 토큰 없으면 audit 미발동"* 정합.
    """
    response = await client.get("/v1/admin/users", params={"q": "anything"})
    assert response.status_code == 401

    async with session_maker() as session:
        result = await session.execute(select(func.count()).select_from(AuditLog))
        assert result.scalar_one() == 0


@pytest.mark.asyncio
async def test_audit_admin_action_propagates_non_admin_role_audit_not_fired(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """role=user JWT(admin secret 위조) → 403 + ``audit_logs`` 0건.

    admin secret으로 서명됐지만 ``role="user"`` claim — ``current_admin`` DB role
    재확인에서 ``AdminRoleRequiredError`` raise → audit 미발동.
    """
    user = await user_factory(role="user")
    forged_payload = {
        "sub": str(user.id),
        "iss": settings.jwt_admin_issuer,
        "aud": JWT_ADMIN_AUDIENCE,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": str(uuid.uuid4()),
        "role": "user",
    }
    forged = jose_jwt.encode(forged_payload, settings.jwt_admin_secret, algorithm=JWT_ALGORITHM)
    response = await client.get(
        "/v1/admin/users",
        params={"q": "anything"},
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert response.status_code == 403

    async with session_maker() as session:
        result = await session.execute(select(func.count()).select_from(AuditLog))
        assert result.scalar_one() == 0


@pytest.mark.asyncio
async def test_audit_admin_action_propagates_ip_block_audit_not_fired(
    client: AsyncClient,
    user_factory: UserFactory,
    session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ADMIN_IP_ALLOWLIST`` 미일치 → 403 + ``audit_logs`` 0건.

    ASGITransport는 ``request.client``를 None으로 두므로 ``get_real_client_ip``는 빈
    문자열 → ``check_admin_ip_allowed`` deny → ``AdminIpBlockedError`` raise →
    ``current_admin`` 단계 미진입 → audit 미발동.
    """
    monkeypatch.setattr(settings, "admin_ip_allowlist", ["10.0.0.0/24"])
    admin = await user_factory(role="admin")
    admin_token = create_admin_token(admin.id)
    response = await client.get(
        "/v1/admin/users",
        params={"q": "anything"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 403

    async with session_maker() as session:
        result = await session.execute(select(func.count()).select_from(AuditLog))
        assert result.scalar_one() == 0
