"""0016_users_profile_updated_at — Story 5.1 (건강 프로필 수정 timestamp 컬럼).

``users.profile_updated_at`` DateTime(timezone=True) nullable 컬럼 1건 추가.

3 timestamp 컬럼 의미 분리(SOT):
- ``profile_completed_at`` (Story 1.5) — *최초 온보딩 완료 시점*. ``POST /me/profile``
  최초 입력 시 set, ``PATCH /me/profile`` 시 미터치(invariant 보존).
- ``profile_updated_at`` (Story 5.1, 본 revision) — *프로필을 명시적으로 마지막 수정한
  시점*. ``PATCH /me/profile`` 시 set. 본 컬럼은 ``POST /me/profile``로는 영향 X
  (POST는 *최초 입력*, PATCH는 *수정* — 의미 분리).
- ``updated_at`` (Story 1.2) — *행 단위 마지막 변경 시점*. SQLAlchemy ``onupdate``로
  macro_goal/notification/profile/role 등 모든 컬럼 변경 시 bump.

기존 모든 row는 ``profile_updated_at = NULL`` default — 회귀 0건. PATCH 첫 호출
시점에 set.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_users_profile_updated_at"
down_revision: str | None = "0015_users_macro_goal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_NAME = "users"
_COLUMN_NAME = "profile_updated_at"


def upgrade() -> None:
    op.add_column(
        _TABLE_NAME,
        sa.Column(
            _COLUMN_NAME,
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(_TABLE_NAME, _COLUMN_NAME)
