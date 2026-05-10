"""PaymentLog ORM model — Story 6.1 (정기결제 sandbox 신청 + payment_logs audit-trail).

``payment_logs`` 테이블 — Epic 6 결제 도메인 *audit-trail*. 모든 결제 시도(성공/
실패)와 forward-compat 이벤트(refund/renew/cancel)를 추적. soft-delete 미적용 —
audit-trail 성격이라 영구 보존(``ondelete="CASCADE"``로 사용자 삭제 시점에만 cascade).

13 컬럼:

- ``id``                       ``UUID`` PK (``gen_random_uuid()`` server_default)
- ``user_id``                  ``UUID NOT NULL`` FK ``users.id ON DELETE CASCADE``
- ``subscription_id``          ``UUID NULL`` FK ``subscriptions.id ON DELETE SET NULL``
                               — 결제 시점에 subscription row가 동일 트랜잭션에서 막
                               생성되므로 NOT NULL이 자연이지만, 환불/실패 결제 등
                               subscription 무관 이벤트 forward-compat 위해 nullable
- ``event_type``               Postgres ENUM ``payment_logs_event_type_enum``
                               (``subscribe``/``cancel``/``renew``/``failed``/
                               ``refund``) NOT NULL — 6.1은 ``subscribe``/``failed``만
- ``provider``                 Postgres ENUM ``payment_logs_provider_enum``
                               (``toss``/``stripe``) NOT NULL — 6.1은 ``toss``만
- ``provider_payment_key``     ``Text`` NULL — Toss ``paymentKey``(36+자) /
                               Stripe ``pi_...``. 결제 실패 시 NULL 가능
- ``provider_order_id``        ``Text`` NULL — Toss ``orderId`` (UUID v4 권장)
- ``amount_krw``               ``int`` NOT NULL — 9,900 (KRW integer 정합)
- ``status``                   Postgres ENUM ``payment_logs_status_enum``
                               (``success``/``failed``/``pending``) NOT NULL —
                               6.1은 ``success``/``failed``만, ``pending``은
                               Story 6.3 webhook forward
- ``idempotency_key``          ``Text`` NULL — application-level Idempotency-Key
                               영속화 (Story 2.5 ``meals.idempotency_key`` 패턴 정합)
- ``raw_payload``              ``JSONB`` NULL — Toss ``confirm_payment`` 응답 본문
                               *마스킹 후* (``customerEmail``/``customerName``/
                               ``customerMobilePhone`` 제거 + ``card.number`` 마지막
                               4자리 보존 — ``_mask_payment_payload`` SOT)
- ``occurred_at``              ``timestamptz`` NOT NULL — Toss ``approvedAt`` 또는
                               server ``now()`` fallback
- ``created_at``               ``timestamptz`` NOT NULL ``server_default=now()``

인덱스 3건:

- ``idx_payment_logs_user_id_occurred_at`` ``(user_id, occurred_at DESC)`` — Story
  6.2 history 조회 정합 (시계열 sort).
- ``idx_payment_logs_provider_payment_key_event_type_unique`` ``(provider,
  provider_payment_key, event_type) WHERE provider_payment_key IS NOT NULL`` composite
  partial UNIQUE — Story 6.3 alembic 0020 (D9 흡수). 같은 paymentKey가 *multiple
  event_type*(``subscribe → refund`` / ``renew → failed`` 등) INSERT 가능. 같은
  ``(provider, payment_key, event_type)`` 중복은 그대로 차단(*같은 결제건 같은 event 2번
  INSERT 방지*). 0019 baseline ``(provider, provider_payment_key)`` partial UNIQUE는
  drop + recreate.
- ``idx_payment_logs_user_id_idempotency_key_unique`` ``(user_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL`` partial UNIQUE — Story 2.5 0009 패턴 1:1 정합.
  application-level Idempotency-Key replay race-free SELECT-INSERT-CATCH-SELECT
  (``_subscribe_idempotent_or_replay`` 헬퍼).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Final, Literal

from sqlalchemy import ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.db.base import Base

# ENUM 값 SOT — alembic 0019와 *동일 SOT*.
PAYMENT_LOG_EVENT_TYPE_VALUES: Final[tuple[str, ...]] = (
    "subscribe",
    "cancel",
    "renew",
    "failed",
    "refund",
)
PAYMENT_LOG_PROVIDER_VALUES: Final[tuple[str, ...]] = ("toss", "stripe")
PAYMENT_LOG_STATUS_VALUES: Final[tuple[str, ...]] = ("success", "failed", "pending")

PaymentLogEventType = Literal["subscribe", "cancel", "renew", "failed", "refund"]
PaymentLogProvider = Literal["toss", "stripe"]
PaymentLogStatus = Literal["success", "failed", "pending"]


class PaymentLog(Base):
    __tablename__ = "payment_logs"

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
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(
        PG_ENUM(
            *PAYMENT_LOG_EVENT_TYPE_VALUES,
            name="payment_logs_event_type_enum",
            create_type=False,
        ),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        PG_ENUM(
            *PAYMENT_LOG_PROVIDER_VALUES,
            name="payment_logs_provider_enum",
            create_type=False,
        ),
        nullable=False,
    )
    provider_payment_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        PG_ENUM(
            *PAYMENT_LOG_STATUS_VALUES,
            name="payment_logs_status_enum",
            create_type=False,
        ),
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        # Story 6.2 history 조회 — 시계열 sort. user별 최근 결제 이력 fetch에 hit.
        Index(
            "idx_payment_logs_user_id_occurred_at",
            "user_id",
            text("occurred_at DESC"),
        ),
        # Story 6.3 (D9 흡수) — composite partial UNIQUE. 같은 paymentKey가 multiple
        # event_type(subscribe → refund / renew → failed 등) INSERT 가능. 0019 baseline
        # ``(provider, provider_payment_key)`` partial UNIQUE는 0020에서 drop + recreate.
        # NULL 미포함 partial WHERE — 결제 실패(키 부재) row는 색인 미진입(자유 INSERT).
        Index(
            "idx_payment_logs_provider_payment_key_event_type_unique",
            "provider",
            "provider_payment_key",
            "event_type",
            unique=True,
            postgresql_where=text("provider_payment_key IS NOT NULL"),
        ),
        # application-level Idempotency-Key replay 가드. Story 2.5 패턴 정합 — race-free
        # SELECT-INSERT-CATCH-SELECT의 IntegrityError 진입 신호.
        Index(
            "idx_payment_logs_user_id_idempotency_key_unique",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )
