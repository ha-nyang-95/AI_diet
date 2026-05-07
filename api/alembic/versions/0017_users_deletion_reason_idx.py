"""0017_users_deletion_reason_idx — Story 5.2 (회원 탈퇴 사유 + 30일 grace partial index).

Revision name이 alembic_version.version_num varchar(32) 제한에 맞춰 ``_idx``로 축약 —
실제 생성되는 partial index 이름은 ``idx_users_deleted_at_pending_purge`` 그대로.

본 revision은 *2건 변경*:

1. ``users.deletion_reason`` Text nullable 컬럼 1건 추가 — 사용자가 탈퇴 시 선택적으로
   기재한 자유 텍스트 사유. 미송신 시 NULL. enum 미사용(MVP — 향후 카테고리 분류
   필요 시 polish 스토리에서 enum 도입 검토 — Story 8.x forward).
2. ``idx_users_deleted_at_pending_purge`` partial index 1건 추가 — predicate
   ``WHERE deleted_at IS NOT NULL``. 30일 grace 후 물리 파기 cron worker
   (``app/workers/soft_delete_purge.py``)가 ``SELECT id FROM users WHERE
   deleted_at IS NOT NULL AND deleted_at < :cutoff`` 쿼리를 일별 1회 실행 — 본
   index가 hit해 *활성 사용자 hot path INSERT/UPDATE 비용 0*(predicate가 NULL인
   row는 색인 미진입).

회귀 0건: 기존 row는 ``deletion_reason=NULL`` default. partial index는 활성
사용자(``deleted_at IS NULL``) 색인 안 함 — 가장 비용 큰 hot path 가드.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_users_deletion_reason_idx"
down_revision: str | None = "0016_users_profile_updated_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_NAME = "users"
_COLUMN_NAME = "deletion_reason"
_INDEX_NAME = "idx_users_deleted_at_pending_purge"


def upgrade() -> None:
    op.add_column(
        _TABLE_NAME,
        sa.Column(
            _COLUMN_NAME,
            sa.Text(),
            nullable=True,
        ),
    )
    op.create_index(
        _INDEX_NAME,
        _TABLE_NAME,
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME)
    op.drop_column(_TABLE_NAME, _COLUMN_NAME)
