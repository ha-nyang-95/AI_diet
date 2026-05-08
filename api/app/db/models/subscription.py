"""Subscription ORM model — Story 6.1 (정기결제 sandbox 신청 + Toss 1플랜).

``subscriptions`` 테이블 — Epic 6 결제 도메인의 *active 구독* SOT. 한 사용자에 1
active subscription invariant를 ``idx_subscriptions_user_id_active_unique``
partial UNIQUE(``WHERE status='active'``)로 강제한다. Story 6.2 cancel 흐름에서
``status='cancelled'`` 전이 시 다음 신청 가능.

12 컬럼:

- ``id``                     ``UUID`` PK (``gen_random_uuid()`` server_default)
- ``user_id``                ``UUID NOT NULL`` FK ``users.id ON DELETE CASCADE``
- ``status``                 Postgres ENUM ``subscriptions_status_enum``
                             (``active``/``cancelled``/``expired``) NOT NULL
- ``plan``                   Postgres ENUM ``subscriptions_plan_enum``
                             (``monthly``) NOT NULL — 단일값 enum이지만 Story 6.x
                             후속에서 plan 추가 시 ``ALTER TYPE ADD VALUE`` 자연 확장
- ``plan_price_krw``         ``int`` NOT NULL — KRW integer (NFR-L3 / 9,900원)
- ``started_at``             ``timestamptz`` NOT NULL ``server_default=now()``
- ``cancelled_at``           ``timestamptz`` NULL — Story 6.2 cancel set
- ``expires_at``             ``timestamptz`` NULL — 현재 결제 주기 만료일
                             (Story 6.1: ``started_at + 30일``)
- ``provider``               Postgres ENUM ``subscriptions_provider_enum``
                             (``toss``/``stripe``) NOT NULL — 6.1은 ``toss``만
                             INSERT, ``stripe`` 값은 forward-compat 등재만
- ``provider_billing_key``   ``Text`` NULL — Toss billing key (Story 6.3 forward,
                             6.1에서는 항상 NULL)
- ``created_at``             ``timestamptz`` NOT NULL ``server_default=now()``
- ``updated_at``             ``timestamptz`` NOT NULL ``server_default=now()``
                             ``onupdate=now()``

partial UNIQUE: ``idx_subscriptions_user_id_active_unique`` ``(user_id) WHERE
status='active'`` — 한 사용자 1 active subscription invariant.

FK ``ondelete="CASCADE"`` — Story 5.2 30일 grace 후 hard-delete cascade.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Final, Literal

from sqlalchemy import ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.db.base import Base

# ENUM 값 SOT — alembic 0018과 *동일 SOT*. 변경 시 alembic 신규 revision으로
# ``ALTER TYPE ADD VALUE`` 또는 drop+recreate.
SUBSCRIPTION_STATUS_VALUES: Final[tuple[str, ...]] = ("active", "cancelled", "expired")
SUBSCRIPTION_PLAN_VALUES: Final[tuple[str, ...]] = ("monthly",)
SUBSCRIPTION_PROVIDER_VALUES: Final[tuple[str, ...]] = ("toss", "stripe")

SubscriptionStatus = Literal["active", "cancelled", "expired"]
SubscriptionPlan = Literal["monthly"]
SubscriptionProvider = Literal["toss", "stripe"]


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Postgres ENUM 직접 매핑 — ``create_type=False``로 alembic이 ENUM 생성 책임 SOT
    # (모델 import 시 implicit ENUM 생성 방지).
    status: Mapped[str] = mapped_column(
        PG_ENUM(
            *SUBSCRIPTION_STATUS_VALUES,
            name="subscriptions_status_enum",
            create_type=False,
        ),
        nullable=False,
    )
    plan: Mapped[str] = mapped_column(
        PG_ENUM(
            *SUBSCRIPTION_PLAN_VALUES,
            name="subscriptions_plan_enum",
            create_type=False,
        ),
        nullable=False,
    )
    plan_price_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider: Mapped[str] = mapped_column(
        PG_ENUM(
            *SUBSCRIPTION_PROVIDER_VALUES,
            name="subscriptions_provider_enum",
            create_type=False,
        ),
        nullable=False,
    )
    # Story 6.3 forward — Toss billing key (자동 갱신용). 6.1 baseline에서는 항상 NULL.
    provider_billing_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    __table_args__ = (
        # 한 사용자 1 active subscription invariant. partial UNIQUE — non-active row는
        # 색인 미진입 (cancel 후 재신청 자유 + DB-level race-free 가드).
        Index(
            "idx_subscriptions_user_id_active_unique",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )
