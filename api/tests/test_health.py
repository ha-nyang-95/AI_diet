"""Smoke tests — /healthz, /readyz, X-Request-ID middleware.

전제: Postgres(pgvector extension 등록됨) + Redis 가 실행 중.
- CI: service container (pgvector 수동 설치 후 conftest precondition fixture가 검증)
- 로컬: docker compose up
"""

from __future__ import annotations

import re
import uuid

from httpx import AsyncClient

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


async def test_healthz_ok(client: AsyncClient) -> None:
    """Liveness — 외부 의존성 무관, 프로세스 생존만 확인."""
    response = await client.get("/healthz")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload == {"status": "ok"}  # DB 키 등 없음 — 의도적으로 의존성 분리


async def test_readyz_ok(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["postgres"] == "ok"
    assert payload["pgvector"] == "ok"
    assert payload["redis"] == "ok"


async def test_request_id_generated_when_absent(client: AsyncClient) -> None:
    """클라이언트가 X-Request-ID를 안 보내면 서버가 UUIDv4를 신규 발급."""
    response = await client.get("/healthz")
    assert "X-Request-ID" in response.headers
    rid = response.headers["X-Request-ID"]
    # UUID 파싱이 성공하고 v4여야 함
    parsed = uuid.UUID(rid)
    assert parsed.version == 4
    assert UUID_RE.fullmatch(rid) is not None


async def test_request_id_preserved_when_valid(client: AsyncClient) -> None:
    """검증 통과한 클라이언트 X-Request-ID는 그대로 보존."""
    incoming = "abc-123-xyz-42"
    response = await client.get("/healthz", headers={"X-Request-ID": incoming})
    assert response.headers["X-Request-ID"] == incoming


async def test_request_id_rejected_when_malformed(client: AsyncClient) -> None:
    """검증 실패한 X-Request-ID(CRLF 인젝션·형식 위반)는 폐기, 신규 UUID 발급."""
    malicious = "evil\r\nX-Injected: yes"
    response = await client.get("/healthz", headers={"X-Request-ID": malicious})
    rid = response.headers["X-Request-ID"]
    assert rid != malicious
    assert "\r" not in rid and "\n" not in rid
    # 신규 발급은 UUIDv4
    assert uuid.UUID(rid).version == 4
