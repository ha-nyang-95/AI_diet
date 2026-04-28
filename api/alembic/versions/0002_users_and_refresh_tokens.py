"""0002_users_and_refresh_tokens — Story 1.2.

신규:
- users: Google OAuth 기반 사용자 + role(user|admin)
- refresh_tokens: opaque refresh token rotation chain (sha256 hash 저장)

`gen_random_uuid()`은 Postgres 17 core 내장 — pgcrypto extension 의존성 없음.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_users_and_refresh_tokens"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("google_sub", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("picture_url", sa.String(), nullable=True),
        sa.Column(
            "role",
            sa.String(),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
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
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("google_sub", name="uq_users_google_sub"),
        sa.CheckConstraint("role IN ('user','admin')", name="ck_users_role"),
    )
    # admin 사용자만 인덱싱 — partial index로 lookup 비용 최소화 (Story 7.1+에서 활용).
    op.create_index(
        "idx_users_role_admin",
        "users",
        ["role"],
        postgresql_where=sa.text("role = 'admin'"),
    )

    op.create_table(
        "refresh_tokens",
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
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replaced_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "refresh_tokens.id",
                ondelete="SET NULL",
                name="fk_refresh_tokens_replaced_by",
            ),
            nullable=True,
        ),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("idx_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("idx_refresh_tokens_family_id", "refresh_tokens", ["family_id"])


def downgrade() -> None:
    op.drop_index("idx_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("idx_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("idx_users_role_admin", table_name="users")
    op.drop_table("users")
