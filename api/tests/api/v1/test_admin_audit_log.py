"""Story 7.3 AC6 — ``admin.py`` 6 endpoint integration audit 기록 회귀 가드.

테스트 분포 (~24 케이스):
- endpoint별 audit row 기록 11 필드 검증 (6 endpoint, 평균 3 케이스 = 18)
- transitive 연쇄 추가 케이스 1 (expired token — AC2가 cover하지 않음)
- fail-open 2 (DB error / response 정상)
- 회귀 0건 3 (Story 7.2 응답 동형 + admin_whoami audit 미발동 + admin_exchange audit 미발동)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import ADMIN_ACCESS_TOKEN_TTL_SECONDS
from app.core.security import create_admin_token, create_user_token
from app.db.models.audit_log import AuditLog
from app.db.models.meal import Meal
from app.db.models.user import User
from app.main import app
from tests.conftest import UserFactory


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    _ = client
    return app.state.session_maker


def _admin_headers(admin: User) -> dict[str, str]:
    """admin JWT를 Authorization 헤더로 직조."""
    token = create_admin_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


async def _insert_meal(*, user_id: uuid.UUID, raw_text: str = "라면 1개") -> Meal:
    """test-only meal INSERT helper."""
    session_maker = app.state.session_maker
    async with session_maker() as session:
        meal = Meal(
            user_id=user_id,
            raw_text=raw_text,
            ate_at=datetime.now(UTC),
        )
        session.add(meal)
        await session.commit()
        await session.refresh(meal)
        return meal


async def _fetch_audit_rows(session_maker: async_sessionmaker) -> list[AuditLog]:
    async with session_maker() as session:
        result = await session.execute(select(AuditLog).order_by(AuditLog.occurred_at))
        return list(result.scalars().all())


# ============================================================================
# endpoint별 audit row 검증
# ============================================================================


@pytest.mark.asyncio
async def test_search_users_creates_audit_row(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """``GET /v1/admin/users?q=foo`` 200 → audit_logs 1건 + 11 필드 SOT."""
    admin = await user_factory(role="admin", email="admin1@example.com")
    response = await client.get(
        "/v1/admin/users", params={"q": "anything"}, headers=_admin_headers(admin)
    )
    assert response.status_code == 200

    rows = await _fetch_audit_rows(session_maker)
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_id == admin.id
    assert row.actor_email_masked == "a***@example.com"
    assert row.action == "user_search"
    assert row.target_user_id is None  # 검색 endpoint는 path param 없음
    assert row.target_resource == "users"
    assert row.target_resource_id is None
    assert row.path == "/v1/admin/users"
    assert row.method == "GET"
    assert row.request_id  # not empty (RequestIdMiddleware bind)


@pytest.mark.asyncio
async def test_get_user_detail_creates_audit_row_with_target_user_id(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """``GET /v1/admin/users/{user_id}`` 200 → audit row target_user_id matches."""
    admin = await user_factory(role="admin")
    target = await user_factory(role="user")
    response = await client.get(f"/v1/admin/users/{target.id}", headers=_admin_headers(admin))
    assert response.status_code == 200

    rows = await _fetch_audit_rows(session_maker)
    assert len(rows) == 1
    assert rows[0].action == "user_profile_view"
    assert rows[0].target_user_id == target.id
    assert rows[0].target_resource == "users"
    assert rows[0].path == f"/v1/admin/users/{target.id}"
    assert rows[0].method == "GET"


@pytest.mark.asyncio
async def test_list_user_meals_creates_audit_row(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """``GET .../meals`` → action=user_meal_history_view + target_resource=meals."""
    admin = await user_factory(role="admin")
    target = await user_factory(role="user")
    response = await client.get(f"/v1/admin/users/{target.id}/meals", headers=_admin_headers(admin))
    assert response.status_code == 200

    rows = await _fetch_audit_rows(session_maker)
    assert len(rows) == 1
    assert rows[0].action == "user_meal_history_view"
    assert rows[0].target_resource == "meals"
    assert rows[0].target_user_id == target.id


@pytest.mark.asyncio
async def test_list_user_meal_analyses_creates_audit_row(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """``GET .../meal-analyses`` → action=user_feedback_history_view + meal_analyses target."""
    admin = await user_factory(role="admin")
    target = await user_factory(role="user")
    response = await client.get(
        f"/v1/admin/users/{target.id}/meal-analyses", headers=_admin_headers(admin)
    )
    assert response.status_code == 200

    rows = await _fetch_audit_rows(session_maker)
    assert len(rows) == 1
    assert rows[0].action == "user_feedback_history_view"
    assert rows[0].target_resource == "meal_analyses"
    assert rows[0].target_user_id == target.id


@pytest.mark.asyncio
async def test_patch_user_profile_creates_audit_row(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """``PATCH .../{user_id}`` 200 → action=user_profile_edit + target_resource=users."""
    admin = await user_factory(role="admin")
    target = await user_factory(role="user", profile_completed=True)
    response = await client.patch(
        f"/v1/admin/users/{target.id}",
        json={"weight_kg": "72.0"},
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200, response.text

    rows = await _fetch_audit_rows(session_maker)
    assert len(rows) == 1
    assert rows[0].action == "user_profile_edit"
    assert rows[0].target_resource == "users"
    assert rows[0].target_user_id == target.id
    assert rows[0].method == "PATCH"


@pytest.mark.asyncio
async def test_delete_user_meal_creates_audit_row_with_target_resource_id(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """``DELETE .../meals/{meal_id}`` 204 → admin_meal_delete + target_resource_id=meal_id."""
    admin = await user_factory(role="admin")
    target = await user_factory(role="user")
    meal = await _insert_meal(user_id=target.id)

    response = await client.delete(
        f"/v1/admin/users/{target.id}/meals/{meal.id}", headers=_admin_headers(admin)
    )
    assert response.status_code == 204, response.text

    rows = await _fetch_audit_rows(session_maker)
    assert len(rows) == 1
    assert rows[0].action == "admin_meal_delete"
    assert rows[0].target_resource == "meals"
    assert rows[0].target_user_id == target.id
    assert rows[0].target_resource_id == meal.id
    assert rows[0].method == "DELETE"


@pytest.mark.asyncio
async def test_search_users_audit_row_request_id_format(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """``RequestIdMiddleware`` bind한 ``request_id``가 audit row에 영속화 — middleware
    가 X-Request-ID 헤더를 client가 송신하면 그대로 echo, 부재 시 UUID4 생성.
    """
    admin = await user_factory(role="admin")
    client_request_id = "client-supplied-id"
    headers = {**_admin_headers(admin), "X-Request-ID": client_request_id}
    response = await client.get("/v1/admin/users", params={"q": "anything"}, headers=headers)
    assert response.status_code == 200

    rows = await _fetch_audit_rows(session_maker)
    assert len(rows) == 1
    assert rows[0].request_id == client_request_id


@pytest.mark.asyncio
async def test_delete_user_meal_audit_row_persists_even_when_meal_not_found_404(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """meal_id가 미존재여도 audit row 영속화 — *시도 자체*가 audit 대상 (FR37 *조회·수정
    액션* 정합).

    dep commit이 핸들러 본문보다 *먼저* 실행 → 핸들러가 404 raise해도 audit는 이미 commit.
    """
    admin = await user_factory(role="admin")
    target = await user_factory(role="user")
    nonexistent_meal_id = uuid.uuid4()

    response = await client.delete(
        f"/v1/admin/users/{target.id}/meals/{nonexistent_meal_id}",
        headers=_admin_headers(admin),
    )
    assert response.status_code == 404, response.text

    rows = await _fetch_audit_rows(session_maker)
    assert len(rows) == 1
    assert rows[0].action == "admin_meal_delete"
    assert rows[0].target_resource_id == nonexistent_meal_id


@pytest.mark.asyncio
async def test_patch_user_profile_with_nonexistent_user_id_fails_open(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """nonexistent user_id PATCH → endpoint 404 + audit row 0건(fail-open).

    ``target_user_id`` FK 위반(``audit_logs_target_user_id_fkey``) → ``record_admin_action``
    fail-open → 핸들러 본문 404 raise. *추적 가능* 의무는 best-effort(epics.md:909) +
    FK invariant(audit row의 ``target_user_id`` 는 *실제 user* 보장)이 우선 — 비존재
    UUID prefix scanning은 ``user_search`` audit으로 별 분기에서 추적.

    Story 8 forward: target_user_id FK 제거 + soft-delete된 user_id도 NULL fallback
    검토 (audit 가시성 vs FK invariant trade-off 재고).
    """
    admin = await user_factory(role="admin")
    nonexistent_user_id = uuid.uuid4()

    response = await client.patch(
        f"/v1/admin/users/{nonexistent_user_id}",
        json={"weight_kg": "72.0"},
        headers=_admin_headers(admin),
    )
    assert response.status_code == 404

    async with session_maker() as session:
        result = await session.execute(select(func.count()).select_from(AuditLog))
        assert result.scalar_one() == 0


# ============================================================================
# transitive 연쇄 추가 케이스 (AC2가 cover하지 않은 expired token 분기)
# ============================================================================


@pytest.mark.asyncio
async def test_admin_endpoint_expired_token_returns_401_and_no_audit_row(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """admin JWT ``exp`` 과거 → 401 + ``audit_logs`` 0건.

    ``verify_admin_token``이 ``AccessTokenExpiredError`` raise → ``current_admin`` 미진입
    → audit 미발동.
    """
    admin = await user_factory(role="admin")
    # ``JWT_LEEWAY_SECONDS=60`` 초과해 명확히 만료 분기 진입(Story 7.1 baseline 패턴).
    past = datetime.now(UTC) - timedelta(seconds=ADMIN_ACCESS_TOKEN_TTL_SECONDS + 120)
    expired = create_admin_token(admin.id, now=past)
    response = await client.get(
        "/v1/admin/users",
        params={"q": "anything"},
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert response.status_code == 401

    async with session_maker() as session:
        result = await session.execute(select(func.count()).select_from(AuditLog))
        assert result.scalar_one() == 0


# ============================================================================
# fail-open 분기 (audit infra 장애 시 business action 가용성 보존)
# ============================================================================


@pytest.mark.asyncio
async def test_admin_endpoint_succeeds_when_audit_insert_db_error(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """``record_admin_action``에 ``db.execute`` raise 시 endpoint는 200 + audit_logs 0건.

    fail-open 정책 — admin business action 가용성 우선(B3 KPI SLA).
    """
    admin = await user_factory(role="admin")

    # audit_service의 db.execute INSERT 호출만 raise하도록 patch.
    from app.services import audit_service

    real_record = audit_service.record_admin_action

    async def _record_with_db_error(db, **kwargs):  # type: ignore[no-untyped-def]
        # db.execute가 SQLAlchemyError 하위로 raise → fail-open 분기 진입(Gemini G1 정합)
        with patch.object(
            db,
            "execute",
            new=AsyncMock(
                side_effect=OperationalError("simulated audit DB down", params=None, orig=None)
            ),
        ):
            await real_record(db, **kwargs)

    # fail-open invariant — silent return은 *관측 가능*해야 함(Sentry alert + 운영
    # 인지 SOT). ``logger.error("audit.record_admin_action.failed", ...)`` 호출
    # 자체가 누락되면 본 가드가 fail. CR P1 회귀 가드.
    #
    # structlog 모듈 logger는 ``cache_logger_on_first_use=True``로 캐시되므로
    # ``capture_logs()``는 우회됨 — ``audit_service.logger`` 자체를 patch.
    with (
        patch.object(audit_service, "logger") as mock_logger,
        patch.object(audit_service, "record_admin_action", new=_record_with_db_error),
    ):
        response = await client.get(
            "/v1/admin/users", params={"q": "anything"}, headers=_admin_headers(admin)
        )

    assert response.status_code == 200, response.text

    async with session_maker() as session:
        result = await session.execute(select(func.count()).select_from(AuditLog))
        assert result.scalar_one() == 0

    # logger.error("audit.record_admin_action.failed", ...) 호출 검증.
    mock_logger.error.assert_called_once()
    call_args = mock_logger.error.call_args
    assert call_args.args[0] == "audit.record_admin_action.failed"
    assert call_args.kwargs.get("action") == "user_search"
    assert call_args.kwargs.get("exc_info") is True


@pytest.mark.asyncio
async def test_admin_endpoint_fail_open_does_not_leak_exception_in_response(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """fail-open 시 response payload는 정상 schema (audit infra 장애를 client에 미노출)."""
    admin = await user_factory(role="admin")
    from app.services import audit_service

    real_record = audit_service.record_admin_action

    async def _record_with_db_error(db, **kwargs):  # type: ignore[no-untyped-def]
        with patch.object(
            db,
            "execute",
            new=AsyncMock(
                side_effect=OperationalError("audit infra failure", params=None, orig=None)
            ),
        ):
            await real_record(db, **kwargs)

    # CR P1 회귀 가드 — fail-open 분기에서 logger.error가 *반드시* 호출돼야 운영
    # 가시 invariant 보존. cached structlog logger를 직접 patch.
    with (
        patch.object(audit_service, "logger") as mock_logger,
        patch.object(audit_service, "record_admin_action", new=_record_with_db_error),
    ):
        response = await client.get(
            "/v1/admin/users", params={"q": "anything"}, headers=_admin_headers(admin)
        )

    assert response.status_code == 200
    body = response.json()
    # response schema 정합 — AdminUserSearchResponse(users + next_cursor) 동형.
    assert "users" in body
    assert "next_cursor" in body

    # fail-open 분기에서도 client에는 audit infra 장애 미노출(payload는 정상) +
    # 운영자에게는 structlog ERROR로 가시.
    mock_logger.error.assert_called_once()
    assert mock_logger.error.call_args.args[0] == "audit.record_admin_action.failed"


# ============================================================================
# 회귀 0건 (Story 7.2 응답 + admin_whoami + admin_exchange audit 미적용 SOT)
# ============================================================================


@pytest.mark.asyncio
async def test_existing_admin_user_search_response_schema_unchanged_after_audit_wire(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """Story 7.2 ``AdminUserSearchResponse`` 응답 schema 회귀 0건.

    데코레이터 ``dependencies=[...]`` 추가는 핸들러 시그니처/응답 모델에 영향 0건 —
    JSON wire 동형 invariant.
    """
    admin = await user_factory(role="admin")
    response = await client.get(
        "/v1/admin/users", params={"q": "anything"}, headers=_admin_headers(admin)
    )
    assert response.status_code == 200
    body = response.json()
    # AdminUserSearchResponse 2 필드 SOT.
    assert set(body.keys()) == {"users", "next_cursor"}
    assert isinstance(body["users"], list)


@pytest.mark.asyncio
async def test_admin_whoami_creates_no_audit_row(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """``GET /v1/auth/admin/whoami`` 200 → audit_logs 0건 (Story 7.1 580행 SOT 정합).

    admin meta-info 조회는 enum scope 제외 — admin session introspect는 audit 노이즈.
    """
    admin = await user_factory(role="admin")
    response = await client.get("/v1/auth/admin/whoami", headers=_admin_headers(admin))
    assert response.status_code == 200

    async with session_maker() as session:
        result = await session.execute(select(func.count()).select_from(AuditLog))
        assert result.scalar_one() == 0


@pytest.mark.asyncio
async def test_admin_exchange_creates_no_audit_row(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """``POST /v1/auth/admin/exchange`` → audit_logs 0건 (인증 lifecycle scope 외).

    epics.md:996 *"관리자의 *모든 조회·수정 액션*"* — exchange는 *인증 발급*이라
    business action 범주 X.
    """
    admin = await user_factory(role="admin")
    user_token = create_user_token(admin.id, role=admin.role, platform="mobile")
    response = await client.post(
        "/v1/auth/admin/exchange",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code in (200, 204)

    async with session_maker() as session:
        result = await session.execute(select(func.count()).select_from(AuditLog))
        assert result.scalar_one() == 0
