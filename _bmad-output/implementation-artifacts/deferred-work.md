# Deferred Work

리뷰·구현 과정에서 식별되었으나 다음 스토리·시점으로 미룬 항목 모음.

## Deferred from: code review of 2-2-식단-사진-입력-권한-흐름 (2026-04-29)

- **DF1 — declared `content_length` vs 실제 R2 PUT body-size enforcement 부재** — `api/app/adapters/r2.py:create_presigned_upload`. 클라이언트가 presign 요청 시 `content_length=1`로 신고 후 50MB body PUT 시 R2 측 거부 게이트 부재 → storage abuse 가능. 사유: spec.md:37("R2 측 enforcement 부재 — Story 8 hardening") 명시 + 본 스토리는 발급 게이트 책임만 담당. **재검토 시점**: Story 8(운영·hardening) — `Content-Length-Range` SigV4 condition 도입 또는 PUT 완료 후 `head_object` size 비교 게이트 추가. 본 스토리에 P21(POST/PATCH attach 시 `head_object` HEAD-check)가 도입되어 *미PUT 키 attach 1차 차단*은 됐으나, *PUT 후 size 우회*는 미해결.
- **DF2 — `(사진 입력)` placeholder가 사용자 입력과 충돌** — `api/app/api/v1/meals.py:PHOTO_ONLY_RAW_TEXT_PLACEHOLDER`. 사용자가 `raw_text="(사진 입력)"`을 직접 입력하면 자동 fallback과 구분 불가. PATCH explicit-null로 image_key clear 시 `(사진 입력)` 잔존(`test_patch_meal_can_clear_image_key_with_explicit_null`이 contract로 entrench). 사유: Story 2.3(OCR Vision 추출 + 확인 카드) 진입 시 OCR overwrite heuristic 결정과 sentinel 도입을 함께 평가해야 의미적 일관성 ↑. 본 스토리 단독 0008 마이그레이션은 scope 확장 + 후속 재설계 가능성. **재검토 시점**: Story 2.3 — 옵션 후보: (a) `is_placeholder_text BOOLEAN` 컬럼 추가, (b) DB `raw_text` nullable + 응답 시 placeholder derive (Story 2.1 invariant 갱신 필요), (c) zero-width unicode prefix sentinel(예: `​(사진 입력)`).
- **DF3 — 모바일 R2 PUT body가 full-buffer Blob(streaming X)** — `mobile/features/meals/api.ts:uploadImageToR2`. 현재 `fetch(uri).blob()` → `fetch(upload_url, { body: blob })` 패턴은 단일 사진 전체를 JS heap에 적재 후 PUT. 사유: P5(`expo-file-system.uploadAsync` BINARY_CONTENT streaming) 도입은 신규 의존성 + `app.json` plugin 등록 + Android/iOS 양 플랫폼 회귀 검증 필요로 portfolio 영업 일정에 risk. 현 패턴은 RN 0.81 + 10 MB 한도에서 안정 동작 — heap 영향 미미(256 MB+ 한계 대비). **재검토 시점**: Story 8 polish 또는 expo-file-system이 다른 기능(예: 영수증 첨부, 공유 export)에 자연 도입되는 시점. 도입 시 (a) `app.json` plugin entry + 네이티브 빌드 회귀, (b) `MealImageUploadError` PUT 에러 매핑 갱신, (c) Android `content://` URI 호환 검증.

## Deferred from: code review of 1-1-프로젝트-부트스트랩 (2026-04-27)

- **mypy `[[tool.mypy.overrides]]` 누락 모듈** — `api/pyproject.toml:46-52`에 langgraph, langchain*, langsmith, sse-starlette, tenacity, structlog 모듈 override 누락. 현재 mypy strict는 통과(import 미발생), 다음 스토리에서 해당 의존 import 도입 시 동시에 등재. 사유: 미사용 의존성에 대한 선제적 무시 규칙은 yagni; 실제 import 추가 시 즉시 처리.
- **이미지 태그 digest pin** — `docker-compose.yml`(`pgvector/pgvector:pg17`, `redis:7-alpine`), `docker/Dockerfile.api`(`ghcr.io/astral-sh/uv:0.11`)를 `@sha256:...` 형태로 pin. 사유: 부트스트랩 단계는 메이저 태그로 재현성 충분(rolling이지만 안정 채널). prod 재현성 hardening은 Story 8(운영·hardening)에서 SBOM·취약점 스캐너와 함께 일괄 도입.
- **`alembic upgrade head` migrate 서비스 분리** — 현재 `api` 컨테이너 CMD가 매 부팅마다 `alembic upgrade head && uvicorn`. 단일 replica에서는 안전, multi-replica 도입 시(Story 4 nudge alarm worker 추가 시점 또는 Railway scaling 활성화 시) advisory-lock 경합 차단을 위해 별도 `migrate` one-shot 서비스로 분리. Dockerfile.api에 NOTE(D3) 주석 예약.

## Deferred from: code review of 1-2-google-oauth-로그인-jwt (2026-04-27, chunk 1 of 4 — 백엔드 인증 코어)

