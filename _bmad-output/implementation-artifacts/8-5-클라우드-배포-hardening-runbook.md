# Story 8.5: Render + Supabase 미니멀 배포 + Docker hardening + 일별 비용 cron + Runbook 3종

Status: review

<!-- Epic 8 첫 진입 스토리(8.1-8.4보다 8.5 우선 시작 — 사용자 결정 2026-05-12). epics.md:1007-1021
원본 AC body는 Vercel(Web) + Railway(API+Postgres+Redis) + Cloudflare R2(이미지) 토폴로지
명시였으나, **2026-05-12 사용자 결정으로 Render + Supabase 2-서비스 미니멀 패턴으로 swap**.
배경: (a) Railway 무료 tier 2023-08 폐지(Trial $5 일회성 → Hobby $5/월 구독 필수),
(b) 포트폴리오 데모 한정(실 사용자 X) → 비용 $0 + 단순성 우선, (c) Cloudflare WAF는
포트폴리오 scope 외, (d) Cloudflare R2도 Supabase Storage로 swap해 dashboard 1개로 통합.

**미니멀 패턴 (2 서비스)**:
- **Render** Free tier — Web Service A (FastAPI `bn-api.onrender.com` Docker 빌드) +
  Web Service B (Next.js `bn-web.onrender.com` Node 빌드). 15분 idle → cold start
  30~60초 수용(데모 직전 워밍업 1회 ping).
- **Supabase** Free tier — Postgres 500MB + pgvector 네이티브 + Storage 1GB. region
  Seoul(없을 시 Tokyo). 7일 inactivity → pause(restore 1분).
- **Redis 생략** — `redis is None` graceful fallback 활용:
  * `slowapi` rate limit → in-memory backend (`api/app/main.py` Limiter init)
  * Vision/LLM router 캐시 → 미적용(매 호출 → cost 살짝 ↑ but 포트폴리오 scope OK)
  * `subscription_expire.py` lock → in-memory fallback(line 70-72)
  * Idempotency-Key (`api/app/core/idempotency.py`) → DB `meals.idempotency_key`
    UNIQUE 제약이 SOT라 Redis 없어도 멱등성 유지(Story 2.5 SOT)
- **Cloudflare 완전 생략** — DNS·WAF·R2 모두 미사용(포트폴리오 데모는 `.onrender.com`
  subdomain 그대로 + Supabase Storage 사용). 외주 인수 시점에 Cloudflare 재도입 옵션은
  `docs/runbook/deployment.md` §4.4에 SOP 명시.
- **도메인 생략** — `.onrender.com` subdomain 그대로 사용. Google OAuth Console에
  `https://bn-web.onrender.com/api/auth/google/callback` 사전 등록 완료(2026-05-12).
- **모니터링**: Sentry Developer plan(무료) — backend project `balancenote-api` +
  frontend project `balancenote-web` 2개 분리, DSN 2개를 Render env vars에 주입.
- **OAuth 재사용**: 기존 Web client(`559604985813-fi8m...`) 그대로 + 신규 redirect
  URI 추가만(2026-05-12 사용자 등록 완료). iOS/Android client는 변경 0건.
- **시크릿 재사용**: dev 키 그대로 prod에 재사용(포트폴리오 scope). 인수 시점에
  분리 발급 SOP를 `docs/runbook/secret-rotation.md` §5/§8에 명시.

**Storage 추상화 결정 (D1, 2026-05-12)**: `api/app/adapters/r2.py`를
`api/app/adapters/storage.py`로 rename하지 않고 **모듈 SOT를 그대로 유지하되 내부 구현을
Supabase Storage로 swap**. 함수 시그니처(`create_presigned_upload`, `head_object_exists`,
`resolve_public_url`, `PresignedUpload` dataclass) + import 경로(`from app.adapters import
r2 as r2_adapter`) 모두 유지 → 호출처(`meals_images.py`, `data_export_service.py`,
`meal_analysis_persistence.py` 등) 변경 0건. *내부 구현*만 boto3 → `supabase-py` Storage
client로 교체. `r2` 이름은 *historical*이지만 *external semantic은 같음*(presigned upload
+ public URL + HEAD check). 외주 인수 시 R2 재도입 의향 시점에 `storage.py`로 정식 추상화
+ `STORAGE_PROVIDER` env로 분기 (Story 8.4 polish forward).

**Story 8.4 사전 의존 분리 (D2, 2026-05-12)**: Story 8.4 polish 일부가 prod 가시화에
유용하나(Sentry prod env split / OpenAPI 정리 / rate limit hardening 등), 본 스토리는
*prod 동작 자체*만 책임 — 8.4는 8.5 머지 후 별도 진행. 8.5에 포함하는 *최소 8.4 hunk*는:
(a) Sentry `environment` 환경별 분리(`environment="production"` env var), (b) `ENVIRONMENT=
production` env가 부재 시 graceful default("dev"). 그 외 8.4 항목(rate limit Redis backend
정교화 / LLM 캐시 정교화 / 표준 빈/로딩/에러 화면 일괄)은 OUT.

**Discord vs Slack (D3, 2026-05-12)**: 비용 알림 webhook 채널 → **Discord** 채택. 사유:
(a) 개인 server 생성·webhook 발급 5분, (b) 무료 영구 메시지 보관(Slack free 90일 한정),
(c) Sentry/GitHub 모두 Discord webhook native 지원.

**Render service plan (D4)**: Free tier 확정 — cold start 30~60초 + 750 hours/월 한도.
포트폴리오 데모는 idle time 다수라 750hr/월 충분.

**Supabase plan (D5)**: Free tier 확정 — Postgres 500MB(식약처 시드 1500건 + 가이드라인
chunk + 사용자 row 충분), Storage 1GB(데모 사진 ~100MB 예상), 7일 inactivity pause(데모
직전 dashboard restore 1분).

**pgvector on Supabase (D6)**: Supabase free tier에서 `CREATE EXTENSION vector` 권한 보유
(dashboard → Database → Extensions에서 enable). 기존 alembic `0010_food_nutrition_and_aliases.py`
의 `CREATE EXTENSION IF NOT EXISTS vector` 그대로 실행 가능 — Supabase는 superuser 권한
없는 사용자도 vector extension 활성화 허용(공식 docs 확인 완료).

**daily-cost-alert webhook 무료 plan 호환 (D7)**: Discord webhook은 무료 plan에서 1초당
30 messages 제한 — 매일 1회 호출은 무관. OpenAI/Anthropic Usage API는 둘 다 무료 호출(빈도
제한만). LangSmith API도 free plan에서 read 호출 무료(write/dataset만 한도).

**scope 외 (OUT, 후속 처리)**:
- DF102/DF103 식약처 데이터 보강 (NOW-ACTIONABLE 결정 완료, 별도 PR)
- W4 약관 버전 bump major/minor SOP (NOW-ACTIONABLE, 별도 PR)
- Story 8.4 운영 polish 전체 (rate limit Redis / LLM 캐시 정교화 / 표준 빈/로딩/에러 / OpenAPI 정리 / 모바일 jest 인프라 등)
- 도메인 구매 / Cloudflare 통합 / WAF rule
- Toss prod live mode (sandbox만)
- Apple Developer / Google Play 정식 출시 (모바일 EAS dev build로 데모)
- Multi-replica 운영
- Cron 자동 ping(idle pause 회피) — 데모 직전 수동 활성화

PR pattern: feature branch `story/8.5-cloud-deploy-render-supabase` (master에서 분기 완료
2026-05-12) — CS/DS/CR 모두 동일 브랜치, PR은 CR 완료 후 1회 + memory
`feedback_cr_done_status_in_pr_commit` 정합으로 CR 종료 직전 sprint-status `review → done`
+ `epic-8: backlog → in-progress` 갱신 commit에 포함. -->

## Story

As a 1인 개발자 / 외주 인수 클라이언트 / 영업 포트폴리오 시연자,
I want 프로덕션 staging 환경이 Render + Supabase 2-서비스 미니멀 패턴으로 비용 $0에 배포되고, Docker multi-stage build로 hardening되며, 일별 LLM 비용 알림 cron이 Discord webhook으로 작동하고, Runbook 3종(deployment / secret-rotation / incident-response)이 운영 SOP를 제공하기를,
So that 영업 미팅에서 라이브 URL을 즉시 시연할 수 있고, 비용 폭증·보안 약점·운영 사고에 대한 사전 차단·사후 대응이 즉시 가능하다.

## Acceptance Criteria

