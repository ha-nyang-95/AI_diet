"""0004_consents_automated_decision — Story 1.4.

PIPA 2026.03.15 자동화 의사결정 동의 컬럼 3개를 ``consents`` 테이블에 ADD:
- automated_decision_consent_at  (timestamptz, NULL)
- automated_decision_revoked_at  (timestamptz, NULL)
- automated_decision_version     (text, NULL)

모든 컬럼 nullable — Story 1.3 INSERT/UPDATE statement 회귀 0건. user_id 기준
단일 row lookup만 발생하므로 추가 인덱스 불필요(``uq_consents_user_id`` 자동 활용).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_consents_automated_decision"
down_revision: str | None = "0003_consents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "consents",
        sa.Column("automated_decision_consent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "consents",
        sa.Column("automated_decision_revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "consents",
        sa.Column("automated_decision_version", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("consents", "automated_decision_version")
    op.drop_column("consents", "automated_decision_revoked_at")
    op.drop_column("consents", "automated_decision_consent_at")
