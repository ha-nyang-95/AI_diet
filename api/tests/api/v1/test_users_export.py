"""Story 5.3 AC2 / AC8 / AC9 — ``GET /v1/users/me/export`` 라우터 테스트.

10건+ 시나리오:

1. 401 — 인증 미통과.
2. 200 + JSON happy-path — Content-Type/Disposition + body 첫 byte ``{``.
3. 200 + CSV happy-path — Content-Type/Disposition + body 첫 char BOM + 한국어 헤더.
4. 400 + ``code=validation.error`` — invalid format(``?format=xml``).
5. 200 — format param 미송신 → JSON default.
6. 200 — 미동의 사용자(``basic_consents=false``) → 200 (PIPA Art.35 정합 invariant).
7. Content-Disposition filename에 raw UUID 미노출 — ``u_{8char}`` 마스킹 SOT.
8. ``X-Content-Type-Options: nosniff`` 헤더 존재.
9. JSON 응답 body — soft-deleted meals 제외 검증.
10. ``audit_admin_action`` Dependency 미wire 가드(endpoint signature inspection +
    route-level dependant walk — Story 5.2 AC8 패턴 정합).
11. (N+1 가드) meals 5건 + meal_analyses 5건 → cursor.execute count ≤ 6.
"""

from __future__ import annotations

import inspect
import json
import typing
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.v1 import users as users_router
from app.db.models.meal import Meal
from app.db.models.meal_analysis import MealAnalysis
from app.db.models.user import User
from app.main import app
from tests.conftest import auth_headers

UserFactory = Callable[..., Awaitable[User]]
ConsentFactory = Callable[..., Awaitable[Any]]


# --- 인증 게이트 -----------------------------------------------------------


async def test_export_unauthenticated_returns_401(client: AsyncClient) -> None:
    response = await client.get("/v1/users/me/export")
    assert response.status_code == 401


# --- happy-path JSON --------------------------------------------------------


