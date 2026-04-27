"""request_id 미들웨어.

- 클라이언트가 보낸 X-Request-ID를 검증 후 채택, 미통과 시 신규 UUIDv4 발급.
- 검증 실패 케이스: 형식 부적합 / 길이 초과 / CRLF 포함 — 로그 인젝션 차단.
- structlog contextvars에 bind, response 헤더에 X-Request-ID 반영.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
# 허용 문자: 영숫자 + 하이픈, 길이 1~64 (UUID·짧은 토큰·correlation id 모두 수용).
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def _accept_or_generate(incoming: str | None) -> str:
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return str(uuid.uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _accept_or_generate(request.headers.get(REQUEST_ID_HEADER))

        # bound_contextvars 컨텍스트매니저 — BackgroundTasks·create_task로 이어지는
        # 자식 태스크에 contextvars가 누수되지 않도록 스코프 한정.
        with structlog.contextvars.bound_contextvars(request_id=request_id):
            response = await call_next(request)

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
