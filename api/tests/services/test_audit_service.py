"""Story 7.3 AC2 — ``record_admin_action`` 8 케이스 단위 테스트.

audit row INSERT 11 필드 + actor_email 마스킹 SOT + path param UUID parsing +
structlog contextvars request_id 추출 + fail-open silent log.error 회귀 가드.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import structlog
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.requests import Request
from starlette.types import Scope

from app.db.models.audit_log import AuditLog
from app.db.models.user import User
from app.main import app
from app.services.audit_service import record_admin_action


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    _ = client
    return app.state.session_maker


def _make_request(
    *,
    path: str = "/v1/admin/users",
    method: str = "GET",
    path_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    client_host: str = "127.0.0.1",
) -> Request:
    """``Request`` instance — ``audit_service`` SOT 호출 패턴 mimic.

    starlette ``Request``는 ``scope`` dict + path_params 직접 set으로 단위 테스트
    가능 — middleware/router resolution 미통과 흐름 reproduce.
    """
    raw_headers: list[tuple[bytes, bytes]] = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))

    scope: Scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode("ascii"),
        "headers": raw_headers,
        "query_string": b"",
        "scheme": "http",
        "server": ("test", 80),
        "client": (client_host, 12345) if client_host else None,
        "path_params": path_params or {},
        "app": app,
    }
    return Request(scope)


async def _make_admin(session_maker: async_sessionmaker, *, email: str | None = None) -> User:
    async with session_maker() as session:
        admin = User(
            google_sub=f"google-sub-{uuid.uuid4()}",
            email=email or f"admin-{uuid.uuid4().hex}@example.com",
            email_verified=True,
            role="admin",
            last_login_at=datetime.now(UTC),
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        return admin


@pytest.mark.asyncio
async def test_record_admin_action_inserts_row_with_all_fields(
    session_maker: async_sessionmaker,
) -> None:
    """11 필드 모두 채워진 audit row INSERT (occurred_at·id는 server side)."""
    admin = await _make_admin(session_maker)
    target_user_id = uuid.uuid4()
    request = _make_request(
        path=f"/v1/admin/users/{target_user_id}",
        method="GET",
        path_params={"user_id": str(target_user_id)},
        headers={"User-Agent": "pytest-ua"},
    )

    async with session_maker() as session:
        # FK target user 미리 INSERT (target_user_id NOT NULL 제약은 없지만 FK valid 보장)
        target_user = User(
            id=target_user_id,
            google_sub=f"google-sub-{uuid.uuid4()}",
            email=f"target-{uuid.uuid4().hex}@example.com",
            email_verified=True,
            last_login_at=datetime.now(UTC),
        )
        session.add(target_user)
        await session.commit()

    async with session_maker() as session:
        await record_admin_action(
            session,
            request=request,
            admin=admin,
            action="user_profile_view",
            target_resource="users",
        )

    async with session_maker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.actor_id == admin.id))
        row = result.scalar_one()

    assert row.id is not None
    assert row.occurred_at is not None
    assert row.actor_id == admin.id
    assert row.action == "user_profile_view"
    assert row.target_user_id == target_user_id
    assert row.target_resource == "users"
    assert row.target_resource_id is None
    assert row.path == f"/v1/admin/users/{target_user_id}"
    assert row.method == "GET"
    assert row.request_id == "unknown"  # contextvars 미바인드
    assert row.user_agent == "pytest-ua"


@pytest.mark.asyncio
async def test_record_admin_action_masks_actor_email(
    session_maker: async_sessionmaker,
) -> None:
    """actor_email_masked = mask_email(admin.email) — NFR-S5 SOT."""
    admin = await _make_admin(session_maker, email="john.smith@example.com")
    request = _make_request()

    async with session_maker() as session:
        await record_admin_action(
            session, request=request, admin=admin, action="user_search", target_resource="users"
        )

    async with session_maker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.actor_id == admin.id))
        row = result.scalar_one()

    assert row.actor_email_masked == "j***@example.com"


@pytest.mark.asyncio
async def test_record_admin_action_target_user_id_from_path_param(
    session_maker: async_sessionmaker,
) -> None:
    """``request.path_params['user_id']`` → ``target_user_id`` UUID parsing."""
    admin = await _make_admin(session_maker)
    target_id = uuid.uuid4()

    async with session_maker() as session:
        target_user = User(
            id=target_id,
            google_sub=f"google-sub-{uuid.uuid4()}",
            email=f"t-{uuid.uuid4().hex}@example.com",
            email_verified=True,
            last_login_at=datetime.now(UTC),
        )
        session.add(target_user)
        await session.commit()

    request = _make_request(path_params={"user_id": str(target_id)})
    async with session_maker() as session:
        await record_admin_action(session, request=request, admin=admin, action="user_profile_view")

    async with session_maker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.actor_id == admin.id))
        row = result.scalar_one()
    assert row.target_user_id == target_id


@pytest.mark.asyncio
async def test_record_admin_action_target_resource_id_from_meal_id_path_param(
    session_maker: async_sessionmaker,
) -> None:
    """``meal_id`` path param → ``target_resource_id`` UUID parsing."""
    admin = await _make_admin(session_maker)
    target_id = uuid.uuid4()
    meal_id = uuid.uuid4()

    async with session_maker() as session:
        target_user = User(
            id=target_id,
            google_sub=f"google-sub-{uuid.uuid4()}",
            email=f"t-{uuid.uuid4().hex}@example.com",
            email_verified=True,
            last_login_at=datetime.now(UTC),
        )
        session.add(target_user)
        await session.commit()

    request = _make_request(
        path=f"/v1/admin/users/{target_id}/meals/{meal_id}",
        method="DELETE",
        path_params={"user_id": str(target_id), "meal_id": str(meal_id)},
    )
    async with session_maker() as session:
        await record_admin_action(
            session,
            request=request,
            admin=admin,
            action="admin_meal_delete",
            target_resource="meals",
        )

    async with session_maker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.actor_id == admin.id))
        row = result.scalar_one()
    assert row.target_user_id == target_id
    assert row.target_resource_id == meal_id
    assert row.target_resource == "meals"


@pytest.mark.asyncio
async def test_record_admin_action_target_user_id_invalid_uuid_to_none(
    session_maker: async_sessionmaker,
) -> None:
    """``path_params['user_id']``가 invalid UUID 시 ``target_user_id=None``."""
    admin = await _make_admin(session_maker)
    request = _make_request(path_params={"user_id": "garbage"})

    async with session_maker() as session:
        await record_admin_action(session, request=request, admin=admin, action="user_profile_view")

    async with session_maker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.actor_id == admin.id))
        row = result.scalar_one()
    assert row.target_user_id is None


@pytest.mark.asyncio
async def test_record_admin_action_request_id_from_structlog_contextvars(
    session_maker: async_sessionmaker,
) -> None:
    """structlog ``bound_contextvars(request_id="...")`` → INSERT request_id."""
    admin = await _make_admin(session_maker)
    request = _make_request()
    request_id_value = "req-abc-123"

    async with session_maker() as session:
        with structlog.contextvars.bound_contextvars(request_id=request_id_value):
            await record_admin_action(session, request=request, admin=admin, action="user_search")

    async with session_maker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.actor_id == admin.id))
        row = result.scalar_one()
    assert row.request_id == request_id_value


@pytest.mark.asyncio
async def test_record_admin_action_request_id_fallback_unknown(
    session_maker: async_sessionmaker,
) -> None:
    """contextvars 미바인드 시 ``request_id="unknown"`` fallback (NOT NULL 보존)."""
    # contextvars 정리 — 이전 테스트 누수 차단
    structlog.contextvars.clear_contextvars()
    admin = await _make_admin(session_maker)
    request = _make_request()

    async with session_maker() as session:
        await record_admin_action(session, request=request, admin=admin, action="user_search")

    async with session_maker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.actor_id == admin.id))
        row = result.scalar_one()
    assert row.request_id == "unknown"


@pytest.mark.asyncio
async def test_record_admin_action_fail_open_on_db_error(
    session_maker: async_sessionmaker,
) -> None:
    """db.execute raise → logger.error + 본 함수는 no-raise(silent return).

    fail-open 정책 (admin business action 가용성 우선 — B3 KPI SLA).
    ``SQLAlchemyError`` 하위 ``OperationalError`` simulate — Gemini G1 정합으로
    좁힌 except 분기 회귀 가드.
    """
    admin = await _make_admin(session_maker)
    request = _make_request()
    db_error = OperationalError("simulated db down", params=None, orig=None)

    async with session_maker() as session:
        # db.execute가 SQLAlchemyError 하위(=OperationalError)로 raise하도록 monkeypatch.
        with patch.object(session, "execute", new=AsyncMock(side_effect=db_error)):
            # no-raise invariant — 본 함수 자체가 raise 시 admin business action 차단됨
            await record_admin_action(session, request=request, admin=admin, action="user_search")

    # audit row는 INSERT 미실행
    async with session_maker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.actor_id == admin.id))
        rows = list(result.scalars().all())
    assert rows == []


@pytest.mark.asyncio
async def test_record_admin_action_does_not_swallow_programming_bugs(
    session_maker: async_sessionmaker,
) -> None:
    """``TypeError``/``AttributeError`` 등 코딩 버그는 fail-open 분기 *밖*으로 노출.

    Gemini G1 정합 — ``except SQLAlchemyError``로 좁힌 결과 DB 무관 예외는 잡지
    않음. 본 가드는 broad ``except Exception`` 회귀(silent bug 흡수) 차단.
    """
    admin = await _make_admin(session_maker)
    request = _make_request()

    async with session_maker() as session:
        with patch.object(
            session, "execute", new=AsyncMock(side_effect=TypeError("simulated bug"))
        ):
            with pytest.raises(TypeError, match="simulated bug"):
                await record_admin_action(
                    session, request=request, admin=admin, action="user_search"
                )


# ============================================================================
# CR P2/P3/P4 — IP/request_id/user_agent 정규화 + 정제 회귀 가드
# ============================================================================


@pytest.mark.asyncio
async def test_record_admin_action_ipv4_mapped_ipv6_is_normalized_to_ipv4(
    session_maker: async_sessionmaker,
) -> None:
    """``::ffff:203.0.113.42`` (IPv4-mapped IPv6) → ``203.0.113.42``로 저장.

    포렌식 IPv4 CIDR 필터 일관성 보존(``check_admin_ip_allowed`` Story 1.2 SOT
    가 이미 ``ipv4_mapped`` 분기로 IPv4 trust 적용 → audit 영속화도 동일 정규화
    정합). CR P2 회귀 가드.
    """
    import ipaddress

    admin = await _make_admin(session_maker)
    request = _make_request(
        headers={
            # ``get_real_client_ip``는 trusted proxy 분기 시 ``X-Forwarded-For``
            # 첫 IP를 반환 — IPv4-mapped IPv6 표기 그대로 전달되는 케이스 mimic.
            "CF-Connecting-IP": "::ffff:203.0.113.42",
        },
    )

    async with session_maker() as session:
        await record_admin_action(session, request=request, admin=admin, action="user_search")

    async with session_maker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.actor_id == admin.id))
        row = result.scalar_one()
    # 정규화된 IPv4Address 저장 — INET column이 IPv4로 보존.
    assert row.ip == ipaddress.IPv4Address("203.0.113.42")


@pytest.mark.asyncio
async def test_record_admin_action_request_id_strips_control_chars_and_caps_length(
    session_maker: async_sessionmaker,
) -> None:
    """contextvars의 request_id가 newline/NUL/긴 페이로드라도 정제 후 저장.

    middleware는 정규화된 UUID4를 bind하지만, 비정상 진입 경로(외부 체인) 방어로
    audit 영속화 시점에도 한 번 더 정제 — Postgres ``text`` NUL 거부 회피 +
    로그 라인 인젝션 차단. CR P3 회귀 가드.
    """
    admin = await _make_admin(session_maker)
    request = _make_request()
    # newline + NUL + 길이 폭증을 포함한 adversarial payload
    poisoned = "abc\n\x00xyz" + ("A" * 500)

    async with session_maker() as session:
        with structlog.contextvars.bound_contextvars(request_id=poisoned):
            await record_admin_action(session, request=request, admin=admin, action="user_search")

    async with session_maker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.actor_id == admin.id))
        row = result.scalar_one()
    # 제어문자 제거 + 128자 cap (REQUEST_ID_MAX_LEN SOT)
    assert "\n" not in row.request_id
    assert "\x00" not in row.request_id
    assert len(row.request_id) <= 128
    assert row.request_id.startswith("abcxyz")


@pytest.mark.asyncio
async def test_record_admin_action_user_agent_nul_byte_is_stripped(
    session_maker: async_sessionmaker,
) -> None:
    """``User-Agent``에 NUL byte/긴 payload가 있어도 정제 후 저장 (fail-open silent
    drop 회피).

    Postgres ``text``는 NUL byte를 거부 — 정제 없이 INSERT 시 ``invalid byte
    sequence``로 fail-open 분기가 발동해 audit row가 0건이 됨. 정제로 audit 보존.
    CR P4 회귀 가드.
    """
    admin = await _make_admin(session_maker)
    # Starlette Request scope는 헤더 값에 ASCII 8-bit만 허용 → latin-1 NUL byte
    # 사용 (실제 client가 보낼 수 있는 raw bytes mimic).
    request = _make_request(headers={"User-Agent": "Mozilla\x00Evil/" + "X" * 2000})

    async with session_maker() as session:
        await record_admin_action(session, request=request, admin=admin, action="user_search")

    async with session_maker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.actor_id == admin.id))
        row = result.scalar_one()
    assert row.user_agent is not None
    assert "\x00" not in row.user_agent
    # USER_AGENT_MAX_LEN SOT 1024
    assert len(row.user_agent) <= 1024
    assert row.user_agent.startswith("MozillaEvil/")


@pytest.mark.asyncio
async def test_record_admin_action_user_agent_only_control_chars_becomes_null(
    session_maker: async_sessionmaker,
) -> None:
    """``User-Agent``가 제어문자만으로 구성되면 정제 결과는 ``None``.

    ``audit_logs.user_agent`` NULL 허용 컬럼이라 안전 fallback.
    """
    admin = await _make_admin(session_maker)
    request = _make_request(headers={"User-Agent": "\x01\x02\x03"})

    async with session_maker() as session:
        await record_admin_action(session, request=request, admin=admin, action="user_search")

    async with session_maker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.actor_id == admin.id))
        row = result.scalar_one()
    assert row.user_agent is None
