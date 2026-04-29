"""0007_meals_image_key — Story 2.2 (식단 사진 입력 + R2 presigned URL).

``meals`` 테이블에 ``image_key`` TEXT NULL 1 컬럼 추가 — R2 object key
(`meals/{user_id}/{uuid}.{ext}` 형식).

NOT NULL 부여 X — 텍스트-only 식단 호환 (Story 2.1 baseline 정합). 사진-only
입력 시 서버가 ``raw_text="(사진 입력)"`` placeholder fallback (라우터 책임).

CHECK 제약 X — image_key 형식 검증은 백엔드 라우터(`r2.generate_image_key`) 또는
Pydantic으로 충분. UNIQUE 제약 X — 같은 사용자가 같은 사진을 여러 식단에 첨부 가능
(동일 메뉴 반복 식사 시 사진 재사용). 추가 인덱스 X — `image_key` 단독 색인
미요구(쿼리 패턴 부재). soft-deleted 사진의 R2 garbage collection은 Story 5.2
(회원 탈퇴 + 30일 grace + 물리 파기 cron)에서 일괄 도입.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_meals_image_key"
down_revision: str | None = "0006_meals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meals", sa.Column("image_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("meals", "image_key")
