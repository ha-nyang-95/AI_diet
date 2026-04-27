"""structlog 초기화 — JSON renderer + mask_processor 자리표시자.

NFR-S5 정규식 마스킹은 Epic 8에서 정교화. 본 스토리에서는 구조만 박는다.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from app.core.config import settings


def mask_processor(
    logger: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """structlog processor — 민감정보 마스킹 자리표시자.

    향후 추가 위치:
    - event_dict 내 'authorization', 'cookie', 'jwt', 'token', 'secret' 키 마스킹
    - JSON 본문 내 패턴(`sk-...`, `eyJ...`) 정규식 마스킹
    """
    _ = logger, method_name
    return event_dict


def configure_logging() -> None:
    """애플리케이션 시작 시 1회 호출."""
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        mask_processor,
    ]

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    if settings.environment == "dev":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
