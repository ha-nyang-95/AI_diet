"""Story 5.2 — ``DELETE /v1/users/me`` 라우터 통합 테스트 (AC #2, #7, #8).

~9 케이스 + Task 7 확장 케이스(integration cascade + post-delete 401 + audit gate):
- DELETE happy 사유 미송신 / 송신 / 빈 string normalize
- DELETE 사유 200자 초과 → 400
- DELETE 인증 미통과 → 401
- DELETE extra forbid → 400
- DELETE 후 GET ``/me`` → 401(``User.deleted_at.is_(None)`` 가드 회귀)
- DELETE 후 active refresh_tokens 모두 revoked
- audit_admin_action Dependency 미wire 가드(endpoint signature inspection)

PIPA Art.35 정보주체 권리 정합 — ``Depends(require_basic_consents)`` 미적용,
``Depends(current_user)`` 단독.
"""

from __future__ import annotations

import inspect
import typing
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.v1 import users as users_router
from app.core.config import USER_REFRESH_TOKEN_TTL_SECONDS
from app.core.security import create_refresh_token
from app.db.models.refresh_token import RefreshToken
from app.db.models.user import User
from app.main import app
from tests.conftest import auth_headers

UserFactory = Callable[..., Awaitable[User]]


async def _insert_refresh_token(
    user: User,
    *,
    revoked_at: datetime | None = None,
) -> RefreshToken:
    """Story 5.2 — 테스트용 refresh_tokens row INSERT helper.

    active(``revoked_at IS NULL``) 또는 already-revoked row 생성 — multi-device 격리
    검증 + idempotent revoke 정합 SOT.
    """
    session_maker: async_sessionmaker = app.state.session_maker
    _, token_hash = create_refresh_token()
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=USER_REFRESH_TOKEN_TTL_SECONDS)
    async with session_maker() as session:
        rt = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            family_id=uuid.uuid4(),
            expires_at=expires_at,
            revoked_at=revoked_at,
        )
        session.add(rt)
        await session.commit()
        await session.refresh(rt)
        return rt


# --- 인증 게이트 -----------------------------------------------------------


async def test_delete_me_unauthenticated_returns_401(client: AsyncClient) -> None:
    """Authorization 헤더 미포함 → 401(``current_user`` 가드)."""
    response = await client.delete("/v1/users/me")
    assert response.status_code == 401


# --- happy-path -------------------------------------------------------------