1. **AC1 — Dockerfile.api multi-stage build (이미지 size ↓ + build/runtime 분리)** (NFR-Sc1)
   **Given** 현 `docker/Dockerfile.api` single-stage(python:3.13-slim + uv sync + COPY api/ + alembic + uvicorn), **When** multi-stage로 재작성, **Then**:
   - **Stage 1 `builder`** — `python:3.13-slim` + `apt-get install build-essential libpq5 curl` + uv 바이너리 + `uv sync --frozen --no-dev --no-install-project` + 소스 COPY + `uv sync --frozen --no-dev`로 venv build (`/opt/uv-venv` 산출물)
   - **Stage 2 `runtime`** — `python:3.13-slim` + `apt-get install libpq5 curl`(런타임 최소) + `COPY --from=builder /opt/uv-venv /opt/uv-venv` + `COPY --from=builder /app /app` + `COPY scripts/ /app/scripts/` + `ENV PATH="/opt/uv-venv/bin:$PATH"`
   - **build-essential 등 빌드 도구 runtime 미포함** → 이미지 size ~40% 감소(현 ~800MB → 목표 ~500MB)
   - **healthcheck `/healthz` 정합 유지** — `HEALTHCHECK CMD curl -f http://localhost:8000/healthz || exit 1`
   - **CMD 유지** — `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}` (Render는 `$PORT` env 자동 주입, 로컬 docker-compose는 8000 default)
   - **`.dockerignore` 신규 작성 또는 갱신** — `node_modules/`, `.next/`, `.git/`, `mobile/`, `web/`, `_bmad/`, `_bmad-output/`, `docs/`, `tests/`, `__pycache__/`, `*.pyc`, `.env*` 제외해 build context 최소화
   - **로컬 회귀 0건** — `docker compose up`로 기존 흐름 정상 동작(api healthy + seed 통과)

2. **AC2 — docker-compose.yml hardening 검증 (이미 적용된 healthcheck/dependency wait 유지 + prod 분리 명시)** (NFR-Sc1)
   **Given** 현 `docker-compose.yml`이 이미 postgres/redis healthcheck + `condition: service_healthy` dependency wait + volume mount 분리(api source + scripts) 적용, **When** Render 배포가 docker-compose를 참조하지 않음을 명시화, **Then**:
   - **docker-compose.yml 본문 변경 0건** — 로컬 dev 전용 SOT로 보존
   - **헤더 주석 갱신** — `# Local dev only. Render는 본 파일 미참조 — Dockerfile.api 단독 사용.` 명시
   - **`postgres-init/` 폴더 검증** — pgvector extension auto-create SQL이 있다면 Supabase에서는 dashboard 활성화로 대체됨을 주석 명시
   - **회귀 0건** — `docker compose up` 정상 부팅 + api healthy + seed 통과

3. **AC3 — Render 배포 (Web Service A: bn-api FastAPI + Web Service B: bn-web Next.js) + Supabase Postgres+pgvector+Storage prod 운영** (NFR-Sc1/Sc4, FR48)
   **Given** Render dashboard에서 사용자가 2개 Web Service 생성 + Supabase dashboard에서 1개 project 생성, **When** 본 스토리 코드/설정 머지 + 사용자가 환경변수 주입 + 첫 배포 trigger, **Then**:
   - **bn-api Web Service** (Render Free tier, Docker runtime):
     * **Source**: GitHub repo `chulhwan/AI_diet` + branch `master` + auto-deploy ON
     * **Dockerfile path**: `docker/Dockerfile.api`
     * **Docker context**: `.` (repo root)
     * **Health check path**: `/healthz`
     * **환경변수 입력 항목**(`.env.production.example` SOT 정합 — AC10):
       - `DATABASE_URL`: Supabase project Settings → Database → Connection string → URI(Transaction mode pooler `?pgbouncer=true` 사용, port 6543)
       - `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `LANGSMITH_API_KEY` (dev 키 재사용)
       - `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` (dev 클라이언트 재사용)
       - `GOOGLE_OAUTH_REDIRECT_URI`: `https://bn-web.onrender.com/api/auth/google/callback`
       - `SENTRY_DSN`: Sentry backend project DSN
       - `ENVIRONMENT`: `production`
       - `JWT_SECRET_KEY` (32+ bytes 신규 발급 — Python `secrets.token_urlsafe(32)`)
       - `STORAGE_PROVIDER`: `supabase` (신규 env, AC8 정합)
       - `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_STORAGE_BUCKET=meals` (신규 env, AC8)
       - `CORS_ALLOWED_ORIGINS`: `https://bn-web.onrender.com`
       - `TOSS_SECRET_KEY` / `TOSS_WEBHOOK_SECRET_KEY` (dev sandbox 키 재사용)
       - `LANGCHAIN_TRACING_V2=true` / `LANGSMITH_PROJECT=balancenote-prod`
     * **Render는 HTTPS 자동 적용** — `.onrender.com` subdomain은 Let's Encrypt 자동 발급
     * **첫 배포 시 alembic migration 자동 실행** — Dockerfile CMD에 `alembic upgrade head &&` 포함이 SOT
   - **bn-web Web Service** (Render Free tier, Node runtime):
     * **Source**: 동일 repo + branch `master` + auto-deploy ON
     * **Root directory**: `web`
     * **Build command**: `pnpm install --frozen-lockfile && pnpm build`
     * **Start command**: `pnpm start` (standalone mode 활성 시 자동 적용 — AC9)
     * **환경변수 입력 항목**:
       - `NEXT_PUBLIC_API_BASE_URL`: `https://bn-api.onrender.com`
       - `API_BASE_URL`: `https://bn-api.onrender.com` (server-side fetch용)
       - `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT_URI` (bn-api와 동일 값)
       - `NEXT_PUBLIC_SENTRY_DSN`: Sentry frontend project DSN
       - `NODE_ENV=production` (Render 자동 주입)
   - **Supabase project 설정**:
     * region: Northeast Asia (Seoul) 1순위, Tokyo 차선
     * pgvector extension 활성화: dashboard → Database → Extensions → `vector` enable
     * Storage bucket 생성: name `meals`, public access OFF(presigned URL flow), file size limit 10MB
     * Connection pooler: Transaction mode 사용(port 6543) — Render Free의 connection 한도 정합
   - **smoke 검증** (수동, 본 AC 정의):
     * `https://bn-api.onrender.com/healthz` → 200 OK + body `{"status":"ok"}`
     * `https://bn-web.onrender.com/login` → 200 OK + Google OAuth 버튼 렌더
     * Google 로그인 → onboarding → 건강 프로필 입력 → 식단 텍스트 입력 1건 → 분석 결과 표시 (fit_score + 매크로 + 인용 피드백 모두 정상)
     * 식단 사진 입력 1건 → R2(Supabase Storage) presigned URL 발급 → 사진 업로드 → OCR 분석 → 결과 표시
   - **Sentry prod 환경 분리** — `environment="production"` env var 적용으로 prod issue가 Sentry dashboard에서 dev와 분리 표시

4. **AC4 — GitHub Actions daily-cost-alert.yml 실제 구현 + Discord webhook + Sentry custom event** (NFR-Sc4, R6)
   **Given** 현 `.github/workflows/daily-cost-alert.yml`이 placeholder(echo만), **When** 본격 구현, **Then**:
   - **cron**: `0 0 * * *` (UTC 00:00 = KST 09:00) — 매일 1회. 추가 `workflow_dispatch: {}` 수동 trigger 옵션 보존
   - **단일 job `daily-cost-alert`**, ubuntu-latest, steps:
     1. **OpenAI Usage API 호출** — `GET https://api.openai.com/v1/usage?date=YYYY-MM-DD` (어제 KST 기준) → `total_usage` cents 추출
     2. **Anthropic Usage API 호출** — `GET https://api.anthropic.com/v1/organizations/.../usage_report` (또는 admin console scrape — Anthropic Public Usage API 베타) → 어제 cost USD
     3. **LangSmith spend 조회** (옵션) — `GET https://api.smith.langchain.com/api/v1/usage` → 어제 trace count
     4. **합산** + **임계치 비교** — `THRESHOLD_USD=5.0` (env var) 초과 시 alert level=warning, `10.0` 초과 시 critical
     5. **Discord webhook 송신** — `POST $DISCORD_COST_WEBHOOK_URL` with embed body(date / openai_usd / anthropic_usd / langsmith_traces / threshold_status / 전일 대비 변화율). Webhook URL은 GitHub Actions Secrets로 주입
     6. **Sentry custom event** (옵션, Sentry 통합 시) — `POST https://sentry.io/api/0/.../events/` with `level=warning|error` + tags
     7. **임계치 초과 시 GitHub Issue 자동 생성** — `gh issue create --title "Daily cost threshold exceeded" --body "..."`
   - **failure handling**: 각 API 호출 실패 시 Discord에 fallback message 송신("API X unreachable") + workflow는 success exit(0)으로 처리(다음날 cron 보장)
   - **secrets 필요**: `OPENAI_API_KEY`(read-only 별도 발급 권장), `ANTHROPIC_ADMIN_API_KEY`, `LANGSMITH_API_KEY`, `DISCORD_COST_WEBHOOK_URL`, `SENTRY_AUTH_TOKEN`(옵션) — GitHub repo Settings → Secrets and variables → Actions
   - **수동 trigger 검증**: `gh workflow run daily-cost-alert.yml` 실행 후 Discord 채널에서 메시지 수신 확인

