"""0023_meal_analyses_used_llm_openai_only — Story 8.5 (Anthropic 제거 + OpenAI 단독).

본 revision은 *2건 변경*:

1. ``meal_analyses.used_llm`` 기존 row 정리 — ``'claude'`` 값을 ``'gpt-4o-mini'``로 대체
   (Story 3.6 dual-LLM router에서 Anthropic fallback이 응답한 row를 OpenAI 기본 모델로
   라벨 갱신, 향후 admin/SSE 응답에서 *legacy 라벨 없음* 보장).
2. ``ck_meal_analyses_used_llm`` CHECK 제약 갱신 — 허용 set을
   ``('gpt-4o-mini', 'claude', 'stub')`` → ``('gpt-4o-mini', 'gpt-4o', 'stub')``로 swap.
   ``'gpt-4o'``는 Story 3.9 AC13 env override 승격 라벨 정합.

설계 결정:

- **데이터 마이그레이션 방향성**: ``'claude'`` → ``'gpt-4o-mini'`` (downgrade는 무손실 복원
  불가능 — Story 8.5 시점에 prod 데이터 없음 + dev DB에 한정된 영향이라 일방향 OK).
- **CHECK 제약 swap 순서**: DROP → UPDATE → ADD. UPDATE 전에 CHECK를 DROP해야 *기존 'claude'
  값이 새 CHECK에 부합하지 않아 ALTER 실패*하는 race 차단.
- **prod 데이터 위험**: Story 8.5는 epic-8 첫 진입 = prod 미배포. 본 마이그레이션은 dev DB +
  CI test DB만 영향. prod 첫 배포 시점에 빈 DB로 0001~0023 일괄 적용 → 'claude' row 미존재.
"""

from __future__ import annotations

from alembic import op

revision: str = "0023_used_llm_openai_only"
down_revision: str | None = "0022_create_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 기존 CHECK 제약 DROP — 신규 'gpt-4o' 값 ALTER 통과 + UPDATE 전 사전 정리.
    op.drop_constraint(
        "ck_meal_analyses_used_llm",
        "meal_analyses",
        type_="check",
    )

    # 2. legacy 'claude' row를 'gpt-4o-mini'로 정리 (dev DB cleanup, prod는 빈 상태).
    op.execute(
        "UPDATE meal_analyses SET used_llm = 'gpt-4o-mini' WHERE used_llm = 'claude'"
    )

    # 3. 새 CHECK 제약 ADD — Story 8.5 OpenAI 단독 라벨 set.
    op.create_check_constraint(
        "ck_meal_analyses_used_llm",
        "meal_analyses",
        "used_llm IN ('gpt-4o-mini','gpt-4o','stub')",
    )


def downgrade() -> None:
    # 1. 새 CHECK 제약 DROP — 'gpt-4o' row를 'gpt-4o-mini'로 ALTER 통과시키기 위해.
    op.drop_constraint(
        "ck_meal_analyses_used_llm",
        "meal_analyses",
        type_="check",
    )

    # 2. 'gpt-4o' row는 'gpt-4o-mini'로 강등 (downgrade는 lossy — Story 3.9 env override 승격
    #    내역은 보존 불가, prod 미가동 시점 안전 trade-off).
    op.execute(
        "UPDATE meal_analyses SET used_llm = 'gpt-4o-mini' WHERE used_llm = 'gpt-4o'"
    )

    # 3. 기존 CHECK 제약 복원 (legacy 'claude' 허용은 그대로 — 과거 row 복원 시 호환).
    op.create_check_constraint(
        "ck_meal_analyses_used_llm",
        "meal_analyses",
        "used_llm IN ('gpt-4o-mini','claude','stub')",
    )
