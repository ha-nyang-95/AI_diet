"""Story 3.3 — `tests/graph/` 공통 fixtures.

`fake_deps`: `NodeDeps` 인스턴스를 fake `session_maker`/`redis=None`/실 `settings`로
구성 — DB 노드(`fetch_user_profile`) 외 stub 노드 대부분이 `deps`를 *읽지만 사용 X*.

DB 통합 fixture(`db_deps`)는 conftest.py 의 session_maker를 재활용.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.graph.deps import NodeDeps
from app.main import app


@pytest.fixture
def fake_deps() -> NodeDeps:
    """DB·redis 미사용 stub 노드용 fake `NodeDeps`."""
    fake_session_maker: Any = MagicMock(spec=async_sessionmaker)
    return NodeDeps(session_maker=fake_session_maker, redis=None, settings=settings)


@pytest_asyncio.fixture
async def db_deps(client: AsyncClient) -> NodeDeps:
    """실 DB session_maker 기반 `NodeDeps` — `fetch_user_profile` 통합 테스트용."""
    _ = client  # ensure lifespan started
    return NodeDeps(
        session_maker=app.state.session_maker,
        redis=app.state.redis,
        settings=settings,
    )
