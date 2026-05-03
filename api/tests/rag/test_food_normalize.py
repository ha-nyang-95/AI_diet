"""Story 3.4 — `app/rag/food/normalize.py` `lookup_canonical` 단위 테스트 (AC3).

mock AsyncSession 기반 단위 테스트 — DB 도달 X. 시드 의존 통합 테스트는
``test_food_aliases_seed.py``(Story 3.1 baseline) + retrieve_nutrition 노드 통합
테스트가 분담.

케이스:
1. seeded ``"자장면"`` → ``"짜장면"`` (mock DB hit).
2. 미스 ``"임의의_음식_xyz"`` → ``None``.
3. 빈 입력 ``""`` → ``None`` (DB 호출 X — execute 호출 횟수 0).
4. 공백 trim 차이(``"  자장면  "``) → ``None`` (사전적 exact 매칭 강제 — DB 호출 X).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.rag.food.normalize import lookup_canonical


def _build_mock_session(scalar_value: str | None) -> tuple[MagicMock, AsyncMock]:
    """`session.execute(stmt).scalar_one_or_none()` 체인 mock."""
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    execute_mock = AsyncMock(return_value=result)
    session.execute = execute_mock
    return session, execute_mock


async def test_lookup_canonical_alias_hit() -> None:
    """seeded `"자장면"` → `"짜장면"` (mock DB hit)."""
    session, execute = _build_mock_session("짜장면")

    result = await lookup_canonical(session, "자장면")

    assert result == "짜장면"
    assert execute.await_count == 1


async def test_lookup_canonical_alias_miss() -> None:
    """미스 → `None`."""
    session, execute = _build_mock_session(None)

    result = await lookup_canonical(session, "임의의_음식_xyz")

    assert result is None
    assert execute.await_count == 1


async def test_lookup_canonical_empty_input_no_db_call() -> None:
    """빈 입력 → DB 호출 X (cost 0)."""
    session, execute = _build_mock_session("never_returned")

    result_empty = await lookup_canonical(session, "")
    assert result_empty is None
    assert execute.await_count == 0

    result_ws = await lookup_canonical(session, "   ")
    assert result_ws is None
    assert execute.await_count == 0


async def test_lookup_canonical_whitespace_padded_input_returns_none() -> None:
    """공백 trim 차이 → 사전적 exact 매칭 강제 → `None` (DB 호출 X)."""
    session, execute = _build_mock_session("짜장면")

    result = await lookup_canonical(session, "  자장면  ")

    # 사전 entry는 trimmed only — 공백 padded 입력은 호출자가 trim 책임 → 본 함수는 미스.
    assert result is None
    # DB 호출 X (cost 0) — 사전적 exact 매칭만.
    assert execute.await_count == 0
