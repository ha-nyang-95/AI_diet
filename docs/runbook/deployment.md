# 배포 토폴로지 + 외주 인수 마이그레이션 SOP

**SOT 작성일**: 2026-05-05 (Story 3.9 AC3)
**대상 독자**: 운영자(hwan) / 외주 인수자(향후) / 클라이언트 SRE

---

## 1. 현행 토폴로지 (Railway + Cloudflare + R2)

```
┌──────────────┐
│ Mobile / Web │
└──────┬───────┘
       │ HTTPS (TLS 1.3)
       ▼
┌────────────────────────────────────────┐
│ Cloudflare                             │
│  • DNS (api.balancenote.com)           │
│  • WAF rule set                        │
│  • DDoS L7 mitigation                  │
│  • TLS termination                     │
│  • CF-Connecting-IP 헤더 첨부          │
└──────┬─────────────────────────────────┘
       │ HTTPS (Cloudflare → origin)
       ▼
┌────────────────────────────────────────┐
│ Railway                                │
│  • uvicorn (FastAPI lifespan)          │
│  • proxy_headers=True                  │
│  • forwarded_allow_ips=Cloudflare CIDR │
└──┬───────────┬───────────┬─────────────┘
   │           │           │
   ▼           ▼           ▼
┌──────────┐ ┌──────┐ ┌──────────────────┐
│ Postgres │ │Redis │ │ Cloudflare R2    │
│  + pgvec │ │      │ │ (image storage)  │
└──────────┘ └──────┘ └──────────────────┘
```

### 핵심 설계 선택

- **Cloudflare 프록시 in front**: WAF/DDoS/CDN 1차 방어 + 한국 사용자 PoP latency 단축.
  TLS는 Cloudflare가 종단 처리 — origin(Railway)은 HTTPS *origin pull* 정합.
- **`CF-Connecting-IP` 헤더 신뢰**: Cloudflare가 강제 첨부하는 원본 클라이언트 IP. 신뢰
  proxy 검증(`api/app/core/proxy.py:_is_trusted_proxy_ip`)으로 spoofing 차단.
- **uvicorn `proxy_headers`**: Railway → uvicorn 사설 IP forwarding 시 `X-Forwarded-For`
  로 원본 IP 노출. `forwarded_allow_ips`에 Cloudflare IPv4/IPv6 CIDR 22개 + private
  range 화이트리스트.
- **Railway-specific feature 회피**: pgvector container, Redis container 모두 Railway
  plugin이 아닌 standard Postgres + Redis로 구성 → Cloud Run / AWS ECS 마이그레이션
  시 그대로 swap 가능.

---

## 2. uvicorn 실행 시점 wire (Railway)

Railway 환경 변수:

```bash
# Railway dashboard → Service → Variables
PORT=8080
WEB_CONCURRENCY=2
```

`Procfile` 또는 Railway start command:

```bash
uv run uvicorn app.main:app \
  --host 0.0.0.0 \
  --port ${PORT} \
  --proxy-headers \
  --forwarded-allow-ips='*'
```

**`--forwarded-allow-ips='*'`** 의미: Railway가 자체 internal proxy로 연결하므로 모든
forwarded 헤더를 일단 trust. application-layer에서 `app.core.proxy.get_real_client_ip`
가 *Cloudflare CIDR + private IP*로 다시 필터링 → 두 단계 trust 모델.

---

## 3. Cloudflare WAF rule (`forwarded_allow_ips` 보강)

Cloudflare dashboard → Security → WAF → Custom Rules:

### Rule 1 — Web 전용 Same-origin Referer 강제 (W17 1.5)

```
(http.request.method eq "POST"
  and http.request.uri.path eq "/v1/users/me/profile"
  and (
    starts_with(http.user_agent, "Mozilla/")
    or http.user_agent contains "Chrome"
  )
  and http.referer ne "https://balancenote.com")
=> Block (403)
```