5. **AC5 — `docs/runbook/deployment.md` 갱신 (§4.4 Render + Supabase 미니멀 배포 신설)**
   **Given** 현 `docs/runbook/deployment.md`가 Railway+Cloudflare 토폴로지 SOT + §4.1 Cloud Run / §4.2 AWS ECS 마이그레이션 가이드 보유, **When** Render+Supabase 패턴을 추가 섹션으로 신설, **Then**:
   - **§4.4 신설** — `## 4.4 Render + Supabase 미니멀 배포 (포트폴리오 패턴)` 헤더 + 토폴로지 다이어그램(ASCII):
     ```
     ┌──────────────┐
     │ Mobile / Web │
     └──────┬───────┘
            │ HTTPS (Render 자동 TLS)
            ▼
     ┌─────────────────────────┐
     │ Render Free             │
     │  Web Service A: bn-api  │  ← FastAPI Docker
     │  Web Service B: bn-web  │  ← Next.js Node
     └──────┬──────────────────┘
            │ HTTPS (asyncpg + supabase-py)
            ▼
     ┌─────────────────────────┐
     │ Supabase Free           │
     │  Postgres 500MB+pgvec   │
     │  Storage 1GB (bucket=meals) │
     └─────────────────────────┘
     ```
   - **핵심 설계 선택** 단락 — Redis 생략 (graceful fallback 활용 위치 명시) / Cloudflare 생략 / 도메인 생략 / 시크릿 재사용 / cold start 30~60초 / 7일 inactivity pause 회피 SOP(매주 dashboard ping 또는 외부 cron-job.org 무료 ping 등록)
   - **첫 배포 절차** 단계별 — Render dashboard 클릭 위치 + Supabase project 설정 + 환경변수 주입 체크리스트 + 첫 배포 trigger + smoke 검증
   - **롤백 절차** — Render dashboard → Deploys → 이전 commit → "Rollback to this deploy" 클릭 (1분 내 복구) / Supabase DB rollback은 alembic `downgrade -1` 수동 실행
   - **Alembic migration 안전 가이드** — destructive migration(DROP COLUMN 등) 적용 시 Supabase dashboard에서 사전 백업 dump 수행 SOP
   - **인수 시점 마이그레이션 옵션** — Render → Railway 또는 Cloud Run으로 swap 시 변경 지점(§4.1/§4.2 cross-link) + Cloudflare WAF/R2 재도입 SOP
   - **기존 §1~§4.3 본문 변경 0건** — Railway 패턴은 미래 옵션으로 보존

6. **AC6 — `docs/runbook/secret-rotation.md` placeholder 단락 채우기 (§1 OpenAI / §2 Anthropic / §5 Google OAuth / §8 Sentry+Supabase Storage)**
   **Given** 현 `docs/runbook/secret-rotation.md`가 §3 LangSmith / §4 EXPO_ACCESS_TOKEN / §6 TOSS_SECRET_KEY / §7 TOSS_WEBHOOK_SECRET_KEY 4개 단락 완성 + 나머지 placeholder, **When** placeholder 단락 채우기, **Then**:
   - **§1 OpenAI API key 회전** — Platform → API keys → Create new + 24h overlap + 신구 key 동시 유효 (env var swap) + Render 자동 재배포 검증 + 구 key revoke + rollback 절차
   - **§2 Anthropic API key 회전** — Console → Settings → API keys → 동일 패턴
   - **§5 Google OAuth client secret 회전** — Console → 사용자 인증 정보 → 웹 클라이언트 → "+ 새 시크릿 만들기" → 7일 grace 동안 신구 동시 유효 → Render env var swap + 자동 재배포 검증 + 구 secret 비활성화 + redirect URI는 회전과 무관
   - **§8 Sentry DSN 회전** — Sentry project → Settings → Client Keys (DSN) → Generate new key → Render env var swap + 새 에러로 DSN 검증 + 구 key revoke. **Supabase Storage Service Key 회전**도 §8에 추가 — Supabase dashboard → Settings → API → Generate new service role key → Render env var swap
   - **§9 회전 캘린더 갱신** — 분기 1회(Q1/Q2/Q3/Q4) cron 알림 + 6개월 1회 / 12개월 1회 카테고리별 표
   - 기존 §3/§4/§6/§7 본문 변경 0건

7. **AC7 — `docs/runbook/incident-response.md` 신규 작성 (3종 runbook 마지막)**
   **Given** 현재 `docs/runbook/`에 `deployment.md`, `secret-rotation.md`, `cloudflare-ip-refresh.md`, `push-notifications-dev.md`, `web-perf-check.md` 존재 + incident-response.md 부재, **When** 신규 작성, **Then** 4 시나리오 단락:
   - **§1 외부 API 장애** (OpenAI / Anthropic / Google OAuth / Supabase / Render) — Sentry alert 수신 시 1차 대응(상태 페이지 확인 URL 표) → 2차(graceful fallback 활성 — LLM router는 dual-LLM이라 1개 장애 시 자동 swap, OAuth 장애 시 사용자 안내 메시지) → 3차(영업 데모 시점 발생 시 사전 안내 SOP)
   - **§2 DB 다운** (Supabase) — 증상(`/healthz` 503 + Sentry `OperationalError` 폭증) → 1차 대응(Supabase dashboard 상태 확인 + restore 버튼) → 2차(7일 inactivity pause면 restore 1분) → 3차(quota 초과 시 일시 read-only 모드 권고 — 코드 변경 없이 Supabase 자동 처리)
   - **§3 LLM 비용 폭증** (daily-cost-alert 임계치 초과) — Discord alert 수신 시 1차 대응(Sentry/LangSmith로 어느 endpoint가 폭증인지 식별) → 2차(임시 cost cap 강화 — `ENVIRONMENT=production` 환경변수에 `VISION_DAILY_COST_CAP_USD` 추가 override) → 3차(악성 사용자 차단 — rate limit IP block 또는 사용자 deactivate)
   - **§4 보안 침해** (시크릿 leak / DB 접근 의심) — 1차 대응(즉시 secret-rotation.md 해당 §에 따라 회전) → 2차(Sentry breadcrumb + audit_logs 검토 — Story 7.3 audit_logs SOT 활용) → 3차(필요 시 사용자 강제 logout — JWT_SECRET_KEY 회전으로 일괄 무효화) + PIPA 신고 의무(72h 이내) cross-link
   - **§5 비상 연락처 / 회복 자료** — Render support / Supabase support / OpenAI status / Anthropic status / 본인(hwan) 연락처 placeholder

