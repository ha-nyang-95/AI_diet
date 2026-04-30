"""FoodAlias ORM model — Story 3.1 (한국식 음식명 변형 → 표준 음식명 정규화 사전).

Epic 3 데이터 베이스라인 — 50+ 핵심 변형(짜장면/자장면, 김치찌개/김치 찌개,
떡볶이/떡뽁이 등). Story 3.4 ``normalize.py`` 1차 lookup 입력. 본 스토리는
*시드 시점* 50+건만 — 외주 클라이언트 alias 추가 SOP는 ``data/README.md``의
3 경로(코드 PR / psql 직접 INSERT / admin UI Story 7.x) 책임.

UNIQUE 제약은 ``alias`` 단일 컬럼 — 같은 alias 중복 시드 차단(epic AC line 594
*"unique 제약"* 명시 정합). 시드 멱등은 ``ON CONFLICT (alias) DO UPDATE`` 분기.
``canonical_name`` ↔ ``food_nutrition.name`` 매칭은 *Story 3.4 책임*(forward join,
시드 시점 검증 X — orphan은 임베딩 fallback 분기에서 자연 처리).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.db.base import Base


class FoodAlias(Base):
    __tablename__ = "food_aliases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    __table_args__ = (UniqueConstraint("alias", name="uq_food_aliases_alias"),)
