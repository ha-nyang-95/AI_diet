"""식약처 *식품 등의 표시기준 별표* 22종 알레르기 유발물질 SOT — Story 1.5.

SOT 단일 위치: 본 모듈의 ``KOREAN_22_ALLERGENS`` tuple.

변경 시:
1. 본 tuple 갱신 → 정의 순서 보존(식약처 표시기준 별표 PDF 순).
2. 새 alembic revision으로 ``users.allergies`` CHECK 제약 drop+recreate
   (``app/db/models/user.py`` 모델 선언과 동일 SQL 사용).
3. ``scripts/verify_allergy_22.py`` 분기 1회 cron(R8 SOP, Story 8) 실행 결과 동기.

응용:
- ``app/api/v1/users.py:HealthProfileSubmitRequest`` Pydantic validator가
  ``normalize_allergens()``로 22종 부분집합 검증 + dedup.
- ``users.allergies`` Postgres ``text[]`` 컬럼에 DB CHECK 제약(``<@`` 부분집합)이
  본 tuple SQL 인라인으로 박힘(0005 마이그레이션).
- Story 3.5 ``domain/fit_score.py``가 ``users.allergies`` ∩ ``parsed_items`` 단락
  매칭 — 본 SOT의 22종 무결성에 의존.
"""

from __future__ import annotations

from typing import Final

# 식약처 별표 22종 — 정의 순서는 표시기준 PDF 순(우유 → 메밀 → 땅콩 → … → 기타).
# 본 순서를 *바꾸지 말 것* — 마이그레이션 SQL 인라인 + Story 3.5 fit_score 단위
# 테스트가 본 순서에 의존.
KOREAN_22_ALLERGENS: Final[tuple[str, ...]] = (
    "우유",
    "메밀",
    "땅콩",
    "대두",
    "밀",
    "고등어",
    "게",
    "새우",
    "돼지고기",
    "아황산류",
    "복숭아",
    "토마토",
    "호두",
    "닭고기",
    "난류(가금류)",
    "쇠고기",
    "오징어",
    "조개류(굴/전복/홍합 포함)",
    "잣",
    "아몬드",
    "잔류 우유 단백",
    "기타",
)

KOREAN_22_ALLERGENS_SET: Final[frozenset[str]] = frozenset(KOREAN_22_ALLERGENS)


def is_valid_allergen(value: str) -> bool:
    """단일 알레르기 라벨이 22종 도메인 내 인지 확인 — Pydantic validator/route 검증에서 사용."""
    return value in KOREAN_22_ALLERGENS_SET


def normalize_allergens(values: list[str]) -> list[str]:
    """22종 부분집합 검증 + dedup. invalid 항목 발견 시 ``ValueError`` 발생.

    반환 순서는 ``KOREAN_22_ALLERGENS`` 정의 순(결정성). dedup은 frozenset 거친 후
    정의 순 재정렬. 빈 입력 → 빈 리스트.
    """
    seen: set[str] = set()
    for v in values:
        if v not in KOREAN_22_ALLERGENS_SET:
            raise ValueError(f"unknown allergen: {v!r}; must be one of 22 식약처 standard.")
        seen.add(v)
    return [a for a in KOREAN_22_ALLERGENS if a in seen]
