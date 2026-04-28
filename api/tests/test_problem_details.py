"""Story 1.2 — RFC 7807 Problem Details 글로벌 핸들러 단위 테스트 (AC #8).

검증:
- BalanceNoteError 서브클래스 → status / code / media_type 정합
- RequestValidationError → 400 + code=validation.error + errors 확장
- HTTPException → code=http.<status>
- 401 응답에 WWW-Authenticate: Bearer ... 헤더 동시 첨부
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.core.exceptions import (
    PROBLEM_JSON_MEDIA_TYPE,
    AccessTokenExpiredError,
    AdminRoleRequiredError,
    BalanceNoteError,
    InvalidIdTokenError,
)
from app.main import (
    balancenote_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)


def _build_isolated_app() -> FastAPI:
    """글로벌 핸들러만 검증하기 위한 격리된 FastAPI 인스턴스.

    `app.main.app`은 lifespan에서 DB/Redis init이 필요해 부담이 크다.
    핸들러 함수는 module-level이므로 본 헬퍼가 재바인딩.
    """
    test_app = FastAPI()
    test_app.add_exception_handler(BalanceNoteError, balancenote_exception_handler)  # type: ignore[arg-type]
    test_app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,  # type: ignore[arg-type]
    )
    test_app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]

    @test_app.get("/raise/expired")
    async def _expired() -> None:
        raise AccessTokenExpiredError("access token expired")

    @test_app.get("/raise/invalid-id-token")
    async def _invalid_id() -> None:
        raise InvalidIdTokenError("google id_token signature mismatch")

    @test_app.get("/raise/admin-required")
    async def _admin() -> None:
        raise AdminRoleRequiredError("admin required")

    @test_app.get("/raise/http")
    async def _http() -> None:
        raise HTTPException(status_code=418, detail="im a teapot")

    class Body(BaseModel):
        x: int

    @test_app.post("/validate")
    async def _validate(body: Body) -> dict[str, int]:
        return {"x": body.x}

    return test_app


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_balancenote_error_returns_problem_json() -> None:
    app = _build_isolated_app()
    async with await _client(app) as ac:
        response = await ac.get("/raise/expired")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    body = response.json()
    assert body["status"] == 401
    assert body["code"] == "auth.access_token.expired"
    assert body["title"] == "Access token expired"
    assert body["instance"] == "/raise/expired"


async def test_balancenote_401_attaches_www_authenticate_header() -> None:
    app = _build_isolated_app()
    async with await _client(app) as ac:
        response = await ac.get("/raise/invalid-id-token")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "auth.google.id_token_invalid"
    auth_header = response.headers.get("www-authenticate", "")
    assert auth_header.startswith("Bearer ")
    assert 'realm="balancenote"' in auth_header
    assert 'error="invalid_token"' in auth_header


async def test_balancenote_403_admin_required() -> None:
    app = _build_isolated_app()
    async with await _client(app) as ac:
        response = await ac.get("/raise/admin-required")
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "auth.admin.role_required"
    # 403은 WWW-Authenticate 비강제(401만 강제).
    assert "www-authenticate" not in {k.lower() for k in response.headers}


async def test_http_exception_maps_to_http_code() -> None:
    app = _build_isolated_app()
    async with await _client(app) as ac:
        response = await ac.get("/raise/http")
    assert response.status_code == 418
    body = response.json()
    assert body["code"] == "http.418"
    assert body["detail"] == "im a teapot"


async def test_validation_error_maps_to_400_with_errors_field() -> None:
    app = _build_isolated_app()
    async with await _client(app) as ac:
        response = await ac.post("/validate", json={"x": "not-a-number"})
    assert response.status_code == 400
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    body = response.json()
    assert body["status"] == 400
    assert body["code"] == "validation.error"
    assert isinstance(body["errors"], list)
    assert len(body["errors"]) >= 1
    assert "loc" in body["errors"][0]
