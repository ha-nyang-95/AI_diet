"""0011_knowledge_chunks — Story 3.2 (가이드라인 RAG 시드 + chunking 모듈).

Epic 3 데이터 베이스라인 — 한국 1차 출처 가이드라인(KDRIs/KSSO/KDA/MFDS/KDCA)
50-100 chunks 시드 인프라.

신규 테이블 ``knowledge_chunks`` — 11 컬럼:
- ``id``                          ``uuid``        PRIMARY KEY (gen_random_uuid)
- ``source``                      ``text``        NOT NULL — 5 enum-style
  (MFDS/MOHW/KSSO/KDA/KDCA — application-level Pydantic 검증)
- ``source_id``                   ``text``        NOT NULL — 문서 식별자
  (예: ``KDRIS-2020-AMDR``, ``MFDS-ALLERGEN-22``)
- ``chunk_index``                 ``integer``     NOT NULL — 0-based 순번 (멱등 키)
- ``chunk_text``                  ``text``        NOT NULL — chunk 본문 (단일 인용 단위)
- ``embedding``                   ``vector(1536)``NULL — text-embedding-3-small (D4)
- ``authority_grade``             ``text``        NOT NULL — A/B/C (DB CHECK X)
- ``topic``                       ``text``        NOT NULL — 4 enum
  (``macronutrient`` / ``allergen`` / ``disease_specific`` / ``general``)
- ``applicable_health_goals``     ``text[]``      NOT NULL DEFAULT ``'{}'::text[]``
- ``published_year``              ``integer``     NULL
- ``doc_title``                   ``text``        NOT NULL
- ``created_at`` / ``updated_at`` ``timestamptz`` NOT NULL DEFAULT ``now()``

UNIQUE 제약 — ``uq_knowledge_chunks_source_source_id_chunk_index`` ON
``(source, source_id, chunk_index)`` — 시드 멱등 ``ON CONFLICT DO UPDATE`` 입력 (D5).

HNSW 인덱스 — ``idx_knowledge_chunks_embedding`` ``USING hnsw (embedding
vector_cosine_ops) WITH (m=16, ef_construction=64)`` (Story 3.1 D3 정합).

GIN 인덱스 — ``idx_knowledge_chunks_applicable_health_goals`` ``USING gin
(applicable_health_goals)`` — Story 3.6 retrieve guideline 노드 filtered top-K
(``applicable_health_goals @> ARRAY[:health_goal]`` + 빈 배열 OR 분기).

Composite btree 인덱스 — ``idx_knowledge_chunks_source`` ON
``(source, authority_grade)`` — 인용 출처 카드별 검색 가속 + 기관별 가중치 토대.

CHECK 제약 X — ``source``/``authority_grade``/``topic`` enum 검증은 application-level
Pydantic + ``data/guidelines/*.md`` frontmatter ``_FrontmatterSchema`` 책임 (Story 3.1
D4 정합 — DB CHECK 마찰 회피).

``vector`` extension — ``docker/postgres-init/01-pgvector.sql`` Story 1.1 baseline (no-op).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_knowledge_chunks"
down_revision: str | None = "0010_food_nutrition_and_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # knowledge_chunks 테이블 — embedding 컬럼은 별 ALTER로 raw 추가(pgvector type 회피).
    op.create_table(
        "knowledge_chunks",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("authority_grade", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column(
            "applicable_health_goals",
            sa.dialects.postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("published_year", sa.Integer(), nullable=True),
        sa.Column("doc_title", sa.Text(), nullable=False),
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
        sa.UniqueConstraint(
            "source",
            "source_id",
            "chunk_index",
            name="uq_knowledge_chunks_source_source_id_chunk_index",
        ),
    )
    # embedding vector(1536) 컬럼 — pgvector type은 SQLAlchemy core ALTER 직접 미지원 →
    # raw SQL ALTER (Story 3.1 0010 패턴 정합).
    op.execute(sa.text("ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(1536) NULL"))

    # HNSW 인덱스 — vector_cosine_ops + m=16 + ef_construction=64 (D3).
    op.create_index(
        "idx_knowledge_chunks_embedding",
        "knowledge_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # GIN 인덱스 — applicable_health_goals filtered top-K (architecture line 293).
    op.create_index(
        "idx_knowledge_chunks_applicable_health_goals",
        "knowledge_chunks",
        ["applicable_health_goals"],
        postgresql_using="gin",
    )

    # Composite btree — (source, authority_grade) 패턴 가속.
    op.create_index(
        "idx_knowledge_chunks_source",
        "knowledge_chunks",
        ["source", "authority_grade"],
    )


def downgrade() -> None:
    # 역순 — 인덱스 3건 drop → 테이블 drop.
    op.drop_index("idx_knowledge_chunks_source", table_name="knowledge_chunks")
    op.drop_index("idx_knowledge_chunks_applicable_health_goals", table_name="knowledge_chunks")
    op.drop_index("idx_knowledge_chunks_embedding", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
