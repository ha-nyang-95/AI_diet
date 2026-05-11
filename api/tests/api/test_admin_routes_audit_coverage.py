"""Story 7.3 CR P5 — ``/v1/admin/*`` 라우터 ``audit_admin_action`` wire 정적 가드.

신규 admin business endpoint가 ``audit_admin_action`` dep 누락으로 추가되면 CI에서
차단. FR37 *"관리자의 모든 조회·수정 액션 audit log 자동 기록"* drift 방지.

scope 외 endpoint(``admin_whoami``/``admin_exchange`` — 인증 lifecycle 또는 admin
meta-info 조회)는 명시 allowlist SOT(``_AUDIT_SCOPE_EXCLUDED_ROUTE_PATHS``)에 등재.
SOT를 변경할 때는 명시적 의사결정 + spec 갱신 의무.
"""

from __future__ import annotations

from typing import Final

from fastapi.routing import APIRoute

from app.api.deps import audit_admin_action
from app.main import app

# Story 7.3 scope 외 — audit 미적용 명시 SOT (spec 837-839 + Story 7.1 docstring 580
# 정합). 인증 lifecycle / admin meta-info introspection은 business action 범주 외.
_AUDIT_SCOPE_EXCLUDED_ROUTE_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/v1/auth/admin/whoami",
        "/v1/auth/admin/exchange",
    }
)

# ``audit_admin_action`` factory가 반환한 closure는 ``_dep`` 함수 이름 +
# ``audit_admin_action.<locals>._dep`` qualname을 갖는다 — 정적 식별 SOT.
_AUDIT_DEP_FUNC_NAME: Final[str] = "_dep"
_AUDIT_DEP_QUALNAME_PREFIX: Final[str] = "audit_admin_action"


def _dep_call_is_audit_wire(dep_call: object) -> bool:
    """dep callable이 ``audit_admin_action`` factory가 반환한 closure인지 확인."""
    name = getattr(dep_call, "__name__", "")
    qualname = getattr(dep_call, "__qualname__", "")
    return name == _AUDIT_DEP_FUNC_NAME and qualname.startswith(_AUDIT_DEP_QUALNAME_PREFIX)


def _route_has_audit_admin_action_wire(route: APIRoute) -> bool:
    """route의 dep tree에서 ``audit_admin_action`` ``_dep`` 등장 여부 확인.

    ``dependencies=[Depends(audit_admin_action(...))]`` 데코레이터 wire는
    ``route.dependant.dependencies`` top-level에 등록된다(handler signature dep와
    분리 보존).
    """
    for sub_dep in route.dependant.dependencies:
        if sub_dep.call is None:
            continue
        if _dep_call_is_audit_wire(sub_dep.call):
            return True
    return False


def test_audit_admin_action_factory_returns_recognizable_dep() -> None:
    """``audit_admin_action(action=..., target_resource=...)`` 반환 callable이
    ``_dep_call_is_audit_wire``로 식별 가능 — 본 가드 자체의 self-test.

    factory 구현이 변경되어 closure 이름 규칙이 깨지면 본 테스트가 fail →
    가드 식별자 SOT 동기화 의무.
    """
    dep = audit_admin_action(action="user_search", target_resource="users")
    assert _dep_call_is_audit_wire(dep)


def test_all_v1_admin_business_routes_have_audit_admin_action_wire() -> None:
    """``/v1/admin/*`` business endpoint는 모두 ``audit_admin_action`` dep wire.

    신규 admin endpoint가 audit wire 없이 추가되면 본 테스트가 fail. FR37
    *"모든 조회·수정 액션 audit log 자동 기록"* invariant drift CI 가드 — Story
    7.3 scope SOT.
    """
    audit_missing: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/v1/admin"):
            continue
        if not _route_has_audit_admin_action_wire(route):
            audit_missing.append(f"{sorted(route.methods)} {route.path} ({route.name})")

    assert not audit_missing, (
        "Admin business routes missing audit_admin_action wire (FR37 drift — "
        "Story 7.3 invariant violated):\n  - " + "\n  - ".join(audit_missing)
    )


def test_v1_auth_admin_endpoints_are_intentionally_not_audited() -> None:
    """``admin_whoami``/``admin_exchange``는 audit 대상 X — 의도적 exclusion SOT.

    spec 837-839 + Story 7.1 docstring 580 정합. exclusion SOT가 stale(엔드포인트
    삭제·리네임)이면 본 테스트가 fail → SOT 갱신 의무. 반대로 exclusion 항목에
    audit wire가 추가되면 의도 위반 → 본 테스트가 fail.
    """
    seen_paths: set[str] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path not in _AUDIT_SCOPE_EXCLUDED_ROUTE_PATHS:
            continue
        seen_paths.add(route.path)
        assert not _route_has_audit_admin_action_wire(route), (
            f"{route.path} is audit-scope-excluded by SOT but has audit wire — intent violation"
        )

    missing = _AUDIT_SCOPE_EXCLUDED_ROUTE_PATHS - seen_paths
    assert not missing, (
        f"audit-scope-excluded routes missing from app.routes (stale SOT): {sorted(missing)}"
    )
