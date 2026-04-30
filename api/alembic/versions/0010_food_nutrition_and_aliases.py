"""0010_food_nutrition_and_aliases — Story 3.1 (음식 영양 RAG 시드 + pgvector HNSW + 정규화 사전).

Epic 3 데이터 베이스라인 — 두 신규 테이블 + UNIQUE 제약 + HNSW 인덱스.

신규 테이블 ``food_nutrition`` — 12 컬럼:
- ``id``              ``uuid``        PRIMARY KEY DEFAULT ``gen_random_uuid()``
- ``name``            ``text``        NOT NULL  (한국어 표준 음식명, 예: ``"짜장면"``)
- ``category``        ``text``        NULL      (식약처 품목분류 — 임베딩 텍스트 분리용 D8)
- ``nutrition``       ``jsonb``       NOT NULL  (식약처 표준 키 그대로 — 키 추가 무중단)
- ``embedding``       ``vector(1536)`` NULL     (text-embedding-3-small — D4 부분 실패 graceful)
- ``source``          ``text``        NOT NULL  (`MFDS_FCDB`/`MFDS_ZIP`/`CUSTOM`)
- ``source_id``       ``text``        NOT NULL  (식약처 식품코드 — `K-115001` 등)
- ``created_at``      ``timestamptz`` NOT NULL DEFAULT ``now()``
- ``updated_at``      ``timestamptz`` NOT NULL DEFAULT ``now()`` (ORM ``onupdate=now()``)

UNIQUE 제약 — ``uq_food_nutrition_source_source_id`` ON ``(source, source_id)`` —
시드 멱등 ``ON CONFLICT (source, source_id) DO UPDATE`` 입력 (D5).

HNSW 인덱스 — ``idx_food_nutrition_embedding`` ON ``embedding``
``USING hnsw`` ``vector_cosine_ops`` ``WITH (m=16, ef_construction=64)`` — Story 3.3
``retrieve_nutrition`` 노드의 1차 검색 (D3). NULL embedding은 자동 제외(pgvector
0.8.2 표준 — partial-index 명시 X 시 NULL 미인덱싱).

신규 테이블 ``food_aliases`` — 5 컬럼:
- ``id``              ``uuid``        PRIMARY KEY DEFAULT ``gen_random_uuid()``
- ``alias``           ``text``        NOT NULL  (변형 음식명 — `"자장면"`)
- ``canonical_name``  ``text``        NOT NULL  (표준 음식명 — `"짜장면"`)
- ``created_at``      ``timestamptz`` NOT NULL DEFAULT ``now()``
- ``updated_at``      ``timestamptz`` NOT NULL DEFAULT ``now()`` (ORM ``onupdate=now()``)

UNIQUE 제약 — ``uq_food_aliases_alias`` ON ``alias`` — 같은 alias 중복 시드 차단
(epic AC line 594 정합) + 시드 멱등 ``ON CONFLICT (alias) DO UPDATE`` 입력.

CHECK 제약 X — ``nutrition`` jsonb 키 검증 / ``embedding`` 차원 검증은 application-level
Pydantic + 시드 함수 책임. DB CHECK는 마이그레이션 마찰 회피 (Story 8 hardening).

``vector`` extension — ``docker/postgres-init/01-pgvector.sql`` 자동 설치(Story 1.1
baseline) — 본 마이그레이션은 ``CREATE EXTENSION`` 호출 X (no-op 보장).

HNSW 인덱스는 SQLAlchemy autogen 미지원 — raw ``op.create_index(postgresql_using='hnsw',
postgresql_with={...}, postgresql_ops={...})``로 명시.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_food_nutrition_and_aliases"
down_revision: str | None = "0009_meals_idempotency_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # food_nutrition 테이블 — 12 컬럼 + UNIQUE.
    op.create_table(
        "food_nutrition",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("nutrition", sa.dialects.postgresql.JSONB(), nullable=False),
        # pgvector raw column — sa.dialects는 vector type 미보유. 본 컬럼은 SQL DDL
        # raw로 ALTER TABLE 패턴 또는 op.add_column으로 sa.Column("...", sa.types.UserDefinedType)
        # 사용. 가장 단순한 방식: sa.text() 기반 raw SQL ALTER.
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
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
        sa.UniqueConstraint("source", "source_id", name="uq_food_nutrition_source_source_id"),
    )
    # embedding vector(1536) 컬럼 — pgvector type은 SQLAlchemy core ALTER로 raw 추가.
    # `pgvector.sqlalchemy.Vector(1536)`을 op.add_column에 직접 사용하려면 import 필요 —
    # raw SQL이 더 단순 + autogen 회귀 차단.
    op.execute(sa.text("ALTER TABLE food_nutrition ADD COLUMN embedding vector(1536) NULL"))

    # HNSW 인덱스 — vector_cosine_ops + m=16 + ef_construction=64 (D3).
    op.create_index(
        "idx_food_nutrition_embedding",
        "food_nutrition",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # food_aliases 테이블 — 5 컬럼 + UNIQUE.
    op.create_table(
        "food_aliases",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
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
        sa.UniqueConstraint("alias", name="uq_food_aliases_alias"),
    )


def downgrade() -> None:
    # 역순 — food_aliases drop → food_nutrition HNSW 인덱스 → food_nutrition drop.
    op.drop_table("food_aliases")
    op.drop_index("idx_food_nutrition_embedding", table_name="food_nutrition")
    op.drop_table("food_nutrition")
