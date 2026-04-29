"""FastAPI app entrypoint.

부팅 시 다음을 초기화한다:
- structlog (JSON or console renderer + mask_processor 자리표시자)
- Sentry (DSN 있을 때만)
- slowapi limiter — 3-tier 키 정의 (60/min, 1000/hour, LangGraph 10/min). 라우터 적용은 후속 스토리.
  · Redis 가용 시 Redis 백엔드, 아니면 in-memory fallback (테스트/CI 포함).
- request_id 미들웨어 (UUIDv4 + X-Request-ID 응답 헤더)
- /healthz (liveness — 프로세스 생존만, 외부 의존성 무관 — k8s 컨벤션)
- /readyz (readiness — Postgres + Redis + pgvector extension 확인, 타임아웃 적용)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import redis.asyncio as redis_asyncio
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1 import auth as auth_router
from app.api.v1 import consents as consents_router
from app.api.v1 import legal as legal_router
from app.api.v1 import meals as meals_router
from app.api.v1 import users as users_router
from app.core.config import settings
from app.core.exceptions import (
    PROBLEM_JSON_MEDIA_TYPE,
    X_CONSENT_LATEST_VERSION_HEADER,
    AutomatedDecisionConsentVersionMismatchError,
    BalanceNoteError,
    ConsentVersionMismatchError,
    ProblemDetail,
    encode_latest_version_header,
)
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware
from app.core.sentry import init_sentry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# AC5 — 3-tier rate limit 키 정의 (라우터 적용은 후속 스토리)
RATE_LIMIT_USER_PER_MINUTE = "60/minute"
RATE_LIMIT_USER_PER_HOUR = "1000/hour"
RATE_LIMIT_LANGGRAPH = "10/minute"

PROBE_TIMEOUT_SECONDS = 2.0
_NON_PROD_ENVIRONMENTS = {"ci", "test"}


def _build_limiter(storage_uri: str) -> Limiter:
    return Limiter(
        key_func=get_remote_address,
        default_limits=[RATE_LIMIT_USER_PER_HOUR, RATE_LIMIT_USER_PER_MINUTE],
        storage_uri=storage_uri,
        # AC5의 LangGraph tier는 후속 스토리에서 라우트별 데코레이터로 적용.
        # 현 시점에는 키 상수(RATE_LIMIT_LANGGRAPH)만 정의 — 모듈 import로 노출.
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    init_sentry()

    log = structlog.get_logger()
    log.info("app.startup", environment=settings.environment)

    # 자원 init은 각각 독립 try/except — 한 자원 실패가 다른 자원·앱 부팅 자체를 막지 않음.
    try:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        app.state.engine = engine
        app.state.session_maker = async_sessionmaker(engine, expire_on_commit=False)
    except Exception as exc:  # noqa: BLE001
        log.error("app.startup.engine_init_failed", error=str(exc))
        app.state.engine = None
        app.state.session_maker = None

    try:
        app.state.redis = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    except Exception as exc:  # noqa: BLE001
        log.error("app.startup.redis_init_failed", error=str(exc))
        app.state.redis = None

    # Limiter는 (a) 테스트/CI 또는 (b) Redis init 실패 시 in-memory fallback.
    use_memory_storage = settings.environment in _NON_PROD_ENVIRONMENTS or app.state.redis is None
    storage_uri = "memory://" if use_memory_storage else settings.redis_url
    try:
        app.state.limiter = _build_limiter(storage_uri)
    except Exception as exc:  # noqa: BLE001
        log.error("app.startup.limiter_init_failed", error=str(exc))
        app.state.limiter = _build_limiter("memory://")

    try:
        yield
    finally:
        # cleanup 자원별 독립 — 한쪽 실패가 나머지 cleanup을 막지 않음.
        cleanup_engine = getattr(app.state, "engine", None)
        if cleanup_engine is not None:
            try:
                await cleanup_engine.dispose()
            except Exception as exc:  # noqa: BLE001
                log.warning("app.shutdown.engine_dispose_failed", error=str(exc))

        cleanup_redis = getattr(app.state, "redis", None)
        if cleanup_redis is not None:
            try:
                await cleanup_redis.aclose()
            except Exception as exc:  # noqa: BLE001
                log.warning("app.shutdown.redis_aclose_failed", error=str(exc))

        log.info("app.shutdown")


app = FastAPI(
    title="BalanceNote API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — `/v1/auth/*`은 본 프로젝트의 첫 cross-origin endpoint.
# `allow_credentials=True` + `allow_origins=["*"]` 조합 절대 금지(브라우저 차단).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
)
app.add_middleware(RequestIdMiddleware)


# --- RFC 7807 Problem Details 글로벌 핸들러 -----------------------------------
# 등록 순서: 가장 구체적인 BalanceNoteError → RequestValidationError(HTTPException 서브클래스)
# → HTTPException base. FastAPI는 등록 순서가 아닌 가장 구체적인 핸들러로 디스패치하지만,
# 명시적으로 좁은 범위부터 등록해두면 의도가 코드에 그대로 드러난다.


def _sanitize_header_value(value: str) -> str:
    """RFC 6750 quoted-string 안전화 — `"`, CR, LF 제거(헤더 인젝션 차단)."""
    return value.replace('"', "").replace("\r", "").replace("\n", "")


def _problem_response(
    problem: ProblemDetail,
    *,
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    headers: dict[str, str] = {}
    if problem.status == 401:
        # RFC 6750 — 401 응답에는 WWW-Authenticate 헤더 동시 첨부.
        description = _sanitize_header_value(problem.detail or problem.title)
        headers["WWW-Authenticate"] = (
            f'Bearer realm="balancenote", error="invalid_token", error_description="{description}"'
        )
    if extra_headers:
        headers.update(extra_headers)
    return JSONResponse(
        status_code=problem.status,
        content=problem.to_response_dict(),
        media_type=PROBLEM_JSON_MEDIA_TYPE,
        headers=headers,
    )


@app.exception_handler(BalanceNoteError)
async def balancenote_exception_handler(request: Request, exc: BalanceNoteError) -> JSONResponse:
    extra_headers: dict[str, str] | None = None
    # Story 1.4 W13 — 409 version mismatch 응답에 ``X-Consent-Latest-Version`` 첨부.
    # 클라이언트가 추가 GET round-trip 없이 latest version 즉시 인식.
    if (
        isinstance(exc, ConsentVersionMismatchError | AutomatedDecisionConsentVersionMismatchError)
        and exc.latest_versions
    ):
        extra_headers = {
            X_CONSENT_LATEST_VERSION_HEADER: encode_latest_version_header(exc.latest_versions),
        }
    return _problem_response(
        exc.to_problem(instance=str(request.url.path)),
        extra_headers=extra_headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    problem = ProblemDetail(
        title="Validation Error",
        status=400,
        detail="Request validation failed",
        instance=str(request.url.path),
        code="validation.error",
    )
    # RFC 7807은 확장 멤버 허용 — 필드별 에러 배열을 `errors`로 추가.
    payload: dict[str, object] = dict(problem.to_response_dict())
    payload["errors"] = [
        {"loc": list(err.get("loc", [])), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=400,
        content=payload,
        media_type=PROBLEM_JSON_MEDIA_TYPE,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    problem = ProblemDetail(
        title=detail or "HTTP Error",
        status=exc.status_code,
        detail=detail,
        instance=str(request.url.path),
        code=f"http.{exc.status_code}",
    )
    return _problem_response(problem, extra_headers=dict(exc.headers or {}))


# --- Routers ----------------------------------------------------------------
app.include_router(auth_router.router, prefix="/v1/auth", tags=["auth"])
app.include_router(users_router.router, prefix="/v1/users", tags=["users"])
app.include_router(consents_router.router, prefix="/v1/users/me/consents", tags=["consents"])
app.include_router(legal_router.router, prefix="/v1/legal", tags=["legal"])
app.include_router(meals_router.router, prefix="/v1/meals", tags=["meals"])


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Liveness probe — 프로세스 생존 신호만 응답. DB·Redis 의존성 없음.

    k8s liveness 컨벤션상 외부 의존성과 분리되어야 함. DB 일시 장애가 컨테이너 재시작
    루프를 유발하지 않도록. DB·Redis·pgvector 확인은 /readyz에서 담당.
    """
    return JSONResponse({"status": "ok"})


