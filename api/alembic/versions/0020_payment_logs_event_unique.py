"""0020_payment_logs_event_unique — Story 6.3 (D9 흡수).

``payment_logs.provider_payment_key`` partial UNIQUE를 *composite UNIQUE*로 확장:

- 기존 0019: ``(provider, provider_payment_key) WHERE provider_payment_key IS NOT NULL``
- 신규 0020: ``(provider, provider_payment_key, event_type) WHERE provider_payment_key IS NOT NULL``

같은 paymentKey가 *multiple event_type*(예: ``subscribe → refund`` / ``renew → failed`` /
``subscribe → renew → renew`` 등) INSERT 되는 webhook 흐름을 흡수. 같은
``(provider, payment_key, event_type)`` 중복은 그대로 차단(*같은 결제건 같은 event 2번
INSERT 방지*).

upgrade는 인덱스 drop → recreate(같은 partial WHERE 유지). downgrade는 역순.

Revision id ``0020_payment_logs_event_unique``는 alembic 표준 ``version_num
VARCHAR(32)`` 한도(32자) 정합 — 본 스토리 spec은 *의미 보존*만 요구(스펙은 "composite
UNIQUE (provider, provider_payment_key, event_type)" 명세, revision id는 alembic 한도
내에서 자유 선정).

CR P10 (Story 6.3) — **prod-scale lock 주의사항**:

본 마이그레이션은 ``op.drop_index`` + ``op.create_index``를 *비-CONCURRENTLY*로 실행 →
대규모 ``payment_logs`` 테이블(>10만 row)에 ACCESS EXCLUSIVE/SHARE 락을 걸어 마이그레이션
duration 동안 결제 INSERT가 차단됨. baseline은 sandbox/소규모 prod라 영향 0이지만,
prod 트래픽 증가 후 본 패턴 재실행 시 다음 SOP 권장:

- ``alembic upgrade``를 트랜잭션 밖으로 분리(``transactional_ddl=False``).
- CREATE는 ``op.execute("CREATE UNIQUE INDEX CONCURRENTLY ...")`` 변환(트랜잭션 외부
  필수).
- DROP은 별 마이그레이션으로 분리해 점진 적용.

CR P11 (Story 6.3) — **pre-flight 중복 데이터 가드**:

기존 데이터에 같은 ``(provider, provider_payment_key, event_type)`` 중복 row가 있으면
``CREATE UNIQUE INDEX`` 실패 → 마이그레이션 abort. prod 적용 *전*에 다음 SQL로 중복
검출 의무::

    SELECT provider, provider_payment_key, event_type, COUNT(*)
    FROM payment_logs
    WHERE provider_payment_key IS NOT NULL
    GROUP BY 1, 2, 3
    HAVING COUNT(*) > 1;

결과 0건이어야 안전 적용. 비-0건이면 cleanup 후 재시도(보통 dev/test 환경 잔여 row).
sandbox baseline은 0019 partial UNIQUE가 더 강한 제약이라 본 SQL은 자동으로 0건.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_payment_logs_event_unique"
down_revision: str | None = "0019_payment_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_NAME = "payment_logs"
_OLD_INDEX_NAME = "idx_payment_logs_provider_payment_key_unique"
_NEW_INDEX_NAME = "idx_payment_logs_provider_payment_key_event_type_unique"
_PARTIAL_WHERE = "provider_payment_key IS NOT NULL"


def upgrade() -> None:
    op.drop_index(_OLD_INDEX_NAME, table_name=_TABLE_NAME)
    op.create_index(
        _NEW_INDEX_NAME,
        _TABLE_NAME,
        ["provider", "provider_payment_key", "event_type"],
        unique=True,
        postgresql_where=sa.text(_PARTIAL_WHERE),
    )


def downgrade() -> None:
    op.drop_index(_NEW_INDEX_NAME, table_name=_TABLE_NAME)
    op.create_index(
        _OLD_INDEX_NAME,
        _TABLE_NAME,
        ["provider", "provider_payment_key"],
        unique=True,
        postgresql_where=sa.text(_PARTIAL_WHERE),
    )