**중요 주의 (CR P20 — 2026-05-06)**: React Native / Expo 네이티브 클라이언트는 표준
``Referer`` 헤더를 발신하지 않으므로 단순 ``http.referer ne ...`` 조건은 모바일
트래픽도 일괄 차단된다. 위 룰은 *브라우저 UA prefix*로 web 트래픽만 게이팅 — 모바일은
JWT(Bearer) + httpOnly cookie 부재로 CSRF 표면 자체가 다르다(SameSite는 브라우저 정책).
운영 적용 전 staging에서 모바일 happy-path 1회 검증 의무.

CSRF 추가 가드 — httpOnly 쿠키 + SameSite=Lax는 1차 방어, Cloudflare WAF는 2차.

### Rule 2 — Known bad bot 차단 (DDoS 보강)

```
(cf.client.bot eq "true" and not cf.verified_bot eq "true")
=> Challenge (CAPTCHA)
```

---

## 4. 외주 인수 마이그레이션 가이드

### 4.1 Cloud Run / Google Cloud로 마이그레이션 시

**변경 필요 지점**:

| 영역 | Railway 패턴 | Cloud Run 패턴 |
|---|---|---|
| Secret 저장 | Railway env vars | GCP Secret Manager |
| DB connection | `DATABASE_URL` | `DATABASE_URL` + Cloud SQL Auth Proxy |
| Redis | Railway plugin | Memorystore for Redis |
| R2 | Cloudflare R2 (S3 API 호환) | Cloud Storage |
| Container build | Railway Nixpacks | `Dockerfile` + Artifact Registry |

**uvicorn `--forwarded-allow-ips`**: Cloud Run은 `X-Forwarded-For` 마지막 IP가 원본
이라 본 패턴이 다름 — `app/core/proxy.py`의 `get_real_client_ip`에 ``cloud_run_xff``
모드 추가 필요. 외주 인수 시 작성.

### 4.2 AWS ECS / Fargate로 마이그레이션 시

**변경 필요 지점**:

| 영역 | Railway 패턴 | AWS 패턴 |
|---|---|---|
| Load Balancer | Cloudflare → Railway | Cloudflare → ALB → ECS |
| Secret 저장 | Railway env vars | AWS Secrets Manager |
| DB | Railway Postgres | RDS PostgreSQL + pgvector extension |
| Redis | Railway plugin | ElastiCache Redis |
| R2 | Cloudflare R2 | S3 |

**ALB `X-Forwarded-For` 첫 IP가 원본** — Railway 패턴과 동일하게 동작 → `proxy.py`
변경 0건.

### 4.3 Cloudflare 자체를 제거하는 경우

`api/app/core/proxy.py`:
- `_CLOUDFLARE_IPV4`/`_CLOUDFLARE_IPV6` frozenset를 빈 set로 swap.
- `get_real_client_ip`가 자동으로 `request.client.host` raw fallback 의존.
- Cloudflare WAF rule(§3)을 ALB WAF / Cloud Armor로 이전.

---

## 4.4 Render + Supabase 미니멀 배포 (포트폴리오 패턴) — Story 8.5

**SOT 작성일**: 2026-05-12 (Story 8.5)
**대상**: 포트폴리오 영업 시연 / 데모 / 외주 인수 candidate. **실 사용자 prod 운영은 §4.1/§4.2 참조**.

본 섹션은 §1~§4.3과 *독립적인 별 토폴로지* — Railway/Cloudflare/R2 패턴은 미래 옵션으로 보존하고, 비용 $0 + 단순성 우선 패턴을 신설.

### 4.4.1 토폴로지

```
┌──────────────┐
│ Mobile / Web │
└──────┬───────┘
       │ HTTPS (Render 자동 TLS / Let's Encrypt)
       ▼
┌─────────────────────────────────┐
│ Render Free tier (2 services)   │
│  • Web Service A: bn-api        │  ← FastAPI Docker (Dockerfile.api)
│    `https://bn-api.onrender.com`│
│  • Web Service B: bn-web        │  ← Next.js standalone (Node 빌드)
│    `https://bn-web.onrender.com`│
└──────┬──────────────────────────┘
       │ HTTPS (asyncpg + storage3)
       ▼
