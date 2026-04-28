"""pytest fixtures — async test client + 인프라 precondition fail-fast.

전제: Postgres(+pgvector extension 등록) + Redis 가 실행 중.
- CI: service container + `CREATE EXTENSION vector` 사전 실행 (CI workflow에서)
- 로컬: docker compose up

pgvector extension이 누락된 환경에서 테스트가 cryptic 503으로 실패하지 않도록
session-scoped fixture로 한 번 검증하고, 실패 시 명확한 메시지로 즉시 abort.

Story 1.2부터:
- alembic 마이그레이션 자동 적용(테스트 DB가 0002 상태가 되도록 보장)
- user_factory async fixture — DB에 user를 직접 INSERT
- auth_headers helper — Authorization 헤더 dict 생성
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from alembic.config import Config as AlembicConfig
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command as alembic_command
from app.core.config import settings
from app.core.security import create_user_token
from app.db.models.consent import Consent
from app.db.models.user import User
from app.domain.legal_documents import CURRENT_VERSIONS
from app.main import app


def _alembic_config() -> AlembicConfig:
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _verify_pgvector_extension() -> None:
    """Fail fast if pgvector extension is missing — surface clear remediation."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname='vector'")
            )
            row = result.first()
        if row is None:
            pytest.fail(
                "pgvector extension not installed in target Postgres.\n"
                "  Local: `docker compose up` (postgres-init/01-pgvector.sql 자동 실행).\n"
                '  CI/manual: `psql -c "CREATE EXTENSION IF NOT EXISTS vector;"`',
                pytrace=False,
            )
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _alembic_upgrade_head() -> None:
    """테스트 DB를 head 상태로 보장 — Story 1.2 0002 마이그레이션 자동 적용.

    alembic 명령은 sync API라 thread executor에서 실행.
    """
    await asyncio.to_thread(alembic_command.upgrade, _alembic_config(), "head")


@pytest_asyncio.fixture(autouse=True)
async def _truncate_user_tables() -> AsyncIterator[None]:
    """매 테스트 *시작 전* users / refresh_tokens 비움 — 첫 테스트 직전 잔존 데이터까지 격리.

    setup 단계에서 TRUNCATE해야 (a) 이전 실행이 abort된 후에도 깨끗한 시작 + (b) 첫 테스트가
    서버 마이그레이션 직후 데이터 없이 시작 가능. teardown에서 truncate 시 첫 테스트는 무방비.

    pytest-asyncio function-scoped event loop + asyncpg는 session-scoped engine 공유 시
    cross-loop 사용 위험 — engine을 매 테스트 생성·dispose 한다(perf 비용 < 안전성).
    """
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            # consents는 users.id ON DELETE CASCADE라 자동 cascade되지만, 명시 prepend로
            # 가독성 + 후속 모델 추가 시 truncate 누락 회피.
            await conn.execute(
                text("TRUNCATE consents, refresh_tokens, users RESTART IDENTITY CASCADE")
            )
    finally:
        await engine.dispose()
    yield


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # lifespan_context로 startup/shutdown 트리거 (engine, redis 초기화)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as ac,
        app.router.lifespan_context(app),
    ):
        yield ac


UserFactory = Callable[..., Awaitable[User]]


@pytest_asyncio.fixture
async def user_factory(client: AsyncClient) -> UserFactory:
    """test DB에 user row를 INSERT하는 async factory.

    `client` fixture에 의존 — lifespan이 활성화돼 `app.state.session_maker`가 init된 상태.
    """
    _ = client  # ensure lifespan started

    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker

    async def _make(
        *,
        role: str = "user",
        email: str | None = None,
        google_sub: str | None = None,
        display_name: str | None = "Test User",
        picture_url: str | None = None,
        deleted: bool = False,
    ) -> User:
        async with session_maker() as session:
            user = User(
                google_sub=google_sub or f"google-sub-{uuid.uuid4()}",
                email=email or f"{uuid.uuid4().hex}@example.com",
                email_verified=True,
                display_name=display_name,
                picture_url=picture_url,
                role=role,
                last_login_at=datetime.now(UTC),
                deleted_at=datetime.now(UTC) if deleted else None,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return _make


def auth_headers(user: User, *, platform: str = "mobile") -> dict[str, str]:
    """user JWT를 Authorization 헤더로 직조."""
    token = create_user_token(user.id, role=user.role, platform=platform)
    return {"Authorization": f"Bearer {token}"}


ConsentFactory = Callable[..., Awaitable[Consent]]


@pytest_asyncio.fixture
async def consent_factory(client: AsyncClient) -> ConsentFactory:
    """test DB에 consents row를 직접 INSERT하는 async factory.

    키워드 인자로 부분 동의 구성 가능 — ``sensitive=False`` 단일 누락 케이스 등 PIPA
    23조 회귀 테스트에 사용.

    ``version`` 인자는 4 항목 모두에 동일 적용 — 미지정 시 ``CURRENT_VERSIONS``의
    값(현 SOT)을 사용해 ``basic_consents_complete=True`` 시나리오를 자연스럽게 구성.
    """
    _ = client

    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker

    async def _make(
        user: User,
        *,
        disclaimer: bool = True,
        terms: bool = True,
        privacy: bool = True,
        sensitive: bool = True,
        version: str | None = None,
    ) -> Consent:
        now = datetime.now(UTC)
        async with session_maker() as session:
            consent = Consent(
                user_id=user.id,
                disclaimer_acknowledged_at=now if disclaimer else None,
                terms_consent_at=now if terms else None,
                privacy_consent_at=now if privacy else None,
                sensitive_personal_info_consent_at=now if sensitive else None,
                disclaimer_version=(
                    (version or CURRENT_VERSIONS["disclaimer"]) if disclaimer else None
                ),
                terms_version=((version or CURRENT_VERSIONS["terms"]) if terms else None),
                privacy_version=((version or CURRENT_VERSIONS["privacy"]) if privacy else None),
                sensitive_personal_info_version=(
                    (version or CURRENT_VERSIONS["sensitive_personal_info"]) if sensitive else None
                ),
            )
            session.add(consent)
            await session.commit()
            await session.refresh(consent)
            return consent

    return _make