@app.get("/readyz")
async def readyz() -> JSONResponse:
    """Readiness probe — Postgres + Redis + pgvector extension 확인 (타임아웃 적용)."""
    checks: dict[str, str] = {}
    overall_ok = True

    engine = getattr(app.state, "engine", None)
    if engine is None:
        checks["postgres"] = "starting"
        checks["pgvector"] = "unknown"
        overall_ok = False
    else:
        try:
            async with engine.connect() as conn:
                await asyncio.wait_for(
                    conn.execute(text("SELECT 1")), timeout=PROBE_TIMEOUT_SECONDS
                )
                result = await asyncio.wait_for(
                    conn.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")),
                    timeout=PROBE_TIMEOUT_SECONDS,
                )
                row = result.first()
                checks["postgres"] = "ok"
                checks["pgvector"] = "ok" if row is not None else "missing"
                if row is None:
                    overall_ok = False
        except TimeoutError:
            checks["postgres"] = "timeout"
            checks["pgvector"] = "unknown"
            overall_ok = False
        except Exception:
            # 내부 예외 문자열은 로그로만 — 응답 본문에는 노출 금지 (info disclosure 차단)
            structlog.get_logger().exception("readyz.postgres_check_failed")
            checks["postgres"] = "fail"
            checks["pgvector"] = "unknown"
            overall_ok = False

    redis_client = getattr(app.state, "redis", None)
    if redis_client is None:
        checks["redis"] = "starting"
        overall_ok = False
    else:
        try:
            pong = await asyncio.wait_for(redis_client.ping(), timeout=PROBE_TIMEOUT_SECONDS)
            if pong is True:
                checks["redis"] = "ok"
            else:
                checks["redis"] = "fail"
                overall_ok = False
        except TimeoutError:
            checks["redis"] = "timeout"
            overall_ok = False
        except Exception:
            structlog.get_logger().exception("readyz.redis_check_failed")
            checks["redis"] = "fail"
            overall_ok = False

    payload = {"status": "ok" if overall_ok else "not-ready", **checks}
    return JSONResponse(status_code=200 if overall_ok else 503, content=payload)
