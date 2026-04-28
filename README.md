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

### Google OAuth Client 발급 SOP (Story 1.2)

Story 1.2부터 Google 로그인을 사용하려면 Google Cloud Console에서 OAuth 2.0 client ID 3종을
발급해야 합니다.

1. https://console.cloud.google.com/ → 프로젝트 생성/선택 → "APIs & Services" → "Credentials".
2. **OAuth consent screen** 우선 구성: User Type=External, scopes=`openid email profile`.
3. **Credentials → Create Credentials → OAuth client ID** 를 3번 반복:
   - **iOS**: Application type=`iOS`, Bundle ID=`com.balancenote.mobile` (Expo `app.json` slug 정합).
   - **Android**: Application type=`Android`, Package name=`com.balancenote.mobile`, SHA-1 fingerprint
     (`eas credentials --platform android` 또는 `keytool -list -v -keystore ~/.android/debug.keystore`).
   - **Web**: Application type=`Web application`, Authorized redirect URIs에
     `http://localhost:3000/api/auth/google/callback` (dev) +
     `https://app.balancenote.app/api/auth/google/callback` (prod).
4. 발급된 Client ID / Secret을 `.env` 에 입력:
   - `mobile/.env`: `EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_{IOS,ANDROID,WEB}`
   - `web/.env.local`: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
     `GOOGLE_OAUTH_REDIRECT_URI`
   - 루트 `.env`: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` (백엔드용)

> Expo Go 개발 환경에서는 Web client ID를 모든 플랫폼에 사용해 PKCE 흐름을 검증하면 가장 마찰이 적습니다.

### 인증·동의 디버깅 SOP

응답 본문의 `code` 필드로 원인을 1차 식별합니다. 본 프로젝트가 정의한 RFC 7807 코드 카탈로그:

| code | 상태 | 의미 |
|------|------|------|
| `auth.access_token.expired` | 401 | access JWT 만료 — 클라이언트가 refresh로 갱신 |
| `auth.access_token.invalid` | 401 | access JWT 형식·서명 불일치 |
| `auth.refresh.invalid` | 401 | refresh token 미인식 / 만료 |
| `auth.refresh.replay_detected` | 401 | revoked refresh 재사용 — family 전체 revoke |
| `auth.token.issuer_mismatch` | 401 | user/admin issuer 혼용 |
| `auth.admin.role_required` | 403 | admin endpoint에 user role |
| `auth.account.deleted` | 403 | soft-deleted user 재로그인 시도 |
| `auth.google.id_token_invalid` | 401 | Google id_token 검증 실패 |
| `auth.google.email_unverified` | 401 | Google 이메일 미인증 |
| `consent.basic.missing` | 403 | 4종 기본 동의 미통과 — `(auth)/onboarding/disclaimer` 필요 |
| `consent.version_mismatch` | 409 | 클라이언트가 stale 동의 화면 제출 — 최신 텍스트 fetch 후 재동의 |
| `validation.error` | 400 | Pydantic validation (`errors[]` 배열에 필드별 사유) |

`401 Unauthorized` 점검 순서:

1. 응답 `code` 필드 확인.
2. JWT decode (https://jwt.io) — `iss` / `aud` / `exp` 가 환경 변수와 일치하는지.
3. DB에서 `users` row 조회 — `deleted_at IS NULL`, `role` 일치.
4. refresh 401이면 `refresh_tokens` row의 `revoked_at` / `expires_at` 확인.
5. `WWW-Authenticate` 헤더(401에 항상 첨부)로 RFC 6750 정합 응답 확인.

### 동의 흐름 SOP (Story 1.3)

- **풀텍스트 SOT**: `api/app/domain/legal_documents.py` 모듈 const (한·영). DB row 또는 외부
  파일을 사용하지 않습니다(1인 8주 MVP 정합). 텍스트 변경 시:
  1. `LEGAL_DOCUMENTS[(type, lang)].body` 업데이트
  2. `CURRENT_VERSIONS`의 version 문자열을 bump (`ko-2026-04-28` → `ko-2026-MM-DD`)
  3. `updated_at` 갱신
  4. PR diff로 변경 가시성 확보 — 운영 SOP는 Story 8 polish.
- **PIPA 별도 동의 의무**: 4 항목(disclaimer / terms / privacy / sensitive_personal_info)을
  *별도 체크박스*로 분리 표시. "전체 동의" 단일 체크박스 위장 금지(PIPA 22조 위반). 민감정보
  체크박스는 horizontal divider + 별 색상으로 시각 구분(PIPA 23조).
- **재열람 위치**:
  - Mobile: `(tabs)/settings` → 디스클레이머 / 약관 / 개인정보 처리방침 (한국어).
  - Web: `/legal/{disclaimer,terms,privacy}` (한국어), `/en/legal/...` (영문) — 인증 무관 public.
- **버전 mismatch 처리**: 클라이언트가 `*_version`을 backend SOT 버전과 다르게 보내면 409.
  사용자가 stale 화면을 제출한 케이스 — 모바일/Web이 최신 텍스트를 다시 fetch한 뒤 재동의.

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