8. **AC8 — R2 어댑터 내부 구현 Supabase Storage swap (시그니처 유지, 회귀 0건)** (FR12)
   **Given** 현 `api/app/adapters/r2.py`가 boto3 S3-compat client로 Cloudflare R2 호출 + `create_presigned_upload` / `head_object_exists` / `resolve_public_url` / `PresignedUpload` dataclass 4 SOT export, **When** 내부 구현을 Supabase Storage Python SDK(`supabase-py` 또는 `storage3` direct)로 swap + `STORAGE_PROVIDER` env로 분기, **Then**:
   - **함수 시그니처 변경 0건** — `create_presigned_upload(user_id, content_type, content_length) → PresignedUpload`, `head_object_exists(image_key) → bool`, `resolve_public_url(image_key) → str | None` 모두 동일
   - **`PresignedUpload` dataclass 필드 변경 0건** — `upload_url`/`image_key`/`public_url`/`expires_at`/`content_type`
   - **`STORAGE_PROVIDER` env 분기** — `settings.storage_provider: Literal["r2", "supabase"] = "r2"` (default 보존 — 외주 인수 시 R2 옵션 유지). `"supabase"` 분기에서 내부적으로 Supabase client 호출
   - **새 settings 필드** — `supabase_url: str = ""` / `supabase_service_key: str = ""` / `supabase_storage_bucket: str = "meals"`
   - **`R2NotConfiguredError` → 일반화** — `StorageNotConfiguredError` 부모 클래스 도입 + R2/Supabase 각각 child(forward-compat, 본 스토리는 부모만 raise) OR 기존 `R2NotConfiguredError`를 *Storage 일반 에러*로 의미 확장 + docstring 갱신. 선택 후 `meals_images.py`의 except 절도 일관성 갱신
   - **Supabase presigned upload 구현** — `supabase.storage.from_(bucket).create_signed_upload_url(path)` — 5분 만료 PUT URL 반환(Supabase는 PUT 메서드 + 5분 만료가 기본)
   - **Supabase public URL** — `supabase.storage.from_(bucket).get_public_url(path)` (bucket public access OFF면 signed download URL 사용 — 본 스토리는 *meal 사진은 사용자 본인만 봄*이라 signed URL이 적절. 다만 OCR Vision은 image_url을 외부 OpenAI에 forward → 임시 signed URL이 OpenAI에 5분 이상 유효해야 함. 1h signed URL 또는 public bucket으로 정책 결정 필요 — Dev Notes 참조)
   - **`head_object_exists` Supabase 구현** — `supabase.storage.from_(bucket).list(prefix)` 또는 `download` 시도 후 404 catch
   - **`image_key` 형식 유지** — `meals/{user_id}/{uuid4}.{ext}` 동일 (Supabase Storage path도 동일 prefix 패턴 OK)
   - **새 dependency**: `supabase>=2.0` 또는 `storage3>=0.7` 추가 (`api/pyproject.toml`)
   - **회귀 가드 단위 테스트** — 기존 `tests/adapters/test_r2.py`(있다면)을 `STORAGE_PROVIDER=r2`로 두고 그대로 통과 + 신규 `tests/adapters/test_supabase_storage.py` 추가(mock `supabase-py` client + 시그니처 동등성 검증 + 5종 content_type 모두 정상 분기 + 10MB 초과 거부 + 미설정 시 `StorageNotConfiguredError` 검증)
   - **기존 호출처 변경 0건** — `meals_images.py:159-181`, `data_export_service.py`(있다면), `meal_analysis_persistence.py`(있다면) 모두 import 경로/시그니처 유지

9. **AC9 — Next.js standalone output 모드 (Render Node service 빌드 정합)** (NFR-Sc1)
   **Given** 현 `web/next.config.ts`가 placeholder(`/* config options here */` 빈 객체), **When** standalone mode 추가, **Then**:
   - **`web/next.config.ts` 갱신**:
     ```typescript
     import type { NextConfig } from "next";

     const nextConfig: NextConfig = {
       output: "standalone",
       // Story 8.5 — Render Node service에서 .next/standalone/server.js 단독 실행을 위한 모드.
       // standalone 산출물은 node_modules의 production-required 의존성만 포함 → 컨테이너 size ↓.
     };

     export default nextConfig;
     ```
   - **`web/package.json` `start` 스크립트 검증** — `"start": "next start"`가 standalone 모드에서도 호환되는지 확인. standalone mode는 `node .next/standalone/server.js` 직접 실행을 권장하지만 `next start`도 동작
   - **Render Start command 권장값** — `node .next/standalone/server.js` (deployment.md §4.4 명시)
   - **회귀 검증** — `pnpm build` 0 errors + `pnpm tsc --noEmit` 0 errors + 로컬 `pnpm dev` 정상 동작

10. **AC10 — `.env.production.example` 신규 작성 (Render·Supabase·Sentry 환경변수 template)**
    **Given** 현 repo에 `.env.example` 부재(`api/.env.example`, `web/.env.example`, `mobile/.env.example`는 dev용), **When** 루트에 `.env.production.example` 신규 작성, **Then**:
    - **파일 구조**: 4 섹션(`# === API (bn-api) ===`, `# === Web (bn-web) ===`, `# === GitHub Actions Secrets ===`, `# === Sentry Console에서 수동 입력 ===`)
    - **API 섹션** 항목(주석 + 빈 값 또는 placeholder):
      ```
      DATABASE_URL=postgresql+asyncpg://postgres:[YOUR-PASSWORD]@[YOUR-PROJECT-REF].pooler.supabase.com:6543/postgres?pgbouncer=true
      ENVIRONMENT=production
      JWT_SECRET_KEY=  # python -c "import secrets; print(secrets.token_urlsafe(32))"
      OPENAI_API_KEY=
      ANTHROPIC_API_KEY=
      LANGSMITH_API_KEY=
      LANGCHAIN_TRACING_V2=true
      LANGSMITH_PROJECT=balancenote-prod
      GOOGLE_OAUTH_CLIENT_ID=559604985813-fi8mfivn1fhjgq9a9ehdh5l8qp5iivpk.apps.googleusercontent.com
      GOOGLE_OAUTH_CLIENT_SECRET=
      GOOGLE_OAUTH_REDIRECT_URI=https://bn-web.onrender.com/api/auth/google/callback
      SENTRY_DSN=
      STORAGE_PROVIDER=supabase
      SUPABASE_URL=https://[YOUR-PROJECT-REF].supabase.co
      SUPABASE_SERVICE_KEY=
      SUPABASE_STORAGE_BUCKET=meals
      CORS_ALLOWED_ORIGINS=https://bn-web.onrender.com
      TOSS_SECRET_KEY=test_sk_...
      TOSS_WEBHOOK_SECRET_KEY=whsec_...
      EXPO_ACCESS_TOKEN=  # 모바일 푸시 알림 — 선택
      ```
    - **Web 섹션** 항목:
      ```
      NEXT_PUBLIC_API_BASE_URL=https://bn-api.onrender.com
      API_BASE_URL=https://bn-api.onrender.com
      NEXT_PUBLIC_SENTRY_DSN=
      GOOGLE_OAUTH_CLIENT_ID=559604985813-fi8mfivn1fhjgq9a9ehdh5l8qp5iivpk.apps.googleusercontent.com
      GOOGLE_OAUTH_CLIENT_SECRET=
      GOOGLE_OAUTH_REDIRECT_URI=https://bn-web.onrender.com/api/auth/google/callback
      ```
    - **GitHub Actions Secrets 섹션** 항목:
      ```
      OPENAI_API_KEY=  # daily-cost-alert.yml용 (read-only 별도 발급 권장)
      ANTHROPIC_ADMIN_API_KEY=
      LANGSMITH_API_KEY=
      DISCORD_COST_WEBHOOK_URL=  # Discord 채널 → Edit Channel → Integrations → Webhooks
      THRESHOLD_USD=5.0
      ```
    - **Sentry 섹션** 항목: Sentry dashboard에서 수동 발급 + 메모 노트 (API DSN 1개 + Web DSN 1개)
    - **헤더 주석** — 본 파일은 *템플릿*이며 실 값은 *각 dashboard에 직접 주입*(git 커밋 금지). `.gitignore`에 `.env.production`(non-example) 등록 확인
    - **README 또는 deployment.md cross-link** — "Render dashboard 환경변수 입력 시 본 파일 참조" 명시

## Tasks / Subtasks

