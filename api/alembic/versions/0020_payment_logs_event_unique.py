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
