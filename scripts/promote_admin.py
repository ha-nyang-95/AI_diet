"""Story 7.1 — admin role flip CLI.

사용법:
  uv run python scripts/promote_admin.py --email user@example.com
  uv run python scripts/promote_admin.py --email user@example.com --demote
  uv run python scripts/promote_admin.py --email user@example.com --yes  # confirm 생략

흐름:
  1. SQLAlchemy async engine 연결(``settings.database_url`` SOT).
  2. ``SELECT id, email, role FROM users WHERE email=$1 AND deleted_at IS NULL``.
  3. 미발견 → exit 1 + stderr "사용자를 찾을 수 없습니다".
  4. 같은 role이면 warning + exit 0(변경 없음).
  5. confirm prompt(``--yes`` 미지정 시) — non-tty + prod/staging은 fail-fast (exit 3).
  6. 트랜잭션 wrap UPDATE → 재조회 + 결과 출력.
  7. **forward-compat**: Story 7.3 audit log 도입 시 본 CLI도 audit_logs row INSERT
     (actor_id="cli", action="admin_role_flip", target_user_id=...) 추가 — 본 스토리는
     forward stub 코멘트만 인용.

Exit codes:
  0 — 성공 또는 변경 없음(이미 같은 role) 또는 사용자 confirm 취소.
  1 — 사용자 미발견.
  2 — DB 연결/쿼리 실패.
  3 — prod/staging 환경 + ``--yes`` 미지정 + non-tty (실수 자동 실행 차단).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Literal

# scripts → repo root → api 경로 등록(``app.*`` import 호환).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import select, update  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.models.user import User  # noqa: E402

_PROD_LIKE_ENVIRONMENTS: frozenset[str] = frozenset({"prod", "staging"})


def _is_non_tty() -> bool:
    """stdin이 tty가 아닌지(자동화 컨텍스트)."""
    return not sys.stdin.isatty()


async def promote_admin(
    *,
    email: str,
    demote: bool = False,
    confirm_yes: bool = False,
) -> int:
    """admin role flip 메인 흐름.

    Returns:
        Exit code (0 success / 1 not found / 2 DB error / 3 non-tty prod-like).
    """
    target_role: Literal["user", "admin"] = "user" if demote else "admin"

    if (
        not confirm_yes
        and settings.environment in _PROD_LIKE_ENVIRONMENTS
        and _is_non_tty()
    ):
        print(
            "prod/staging 환경에서는 --yes 명시가 필요합니다 (자동화 컨텍스트 차단).",
            file=sys.stderr,
        )
        return 3

    try:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    except Exception as exc:  # noqa: BLE001 — DB 연결 실패 graceful.
        print(f"DB 연결에 실패했습니다: {exc}", file=sys.stderr)
        return 2

    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                select(User.id, User.email, User.role).where(
                    User.email == email,
                    User.deleted_at.is_(None),
                )
            )
            row = result.first()
            if row is None:
                print(
                    f"사용자를 찾을 수 없습니다: {email!r} (또는 탈퇴됨).",
                    file=sys.stderr,
                )
                return 1

            current_role = row.role
            if current_role == target_role:
                print(
                    f"사용자 {email}는 이미 '{current_role}' role입니다 — 변경 없음.",
                )
                return 0

            print(f"사용자 {email} 현재 role: '{current_role}'")
            if not confirm_yes:
                answer = input(
                    f"'{target_role}'로 flip하시겠습니까? [y/N]: "
                ).strip().lower()
                if answer not in {"y", "yes"}:
                    print("취소되었습니다 — role 변경 없음.")
                    return 0

            # SQLAlchemy 2.x async ``engine.connect()``는 첫 ``execute``에서 autobegin —
            # commit 호출로 명시 종료 후 fresh read.
            await conn.execute(
                update(User).where(User.id == row.id).values(role=target_role)
            )
            await conn.commit()
            verify = await conn.execute(
                select(User.role).where(User.id == row.id)
            )
            new_role = verify.scalar_one()
            print(f"사용자 {email} role: '{current_role}' → '{new_role}'")
            return 0
    except Exception as exc:  # noqa: BLE001 — DB 쿼리 graceful.
        print(f"DB 작업 실패: {exc}", file=sys.stderr)
        return 2
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Admin role flip CLI (Story 7.1).",
    )
    parser.add_argument(
        "--email", required=True, help="대상 사용자 email (users.email)."
    )
    parser.add_argument(
        "--demote",
        action="store_true",
        help="admin → user (default는 user → admin)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm prompt skip (CI/automation 호환).",
    )
    args = parser.parse_args(argv)
    return asyncio.run(
        promote_admin(
            email=args.email,
            demote=args.demote,
            confirm_yes=args.yes,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