┌─────────────────────────────────┐
│ Supabase Free tier (1 project)  │
│  • Postgres 500MB + pgvector    │
│  • Storage 1GB (bucket=meals)   │
└─────────────────────────────────┘
```

### 4.4.2 핵심 설계 선택

- **Redis 생략** — Render Free에 별 service 추가하지 않음. graceful fallback 활용:
  * `slowapi` rate limit → in-memory backend (`api/app/main.py:_build_limiter` 자동 분기).
  * Vision/LLM router 캐시 → 미적용 (매 호출 → cost 살짝 ↑ but 포트폴리오 scope OK).
  * `subscription_expire.py` advisory lock → in-memory fallback (single replica 전제).
  * Idempotency-Key (`api/app/core/idempotency.py`) → DB `meals.idempotency_key`
    UNIQUE 제약이 SOT라 Redis 없어도 멱등성 유지 (Story 2.5).
- **Cloudflare 완전 생략** — DNS·WAF·R2 모두 미사용. `.onrender.com` subdomain 그대로 +
  Supabase Storage 사용. 외주 인수 시점에 Cloudflare 재도입은 §3 + §4.3 SOP로 복귀.
- **도메인 생략** — `.onrender.com` subdomain 사용. Google OAuth Console에는
  `https://bn-web.onrender.com/api/auth/google/callback` 사전 등록 필요 (Story 8.5 2026-05-12 완료).
- **시크릿 재사용** — dev 키 그대로 prod에 재사용 (포트폴리오 scope). JWT_SECRET_KEY만
  prod 전용 신규 발급 (dev 사용자 자동 prod 진입 차단). 인수 시점 분리 발급 SOP는
  `secret-rotation.md` §1/§2/§5/§8 참조.
- **Storage 추상화** — `api/app/adapters/r2.py` 모듈명 유지하되 내부 분기 (`STORAGE_PROVIDER=r2`
  vs `supabase`). 호출처(`meals_images.py` 등) 변경 0건. 외주 인수 시점에 R2 swap-back 가능.
- **cold start 30~60초** — Render Free 15분 idle 후 워밍업 필요. 데모 직전 1회 ping (또는
  `cron-job.org` 무료 5분 ping 등록 — 본 스토리 OUT).
- **7일 inactivity pause** — Supabase Free 정책. dashboard restore 1분. 매주 GitHub
  Actions cron으로 `SELECT 1` 1회 ping 가능 (별도 workflow, 본 스토리 OUT).
- **모니터링** — Sentry Developer plan(무료) 2 project 분리:
  * `balancenote-api` → `SENTRY_DSN` (backend)
  * `balancenote-web` → `NEXT_PUBLIC_SENTRY_DSN` (web — wiring은 Story 8.4 forward)
- **Discord webhook** — 비용 알림 채널. Slack 대비 (a) 영구 메시지 보관 (Slack free 90일
  한정), (b) Sentry/GitHub 모두 native 지원. 채널 → Edit Channel → Integrations → Webhooks.

### 4.4.3 첫 배포 절차 (체크리스트)

**사전 준비** (사용자 hands-on):

- [ ] Render 계정 + GitHub repo OAuth 연동.
- [ ] Supabase 계정 + 프로젝트 생성 권한.
- [ ] OAuth Console에 prod redirect URI 등록 — `https://bn-web.onrender.com/api/auth/google/callback`.
- [ ] `python -c "import secrets; print(secrets.token_urlsafe(32))"` 출력으로 `JWT_SECRET_KEY` 신규 발급.
- [ ] Sentry 2 project 발급 — `balancenote-api`, `balancenote-web` (Client Keys DSN 복사).
- [ ] Discord 채널 webhook URL 발급 (비용 알림 전용 채널 권장).

**Supabase project 생성**:

1. https://supabase.com → New Project.
   * Region: **Northeast Asia (Seoul) 1순위, Tokyo 차선**.
   * Database password: 안전한 비밀번호 (이후 `DATABASE_URL`에 사용).
2. Settings → Database → Connection string → **Transaction mode pooler (port 6543)**.
   * 형식: `postgresql+asyncpg://postgres:[PWD]@[REF].pooler.supabase.com:6543/postgres?pgbouncer=true`
3. Database → Extensions → `vector` 검색 → **Enable**. (alembic 0010이 `CREATE EXTENSION
   IF NOT EXISTS vector` 호출하지만 superuser 권한 없는 경우 사전 활성화 필수.)
