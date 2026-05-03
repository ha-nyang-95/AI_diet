"""Story 3.4 — 음식명 정규화 사전 1차 lookup (FR19, AC3).

`food_aliases` 테이블의 ``alias`` exact 매칭으로 한국어 변형(자장면/짜장면, 김치 찌개/
김치찌개, 떡뽁이/떡볶이 등)을 표준 음식명으로 정규화. ``retrieve_nutrition`` 노드가
1차 lookup 후 hit 시 ``food_nutrition.name`` exact 매칭으로 직진, miss 시 임베딩
fallback 진입.

design:
- 1 round-trip — ORM ``select(FoodAlias.canonical_name).where(FoodAlias.alias == alias)
  .limit(1)``. ``UNIQUE(alias)`` 제약으로 결과는 0/1건.
- 빈 입력 → ``None`` (DB 호출 X). 호출자가 alias 없는 raw item으로 다음 단계 진행.
- *exact 한국어 매칭만* — 소문자 정규화/공백 trim 책임 분리. ``"  자장면  "``는 미스
  반환 (호출자 책임 — 사전적 정확 매칭 강제).
- NFR-S5 마스킹 — alias raw 노출 X. hit/miss bool + length만.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.food_alias import FoodAlias

logger = structlog.get_logger(__name__)


async def lookup_canonical(session: AsyncSession, alias: str) -> str | None:
    """``alias`` → ``canonical_name`` exact 매칭 (1 round-trip).

    - 빈 입력(``alias.strip() == ""``) — 즉시 ``None`` (DB 호출 X / cost 0).
    - 매치 — ``canonical_name`` 반환.
    - 미스 — ``None``.

    NFR-S5 — alias raw 출력 X. hit bool + alias_length + canonical_length만.
    """
    if not alias or not alias.strip() or alias != alias.strip():
        # 공백 trim 차이 또는 빈 입력 → DB 호출 X (사전적 exact 매칭 강제 / cost 0).
        # ``"  자장면  "``는 호출자가 trim 책임 — 본 함수는 *사전적 exact*만.
        if not alias.strip():
            logger.info("food.normalize.empty_input", hit=False)
            return None
        # 공백 포함 raw 입력 — exact 매칭 미스 즉시 (사전 entry는 trimmed only).
        logger.info("food.normalize.whitespace_pad", hit=False, alias_length=len(alias))
        return None

    stmt = select(FoodAlias.canonical_name).where(FoodAlias.alias == alias).limit(1)
    result = await session.execute(stmt)
    canonical: str | None = result.scalar_one_or_none()

    logger.info(
        "food.normalize.lookup",
        hit=canonical is not None,
        alias_length=len(alias),
        canonical_length=len(canonical) if canonical else 0,
    )
    return canonical


__all__ = ["lookup_canonical"]
