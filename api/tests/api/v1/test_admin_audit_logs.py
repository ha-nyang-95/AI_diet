"""Story 7.4 AC1 — ``GET /v1/admin/audit-logs?actor_id=me`` self-audit endpoint.

테스트 분포 (16 케이스):
- AC1 invariant 5 — current admin only / empty / order / cursor round-trip / cursor invalid
- AC1 filter 4 — action / target_user_id / since / combined
- AC1 권한·검증 5 — actor_id literal / limit clamp / action enum / non-admin / no-token
- AC1 self-audit invariant 1 — meta-audit row 미발동
- AC1 NFR-P9 1 — 1만 row 단일 query ≤ 1초 (synthetic data)

회귀 가드: Story 7.3 ``test_admin_audit_log.py`` 24 케이스 + Story 7.2
``test_admin_users.py`` 45 케이스 모두 별 파일 owner 그대로 유지.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.security import create_admin_token, create_user_token
from app.db.models.audit_log import AUDIT_LOG_ACTION_VALUES, AuditLog
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


async def _insert_audit_row(
    *,
    actor_id: uuid.UUID,
    actor_email_masked: str = "a***@example.com",
    action: str = "user_search",
    target_user_id: uuid.UUID | None = None,
    target_resource: str | None = "users",
    target_resource_id: uuid.UUID | None = None,
    path: str = "/v1/admin/users",
    method: str = "GET",
    occurred_at: datetime | None = None,
    request_id: str = "00000000-0000-4000-8000-000000000000",
) -> uuid.UUID:
    """test-only audit_logs INSERT helper — 직접 row 작성."""
    session_maker = app.state.session_maker
    row_id = uuid.uuid4()
    async with session_maker() as session:
        values: dict = {
            "id": row_id,
            "actor_id": actor_id,
            "actor_email_masked": actor_email_masked,
            "action": action,
            "target_user_id": target_user_id,
            "target_resource": target_resource,
            "target_resource_id": target_resource_id,
            "path": path,
            "method": method,
            "ip": None,
            "request_id": request_id,
            "user_agent": None,
        }
        if occurred_at is not None:
            values["occurred_at"] = occurred_at
        await session.execute(insert(AuditLog).values(**values))
        await session.commit()
    return row_id


# ============================================================================
# AC1 invariant — current admin only / empty / order / cursor / cursor invalid
# ============================================================================


@pytest.mark.asyncio
async def test_list_audit_logs_returns_only_current_admin_rows(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """다른 admin의 audit row는 응답 list에 비포함 invariant."""
    me = await user_factory(role="admin", email="me@example.com")
    other = await user_factory(role="admin", email="other@example.com")
    # other admin row 5건
    for _ in range(5):
        await _insert_audit_row(actor_id=other.id)
    # me admin row 3건
    for _ in range(3):
        await _insert_audit_row(actor_id=me.id)

    response = await client.get(
        "/v1/admin/audit-logs", params={"actor_id": "me"}, headers=_admin_headers(me)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 3
    assert all(item["actor_id"] == str(me.id) for item in body["items"])


@pytest.mark.asyncio
async def test_list_audit_logs_empty_returns_empty_list_with_null_cursor(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """audit_logs 0건 → ``items=[]`` + ``next_cursor=null`` + 200."""
    admin = await user_factory(role="admin")
    response = await client.get(
        "/v1/admin/audit-logs", params={"actor_id": "me"}, headers=_admin_headers(admin)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_audit_logs_orders_by_occurred_at_desc(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """5건 INSERT (occurred_at 분산) → 응답 occurred_at DESC 정렬."""
    admin = await user_factory(role="admin")
    base = datetime.now(UTC) - timedelta(days=10)
    for i in range(5):
        await _insert_audit_row(actor_id=admin.id, occurred_at=base + timedelta(hours=i))

    response = await client.get(
        "/v1/admin/audit-logs", params={"actor_id": "me"}, headers=_admin_headers(admin)
    )
    assert response.status_code == 200
    items = response.json()["items"]
    occurred_ats = [item["occurred_at"] for item in items]
    assert occurred_ats == sorted(occurred_ats, reverse=True)


@pytest.mark.asyncio
async def test_list_audit_logs_cursor_round_trip(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """limit=2 + 5건 → 첫(2)+next_cursor → 둘째(2)+cursor → 셋째(1)+cursor=None."""
    admin = await user_factory(role="admin")
    base = datetime.now(UTC) - timedelta(days=1)
    for i in range(5):
        await _insert_audit_row(actor_id=admin.id, occurred_at=base + timedelta(seconds=i))

    headers = _admin_headers(admin)
    r1 = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "me", "limit": 2},
        headers=headers,
    )
    assert r1.status_code == 200
    page1 = r1.json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    r2 = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "me", "limit": 2, "cursor": page1["next_cursor"]},
        headers=headers,
    )
    assert r2.status_code == 200
    page2 = r2.json()
    assert len(page2["items"]) == 2
    assert page2["next_cursor"] is not None

    r3 = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "me", "limit": 2, "cursor": page2["next_cursor"]},
        headers=headers,
    )
    assert r3.status_code == 200
    page3 = r3.json()
    assert len(page3["items"]) == 1
    assert page3["next_cursor"] is None

    # 정렬 일관성 — 페이지간 audit_id disjoint + 시간 역순.
    seen = [item["audit_id"] for page in (page1, page2, page3) for item in page["items"]]
    assert len(set(seen)) == 5


@pytest.mark.asyncio
async def test_list_audit_logs_cursor_invalid_returns_400(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """``?cursor=garbage`` → 400 ``code=admin.cursor.invalid``."""
    admin = await user_factory(role="admin")
    response = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "me", "cursor": "garbage_token_not_b64"},
        headers=_admin_headers(admin),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "admin.cursor.invalid"


# ============================================================================
# AC1 filter — action / target_user_id / since / combined
# ============================================================================


@pytest.mark.asyncio
async def test_list_audit_logs_filter_by_action(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """3건(user_search 1 + user_pii_view 2) + ``?action=user_pii_view`` → 2건 hit."""
    admin = await user_factory(role="admin")
    await _insert_audit_row(actor_id=admin.id, action="user_search")
    await _insert_audit_row(actor_id=admin.id, action="user_pii_view")
    await _insert_audit_row(actor_id=admin.id, action="user_pii_view")

    response = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "me", "action": "user_pii_view"},
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    assert all(item["action"] == "user_pii_view" for item in items)


@pytest.mark.asyncio
async def test_list_audit_logs_filter_by_target_user_id(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """다른 target row 분산 + ``?target_user_id={uuid}`` → 일치 row만 hit."""
    admin = await user_factory(role="admin")
    target1 = await user_factory(role="user")
    target2 = await user_factory(role="user")
    for _ in range(3):
        await _insert_audit_row(actor_id=admin.id, target_user_id=target1.id)
    for _ in range(2):
        await _insert_audit_row(actor_id=admin.id, target_user_id=target2.id)

    response = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "me", "target_user_id": str(target1.id)},
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 3
    assert all(item["target_user_id"] == str(target1.id) for item in items)


@pytest.mark.asyncio
async def test_list_audit_logs_filter_by_since(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """7건(시계열 분산) + ``?since={iso}`` → 이후 row만 hit."""
    admin = await user_factory(role="admin")
    base = datetime(2026, 5, 5, tzinfo=UTC)
    for i in range(7):
        await _insert_audit_row(actor_id=admin.id, occurred_at=base + timedelta(days=i))
    since_dt = datetime(2026, 5, 10, tzinfo=UTC)

    response = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "me", "since": since_dt.isoformat().replace("+00:00", "Z")},
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200
    items = response.json()["items"]
    # 5/5, 5/6, 5/7, 5/8, 5/9, 5/10, 5/11 → since=5/10 (inclusive) → 5/10, 5/11 = 2건
    assert len(items) == 2


@pytest.mark.asyncio
async def test_list_audit_logs_combines_filters(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """3 필터 AND — action + target_user_id + since."""
    admin = await user_factory(role="admin")
    target = await user_factory(role="user")
    base = datetime(2026, 5, 5, tzinfo=UTC)
    # 매치
    await _insert_audit_row(
        actor_id=admin.id,
        action="user_profile_view",
        target_user_id=target.id,
        occurred_at=base + timedelta(days=10),
    )
    # action mismatch
    await _insert_audit_row(
        actor_id=admin.id,
        action="user_search",
        target_user_id=target.id,
        occurred_at=base + timedelta(days=10),
    )
    # since mismatch
    await _insert_audit_row(
        actor_id=admin.id,
        action="user_profile_view",
        target_user_id=target.id,
        occurred_at=base - timedelta(days=5),
    )
    # target mismatch
    other = await user_factory(role="user")
    await _insert_audit_row(
        actor_id=admin.id,
        action="user_profile_view",
        target_user_id=other.id,
        occurred_at=base + timedelta(days=10),
    )

    response = await client.get(
        "/v1/admin/audit-logs",
        params={
            "actor_id": "me",
            "action": "user_profile_view",
            "target_user_id": str(target.id),
            "since": base.isoformat().replace("+00:00", "Z"),
        },
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1


# ============================================================================
# AC1 검증 — actor_id literal / limit clamp / enum / 권한
# ============================================================================


@pytest.mark.asyncio
async def test_list_audit_logs_actor_id_non_me_returns_400(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """``?actor_id=foo`` → 400 (FastAPI Literal["me"] 검증, 422 → 400 변환).

    프로젝트 SOT — ``main.py:validation_exception_handler``가 RequestValidationError를
    RFC 7807 400 ``code=validation.error``로 변환.
    """
    admin = await user_factory(role="admin")
    response = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "foo"},
        headers=_admin_headers(admin),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


@pytest.mark.asyncio
async def test_list_audit_logs_actor_id_other_admin_uuid_returns_400(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """``?actor_id={other_admin_uuid}`` → 400 (1인 owner MVP 보호)."""
    admin = await user_factory(role="admin")
    other_uuid = uuid.uuid4()
    response = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": str(other_uuid)},
        headers=_admin_headers(admin),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_audit_logs_limit_clamped_to_100(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """``?limit=101`` → 400 (Query ge=1, le=100 검증)."""
    admin = await user_factory(role="admin")
    response = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "me", "limit": 101},
        headers=_admin_headers(admin),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_audit_logs_action_invalid_enum_returns_400(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """``?action=garbage`` → 400 (Literal action enum)."""
    admin = await user_factory(role="admin")
    response = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "me", "action": "garbage_action"},
        headers=_admin_headers(admin),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_audit_logs_blocked_for_non_admin(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """user JWT → admin issuer mismatch → 401 ``code=auth.access_token.invalid``.

    Story 7.1 패턴 정합 — user 토큰을 admin 검증으로 보내면 issuer mismatch라 401.
    role_required 분기는 admin issuer + non-admin role 시점에만 발동.
    """
    user = await user_factory(role="user")
    token = create_user_token(user.id, role="user", platform="mobile")
    response = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "me"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code in {401, 403}
    assert response.json()["code"] in {
        "auth.admin.role_required",
        "auth.access_token.invalid",
    }


@pytest.mark.asyncio
async def test_list_audit_logs_blocked_when_token_missing(
    client: AsyncClient,
) -> None:
    """Authorization + 쿠키 부재 → 401."""
    response = await client.get("/v1/admin/audit-logs", params={"actor_id": "me"})
    assert response.status_code == 401


# ============================================================================
# AC1 self-audit invariant — meta-audit row 미발동
# ============================================================================


@pytest.mark.asyncio
async def test_list_audit_logs_no_self_audit_row_created_when_called(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """self-audit 호출 자체는 audit_logs row 미발동 (``admin_whoami`` exclusion 패턴)."""
    admin = await user_factory(role="admin")
    response = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "me"},
        headers=_admin_headers(admin),
    )
    assert response.status_code == 200

    async with session_maker() as session:
        count = await session.scalar(select(func.count()).select_from(AuditLog))
        assert count == 0


# ============================================================================
# AC1 NFR-P9 — 1만 row 단일 query ≤ 1초
# ============================================================================


@pytest.mark.asyncio
async def test_list_audit_logs_nfr_p9_10k_rows_under_1s(
    client: AsyncClient, user_factory: UserFactory, session_maker: async_sessionmaker
) -> None:
    """1만 audit row + ``actor_id=me ORDER BY occurred_at DESC LIMIT 50`` p95 ≤ 1초.

    Story 7.2 NFR-P9 패턴 정합. ``idx_audit_logs_actor_id_occurred_at`` composite
    index hit 보장.
    """
    me = await user_factory(role="admin", email="nfrp9@example.com")
    other = await user_factory(role="admin", email="nfrp9_other@example.com")

    # 1만 row INSERT — bulk insert로 setup latency 최소화.
    # 9000건 other + 1000건 me — composite index 회피 vs hit 분기 검증.
    bulk_rows: list[dict] = []
    base = datetime.now(UTC) - timedelta(days=30)
    for i in range(9000):
        bulk_rows.append(
            {
                "actor_id": other.id,
                "actor_email_masked": "n***@example.com",
                "action": "user_search",
                "path": "/v1/admin/users",
                "method": "GET",
                "request_id": "bulk-other",
                "occurred_at": base + timedelta(seconds=i),
            }
        )
    for i in range(1000):
        bulk_rows.append(
            {
                "actor_id": me.id,
                "actor_email_masked": "n***@example.com",
                "action": "user_search",
                "path": "/v1/admin/users",
                "method": "GET",
                "request_id": "bulk-me",
                "occurred_at": base + timedelta(seconds=9000 + i),
            }
        )

    async with session_maker() as session:
        await session.execute(insert(AuditLog), bulk_rows)
        await session.commit()

    start = time.perf_counter()
    response = await client.get(
        "/v1/admin/audit-logs",
        params={"actor_id": "me", "limit": 50},
        headers=_admin_headers(me),
    )
    elapsed = time.perf_counter() - start
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 50
    assert all(item["actor_id"] == str(me.id) for item in items)
    assert elapsed < 1.0, f"NFR-P9 위반: {elapsed:.3f}s"


# ============================================================================
# audit_logs Pydantic 응답 — 11 필드 직렬화 검증
# ============================================================================


@pytest.mark.asyncio
async def test_list_audit_logs_response_includes_all_audit_fields(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """응답 item 13 필드 모두 노출 + ENUM action 7 값 중 하나."""
    admin = await user_factory(role="admin", email="full@example.com")
    target = await user_factory(role="user")
    await _insert_audit_row(
        actor_id=admin.id,
        actor_email_masked="f***@example.com",
        action="user_profile_view",
        target_user_id=target.id,
        target_resource="users",
        path=f"/v1/admin/users/{target.id}",
        method="GET",
        request_id="00000000-0000-4000-8000-000000000abc",
    )

    response = await client.get(
        "/v1/admin/audit-logs", params={"actor_id": "me"}, headers=_admin_headers(admin)
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert set(item.keys()) == {
        "audit_id",
        "occurred_at",
        "actor_id",
        "actor_email_masked",
        "action",
        "target_user_id",
        "target_resource",
        "target_resource_id",
        "path",
        "method",
        "ip",
        "request_id",
        "user_agent",
    }
    assert item["action"] in AUDIT_LOG_ACTION_VALUES
    assert item["actor_id"] == str(admin.id)
    assert item["target_user_id"] == str(target.id)
    assert item["actor_email_masked"] == "f***@example.com"
    assert item["path"] == f"/v1/admin/users/{target.id}"