4. Storage → New Bucket → name `meals`, **Public access OFF**, file size limit 10 MB.
5. Settings → API → `service_role` 키 복사 (server-side 전용, anon key 사용 금지).

**Render Web Service A (bn-api)**:

1. https://dashboard.render.com → New → Web Service → Connect GitHub repo.
2. 설정:
   * Name: `bn-api`
   * Region: Singapore (한국 latency 최단)
   * Branch: `master`, Auto-Deploy: ON
   * **Language/Runtime**: Docker
   * **Dockerfile Path**: `docker/Dockerfile.api`
   * **Docker Context**: `.` (repo root)
   * **Health Check Path**: `/healthz`
   * Instance Type: Free
3. Environment Variables (`.env.production.example` SOT 정합):
   - [ ] `DATABASE_URL` — Supabase pooler URI (위 §4.4.3 Supabase 생성 step 2).
   - [ ] `ENVIRONMENT=production`
   - [ ] `JWT_SECRET_KEY` — 신규 발급 값.
   - [ ] `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `LANGSMITH_API_KEY` (dev 키 재사용).
   - [ ] `LANGCHAIN_TRACING_V2=true` / `LANGSMITH_PROJECT=balancenote-prod`
   - [ ] `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT_URI`
     (dev client 재사용 + prod URI).
   - [ ] `SENTRY_DSN` — backend project DSN.
   - [ ] `STORAGE_PROVIDER=supabase`
   - [ ] `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_STORAGE_BUCKET=meals`
   - [ ] `CORS_ALLOWED_ORIGINS=https://bn-web.onrender.com`
   - [ ] `TOSS_SECRET_KEY` / `TOSS_WEBHOOK_SECRET_KEY` (dev sandbox 키 재사용).
4. Save → 첫 빌드 + 배포 트리거 (10~15분). `alembic upgrade head`가 Dockerfile CMD에 포함되어
   첫 부팅 시 0001~0023 migration 자동 실행.

**Render Web Service B (bn-web)**:

1. Dashboard → New → Web Service → 동일 GitHub repo.
2. 설정:
   * Name: `bn-web`
   * Region: Singapore
   * Branch: `master`, Auto-Deploy: ON
   * **Language/Runtime**: Node
   * **Root Directory**: `web`
   * **Build Command**: `pnpm install --frozen-lockfile && pnpm build`
   * **Start Command**: `node .next/standalone/server.js` (standalone mode, Story 8.5 AC9)
   * Instance Type: Free
3. Environment Variables:
   - [ ] `NEXT_PUBLIC_API_BASE_URL=https://bn-api.onrender.com`
   - [ ] `API_BASE_URL=https://bn-api.onrender.com`
   - [ ] `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT_URI`
     (bn-api와 동일).
   - [ ] `NEXT_PUBLIC_SENTRY_DSN` (Story 8.4 web Sentry wiring 시점에 활성).
4. Save → 첫 빌드 + 배포 (5~8분, Node 빌드는 Docker보다 빠름).

**GitHub Actions Secrets** (`daily-cost-alert.yml` 등 workflow용):

- [ ] Repository Settings → Secrets and variables → Actions → New repository secret.
- [ ] `OPENAI_API_KEY` (read-only 별도 발급 권장), `ANTHROPIC_ADMIN_API_KEY`,
  `LANGSMITH_API_KEY`, `DISCORD_COST_WEBHOOK_URL`, `THRESHOLD_USD=5.0`,
  `SENTRY_AUTH_TOKEN` (옵션).

### 4.4.4 smoke 검증 (배포 후 첫 1회)

- [ ] `curl -i https://bn-api.onrender.com/healthz` → `200 OK` + body `{"status":"ok"}`
- [ ] 브라우저 → `https://bn-web.onrender.com/login` → Google 로그인 버튼 클릭 → 인증 →
      onboarding → 건강 프로필 → 식단 텍스트 입력 1건 → 분석 결과 (fit_score + 매크로 +
      인용 피드백) 표시.
- [ ] 식단 사진 입력 1건 → Supabase Storage presigned URL 발급 → 사진 업로드 → OCR 결과 표시.
- [ ] Sentry dashboard `balancenote-api` → 의도적 에러 1건 발생 후 `environment="production"`
      tag 확인.
