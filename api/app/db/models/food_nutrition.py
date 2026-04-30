"""FoodNutrition ORM model — Story 3.1 (음식 영양 RAG 시드 + pgvector HNSW).

Epic 3 데이터 베이스라인 — 식약처 식품영양성분 DB OpenAPI(공공데이터포털 15127578)
1차 + 통합 자료집 ZIP 백업 2단 fallback으로 한식 우선 1,500-3,000건 시드. 응답 키는
식약처 표준(``energy_kcal``/``carbohydrate_g``/``protein_g``/``fat_g``/
``saturated_fat_g``/``sugar_g``/``fiber_g``/``sodium_mg``/``cholesterol_mg``/
``serving_size_g``/``serving_unit``/``source``/``source_id``/``source_updated``)
그대로 ``nutrition`` JSONB에 저장 — 외주 인수 클라이언트 자사 SKU 변환 코스트 0.

``embedding`` ``vector(1536)`` (text-embedding-3-small) — Story 3.3
``retrieve_nutrition`` 노드의 1차 검색 인덱스. HNSW(``vector_cosine_ops``,
m=16, ef_construction=64) 인덱스는 마이그레이션 0010에서 raw
``op.create_index(postgresql_using='hnsw', ...)``로 생성(SQLAlchemy autogen 미지원).

D4 — ``embedding NULL`` 허용 — 부분 실패 graceful (어댑터 transient 시 일부 row만
임베딩 없이 INSERT 성공) + 검색 시 ``WHERE embedding IS NOT NULL`` 자동 제외.

D5 — 시드 멱등 ``ON CONFLICT (source, source_id) DO UPDATE`` — ``UNIQUE(source,
source_id)`` 제약으로 재실행 안전 + UPDATE 분기.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.db.base import Base


class FoodNutrition(Base):
    __tablename__ = "food_nutrition"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # 식약처 품목분류 — 임베딩 텍스트 분리용(D8). NULL 허용 — 카테고리 미분류 row 호환.
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 식약처 표준 키 jsonb — 키 추가는 무중단(jsonb 특성). 키 omission 허용 (결측치는
    # 키 누락으로 보존 — DB NULL 채움 X).
    nutrition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # text-embedding-3-small (1536 dim). NULL 허용 — D4(부분 실패 graceful).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    # 시드 출처 식별 — `MFDS_FCDB`(OpenAPI 1차) / `MFDS_ZIP`(ZIP fallback) / `CUSTOM`.
    source: Mapped[str] = mapped_column(Text, nullable=False)
    # 식약처 식품코드(예: `K-115001`) 또는 ZIP 케이스 `MFDS-ZIP-{seq}`.
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
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
        # D5 — 시드 멱등 ON CONFLICT 입력. naming: Story 1.2 W9 정합 `uq_*`.
        UniqueConstraint("source", "source_id", name="uq_food_nutrition_source_source_id"),
        # HNSW 인덱스는 Alembic 0010에서 raw op.create_index로 생성 — SQLAlchemy
        # `Index` 객체는 `vector_cosine_ops` opclass + HNSW `with` 파라미터 미지원.
        # ORM은 `__table_args__` SOT만 유지(인덱스 책임은 마이그레이션에 박힘).
    )
