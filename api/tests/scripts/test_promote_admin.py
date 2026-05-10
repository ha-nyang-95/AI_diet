"""Story 7.1 AC3 — ``scripts/promote_admin.py`` CLI 6 케이스 단위 테스트.

테스트:
1. ``test_promote_user_to_admin_succeeds`` — fixture user → admin → DB role=admin.
2. ``test_promote_admin_to_admin_warns_no_change`` — 이미 admin → exit 0 + DB 변경 0.
3. ``test_demote_admin_to_user`` — ``--demote`` flag → admin → user.
4. ``test_promote_user_not_found_exits_with_code_1`` — 미존재 email → exit 1.
5. ``test_promote_soft_deleted_user_excluded`` — ``deleted_at`` 사용자 → 미발견 분기.
6. ``test_promote_idempotent_within_transaction`` — 같은 user 2회 promote → 두 번째는 변경 0.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models.user import User
from app.main import app

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from promote_admin import promote_admin  # type: ignore[import-not-found] # noqa: E402

UserFactory = Callable[..., Awaitable[User]]


async def _read_role_from_db(user_id) -> str | None:
    """DB에서 user.role을 fresh read."""
    session_maker = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(select(User.role).where(User.id == user_id))
        return result.scalar_one_or_none()


# --- 1: user → admin -----------------------------------------------------


async def test_promote_user_to_admin_succeeds(
    client,  # noqa: ANN001 — pytest fixture
    user_factory: UserFactory,
) -> None:
    user = await user_factory(role="user", email="promote-target@example.com")
    code = await promote_admin(
        email="promote-target@example.com",
        demote=False,
        confirm_yes=True,
    )
    assert code == 0
    new_role = await _read_role_from_db(user.id)
    assert new_role == "admin"


# --- 2: admin → admin (no change) ----------------------------------------


async def test_promote_admin_to_admin_warns_no_change(
    client,  # noqa: ANN001
    user_factory: UserFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    user = await user_factory(role="admin", email="already-admin@example.com")
    code = await promote_admin(
        email="already-admin@example.com",
        demote=False,
        confirm_yes=True,
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "이미 'admin' role입니다" in captured.out
    new_role = await _read_role_from_db(user.id)
    assert new_role == "admin"


# --- 3: --demote ---------------------------------------------------------


async def test_demote_admin_to_user(
    client,  # noqa: ANN001
    user_factory: UserFactory,
) -> None:
    user = await user_factory(role="admin", email="demote-target@example.com")
    code = await promote_admin(
        email="demote-target@example.com",
        demote=True,
        confirm_yes=True,
    )
    assert code == 0
    new_role = await _read_role_from_db(user.id)
    assert new_role == "user"


# --- 4: not found → exit 1 -----------------------------------------------


async def test_promote_user_not_found_exits_with_code_1(
    client,  # noqa: ANN001
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = await promote_admin(
        email="nonexistent@example.com",
        demote=False,
        confirm_yes=True,
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "사용자를 찾을 수 없습니다" in captured.err


# --- 5: deleted_at 사용자 → 미발견 분기 ---------------------------------


async def test_promote_soft_deleted_user_excluded(
    client,  # noqa: ANN001
    user_factory: UserFactory,
) -> None:
    """soft-deleted user는 ``deleted_at IS NULL`` 필터에서 제외 → exit 1."""
    await user_factory(
        role="user",
        email="soft-deleted@example.com",
        deleted=True,
    )
    code = await promote_admin(
        email="soft-deleted@example.com",
        demote=False,
        confirm_yes=True,
    )
    assert code == 1


# --- 6: 멱등 — 2회 호출 ------------------------------------------------


async def test_promote_idempotent_within_transaction(
    client,  # noqa: ANN001
    user_factory: UserFactory,
) -> None:
    """같은 user 2회 promote 호출 → 첫 번째 admin 전이, 두 번째는 변경 0."""
    user = await user_factory(role="user", email="idempotent@example.com")
    code1 = await promote_admin(
        email="idempotent@example.com",
        demote=False,
        confirm_yes=True,
    )
    code2 = await promote_admin(
        email="idempotent@example.com",
        demote=False,
        confirm_yes=True,
    )
    assert code1 == 0
    assert code2 == 0
    new_role = await _read_role_from_db(user.id)
    assert new_role == "admin"
