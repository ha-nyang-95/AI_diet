"""KnowledgeChunk ORM model — Story 3.2 (가이드라인 RAG 시드 + chunking 모듈).

Epic 3 데이터 베이스라인 — KDRIs/KSSO/KDA/MFDS/KDCA 5개 한국 1차 출처 가이드라인을
50-100 chunks로 시드해 Story 3.6 ``generate_feedback`` 노드의 *(출처: 보건복지부 2020
KDRIs)* 패턴 인용 인프라를 박는다. 메타데이터 7컬럼은 정규 컬럼(JSONB 미사용) — 필터
top-K + 인용 패턴 직접 주입 + 인덱싱 자유.

D2 — ``text-embedding-3-small`` 1536 dim 고정 (Story 3.1 정합).
D3 — HNSW(``vector_cosine_ops``, m=16, ef_construction=64) 인덱스는 0011 마이그레이션
raw ``op.create_index``에서 생성 (SQLAlchemy autogen 미지원 — Story 3.1 0010 패턴).
D4 — ``embedding NULL`` 허용 — 부분 실패 graceful + 검색 시 ``WHERE embedding IS NOT
NULL`` 자동 제외.
D5 — UNIQUE(source, source_id, chunk_index) — 시드 멱등 ``ON CONFLICT DO UPDATE`` 입력.

``applicable_health_goals`` ``text[]`` — Story 3.6 retrieve guideline 노드의 사용자
목표별 filtered top-K 검색 키. 빈 배열 ``{}``은 *전 사용자 적용*(식약처 22종 알레르기
등 — 모든 사용자에게 노출). GIN 인덱스는 0011에서 raw ``op.create_index(...,
postgresql_using='gin')``로 생성.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime, Integer

from app.db.base import Base


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # `source` enum-style — DB CHECK 제약 X (application-level Pydantic _FrontmatterSchema 검증).
    # 5 enum 값: MFDS / MOHW / KSSO / KDA / KDCA.
    source: Mapped[str] = mapped_column(Text, nullable=False)
    # 문서 식별자 — `KDRIS-2020-AMDR`, `KSSO-2024-CH3`, `KDA-MACRO-2017`, `MFDS-ALLERGEN-22` 등.
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    # 문서 내 chunk 순번 — 0부터 시작, 멱등 키 (D5).
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # chunk 본문 — 단일 인용 단위.
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    # text-embedding-3-small (1536 dim, D2). NULL 허용 — D4 (부분 실패 + dev graceful).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    # 신뢰 등급 — `A`/`B`/`C` (research 1.2). DB CHECK X (application-level).
    authority_grade: Mapped[str] = mapped_column(Text, nullable=False)
    # 주제 — `macronutrient`/`allergen`/`disease_specific`/`general` (research 2.5).
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    # 사용자 목표별 filtered top-K 키 (Story 3.6 retrieve guideline 노드).
    # 빈 배열 = *전 사용자 적용*. `weight_loss`/`muscle_gain`/`maintenance`/`diabetes_management`.
    applicable_health_goals: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    # 발행연도 — 인용 패턴 *(출처: 기관명, 문서명, 연도)* 직접 주입용. 미상 시 NULL.
    published_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 문서 표시명 — 예: *"2020 한국인 영양소 섭취기준"*. 인용 패턴 직접 주입.
    doc_title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    __table_args__ = (
        # D5 — 시드 멱등 ON CONFLICT 입력. naming: Story 3.1 0010 `uq_*` 정합.
        UniqueConstraint(
            "source",
            "source_id",
            "chunk_index",
            name="uq_knowledge_chunks_source_source_id_chunk_index",
        ),
        # HNSW + GIN + composite btree 인덱스는 Alembic 0011에서 raw op.create_index로 생성 —
        # SQLAlchemy `Index` 객체는 `vector_cosine_ops` opclass / HNSW `with` 파라미터 / GIN
        # array opclass 미지원. ORM은 `__table_args__` SOT만 (인덱스 책임은 마이그레이션에 박힘).
    )
