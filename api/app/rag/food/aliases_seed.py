"""Story 3.1 — ``food_aliases`` 시드 비즈니스 로직 (AC #5).

50+ 핵심 변형(``FOOD_ALIASES`` const dict) → DB INSERT 멱등 + count ≥ 50 게이트.
재실행 안전 — ``ON CONFLICT (alias) DO UPDATE SET canonical_name = EXCLUDED.canonical_name``.

본 모듈은 *시드 시점*만 사용 — 외주 클라이언트 alias 추가는 ``data/README.md``의
3 경로(코드 PR / psql 직접 INSERT / admin UI Story 7.x) 책임. 본 모듈은 *최초 시드
+ 재시드 멱등*만.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import FoodSeedAdapterError
from app.rag.food.aliases_data import ALIASES_MIN_COUNT, FOOD_ALIASES

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AliasesSeedResult:
    """``seed_food_aliases`` 결과 — 통계만 (raw 데이터 노출 X — NFR-S5)."""

    inserted: int
    updated: int
    total: int


_INSERT_ALIAS_SQL: Final[str] = """
INSERT INTO food_aliases (alias, canonical_name)
VALUES (:alias, :canonical_name)
ON CONFLICT (alias) DO UPDATE SET
    canonical_name = EXCLUDED.canonical_name,
    updated_at = now()
RETURNING (xmax = 0) AS inserted
"""
"""``xmax = 0``는 INSERT 분기, 아니면 UPDATE 분기 — Postgres MVCC 표준 패턴.

``RETURNING`` 절로 분기 통계 한 round-trip에 수집(추가 SELECT 비용 0).
"""


async def seed_food_aliases(session: AsyncSession) -> AliasesSeedResult:
    """``FOOD_ALIASES`` const → DB INSERT 멱등 + count 게이트 검증.

    단일 transaction(50+건은 메모리 + 트랜잭션 비용 무시 가능). 부분 실패 시 전체
    롤백 — 호출자(시드 스크립트)가 commit/rollback 책임.

    오류:
    - count < 50 — ``FoodSeedAdapterError``(AC #5 게이트 — 사전이 줄어든 것은 회귀
      신호).
    """
    inserted = 0
    updated = 0
    for alias, canonical_name in FOOD_ALIASES.items():
        result = await session.execute(
            text(_INSERT_ALIAS_SQL),
            {"alias": alias, "canonical_name": canonical_name},
        )
        row = result.first()
        if row is None:
            continue
        if row.inserted:
            inserted += 1
        else:
            updated += 1

    # count 게이트 — DB row 기준(같은 alias 중복은 UNIQUE 제약으로 차단되므로 dict
    # 단일 출처 길이 게이트가 1차, DB count는 2차 방어).
    count_result = await session.execute(text("SELECT count(*) AS n FROM food_aliases"))
    count_row = count_result.first()
    total = int(count_row.n) if count_row else 0
    if total < ALIASES_MIN_COUNT:
        raise FoodSeedAdapterError(
            f"food_aliases seed insufficient: count={total} < {ALIASES_MIN_COUNT}"
        )

    logger.info(
        "food_aliases.seed",
        inserted=inserted,
        updated=updated,
        total=total,
    )
    return AliasesSeedResult(inserted=inserted, updated=updated, total=total)
