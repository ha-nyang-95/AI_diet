"""Story 3.3 — `NodeDeps` 노드 의존성 컨테이너 (D8 — closure 패턴).

LangGraph 표준 노드 시그니처는 `(state) -> dict` — 외부 자원(DB session / Redis /
settings) 접근은 `functools.partial(node, deps=deps)` wrap으로 컴파일 시점 주입.
테스트에서는 fake `NodeDeps` instance 만들어 의존성 격리.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as redis_asyncio
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.config import Settings


@dataclass(frozen=True)
class NodeDeps:
    """LangGraph 노드들이 공유하는 외부 자원.

    `frozen=True` — pipeline 컴파일 시점 1회 생성 후 immutable. 노드 wrapper
    `functools.partial(node, deps=deps)`가 cell variable로 캡처.
    """

    session_maker: async_sessionmaker[AsyncSession]
    redis: redis_asyncio.Redis | None
    settings: Settings
