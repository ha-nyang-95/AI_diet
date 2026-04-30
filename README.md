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
| `consent.automated_decision.missing` | 403 | PIPA 2026.03.15 자동화 의사결정 동의 미부여 — 분석 라우터 차단(LLM 비용 0 보호) |
| `consent.automated_decision.not_granted` | 404 | `DELETE /automated-decision`을 미동의 row에서 호출 — GET으로 상태 재확인 |
| `consent.automated_decision.version_mismatch` | 409 | 자동화 의사결정 동의서 갱신됨 — `X-Consent-Latest-Version` 헤더에 SOT 버전 첨부 |
| `validation.error` | 400 | Pydantic validation (`errors[]` 배열에 필드별 사유 — `age`/`weight_kg`/`height_cm` 범위 외, `activity_level`/`health_goal` enum 외, `allergies` 22종 외 항목·dedup, 누락 필드, `extra="forbid"` 위반 등 Story 1.5) |

본 스토리(Story 1.5)에서 `POST /v1/users/me/profile` 200 / `GET /v1/users/me/profile` 200 두 endpoint가 신규 도입되며 `Depends(require_basic_consents)`가 `POST`에 첫 wire 됩니다(`GET`은 *자기 정보 조회*라 동의 게이트 미적용). 검증 실패 케이스 6 종(범위·enum·22종 알레르기·누락·extra·중복)은 모두 `code=validation.error` 400 으로 매핑됩니다.

**409 응답 헤더 — `X-Consent-Latest-Version`** (Story 1.4)

- 두 version mismatch(`consent.version_mismatch` / `consent.automated_decision.version_mismatch`)
  응답에 `X-Consent-Latest-Version: <doc_type>=<version>` 헤더가 첨부됩니다.
- 클라이언트가 추가 `GET /v1/legal/{type}` round-trip 없이 latest version을 즉시 인식할 수 있도록
  돕는 *옵션 hint* — 1차 신호는 body의 `code`/`detail`. 첫 mismatch entry만 인코딩하므로
  필요 시 클라이언트가 GET으로 fresh 텍스트를 fetch하면 다른 항목도 함께 갱신됩니다.

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

### PIPA 자동화 의사결정 SOP (Story 1.4)

- **별 SOT 위치**: `api/app/domain/legal_documents.py`의 `("automated-decision", "ko"|"en")` entry.
  `disclaimer/terms/privacy`와 *분리된 5섹션 텍스트*(처리 항목 / 이용 목적 / 보관 기간 / 제3자 제공
  / LLM 외부 처리). PIPA 2026.03.15 자동화된 결정 동의 의무에 정합하며, 입법예고(R9)는 분기 1회
  추적 후 텍스트·version을 갱신합니다 — `https://www.moleg.go.kr/lawinfo/makingInfo.mo?lawSeq=81114`.
- **3 게이트 분리** (절대 통합 금지):
  1. `current_user` (Story 1.2) — JWT 검증.
  2. `require_basic_consents` (Story 1.3) — 4종 기본 동의 + SOT 버전 일치.
  3. `require_automated_decision_consent` (Story 1.4) — `automated_decision_consent_at` NOT NULL +
     `_revoked_at` IS NULL + `_version` 일치. **Epic 3 분석 라우터(`/v1/analysis/stream` 등)에서만
     wire** — `/v1/users/me`/`/v1/users/me/profile`처럼 LLM 호출 없는 endpoint에는 wire 금지.
- **철회 endpoint**: `DELETE /v1/users/me/consents/automated-decision` — `revoked_at = now()` set,
  `consent_at`은 보존(과거 동의 사실 감사 흔적). 미동의 상태에서 호출 시 404
  (`consent.automated_decision.not_granted`). 사용자 의도 *철회*인데 *미동의 상태*는 모호 →
  명시 분기로 클라이언트가 GET 후 재분기.
- **재동의 케이스**: 철회 후 `POST /v1/users/me/consents/automated-decision`가 `revoked_at = NULL`로
  reset, `consent_at`을 새 시각으로 갱신. UPSERT(`pg_insert(...).on_conflict_do_update`)로 race-free.
