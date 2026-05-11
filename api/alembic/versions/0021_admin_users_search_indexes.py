"""0021_admin_users_search_indexes — Story 7.2 (관리자 사용자 검색 인덱스).

본 revision은 *1건 변경*:

1. ``idx_users_email_lower`` expression index 1건 추가 — ``CREATE INDEX
   idx_users_email_lower ON users (lower(email))``. ``GET /v1/admin/users?q=...``
   검색 endpoint의 email ILIKE prefix(``lower(email) LIKE 'lower_q%'``) 매칭 SOT —
   NFR-P9 *Web 관리자 사용자 검색 1만 건 ≤ 1초* 정합.

설계 결정:

- ``varchar_pattern_ops`` / ``text_pattern_ops`` 미사용 — ``lower()`` 이미 case-insensitive
  변환 후 ``LIKE 'lower_q%'`` 형태이므로 default ops로 prefix range hit. ``LIKE 'q%'`` 또는
  ``ILIKE 'q%'`` 직접 사용 시는 별도 ops 의무이지만 본 endpoint는 ``func.lower(email)``로
  통일.
- ``partial WHERE`` 미적용 — soft-deleted 사용자(``deleted_at IS NOT NULL``)도 admin 검색
  대상(거버넌스 가시화). 활성/비활성 양쪽 모두 색인.
- ``users.id::text`` 인덱스 미생성 — UUID v4 ``gen_random_uuid()`` random distribution이라
  prefix 검색은 인덱스 hit률 0(btree range scan은 row가 무작위 페이지에 흩어져 random I/O).
  1만 row × text cast ≤ 100ms full scan 허용. 100만 row 이상 + 빈도 폭증 시
  ``pg_trgm`` GIN index 도입 — Story 8 perf hardening.

회귀 0건: 신규 expression index만 추가, 기존 컬럼/CHECK/인덱스 변경 없음.
``users.email`` UNIQUE는 0001/0002 SOT 그대로 유지 — 본 인덱스는 *case-insensitive prefix
검색 가속*만 담당.

prod-scale lock 주의(Story 6.3 0020 P10 패턴 정합): 본 ``op.create_index``는 *비-CONCURRENTLY*
실행 → 대규모 ``users`` 테이블에서 ACCESS EXCLUSIVE/SHARE 락. baseline은 sandbox라 영향 0.
prod 트래픽 증가 후 재실행 시 ``CREATE INDEX CONCURRENTLY`` 변환 + 트랜잭션 분리 SOP 권장.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021_admin_users_search_indexes"
down_revision: str | None = "0020_payment_logs_event_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEX_NAME = "idx_users_email_lower"


def upgrade() -> None:
    op.execute(f"CREATE INDEX {_INDEX_NAME} ON users (lower(email))")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