- **W1 admin JWT denylist 부재** — admin JWT는 stateless 8h, logout 시 쿠키만 만료. 토큰 탈취 후 8h 윈도우 존재. 사유: spec NFR-S7가 stateless+재로그인 정책 명시. Epic 7(관리자) 또는 Story 5.x에서 jti 기반 denylist 검토.
- **W2 `request.client.host` proxy 헤더 처리** — `RefreshToken.ip_address`에 raw `request.client.host` 저장. reverse proxy 뒤에서는 LB IP로 통일. 사유: 운영 토폴로지(Railway/Cloud Run/직접 LB) 결정 후 trusted proxy 화이트리스트와 함께 일괄 도입.
- **W3 httpx retry/backoff 미적용** — `google_oauth.exchange_code` 5초 timeout만, transient 5xx/네트워크 예외가 그대로 `InvalidIdTokenError`로 전파. 사유: Epic 8(운영 hardening)의 resilience 패턴(tenacity·circuit breaker)과 함께 일괄 적용.
- **W4 Google id_token nonce 검증 미적용** — `verify_oauth2_token`이 audience만 검증. 사유: PKCE 강제 + native app 흐름이라 nonce 부재 수용 가능. 외부 보안 audit 결과에 따라 재검토.
- **W5 HTTPException 핸들러 `WWW-Authenticate` merge 우선순위** — framework 401과 도메인 401의 헤더 우선순위가 dict.update 순서에 의존. 사유: FastAPI 내부 401 발생 경로 거의 없음(모든 도메인 예외 사용 중). 신규 라우터 추가 시 재검토.
- **W6 `ProblemDetail.type=about:blank` 일관 사용** — RFC 7807 허용 범위. 사유: code 카탈로그 + i18n URI는 운영 안정화 후 Story 8 일괄.
- **W7 `email_verified` 응답 미포함** — `UserPublic`/`UserMeResponse`에 없음. 사유: spec 비요구. Story 5.x(건강 프로필 수정) 시 검토.
- **W8 AC3 `auth.token.issuer_mismatch` 노출 비대칭** — admin secret 분리로 signature 1차 차단 → 외부 코드는 `auth.access_token.invalid`로만 노출. 사유: Completion Notes에 의도적 variance 명시(2단 방어 동등).
- **W9 AC7 인덱스 naming variance** — alembic이 만든 `uq_*` ↔ spec `idx_*`. 사유: 기능 동등 / explain plan 동일. autogenerate diff 잡티만 발생할 경우 일괄 rename.
- **W10 ValidationError `msg`/`loc` raw 노출** — pydantic 메시지가 입력값 echo. 사유: 별도 NFR(입력 echo 정책) 정의 후 모든 validation 에러 일괄 sanitize.
- **W11 refresh body+cookie 동시 전송 시 새 쿠키 미설정** — Web 클라이언트가 둘 다 보내면 mobile 분기 진입 → `Set-Cookie` 누락 → 다음 요청부터 401. 사유: 클라이언트 분기 정책(쿠키 우선) 합의 후 한 번에 수정.
- **W12 (D5 결정) `redirect_uri` 서버 화이트리스트 미도입** — 클라이언트가 임의 `redirect_uri` 전달, Google 콘솔 화이트리스트만으로 통제. 사유: 8주 일정 정합 + 운영 복잡도 회피. Google OAuth 콘솔 redirect URI 화이트리스트가 1차 방어로 충분 판단(공격자가 임의 redirect_uri를 보내도 Google 측에서 거부). Story 8(운영 hardening) 또는 외부 보안 audit 결과에 따라 재검토.

## Spec deviation: SameSite=Lax (2026-04-28, runtime debugging)

- **AC2/AC3 spec**: `bn_access`/`bn_refresh`/`bn_admin_access` 쿠키에 `SameSite=Strict` 명시.
- **실제 구현**: `SameSite=Lax`로 변경 (`api/app/api/v1/auth.py`).
- **사유**: spec literal 따라 Strict로 발급하면 OAuth callback의 cross-site initiated redirect chain(`accounts.google.com → /api/auth/google/callback → /dashboard`)에서 첫 `/dashboard` 요청에 쿠키가 포함되지 않음. 브라우저는 redirect chain의 initiator가 cross-site(Google)이면 chain 전체를 cross-site로 판정해 Strict 쿠키를 배제. 결과: 로그인 직후 무한 `/login → /dashboard → /login` 루프.
- **Lax 채택 안전성**: CSRF 방어는 여전히 충분 — 외부 사이트의 form POST/AJAX는 Lax 쿠키 미포함(state-changing 요청 차단). 차이는 "외부 링크 클릭으로 들어온 GET 네비게이션 시 쿠키 포함" — auth 흐름 정상 동작.
- **재검토 시점**: 외부 보안 audit 또는 Story 8 운영 hardening. 대안(HTML+JS redirect로 chain 끊기)은 UX 저하 + 코드 복잡도 증가로 미채택.

## Deferred from: code review of 1-3-약관-개인정보-동의 (2026-04-28)

