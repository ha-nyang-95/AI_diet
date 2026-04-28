"""0003_consents — Story 1.3.

신규:
- consents: 약관·개인정보·민감정보 동의 timestamp + version (1 user 1 row).

`gen_random_uuid()`은 Postgres 17 core 내장. Story 1.4가 자동화 의사결정 동의 컬럼을
0004 마이그레이션으로 추가(scope 분리).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_consents"
down_revision: str | None = "0002_users_and_refresh_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("disclaimer_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("privacy_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sensitive_personal_info_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disclaimer_version", sa.String(), nullable=True),
        sa.Column("terms_version", sa.String(), nullable=True),
        sa.Column("privacy_version", sa.String(), nullable=True),
        sa.Column("sensitive_personal_info_version", sa.String(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", name="uq_consents_user_id"),
    )


def downgrade() -> None:
    op.drop_table("consents")