- **재열람 위치**:
  - Mobile: `(tabs)/settings/automated-decision` — 풀텍스트 + 부여/철회 버튼(분기) + Confirm 다이얼로그.
  - Web: `/legal/automated-decision` (한국어), `/en/legal/automated-decision` (영문) — 인증 무관 public.
    Web settings 측 *철회·재부여 UI*는 Story 5.1에서 추가 예정(현 Web에 settings 그룹 부재).

### 건강 프로필 입력 SOP (Story 1.5)

- **22종 알레르기 SOT 위치**: `api/app/domain/allergens.py:KOREAN_22_ALLERGENS` tuple. 식약처
  *식품 등의 표시기준 별표* 22종. 정의 순서(우유 → 메밀 → … → 기타)는 PDF 순 — 본 순서는
  Story 3.5 fit_score 알레르기 위반 단락 22 단위 테스트 입력 도메인. 변경 SOP:
  1. `KOREAN_22_ALLERGENS` tuple 갱신 (정의 순 보존).
  2. mobile/web 두 클라이언트 schema(`features/onboarding/healthProfileSchema.ts`)도 동일 갱신
     (백엔드 SOT를 import하지 않는 이유: bundler 분리 + i18n 라벨 분기 가능성).
  3. 새 alembic revision으로 `users.allergies` `ck_users_allergies_domain` CHECK 제약
     drop+recreate(`app.domain.allergens` import 후 SQL 인라인).
  4. `scripts/verify_allergy_22.py` 분기 1회 cron(R8 SOP, Story 8) 실행 결과 동기.
- **`health_goal` 4종 + `activity_level` 5종**: `api/app/domain/health_profile.py` Literal SOT —
  `weight_loss` / `muscle_gain` / `maintenance` / `diabetes_management` (KDRIs AMDR 매크로 룰
  forward-hook, Story 3.5 fit_score lookup table 키) + `sedentary` / `light` / `moderate` /
  `active` / `very_active` (Mifflin-St Jeor + Harris-Benedict 활동 계수 표준 5단계, Story 3.x
  BMR/TDEE 기반). 한국어 라벨 매핑은 클라이언트(`HEALTH_GOAL_LABELS_KO` /
  `ACTIVITY_LEVEL_LABELS_KO`) 책임 — 백엔드는 enum 영문값만 저장·반환(향후 영문 UI 전환 시
  백엔드 변경 0).
- **`require_basic_consents` 첫 라우터 wire**: 본 스토리에서 `POST /v1/users/me/profile`에
  첫 wire 적용 (Story 1.3 W14 deferred 흡수). 4종 기본 동의 미통과 사용자는 403 +
  `code=consent.basic.missing` raise → 모바일/Web 클라이언트가 `(auth)/onboarding/disclaimer`
  로 자동 redirect. **`GET /v1/users/me/profile`에는 적용 금지** — 자기 정보 *조회*는 동의 무관
  (`deps.py:require_basic_consents` docstring 정합).
- **`profile_completed_at` 4번째 가드 (mobile + Web)**: Story 1.5에서 `users.profile_completed_at`
  컬럼 추가 후 `GET /v1/users/me` 응답 모델(`UserMeResponse`)이 본 필드 forward.
  - Mobile: `(tabs)/_layout.tsx`가 (1) 인증 → (2) basic → (3) AD → **(4) profile** 4단계 가드 —
    `!user.profile_completed_at` 시 `(auth)/onboarding/profile` redirect.
  - Web: `(user)/dashboard/page.tsx`가 동일 4단계 가드 — `!user.profile_completed_at` 시
    `/onboarding/profile` redirect.
  - **가드 순서 엄수** — basic/AD 미통과 사용자가 profile 화면으로 우회되지 않도록 (1)→(2)→(3)→(4)
    순서 유지.