- [ ] Actions → `daily-cost-alert.yml` → Run workflow → Discord 채널에서 메시지 수신 확인.

### 4.4.5 롤백 절차

**bn-api / bn-web 코드 롤백**:

1. Render dashboard → 해당 service → Deploys 탭.
2. 정상 동작하던 이전 commit 행 → ⋯ 메뉴 → **Rollback to this deploy** → 1분 내 복구.

**Supabase migration 롤백** (destructive migration 적용 후 회귀 시):

1. Supabase dashboard → Database → Backups → 자동 백업 시점에서 restore (Free tier는 7일
   PITR 미지원이라 backup dump 필요).
2. 또는 `alembic downgrade -1` 수동 실행 (Render shell — Dashboard → Shell):
   ```bash
   alembic downgrade -1
   ```
3. destructive migration(DROP COLUMN 등) 적용 *전*에는 Supabase Dashboard → Database →
   Backups → Create backup 수동 실행 권장.

### 4.4.6 인수 시점 마이그레이션 옵션

외주 인수 시 또는 트래픽 증가 시 다음 패턴으로 swap:

- **Render → Railway/Cloud Run/AWS**: §4.1/§4.2 cross-link. `Dockerfile.api`는 그대로 사용.
- **Supabase → 자체 Postgres**: `DATABASE_URL` 교체 + pgvector 확장 활성화. `STORAGE_PROVIDER=r2`
  swap-back은 `r2_*` env 5종 주입 + Supabase env 비우기.
- **Cloudflare WAF 재도입**: §3 SOP 복귀 + Render origin → Cloudflare proxy 전환.
- **Sentry plan 업그레이드**: Developer → Team (5명 사용자 + custom alert).

### 4.4.7 알려진 제약 / 운영 주의

| 항목 | 영향 | 대응 |
|---|---|---|
| Render Free 15분 cold start | 데모 첫 호출 30~60초 지연 | 데모 직전 ping 1회 워밍업 |
| Supabase 7일 inactivity pause | 데모 직전 unavailable | dashboard restore 1분 / 매주 cron ping |
| Render Free 750hr/월 한도 | 24x7 운영 시 월 30일 ÷ 2 service = 360hr 정도 사용 | 데모 시점만 가동 — 충분 |
| Supabase Free 500MB DB | 사용자 row + 식단 + RAG chunk 충분 | 1500건 식약처 + chunk + user 데이터 ~100MB 예상 |
| asyncpg + pgbouncer PREPARE 비호환 | 첫 쿼리 오류 가능 | `?pgbouncer=true` URL 인식 시 `statement_cache_size=0` 적용 필요 (engine 갱신 forward) |
| Multi-replica 미지원 | APScheduler advisory lock 미발동 시 cron 중복 가능 | 단일 replica 전제 — multi-replica는 인수 시점 forward |

---

## 5. Cloudflare IP range 갱신 SOP

분기 1회(=3개월) 운영자 작업. 별도 문서: [`cloudflare-ip-refresh.md`](./cloudflare-ip-refresh.md).

### 5.1 Push 알림 dev SOP (Story 4.1)

EAS dev build / projectId / FCM v1 / iOS aps-environment / 권한 거부 회복 절차:
[`push-notifications-dev.md`](./push-notifications-dev.md).

---

## 6. 결정 SOT

- **Story 3.9 AC1-3 결정** (2026-05-05) — `_bmad-output/implementation-artifacts/deferred-work.md`.
- **architecture.md** — `Infrastructure & Deployment` 섹션 (line 340-353) 참조.

---

## 7. 비상 연락처 / 회복 절차

(외주 인수 시 클라이언트가 채움)

- **DNS 장애**: Cloudflare dashboard → DNS → Records 확인 + `dig api.balancenote.com`.
- **TLS 인증서 만료**: Cloudflare 자동 갱신 — 만료 7일 전 알림 + dashboard SSL/TLS.
- **Origin 서버 down**: Railway dashboard → Service → Restart. 또는 Cloud Run / ECS
  health check 강제 재배포.
