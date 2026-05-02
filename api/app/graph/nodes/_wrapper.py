"""Story 3.3 — `_node_wrapper` 데코레이터 (AC3, AC6, AC7 + D4).

각 노드 함수에 (a) tenacity 1회 retry (transient만 — Pydantic / asyncio Timeout
/ httpx HTTPError), (b) Sentry child span (`op="langgraph.node"`), (c) retry 후
fallback 진입 시 `NodeError` instance를 반환 dict에 append (LangGraph dict-merge
정합) — 한 노드 실패가 전체 파이프라인을 멈추지 않음 (FR45 정합).

`AnalysisNodeError`는 retry skip — `fetch_user_profile.user_not_found`처럼 retry
의미 X 케이스를 즉시 fallback edge로 보냄.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

import httpx
import sentry_sdk
import structlog
from pydantic import ValidationError as PydanticValidationError
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.exceptions import AnalysisNodeError, AnalysisStateValidationError
from app.graph.state import MealAnalysisState, NodeError

log = structlog.get_logger()

NodeFn = Callable[..., Awaitable[dict[str, Any]]]

_RETRY_TYPES: tuple[type[BaseException], ...] = (
    PydanticValidationError,
    AnalysisStateValidationError,
    asyncio.TimeoutError,
    # transient httpx — 4xx/5xx response error는 retry 의미 X (요청 재시도 ≠ 응답 재시도).
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)


def _node_wrapper(node_name: str) -> Callable[[NodeFn], NodeFn]:
    """노드 함수를 (a) tenacity retry + (b) Sentry span + (c) NodeError fallback로 감싼다.

    노드 함수의 raw 시그니처는 `async def <name>(state, *, deps) -> dict`. wrapper는
    동일 시그니처 + `state["node_errors"]`를 *부분 갱신* dict로 반환(LangGraph
    dict-merge 정합).
    """

    def _decorator(fn: NodeFn) -> NodeFn:
        @wraps(fn)
        async def _wrapped(state: MealAnalysisState, **kwargs: Any) -> dict[str, Any]:
            attempts = 0
            last_exc: BaseException | None = None
            sentry_sdk.add_breadcrumb(
                category="langgraph",
                message=f"enter:{node_name}",
                data={"rewrite_attempts": state.get("rewrite_attempts", 0)},
            )
            with sentry_sdk.start_span(op="langgraph.node", name=node_name) as span:
                span.set_data("rewrite_attempts", state.get("rewrite_attempts", 0))
                try:
                    async for attempt in AsyncRetrying(
                        stop=stop_after_attempt(2),
                        wait=wait_exponential(multiplier=1, min=1, max=4),
                        retry=retry_if_exception_type(_RETRY_TYPES),
                        reraise=True,
                    ):
                        with attempt:
                            attempts = attempt.retry_state.attempt_number
                            if attempts > 1:
                                log.info(
                                    f"node.{node_name}.retry",
                                    attempts=attempts,
                                )
                            return await fn(state, **kwargs)
                except RetryError as exc:
                    inner = exc.last_attempt.exception()
                    last_exc = inner if inner is not None else exc
                except AnalysisNodeError as exc:
                    last_exc = exc
                    attempts = 1
                except _RETRY_TYPES as exc:
                    last_exc = exc
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc

                # fallback 진입 — NodeError append + 예외 swallow(다음 노드 진행)
                error_class = type(last_exc).__name__ if last_exc is not None else "Unknown"
                message = str(last_exc) if last_exc is not None else "unknown"
                log.warning(
                    f"node.{node_name}.fallback",
                    attempts=attempts,
                    error_class=error_class,
                )
                if last_exc is not None:
                    sentry_sdk.capture_exception(last_exc)
                node_err = NodeError(
                    node_name=node_name,
                    error_class=error_class,
                    message=message,
                    attempts=attempts,
                )
                existing = list(state.get("node_errors", []))
                existing.append(node_err)
                return {"node_errors": existing}

        return _wrapped

    return _decorator


__all__ = ["_node_wrapper"]