- **컬럼 무결성 (DB CHECK 제약)**: `0005_users_health_profile.py` 마이그레이션이 `age`(1~150) /
  `weight_kg`(1.0~500.0) / `height_cm`(50~300) / `allergies`(22종 부분집합 `<@`) 4건의
  CHECK 제약과 `users_activity_level_enum` / `users_health_goal_enum` 2종 Postgres ENUM 타입을
  생성. SQLAlchemy 모델 선언과 alembic SQL이 *동일 SOT*(`app.domain.allergens.KOREAN_22_ALLERGENS`
  module-level import)로 동기 — autogenerate diff 0건 보장.

### 온보딩 튜토리얼 SOP (Story 1.6)

- **Onboarding chain 6단계 도식 (Story 1.3·1.4·1.5·1.6 누적)**:
  ```
  로그인 → /onboarding/disclaimer → /terms → /privacy → /automated-decision → /tutorial → /profile → /(tabs)/meals
  ```
  - `disclaimer / terms / privacy` (Story 1.3 4 surface) + `automated-decision` (Story 1.4 PIPA
    별도 동의) + `tutorial` (Story 1.6 사용법 3 슬라이드) + `profile` (Story 1.5 6 입력) — 6 화면
    순차 통과 시 `(tabs)/meals` 진입. mobile-only chain — Web `/onboarding`은 `disclaimer ·
    automated-decision · profile` 3 path로 minimal UI(architecture line 985 정합).
- **`users.onboarded_at` vs `users.profile_completed_at` 의미 분리**:
  - `onboarded_at`: *최초 온보딩 흐름 통과 시점*. 첫 `POST /v1/users/me/profile` 시 한 번만
    DB `func.coalesce(User.onboarded_at, func.now())`로 멱등 set. 이후 재 POST(Story 5.1
    프로필 수정)에도 *변경 X* — 사용자 *최초 가입 audit*용 단일 출처.
  - `profile_completed_at`: *최신 프로필 기록 시점*. 매 POST 갱신.
  - 두 컬럼 모두 `UserMeResponse` (`GET /v1/users/me`) + `UserPublic` (signIn 응답)로 forward.
