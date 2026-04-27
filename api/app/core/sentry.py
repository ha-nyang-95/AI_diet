"""Sentry 초기화 + before_send hook 자리표시자 (NFR-S5 마스킹은 Story 1.2/Epic 8에서 정교화)."""

from __future__ import annotations

import sentry_sdk
from sentry_sdk.types import Event, Hint

from app.core.config import settings


def mask_event(event: Event, hint: Hint) -> Event | None:
    """Sentry before_send hook — 민감정보 마스킹 자리표시자.

    향후 NFR-S5 정규식 마스킹 추가 위치:
    - request.headers.Authorization → "***"
    - request.cookies → "***"
    - extra/contexts에 포함된 JWT/secret 패턴 마스킹
    """
    _ = hint
    return event


def init_sentry() -> None:
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.1,
        send_default_pii=False,
        before_send=mask_event,
    )