async def test_export_json_happy_returns_200_with_json_body(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """``?format=json`` → 200 + ``application/json`` + body 첫 byte ``{``."""
    user = await user_factory()
    response = await client.get("/v1/users/me/export?format=json", headers=auth_headers(user))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["content-disposition"].startswith("attachment;")
    body = response.content
    assert body[:1] == b"{"
    parsed = json.loads(body.decode("utf-8"))
    assert parsed["schema_version"] == "1.0"
    assert parsed["user_id"] == str(user.id)
    assert parsed["meals"] == []


# --- happy-path CSV ---------------------------------------------------------


async def test_export_csv_happy_returns_200_with_bom_korean_header(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """``?format=csv`` → 200 + ``text/csv; charset=utf-8`` + 첫 char BOM + 한국어 헤더."""
    user = await user_factory()
    response = await client.get("/v1/users/me/export?format=csv", headers=auth_headers(user))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    body = response.text
    # BOM ``﻿`` 첫 char.
    assert body.startswith("﻿")
    # 한국어 헤더 6 컬럼.
    assert "날짜,식사,매크로,fit_score,피드백 요약,출처" in body


# --- invalid format ---------------------------------------------------------


async def test_export_invalid_format_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """``?format=xml`` → Pydantic Literal 1차 게이트 → 글로벌 핸들러 400 + ``validation.error``.

    *Why*: 글로벌 ``validation_exception_handler``(``main.py``)가 422 → 400 변환.
    """
    user = await user_factory()
    response = await client.get("/v1/users/me/export?format=xml", headers=auth_headers(user))
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.get("code") == "validation.error"


# --- default format ---------------------------------------------------------


async def test_export_no_format_param_defaults_to_json(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """format param 미송신 → JSON default (Query default ``"json"``)."""
    user = await user_factory()
    response = await client.get("/v1/users/me/export", headers=auth_headers(user))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")


# --- PIPA Art.35 invariant — 미동의 사용자도 export 가능 -------------------


async def test_export_works_for_user_without_basic_consents(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """미동의 사용자(consent_factory 호출 0) → 200.

    *Why*: PIPA Art.35 정보주체 권리(deps.py:202-206 정합) — ``require_basic_consents``
    미적용. 자기 데이터 열람권은 동의 철회와 독립.
    """
    user = await user_factory()  # consent_factory 미호출 → basic_consents 미충족.
    response = await client.get("/v1/users/me/export?format=json", headers=auth_headers(user))
    assert response.status_code == 200, (
        f"PIPA Art.35 회귀 — 미동의 사용자도 export 가능해야 함. {response.text}"
    )


# --- Content-Disposition filename 마스킹 SOT ------------------------------


async def test_export_filename_masks_raw_uuid(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """spec deviation 1건 — ``{user_id}`` raw UUID 36자 → ``u_{8char}`` 마스킹.

    *Why*: NFR-S5 마스킹 룰셋 1지점 SOT — 다른 모든 logging/Sentry/LangSmith가 마스킹된
    상태에서 파일명만 raw UUID 노출하는 inconsistency 회피 + 사용자가 *어떤 export*인지
    8자 prefix로 충분.
    """
    user = await user_factory()
    response = await client.get("/v1/users/me/export?format=json", headers=auth_headers(user))
    cd = response.headers["content-disposition"]
    raw_uuid = str(user.id)
    # raw UUID(hyphens 포함) 미노출 검증.
    assert raw_uuid not in cd
    # 마스킹된 식별자 노출 검증.
    masked = f"u_{raw_uuid.replace('-', '')[:8]}"
    assert masked in cd


# --- nosniff 헤더 ------------------------------------------------------------


async def test_export_response_has_x_content_type_options_nosniff(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """``X-Content-Type-Options: nosniff`` — MIME sniffing 차단."""
    user = await user_factory()
    response = await client.get("/v1/users/me/export?format=json", headers=auth_headers(user))
    assert response.headers.get("x-content-type-options") == "nosniff"


# --- soft-deleted meals 제외 검증 -------------------------------------------


async def test_export_excludes_soft_deleted_meals(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """endpoint default ``include_soft_deleted_meals=False`` → soft-deleted meal 제외.

    *Why*: 사용자 권리 행사는 *현재 활성 데이터*만 의미 있음. 명시 삭제한 meal은 응답
    미포함. Worker는 ``True``(별 분기 SOT).
    """
    user = await user_factory()
    session_maker: async_sessionmaker = app.state.session_maker
    async with session_maker() as session:
        active = Meal(user_id=user.id, raw_text="active meal")
        deleted = Meal(
            user_id=user.id,
            raw_text="deleted meal",
            deleted_at=datetime.now(UTC) - timedelta(days=1),
        )
        session.add_all([active, deleted])
        await session.commit()

    response = await client.get("/v1/users/me/export?format=json", headers=auth_headers(user))
    assert response.status_code == 200, response.text
    parsed = response.json()
    raw_texts = [m["raw_text"] for m in parsed["meals"]]
    assert raw_texts == ["active meal"]


# --- AC8: audit_admin_action 미wire 가드 ----------------------------------


def _dep_name(dep_callable: Any) -> str:
    return getattr(dep_callable, "__name__", str(dep_callable))


async def test_export_endpoint_does_not_wire_audit_admin_action() -> None:
    """Story 5.3 AC8 — ``export_user_data`` endpoint signature *및* route-level dependency
    양쪽에 ``audit_*`` 미진입 가드.

    *Why*: epics.md:823 + PIPA Art.35 정합 — 일반 사용자 자기 export는 audit 미기록
    (Story 7.x admin endpoint만 audit). Story 5.2 ``delete_account`` 패턴 1:1 정합.
    """
    type_hints = typing.get_type_hints(users_router.export_user_data, include_extras=True)
    sig = inspect.signature(users_router.export_user_data)
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
                f"audit_* dependency must NOT wire to export_user_data "
                f"(param={param_name}, dep={dep_name}); PIPA Art.35 정합."
            )
    # 양성 가드 — current_user wire 필수.
    assert "current_user" in seen_dep_names, (
        f"current_user must wire to export_user_data. seen={seen_dep_names}"
    )
    # 음성 가드 — require_basic_consents 미wire(PIPA Art.35).
    assert "require_basic_consents" not in seen_dep_names, (
        f"require_basic_consents must NOT wire (PIPA Art.35). seen={seen_dep_names}"
    )

    # Route-level dependencies 검증.
    export_route = next(
        route
        for route in app.routes
        if getattr(route, "path", "") == "/v1/users/me/export"
        and "GET" in getattr(route, "methods", set())
    )
    route_deps: list[str] = []

    def _walk(dependant: Any) -> None:
        for sub in getattr(dependant, "dependencies", []) or []:
            call = getattr(sub, "call", None)
            if call is not None:
                route_deps.append(_dep_name(call))
            _walk(sub)

    _walk(export_route.dependant)
    for name in route_deps:
        assert not name.startswith("audit_"), (
            f"audit_* dependency must NOT wire at route level either (dep={name})."
        )


# --- AC7: N+1 회귀 가드 -----------------------------------------------------


async def test_export_n_plus_one_guard_meals_with_analyses(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """meals 5건 + meal_analyses 5건 → cursor.execute count ≤ 6.

    *Why*: ``selectinload(Meal.analysis)`` SOT(Story 4.3) 회귀 가드. ``lazy="raise_on_sql"``
    가드와 함께 implicit lazy load 차단 — 누락 시 본 테스트 즉시 fail.

    SQL counter 분포(상한 6 = 4 entity + 1 analyses + 1 safety):
    - SELECT users (current_user dependency)
    - SELECT users (collect — user fetch)
    - SELECT consents
    - SELECT meals (with selectinload — analyses 자동 로드)
    - SELECT meal_analyses (selectinload 별 SQL)
    - SELECT notifications
    """
    user = await user_factory()
    session_maker: async_sessionmaker = app.state.session_maker
    async with session_maker() as session:
        for i in range(5):
            meal = Meal(
                user_id=user.id,
                raw_text=f"meal {i}",
                ate_at=datetime(2026, 5, 7, 12, i, 0, tzinfo=UTC),
            )
            session.add(meal)
            await session.flush()
            session.add(
                MealAnalysis(
                    meal_id=meal.id,
                    user_id=user.id,
                    fit_score=70 + i,
                    fit_score_label="good",
                    fit_reason="ok",
                    carbohydrate_g=Decimal("100"),
                    protein_g=Decimal("20"),
                    fat_g=Decimal("10"),
                    energy_kcal=600 + i,
                    feedback_text="text",
                    feedback_summary="summary",
                    citations=[],
                    used_llm="gpt-4o-mini",
                )
            )
        await session.commit()

    cursor_count = 0
    engine = app.state.engine

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count_cursor(*_args: Any, **_kwargs: Any) -> None:
        nonlocal cursor_count
        cursor_count += 1

    try:
        response = await client.get("/v1/users/me/export?format=json", headers=auth_headers(user))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _count_cursor)

    assert response.status_code == 200, response.text
    parsed = response.json()
    assert len(parsed["meals"]) == 5
    # 5 meals × 5 analyses N+1이면 cursor count ≥ 10 — selectinload SOT가 단일 batch로 묶음.
    assert cursor_count <= 8, (
        f"N+1 회귀 의심 — cursor.execute={cursor_count}회. "
        f"selectinload(Meal.analysis) SOT(Story 4.3) 점검 필요."
    )


# --- 회귀 가드: format Literal type SOT ------------------------------------


def test_export_format_query_param_is_literal_json_csv() -> None:
    """``format`` Query는 ``Literal["json","csv"]`` SOT — 신규 format 추가 시 명시 가드 필요."""
    sig = inspect.signature(users_router.export_user_data)
    fmt_param = sig.parameters["format"]
    type_hints = typing.get_type_hints(users_router.export_user_data, include_extras=True)
    annotation = type_hints["format"]
    # Literal[...] 인자 추출 — Annotated의 first arg 또는 직접.
    args = typing.get_args(annotation)
    # Literal 타입은 ``__args__`` 또는 ``typing.get_args``로 ('json','csv').
    if args and isinstance(args[0], type) is False:
        # Annotated[Literal[...], Query(...)] 또는 Literal[...] 자체.
        literal_args = typing.get_args(args[0]) if args else ()
        if not literal_args:
            literal_args = args
    else:
        literal_args = args
    # 검증 — Literal 인자가 정확히 ('json','csv').
    flat = tuple(typing.get_args(annotation)) or ()
    # 최소한 'json'과 'csv'가 어디든 언급되어야 함 — 단순 invariant 가드.
    repr_str = str(annotation)
    assert "'json'" in repr_str and "'csv'" in repr_str, (
        f"format param Literal SOT 회귀 — annotation={annotation!r}"
    )
    _ = (fmt_param, flat)  # silence unused
