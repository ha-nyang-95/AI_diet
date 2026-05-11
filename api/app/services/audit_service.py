"""관리자 audit log 자동 기록 서비스 — Story 7.3 (FR37).

``record_admin_action`` 단일 함수 — ``audit_admin_action`` factory Dependency가
호출. payment_service.py audit-trail INSERT 패턴 1:1 정합 (single-INSERT + commit).

실패 격리: DB error는 silent log.error + return. ``audit_admin_action`` docstring
정합 — fail-open으로 admin business action 가용성 보존.
"""

from __future__ import annotations

import ipaddress
import uuid
from typing import TYPE_CHECKING

import structlog
from fastapi import Request
from sqlalchemy import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.masking import mask_email
from app.core.proxy import get_real_client_ip
from app.db.models.audit_log import AuditLog, AuditLogAction

if TYPE_CHECKING:  # pragma: no cover
    from app.db.models.user import User

logger = structlog.get_logger(__name__)

_REQUEST_ID_FALLBACK = "unknown"
_USER_AGENT_HEADER = "User-Agent"
# audit row text 컬럼 안전 상한 — client-controlled 입력(X-Request-ID/User-Agent)이
# 무제한 페이로드로 ``audit_logs`` 행 폭증 또는 Postgres ``invalid byte sequence``를
# 일으키지 않도록 explicit bound. 운영 SOP 정합 (Story 8.4 forward audit DB 분리시
# 별도 조정 가능).
_REQUEST_ID_MAX_LEN = 128
_USER_AGENT_MAX_LEN = 1024


def _sanitize_audit_text(raw: str | None, max_len: int) -> str | None:
    """audit row text 컬럼용 정제 — 제어문자(``\\x00-\\x1f`` + ``\\x7f``) 제거 +
    길이 cap.

    client-controlled 헤더(``X-Request-ID``/``User-Agent``)가 newline/NUL byte로
    audit row 위조(로그 라인 인젝션) 또는 Postgres ``text``의 NUL 거부로 fail-open
    silent drop을 일으키는 것을 차단. 정제 후 빈 string은 ``None`` 반환(NULL 허용
    필드용 — caller가 fallback 처리).
    """
    if raw is None:
        return None
    cleaned = "".join(ch for ch in raw if ch >= " " and ch != "\x7f")
    if not cleaned:
        return None
    return cleaned[:max_len]


def _extract_request_id() -> str:
    """structlog contextvars에서 ``RequestIdMiddleware`` bind된 ``request_id`` 추출.

    middleware 미통과(직접 dep call 등 비정상 진입) 시 ``"unknown"`` fallback —
    audit row의 ``request_id NOT NULL`` invariant 보존.

    middleware는 정규화된 UUID4를 bind하나, 비정상 진입 경로(예: 외부 미들웨어
    체인이 raw header를 그대로 bind)를 방어하기 위해 ``_sanitize_audit_text``로
    한 번 더 정제 — 제어문자/길이 폭증 차단.
    """
    ctx = structlog.contextvars.get_contextvars()
    value = ctx.get("request_id")
    if isinstance(value, str) and value:
        sanitized = _sanitize_audit_text(value, _REQUEST_ID_MAX_LEN)
        if sanitized:
            return sanitized
    return _REQUEST_ID_FALLBACK


def _coerce_ip(raw: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """``get_real_client_ip`` SOT 결과를 ``INET`` 컬럼 형식으로 변환.

    빈 string(헤더 부재 + request.client None — 테스트 환경) 또는 parsing 실패 시
    ``None`` 반환. INET NULL 허용으로 audit row 보존.

    IPv4-mapped IPv6(``::ffff:a.b.c.d``)는 IPv4로 정규화 — 포렌식 IPv4 CIDR 필터
    일관성 보존(``check_admin_ip_allowed`` Story 1.2 SOT가 이미 ``ipv4_mapped``
    분기로 IPv4 trust를 적용 → audit 영속화도 동일 정규화 정합).
    """
    if not raw:
        return None
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _extract_path_param_uuid(request: Request, key: str) -> uuid.UUID | None:
    """``request.path_params[key]``을 UUID로 parsing. 누락/실패 시 ``None``."""
    raw = request.path_params.get(key)
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


async def record_admin_action(
    db: AsyncSession,
    *,
    request: Request,
    admin: User,
    action: AuditLogAction,
    target_resource: str | None = None,
) -> None:
    """admin business action audit row INSERT + commit. fail-open log.error.

    payment_service single-INSERT 패턴 정합. ``commit()``은 본 함수에서 즉시 — read-only
    endpoint(검색/상세/이력)에서도 audit row가 persistent invariant 보존(write endpoint
    의 후속 ``db.commit()``과 별 트랜잭션 — 두 번째 commit은 audit row에는 무해).

    ``expire_on_commit=False``(lifespan SOT)로 commit 후에도 SQLAlchemy session 재사용
    가능 — 핸들러가 admin/db 객체를 계속 사용.
    """
    try:
        target_user_id = _extract_path_param_uuid(request, "user_id")
        target_resource_id = _extract_path_param_uuid(request, "meal_id")
        ip_value = _coerce_ip(get_real_client_ip(request) or None)
        request_id = _extract_request_id()
        user_agent = _sanitize_audit_text(
            request.headers.get(_USER_AGENT_HEADER), _USER_AGENT_MAX_LEN
        )

        await db.execute(
            insert(AuditLog).values(
                actor_id=admin.id,
                actor_email_masked=mask_email(admin.email),
                action=action,
                target_user_id=target_user_id,
                target_resource=target_resource,
                target_resource_id=target_resource_id,
                path=request.url.path,
                method=request.method,
                ip=ip_value,
                request_id=request_id,
                user_agent=user_agent,
            )
        )
        await db.commit()
    except SQLAlchemyError as exc:
        # fail-open: rollback + log + return.
        #   - business action 가용성 보존(거버넌스 SLA 우선)
        #   - Sentry 자동 capture(SDK before_send → NFR-S5 마스킹 정합)
        #   - audit DB 분리 시점(Story 8)까지 단일 DB 가용성 risk 흡수
        # ``SQLAlchemyError`` 한정 — DB/세션 장애만 흡수하고 ``TypeError``/
        # ``AttributeError`` 같은 코딩 버그는 즉시 노출(CR Gemini G1 권고 정합).
        # P0001 append-only trigger 위반은 ``IntegrityError`` (SQLAlchemyError 하위)
        # 라 fail-open 적용 — INSERT-only 경로에서 트리거는 미발동이므로 hypothetical.
        try:
            await db.rollback()
        except SQLAlchemyError as rollback_exc:
            # rollback 자체 실패는 session 심각 문제 신호 — 별도 ERROR 로깅으로
            # 운영 가시 보존(CR Gemini G2 권고 정합). 핸들러 본문 실행은 fail-open
            # 정책상 계속 진행.
            logger.error(
                "audit.record_admin_action.rollback_failed",
                action=action,
                error=str(rollback_exc),
                exc_info=True,
            )
        logger.error(
            "audit.record_admin_action.failed",
            action=action,
            error=str(exc),
            exc_info=True,
        )
