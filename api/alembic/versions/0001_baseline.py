"""0001_baseline — empty migration.

도메인 테이블(`users`, `meals` 등)은 Story 1.2/1.5+에서 추가된다.
`vector` extension 및 `lg_checkpoints` 스키마 생성은 docker/postgres-init/01-pgvector.sql에서 처리.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
