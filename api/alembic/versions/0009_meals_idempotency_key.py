"""0009_meals_idempotency_key — Story 2.5 (오프라인 텍스트 큐잉 + Idempotency-Key 처리).

W46 (Story 2.1 deferred — 앱 백그라운드/킬 mid-mutation 중복 POST) 흡수.

``meals`` 테이블에 ``idempotency_key`` TEXT NULL 1 컬럼 추가 + ``(user_id,
idempotency_key) WHERE idempotency_key IS NOT NULL`` partial UNIQUE index 추가.

NULL 미포함 partial UNIQUE — 헤더 미송신 입력은 자유 INSERT(회귀 0건). 같은
``user_id`` + 같은 ``idempotency_key`` 재송신 시 라우터에서 race-free SELECT-INSERT-
CATCH-SELECT 패턴으로 200 idempotent replay (RFC 9110).

CHECK 제약 X — UUID v4 형식 검증은 라우터 application-level regex로 충분 (Story 8
hardening 시점에 DB CHECK 검토). 응답 wire 변경 X — ``MealResponse``에 노출 X
(클라이언트 입력 echo 회피 + payload 경량화).

partial UNIQUE는 Story 2.1 ``idx_meals_user_id_ate_at_active`` 패턴 정합 — NULL 제외
unique. ``deleted_at`` 무관 (soft-deleted row와 같은 키 재사용 시도는 라우터에서
``MealIdempotencyKeyConflictDeletedError(409)`` 분기 — AC2/AC9 정합).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_meals_idempotency_key"
down_revision: str | None = "0008_meals_parsed_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "meals",
        sa.Column("idempotency_key", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_meals_user_id_idempotency_key_unique",
        "meals",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    # idempotency_key는 부수 메타데이터(클라이언트 입력 echo X) — populated row 가드
    # 미적용 (Story 2.3 P8 패턴 X). 단순 drop.
    op.drop_index("idx_meals_user_id_idempotency_key_unique", table_name="meals")
    op.drop_column("meals", "idempotency_key")
