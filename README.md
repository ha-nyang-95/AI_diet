# BalanceNote (AI_diet)

> AI 영양 분석 + 인용 기반 피드백 — 한국형 식단 트래킹.
> 모바일(Expo) + Web 주간 리포트(Next.js) + FastAPI 백엔드 + LangGraph Self-RAG.

---

## 1. Quick Start (8시간 onboarding 체크리스트)

> 인수 대상 개발자가 *git clone부터 로컬 풀스택 부팅 + 자체 데이터 통합*까지 8시간 안에 완료할 수 있는 시퀀스.

### 사전 요구사항

- Docker Desktop ≥ 25 (Compose v2 내장)
- Node ≥ 22, pnpm ≥ 10 (`npm i -g pnpm`)
- Python ≥ 3.13 (uv가 자동 설치 가능)
- uv ≥ 0.11 (`pip install uv` 또는 `curl -LsSf https://astral.sh/uv/install.sh | sh`)

### 1-cmd 부팅

```bash
git clone <repo-url> AI_diet
cd AI_diet
cp .env.example .env             # 시크릿 채우기 (LLM key 없이도 인프라 부팅 OK)
docker compose up                # postgres + redis + api + seed 일괄 부팅 (≤ 10분)
```

다음 엔드포인트가 200을 반환하면 성공:

- `http://localhost:8000/healthz` — liveness
- `http://localhost:8000/readyz` — readiness (Postgres + Redis + pgvector 확인)
- `http://localhost:8000/docs` — Swagger UI

### Web (별 터미널)

```bash
cd web
pnpm install
pnpm dev                          # http://localhost:3000
```

### Mobile (별 터미널)

```bash
cd mobile
pnpm install
pnpm start                        # Expo dev menu — QR 스캔 또는 simulator
```

### OpenAPI 클라이언트 생성

백엔드가 가동된 상태에서:

```bash
pnpm gen:api                      # web/src/lib/api-client.ts + mobile/lib/api-client.ts 자동 생성
```

API 스키마가 변경되면 **반드시** 위 명령을 실행하고 결과 파일을 커밋해야 합니다(CI `openapi-diff` 게이트가 차단).

### 8시간 체크리스트

- [ ] (1h) `docker compose up` 4개 컨테이너 healthy 확인
- [ ] (2h) `web` `mobile` 각 dev 서버 시작
- [ ] (3h) `pnpm gen:api` 실행 + 자동 생성 확인
- [ ] (4h) `_bmad-output/planning-artifacts/architecture.md` 1독
- [ ] (5h) `_bmad-output/planning-artifacts/prd.md` 1독
- [ ] (6h) `api/tests` 테스트 실행 (`cd api && uv run pytest`)
- [ ] (7h) `_bmad-output/planning-artifacts/epics.md`로 다음 스토리 파악
- [ ] (8h) `pnpm tsc --noEmit` (web + mobile) 통과 확인 + 첫 PR 토스 검증

---

## 2. Architecture (placeholder)

> Story 8.3에서 채움. 현재는 `_bmad-output/planning-artifacts/architecture.md` 참조.

---

## 3. 데이터 모델 (placeholder)

> Story 8.3에서 채움.

---

## 4. 영업 closing FAQ (placeholder)

> Story 8.2에서 채움.

---

## 5. 클라우드 마이그레이션 SOP (placeholder)

> Story 8.5에서 채움.

### Vercel/Railway secret 등록 SOP (현 시점 placeholder)

main 브랜치 자동 배포는 다음을 전제로 한다:

- **Vercel** (Web)
  1. Vercel 대시보드 → Add New Project → 본 repo 연결
  2. Root directory: `web`
  3. Framework preset: Next.js (자동 감지)
  4. Environment variables: `NEXT_PUBLIC_API_BASE_URL` 등록
  5. main 브랜치 push 시 자동 배포

- **Railway** (API)
  1. Railway 대시보드 → New Project → Deploy from GitHub repo
  2. Root directory: `api` (또는 Dockerfile path: `docker/Dockerfile.api`)
  3. Service variables: `DATABASE_URL`, `REDIS_URL`, JWT/LLM 시크릿 전부 등록
  4. Postgres + Redis 플러그인 추가 (또는 외부 호스팅)
  5. Build hook으로 `alembic upgrade head` 실행

상세는 Story 8.5 (Cloud Migration Hardening Runbook)에서 갱신.
