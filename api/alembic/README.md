# Alembic — async migration

```bash
# 로컬 (api 컨테이너 외부)
cd api
uv run alembic upgrade head             # 최신
uv run alembic revision -m "add_users"  # autogenerate 미사용 (수동 review)
uv run alembic downgrade -1             # 1단계 롤백
```

## 컨벤션

- 본 프로젝트는 `autogenerate` 없이 **수동 작성** (PR review에서 destructive 차단).
- `target_metadata = None` — 도메인 모델 추가 시 `app/db/base.py`의 `Base.metadata`로 교체.
- **`lg_checkpoints` 스키마는 Alembic 추적 외부** — LangGraph `AsyncPostgresSaver.setup()`이 자체 관리.
- **`vector` extension**은 `docker/postgres-init/01-pgvector.sql`에서 `CREATE EXTENSION IF NOT EXISTS`로 처리 (Alembic 외부).

## CI 게이트

- PR마다 `alembic upgrade head --sql` 결과를 코멘트로 게시 (`alembic-dry-run` 잡).
- main 머지 시 Railway 배포 hook이 `alembic upgrade head` 자동 실행.