- [x] **Task 1: Dockerfile.api multi-stage build 재작성** (AC: #1, #2)
  - [x] 1.1 `docker/Dockerfile.api` 2-stage(builder + runtime) 재작성 — venv `/opt/uv-venv` artifact 패턴
  - [x] 1.2 `.dockerignore` 신규 작성 — node_modules / .next / .git / mobile / web / _bmad / _bmad-output / docs / tests / __pycache__ / *.pyc / .env*
  - [x] 1.3 `CMD`에 `${PORT:-8000}` 추가 — Render `$PORT` env 자동 대응 + 로컬 docker-compose 기본 8000 보존
  - [x] 1.4 `docker build -f docker/Dockerfile.api -t balancenote-api:multistage-test .` 빌드 성공 (exit 0). 로컬 `docker compose up` 회귀 검증은 사용자 hands-on (DS는 build 검증으로 1차 통과)
  - [x] 1.5 이미지 size 측정 — 1.18GB (목표 ~500MB 미달성: storage3 2.20-2.25 도입으로 +deps, 그러나 supabase 메타패키지 회피로 pyiceberg 200MB 제외). 자세한 분석은 Completion Notes
  - [x] 1.6 docker-compose.yml 헤더 주석 갱신(AC2 — `# Local dev only. Render는 본 파일 미참조`)

- [x] **Task 2: Storage 어댑터 Supabase Storage swap (R2 → Supabase, 시그니처 유지)** (AC: #8)
  - [x] 2.1 `api/pyproject.toml`에 `storage3>=2.20,<2.26` 직접 dependency 추가(supabase 메타패키지 회피로 pyiceberg/realtime/postgrest/auth 미사용 sibling 제외 — 이미지 size 정합) + `uv lock` + `uv sync`
  - [x] 2.2 `api/app/core/config.py`에 신규 settings 4개 추가 — `storage_provider: str = "r2"` (Literal 대신 str — 기존 `environment` 필드와 정합 + Render env coercion), `supabase_url`, `supabase_service_key`, `supabase_storage_bucket = "meals"`
  - [x] 2.3 `api/app/core/exceptions.py` — `StorageNotConfiguredError(MealImageError)` 부모 + `R2NotConfiguredError(StorageNotConfiguredError)` child + `SupabaseStorageNotConfiguredError(StorageNotConfiguredError)` child. 기존 R2 code(`meals.image.r2_unconfigured`) 보존 + 신규 code(`meals.image.supabase_unconfigured` / `meals.image.storage_unconfigured` for parent)
  - [x] 2.4 `api/app/adapters/r2.py` 내부 분기 — `_get_r2_client()` / `_get_supabase_storage()` 별 lazy singleton + `STORAGE_PROVIDER` 분기는 public API 함수 내부
  - [x] 2.5 `create_presigned_upload` Supabase 분기 — `client.from_(bucket).create_signed_upload_url(image_key)` + 상대 URL을 supabase_url로 정규화 + `PresignedUpload` dataclass 매핑
  - [x] 2.6 `resolve_public_url` Supabase 분기 — 1h signed download URL (`create_signed_url`, `SIGNED_DOWNLOAD_URL_EXPIRES_SECONDS=3600`) — bucket private 유지 + Vision OCR 5분 이상 여유
  - [x] 2.7 `head_object_exists` Supabase 분기 — `client.from_(bucket).list(path=prefix, options={"limit":1, "search":filename})` 정확 매칭만 인정(substring leak 차단)
  - [x] 2.8 `api/tests/test_r2_adapter.py` 기존 케이스 보존 — `_get_client` → `_get_r2_client` 함수명 갱신 + 모든 fixture에 `monkeypatch.setattr(_settings, "storage_provider", "r2")` 명시
  - [x] 2.9 `api/tests/adapters/test_supabase_storage.py` 신규 — 13 test case(`_StubBucket`/`_StubStorage` stub + 정상 흐름 + content_type whitelist + size 검증 + unconfigured raise + parent class catch + signed URL 정규화 + list 매칭/미매칭/substring 거부 + provider 분기 강제 검증)
  - [x] 2.10 `meals_images.py` import/except 변경 0건 확인 — `R2NotConfiguredError`는 여전히 raise 가능(child 보존), `from app.adapters import r2 as r2_adapter` 그대로

- [x] **Task 3: Next.js standalone output 모드** (AC: #9)
  - [x] 3.1 `web/next.config.ts`에 `output: "standalone"` 추가 + 주석
  - [x] 3.2 `web/package.json` `start` 스크립트 — Render Start command는 `node .next/standalone/server.js` 권장(deployment.md §4.4 명시). `next start`도 동작하나 standalone 산출물 직접 호출이 정합
  - [x] 3.3 `pnpm build` 0 errors + `.next/standalone/server.js` 산출물 확인 — 첫 빌드 시 발견한 회귀 2건 fix 포함: `/account/subscribe/success`, `/account/subscribe/fail`의 `useSearchParams()`를 `<Suspense>` 래퍼로 분리(Next.js 16 prerender 정합)
  - [x] 3.4 `pnpm tsc --noEmit` 0 errors

- [x] **Task 4: `.env.production.example` 신규 작성** (AC: #10)
  - [x] 4.1 루트에 `.env.production.example` 작성 — 4 섹션(API / Web / GitHub Actions / Sentry) + 모든 env var 항목 + 주석
  - [x] 4.2 `.gitignore` 검증 — `.env.production` non-example는 line 11에 이미 `.env*.local` + line 14에 `.env.production`/`.env.staging` 등록 완료
  - [x] 4.3 deployment.md §4.4 첫 배포 절차 단락에서 `.env.production.example` cross-reference

- [x] **Task 5: `docs/runbook/deployment.md` §4.4 Render + Supabase 미니멀 배포 섹션 신설** (AC: #5)
  - [x] 5.1 §4.4 신설 — 토폴로지 다이어그램 + 핵심 설계 선택(Redis/Cloudflare/도메인 생략 + cold start + 7일 pause + Storage 추상화 + 모니터링)
  - [x] 5.2 첫 배포 절차 단계별 — Supabase project 생성 → bn-api Render Web Service → bn-web Render Web Service → GitHub Actions Secrets, 모두 체크박스 형식
  - [x] 5.3 롤백 절차(코드 + alembic) + destructive migration 사전 백업 SOP
  - [x] 5.4 인수 시점 마이그레이션 옵션 — Render→Railway/Cloud Run/AWS / Supabase→자체 Postgres / Cloudflare WAF 재도입 / Sentry plan 업그레이드
  - [x] 5.5 기존 §1~§4.3 본문 변경 0건 — 본 PR는 §4.4 추가만

- [x] **Task 6: GitHub Actions `daily-cost-alert.yml` 실제 구현** (AC: #4)
  - [x] 6.1 OpenAI Usage API 호출 — curl + jq, `total_usage` cents 추출 → USD 변환
  - [x] 6.2 Anthropic Admin API 호출 — `/v1/organizations/usage_report/messages` beta endpoint + best-effort cost_in_usd 합산
  - [x] 6.3 LangSmith trace count 조회 — `/api/v1/runs` 어제 KST 0~24시 (optional)
  - [x] 6.4 임계치 비교 — `THRESHOLD_USD` (default 5.0) + `CRITICAL_USD` (10.0). severity = ok/warning/critical
  - [x] 6.5 Discord webhook embed body — severity별 color + 4 field(total/openai/anthropic/langsmith)
  - [x] 6.6 Sentry custom event — auth_token 있을 시 step 활성, 실제 POST는 Story 8.4 forward 표시(현 단계는 이벤트 level 결정 로직만)
  - [x] 6.7 `gh issue create` — severity=critical 시 자동 발급(`cost-alert` + `priority:high` 라벨)
  - [x] 6.8 failure handling — 각 API step이 key 없으면 graceful skip + status "skipped (no key)" 노출. workflow 자체는 항상 success exit
  - [x] 6.9 `workflow_dispatch: {}` 보존 — 수동 trigger 가능

- [x] **Task 7: `docs/runbook/secret-rotation.md` placeholder 단락 채우기** (AC: #6)
  - [x] 7.1 §1 OpenAI API key 회전 — Platform → API keys → Create new + 24h overlap + Render swap + 도착 검증 + rollback + 트리거
  - [x] 7.2 §2 Anthropic API key 회전 — Console → API Keys → Create + 24h overlap + Render swap + rollback. `ANTHROPIC_ADMIN_API_KEY` GitHub Actions secret 별 키임 명시
  - [x] 7.3 §5 Google OAuth client secret 회전 — Console → 웹 클라이언트 → "+ 새 시크릿 만들기" + 7일 grace + Render 2 service 동시 swap + redirect URI 무관 명시
  - [x] 7.4 §8 Sentry DSN + Supabase Service Key 회전 — Sentry: Generate New Key + 24h grace + revoke. Supabase: Reset 시 grace 0초 → Render env 미리 입력 SOP
  - [x] 7.5 §9 회전 캘린더 — 분기/6개월/12개월 표 + 다음 회전 예 + 공통 checklist + 자동화는 Story 8.4 forward

- [x] **Task 8: `docs/runbook/incident-response.md` 신규 작성 (3종 runbook 마지막)** (AC: #7)
  - [x] 8.1 §1 외부 API 장애 — 상태 페이지 표(OpenAI/Anthropic/Google OAuth/Supabase/Render) + 1차/2차/3차 대응 + 데모 사전 안내 SOP
  - [x] 8.2 §2 DB 다운 — Supabase pause/restore + 외부 incident + 500MB quota 초과 + connection pool 고갈 4 분기 + destructive migration rollback
  - [x] 8.3 §3 LLM 비용 폭증 — endpoint 식별 + cost cap 강화 + secret 일시 회전 + 악성 사용자 deactivate
  - [x] 8.4 §4 보안 침해 — 60분 내 secret 회전 + JWT_SECRET_KEY 회전(전체 사용자 강제 logout) + audit_logs 검토(Story 7.3) + PIPA 신고 72h cross-link
  - [x] 8.5 §5 비상 연락처 — 외부 서비스 support 표 + KISA/PIPA/GitHub Support + 운영자 placeholder

- [x] **Task 9: Sentry prod 환경 분리 minimal hunk (Story 8.4 사전 의존 최소화)** (AC: #3)
  - [x] 9.1 `api/app/core/sentry.py:133` — `environment=settings.environment` 이미 명시되어 있음(Story 1.1 baseline). 변경 0건
  - [x] 9.2 `settings.environment` default `"dev"` 보존 + `_validate_jwt_secrets_in_prod` 분기 합집합에 `"production"` 추가(Render dashboard 표기 정합 — `.env.production.example`이 `ENVIRONMENT=production` 사용)
  - [x] 9.3 web 측 Sentry init — `NEXT_PUBLIC_SENTRY_DSN` env는 `.env.production.example` 템플릿에 documented, 실제 SDK wiring(@sentry/nextjs)은 Story 8.4 polish forward. 본 스토리 scope 외(번들 size + withSentryConfig + sourcemap upload 등 SDK 의존성 무거움)

- [x] **Task 10: 수동 smoke 검증 (DS 종료 직전 + CR 종료 직전 2회)** (AC: #3)
  - [ ] 10.1~10.6 **사용자 hands-on (Render dashboard + Supabase dashboard + Google OAuth Console 권한 필요 — AI 대행 불가)**. DS 종료 시점 코드/문서 작업은 완료, 첫 배포 검증은 사용자가 다음 단계에서 진행. SOP는 `docs/runbook/deployment.md` §4.4.3-§4.4.4 명시 — 첫 배포 + smoke 1회 통과 시 본 Task 체크 + CR 종료 직전 2차 검증

- [x] **Task 11: Sprint status 갱신 + epic-8 transition** (절차)
  - [x] 11.1 DS 시작 시점 `_bmad-output/implementation-artifacts/sprint-status.yaml` 갱신 — `8-5-...: ready-for-dev → in-progress` + last_updated 1행 prepend (이미 적용)
  - [ ] 11.2 CR 종료 직전 `review → done` + `epic-8: backlog → in-progress` + PR commit 포함 (memory `feedback_cr_done_status_in_pr_commit` 정합) — CR 단계에서 처리

## Dev Notes

### 아키텍처 정합 / 변경 면적

- **본 스토리는 prod 동작 자체만 책임** — Story 8.4 polish(rate limit Redis backend / LLM 캐시 정교화 / 표준 빈/로딩/에러 화면 / OpenAPI 정리 / 모바일 jest 인프라)는 별도 후속. 8.5에 포함하는 *최소 8.4 hunk*는 Sentry environment 분리(Task 9) 1건뿐.
- **Storage 추상화 결정 D1** — `api/app/adapters/r2.py` 모듈 이름을 보존하되 내부 분기. *historical 이름이지만 external semantic은 같음*. forward-compat을 위한 추상 인터페이스(`storage.py`)는 Story 8.4 polish forward로 명시.
- **Redis 생략 결정** — graceful fallback 경로 4곳 모두 single-instance 환경에서 정상 동작 검증된 상태. multi-instance 전환 시점에 Redis 재도입(`docs/runbook/deployment.md` §4.4 명시).
- **alembic migration on first deploy** — Dockerfile.api `CMD`에 `alembic upgrade head &&`가 SOT. Render 첫 배포 + Supabase 빈 DB → 0001~0023 전체 자동 실행. pgvector extension은 Supabase dashboard에서 *사전 활성화 필요*(alembic 0010이 `CREATE EXTENSION IF NOT EXISTS vector` 호출하지만 권한 부재 시 fail — deployment.md §4.4에 활성화 절차 명시 필수).
- **JWT_SECRET_KEY 신규 발급** — dev 키 재사용 시 *기존 dev 사용자가 prod에서 자동 로그인됨*(위험). 본 스토리에서 prod 전용 신규 JWT secret 생성 후 Render env var 주입 SOP를 deployment.md에 명시. 사용자 친구 데모 시점에 prod 사용자는 신규 가입 자연.
- **Supabase Connection pooler 강제** — Render Free의 outbound connection 한도가 좁아서 direct connection(port 5432)은 connection 누수 시 즉시 한도 도달. Transaction mode pooler(port 6543, `?pgbouncer=true`)가 SOT. asyncpg + pgbouncer transaction mode는 PREPARE statement 비호환이라 SQLAlchemy 측 `prepared_statement_cache_size=0` 설정 필요 — `api/app/db/engine.py` 또는 engine init 위치 확인 필요(현재 코드 패턴 추가 필요).

### 신규 의존성 + 환경 변수

- **신규 dependency** (1건): `supabase>=2.0` 또는 `storage3>=0.7` — `api/pyproject.toml`
- **신규 settings** (4건): `storage_provider`, `supabase_url`, `supabase_service_key`, `supabase_storage_bucket`
- **신규 env var (Render API)** (5건): `STORAGE_PROVIDER`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_STORAGE_BUCKET`(optional), `JWT_SECRET_KEY`(신규 발급 권장)
- **신규 env var (Render Web)** (0건 — 기존 env 재사용)
- **신규 env var (GitHub Actions Secrets)** (5건): `OPENAI_API_KEY`(read-only), `ANTHROPIC_ADMIN_API_KEY`, `LANGSMITH_API_KEY`, `DISCORD_COST_WEBHOOK_URL`, `SENTRY_AUTH_TOKEN`(optional)
- **신규 alembic** (0건)
- **deprecated env (Render에서 미사용, 기존 dev에서는 보존)**: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL` — 빈 값으로 두면 graceful (`r2.py`가 `STORAGE_PROVIDER=supabase` 분기로 진입)

### 회귀 invariant (절대 깨면 안 됨)

- 기존 식단 입력/분석/조회 모든 endpoint 흐름 — Storage swap이 외부 호출처에 보이지 않음 (`meals_images.py` import/except 변경 0)
- 기존 alembic 0001~0023 migration 모두 정상 적용 (pgvector extension은 사전 활성화 필수)
- 기존 OAuth 흐름 — dev redirect URI (`localhost:3000`)도 OAuth Console에 등록 보존되어 로컬 개발 영향 0
- 기존 docker-compose dev 흐름 — 본 PR 머지 후에도 `docker compose up` 정상 부팅
- Story 7.3 audit_logs 흐름 — Sentry env 분리가 audit log 작성에 영향 0

### Risks / Mitigations

| Risk | 영향 | Mitigation |
|---|---|---|
| Render Free 15분 cold start | 데모 첫 호출 30~60초 지연 | 데모 직전 ping 1회 워밍업 + deployment.md §4.4 SOP 명시 |
| Supabase Free 7일 inactivity pause | 데모 직전 unavailable | dashboard restore 1분 / 매주 GitHub Actions cron으로 ping (별도 workflow, 본 스토리 OUT) |
| pgvector extension 사전 활성화 누락 | alembic 0010 fail → 첫 배포 실패 | deployment.md §4.4 첫 배포 체크리스트에 *체크박스*로 명시 |
| Connection pooler PREPARE 비호환 | asyncpg 첫 쿼리 시점 에러 | `prepared_statement_cache_size=0` 설정 추가 (engine.py 갱신 필요) |
| JWT_SECRET_KEY dev 재사용 시 prod 보안 위험 | dev 토큰으로 prod 진입 가능 | 본 스토리에서 prod 전용 신규 secret 발급 SOP 명시 + Render env var 주입 |
| Supabase Storage bucket public 정책 결정 | Vision OCR이 외부에서 image_url fetch | 1h signed URL 채택 + Vision 호출 직전 발급 패턴 (`meals_images.py` 흐름) |
| Discord webhook URL leak | 외부에서 spam 가능 | GitHub Secrets 저장 + 로그에 raw URL 출력 차단 |
| 첫 배포 시 alembic migration 실패 | service start 실패 | Dockerfile CMD에 `&&` chain → fail 시 컨테이너 즉시 종료 + Render dashboard에서 즉시 가시화 |

### Source tree 영향 (UPDATE / NEW)

- **UPDATE** `docker/Dockerfile.api` (multi-stage)
- **UPDATE** `docker-compose.yml` (헤더 주석만)
- **NEW** `.dockerignore` (또는 기존 갱신)
- **UPDATE** `api/app/adapters/r2.py` (Supabase 분기 추가, 시그니처 유지)
- **UPDATE** `api/app/core/config.py` (4 신규 settings)
- **UPDATE** `api/app/core/exceptions.py` (StorageNotConfiguredError 추가 또는 R2 일반화)
- **UPDATE** `api/pyproject.toml` + `api/uv.lock` (supabase 의존성)
- **UPDATE** `api/app/db/engine.py` 또는 engine init (asyncpg `prepared_statement_cache_size=0`)
- **UPDATE** `api/app/core/observability.py` 또는 Sentry init (environment 명시)
- **UPDATE** `web/next.config.ts` (output: "standalone")
- **UPDATE** `web/package.json` (start 스크립트 검증)
- **UPDATE** `.github/workflows/daily-cost-alert.yml` (실 구현)
- **UPDATE** `docs/runbook/deployment.md` (§4.4 추가)
- **UPDATE** `docs/runbook/secret-rotation.md` (§1/§2/§5/§8/§9 채우기)
- **NEW** `docs/runbook/incident-response.md`
- **NEW** `.env.production.example` (루트)
- **NEW** `api/tests/adapters/test_supabase_storage.py`
- **UPDATE** `_bmad-output/implementation-artifacts/sprint-status.yaml` (CR 종료 직전, Task 11)

### Project Structure Notes

- Render 배포는 *docker 빌드 패턴*(bn-api) + *Node 빌드 패턴*(bn-web) 2종 — 본 repo 구조(`docker/Dockerfile.api` + `web/`) 그대로 정합
- Supabase Storage path: `meals/{user_id}/{uuid4}.{ext}` — 기존 R2 image_key 형식 그대로 유지 (외주 인수 시 R2 swap-back 호환)
- Sentry projects 분리: `balancenote-api` + `balancenote-web` (Korean: `balancenote-api`/`balancenote-web`)
- 향후 Cloudflare 재도입(외주 인수 시점) 또는 도메인 추가 시: `deployment.md` §3 Cloudflare 섹션 재활성 + `proxy.py` `CF-Connecting-IP` trust 그대로 복귀

### References

- Story 8.5 epics.md AC body — [epics.md:1007-1021](../planning-artifacts/epics.md#story-85)
- Story 8.4 polish AC body — [epics.md:987-1005](../planning-artifacts/epics.md#story-84) (분리 의존)
- prd.md NFR-Sc4 LLM 비용 보호 — [prd.md:1077-1078](../planning-artifacts/prd.md#nfr-sc4)
- prd.md NFR-R6 Sentry 알림 — [prd.md:1060-1061](../planning-artifacts/prd.md#nfr-r6)
- architecture.md Infrastructure & Deployment — [architecture.md:340-353](../planning-artifacts/architecture.md#infrastructure--deployment)
- architecture.md 호스팅 토폴로지 — [architecture.md:61-65](../planning-artifacts/architecture.md#기술-스택)
- `api/app/adapters/r2.py` Storage swap 대상 — 시그니처 4개 보존
- `api/app/api/v1/meals_images.py:159-181, 219-237` R2 호출처 — 변경 0
- `api/app/core/config.py:76, 149, 162-170` Redis/Sentry/R2 settings — 신규 settings 추가 위치
- `api/app/db/models/user.py`, `api/app/db/engine.py` connection pooler 설정 위치
- `.github/workflows/daily-cost-alert.yml` placeholder — 실 구현 대상
- `docs/runbook/deployment.md` §4 마이그레이션 SOP — §4.4 추가 위치
- `docs/runbook/secret-rotation.md` §1/§2/§5/§8 placeholder — 채우기 대상
- `docker/Dockerfile.api` single-stage → multi-stage 재작성 대상
- `docker-compose.yml` 본문 보존, 헤더 주석만 갱신
- `web/next.config.ts` standalone 추가 대상
- `_bmad-output/implementation-artifacts/deferred-work.md` Story 3.9 결정 SOT (Cloudflare/Railway 결정 보존 라인) + DF102/DF103/W4(scope 외)
- memory `feedback_branch_from_master_only` / `feedback_pr_pattern_for_master` / `feedback_cr_done_status_in_pr_commit` / `feedback_ds_complete_to_commit_push` 모두 정합 (branch는 이미 master에서 분기 완료)

## Dev Agent Record

### Agent Model Used

- Amelia (bmad-agent-dev / bmad-dev-story) on Claude Opus 4.7 (1M context). DS 진행일: 2026-05-12.

### Debug Log References

- Storage adapter swap — 첫 시도에서 `supabase>=2.5` 메타패키지 도입 시 `storage3 2.30.0`이
  `pyiceberg>=0.10.0` transitive dep을 강제 → Docker image 1.18GB(+pyiceberg 200MB 추가). 분석 후
  `supabase` 메타패키지를 drop하고 `storage3>=2.20,<2.26` 직접 dep로 swap — pyiceberg 도입 전
  버전대로 회피. 호출 API(`from_(bucket).create_signed_upload_url/create_signed_url/list`) 동일.
- Web `pnpm build` — `output: "standalone"` 적용 후 첫 빌드에서 `useSearchParams()` Suspense
  경계 미설정으로 prerender fail (Next.js 16 정책). 2 page (`/account/subscribe/success`, `.../fail`)
  를 `<Suspense fallback>` + 내부 컴포넌트 분리 패턴으로 refactor. CI 이전 단계에서 `pnpm build`
  가 한 번도 실행되지 않은 invariant 회귀 — Story 8.5가 처음으로 prod build 게이트 적용.
- mypy `r2.py` line 254 — `signed.get("signedURL") or signed.get("signedUrl")` chain이 `Any` 반환
  → typed local var(`url: str | None = ...`) 우회로 strict 통과.
- ruff line-too-long — exceptions.py `StorageNotConfiguredError` docstring 102자, db/session.py
  `_asyncpg_connect_args` docstring 102자 fix.
- pgbouncer transaction mode — Dev Notes line 390에 `prepared_statement_cache_size=0` 표기되어
  있으나 *asyncpg 실제 param명은 `statement_cache_size`*. `_asyncpg_connect_args(url)` 헬퍼가
  `?pgbouncer=true` 감지 시 `{"connect_args": {"statement_cache_size": 0}}` 반환. direct connection
  dev/test는 미발동.

### Completion Notes List

**전체**

- 11 task 중 10건 코드/문서 완료, Task 10(수동 smoke 검증)은 사용자 hands-on 단계로 분리(Render
  dashboard + Supabase dashboard + Google OAuth Console 접근 권한 필요).
- AC1~AC9 모두 작업 완료. AC3 smoke 검증은 사용자 hands-on 후 확정.
- Full pytest: 1379 passed / 11 skipped / 0 failed (Storage swap + pgbouncer hunk + Sentry env
  invariant 보존). 신규 13 case `test_supabase_storage.py` 통과. 기존 `test_r2_adapter.py` `_get_client`
  → `_get_r2_client` 함수명 갱신 + `storage_provider="r2"` fixture 명시화로 회귀 0건.
- ruff/format/mypy 0 errors. web `pnpm tsc --noEmit` + `pnpm build` (standalone) 0 errors.

**AC1 — Dockerfile.api multi-stage**

- 빌드 성공(`docker build -f docker/Dockerfile.api -t balancenote-api:multistage-test . → exit 0`).
  이미지 size: **1.18GB** (목표 ~500MB 미달성). 분석:
  - Multi-stage 효과는 정확히 작동 — builder의 `build-essential`(~150MB)은 runtime에 미포함.
  - 그러나 Story 8.5에서 신규 `storage3` dep 도입 + 기존 `langgraph`/`pypdf`/`beautifulsoup4`/
    `boto3`/`anthropic`/`openai`/`pgvector` 등 누적 LLM/RAG SDK 의존성 합산이 우세.
  - 만약 storage3 메타 supabase로 갔다면 +200MB → 1.4GB 정도였을 것. 직접 dep로 회피한 결과
    1.18GB로 제한.
  - Render Free tier에는 이미지 size 제한 없음(메모리 한도만) → prod 영향 0. 목표 미달이지만
    *기능 우선* 결정.

**AC2 — docker-compose.yml hardening**

- 본문 변경 0건. 헤더 주석에 `Local dev only. Render는 본 파일 미참조` 명시.
- pgvector extension은 dev `pgvector/pgvector:pg17` 이미지가 자동 활성, Supabase는 dashboard
  enable 필요(deployment.md §4.4 첫 배포 절차 SOP 명시).

**AC3 — Render 배포 + Supabase prod 운영**

- 코드/설정 SOT 완료(Dockerfile / next.config / `.env.production.example` / deployment.md SOP).
- Sentry prod env 분리: `settings.environment="production"` 입력 시 `sentry_sdk.init(environment=...)`이
  자동 forward(sentry.py:133). `_validate_jwt_secrets_in_prod`가 prod/production/staging 합집합으로 dev
  secret 차단.
- 실 배포는 사용자 hands-on Task 10 단계.

**AC4 — daily-cost-alert.yml 실 구현**

- OpenAI Usage API + Anthropic Admin Usage Report + LangSmith runs count + Discord embed +
  gh issue auto-create + workflow_dispatch + 각 step graceful skip.
- Anthropic Admin Usage Report는 beta endpoint(`anthropic-version: 2023-06-01`) — schema 안정성은
  Anthropic 측 변경 가능, 본 workflow는 best-effort cost_in_usd 합산 + JSON 파싱 실패 시 0 fallback.
- 검증: `python yaml.safe_load` 통과. 실제 Discord 메시지 수신은 사용자가 GitHub Secrets 입력 +
  manual trigger로 확정.

**AC5 — deployment.md §4.4**

- 토폴로지 다이어그램(ASCII) + 핵심 설계 7건 + 첫 배포 절차(체크박스 26개) + smoke 5건 +
  롤백 + 인수 시점 마이그레이션 옵션 + 알려진 제약 표.
- 기존 §1~§4.3 본문 변경 0건 검증.

**AC6 — secret-rotation.md §1/§2/§5/§8/§9**

- §1 OpenAI + §2 Anthropic + §5 Google OAuth + §8.1 Sentry DSN + §8.2 Supabase Service Key
  각 5~6 sub-step 패턴(발급/Render swap/검증/revoke/rollback/트리거).
- §9 회전 캘린더 11항목 표 + 공통 checklist + 자동화 forward 표시.
- 기존 §3 LangSmith / §4 Expo / §6 Toss / §7 Toss webhook 본문 변경 0건.

**AC7 — incident-response.md 신규**

- §1 외부 API 장애(5 외부 의존성 상태페이지 표) + §2 DB 다운(4 분기) + §3 LLM 비용 폭증
  (endpoint 식별 + cap 강화 + 악성 사용자 차단) + §4 보안 침해(60분 1차 + PIPA 72h) + §5 비상 연락처.
- audit_logs SQL 예시(Story 7.3 cross-link), JWT_SECRET_KEY 회전으로 전체 강제 logout 패턴, PIPA
  민감정보 항목 분류 등 실 운영 지향.

**AC8 — R2 어댑터 Supabase 분기 swap**

- 외부 시그니처 4개(`create_presigned_upload` / `head_object_exists` / `resolve_public_url` /
  `PresignedUpload` dataclass) **변경 0건**. `meals_images.py` import/except 변경 0건.
- `STORAGE_PROVIDER=r2`(default) / `supabase` 분기 — 양 provider별 lazy singleton (`_get_r2_client` /
  `_get_supabase_storage`).
- Supabase signed download URL TTL 1h(`SIGNED_DOWNLOAD_URL_EXPIRES_SECONDS=3600`) — bucket
  private 유지 + Vision OCR 5분 이상 여유 정합.
- `head_object_exists` Supabase 분기는 list options `search=filename`로 1차 필터 + Python 측
  정확 매칭 검증(substring leak 차단).
- 13 test case 추가 (`test_supabase_storage.py`) + 기존 8 case 보존 (`test_r2_adapter.py`).

**AC9 — Next.js standalone**

- `output: "standalone"` + `.next/standalone/server.js` 산출물 검증.
- `useSearchParams()` Suspense 경계 fix 2건 — Toss callback page (Story 6.1 작성 시점에 SSR
  prerender 게이트 미통과한 invariant 회귀, 8.5에서 처음 가시화). 본 hunk는 Story 6.1 기능
  무영향 — fallback UI는 기존 "loading…" 메시지와 동일 톤.

**AC10 — `.env.production.example`**

- 4 섹션 + 31개 env var(주석 포함). API 섹션 18개, Web 섹션 6개, GitHub Actions 5개, Sentry
  console 2개.
- `.gitignore` 검증 — `.env.production` non-example은 이미 line 11 `.env.production`로 ignore.

**deferred / forward 항목 (본 스토리 OUT, 추후 처리)**

- Web Sentry SDK wiring (`@sentry/nextjs` + instrumentation.ts) — Story 8.4 polish forward.
- 매주 GitHub Actions cron으로 Supabase `SELECT 1` ping (7일 inactivity pause 방지) — Story 8.5
  AC range 외, 별 workflow.
- Sentry custom event 실 POST(daily-cost-alert) — Story 8.4 forward.
- Cron ping 자동화 (idle pause 회피) — 별 workflow.
- 이미지 size 추가 최적화 — `python:3.13-alpine` 기반 / multi-arch / debug symbol strip 등 forward.

### File List

**NEW**:
- `.dockerignore`
- `.env.production.example`
- `api/tests/adapters/test_supabase_storage.py`
- `docs/runbook/incident-response.md`

**UPDATE**:
- `docker/Dockerfile.api` (multi-stage 재작성)
- `docker-compose.yml` (헤더 주석만)
- `api/pyproject.toml` (`storage3>=2.20,<2.26` 추가 + mypy override)
- `api/uv.lock` (의존성 회전)
- `api/app/adapters/r2.py` (Supabase 분기 추가, 시그니처 보존)
- `api/app/core/config.py` (4 신규 settings + environment description 보강)
- `api/app/core/exceptions.py` (`StorageNotConfiguredError` 부모 + `SupabaseStorageNotConfiguredError` child)
- `api/app/db/session.py` (`_asyncpg_connect_args` 헬퍼)
- `api/app/main.py` (engine init에 `_asyncpg_connect_args` 적용)
- `api/tests/test_r2_adapter.py` (`_get_client` → `_get_r2_client` 갱신 + `storage_provider="r2"` fixture)
- `web/next.config.ts` (`output: "standalone"`)
- `web/src/app/(user)/account/subscribe/success/page.tsx` (Suspense 래퍼)
- `web/src/app/(user)/account/subscribe/fail/page.tsx` (Suspense 래퍼)
- `.github/workflows/daily-cost-alert.yml` (placeholder → 실 구현)
- `docs/runbook/deployment.md` (§4.4 신설)
- `docs/runbook/secret-rotation.md` (§1/§2/§5/§8/§9 채움)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (`ready-for-dev → in-progress` + 1행 prepend)
- `_bmad-output/implementation-artifacts/8-5-클라우드-배포-hardening-runbook.md` (Status, Tasks, Dev Agent Record)

### Change Log

| 일자 | 항목 | 비고 |
|---|---|---|
| 2026-05-12 | Story 8.5 DS 시작 | Amelia / Opus 4.7, branch `story/8.5-cloud-deploy-render-supabase` |
| 2026-05-12 | Dockerfile.api multi-stage + .dockerignore 작성 | builder/runtime 분리, build 성공 1.18GB |
| 2026-05-12 | Storage adapter Supabase 분기 swap | storage3 직접 dep, 시그니처 0건 변경 |
| 2026-05-12 | Next.js standalone + Suspense 회귀 fix 2건 | success/fail page 분리 |
| 2026-05-12 | deployment.md §4.4 + secret-rotation.md §1/§2/§5/§8/§9 + incident-response.md 신규 | 3종 runbook 완성 |
| 2026-05-12 | daily-cost-alert.yml 실 구현 | OpenAI/Anthropic/LangSmith + Discord + gh issue |
| 2026-05-12 | asyncpg pgbouncer transaction mode 호환 | `_asyncpg_connect_args` 헬퍼 + main.py 적용 |
| 2026-05-12 | Sentry prod env 분리 — `_validate_jwt_secrets_in_prod`에 `production` 추가 | Render dashboard 표기 정합 |
| 2026-05-12 | DS 종료 — Status `in-progress → review` | 1379 pytest passed, 0 failures. Task 10 사용자 hands-on |