- **`tutorial-seen` AsyncStorage 키**:
  - 키: `bn:onboarding-tutorial-seen` (boolean stringified — `'1'` 저장, 미존재 시 false 간주).
  - 모듈: `mobile/features/onboarding/tutorialState.ts` — `getTutorialSeen() / setTutorialSeen(true) /
    clearOnboardingState()` 3 helper export.
  - clear 정책: `mobile/lib/auth.tsx:signOut`이 `clearAuth()` (토큰 clear, secure-store 책임)
    호출 직후 `clearOnboardingState()` (onboarding state clear, tutorialState 책임)를 *순차
    await* — 사용자 A 로그아웃 후 B 로그인 시 A의 seen 잔존이 B에게 전파 차단.
  - 책임 분리: `secure-store.ts`는 *토큰 전용* 유지(`secure-store.ts:4` "AsyncStorage 평문 저장
    금지" 주석은 NFR-S1 토큰 보호 context). 비-민감 client preference는 `tutorialState`가 별도
    AsyncStorage에서 관리.
- **Epic 1 종료 — 기반 인프라 + 인증 + 온보딩·동의 (1.1~1.6) 6 스토리 완료**:
  Story 1.1(부트스트랩) · 1.2(Google OAuth + JWT) · 1.3(약관·개인정보 동의 4-surface) · 1.4(PIPA
  자동화 의사결정) · 1.5(건강 프로필 22종 알레르기) · 1.6(온보딩 튜토리얼 + Epic 1 종료). Epic 2
  (식단 입력 + 일별 기록 + 권한 흐름) 진입 준비 완료.

### 식단 CRUD SOP (Story 2.1)

- `/v1/meals` REST 4 endpoint (POST/GET/PATCH/DELETE) — *작성 경로*(POST/PATCH/DELETE) 3종에만
  `Depends(require_basic_consents)` wire (Story 1.5 W14 두 번째 적용). *조회 경로*(GET)는
  `current_user`만 — PIPA Art.35 정보주체 권리(자기 데이터 열람은 동의 철회와 독립).
- `meals` soft delete 정책 — `DELETE /v1/meals/{id}`는 `deleted_at = func.now()` 단일 UPDATE만
  실행 (물리 삭제 X). 30일 grace + 일괄 물리 파기는 Story 5.2 책임.
- PATCH/DELETE의 *소유권 미일치 / 존재 X / 이미 deleted* 모두 동일 응답 (404 + `code=meals.not_found`)
  — `update().where(id, user_id, deleted_at IS NULL).returning()` 단일 SQL로 enumeration 차단.
- `Idempotency-Key` 헤더는 본 스토리 baseline에서 *수신만 허용* — 같은 key 재발사 시 중복 row
  생성. 멱등 처리(409/200 분기)는 Story 2.5(오프라인 큐잉 + 자동 sync) 책임.
- Epic 2(*식단 입력 + 일별 기록 + 권한 흐름*) 첫 스토리(2.1) 완료. 후속: 2.2(사진 입력) /
  2.3(OCR 추출) / 2.4(일별 기록 화면 polish) / 2.5(오프라인 텍스트 큐잉 sync).

### 식단 사진 입력 SOP (Story 2.2)

- `POST /v1/meals/images/presign` → R2 직접 업로드(PUT) → `POST /v1/meals` body에 `image_key` 첨부
  2-step (백엔드 proxy 회피, Railway egress + 메모리 폭발 방지). presigned URL 5분 만료, 10 MB 상한.
- R2 환경변수 5종(`r2_account_id`, `r2_access_key_id`, `r2_secret_access_key`, `r2_bucket`,
  `r2_public_base_url`) 미설정 시 503 + `code=meals.image.r2_unconfigured` (dev/CI fail-fast).
- 카메라/사진첩 권한 거부 시 `PermissionDeniedView` 표준 컴포넌트 + `Linking.openSettings()` 안내.
  iOS *Don't Allow* / Android *Don't ask again* 구분 (`canAskAgain`) — 설정 deep link만 의미 있는 경로.
- 사진-only 입력 시 서버가 `raw_text="(사진 입력)"` placeholder fallback (Story 2.3 OCR이 결과로 덮어씀).
  `image_key`는 `meals/{user_id}/{uuid}.{ext}` 형식 — cross-user 도용 차단(`startswith` ownership 검증).
- Epic 2 두 번째 스토리(2.2) 완료. 후속: 2.3(OCR Vision 추출 — `image_key`를 입력으로 활용).

### 식단 사진 OCR Vision SOP (Story 2.3)

- `POST /v1/meals/images/parse` body `{image_key}` → GPT-4o Vision OCR → `parsed_items`
  (name/quantity/confidence) + `low_confidence` 응답. 호출당 ~$0.005-0.01 (R6 cost alert 정합 —
  영업 데모 일일 100건 ≤ $1/일).
- `OPENAI_API_KEY` 환경변수 미설정 시 503 + `code=meals.image.ocr_unavailable` (dev fail-fast).
  R2 public URL 미설정 시 `meals.image.ocr_image_url_missing` (운영 가시성 분리).
- 신뢰도 임계값 0.6 — 모바일 `OCRConfirmCard` *forced confirmation* (CTA 비활성 +
  *"이대로 진행"* 명시 클릭 또는 모든 항목 사용자 편집 후 활성화). NFR-I3 graceful degradation —
  Vision 503 시 *"사진 인식 일시 장애 — 텍스트로 다시 입력"* alert + raw_text 직접 입력 fallback.
- `OCRConfirmCard` 사용자 확인 후 form `raw_text` 자동 갱신 (`formatParsedItemsToRawText` 변환,
  예: *"짜장면 1인분, 군만두 4개"*). DF2(`(사진 입력)` placeholder collision)는 *parsed_items 영속화 +
  raw_text overwrite 흐름*으로 자연 해소 — 클라이언트 미송신 시 서버 fallback도 동일 변환 적용.
- Epic 2 세 번째 스토리(2.3) 완료. 후속: 2.4(일별 기록 화면 polish — `parsed_items` 표시 통합) /
  Story 3.3(LangGraph `parse_meal` 노드가 본 어댑터 재사용).

### 일별 식단 기록 화면 + 7일 로컬 캐시 SOP (Story 2.4)

- `(tabs)/meals/index` 일별 picker(prev/today/next 헤더 버튼 + "오늘로 이동") + 시간순 ASC 정렬.
  헤더 title은 *"오늘 식단"* 또는 *"4월 30일 식단"* 동적 변경(KST `Intl.DateTimeFormat`).
- 백엔드 `GET /v1/meals?from_date=&to_date=`은 `Asia/Seoul` TZ 자정 boundary로 해석(W50 해소, D1
  결정 — option B). KST 0-9시 식단 누락 차단. `from_date`/`to_date` 활성 시 `ate_at ASC`(시간순),
  미적용 시 `ate_at DESC`(D2). 다중 TZ는 Growth NFR-L4.
- `analysis_summary` 슬롯(매크로/피드백/fit_score/label) 정의 — Story 2.4 baseline은 항상 null.
  Story 3.3+에서 `meal_analyses` 테이블 JOIN으로 채움. *persist 캐시 schema 변경 시 buster bump
  필수* (DF21 — `mobile/lib/query-persistence.ts: buster: 'v1' → 'v2'`).
- 7일 로컬 캐시 — TanStack Query `@tanstack/react-query-persist-client` + AsyncStorage persister
  (`bn-rq-cache` 키). `dehydrateOptions.shouldDehydrateQuery`로 *meals queryKey만 persist*(보안: 토큰
  persist X). NFR-R4 정합 — 오프라인 시 *"오프라인 — 마지막 7일 기록 표시 중"* 배너 + 읽기 전용 모드.
- `(tabs)/meals/[meal_id].tsx` 상세 placeholder — Story 3.7 SSE 채팅 통합 진입점. 7일 캐시
  client-side filter 채택(단건 endpoint는 DF18 deferred). *"AI에게 질문하기"* CTA는 disabled —
  Story 3.7 시점에 활성화. 수정/삭제 액션 버튼 + DF15 해소된 parsed_items 부제 + W49 해소된 KST 시간.
- Epic 2 네 번째 스토리(2.4) 완료. 후속: 2.5(오프라인 텍스트 큐잉 — *쓰기 캐시*) / Story 3.x가
  `analysis_summary` 슬롯 wire / Story 3.7가 `[meal_id].tsx` SSE 통합.

### 오프라인 텍스트 큐잉 + 자동 sync SOP (Story 2.5)

- `mobile/lib/offline-queue.ts` AsyncStorage FIFO 큐(`bn:offline-queue:meal:<user_id>` per-user
  namespace) + 100건 hard cap + module-level mutex(single-flight) + `useOfflineQueue` hook.
- 백엔드 `POST /v1/meals` `Idempotency-Key` 헤더 처리 — `meals.idempotency_key` TEXT NULL 컬럼 +
  `(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL` partial UNIQUE index + race-free
  SELECT-INSERT-CATCH-SELECT + 200 idempotent replay (RFC 9110, W46 흡수).
- 자동 flush — `useOnlineStatus` offline → online 전이 시 `flushQueue` 자동 호출 + 지수 backoff
  1s/2s/4s + jitter ±20% 3회 후 큐 잔존(manual retry).
- 사진 입력 + PATCH/DELETE 오프라인 차단 (epic AC) — 사진은 R2/Vision 모두 *온라인 필수*, PATCH는
  *진입 차단*만(Story 8 polish 시점에 PATCH 큐잉 검토 — DF27).
- 큐 size 100 hard cap — 초과 시 Alert *"오프라인 대기 항목이 너무 많아요(100+)"*. 4xx validation
  은 영구 실패(큐 즉시 제거 + Alert 안내), 5xx/네트워크는 transient(잔존 + backoff).
- Epic 2 다섯 스토리(2.1~2.5) 모두 done — Epic 3 AI 영양 분석(Self-RAG + 인용 피드백) 진입 준비 완료.

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
