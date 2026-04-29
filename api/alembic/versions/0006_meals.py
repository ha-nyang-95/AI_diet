"""0006_meals — Story 2.1 (식단 텍스트 입력 + CRUD baseline).

Epic 2 단일 출처 ``meals`` 테이블 신규 — 텍스트 전용 7컬럼 + 1 partial index.

7 컬럼:
- ``id``          ``uuid``        PRIMARY KEY DEFAULT ``gen_random_uuid()``
- ``user_id``     ``uuid``        NOT NULL REFERENCES ``users(id)`` ON DELETE CASCADE
- ``raw_text``    ``text``        NOT NULL
- ``ate_at``      ``timestamptz`` NOT NULL DEFAULT ``now()``
- ``created_at``  ``timestamptz`` NOT NULL DEFAULT ``now()``
- ``updated_at``  ``timestamptz`` NOT NULL DEFAULT ``now()`` (ORM ``onupdate=now()``)
- ``deleted_at``  ``timestamptz`` NULL — soft delete 흔적

1 partial index — Story 2.4 daily list 쿼리(``WHERE user_id=? AND deleted_at IS
NULL ORDER BY ate_at DESC``) 입력:
- ``idx_meals_user_id_ate_at_active`` ON ``meals(user_id, ate_at DESC)``
  WHERE ``deleted_at IS NULL``

CHECK 제약 X — ``raw_text`` 길이/공백 검증은 Pydantic ``Field(min_length=1,
max_length=2000)`` 1차 게이트로 충분 (double-gate DB CHECK는 Story 8 hardening).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_meals"
down_revision: str | None = "0005_users_health_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meals",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column(
            "ate_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Story 2.4 daily list 쿼리 입력 — active row만 색인 (partial index).
    op.create_index(
        "idx_meals_user_id_ate_at_active",
        "meals",
        ["user_id", sa.text("ate_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_meals_user_id_ate_at_active", table_name="meals")
    op.drop_table("meals")
