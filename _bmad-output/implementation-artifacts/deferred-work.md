# Deferred Work

리뷰·구현 과정에서 식별되었으나 다음 스토리·시점으로 미룬 항목 모음.

## Deferred from: code review of 1-1-프로젝트-부트스트랩 (2026-04-27)

- **mypy `[[tool.mypy.overrides]]` 누락 모듈** — `api/pyproject.toml:46-52`에 langgraph, langchain*, langsmith, sse-starlette, tenacity, structlog 모듈 override 누락. 현재 mypy strict는 통과(import 미발생), 다음 스토리에서 해당 의존 import 도입 시 동시에 등재. 사유: 미사용 의존성에 대한 선제적 무시 규칙은 yagni; 실제 import 추가 시 즉시 처리.
- **이미지 태그 digest pin** — `docker-compose.yml`(`pgvector/pgvector:pg17`, `redis:7-alpine`), `docker/Dockerfile.api`(`ghcr.io/astral-sh/uv:0.11`)를 `@sha256:...` 형태로 pin. 사유: 부트스트랩 단계는 메이저 태그로 재현성 충분(rolling이지만 안정 채널). prod 재현성 hardening은 Story 8(운영·hardening)에서 SBOM·취약점 스캐너와 함께 일괄 도입.
- **`alembic upgrade head` migrate 서비스 분리** — 현재 `api` 컨테이너 CMD가 매 부팅마다 `alembic upgrade head && uvicorn`. 단일 replica에서는 안전, multi-replica 도입 시(Story 4 nudge alarm worker 추가 시점 또는 Railway scaling 활성화 시) advisory-lock 경합 차단을 위해 별도 `migrate` one-shot 서비스로 분리. Dockerfile.api에 NOTE(D3) 주석 예약.