async def test_delete_me_no_body_returns_204_and_soft_deletes(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """Story 5.2 AC2 — body 미송신(empty body) → 204 + ``deleted_at`` set +
    ``deletion_reason=NULL`` + ``updated_at`` bump.

    *Why*: ``DELETE``는 RFC 9110 정합으로 body Optional. ``AccountDeleteRequest | None
    = None`` Endpoint signature가 정상 분기.
    """
    user = await user_factory()
    response = await client.delete(
        "/v1/users/me",
        headers=auth_headers(user),
    )
    assert response.status_code == 204, response.text

    # DB 검증.
    session_maker: async_sessionmaker = app.state.session_maker
    async with session_maker() as session:
        loaded = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert loaded.deleted_at is not None
        assert loaded.deletion_reason is None


async def test_delete_me_with_reason_persists_text(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """Story 5.2 AC2 — ``{reason: "..."}`` body → 204 + ``deletion_reason=raw text``."""
    user = await user_factory()
    reason_text = "기능이 부족해요"
    response = await client.request(
        "DELETE",
        "/v1/users/me",
        headers=auth_headers(user),
        json={"reason": reason_text},
    )
    assert response.status_code == 204, response.text

    session_maker: async_sessionmaker = app.state.session_maker
    async with session_maker() as session:
        loaded = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert loaded.deleted_at is not None
        assert loaded.deletion_reason == reason_text


async def test_delete_me_empty_reason_normalizes_to_null(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """Story 5.2 AC2 — ``{reason: ""}`` → 204 + ``deletion_reason=NULL``.

    *Why*: ``_validate_reason`` validator가 빈 string/whitespace를 ``None``으로 normalize
    — wire 레벨 polymorphism(클라이언트가 빈 string 송신해도 미송신과 동등 동작).
    """
    user = await user_factory()
    response = await client.request(
        "DELETE",
        "/v1/users/me",
        headers=auth_headers(user),
        json={"reason": ""},
    )
    assert response.status_code == 204, response.text

    session_maker: async_sessionmaker = app.state.session_maker
    async with session_maker() as session:
        loaded = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert loaded.deletion_reason is None


# --- 검증 분기 --------------------------------------------------------------


async def test_delete_me_reason_over_200_chars_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """Story 5.2 AC2 — 200자 초과 reason → 400 + ``code=validation.error``.

    *Why*: ``Field(max_length=200)`` DoS 방지 가드(content_length 우회 차단).
    """
    user = await user_factory()
    response = await client.request(
        "DELETE",
        "/v1/users/me",
        headers=auth_headers(user),
        json={"reason": "x" * 201},
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "validation.error"


async def test_delete_me_extra_field_forbidden_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """Story 5.2 AC2 — ``extra="forbid"`` 정합 — unknown 필드 → 400."""
    user = await user_factory()
    response = await client.request(
        "DELETE",
        "/v1/users/me",
        headers=auth_headers(user),
        json={"reason": "test", "unknown_field": "x"},
    )
    assert response.status_code == 400, response.text


# --- post-delete 회귀 가드 -------------------------------------------------


async def test_get_me_after_delete_returns_401(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """Story 5.2 AC7 — soft delete 직후 GET ``/me`` → 401.

    *Why*: ``current_user`` Dependency(deps.py:94)의 ``User.deleted_at.is_(None)`` 필터
    회귀 가드 — Story 1.2 baseline. soft-deleted 사용자 valid JWT 즉시 차단.
    """
    user = await user_factory()
    headers = auth_headers(user)

    # DELETE
    delete_response = await client.delete("/v1/users/me", headers=headers)
    assert delete_response.status_code == 204

    # GET /me — 같은 access token으로 재호출 → 401(``deleted_at`` set 후 가드).
    get_response = await client.get("/v1/users/me", headers=headers)
    assert get_response.status_code == 401


async def test_delete_me_revokes_active_refresh_tokens(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """Story 5.2 AC2 — 모든 active refresh_tokens revoke + 이미 revoked는 미터치.

    *Why*: 다중 device 격리 — soft-deleted 사용자는 활성 세션 즉시 무효화. 이미 revoke된
    row의 ``revoked_at`` 시각은 *기존 값 보존*(idempotent guard, ``WHERE revoked_at IS NULL``).
    """
    user = await user_factory()

    # 활성 refresh_token 2건 + already-revoked 1건.
    rt_active1 = await _insert_refresh_token(user)
    rt_active2 = await _insert_refresh_token(user)
    revoked_before = datetime.now(UTC) - timedelta(hours=1)
    rt_already_revoked = await _insert_refresh_token(user, revoked_at=revoked_before)

    response = await client.delete("/v1/users/me", headers=auth_headers(user))
    assert response.status_code == 204

    # 모든 active rows revoked, already-revoked는 시간 보존.
    session_maker: async_sessionmaker = app.state.session_maker
    async with session_maker() as session:
        rows = (
            (await session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id)))
            .scalars()
            .all()
        )
        assert len(rows) == 3
        by_id = {r.id: r for r in rows}
        assert by_id[rt_active1.id].revoked_at is not None
        assert by_id[rt_active2.id].revoked_at is not None
        # already-revoked의 ``revoked_at``은 *기존 시각* 보존(``WHERE revoked_at IS NULL`` 가드).
        assert by_id[rt_already_revoked.id].revoked_at is not None
        # 시각 차이 1초 미만이라야 *기존 시각 보존* 의미
        # (now() vs revoked_before 1시간 차 — 명시 검증).
        original = by_id[rt_already_revoked.id].revoked_at
        assert abs((original - revoked_before).total_seconds()) < 1


# --- AC8: audit_admin_action 미wire 가드 ----------------------------------


def _dep_name(dep_callable: Any) -> str:
    return getattr(dep_callable, "__name__", str(dep_callable))


async def test_delete_me_endpoint_does_not_wire_audit_admin_action() -> None:
    """Story 5.2 AC8 — ``delete_account`` endpoint signature *및* route-level dependency
    양쪽에 ``audit_*`` 미진입 가드.

    *Why*: epics.md:792 + PIPA Art.35 자기 데이터 권리 정합 — 일반 사용자 자기 탈퇴는
    audit log 미기록(Epic 7 admin 탈퇴만 audit). Story 5.1 ``patch_health_profile`` 패턴
    1:1 정합.

    CR P9 — 함수 signature(``Annotated[..., Depends(...)]``)와 *router-level
    dependencies=[]* 두 채널 모두 검증. 후자만 통하는 우회 wire(``@router.delete("/me",
    dependencies=[Depends(audit_admin_action)])``)도 즉시 fail.
    """
    type_hints = typing.get_type_hints(users_router.delete_account, include_extras=True)
    sig = inspect.signature(users_router.delete_account)
    seen_dep_names: list[str] = []
    for param_name in sig.parameters:
        annotation = type_hints.get(param_name)
        metadata = getattr(annotation, "__metadata__", ())
        for meta in metadata:
            dep_callable = getattr(meta, "dependency", None)
            if dep_callable is None:
                continue
            dep_name = _dep_name(dep_callable)
            seen_dep_names.append(dep_name)
            assert not dep_name.startswith("audit_"), (
                f"audit_* dependency must NOT wire to delete_account "
                f"(param={param_name}, dep={dep_name}); "
                "PIPA Art.35 자기 데이터 권리 정합 — Epic 7 admin endpoint만 audit."
            )
    # 양성 가드 — ``current_user``는 wire되어 있어야 함(PIPA Art.35 인증 게이트 SOT).
    assert "current_user" in seen_dep_names, (
        f"current_user must wire to delete_account. seen={seen_dep_names}"
    )
    # 음성 가드 — ``require_basic_consents``는 미wire(PIPA Art.35 — 미동의 사용자도 탈퇴 가능).
    assert "require_basic_consents" not in seen_dep_names, (
        f"require_basic_consents must NOT wire to delete_account "
        f"(PIPA Art.35 — 미동의 사용자 탈퇴 권리 봉쇄 X). seen={seen_dep_names}"
    )

    # CR P9 — route-level dependencies(``@router.delete("/me", dependencies=[...])``) 검증.
    # FastAPI Route 객체의 ``dependant.dependencies`` 트리에 ``audit_*`` callable 부재 검증.
    delete_route = next(
        route
        for route in app.routes
        if getattr(route, "path", "") == "/v1/users/me"
        and "DELETE" in getattr(route, "methods", set())
    )
    route_deps: list[str] = []

    def _walk(dependant: Any) -> None:
        for sub in getattr(dependant, "dependencies", []) or []:
            call = getattr(sub, "call", None)
            if call is not None:
                route_deps.append(_dep_name(call))
            _walk(sub)

    _walk(delete_route.dependant)
    for name in route_deps:
        assert not name.startswith("audit_"), (
            f"audit_* dependency must NOT wire at route level either "
            f"(dep={name}); PIPA Art.35 자기 데이터 권리 정합."
        )


# --- AC7: integration cascade — DELETE /me → soft delete → worker → all child rows 0 ---


async def test_delete_me_then_purge_cascades_all_child_rows(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """Story 5.2 AC7 — full lifecycle: 사용자 + meals 3 + meal_analysis 1 + notification 1 +
    refresh_tokens 2 → DELETE /me → worker hard delete → 모든 child rows 0건.

    *Why*: 코드 변경 0건(FK level CASCADE) 가드 — alembic schema에서 어느 child의
    ondelete=CASCADE 누락이 발생하면 본 테스트 fail. 신규 child 모델 추가 시(Epic 6
    payment_logs 등) 본 테스트가 회귀 가드 진입점.
    """
    from datetime import date as _date
    from datetime import timedelta as _td

    from app.db.models.consent import Consent
    from app.db.models.meal import Meal
    from app.db.models.meal_analysis import MealAnalysis
    from app.db.models.notification import Notification
    from app.workers.soft_delete_purge import purge_expired_soft_deleted_users

    user = await user_factory()
    session_maker: async_sessionmaker = app.state.session_maker

    # consents + 3 meals + 1 meal_analysis + 1 notification + 2 refresh_tokens 부착.
    async with session_maker() as session:
        session.add(
            Consent(
                user_id=user.id,
                disclaimer_acknowledged_at=datetime.now(UTC),
            )
        )
        meals = [Meal(user_id=user.id, raw_text=f"meal {i}") for i in range(3)]
        for m in meals:
            session.add(m)
        await session.flush()
        # 1 meal_analysis on first meal.
        session.add(
            MealAnalysis(
                meal_id=meals[0].id,
                user_id=user.id,
                fit_score=70,
                fit_score_label="moderate",
                fit_reason="ok",
                carbohydrate_g=Decimal("30"),
                protein_g=Decimal("15"),
                fat_g=Decimal("8"),
                energy_kcal=250,
                feedback_text="cascade test feedback",
                feedback_summary="cascade test",
                used_llm="stub",
            )
        )
        session.add(
            Notification(
                user_id=user.id,
                kind="unrecorded_meal",
                kst_date=_date.today(),
            )
        )
        await session.commit()

    await _insert_refresh_token(user)
    await _insert_refresh_token(user)

    # DELETE /me — soft delete.
    delete_response = await client.delete("/v1/users/me", headers=auth_headers(user))
    assert delete_response.status_code == 204

    # cutoff 위해 deleted_at을 31일 전으로 강제 set(테스트 빠르게 진행).
    async with session_maker() as session:
        loaded = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        loaded.deleted_at = datetime.now(UTC) - _td(days=31)
        await session.commit()

    # worker 실행 — r2_adapter=None(R2 cleanup skip), bucket 미설정 → graceful skip.
    stats = await purge_expired_soft_deleted_users(session_maker, r2_adapter=None)
    assert stats["users_purged_count"] == 1
    assert stats["errors_count"] == 0

    # 모든 child rows 0건 검증 — FK CASCADE SOT.
    async with session_maker() as session:
        from app.db.models.refresh_token import RefreshToken as RT

        for table_name in (
            "consents",
            "meals",
            "meal_analyses",
            "notifications",
            "refresh_tokens",
        ):
            cnt = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table_name} WHERE user_id = :uid"),
                    {"uid": user.id},
                )
            ).scalar_one()
            assert cnt == 0, f"{table_name} cascade failed (count={cnt})"
        # 사용자 row 자체도 0.
        user_cnt = (
            await session.execute(
                text("SELECT count(*) FROM users WHERE id = :uid"),
                {"uid": user.id},
            )
        ).scalar_one()
        assert user_cnt == 0
        # ``RT`` import는 cascade 검증에 사용 X — type checker 정합으로만 import.
        _ = RT
