"""0008_meals_parsed_items — Story 2.3 (OCR Vision 추출 + 사용자 확인 카드).

``meals`` 테이블에 ``parsed_items`` JSONB NULL 1 컬럼 추가 — OCR Vision 추출 결과
영속화(`[{"name":"짜장면","quantity":"1인분","confidence":0.92}, ...]` 형식).

NOT NULL 부여 X — 텍스트-only / 사진+텍스트(parse 미호출) 식단 호환 (Story 2.1/2.2
baseline 정합). ``raw_text`` NOT NULL invariant 유지 — 사용자 확인 카드 통과 후 meal
생성 시 frontend가 parsed_items를 한국어 한 줄 텍스트로 변환해 raw_text 동시 송신
(예: "짜장면 1인분, 군만두 4개"). DF2(Story 2.2 ``(사진 입력)`` placeholder collision)는
*raw_text overwrite 흐름 강제*로 자연 해소(behavioral resolution).

추가 인덱스 X — ``parsed_items`` 단독 조회·필터 패턴 부재(Epic 3 LangGraph state 입력으로
``meal_id`` lookup 시점에만 fetch). jsonb path 인덱스(GIN)는 Story 8 perf hardening.

CHECK 제약 X — ``parsed_items`` 형식 검증은 백엔드 라우터(MealCreateRequest/
MealUpdateRequest Pydantic) + Vision 어댑터 응답 Pydantic 모델로 충분(double-gate DB
CHECK는 Story 8 hardening / jsonb 구조 변경 마찰).
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_meals_parsed_items"
down_revision: str | None = "0007_meals_image_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "meals",
        sa.Column(
            "parsed_items",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # CR P8 fix(2026-04-30) — populated 테이블에서 silent data loss 차단. parsed_items
    # 가 채워진 row가 1건이라도 있고 ALEMBIC_ALLOW_DESTRUCTIVE_DOWNGRADE=1이 명시 안 된
    # 경우 abort. 실수 rollback 방어 + 명시적 force flag 요구.
    # Gemini PR #14 review(2026-04-30): env var 체크 누락 buglet 수정 — 에러 메시지에서
    # 안내한 force flag가 실제 코드 분기에 반영되도록 align.
    bind = op.get_bind()
    populated = bind.execute(
        sa.text("SELECT count(*) FROM meals WHERE parsed_items IS NOT NULL")
    ).scalar()
    if populated and int(populated) > 0 and os.getenv("ALEMBIC_ALLOW_DESTRUCTIVE_DOWNGRADE") != "1":
        raise RuntimeError(
            f"refusing downgrade: meals.parsed_items contains {populated} populated row(s). "
            "Manually NULL the column (or set ALEMBIC_ALLOW_DESTRUCTIVE_DOWNGRADE=1) "
            "to confirm data loss is intended."
        )
    op.drop_column("meals", "parsed_items")
