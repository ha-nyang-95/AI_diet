"""AuditLog ORM model — Story 7.3 (관리자 audit log 자동 기록).

``audit_logs`` 테이블 — Epic 7 admin *audit-trail*. 관리자의 *모든 조회·수정 액션*
을 시점·액터·액션·대상·IP·request_id로 영구 기록(append-only — Story 7.3 trigger
SOT). soft-delete 미적용 — audit-trail 성격이라 영구 보존(``actor_id`` ondelete
``RESTRICT`` — admin 사용자 hard delete 시점에 audit 행 보존을 위해 차단 + 운영
이벤트로 신호).

13 컬럼:

- ``id``                  ``UUID`` PK (``gen_random_uuid()`` server_default)
- ``occurred_at``         ``timestamptz NOT NULL`` ``server_default=now()`` — FR37 *시점*
- ``actor_id``            ``UUID NOT NULL`` FK ``users.id ON DELETE RESTRICT`` — FR37 *액터*
                          (RESTRICT: admin hard delete 시 audit 보존 invariant 차단)
- ``actor_email_masked``  ``Text NOT NULL`` — ``j***@example.com`` (NFR-S5,
                          ``mask_email`` SOT 재사용). ``users.email`` 변경 후에도 audit
                          시점 식별 정보 보존.
- ``action``              Postgres ENUM ``audit_logs_action_enum`` NOT NULL — FR37
                          *액션* 7 값: ``user_search``, ``user_profile_view``,
                          ``user_meal_history_view``, ``user_feedback_history_view``,
                          ``user_profile_edit``, ``admin_meal_delete``, ``user_pii_view``
                          (마지막은 Story 7.4 forward).
- ``target_user_id``      ``UUID NULL`` FK ``users.id ON DELETE SET NULL`` — FR37
                          *대상* (검색 endpoint는 NULL — path param 없음).
- ``target_resource``     ``Text NULL`` — ``users`` / ``meals`` / ``meal_analyses``
                          resource 분류 (검색·필터 인덱스 hit률 향상).
- ``target_resource_id``  ``UUID NULL`` — ``admin_meal_delete``의 ``meal_id`` 등
                          sub-resource id (target_user_id와 직교).
- ``path``                ``Text NOT NULL`` — ``/v1/admin/users/{user_id}`` evaluated URL
- ``method``              ``Text NOT NULL`` — ``GET`` / ``PATCH`` / ``DELETE``
                          (HTTP method literal).
- ``ip``                  ``INET NULL`` — ``get_real_client_ip`` SOT(Story 3.9 CR P1).
                          middleware/proxy fall-through 시 빈 string → NULL 변환.
- ``request_id``          ``Text NOT NULL`` — ``RequestIdMiddleware``(Story 3.x SOT)
                          ``structlog.contextvars`` 추출. middleware 미통과 fallback
                          ``"unknown"``.
- ``user_agent``          ``Text NULL`` — ``User-Agent`` 헤더(마스킹 X — 디바이스/
                          브라우저 식별 정보는 PII 비포함).

인덱스 3건 — epics.md:918 *"시간/액터/대상별 인덱스로 응답 ≤ 1초"* 정합:

- ``idx_audit_logs_occurred_at`` ``(occurred_at DESC)`` — 전체 시계열 sort. Story 7.4
  *내 활동 로그 시간순 표시* 정합.
- ``idx_audit_logs_actor_id_occurred_at`` ``(actor_id, occurred_at DESC)`` — Story 7.4
  *self-audit (`actor_id=me` 분기)* 정합.
- ``idx_audit_logs_target_user_id_occurred_at`` ``(target_user_id, occurred_at DESC)
  WHERE target_user_id IS NOT NULL`` partial — *"이 사용자에게 누가 무엇을 했나"* 역추적.
  partial WHERE — 검색(target_user_id NULL)은 색인 미진입으로 hot path INSERT 비용 0.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime
from typing import Final, Literal

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.db.base import Base

AUDIT_LOG_ACTION_VALUES: Final[tuple[str, ...]] = (
    "user_search",
    "user_profile_view",
    "user_meal_history_view",
    "user_feedback_history_view",
    "user_profile_edit",
    "admin_meal_delete",
    "user_pii_view",  # Story 7.4 forward — 원문 보기 토글 액션 자체 기록
)

AuditLogAction = Literal[
    "user_search",
    "user_profile_view",
    "user_meal_history_view",
    "user_feedback_history_view",
    "user_profile_edit",
    "admin_meal_delete",
    "user_pii_view",
]


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_email_masked: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(
        PG_ENUM(
            *AUDIT_LOG_ACTION_VALUES,
            name="audit_logs_action_enum",
            create_type=False,
        ),
        nullable=False,
    )
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    ip: Mapped[ipaddress.IPv4Address | ipaddress.IPv6Address | None] = mapped_column(
        INET, nullable=True
    )
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "idx_audit_logs_occurred_at",
            text("occurred_at DESC"),
        ),
        Index(
            "idx_audit_logs_actor_id_occurred_at",
            "actor_id",
            text("occurred_at DESC"),
        ),
        Index(
            "idx_audit_logs_target_user_id_occurred_at",
            "target_user_id",
            text("occurred_at DESC"),
            postgresql_where=text("target_user_id IS NOT NULL"),
        ),
    )
