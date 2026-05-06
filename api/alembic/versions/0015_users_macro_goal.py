"""0015_users_macro_goal — Story 4.4 (사용자 매크로 목표 JSONB 컬럼 + CHECK 제약).

``users.macro_goal`` JSONB nullable 컬럼 1건 + DB CHECK 제약 1건
(``ck_users_macro_goal_shape``) — Pydantic 1차 가드 + DB 2차 가드(double gate,
Story 1.5 패턴 정합).

CHECK 제약 SQL은 ``app/db/models/user.py`` ``__table_args__`` 텍스트와 *동일 SOT*
— 본 모듈이 SOT, ORM이 import. 변경 시 새 alembic revision으로 drop+recreate
(Story 1.5 R8 SOP 정합).

5 필드 shape 검증:
- ``daily_calorie_target_kcal``: number, 800-6000.
- ``protein_target_g_per_meal``: number, 5-200.
- ``macro_ratio_carb_pct`` / ``macro_ratio_protein_pct`` / ``macro_ratio_fat_pct``: number, 0-100.

ratio all-or-none + sum=100은 *Pydantic 1차 가드*만 — DB CHECK은 *shape*만 가드(SQL
JSONB 다중 키 ratio 합산 expression이 복잡 + 본 가드는 partial set/sum 위반에 대한
방어선이 아닌 *taint payload* 차단이 목적).

downgrade는 CHECK → 컬럼 drop 역순.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.domain.macro_goal import MACRO_GOAL_CHECK_SQL

revision: str = "0015_users_macro_goal"
down_revision: str | None = "0014_create_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_NAME = "users"
_COLUMN_NAME = "macro_goal"
_CHECK_NAME = "ck_users_macro_goal_shape"


def upgrade() -> None:
    op.add_column(
        _TABLE_NAME,
        sa.Column(
            _COLUMN_NAME,
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        _CHECK_NAME,
        _TABLE_NAME,
        MACRO_GOAL_CHECK_SQL,
    )


def downgrade() -> None:
    op.drop_constraint(_CHECK_NAME, _TABLE_NAME, type_="check")
    op.drop_column(_TABLE_NAME, _COLUMN_NAME)