- **W1 — `/v1/legal/{type}` rate limit 미적용** — public endpoint scrape/DoS 가능. 사유: Completion Notes deferred 1번 등재, Story 8 polish에서 slowapi 데코레이터 일괄 도입.
- **W2 — `/v1/legal/{type}` Cache-Control / ETag 미설정** — 모바일은 cold start마다 fetch, CDN 캐시 미활용. 사유: Story 8 polish — 캐시 정책은 Story 4.3(주간 리포트) RSC ISR 검증 후 일괄 결정.
- **W3 — OpenAPI 응답 코드 (201/400/401/409) 미선언** — `submit_consents`는 201/200/400/401/409, `legal` 라우터는 400/422 가능하지만 자동 생성된 client(`web/src/lib/api-client.ts`, `mobile/lib/api-client.ts`)는 200/422만 노출. 사유: Story 1.2 패턴 정합(전 라우터 동일 한정), cross-cutting cleanup으로 Story 8 일괄 처리.
- **W4 — 버전 bump 시 자동 재동의 트리거 부재** — 운영자가 `_VERSION_KO`만 바꾸면 모든 활성 사용자가 즉시 `basic_consents_complete=false`로 차단됨(운영 폭탄). 사유: Completion Notes deferred 2번, 마이그레이션 전략(공지·단계적 강제) 결정 후 운영 SOP에 반영.
- **W5 — `require_basic_consents` DB error → typed 5xx 매핑 미적용** — `db.execute` 실패 시 raw exception으로 500. 사유: cross-cutting, Story 8 운영 hardening.
- **W6 — soft-deleted user 복원 시 stale consents row 사용 가능** — `users.deleted_at` 마킹만 하고 `consents` row 보존 → 복원 시 fresh PIPA assent 누락. 사유: Story 5.x(회원 탈퇴 + 30일 grace) 책임 영역.
- **W7 — Mobile onboarding이 `?next=` 미독해** — `(tabs)/_layout.tsx`가 next 쿼리는 보존하지만 onboarding 화면들이 읽지 않음. 사유: spec AC2 line 31에 *Story 1.6 온보딩 완료 후 복귀에서 활용* 명시.
- **W8 — `consent.basic.missing` 클라이언트 인터셉터 부재** — `require_basic_consents`가 wire되면 사용자가 raw 403만 보고 onboarding 진입 경로 못 찾음. 사유: Story 1.5+ 라우터 wire 시점에 인터셉터 추가.
- **W9 — typed-route cast workaround (`as Parameters<typeof router.push>[0]`)** — Expo Router typed-routes 캐시 재생성 트리거를 위한 임시 우회. 사유: PR 머지·캐시 정상화 후 정리. 잔존 시 settings 경로 변경 시 컴파일러 검출 안 됨.
- **W10 — `request.client.host` proxy 헤더 처리 미적용** — Gemini Code Assist medium 코멘트(PR #5 #discussion_r3153082820). PIPA audit IP가 reverse-proxy 사설 IP로 통일됨. 사유: Story 1.2 W2 deferred 정합 — 운영 토폴로지(Railway/Cloud Run/직접 LB) 결정 후 trusted proxy 화이트리스트와 함께 일괄 도입.
- **W11 — spec Tasks 5.2/5.3/5.4 본문 stale** — Task 5.2 "version mismatch 422", Task 5.3 "/v1/legal/invalid 404", Task 5.4 "4 cases" — implementation은 AC를 따라 409·400·6 cases로 올바르나 task text가 stale. 사유: D1 결정 시 일괄 정비.
- **W12 — middleware JWT 시그니처 검증 불가** — `hasValidLookingCookie`는 길이만 체크. 위조 쿠키로 onboarding GET 한 번 통과 가능(RSC가 bounce). 사유: Edge runtime crypto 제약 + Story 1.2 정합 패턴 — RSC 책임으로 분리.
- **W13 — `ConsentVersionMismatchError` 409에 `X-Consent-Latest-Version` 헤더 미포함** — 클라이언트는 status만 보고 latest version 추론 불가, 추가 round trip 필요. 사유: UX nice-to-have, Story 1.4가 같은 패턴으로 추가 시 일괄 도입.
- **W14 — `require_basic_consents` 라우터 wire 미적용** — `app/api/deps.py`에 정의되어 있으나 어떤 라우터에도 Depends 등록 안 됨. 사유: spec AC11 명시 — 본 스토리는 *함수 정의 + 단위 테스트*만, Story 1.5(`POST /v1/users/me/profile`) / Story 2.1+(`/v1/meals/*`)이 명시 적용.
- **W15 — CSRF 방어 명시 검증 미수행** — Web POST `/v1/users/me/consents`가 cookie 인증 + body POST. 사유: Story 1.2 `Spec deviation: SameSite=Lax` 정합 — Lax 쿠키가 cross-site form POST 차단. 외부 보안 audit 시 재검토.

## Deferred from: code review of 1-4-자동화-의사결정-동의 (2026-04-28)

- **W0 (D1 결정) — 백엔드 `POST /automated-decision`에 `require_basic_consents` 게이트 미적용** [`api/app/api/v1/consents.py:285-321`] — 스펙 AC3 가 INSERT 분기 basic 4 컬럼 NULL 허용을 *명시*("이론상 불가 — 본 화면 진입 가드가 basic 4종 통과 강제"), 직접 API 호출 시 `basic_consents_complete=false` + AD granted 인 일관성 깨진 row 생성 가능 + Anti-pattern catalog (line 535) 모순. 사유: 본 스토리는 데모 sales tool 범위, 프론트엔드 가드로 충분; 직접 API 호출 보호는 운영 hardening 영역 — Story 8(운영 hardening) 또는 외부 보안 audit 시 재검토. 도입 시 새 에러 클래스 `BasicConsentsMissingError(409)` + AC3 수정 + Mobile `extractSubmitErrorMessage` 처리 (P8 와 함께) 일괄.
- **W1 — `request.client.host` 원시 IP** [`api/app/api/v1/consents.py:1061`] — proxy/LB 뒤에서 PIPA audit 가 LB IP 로 통일됨. 사유: Story 1.2 W2 / Story 1.3 W10 정합 — 운영 토폴로지(Railway/Cloud Run/직접 LB) 결정 후 trusted proxy 화이트리스트와 함께 일괄 도입 (Story 8 운영 hardening).
- **W2 — Migration downgrade `op.drop_column` 이 PIPA audit 영구 파괴** [`api/alembic/versions/0004_consents_automated_decision.py:806-810`] — 동의/철회 timestamp + version 손실. 사유: alembic 표준 패턴 (downgrade 가 destructive 인 것은 일반적). Story 8 운영 SOP 에 "PIPA 보존 의무 관련 동의 마이그레이션 downgrade 금지" 명시. NotImplementedError 가드는 운영 SOP 결정 후 도입.
- **W3 — `datetime.now(UTC)` (Python) vs `func.now()` (Postgres) 타임스탬프 drift** [`api/app/api/v1/consents.py:1056-1083, 1109-1113`] — 같은 row 내 `automated_decision_consent_at` (Python) 과 `updated_at` (DB) 에 ms 수준 시계 차이 발생 가능. 사유: Story 1.3 carry-over 패턴 — DB-only(`func.now()`) 또는 Python-only(`datetime.now(UTC)`) 통일은 Story 8 일괄 정리.
- **W4 — `conftest.consent_factory` 가 항상 `CURRENT_VERSIONS["automated-decision"]` 평가 — leaky coupling** [`api/tests/conftest.py:1448`] — `ad_version = automated_decision_version or version or CURRENT_VERSIONS["automated-decision"]`. 향후 SOT 키 rename/제거 시 Story 1.3 호환 테스트 import 만으로 KeyError. 사유: 테스트 인프라 cleanup, 다음 SOT 변경 시 일괄.
- **W5 — `legal_documents` dict missing key 시 raw `KeyError` → 500** [`api/app/domain/legal_documents.py`] — `LEGAL_DOCUMENTS[(doc_type, lang)]` 가 미존재 키일 때 raw KeyError 가 500 으로 surface, fastapi 의 404 매핑 미적용. 사유: Story 1.3 패턴 정합. Story 8 cross-cutting cleanup 에서 KeyError → `LegalDocumentNotFoundError` 매핑 일괄.
- **W6 — OpenAPI client kebab-case migration note 누락** — `automated-decision` (hyphen) 으로 path/Literal 통일했으나 캐시된 underscore 버전 클라이언트는 422 만 반환. 사유: 빌드 산출물 — README "OpenAPI 클라이언트 재생성 SOP" 단락에 kebab-case 마이그레이션 주의사항 추가 (Story 8.3 인수인계 SOP 정합).
- **W7 — `scalar_one()` 가 concurrent CASCADE delete 시 uncaught `NoResultFound` → 500** [`api/app/api/v1/consents.py:1086-1090`] — UPSERT 직후 refresh select 사이에 user 계정 삭제 시 NoResultFound 가 raw 500 으로 노출. 사유: 일반 SQLAlchemy 패턴 — Story 1.3 W5 (typed 5xx 매핑) 와 함께 Story 8 운영 hardening 에서 일괄 처리. 발생 빈도 극히 낮음(시간차 ms 수준 race).

## Spec deviation: logout endpoint (2026-04-28, PR #2 review followup)

- **AC5 spec**: 모바일은 `Authorization: Bearer <access>` + body `{refresh_token}` 두 필드 동시 전송 (logout 시 access token 검증).
- **실제 구현**: refresh-only — `current_user` Depends 미사용. body / 쿠키의 refresh token sha256 hash 매칭 row만 revoke.
- **사유 (PR #2 Gemini Code Assist review comment #2 거부 결정)**:
  1. **만료 세션 강제 종료 보존**: access token 만료된 사용자가 logout 시도 시 `current_user` Depends가 401 발사 → 클라이언트 인터셉터가 refresh 시도 → 또 만료면 logout 자체 불가. *세션 정리* 흐름이 깨진다. refresh-only는 만료 세션도 정상 logout 가능.
  2. **CSRF 방어는 별도 layer**: JSON body 요구(`Content-Type: application/json` + `{refresh_token}` 필드)로 form POST CSRF 차단 + SameSite=Lax 쿠키. logout-CSRF 위협 모델은 *피해자 강제 로그아웃*(annoyance 수준) — refresh token 본인만 알기에 무차별 발사 불가.
  3. **refresh token = 본인 식별자**: 평문 32-byte URL-safe random + DB sha256 매칭. token 보유자만 logout 가능 — access token 검증과 동등한 보증.
- **재검토 시점**: 외부 보안 audit / 외주 클라이언트 보안 요구사항 변경 시. 또는 Story 5.x(전체 디바이스 로그아웃) 도입 시점에 access token 검증 layer 추가 검토.

## Deferred from: code review of 1-5-건강-프로필-입력 (2026-04-29)

- **W15 — Pre-existing `role IN ('user','admin')` text 리터럴 CHECK** [api/app/db/models/user.py:94] — Story 1.2 패턴, 본 스토리 외. role enum 도입 시 일괄 처리.
- **W16 — `POST /v1/users/me/profile` per-user rate limit 미설정** [api/app/api/v1/users.py:127] — slowapi 운영 polish, Story 8 hardening.
- **W17 — Web cookie auth CSRF 보호 미명시** — `bn_access` SameSite=Lax 채택 + 명시 CSRF 미들웨어 없음. project-wide cross-cutting (Story 8).
- **W18 — Migration이 `app.domain.*` import (replay safety vs SOT-sync)** — spec 결정으로 SOT 우선 채택. 향후 22종 변경 cron(Story 8 R8 SOP)과 함께 재검토.
- **W19 — Migration 0005 downgrade가 사용자 health 데이터 silent drop** [alembic 0005 downgrade] — 운영 rollback runbook (Story 8). 실제 운영 전 backup 절차 명시 필요.
- **W20 — Web `HealthProfileForm` AbortController 미적용** — Task 7.5 명시 deviation (`isSubmitting`로 차단 충분). Story 8 polish 또는 메모리 누수 이슈 발견 시 도입.
- **W21 — Mobile `inflightRef` unmount cleanup + AbortController** — react-hook-form `isSubmitting` 우선, Story 8 polish.
- **W22 — `extra="forbid"` 클라이언트 진화 우려** — 각 endpoint 명시 contract 결정 유지. 7번째 입력 필드 추가 시 OpenAPI 재생성 + 양 클라이언트 deploy chain 검토.
- **W23 — `field_validator` + `default_factory` 상호작용 명시 미흡** — 현 동작 OK (`[]` default가 `normalize_allergens([])`를 우회하나 결과 동일). Pydantic strict 모드 전환 시 재검토.
- **W24 — BMR/TDEE float precision drift** [api/app/api/v1/users.py:100, weight_kg float 변환] — Story 3.x BMR 도입 시점 결정 (Decimal 직접 사용 vs float wire format).
- **W25 — `extractSubmitErrorMessage` 429/413 분기 부재** [mobile profile.tsx + web HealthProfileForm.tsx] — rate limit (W16) 도입 후 polish.
- **W26 — Web onSubmit catch-all이 비-network 에러 swallow** [web HealthProfileForm.tsx:84-86] — 진단 polish, AbortError/TypeError 분기.
- **W27 — Mobile `pathname` open-redirect 잠재성** [mobile/app/(tabs)/_layout.tsx:57] — Expo Router pathname 안전 가정. Story 1.6 `?next=` 처리(W7) 시 일괄 whitelist.
- **W28 — Test `body["weight_kg"] == 70.5` exact float 비교** [api/tests/test_users_profile_router.py 다수] — Pydantic v3 마이그레이션 시점 polish (`pytest.approx`).
- **W29 — Activity color spectrum 녹색 일색** [mobile healthProfileSchema.ts:75-81] — NFR-A4는 텍스트 라벨로 충족, design polish.
- **W30 — `+'20'` opacity hex hack** [mobile profile.tsx:198, 241] — design system 도입 시점 일괄 정리.
- **W31 — `ProfileSubmitError` 위치인자 생성자** [mobile useHealthProfile.ts:14-26] — API 갱신 시 object param으로 변경.
- **W32 — `Numeric(5,1)` 상한과 CHECK 500.0 mismatch (defense-in-depth)** [alembic 0005] — Numeric(5,1)은 max 9999.9, CHECK는 500.0. 현 동작 무영향, 정밀도 명세 명시 시점에 일괄 정리.

## Deferred from: code review of 1-6-온보딩-튜토리얼 (2026-04-29)

- **W33 — `?next=` 쿼리 forward + 처리** [mobile/app/(auth)/onboarding/tutorial.tsx Redirect, mobile/app/(tabs)/_layout.tsx:58-62] — onboarding 모든 화면이 forward만 수행, 처리 X. tutorial.tsx도 `<Redirect href={PROFILE_ROUTE} />`로 next 미전파, `setTutorialSeen` 후 `router.replace(PROFILE_ROUTE)`도 동일. Story 1.3 W7 재deferred(spec deferred-work 명시) — Story 5.1 또는 Story 8 polish 시점에 일괄 whitelist + 처리.
- **W34 — 단일 디바이스 다중 사용자(family/employee) tutorial-seen 격리** [mobile/lib/auth.tsx, tutorialState.ts] — A signOut 없이 B signIn 시 A의 seen flag 상속해 B에게 tutorial 강제 스킵. Spec Story 8 polish 명시. 재검토 시점에 user_id-suffix 키(`bn:onboarding-tutorial-seen-{user_id}`) 또는 signIn 시점 clear 정책 도입.
- **W35 — Color contrast WCAG AA 검증** [mobile/app/(auth)/onboarding/tutorial.tsx 색상값 #666·#1a73e8] — Skip 텍스트 #666 on #fff ~5.7:1, primary 버튼 #fff on #1a73e8 ~4.7:1로 WCAG AA borderline. Design system 도입(Story 8) 시점에 일괄 정리.
- **W36 — `asyncio.sleep(0.05)` flaky test smell** [api/tests/test_users_profile_router.py:243] — Postgres `NOW()` 50ms 내 advance 가정. 부하된 CI에서 `profile_completed_at` 동등 비교 깨질 가능성. Deterministic clock fixture(`freezegun`) 도입 시점에 polish.
- **W37 — `app.state.session_maker` 직접 접근(fixture isolation 우회)** [api/tests/test_users_profile_router.py:270 등] — 글로벌 app state 결합. 향후 request-scope DI refactor 시 4 신규 케이스 silent 회귀. 테스트 infra refactor 시점.
- **W38 — 로그 이벤트명 `users.profile.updated` 첫 onboard vs profile edit 미구분** [api/app/api/v1/users.py:194] — 다운스트림 로그 분석이 boolean field 파싱 의존. 별도 `users.onboarded` 이벤트 분리는 Story 7 audit 정제 시점.
- **W39 — `handleNext` last-slide pre-`isLast` render gap** [mobile/app/(auth)/onboarding/tutorial.tsx:73-78] — `currentIndex` state 갱신과 `isLast` 파생 상태 사이 race. *다음* 탭이 last-slide 직전 시점에 떨어지면 finish 미실행. minor.
- **W40 — `finish()` 도중 unmount → setState 또는 storage write race** [mobile/app/(auth)/onboarding/tutorial.tsx:46-53, 80-83] — `cancelled` 가드는 `setSeenChecked`만 보호, `finish()`의 `setTutorialSeen` write는 unmount 후에도 진행. minor.
- **W41 — Concurrent first-POST 시 audit 로그 `first_time=True` 2회 발사** [api/app/api/v1/users.py:175] — DB COALESCE는 atomic이나 ORM 캐시값 읽고 로그만 cosmetic. Story 7 audit 정제 시점.

## Deferred from: code review of 2-1-식단-텍스트-입력-crud (2026-04-29)

- **W42 — `MealError` base 클래스 추상 가드 / 기본 status 재고** [api/app/core/exceptions.py:381-385] — `MealError(BalanceNoteError)` base가 `status=500 / code="meals.error"`로 선언, 단 어떤 코드도 base를 직접 raise하지 않음. Story 2.2(R2 업로드 실패) / 2.3(OCR 장애) / 2.5(큐잉 실패)에서 동일 base 하위 sub-error 추가 시 base 직접 instantiation 회귀 가능. `if type(self) is MealError: raise TypeError(...)` 또는 base default를 400으로 변경. 사유: forward 전용, 본 스토리 reachable 경로 0건. Story 8 hardening.
- **W43 — `_parseProblem` JSON 파싱 실패 시 raw text 보존 X (디버그 가시성)** [mobile/features/meals/api.ts:1773-1782] — 500 응답이 HTML 에러 페이지면 `_parseProblem`이 빈 객체 반환 → 사용자는 "오류가 발생했습니다 (500)"만 노출, Sentry/log telemetry에 raw text 부재. raw text를 debug 필드에 capture. 사유: Story 8 cross-cutting observability polish.
- **W44 — soft-deleted row content 변경 차단 trigger/CHECK 부재** [api/alembic/versions/0006_meals.py] — 현 라우터는 `deleted_at IS NULL`을 PATCH/DELETE WHERE 절에 강제하나, 직접 SQL 또는 ORM bypass 시 soft-deleted row의 `raw_text`/`ate_at` 변경 가능. `BEFORE UPDATE` trigger로 `OLD.deleted_at IS NOT NULL AND (NEW.raw_text <> OLD.raw_text OR NEW.ate_at <> OLD.ate_at)` 시 RAISE. 사유: defense-in-depth, 본 스토리 reachable 경로 0건. Story 8 hardening.
- **W45 — 부분 인덱스 (`idx_meals_user_id_ate_at_active`) 사용 EXPLAIN 검증 부재** [api/tests/test_meals_router.py] — 본 스토리 baseline은 정합성/회귀 테스트 22건. 향후 마이그레이션이 인덱스 조건/컬럼 변경 시 silent 성능 회귀 가능. `EXPLAIN (FORMAT JSON)` 기반 perf smoke 1건 추가. 사유: Story 8 perf hardening 또는 사용자 식단 1k+ 누적 후 성능 이슈 surface 시.
- **W46 — 앱 백그라운드/킬 mid-mutation 시 중복 POST** [mobile/features/meals/api.ts `useCreateMealMutation`] — 사용자가 "저장" 탭 후 OS가 앱을 background → 메모리 회수로 kill, 사용자 재개 후 재시도 시 같은 식단 2 row 생성 (서버는 `Idempotency-Key` 헤더 *수신*만 허용, 처리 X — AC2 정합). 사유: Story 2.5(오프라인 텍스트 큐잉) offline-queue.ts + `meals.idempotency_key UNIQUE` 컬럼 + 409 분기 일괄 도입 시 흡수.
- **W47 — `setError("raw_text", ...)` 미사용 (스펙 wording deviation)** [mobile/app/(tabs)/meals/input.tsx, MealInputForm.tsx] — 스펙 AC8 line 135은 400 응답 시 `setError("raw_text", { message })`로 RHF 필드-에러 API 사용 명시. 현 구현은 `setServerError(state)` + 별도 텍스트 렌더링 — 기능 동등이나 RHF `formState.errors` 통합 미활용(다음 입력 시 자동 클리어 등). 사유: P14(serverError 자동 클리어) 적용 후 추가 polish 가치 낮음, design polish 또는 RHF 통일 시점에 일괄.
- **W48 — `_create_meal_for(user)` 픽스처가 동의 게이트 우회 (의도 코멘트 부재)** [api/tests/test_meals_router.py:557-576] — `test_patch_meal_blocks_user_without_basic_consents_returns_403`은 동의 없는 사용자에게 직접 ORM insert로 meal 생성 후 PATCH 403 검증 — production에서는 같은 사용자가 *애초에* meal 생성 불가(POST에서 403). 시나리오 incoherent하나 dependency wiring 회귀 차단 목적은 유효. 의도 명시 코멘트 1줄 추가. 사유: 테스트 인프라 cleanup, Story 8 또는 메모이제이션 픽스처 도입 시점.
- **W49 — `MealCard.formatHHmm` 디바이스 로컬 TZ 사용 (D1 결정에 종속)** [mobile/features/meals/MealCard.tsx:14-21] — `new Date(isoString).getHours()/getMinutes()`는 디바이스 TZ 기반 — 한국 사용자가 LA 출장 시 PST로 표시. 본 스토리 baseline에서 *정확한 KST pin* 의무 미명시. 사유: D1(date filter wire 시맨틱) 결정 시 wire TZ 정책에 정합 — KST 강제 시 `Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', ... })` 일괄 적용.
- **W50 (D1 결정) — `from_date`/`to_date` wire 시맨틱 KST/UTC 드리프트** [api/app/api/v1/meals.py GET /v1/meals + mobile/app/(tabs)/meals/index.tsx] — 모바일은 디바이스-로컬(`Date.getDate()`)로 "today"를 KST 형식 문자열 송신, 서버는 `date` 타입을 Postgres 세션 TZ(=UTC)로 캐스팅 → KST 0–9시 식사 *제외*. 사유: Story 2.4(*일별 식단 기록 화면*)가 7일/30일 history + 날짜 picker 도입하면서 wire를 timestamptz 또는 `tz` 쿼리 파라미터로 재설계할 책임 영역. 본 스토리 baseline에서 wire 변경은 throwaway 작업. 옵션 일괄 검토(timestamptz wire / `tz` query / 클라이언트 UTC 강제)는 Story 2.4 spec에 명시.
- **W51 (Gemini PR #10 review) — `users.py` `suppress(Exception)` 광범위 제거 (P16 cross-cutting)** [api/app/api/v1/users.py 일대] — Story 2.1 CR P16에서 `meals.py`의 `with contextlib.suppress(Exception):` 로거 가드를 *관측성 silent 차단 방지* 사유로 제거. Gemini 봇은 같은 패턴이 `users.py`(Story 1.5/1.6 코드)에도 잔존함을 지적, 일관성 확보 권장. 사유: 본 PR은 Story 2.1 범위 한정, cross-cutting 패턴 정합은 별도 polish PR (Story 8 hardening 또는 follow-up issue)에서 일괄. 검증 필요 — `git grep -n "suppress(Exception)" api/app` 으로 잔존 위치 식별 후 각각 None guard 또는 specific exception type으로 좁히기.

## Deferred from: Story 2.3 implementation (2026-04-30, OCR Vision + 확인 카드)

- **DF4 — Vision 모델 cost cap 부재** [api/app/adapters/openai_adapter.py] — `gpt-4o` 호출당 ~$0.005-0.01 + 일일 100건 cap 미적용. 영업 데모는 *짜장면+군만두 ~3 photos/day* 가정이라 cost 미미하나 사용자 다수 시 폭증 가능. **재검토 시점**: Story 8 polish — R6 cost alert(`daily-cost-alert.yml`) + 일일 호출 횟수 cap + Redis 통계 + 임계값 알림. 또는 `gpt-4o-mini` 다운그레이드 옵션. *DF2 자연 해소* 일환으로 본 스토리에서 `gpt-4o`를 정확도 우선 채택했으므로 비용 폭발 risk는 일관된 매트릭(latency_ms, items_count) 기반 후속 모니터링 필요.
- **DF5 — Vision 응답 결정성 부족** [api/app/adapters/openai_adapter.py:VISION_MODEL] — `temperature=0.0` 강제이나 *같은 사진 재호출 시 다른 응답* 가능 (모델 내부 비결정성). 사용자 *"OCR 다시 분석"* CTA 시 결과 변동 잠재 — 캐시(`cache:llm:{sha256(image_key)}`) 도입으로 결정성 보장. **재검토 시점**: Story 8 perf hardening 시점 — DF6과 함께.
- **DF6 — Vision 응답 캐시 부재** [api/app/api/v1/meals_images.py POST /parse] — 같은 image_key 재 parse 호출 시 매번 OpenAI 호출 + 비용 + 지연. Redis `cache:llm:{sha256(image_key)}` 24h TTL 도입. **재검토 시점**: Story 8 perf hardening + DF5와 함께 결정성/cost 동시 해결.
- **DF7 — `parsed_items` 음식명 정규화 미적용** [meals.parsed_items jsonb] — Vision이 *"자장면"* / *"짜장면"* / *"jajangmyeon"* 변형 출력 가능. 본 스토리는 *raw 출력 그대로 영속화*만. **재검토 시점**: Story 3.4 — 음식명 정규화 + `food_aliases` 매칭으로 일괄 처리.
- **DF8 — `parsed_items` 알레르기 자동 검출 미적용** — Vision이 *"새우"* 추출 시 알레르기 사용자 자동 경고 부재. **재검토 시점**: Story 3.5(fit_score + 알레르기 단락) 책임.
- **DF9 — Vision 환각 사례 모니터링 부재** — *"사용자 얼굴: 30대 남성"* 등 PII 출력 시도는 structured outputs로 차단되나 *"음식이 아닌 사물"*(예: 책 사진을 *"흰쌀밥"*으로 인식)은 차단 X. confidence 임계값 0.6 + 사용자 확인 카드로 1차 방어. **재검토 시점**: Story 3.8 LangSmith 평가 데이터셋 도입 시 환각률 측정.
- **DF10 — `OCRConfirmCard` 모달 vs inline 결정 미명시** [mobile/features/meals/OCRConfirmCard.tsx] — 본 스토리는 *inline*(form 대체) 채택. 모달 UX(반투명 backdrop + 외부 탭 dismiss)는 baseline OUT. **재검토 시점**: Story 8 polish 또는 사용자 피드백.
- **DF11 — `OCRConfirmCard` lowConfidence forced confirmation UX 검증 미실시** — 사용자가 *"이대로 진행"* 버튼 누르고 환각 항목 그대로 저장하는 *opt-out 시나리오* 측정 부재. **재검토 시점**: W8 데모 또는 Growth 단계 정량 평가.
- **DF12 — Vision 한국어 외 언어 대응 미적용** — 영문/일본어 메뉴판 사진은 *"jajangmyeon"* 또는 *"ジャージャー麺"* 출력 가능 — 한국어 정규화 SOP 부재. **재검토 시점**: 외주 인수 클라이언트 다국가 시점 (NFR-L4 Growth).
- **DF13 — `parsed_items` jsonb GIN 인덱스 부재** [meals.parsed_items 컬럼] — Story 2.4 일별 기록 검색 시 `parsed_items.name` LIKE 검색 도입 가능성 — 현재는 인덱스 부재로 sequential scan. **재검토 시점**: 검색 기능 도입 시 Story 8 perf hardening.
- **DF14 — `OCRConfirmCard` `confidence` 사용자 편집 시 1.0 강제 vs 명시 변경 UX** [mobile/features/meals/OCRConfirmCard.tsx] — *"+ 항목 추가"*는 confidence 1.0 강제이나 *기존 항목 name/quantity 편집* 시 confidence 그대로 — 사용자가 환각 항목을 정확하게 고친 경우에도 낮은 confidence 잔존. behavior tradeoff(편집된 항목은 사용자 확신 vs 원본 confidence 보존)는 baseline에서는 *원본 보존* 선택. **재검토 시점**: Story 3.5 fit_score 도입 시 confidence 활용 패턴 결정 후 일괄.
- **DF15 — `MealCard.tsx` `parsed_items` 표시 forward 미적용** [mobile/features/meals/MealCard.tsx] — Story 2.3 baseline은 *MealCard 변경 X* (Story 2.4가 일별 기록 화면 polish 시 *"인식: 짜장면 1인분, 군만두 4개"* 부제 추가). 본 스토리는 `MealResponse.parsed_items` 인터페이스 노출까지만. **재검토 시점**: Story 2.4 일별 기록 화면 polish.

## Deferred from: code review of story-2.3 (2026-04-30)

- **W1 — Vision 호출 client-side timeout/cancel 부재** [mobile/app/(tabs)/meals/input.tsx parseMealImage chain] — 백엔드 30s + tenacity 1회 retry로 60s까지 spinner 지속 — 사용자 escape 부재. AbortController + 35s 클라이언트 timeout + retry UI는 UX polish 영역. **재검토 시점**: Story 8 UX polish 또는 사용자 피드백 정량.
- **W2 — OpenAI SDK `client.beta.chat.completions.parse` GA 이동 시 fragile** [api/app/adapters/openai_adapter.py:155] — 현재 `beta.` 경로 채택 (spec 정합 + 2.32.0 alias 동작). 향후 SDK 버전이 `beta.` 제거 시 break — Completion Notes에 GA(`chat.completions.parse`) 마이그레이션 명시. **재검토 시점**: Story 8 dependency hardening 또는 SDK 신버전 도입 시점.
- **W3 — 같은 image_key parse 반복 호출 dedup/rate-limit 부재** [api/app/api/v1/meals_images.py POST /parse] — 호출당 새 Vision 호출 + cost 누적. 이미 DF6(Vision 응답 캐시 `cache:llm:{sha256(image_key)}` 24h TTL)와 통합 처리. **재검토 시점**: DF6과 동일 — Story 8 perf hardening.
- **W4 — `_get_client()` singleton API key 변경 무시** [api/app/adapters/openai_adapter.py:_get_client] — 첫 호출 시 캐시된 client는 settings 변경 후 재사용. runtime key rotation rare + `_reset_client_for_tests()` 우회 가능 → polish 영역. **재검토 시점**: 운영 시 key 회전 자동화 도입 시점.
- **W5 — `MealImageParseResponse` `extra="forbid"` 부재** [api/app/api/v1/meals_images.py:MealImageParseResponse] — request 모델은 `extra="forbid"`, response는 미설정. 응답 모델 일관성 polish. **재검토 시점**: Story 8 schema hardening.
