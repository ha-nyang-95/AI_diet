"""0012_create_meal_analyses — Story 3.7 (모바일 SSE 분석 + 영속화).

D5 결정(IN) 정합 — 식단 *관리* 앱 본연 UX. SSE ``event: done`` 시점 UPSERT 입력 +
``GET /v1/meals`` JOIN으로 사용자 재로그인 시 한 주 식습관 한눈에 보이도록.

신규 테이블 ``meal_analyses`` — 14 컬럼 + 1 UNIQUE + 1 인덱스 + 5 CHECK:
- ``id``                   ``uuid``         PRIMARY KEY (gen_random_uuid)
- ``meal_id``              ``uuid``         NOT NULL FK meals.id ON DELETE CASCADE — 1:1 (UNIQUE)
- ``user_id``              ``uuid``         NOT NULL FK users.id ON DELETE CASCADE
- ``fit_score``            ``int``          NOT NULL CHECK 0-100
- ``fit_score_label``      ``text``         NOT NULL CHECK IN(5-band)
- ``fit_reason``           ``text``         NOT NULL CHECK IN(3-band)
- ``carbohydrate_g``       ``numeric``      NOT NULL
- ``protein_g``            ``numeric``      NOT NULL
- ``fat_g``                ``numeric``      NOT NULL
- ``energy_kcal``          ``int``          NOT NULL
- ``feedback_text``        ``text``         NOT NULL
- ``feedback_summary``     ``text``         NOT NULL CHECK length<=120
- ``citations``            ``jsonb``        NOT NULL DEFAULT '[]'::jsonb
- ``used_llm``             ``text``         NOT NULL CHECK IN(3-way)
- ``created_at`` / ``updated_at``           ``timestamptz`` NOT NULL DEFAULT now()

UNIQUE — ``uq_meal_analyses_meal_id`` (1 meal = 1 analysis).
인덱스 — ``idx_meal_analyses_user_id_created_at`` ON ``(user_id, created_at DESC)``
(Story 4.3 주간 리포트 forward-compat).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_create_meal_analyses"
down_revision: str | None = "0011_knowledge_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meal_analyses",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "meal_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fit_score", sa.Integer(), nullable=False),
        sa.Column("fit_score_label", sa.Text(), nullable=False),
        sa.Column("fit_reason", sa.Text(), nullable=False),
        sa.Column("carbohydrate_g", sa.Numeric(), nullable=False),
        sa.Column("protein_g", sa.Numeric(), nullable=False),
        sa.Column("fat_g", sa.Numeric(), nullable=False),
        sa.Column("energy_kcal", sa.Integer(), nullable=False),
        sa.Column("feedback_text", sa.Text(), nullable=False),
        sa.Column("feedback_summary", sa.Text(), nullable=False),
        sa.Column(
            "citations",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("used_llm", sa.Text(), nullable=False),
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
        sa.UniqueConstraint("meal_id", name="uq_meal_analyses_meal_id"),
        sa.CheckConstraint(
            "fit_score >= 0 AND fit_score <= 100", name="ck_meal_analyses_fit_score"
        ),
        sa.CheckConstraint(
            "fit_score_label IN ('allergen_violation','low','moderate','good','excellent')",
            name="ck_meal_analyses_fit_score_label",
        ),
        sa.CheckConstraint(
            "fit_reason IN ('ok','allergen_violation','incomplete_data')",
            name="ck_meal_analyses_fit_reason",
        ),
        sa.CheckConstraint(
            "used_llm IN ('gpt-4o-mini','claude','stub')",
            name="ck_meal_analyses_used_llm",
        ),
        sa.CheckConstraint(
            "length(feedback_summary) <= 120",
            name="ck_meal_analyses_feedback_summary_len",
        ),
    )
    # Story 4.3 forward-compat — user별 최근 분석 N건 정렬.
    op.create_index(
        "idx_meal_analyses_user_id_created_at",
        "meal_analyses",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_meal_analyses_user_id_created_at", table_name="meal_analyses")
    op.drop_table("meal_analyses")
