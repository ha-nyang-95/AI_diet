# Story 1.2: Google OAuth 로그인 + JWT user/admin 분리 + 로그아웃

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **엔드유저**,
I want **Google 계정으로 모바일·웹 양쪽에 가입·로그인하고 어디서나 로그아웃하기를**,
So that **비밀번호 별도 관리 없이 안전하게 진입하고 종료할 수 있다.**

부수적으로 본 스토리는 Epic 1-7 전체 횡단의 인증 인프라(JWT user/admin 분리·issuer claim 검증·refresh rotation·RFC 7807 401 응답·`current_user`/`current_admin` Depends)를 박는다. 이후 모든 보호 라우터(meals/analysis/admin/payments)가 본 스토리의 Depends를 import해 사용한다.

## Acceptance Criteria

> **BDD 형식 — 각 AC는 독립적 검증 가능. 모든 AC 통과 후 `Status: review`로 전환하고 code-review 워크플로우로 진입.**

1. **AC1 — Google OAuth Authorization Code + PKCE → user JWT 발급**
   **Given** Google 계정 보유 사용자, **When** 모바일(expo-auth-session, `responseType=code` + PKCE auto) 또는 Web(서버사이드 redirect)에서 *Google로 계속하기* 후 클라이언트가 `POST /v1/auth/google`(body: `{platform, code, redirect_uri, code_verifier}`) 호출, **Then** 백엔드가 (a) Google OAuth token endpoint와 code 교환 → id_token 획득, (b) `google-auth` 라이브러리의 `id_token.verify_oauth2_token(id_token, Request(), GOOGLE_OAUTH_CLIENT_ID)`로 검증(issuer ∈ {`accounts.google.com`, `https://accounts.google.com`}, audience = `GOOGLE_OAUTH_CLIENT_ID`, 만료 검증), (c) `email_verified=true` 확인, (d) `users` 테이블에 `google_sub` UPSERT(신규 가입 시 `created_at` 기록, 기존 사용자 시 `last_login_at` 갱신), (e) HS256 서명 user JWT(access 30일 + opaque refresh 90일) 발급.
   - id_token 검증 실패 / `email_verified=false` / Google 응답 4xx 시 401 RFC 7807 (`code=auth.google.id_token_invalid` 또는 `auth.google.email_unverified`).
   - access JWT claim: `sub=user_id`, `iss=JWT_USER_ISSUER` ("balancenote-user"), `aud="balancenote-api"` (수신 서비스 식별자 — 단일 값. platform 구분은 별도 `platform="mobile"|"web"` 커스텀 claim으로), `exp=now+30d`, `iat`, `jti`(UUIDv4), `role="user"|"admin"`(`users.role`).
   - refresh token: 32-byte URL-safe random(`secrets.token_urlsafe(32)`) — JWT 아님. DB에 `sha256(token)` 만 저장(평문 저장 금지).

2. **AC2 — 토큰 저장: 모바일 secure-store / Web httpOnly 쿠키**
   - **모바일** (`platform="mobile"`): 응답 body `{access_token, refresh_token, expires_in_seconds, user: {id, email, display_name, picture_url, role}}`. 클라이언트는 `expo-secure-store`(iOS Keychain / Android Keystore) `setItemAsync`로 저장. **`expo-secure-store` 외 저장소 사용 금지** — 특히 AsyncStorage/MMKV는 평문 저장이라 토큰 보관 절대 금지.
   - **Web** (`platform="web"`): 응답 status 200, body `{user: {...}}`. Set-Cookie 헤더 2개 자동 발급:
     - `bn_access=<jwt>; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=2592000` (30일)
     - `bn_refresh=<opaque>; HttpOnly; Secure; SameSite=Strict; Path=/v1/auth; Max-Age=7776000` (90일, refresh endpoint scope 한정)
     - **dev 환경(HTTPS 미사용)**: `Secure` flag 생략(`settings.environment in {"dev", "ci", "test"}`). 그 외 모든 경우 `Secure` 강제.
   - `localStorage` / `sessionStorage` / 일반 cookie(non-httpOnly) 저장 금지(NFR-S2 정합).

3. **AC3 — Admin role JWT 분리 발급(별 secret + 별 issuer claim, 8시간 만료, refresh 없음)**
   **Given** `users.role = "admin"` 사용자가 유효한 user JWT 보유, **When** `POST /v1/auth/admin/exchange` 호출 (header `Authorization: Bearer <user_jwt>`), **Then** admin JWT 1개 발급(body `{admin_access_token, expires_in_seconds: 28800}`).
   - admin JWT claim: `iss=JWT_ADMIN_ISSUER` ("balancenote-admin"), `aud="balancenote-admin"`, `exp=now+8h`, `role="admin"`, HS256 서명 secret = `JWT_ADMIN_SECRET`(`JWT_USER_SECRET`과 다른 값).
   - `users.role != "admin"` 사용자 호출 시 403 RFC 7807(`code=auth.admin.role_required`).
   - admin JWT는 refresh 없음. 8시간 후 재로그인 + 재교환 필요(NFR-S7).
   - Web 응답은 추가 cookie `bn_admin_access` (httpOnly + Secure + SameSite=Strict + Path=/v1/admin + Max-Age=28800) 동시 설정. 모바일은 응답 body로만.
   - **혼용 차단(critical):** `verify_user_token`은 `iss`가 user issuer인지 검증, `verify_admin_token`은 admin issuer 검증. 잘못된 issuer 토큰은 401 + `code=auth.token.issuer_mismatch`. 같은 사용자가 user 토큰을 admin 라우터에 보내면 통과하지 않는다.

4. **AC4 — 401 → refresh 1회 → 실패 시 로그아웃 (클라이언트 인터셉터)**
   **Given** 만료된 access 토큰 + 유효한 refresh 토큰 보유 사용자, **When** 임의 보호 endpoint(예: `GET /v1/users/me` — 본 스토리에서 신규 추가) 호출, **Then** 백엔드는 401 RFC 7807(`code=auth.access_token.expired`) 응답. 클라이언트(모바일 axios/TanStack Query interceptor + Web Next.js middleware/`fetch` wrapper)가 즉시 `POST /v1/auth/refresh`(모바일은 body로 refresh, Web은 `bn_refresh` 쿠키 자동) 호출 → 백엔드가:
     - refresh sha256 hash 비교, 미일치/만료/`revoked_at` 있음 → 401 + `code=auth.refresh.invalid`.
     - 일치 시 (a) 새 refresh 발급(rotation: `secrets.token_urlsafe(32)`), (b) 기존 row `revoked_at = now()` + `replaced_by = new_id` (재사용 탐지용), (c) 새 access JWT 발급, (d) 응답.
     - 같은 (이미 revoked된) refresh가 다시 들어오면 token-replay로 간주 — 해당 family(rotation chain 단위 — 한 사용자가 여러 디바이스에서 로그인하면 family도 여러 개) 전체 row 즉시 revoke + 401(`code=auth.refresh.replay_detected`). 다른 family(다른 디바이스)는 영향 없음. [OWASP Refresh Token Reuse Detection]
   - refresh 성공 시 클라이언트는 원 요청 1회 자동 재시도. 실패 시 로컬 토큰 클리어(`expo-secure-store` `deleteItemAsync` + Web cookie expire) + `/login` 라우팅.
   - admin JWT는 refresh 미지원 — 401 시 즉시 admin 로그인 화면(`/admin/login`)으로 라우팅. 자동 재시도 없음.
   - **재시도 한도 1회**: refresh 실패 후 동일 401에서 추가 refresh 시도 금지(인터셉터 무한 루프 차단).

5. **AC5 — 로그아웃 endpoint + 클라이언트 정리**
   **Given** 로그인 사용자, **When** `POST /v1/auth/logout` 호출 (모바일 `Authorization: Bearer <access>` + body `{refresh_token}`, Web 쿠키 자동), **Then** 백엔드가:
     - 제출된 refresh 토큰의 sha256 hash 매칭 row를 찾아 `revoked_at = now()` 마킹.
     - 동일 사용자의 다른 활성 refresh 모두 유지(other-device 정책 — *현재 디바이스만 로그아웃*).
     - Web 응답에 `Set-Cookie: bn_access=; Max-Age=0` + `bn_refresh=; Max-Age=0` + `bn_admin_access=; Max-Age=0`.
     - 응답 status 204 No Content.
   - 클라이언트는 응답 받으면 (mobile) `expo-secure-store` 두 키 삭제 + 라우터 `/login` 이동, (web) 쿠키는 서버가 expire 처리 + 클라이언트 라우팅 `/login`.
   - access 토큰은 stateless JWT라 서버 측 무효화 없음(만료까지 유효). refresh 무효화로 새 access 발급 차단됨이 본 흐름의 보장. *전체 디바이스 로그아웃은 본 스토리 OUT — Story 5.x 또는 사용자 요청 시 별도 endpoint*.

6. **AC6 — 로그아웃 후 보호 라우트 진입 시 자동 로그인 redirect**
   **Given** 로그아웃 직후 사용자, **When** 모바일 라우터가 `(tabs)/...` 보호 라우트 또는 Web `/(user)/...` / `/(admin)/...` 보호 라우트 진입 시도, **Then**:
     - **Mobile**: `app/index.tsx` 인증 분기가 `expo-secure-store`에서 access 토큰 부재 확인 → `Redirect href="/(auth)/login"`. `(tabs)/_layout.tsx`도 동일 가드.
     - **Web**: `src/middleware.ts`가 `bn_access` 쿠키 부재 시 `NextResponse.redirect("/login")` (matcher: `/(user)/:path*`, `/(admin)/:path*`). admin 영역 추가 가드: `bn_admin_access` 쿠키 부재 시 `/admin/login` redirect.
   - 보호 라우트 진입 직접 URL을 `?next=` 쿼리로 보존 → 로그인 후 복귀.

7. **AC7 — `users` + `refresh_tokens` Alembic 마이그레이션 + SQLAlchemy 모델**
   - `alembic revision -m "0002_users_and_refresh_tokens"` 생성.
   - `users` 테이블 컬럼:
     | 컬럼 | 타입 | 제약 |
     |------|-----|-----|
     | `id` | `uuid` | PK, default `gen_random_uuid()` |
     | `google_sub` | `text` | UNIQUE NOT NULL |
     | `email` | `text` | NOT NULL (중복 허용 — 동일 이메일 재가입 케이스 단순화는 Story 5.x) |
     | `email_verified` | `boolean` | NOT NULL DEFAULT false |
     | `display_name` | `text` | NULL 허용 |
     | `picture_url` | `text` | NULL 허용 |
     | `role` | `text` | NOT NULL DEFAULT `'user'` + CHECK `role IN ('user','admin')` (Story 5/7에서 `users_role_enum` Postgres enum으로 마이그레이션 가능, 현재는 CHECK로 시작 — 8주 일정 정합) |
     | `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |
     | `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |
     | `last_login_at` | `timestamptz` | NULL 허용 |
     | `deleted_at` | `timestamptz` | NULL 허용 (FR5 회원 탈퇴 — Story 5.2가 활용) |
     | `onboarded_at` | `timestamptz` | NULL 허용 (Story 1.6이 갱신) |
   - 인덱스: `idx_users_google_sub` (UNIQUE 제약이 자동 생성), `idx_users_role` partial(`WHERE role = 'admin'`). **`idx_users_email`은 본 스토리 OUT** — google_sub로만 lookup하므로 현재 사용처 없음. admin 사용자 검색(Story 7.2)에서 필요해질 때 추가.
   - **알레르기/health_goal/체중/신장 컬럼은 본 스토리 OUT — Story 1.5에서 추가**(scope 분리, 마이그레이션 충돌 회피).
   - `refresh_tokens` 테이블 컬럼:
     | 컬럼 | 타입 | 제약 |
     |------|-----|-----|
     | `id` | `uuid` | PK, default `gen_random_uuid()` |
     | `user_id` | `uuid` | NOT NULL, FK → `users.id` ON DELETE CASCADE |
     | `token_hash` | `text` | NOT NULL UNIQUE (sha256 hex 64자) |
     | `family_id` | `uuid` | NOT NULL — token rotation chain 식별 (재사용 탐지용) |
     | `issued_at` | `timestamptz` | NOT NULL DEFAULT `now()` |
     | `expires_at` | `timestamptz` | NOT NULL |
     | `revoked_at` | `timestamptz` | NULL 허용 |
     | `replaced_by` | `uuid` | NULL 허용 (rotation 후 새 row id) |
     | `user_agent` | `text` | NULL 허용 (audit용 — 마스킹 X, 디바이스 식별만) |
     | `ip_address` | `inet` | NULL 허용 (audit용) |
   - 인덱스: `idx_refresh_tokens_user_id`, `idx_refresh_tokens_family_id`, `idx_refresh_tokens_token_hash` (UNIQUE).
   - SQLAlchemy declarative 모델은 `app/db/models/user.py`, `app/db/models/refresh_token.py`로 분리. `app/db/base.py`에 `Base = declarative_base()` 신규 생성. `app/db/session.py` (async engine + session_maker) 신규. Alembic `env.py`의 `target_metadata`를 `Base.metadata`로 갱신.
   - `alembic upgrade head` Docker 부팅 entrypoint에서 자동 실행 — Story 1.1 Dockerfile.api 패턴 그대로.

8. **AC8 — RFC 7807 Problem Details 글로벌 핸들러 + 인증 에러 코드 표준화**
   - `app/core/exceptions.py`에 다음 구현:
     - `ProblemDetail` Pydantic 모델 (fields: `type`, `title`, `status`, `detail`, `instance`, `code`).
     - 도메인 예외 계층: `BalanceNoteError(Exception)` → `AuthError(BalanceNoteError)` → `InvalidIdTokenError`, `EmailUnverifiedError`, `AccessTokenExpiredError`, `RefreshTokenInvalidError`, `RefreshTokenReplayError`, `IssuerMismatchError`, `AdminRoleRequiredError`. (Story 3+의 `ConsentMissingError`, `AllergenViolationError`, `LLMUnavailableError` 등은 별 스토리에서 추가)
     - 각 예외에 `to_problem(instance: str) -> ProblemDetail` 메서드. `code` 필드 매핑:
       - `auth.google.id_token_invalid` (401)
       - `auth.google.email_unverified` (401)
       - `auth.access_token.expired` (401)
       - `auth.access_token.invalid` (401, 서명 불일치 등)
       - `auth.refresh.invalid` (401)
       - `auth.refresh.replay_detected` (401)
       - `auth.token.issuer_mismatch` (401)
       - `auth.admin.role_required` (403)
   - `app/main.py`에 핸들러 3개 등록 — **등록 순서 중요**: `BalanceNoteError` → `RequestValidationError` → `HTTPException` 순. FastAPI가 가장 구체적인 핸들러를 먼저 매칭하므로 base class(`HTTPException`)를 마지막에 두지 않으면 `RequestValidationError`(서브클래스)가 잘못 가로채짐.
     - `@app.exception_handler(BalanceNoteError)` → `JSONResponse(status_code=..., content=ProblemDetail.dump(), media_type="application/problem+json")`.
     - `@app.exception_handler(RequestValidationError)` → 400 + `application/problem+json` + `code=validation.error` + `errors` 확장 필드(필드별 에러 배열).
     - `@app.exception_handler(HTTPException)` → 동일 변환(`code=http.<status>`). 단 framework 내부 예외는 status 그대로 보존.
   - 모든 401 응답은 `WWW-Authenticate: Bearer realm="balancenote", error="invalid_token", error_description="<detail>"` 헤더 동시 첨부 (RFC 6750 정합).
   - **Anti-pattern 차단**: 새 라우터에서 `raise HTTPException(401, "...")` 직접 사용 금지 — 도메인 예외 사용. ruff 룰 추가는 본 스토리 OUT, code-review에서 grep 검증.

9. **AC9 — `current_user` / `current_admin` Depends + `users.me` smoke endpoint**
   - `app/api/deps.py` 신규 생성, 다음 Depends export:
     - `async def get_db_session() -> AsyncSession` — `app.state.session_maker()` 사용
     - `async def current_user(authorization: str = Header(...), db: AsyncSession = Depends(get_db_session)) -> User` — Authorization 헤더 또는 `bn_access` 쿠키 둘 중 하나 우선순위(헤더 우선) → `verify_user_token` → DB에서 user 로드(`deleted_at IS NULL` 필터). 실패 시 `AccessTokenExpiredError` / `IssuerMismatchError` 등 raise.
     - `async def current_admin(...) -> User` — `verify_admin_token` 후 `role == 'admin'` 확인.
   - `app/api/v1/users.py` 신규 생성, smoke endpoint 1개:
     - `GET /v1/users/me` → `current_user`로 보호, 응답 `{id, email, display_name, picture_url, role, created_at, last_login_at, onboarded_at}`. snake_case wire format 준수.
   - `app/main.py`에 `app.include_router(auth_router, prefix="/v1/auth")` + `app.include_router(users_router, prefix="/v1/users")` 등록.
   - smoke endpoint 추가는 (a) 인증 통합 검증 + (b) 후속 스토리 라우터 패턴 reference 역할.

10. **AC10 — 모바일 로그인 화면 + secure-store + 인증 분기 라우팅**
    - 신규 파일:
      - `mobile/lib/secure-store.ts` — `setAccess(token)`, `getAccess()`, `setRefresh(token)`, `getRefresh()`, `clearAuth()`. 내부 `expo-secure-store` `WHEN_UNLOCKED` 옵션 사용.
      - `mobile/lib/auth.ts` — TanStack Query `QueryClient` + `fetch` 래퍼(401 → refresh 1회 → 재시도 인터셉터 — AC4 정합). React context `AuthContext`(`{user, isAuthed, signIn(), signOut()}`).
      - `mobile/features/auth/useGoogleSignIn.ts` — `expo-auth-session/providers/google`의 `useAuthRequest` 훅 래퍼. `responseType: ResponseType.Code` + PKCE auto + scopes `["openid", "email", "profile"]`. 성공 시 `code + redirect_uri + code_verifier`를 `POST /v1/auth/google` 전송 → 응답 토큰을 secure-store에 저장.
      - `mobile/app/(auth)/_layout.tsx` + `mobile/app/(auth)/login.tsx` — *Google로 계속하기* 버튼, 로딩 / 에러 상태 표준 표시.
      - `mobile/app/(tabs)/_layout.tsx` placeholder — 인증 분기용. `(tabs)/index.tsx`는 *"Story 1.5/2.1에서 채워짐"* placeholder만.
    - `mobile/app/_layout.tsx`를 갱신해 (a) `QueryClientProvider` + `AuthProvider` 래핑, (b) `Stack`에 `(auth)` 그룹과 `(tabs)` 그룹 등록.
    - `mobile/app/index.tsx` 갱신 — `getAccess()` 결과로 `<Redirect href="/(tabs)" />` 또는 `<Redirect href="/(auth)/login" />` 분기 (Story 1.1의 placeholder 텍스트는 제거).
    - `mobile/package.json`에 deps 추가: `expo-auth-session`, `expo-crypto`(PKCE 의존성), `expo-secure-store`, `@tanstack/react-query`. `pnpm install` 후 `pnpm-lock.yaml` 커밋.
    - `mobile/.env.example`에 `EXPO_PUBLIC_API_BASE_URL`, `EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_IOS`, `EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_ANDROID`, `EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_WEB` 추가(Expo Go 개발은 web client id 사용, 빌드는 native id).

11. **AC11 — Web 로그인 페이지 + 쿠키 인증 + Next.js middleware 가드**
    - 신규 파일:
      - `web/src/lib/auth.ts` — 서버 컴포넌트용 `getServerSideUser()` (cookie `bn_access` 디코드 X — 백엔드 `/v1/users/me` 호출로 검증). 클라이언트용 `useUser()` (TanStack Query).
      - `web/src/lib/api-fetch.ts` — `fetch` 래퍼, `credentials: "include"` 강제, 401 → `POST /v1/auth/refresh` 1회 → 재시도 인터셉터.
      - `web/src/lib/query-client.ts` — `QueryClient` 인스턴스 (TanStack Query).
      - `web/src/app/(public)/login/page.tsx` — *Google로 계속하기* 버튼 (`<a href="/api/auth/google/start">` 또는 클라이언트 컴포넌트). RSC 우선.
      - `web/src/app/api/auth/google/start/route.ts` — Google OAuth URL 생성 후 302 redirect (state + PKCE code_verifier 생성, httpOnly 쿠키 `bn_oauth_state` / `bn_oauth_pkce`에 임시 저장, **`SameSite=Lax`** + Max-Age=600). **Critical**: 두 임시 쿠키는 반드시 `Lax` — `Strict`로 설정하면 Google → 우리 callback redirect 시 쿠키가 차단되어 OAuth 흐름 자체가 깨진다 (cross-site top-level navigation). `Secure`는 prod에서 강제, dev는 분기.
      - `web/src/app/api/auth/google/callback/route.ts` — Google redirect 수신 → state 검증(쿠키와 비교 + 일회성 사용 후 삭제) → 백엔드 `POST /v1/auth/google` 호출 (서버사이드 fetch, code_verifier 동봉) → 백엔드 응답의 `set-cookie` 헤더를 읽어 Next.js `cookies().set(...)`로 사용자 브라우저에 forward → `/dashboard`(또는 `next` 쿼리) redirect. **Set-Cookie forwarding 패턴 의사코드**:
        ```ts
        const backendRes = await fetch(`${API_BASE_URL}/v1/auth/google`, { method: "POST", body: JSON.stringify(payload) });
        const setCookieHeaders = backendRes.headers.getSetCookie();  // Web Fetch API
        for (const sc of setCookieHeaders) {
          // 백엔드가 발급한 Set-Cookie를 그대로 응답에 echo (Next.js Response.headers.append)
          response.headers.append("set-cookie", sc);
        }
        ```
        백엔드는 자신의 도메인 기준으로 cookie를 발급 — Web 도메인이 다르면 백엔드가 보낸 그대로는 무효. **prod에서는 백엔드와 Web을 동일 등록 도메인**(예: `app.balancenote.app` Web + `api.balancenote.app` API + Set-Cookie의 `Domain=balancenote.app`)으로 맞춰 cookie share. dev에서는 Next.js route가 `cookies().set()`으로 직접 발급하는 방식이 마찰 적음.
      - `web/src/middleware.ts` — protected matcher `/(user)/:path*` 및 `/(admin)/:path*`, 쿠키 부재 시 `/login` 또는 `/admin/login` redirect.
    - `web/.env.example`에 `NEXT_PUBLIC_API_BASE_URL`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`(서버 전용), `GOOGLE_OAUTH_REDIRECT_URI` 추가.
    - `web/package.json`에 `@tanstack/react-query` 추가.
    - **next-auth 도입 절대 금지** — 백엔드 JWT를 httpOnly 쿠키로 직접 교환하는 architecture 결정 위반. `next-auth` 의존성 추가 시 code-review에서 차단.

12. **AC12 — 테스트 커버리지 + smoke 검증**
    - 백엔드 테스트(`api/tests/`):
      - `tests/test_auth_security.py` — `create_user_token`, `verify_user_token`, `create_admin_token`, `verify_admin_token` 단위 테스트(8건+). 정상 / 만료(`exp` 과거) / 잘못된 secret / 잘못된 issuer / 잘못된 audience / 잘못된 서명 알고리즘 / `role` claim 누락 등.
      - `tests/test_auth_router.py` — `POST /v1/auth/google`(Google 응답 mock with `respx` 또는 `monkeypatch`), `POST /v1/auth/refresh`(rotation + replay detection), `POST /v1/auth/logout`(refresh revoke), `POST /v1/auth/admin/exchange`(admin 통과 / 403). 신규 가입 + 기존 사용자 + admin 사용자 + email_verified=false 케이스 포함.
      - `tests/test_users_me.py` — `GET /v1/users/me` 인증 통과 / 401(토큰 부재) / 401(만료) / 401(issuer mismatch).
      - `tests/conftest.py` 갱신 — `user_factory(role="user"|"admin")` async fixture + `auth_headers(user)` helper.
    - 프론트 테스트는 본 스토리 OUT (Story 1.6 또는 Epic 8 polish에서 일괄). `tsc --noEmit` 게이트만 적용.
    - coverage gate: `--cov=app --cov-fail-under=70` 유지. 본 스토리 종료 시점에 `app/core/security.py`, `app/core/exceptions.py`, `app/api/deps.py`, `app/api/v1/auth.py`, `app/api/v1/users.py`, `app/db/models/user.py`, `app/db/models/refresh_token.py`, `app/adapters/google_oauth.py` 모두 측정 대상. `omit` 목록은 신규 placeholder가 없으므로 비움(Story 1.1의 `app/core/security.py`, `app/core/exceptions.py` omit 항목 제거).
    - smoke 통합 검증(local): `docker compose up` → mobile/web에서 실 Google 로그인(또는 stub) 1회 + `/v1/users/me` 200 응답 + 로그아웃 후 401 확인. 자동화 어려운 경우 README에 SOP 1단락 명시.

## Tasks / Subtasks

> 순서는 의존성 위주. 각 task는 AC 번호 매핑 명시. 백엔드 task → 프론트 task 순으로 파일럿 단위 PR 1개로 묶을 수 있다(epic 1에서는 단일 PR 권장).

### Task 1 — 의존성 추가 + Alembic 마이그레이션 (AC: #7)

- [x] 1.1 `cd api && uv add google-auth>=2.36` (id_token 검증). `python-jose[cryptography]`는 Story 1.1에서 이미 추가됨 — 추가 작업 없음. (Web OAuth state 쿠키는 Next.js 측에서 발급/검증 — `itsdangerous` 등 추가 의존성 불필요.)
- [x] 1.2 `api/pyproject.toml`의 `[[tool.mypy.overrides]]` `module` 리스트에 `google.*` 추가(deferred-work.md의 mypy override 정리와 동일 PR에서 처리 가능).
- [x] 1.3 `api/app/db/__init__.py`, `api/app/db/base.py`(`Base = declarative_base()`), `api/app/db/session.py`(`async_session_maker`) 신규 생성.
- [x] 1.4 `api/app/db/models/__init__.py`, `api/app/db/models/user.py`, `api/app/db/models/refresh_token.py` 신규 — SQLAlchemy 2.0 `Mapped[...]` 스타일 + `mapped_column(...)`. `__tablename__ = "users"` / `"refresh_tokens"` (snake_case 복수 — naming pattern 정합).
- [x] 1.5 `api/alembic/env.py`의 `target_metadata = None` → `target_metadata = Base.metadata` 갱신. import 순환 회피 위해 `app.db.models` 패키지 import 후 metadata 참조.
- [x] 1.6 `0002_users_and_refresh_tokens.py` 수동 작성 — partial index + CHECK 제약 + UUID server_default 모두 명시. Postgres 17 core `gen_random_uuid()` 사용.
- [x] 1.7 `alembic upgrade head` 로컬 검증 → 두 테이블 생성 확인. `alembic downgrade -1` → upgrade 재실행으로 idempotency 확인.

### Task 2 — JWT issue/verify + Google id_token 검증 (AC: #1, #3)

- [x] 2.1 `api/app/core/security.py` 채움 — placeholder 제거. 함수:
  - `create_user_token(user_id: UUID, role: str, platform: str) -> str` — HS256 + claim 명세대로.
  - `create_refresh_token() -> tuple[str, str]` — `(plaintext, sha256_hex)` 반환.
  - `verify_user_token(token: str) -> UserTokenClaims` — issuer/audience/exp/role 검증, 실패 시 도메인 예외 raise.
  - `create_admin_token(user_id: UUID) -> str` — HS256 + admin secret + admin issuer + 8h.
  - `verify_admin_token(token: str) -> AdminTokenClaims` — 검증 + role==admin enforcement.
  - `hash_refresh_token(token: str) -> str` — `hashlib.sha256(token.encode()).hexdigest()`.
- [x] 2.2 `api/app/adapters/__init__.py`, `api/app/adapters/google_oauth.py` 신규:
  - `async def exchange_code(code: str, redirect_uri: str, code_verifier: str) -> GoogleTokenResponse` — `httpx.AsyncClient`로 Google `https://oauth2.googleapis.com/token` POST(form-urlencoded body). 4xx 시 `InvalidIdTokenError`.
  - `def verify_id_token(id_token_str: str) -> GoogleIdTokenClaims` — `google.oauth2.id_token.verify_oauth2_token(id_token_str, google.auth.transport.requests.Request(), settings.google_oauth_client_id)` 호출. issuer ∈ allowed set 확인. `ValueError` → `InvalidIdTokenError`로 변환. `email_verified=False` → `EmailUnverifiedError`.
- [x] 2.3 단위 테스트 `tests/test_auth_security.py` 작성(AC #12.a) — 14건 통과(round-trip / 만료 / issuer mismatch / wrong secret / wrong audience / 누락된 role / refresh hash 일관성).

### Task 3 — RFC 7807 글로벌 핸들러 + 도메인 예외 계층 (AC: #8)

- [x] 3.1 `api/app/core/exceptions.py` 채움 — `ProblemDetail` Pydantic 모델 + 도메인 예외 계층 + `to_problem` 메서드(8건 code 매핑).
- [x] 3.2 `api/app/main.py`에 핸들러 3개 등록(`BalanceNoteError`, `RequestValidationError`, `HTTPException`). `media_type="application/problem+json"` 강제. 401 시 `WWW-Authenticate: Bearer realm=..., error="invalid_token"` 헤더 추가.
- [x] 3.3 단위 테스트 `tests/test_problem_details.py` — 5건 통과(BalanceNote→problem, 401 WWW-Authenticate, 403 admin, HTTP→http.<status>, validation→errors 확장).

### Task 4 — `/v1/auth/*` 라우터 + DB 통합 (AC: #1, #4, #5)

- [x] 4.1 `api/app/api/__init__.py`, `api/app/api/deps.py`, `api/app/api/v1/__init__.py`, `api/app/api/v1/auth.py` 신규 생성.
- [x] 4.2 `deps.py` — `get_db_session`, `current_user`, `current_admin` Depends. 헤더 우선 + 쿠키 fallback. `current_user_claims` / `current_admin_claims`도 별도 export(DB lookup 없이 claim만 필요한 라우트용).
- [x] 4.3 `auth.py` — POST `/google`, POST `/refresh`, POST `/logout`, POST `/admin/exchange`. Pydantic snake_case 양방향(`alias_generator` 미사용). `_set_user_cookies` / `_set_admin_cookie` / `_clear_auth_cookies` helper에 환경별 Secure flag 분기 추출.
- [x] 4.4 `api/app/main.py` `include_router(auth_router, prefix="/v1/auth")` + `users_router(prefix="/v1/users")` 등록.
- [x] 4.5 CORS 미들웨어 추가 — `settings.cors_allowed_origins`(comma-separated env CORS_ALLOWED_ORIGINS), `allow_credentials=True`, methods/headers 화이트리스트.
- [x] 4.6 통합 테스트 `tests/test_auth_router.py` — `monkeypatch`로 `app.api.v1.auth.google_exchange_code` / `google_verify_id_token` stub. 13건(신규/기존 user, web 쿠키, email_unverified, refresh rotation+replay, logout, admin exchange OK/non-admin/missing auth, secret 분리 차단, issuer mismatch 위조 차단, 보호 라우트 401+ProblemJson).

### Task 5 — `current_user` Depends + `GET /v1/users/me` smoke (AC: #9)

- [x] 5.1 `api/app/api/v1/users.py` 신규 — `GET /me` 엔드포인트, response model `UserMeResponse`(snake_case).
- [x] 5.2 main.py `include_router(users_router, prefix="/v1/users")`.
- [x] 5.3 통합 테스트 `tests/test_users_me.py` — 5건(payload, 401 토큰 부재, 401 만료, 401 admin secret 차단, 401 deleted_at 사용자).

### Task 6 — Mobile 로그인·secure-store·인증 분기 (AC: #2, #4, #6, #10)

- [x] 6.1 `npx expo install expo-auth-session expo-crypto expo-secure-store` + `pnpm add @tanstack/react-query` 완료 — SDK 54 핀 버전 자동 매칭.
- [x] 6.2 `mobile/lib/secure-store.ts`(WHEN_UNLOCKED 옵션), `mobile/lib/auth.tsx`(QueryClient + AuthProvider + authFetch 401→refresh 1회→재시도), `mobile/features/auth/useGoogleSignIn.ts`(expo-auth-session/providers/google + responseType=Code + PKCE auto + scopes openid/email/profile).
- [x] 6.3 `mobile/app/(auth)/_layout.tsx` + `mobile/app/(auth)/login.tsx` — Google로 계속하기 버튼 + 로딩/에러 상태 표시.
- [x] 6.4 `mobile/app/(tabs)/_layout.tsx`(미인증 시 (auth)/login redirect) + `mobile/app/(tabs)/index.tsx` placeholder("Story 2.1에서 채워짐" + 로그아웃 버튼).
- [x] 6.5 `mobile/app/_layout.tsx` 갱신 — `QueryClientProvider` + `AuthProvider` 래핑, Stack 그룹 (index/(auth)/(tabs)) 등록.
- [x] 6.6 `mobile/app/index.tsx` 갱신 — `getAccessToken()` 기반 분기 (`<Redirect href={isAuthed ? '/(tabs)' : '/(auth)/login'} />`).
- [x] 6.7 `mobile/.env.example` 갱신 — `EXPO_PUBLIC_API_BASE_URL` + Google OAuth client id 3종 (iOS/Android/Web).
- [x] 6.8 `pnpm tsc --noEmit` 통과(0 errors). typedRoutes 타입은 `.expo/types/router.d.ts` 갱신.

### Task 7 — Web 로그인 페이지·쿠키·middleware 가드 (AC: #2, #4, #6, #11)

- [x] 7.1 `pnpm add @tanstack/react-query` 완료(5.100.5).
- [x] 7.2 `web/src/lib/api-fetch.ts`(401→refresh 1회→재시도, in-flight 중복 차단), `web/src/lib/auth.ts`(`getServerSideUser` server action — 백엔드 `/v1/users/me` 호출), `web/src/lib/query-client.ts`.
- [x] 7.3 `web/src/app/(public)/login/page.tsx`(Google로 계속하기 + error/next 파라미터 처리) + `api/auth/google/start/route.ts`(state + PKCE 생성 + SameSite=Lax 임시 쿠키) + `api/auth/google/callback/route.ts`(state 검증 + 백엔드 호출 + Set-Cookie forward + 임시 쿠키 정리).
- [x] 7.4 `web/src/middleware.ts` 신규 — `/dashboard/*` + `/admin/*` matcher, 쿠키 부재 시 `/login` 또는 `/admin/login` redirect, `?next=` 보존.
- [x] 7.5 `web/src/app/(user)/dashboard/page.tsx` placeholder — middleware matcher 동작 검증용 + Story 4.3 자리표시자.
- [x] 7.6 `web/.env.example` 갱신 — `API_BASE_URL`, `NEXT_PUBLIC_API_BASE_URL`, `GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI`.
- [x] 7.7 `pnpm tsc --noEmit` + `pnpm build` + `pnpm lint` 모두 통과(0 errors). Next.js 16 `middleware`→`proxy` deprecation은 Story 8 polish로 deferred.

### Task 8 — OpenAPI 클라이언트 자동 생성 + 검증 (AC: #1, #4, #5, #9)

- [x] 8.1 `IN_PROCESS=1 ./scripts/gen_openapi_clients.sh` 실행 → 두 클라이언트 갱신(4 auth + 1 users path 추가). 두 워크스페이스 `pnpm tsc --noEmit` 통과.
- [x] 8.2 openapi-diff 잡은 in-process schema dump 패턴이라 본 변경 그대로 통과 예상(검증은 PR push 후 GitHub Actions에서).

### Task 9 — README 갱신 + 검증 & 문서화 (AC: #1-#12)

- [x] 9.1 `README.md` Quick start 섹션에 "Google OAuth Client 발급 SOP" 추가 — iOS/Android/Web client 3종 발급, redirect URI, `.env` 키 입력 단계.
- [x] 9.2 README에 "인증 디버깅 SOP" 5단계(code 필드 → JWT decode → DB users row → refresh row → WWW-Authenticate 헤더).
- [x] 9.3 Dev Agent Record + File List + Completion Notes 작성 후 `Status: review` 전환.
- [x] 9.4 `sprint-status.yaml` 의 `1-2-google-oauth-로그인-jwt` → `review`로 갱신.

### Review Findings

**Code review (chunk 1 of 4 — 백엔드 인증 코어), 2026-04-27.** 3-layer adversarial: Blind Hunter 28 + Edge Case Hunter 32 + Acceptance Auditor 7 → 통합·중복 제거·분류 후 38건. **2026-04-27 — decision-needed 5건 사용자 결정 완료** → 최종 분류: patch 21 / defer 12 / dismissed 5. **2026-04-28 — 21건 patch 일괄 적용 + 회귀 검증 완료**(pytest 42 passed, ruff clean, mypy strict 0 errors, coverage 74.84%). 백엔드 코어(`api/app/{adapters,api,core,db,main.py}`, alembic, pyproject) 범위. 테스트/모바일/웹 별도 chunk(2~4) 예정.

#### Decision-needed → 결정 완료 (2026-04-27)

- [x] D1 → **patch P19** — 신규 `AccountDeletedError` + `auth.account.deleted` 코드 추가
- [x] D2 → **patch P20** — `bn_refresh` 쿠키 존재로 web 추론 → web은 body에서 `admin_access_token` 제거
- [x] D3 → **dismissed** — 만료 refresh 재사용은 단순 401만, family revoke 미적용 (spec literal 준수, 정상 흐름 오탐 회피)
- [x] D4 → **patch P21** — CORS validator에서 `*` 명시 거부 + `http(s)://` schema 강제
- [x] D5 → **defer W12** — `redirect_uri` 서버 화이트리스트 미도입, Google 화이트리스트 단일 통제 유지

#### Patch (18)

- [x] [Review][Patch] P1 — refresh row 동시-사용 race: `with_for_update()` 또는 `UPDATE ... WHERE token_hash=? AND revoked_at IS NULL RETURNING *` atomic 단일 statement로 변경 — 현재는 SELECT→IF→UPDATE 비원자적. 동일 plaintext 동시 두 요청이 둘 다 통과 → replay 미탐지. [api/app/api/v1/auth.py refresh handler]
- [x] [Review][Patch] P2 — JWT 만료 분기 문자열 매칭 제거: `from jose import ExpiredSignatureError`로 명시 catch + `jwt.decode(..., leeway=60)` 추가. 라이브러리 메시지 변경/클럭 스큐 모두 흡수. [api/app/core/security.py:1172-1176, 1225-1229]
- [x] [Review][Patch] P3 — `payload["sub"]` UUID 파싱 / `payload["exp"]`·`["iat"]` cast 안전화: `try: uuid.UUID(payload["sub"]) except ValueError: raise AccessTokenInvalidError`, `fromtimestamp` `OverflowError`/`OSError`/`ValueError` 전부 catch. raw 500 누출 방지. [api/app/core/security.py verify_user_token/verify_admin_token]
- [x] [Review][Patch] P4 — logout 응답 multi Set-Cookie 평탄화 위험: `return Response(status_code=204, headers=response.headers)` 대신 의존주입 `response`에 `response.status_code = 204` 후 빈 body 반환. 3개 expire 쿠키 중 2개가 누락될 위험 제거. [api/app/api/v1/auth.py logout]
- [x] [Review][Patch] P5 — `WWW-Authenticate: error_description="..."` 인터폴레이션에 `problem.detail` 새니타이즈 추가: `"`/CR/LF 제거 또는 RFC 6750 quoted-string escape. 헤더 인젝션 차단. [api/app/main.py:1514-1518]
- [x] [Review][Patch] P6 — refresh 시 `create_user_token(..., platform="mobile")` 하드코딩 → `bn_refresh` 쿠키 존재로 `"web"`/`"mobile"` 분기. Web 사용자의 mobile platform claim 발급 회귀 제거. [api/app/api/v1/auth.py:774]
- [x] [Review][Patch] P7 — `RefreshToken.replaced_by`에 `ForeignKey("refresh_tokens.id", ondelete="SET NULL")` 추가 + alembic 0002 동기화. dangling reference / chain 추적 가능성 보장. [api/app/db/models/refresh_token.py + api/alembic/versions/0002_users_and_refresh_tokens.py]
- [x] [Review][Patch] P8 — `User.updated_at` Mapped column에 `onupdate=func.now()` 추가. 명시적 setter 없는 경로(향후 Story 5/6/7 추가 컬럼 변경 시) stale 방지. [api/app/db/models/user.py]
- [x] [Review][Patch] P9 — ORM `__table_args__`의 `Index("idx_refresh_tokens_user_id"...)` / `Index("idx_refresh_tokens_family_id"...)` 정의가 alembic이 만든 동명 인덱스와 중복 → autogenerate 잡티 + 정의 분기 위험. alembic 측 정의로 일원화 (ORM에선 제거). [api/app/db/models/refresh_token.py]
- [x] [Review][Patch] P10 — `google_oauth.exchange_code` httpx 예외 처리: `httpx.HTTPError`/`httpx.TimeoutException` catch → `InvalidIdTokenError`로 변환 + `response.json()` `ValueError` catch + `expires_in` `int()` 캐스팅 가드. Google 응답 본문은 raw expose 금지(secret 누출 방지). [api/app/adapters/google_oauth.py:38-55]
- [x] [Review][Patch] P11 — `_upsert_user_from_google` 동시 가입 race: `IntegrityError` (uq_users_google_sub) catch → `await db.rollback(); user = (await db.execute(select(User).where(User.google_sub==...))).scalar_one()` 재조회. 첫 사용자 동시 로그인 500 회귀 방지. [api/app/api/v1/auth.py _upsert_user_from_google]
- [x] [Review][Patch] P12 — `get_db_session` (`api/app/db/session.py`)에서 yield 후 명시적 `try/except: await session.rollback(); raise`. 라우터 예외 시 트랜잭션 잔존 방지. [api/app/db/session.py 또는 api/app/api/deps.py]
- [x] [Review][Patch] P13 — `ProblemDetail.to_response_dict` 타입 annotation을 `dict[str, Any]`로 수정 (현재 `dict[str, str | int | None]`인데 main.py가 `errors: list[...]`를 추가 삽입). mypy strict 통과. [api/app/core/exceptions.py:973-974]
- [x] [Review][Patch] P14 — `current_user`(deps.py)에서 `Authorization: Bearer ` (빈 토큰) 케이스 정책 명시화: 현재는 헤더 truthy로 판단 → cookie fallback 우회 + `AccessTokenInvalidError`. 의도된 거동이라면 테스트 추가, 아니라면 빈 token도 fallback 허용. [api/app/api/deps.py:347-359]
- [x] [Review][Patch] P15 — config 로드 시 `jwt_admin_secret` / `jwt_user_secret` 빈 값 검증 (pydantic-settings field validator 또는 startup hook fail-fast). 빈 secret으로 서명되어 누구나 위조 가능한 회귀 차단. [api/app/core/config.py]
- [x] [Review][Patch] P16 — `_clear_auth_cookies`가 `bn_admin_access` (path=/v1/admin)도 동일 path attribute로 expire 설정하는지 검증 + 누락 시 추가. spec AC5에 명시. [api/app/api/v1/auth.py logout / _clear_auth_cookies]
- [x] [Review][Patch] P17 — `verify_user_token`에 `platform` claim whitelist 검증 추가: `if claims["platform"] not in {"mobile","web"}: raise AccessTokenInvalidError("invalid platform")`. secret 유출 시 임의 platform claim 방지. [api/app/core/security.py verify_user_token]
- [x] [Review][Patch] P18 — `GoogleTokenResponse.refresh_token` 미사용 dead field 제거 (또는 `# unused: Google refresh, not stored` 코멘트). [api/app/adapters/google_oauth.py:198, 257]
- [x] [Review][Patch] P19 (D1 결정) — `core/exceptions.py`에 `AccountDeletedError(code="auth.account.deleted", status=403)` 추가 + `_upsert_user_from_google`에서 `deleted_at IS NOT NULL` 사용자에 이 예외 raise. 핸들러 카탈로그(README의 인증 디버깅 SOP)와 도메인 코드 카탈로그 갱신. [api/app/core/exceptions.py + api/app/api/v1/auth.py:653-655]
- [x] [Review][Patch] P20 (D2 결정) — `/admin/exchange`에서 `request.cookies.get("bn_refresh")` 존재로 web 추론. Web 분기: `_set_admin_cookie(response, admin_token)` + body에서 `admin_access_token` 제외(또는 `null`). Mobile 분기: 현재처럼 body 반환. 응답 모델 분리 또는 `admin_access_token: str | None`. [api/app/api/v1/auth.py:817-830]
- [x] [Review][Patch] P21 (D4 결정) — `_split_cors_origins`(또는 settings field validator)에 `*` 명시 거부 + `http://` / `https://` schema 강제 검증. 잘못된 origin 진입 시 `ValueError`로 startup fail-fast. [api/app/core/config.py]

#### Defer (11)

- [x] [Review][Defer] W1 — admin JWT denylist 부재 — deferred, spec NFR-S7가 stateless 8h 명시 (accepted limitation). [api/app/api/v1/auth.py admin_exchange]
- [x] [Review][Defer] W2 — `request.client.host` proxy 헤더 처리 — deferred, 운영 토폴로지(LB/proxy) 결정 후 별도 NFR. [api/app/api/v1/auth.py:694, 765]
- [x] [Review][Defer] W3 — httpx retry/backoff 미적용 — deferred, 별도 resilience 정책 (Epic 8 운영 hardening). [api/app/adapters/google_oauth.py]
- [x] [Review][Defer] W4 — Google id_token nonce 검증 미적용 — deferred, PKCE-only 정책으로 충분 판단. [api/app/adapters/google_oauth.py:270-274]
- [x] [Review][Defer] W5 — HTTPException 핸들러 `WWW-Authenticate` merge 우선순위 — deferred, FastAPI 내부 401 발생 경로 거의 없음. [api/app/main.py exception handler]
- [x] [Review][Defer] W6 — `ProblemDetail.type=about:blank` 일관 사용 — deferred, RFC 7807 허용 + URI catalog는 후순위 운영 정책. [api/app/core/exceptions.py]
- [x] [Review][Defer] W7 — `UserPublic`/`UserMeResponse`에 `email_verified` 미포함 — deferred, spec 비요구 + Story 5.x 검토. [api/app/api/v1/auth.py:611-618, api/app/api/v1/users.py]
- [x] [Review][Defer] W8 — AC3 `auth.token.issuer_mismatch` 코드 노출 비대칭 (signature 1차 차단 → `auth.access_token.invalid`) — deferred, Completion Notes에 의도적 variance 명시(2단 방어 동등). [api/app/core/security.py verify_admin_token]
- [x] [Review][Defer] W9 — AC7 인덱스 naming variance (`uq_*` vs spec `idx_*`) — deferred, 기능 동등 / explain plan 동일. [api/alembic/versions/0002_users_and_refresh_tokens.py]
- [x] [Review][Defer] W10 — Pydantic ValidationError `msg`/`loc` raw 노출 — deferred, 별도 NFR(입력 echo 정책) 후 일괄 적용. [api/app/main.py:1546-1549]
- [x] [Review][Defer] W11 — refresh body+cookie 둘 다 전송 시 새 쿠키 미설정(mobile 분기 진입) — deferred, 클라이언트 분기 명확화 후. [api/app/api/v1/auth.py:776-785]
- [x] [Review][Defer] W12 (D5 결정) — `redirect_uri` 서버 화이트리스트 미도입 — deferred, Google 콘솔 redirect URI 화이트리스트 단일 통제로 충분 판단. 8주 일정 정합 + 운영 복잡도 회피. Story 8(운영 hardening)에서 재검토. [api/app/api/v1/auth.py:236-244]

#### Dismissed (5 — noise/false-positive 또는 결정 후 기각)

- `coverage.run.omit = []` 빈 리스트 (cosmetic만)
- `aud` claim list 비검증 우려 — `google-auth.verify_oauth2_token` 내부 처리
- UUID type cast — SQLAlchemy UUID 컬럼 native 처리
- logout oracle attack — 마이크로 차이로 식별 비현실적
- D3 만료 refresh family revoke 트리거 — 결정 후 기각 (정상 흐름 오탐 회피, spec AC4 literal 준수)

---

**Code review (chunk 2 of 4 — 백엔드 테스트), 2026-04-28.** 3-layer adversarial: Blind Hunter 16 + Edge Case Hunter 32 + Acceptance Auditor 8 → 통합·중복 제거 후 28건. 분류: patch 12 / defer 14 / dismissed 2. **2026-04-28 — 12건 patch 일괄 적용 + 회귀 검증 완료**(pytest 49 passed [+7 신규], ruff clean, mypy strict 0 errors, coverage 74.97%). 백엔드 테스트(`api/tests/{conftest,test_auth_router,test_auth_security,test_problem_details,test_users_me}.py`) 범위.

#### Patch (12) — 본 chunk에서 적용 예정

- [x] [Review][Patch] T1 — `conftest._truncate_user_tables` 매 테스트 *before yield*로 이동(첫 테스트가 더러운 DB로 시작 방지) + `app.state.engine` 재사용으로 매 테스트 engine 생성·dispose 제거. [api/tests/conftest.py:73-82]
- [x] [Review][Patch] T2 — `pytest.raises((IssuerMismatchError, AccessTokenInvalidError))` tuple 4건을 실제 발생 분기 하나로 고정 — issuer mismatch 회귀 검출력 복구. [test_auth_security.py:491-495,565-568, test_auth_router.py:357-359, test_users_me.py:809-813]
- [x] [Review][Patch] T3 — `test_google_login_web_uses_cookies`에 `HttpOnly`/`SameSite=Strict`/`Max-Age=2592000`(access)·`7776000`(refresh)/dev-환경 `Secure` 부재 단언 추가. AC2 NFR-S2 회귀 차단. [test_auth_router.py:243-256]
- [x] [Review][Patch] T4 — family-cascade revoke 회귀 테스트 추가: 두 family 로그인(다른 디바이스 시뮬) → family A 토큰 replay → family A의 *모든* row revoked + family B 정상. spec AC4 OWASP 정합 핵심. [test_auth_router.py 신규]
- [x] [Review][Patch] T5 — `test_admin_exchange_succeeds_for_admin` 강화: 응답 token을 `verify_admin_token`에 통과시켜 `sub == admin.id` + `iss == jwt_admin_issuer` + `role == "admin"` 단언. expires_in 정수만으론 부족. [test_auth_router.py:314-322]
- [x] [Review][Patch] T6 — Web logout expire-cookie 회귀 테스트 추가: `bn_refresh` 쿠키로 호출 → 응답 `Set-Cookie: bn_access=; Max-Age=0` + `bn_refresh=; Max-Age=0` + `bn_admin_access=; Max-Age=0` 3종 모두 발급 + path 정합. spec AC5. [test_auth_router.py 신규]
- [x] [Review][Patch] T7 — Admin exchange Web 분기(P20) 회귀 테스트: `bn_refresh` 쿠키 동봉 → 응답 body의 `admin_access_token is None` + `Set-Cookie: bn_admin_access=...; Path=/v1/admin` 발급 단언. [test_auth_router.py 신규]
- [x] [Review][Patch] T8 — `auth.google.id_token_invalid` 코드 명시 단언 추가(현재 카탈로그 8건 중 유일하게 미검증). [test_problem_details.py 보강]
- [x] [Review][Patch] T9 — `test_me_with_deleted_user_returns_401`이 `code.startswith("auth.")` → `code == "auth.access_token.invalid"`로 고정. 결정: `current_user` 경로의 deleted user는 401(`auth.access_token.invalid`) 유지(token sig는 valid이나 자원 없음 — 401 의미 정합). P19 `auth.account.deleted`는 `/v1/auth/google` 재로그인 분기 전용. [test_users_me.py:816-823]
- [x] [Review][Patch] T10 — `/v1/auth/google` 재로그인 흐름의 `AccountDeletedError`(P19) 회귀 테스트 추가: deleted_at 사용자가 다시 Google 인증 → 403 + `code == "auth.account.deleted"`. [test_auth_router.py 신규]
- [x] [Review][Patch] T11 — prefix-only assertion 4건을 정확 매칭으로 강화: `test_protected_endpoint_returns_problem_json_when_unauth`, `test_admin_exchange_requires_authentication` 등 — `code.startswith("auth.")` → 구체 코드, `headers["www-authenticate"].startswith("Bearer ")` → `realm="balancenote"` + `error="invalid_token"` 풀 단언. [test_auth_router.py:391-397, 334-337 외]
- [x] [Review][Patch] T12 — `test_refresh_token_random_and_hash_consistent` 강화: 1000회 호출 unique 단언(`len({plaintext}) == 1000`) + `len(plaintext) == 43` (정확) + `hash_refresh_token("a") != hash_refresh_token("b")` 결정적 단언. 통계 가정 제거. [test_auth_security.py:588-600]

#### Defer (14)

- [x] [Review][Defer] T-W1 — `IntegrityError` 동시 가입 race 회귀 테스트 — deferred, asyncio.gather 셋업 복잡 + 본 chunk 1의 P11 코드 적용으로 차단됨(차후 통합 시나리오로). [api/app/api/v1/auth.py:_upsert_user_from_google]
- [x] [Review][Defer] T-W2 — Web refresh 쿠키-only flow E2E — deferred, 핵심 로직은 모바일 분기와 동일 + chunk 4(웹) 통합에서 별도 검증.
- [x] [Review][Defer] T-W3 — concurrent /refresh 동시 호출 race 회귀(`asyncio.gather`) — deferred, asyncpg pool 동시성 셋업 + sleep 없는 race 트리거 어려움. P1(`with_for_update`) 코드 적용으로 1차 차단됨.
- [x] [Review][Defer] T-W4 — Google adapter 단위 테스트 (issuer 화이트리스트 / email 누락 / 4xx / JSON 파싱 실패) — deferred, adapter 별도 모듈로 분리되어 있어 본 chunk(테스트) 외 별도 PR 권장.
- [x] [Review][Defer] T-W5 — `_build_isolated_app` 리팩터(핸들러를 `app.core.handlers`로 분리) — deferred, 구조 변경 + 본 스토리 범위 외.
- [x] [Review][Defer] T-W6 — alembic downgrade/remediation message 강화 — deferred, conftest 운영 NFR(Story 8).
- [x] [Review][Defer] T-W7 — `expires_in_seconds`를 settings 상수와 비교(config drift 방지) — deferred, 30일 SOT가 사실상 코드 한 곳(`USER_ACCESS_TOKEN_TTL_SECONDS`)에 한정.
- [x] [Review][Defer] T-W8 — `claims.jti`의 UUID4 format 단언 약화 또는 spec 명시 문서화 — deferred, 스펙에 jti=UUIDv4 명시되어 있고 회귀 위험 LOW.
- [x] [Review][Defer] T-W9 — `_login_payload`의 PKCE `code_verifier` 형식 단순화 — deferred, stub adapter라 실제 PKCE 검증 미실행.
- [x] [Review][Defer] T-W10 — logout idempotency(2회 호출) 회귀 테스트 — deferred, 멱등성 보장은 코드 단순(이미 revoked row는 update 0건) + 클라이언트 retry NFR.
- [x] [Review][Defer] T-W11 — `Authorization: Basic`/잘못된 scheme + cookie fallback 회귀 — deferred, P14 코드 패치로 fallback 동작 확정 + 통합 회귀는 chunk 4(웹) 미들웨어 시나리오에서.
- [x] [Review][Defer] T-W12 — CORS preflight `evil.com` Origin 거부 — deferred, CORSMiddleware 동작은 starlette 라이브러리 SOT + P21 patch로 잘못된 origin 시작 시 fail-fast.
- [x] [Review][Defer] T-W13 — `WWW-Authenticate` 헤더 인젝션 sanitize 회귀 테스트 — deferred, P5 코드 패치로 차단 + 통합 회귀는 별도 보안 스모크.
- [x] [Review][Defer] T-W14 — alembic 마이그레이션 컬럼/제약/partial index 직접 검증 회귀 — deferred, conftest의 alembic upgrade head 자동 실행 + 마이그레이션 SOT는 Alembic 자체.

#### Dismissed (2 — noise/false-positive)

- `tests.conftest`로부터 `UserFactory`/`auth_headers` 직접 import 패턴 — pytest collection이 conftest를 미리 import하기 때문에 실제 brittle 위험 LOW. 추후 helpers 모듈 분리는 ergonomic.
- `_alembic_upgrade_head` 실패 진단 메시지 부재 — alembic 자체 메시지로 충분 + 운영 hardening Story 8.

---

**Code review (chunk 3 of 4 — 모바일 인증 흐름), 2026-04-28.** 3-layer adversarial: Blind Hunter 27 + Edge Case Hunter 28 + Acceptance Auditor 7 → 통합·중복 제거 후 28건. 분류: patch 10 / defer 15 / dismissed 3. **2026-04-28 — 10건 patch 일괄 적용 + 회귀 검증 완료**(`pnpm tsc --noEmit` exit 0, `pnpm lint` exit 0). 모바일(`mobile/app/{(auth),(tabs),index,_layout}.tsx`, `mobile/lib/{auth.tsx,secure-store.ts}`, `mobile/features/auth/useGoogleSignIn.ts`, `mobile/{app.json,.env.example,package.json}`) 범위.

#### Patch (10) — 본 chunk에서 적용 예정

- [x] [Review][Patch] M1 — `performRefresh` 실패 시 AuthProvider `user` state 동기화 부재. 모듈 레벨 `subscribeSessionCleared(cb)` 도입 → AuthProvider가 mount 시 등록, refresh 401에서 호출. user 상태가 stale로 부활하는 회귀 차단. [mobile/lib/auth.tsx]
- [x] [Review][Patch] M2 — AuthProvider bootstrap useEffect의 race: signOut 중 늦게 도착한 `/v1/users/me` 응답이 setUser(null) 덮어씀 → cancellation flag(`isCancelled`) 추가. [mobile/lib/auth.tsx:111-128]
- [x] [Review][Patch] M3 — logout fetch에 `Authorization: Bearer <access>` 누락(spec AC5 명시 위반: "모바일 Authorization: Bearer <access> + body {refresh_token}"). [mobile/lib/auth.tsx:142-158]
- [x] [Review][Patch] M4 — login error UI: 백엔드 응답 본문(`text`)을 그대로 `setError`에 echo → ValidationError가 `input` 필드에 PKCE verifier echo 가능. raw text 제거하고 status code 위주의 사용자 메시지로 sanitize. [mobile/app/(auth)/login.tsx + useGoogleSignIn.ts:88-91]
- [x] [Review][Patch] M5 — 로그인 버튼 `accessibilityHint` 추가 ("Google 로그인 화면을 엽니다"). spec AC10 가이드라인 정합. [mobile/app/(auth)/login.tsx:13-25]
- [x] [Review][Patch] M6 — `clearAuth`의 `Promise.all` → `Promise.allSettled`: 두 키 중 하나만 실패해도 stale token 잔존하지 않도록. [mobile/lib/secure-store.ts:32-37]
- [x] [Review][Patch] M7 — `(auth)/_layout.tsx` 대칭 가드: 이미 인증된 사용자가 deep-link로 `/(auth)/login` 진입 시 `(tabs)`로 redirect. [mobile/app/(auth)/_layout.tsx]
- [x] [Review][Patch] M8 — AC6 `?next=` 쿼리 보존: `(tabs)/_layout.tsx`/`app/index.tsx`에서 보호 라우트로 진입 직전 pathname을 query로 인코딩 + 로그인 성공 후 `next` 파라미터로 라우팅. [mobile/app/(tabs)/_layout.tsx + index.tsx + (auth)/login.tsx + features/auth/useGoogleSignIn.ts]
- [x] [Review][Patch] M9 — PKCE 흐름의 `codeVerifier`/`redirectUri` null guard: `request.codeVerifier` 또는 `request.redirectUri`가 undefined면 명시적 에러 처리(현재는 그대로 전송 → 백엔드 422). [mobile/features/auth/useGoogleSignIn.ts:73-86]
- [x] [Review][Patch] M10 — refresh 재시도 sentinel: 재시도된 fetch에 `X-Auth-Refreshed=1` 헤더 표시 + authFetch에서 첫 호출 시 헤더 존재 시 refresh 시도 안 함(무한 루프 방어). [mobile/lib/auth.tsx:84-105]

#### Defer (15)

- [x] [Review][Defer] M-W1 — `WHEN_UNLOCKED` → `AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY` 보안 tradeoff(iCloud Keychain 동기화 차단) — deferred, 제품 결정(NFR + UX 영향) 후 일괄. [mobile/lib/secure-store.ts:13]
- [x] [Review][Defer] M-W2 — TanStack Query 자체 인터셉터 wiring(useQuery/useMutation에서 자동 401 처리) — deferred, 현재는 모든 useQuery가 `authFetch`를 queryFn으로 사용하면 자동 인터셉트 적용 — 패턴 가이드 문서화로 일괄. [mobile/lib/auth.tsx queryClient]
- [x] [Review][Defer] M-W3 — proactive refresh(expires_in_seconds 기반 사전 갱신) — deferred, 1차 latency 최적화는 Story 8 polish.
- [x] [Review][Defer] M-W4 — stream body / multipart upload 시 fetch body 재소비 안전성 — deferred, 현재 모든 호출이 JSON string body라 `RequestInit` 재사용 안전. 멀티파트 업로드는 Story 2.2(식단 사진).
- [x] [Review][Defer] M-W5 — generated `RefreshResponse` Union(`RefreshResponseMobile | { [key: string]: string }`) discriminator 추가 — deferred, OpenAPI generator 옵션 변경 + Story 4(웹 리포트)에서 일괄.
- [x] [Review][Defer] M-W6 — fast-refresh 시 module-global `queryClient` HMR 새 인스턴스 위험 — deferred, dev-only 영향 + Expo 4.x 리액트 컴파일러 활성화로 동작 안정.
- [x] [Review][Defer] M-W7 — `SafeAreaView` / `KeyboardAvoidingView` 미적용 — deferred, 본 스토리 범위 밖 UI 폴리싱(Story 1.6 onboarding 튜토리얼에서 일괄).
- [x] [Review][Defer] M-W8 — i18n 미설정 — deferred, Korean-only 기본 + Story 8.6 데모영상 패키지에서 결정.
- [x] [Review][Defer] M-W9 — `expo-auth-session ~7.0.10` SDK 매트릭스 검증 — deferred, `expo doctor` CI 게이트 추가는 Story 8 운영 hardening.
- [x] [Review][Defer] M-W10 — `AuthUser.role` 좁은 타입 vs OpenAPI `string` mismatch — deferred, zod parse 일괄(`auth.tsx`/`api-client.ts` 동시).
- [x] [Review][Defer] M-W11 — generated `api-client.ts`의 cookie 헤더 정의 cross-leak 위험 — deferred, RN 빌드 타깃에서 cookie 미사용 + Expo Web 빌드 적용 시 별도 검토.
- [x] [Review][Defer] M-W12 — `expires_in_seconds` 클라이언트 미저장(proactive refresh 인프라 부재) — deferred, M-W3과 동시 적용.
- [x] [Review][Defer] M-W13 — `redirectUri` 클라이언트 화이트리스트 비교 — deferred, W12(서버 화이트리스트 미도입 결정)와 일관 + Google 콘솔 화이트리스트 단일 통제.
- [x] [Review][Defer] M-W14 — `(tabs)/index.tsx`의 `user.display_name` overflow / `numberOfLines` — deferred, Story 2.1에서 실제 탭 화면 구성 시 일괄.
- [x] [Review][Defer] M-W15 — promptResult `cancel`/`dismiss` 시 setError 미정리 — deferred, `signIn` 시작부 `setError(null)` 호출로 다음 시도엔 자동 정리됨(현재 동작 충분).

#### Dismissed (3 — false positive 또는 노이즈)

- Blind: `app.json` plugins 배열 구조 오류 — 실제 파일 확인 결과 `["expo-router", ["expo-splash-screen", {...}], "expo-secure-store"]`로 정상 구조.
- Edge: secure-store 키 `bn_access`/`bn_refresh` Android keystore alias collision — bundleId-scoped라 실제 collision 위험 미미.
- Edge: useEffect deps에 `setUser`/`authFetch` 미포함 — 모듈 스코프 함수 + setState dispatcher는 React 안정 보장.

---

**Code review (chunk 4 of 4 — 웹 인증 흐름), 2026-04-28.** 3-layer adversarial: Blind Hunter 20 + Edge Case Hunter 33 + Acceptance Auditor 7 → 통합·중복 제거 후 31건. 분류: patch 12 / defer 16 / dismissed 3. **2026-04-28 — 12건 patch 일괄 적용 + 회귀 검증 완료**(`pnpm tsc --noEmit` exit 0, `pnpm lint` exit 0). 웹(`web/src/app/{(public),(user),api/auth}`, `web/src/lib/{auth.ts,api-fetch.ts,query-client.ts,safe-next.ts 신규}`, `web/src/{middleware.ts,app/layout.tsx,app/providers.tsx 신규}`) 범위.

#### Patch (12) — 본 chunk에서 적용 예정

- [x] [Review][Patch] W1 — `web/src/lib/auth.ts`의 `"use server"` 디렉티브 제거 + `import "server-only"`로 교체. 현재 디렉티브는 `getServerSideUser`를 Server Action(클라이언트 RPC)으로 노출 — 의도(server-only helper)와 정반대. [web/src/lib/auth.ts:9]
- [x] [Review][Patch] W2 — `next` 파라미터 open redirect 차단: `next.startsWith('/') && !next.startsWith('//')` 화이트리스트. 3곳 적용: `start/route.ts:40`, `(public)/login/page.tsx:13-14`, `callback/route.ts:44`. [web/src/app/api/auth/google/{start,callback}/route.ts + web/src/app/(public)/login/page.tsx]
- [x] [Review][Patch] W3 — 대시보드에 로그아웃 버튼 + `POST /v1/auth/logout` client handler 추가(AC5 — Web logout 트리거 부재). [web/src/app/(user)/dashboard/page.tsx + 신규 client component]
- [x] [Review][Patch] W4 — `QueryClientProvider` + AuthProvider wiring을 root layout에 추가(AC11 — `useUser`/TanStack Query 사용 준비). 신규 client wrapper(`web/src/app/providers.tsx`)로 lazy init. [web/src/app/layout.tsx + web/src/app/providers.tsx 신규]
- [x] [Review][Patch] W5 — `/admin/login` placeholder 페이지 추가(AC3 — middleware redirect 대상 404 회피). 추후 Story 7에서 admin 흐름 본격 구현. [web/src/app/(public)/admin/login/page.tsx 신규]
- [x] [Review][Patch] W6 — middleware `/admin/login` boundary: `pathname === '/admin/login' || pathname.startsWith('/admin/login/')`로 강화 — `/admin/loginExtra` 우회 차단. [web/src/middleware.ts:17]
- [x] [Review][Patch] W7 — callback의 `loginRedirect`가 백엔드 raw text를 URL에 echo(`?error=backend ${status}: ${text}`) — 일반화된 메시지로 sanitize. [web/src/app/api/auth/google/callback/route.ts:62-64]
- [x] [Review][Patch] W8 — early `loginRedirect` 분기에서 `bn_oauth_state`/`bn_oauth_pkce`/`bn_oauth_next` 쿠키 즉시 expire — stale 쿠키 잔존 차단(`maxAge=0` set helper로 통일). [web/src/app/api/auth/google/callback/route.ts:24-27, 35-48]
- [x] [Review][Patch] W9 — 이미 인증된 사용자가 `/login` 접근 시 `/dashboard`로 redirect(symmetric guard). 모바일 chunk 3 M7과 동등. [web/src/middleware.ts]
- [x] [Review][Patch] W10 — callback의 dead 상수 제거(`ACCESS_TTL_SECONDS`/`REFRESH_TTL_SECONDS` + `void` 줄)와 코멘트/실제 코드 일치(dev fallback 미구현 사실 명시). [web/src/app/api/auth/google/callback/route.ts:16-17, 100-102, 76-83]
- [x] [Review][Patch] W11 — `getServerSideUser`가 cookie를 `Authorization: Bearer`로 재포장 → `Cookie: bn_access=...`로 직접 forward(AGENTS.md "httpOnly 쿠키로 직접 교환" 패턴 정합 + 백엔드 deps의 cookie fallback 활용). [web/src/lib/auth.ts:30-33]
- [x] [Review][Patch] W12 — middleware: 빈/공백/너무 짧은(<20자) cookie 값을 garbage로 보고 무인증 처리. JWT 최소 길이는 `header.payload.signature` 3 segment로 수십 자. [web/src/middleware.ts:18, 27]

#### Defer (16)

- [x] [Review][Defer] W-W1 — `useUser` 클라이언트 훅 추가 — deferred, 본 스토리는 SSR `getServerSideUser`로 충분(dashboard 1곳). 대시보드 차트(Story 4.3) 시 도입.
- [x] [Review][Defer] W-W2 — TanStack Query SSR hydration / `dehydrate`/`HydrationBoundary` — deferred, Story 4.3 차트에서 일괄.
- [x] [Review][Defer] W-W3 — 백엔드 cookie path/domain rewriting (`Domain=...` mismatch) — deferred, 운영 도메인 합의(Story 8 운영 hardening) 후 대응. dev에선 backend cookies 도착 시 동일 도메인 가정.
- [x] [Review][Defer] W-W4 — middleware case-insensitive path matching(`/Dashboard` 등) — deferred, Next.js 라우터가 case-sensitive 라우트 디폴트 + matcher 정규식 변환은 회귀 위험.
- [x] [Review][Defer] W-W5 — `apiFetch`의 `_isRetry`/`_skipRefresh` 비표준 RequestInit prop — deferred, 외부 주입 위험은 모듈 내부 호출만 한정해 영향 LOW. 리팩터(WeakMap)는 별 PR.
- [x] [Review][Defer] W-W6 — `next` cookie 길이 제한(4KB) + 형태 검증 — deferred, `next` 검증(W2)으로 1차 방어 + 4KB 초과는 브라우저 silently drop.
- [x] [Review][Defer] W-W7 — `getSetCookie?.()` Node 버전 호환성 — deferred, Node 20+ 표준 + Next 16 요구 Node 20+.
- [x] [Review][Defer] W-W8 — `isProductionEnvironment` DRY 위반(2 파일 중복) — deferred, 한 곳만 변경되어도 큰 영향 없음 + 이후 utils 모듈로 추출 시 일괄.
- [x] [Review][Defer] W-W9 — `start` route GET sync vs async — deferred, cookies API는 response.cookies.set이라 sync 충분.
- [x] [Review][Defer] W-W10 — Edge Hunter: 동시 두 탭 OAuth start race(쿠키 path=/api/auth/google 공유로 마지막 탭이 이전 탭 PKCE 덮어씀) — deferred, 일반 사용자 패턴 아님 + 실패 시 invalid state로 안전하게 fail-closed.
- [x] [Review][Defer] W-W11 — refresh interceptor가 reject 시 호출자 401 response 반환 후 redirect — deferred, navigation 직전 fail loud OK + Story 4 컴포넌트 도입 시 보강.
- [x] [Review][Defer] W-W12 — `error` query의 `decodeURIComponent` 제거(Next는 자동 디코드) — deferred, React가 텍스트 escape + 잘못된 시퀀스 발생 빈도 낮음.
- [x] [Review][Defer] W-W13 — admin 교환(`/api/auth/admin/exchange`) Web route — deferred, Story 7(관리자) 본격 구현 시 일괄.
- [x] [Review][Defer] W-W14 — `getServerSideUser`에 `React.cache` 도입(요청 단위 캐시) — deferred, 본 스토리는 dashboard 1곳 호출 + N+1 위험 미발생.
- [x] [Review][Defer] W-W15 — middleware matcher route group 하위 path 자동 확장 — deferred, Next.js 라우터 한계(group은 URL 미노출) + literal path 추가는 후속 스토리에서 자연 확장.
- [x] [Review][Defer] W-W16 — refresh CSRF 토큰 — deferred, SameSite=Strict 쿠키 + Origin 검증으로 1차 방어 + 별도 CSRF 토큰은 운영 hardening.

#### Dismissed (3 — false positive 또는 노이즈)

- Blind: `'use server'` 모듈에서 `interface AuthUser` export 빌드 에러 — TS interface는 컴파일 시 erase되므로 런타임 모듈은 함수 1개만. 실 빌드 통과(W1로 디렉티브 자체 교체하므로 어쨌든 해결).
- Edge: PKCE/state 쿠키 path 불일치 가능성 — 현재 코드 4곳 모두 `path: "/api/auth/google"` 동일 + W8 cleanup으로 stale 잔존 차단.
- Edge: `bn_oauth_*` 경로 secure 토글 시 새 쿠키 추가 — set/clear 동일 secure 분기라 불일치 없음.

## Dev Notes

### Architecture decisions (반드시 따를 것)

[Source: architecture.md#Authentication & Security (line 301-313), architecture.md#Decision Impact Analysis (line 354-372)]

**JWT 분리 (절대 통합 금지)**
- user JWT: HS256, secret = `JWT_USER_SECRET`, issuer = `JWT_USER_ISSUER` (`balancenote-user`), access 30일, refresh 90일.
- admin JWT: HS256, secret = `JWT_ADMIN_SECRET`(user secret과 다른 값), issuer = `JWT_ADMIN_ISSUER` (`balancenote-admin`), access 8시간, refresh 없음.
- `verify_*` 함수는 issuer claim을 명시 검증 — 토큰 혼용 차단의 핵심.

**OAuth flow**
- 모바일: `expo-auth-session/providers/google` + `responseType: "code"` + PKCE auto. Implicit flow 절대 금지.
- Web: 서버사이드 redirect — Next.js `/api/auth/google/start` → Google → `/api/auth/google/callback` → 백엔드 `/v1/auth/google` 서버사이드 호출 → cookie set.
- 백엔드는 두 흐름 모두 동일 endpoint(`POST /v1/auth/google`) 처리. id_token 검증은 `google.oauth2.id_token.verify_oauth2_token()` 호출.

**Token 저장**
- 모바일: `expo-secure-store`(iOS Keychain / Android Keystore). AsyncStorage 절대 금지. SecureStore 옵션 `WHEN_UNLOCKED` 사용(`WHEN_UNLOCKED_THIS_DEVICE_ONLY`는 백업 복원 시 토큰 유실 — UX 저하).
- Web: `httpOnly + Secure + SameSite=Strict` 쿠키. `localStorage` / `sessionStorage` / non-httpOnly cookie 절대 금지(NFR-S2 정합).
- `bn_refresh` 쿠키 path를 `/v1/auth`로 한정 — refresh가 다른 endpoint에 자동 전송되는 것 방지(OWASP Cookie Path Restriction).

**Refresh token rotation (OWASP Refresh Token Reuse Detection)**
- refresh는 JWT 아닌 32-byte URL-safe random — `secrets.token_urlsafe(32)`.
- DB에는 `sha256(plaintext)` 만 저장(평문 절대 저장 금지).
- 사용 시 새 refresh 발급 + 기존 row revoke + `replaced_by = new_id` 마킹.
- 이미 revoke된 refresh 재제시 → token-replay 간주 → 해당 family 모든 row revoke + 401.
- family_id는 최초 OAuth 로그인 시 생성, rotation은 동일 family_id 유지.

**RFC 7807 표준 (전체 횡단)**
[Source: architecture.md#API & Communication Patterns (line 320), architecture.md#Format Patterns (line 462-471)]
- 모든 에러 응답 media_type = `application/problem+json`.
- 필드: `type`, `title`, `status`, `detail`, `instance`, `code`(우리 확장).
- `code`는 카탈로그화 — 본 스토리에서 `auth.*` 8건 정의(AC8). 후속 스토리(`consent.*`, `meal.*`, `analysis.*`)가 동일 패턴 따름.
- 401 응답에 `WWW-Authenticate: Bearer realm="balancenote", error="invalid_token"` 헤더 동시 첨부(RFC 6750).

**API 응답 표준 (전체 횡단)**
[Source: architecture.md#Format Patterns (line 457-471)]
- 성공 응답에 wrapper 금지 — 직접 객체. 예: `{"id": "...", "email": "...", ...}`.
- snake_case 양방향(요청·응답). Pydantic `alias_generator=to_camel` 절대 금지.
- 날짜 ISO 8601 + Z (`2026-04-27T14:23:11Z`).

**API 라우터 분할**
[Source: architecture.md#Structure Patterns (line 442-446)]
- 1파일 1 APIRouter 도메인별. 본 스토리: `app/api/v1/auth.py`, `app/api/v1/users.py`.
- 공통 dependency는 `app/api/deps.py`. `current_user`, `current_admin` 본 스토리 도입. `require_consent`(Story 1.4), `audit_admin_action`(Story 7.3) 후속.
- 라우터는 service layer만 호출(architecture#서비스 경계). 본 스토리는 service layer 도입 X — 단순 OAuth 흐름은 라우터 직접 처리. `app/services/auth_service.py` 분리는 Story 1.6 또는 Story 5.x가 추가 책임 발생 시 도입.

**환경 분리 + Secret 관리**
[Source: Story 1.1 Dev Notes "보안·시크릿"]
- 모든 시크릿(JWT_*_SECRET, GOOGLE_OAUTH_CLIENT_SECRET)은 Railway secrets / Vercel env / GitHub Actions secrets에서만 관리.
- `.env.example`은 변수명 + 설명 + placeholder만. 실제 키 절대 커밋 금지.
- 본 스토리에서 신규 추가되는 env 변수:
  - 백엔드(`api/app/core/config.py` + 루트 `.env.example`): `CORS_ALLOWED_ORIGINS` (comma-separated, dev 디폴트 `http://localhost:3000`).
  - Web(`web/.env.example`): `NEXT_PUBLIC_API_BASE_URL`, `GOOGLE_OAUTH_REDIRECT_URI`. (`GOOGLE_OAUTH_CLIENT_ID/SECRET`은 루트 `.env.example`에서 공유.)
  - 모바일(`mobile/.env.example`): `EXPO_PUBLIC_API_BASE_URL`, `EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_IOS/ANDROID/WEB` 4건.

### Library / Framework 요구사항

| 영역 | 라이브러리 | 정확한 사유 |
|------|-----------|-----------|
| Google id_token 검증 (백엔드) | `google-auth>=2.36` | 공식 `verify_oauth2_token` 제공. PyJWT + JWKS 직접 fetch는 anti-pattern(공식 라이브러리 우선) |
| JWT 발급/검증 | `python-jose[cryptography]` (Story 1.1 이미 설치) | HS256 충분. PyJWT로 교체 검토는 Story 8 polish — 본 스토리는 기존 의존성 활용 |
| 백엔드 HTTP 클라이언트 | `httpx>=0.28` (Story 1.1 이미 설치) | Google token endpoint 호출용 |
| 모바일 OAuth | `expo-auth-session` + `expo-crypto` | SDK 54 표준. `responseType=code` + PKCE auto. `@react-native-google-signin/google-signin` 도입 금지 — Expo managed workflow eject 유발 |
| 모바일 secure storage | `expo-secure-store` | Keychain/Keystore 표준. AsyncStorage / MMKV 금지(secret 평문 저장) |
| 모바일 server state | `@tanstack/react-query` | architecture#Frontend Architecture 명시. Redux/Jotai 금지 |
| 백엔드 OAuth 테스트 mock | `respx>=0.22` (dev dep 추가 검토) 또는 `pytest monkeypatch` | Google API 호출 stub. `respx`가 표준 — 단 본 스토리는 `monkeypatch`로도 충분(가벼움 우선). 결정은 dev에 위임 |

### Naming 컨벤션 (전체 횡단)

[Source: architecture.md#Naming Patterns (line 386-431), Story 1.1 Dev Notes "명명 규칙"]
- DB: snake_case + 복수. 본 스토리 추가: `users`, `refresh_tokens`. 컬럼: `google_sub`, `email_verified`, `last_login_at`, `token_hash`, `family_id`, `replaced_by`, `revoked_at`, `expires_at`, `user_agent`, `ip_address`.
- API URL: REST kebab-plural + `/v1/`. 본 스토리: `/v1/auth/google`, `/v1/auth/refresh`, `/v1/auth/logout`, `/v1/auth/admin/exchange`, `/v1/users/me`. (auth 도메인은 plural noun 적용 어색 — `/v1/auth/*` 단수 그룹 유지)
- JSON wire: snake_case 양방향. 응답 예: `{"access_token": "...", "refresh_token": "...", "expires_in_seconds": 2592000, "user": {"id": "...", "display_name": "...", "picture_url": "..."}}`.
- 파일명: Python `snake_case.py` (예: `google_oauth.py`, `refresh_token.py`). React 컴포넌트 `PascalCase.tsx`, 그 외 TS `kebab-case.ts` (예: `secure-store.ts`, `api-fetch.ts`).
- React Native 화면(Expo Router file-based): `mobile/app/(auth)/login.tsx` — kebab-case 파일.

### 폴더 구조 (Story 1.2 종료 시점에 *반드시* 존재해야 하는 신규 항목)

[Source: architecture.md#Complete Project Directory Structure (line 569-841), Story 1.1 종료 시점 골격]

```
api/
├── alembic/versions/
│   ├── 0001_baseline.py                    # 기존
│   └── 0002_users_and_refresh_tokens.py    # 신규
└── app/
    ├── adapters/
    │   ├── __init__.py                      # 신규
    │   └── google_oauth.py                  # 신규 — verify_id_token + exchange_code
    ├── api/
    │   ├── __init__.py                      # 신규
    │   ├── deps.py                          # 신규 — current_user, current_admin, get_db_session
    │   └── v1/
    │       ├── __init__.py                  # 신규
    │       ├── auth.py                      # 신규 — /google, /refresh, /logout, /admin/exchange
    │       └── users.py                     # 신규 — GET /me (smoke)
    ├── core/
    │   ├── security.py                      # 채움 (placeholder 제거)
    │   └── exceptions.py                    # 채움 (placeholder 제거)
    └── db/
        ├── __init__.py                      # 신규
        ├── base.py                          # 신규 — declarative_base
        ├── session.py                       # 신규 — async_session_maker
        └── models/
            ├── __init__.py                  # 신규
            ├── user.py                      # 신규
            └── refresh_token.py             # 신규
api/tests/
├── test_auth_security.py                    # 신규 (단위)
├── test_auth_router.py                      # 신규 (통합)
├── test_users_me.py                         # 신규 (통합)
└── test_problem_details.py                  # 신규 (단위)

mobile/
├── app/
│   ├── _layout.tsx                          # 갱신 — Provider 래핑
│   ├── index.tsx                            # 갱신 — 인증 분기
│   ├── (auth)/                              # 신규
│   │   ├── _layout.tsx
│   │   └── login.tsx
│   └── (tabs)/                              # 신규 placeholder
│       ├── _layout.tsx
│       └── index.tsx                        # "Story 2.1에서 채워짐" placeholder
├── features/
│   └── auth/                                # 신규
│       └── useGoogleSignIn.ts
├── lib/
│   ├── api-client.ts                        # 갱신(`pnpm gen:api`)
│   ├── secure-store.ts                      # 신규
│   └── auth.ts                              # 신규
└── .env.example                             # 갱신

web/
├── src/
│   ├── app/
│   │   ├── (public)/                        # 신규 그룹
│   │   │   └── login/page.tsx
│   │   ├── (user)/                          # 신규 그룹 placeholder (middleware matcher 검증용)
│   │   │   └── _layout.tsx                  # 또는 dashboard placeholder
│   │   └── api/
│   │       └── auth/
│   │           └── google/
│   │               ├── start/route.ts
│   │               └── callback/route.ts
│   ├── lib/
│   │   ├── api-client.ts                    # 갱신
│   │   ├── api-fetch.ts                     # 신규
│   │   ├── auth.ts                          # 신규
│   │   └── query-client.ts                  # 신규
│   └── middleware.ts                        # 신규
└── .env.example                             # 갱신
```

**중요**: 위에서 명시되지 않은 architecture.md의 모듈/도메인 폴더(`app/domain/`, `app/graph/`, `app/rag/`, `app/services/`, `app/workers/`, `mobile/features/meals/`, `web/src/features/*` 등)는 본 스토리에서는 생성하지 않는다. premature scaffolding 회피.

### 보안·민감정보 마스킹 (NFR-S5)

[Source: prd.md#TC1, NFR-S5, architecture.md#Authentication & Security]
- structlog `mask_processor` (Story 1.1 placeholder)에 본 스토리에서 마스킹 패턴 추가 *X* — 본 스토리는 토큰·이메일·refresh hash가 로그·Sentry breadcrumb에 노출되지 않도록 *명시적으로 로깅하지 않음* 으로 처리. 정규식 마스킹 정교화는 Story 8 polish.
- 단, 본 스토리에서 다음 필드는 *절대 로그 출력 금지*:
  - access JWT, refresh token plaintext, refresh hash, Google id_token, Google access_token, OAuth code, code_verifier.
  - email은 마스킹 표시 가능(`u***@example.com`) — debug 시. 단순 `user_id` 위주 로깅 권장.
- Sentry `before_send` hook(Story 1.1 placeholder)은 본 스토리에서 손대지 않음. Story 8 polish가 정규식 마스킹 추가.

### Anti-pattern 카탈로그 (본 스토리 영역)

[Source: architecture.md#Anti-pattern 카탈로그 (line 557-565)]

- ❌ `next-auth` 도입 — architecture 결정 위반. Web은 백엔드 JWT를 httpOnly 쿠키로 직접 교환.
- ❌ Pydantic `alias_generator=to_camel` — 양방향 snake_case 위반.
- ❌ `raise HTTPException(401, "...")` 직접 사용 — 도메인 예외 + RFC 7807 글로벌 핸들러로 통일.
- ❌ AsyncStorage / `localStorage` / non-httpOnly cookie에 토큰 저장.
- ❌ Implicit flow / id_token을 클라이언트가 직접 백엔드에 보내고 백엔드가 그대로 신뢰 — 반드시 `verify_oauth2_token`으로 서명 검증.
- ❌ 401 시 페이지 새로고침으로 회복(refresh flow 우회).
- ❌ refresh token 평문 DB 저장.
- ❌ access JWT denylist 시도(stateless JWT 본질 위반 — 만료까지 유효, refresh 무효화로 흐름 차단).
- ❌ JWT secret을 두 token 타입에 공유.
- ❌ 동일 issuer claim을 두 token 타입에 사용.
- ❌ HTTPS 미사용 환경에서 production cookie `Secure` flag 누락.
- ❌ Story 1.5의 알레르기/health_goal 컬럼을 본 스토리 마이그레이션에 함께 추가(scope creep).

### Previous Story Intelligence (Story 1.1 학습)

[Source: `_bmad-output/implementation-artifacts/1-1-프로젝트-부트스트랩.md` Dev Agent Record + Review Findings + `deferred-work.md`]

**적용 패턴(반드시 재사용):**

- `app/main.py`의 `lifespan` 자원 init은 자원별 독립 `try/except` + 실패 시 `app.state.<resource> = None`. 본 스토리에서 추가하는 자원(없음 — 기존 engine/redis/limiter 재사용) 외 추가 시 동일 패턴 적용.
- `tests/conftest.py`의 `_verify_pgvector_extension` session fixture 패턴 참조 — 본 스토리는 추가 precondition 없음(users 테이블은 alembic으로 자동 생성).
- `_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")` 같은 입력 검증 정규식 패턴 — `family_id`, `code_verifier` 등 클라이언트 제공 값에도 화이트리스트 검증 적용 권장.
- `slowapi` Limiter는 Story 1.1에서 키 상수만 정의됨(`RATE_LIMIT_USER_PER_MINUTE = "60/minute"`). 본 스토리 라우터에 데코레이터 적용은 OUT — Story 8 polish (전체 라우터 일괄 적용 정합).

**Story 1.1 deferred-work.md 항목 — 본 스토리 처리 가능:**

- ✅ **mypy `[[tool.mypy.overrides]]` 누락 모듈** — 본 스토리에서 `google.*` 추가 시 동시 처리(Task 1.2). 단 `langgraph`, `langchain*`, `langsmith`, `sse-starlette`, `tenacity`, `structlog`은 본 스토리에서 import 추가 X — 그 항목은 Story 3.x(LangGraph 도입 시점)로 deferred 유지.
- ⏭ **이미지 태그 digest pin** — 본 스토리 영역 X. Story 8 hardening 그대로 유지.
- ⏭ **`alembic upgrade head` migrate 서비스 분리** — multi-replica 도입 시점(Story 4 또는 그 이후)까지 유지. 본 스토리는 Dockerfile.api entrypoint 그대로(`alembic upgrade head && uvicorn ...`). 0002 마이그레이션은 매 부팅 첫 1회만 실 적용(idempotent).

**Detected Conflict 처리:**

- Story 1.1 이미 처리됨(pg17 표기, Tailwind v4, ESLint flat config). 본 스토리는 신규 conflict 없음.
- 단, `python-jose`는 2024년부터 maintenance 휴면 상태(GitHub 이슈 활성도 저하). PyJWT가 더 활성. 본 스토리는 Story 1.1 결정 존중 + `python-jose` 사용 — Story 8 polish에서 PyJWT 마이그레이션 검토 가능.

### Git Intelligence (최근 커밋 패턴)

```
28ea32b Merge pull request #1 from ha-nyang-95/feat/story-1-1-bootstrap
7288596 docs(story-1.1): record integration verification results
c3a9d9a chore(story-1.1): regenerate openapi clients after docstring changes
20eab73 feat(story-1.1): 프로젝트 부트스트랩 + code review 적용
b390944 docs(story-1.1): apply self-review fixes before dev session
1aac28b chore(bmad): commit planning artifacts + Story 1.1 context + sprint plan
```

- 본 스토리 권장 브랜치: `feat/story-1-2-google-oauth-jwt`.
- 커밋 패턴: `feat(story-1.2): ...` / `chore(story-1.2): regenerate openapi clients` / `docs(story-1.2): ...`. 코드 + 클라이언트 재생성을 별 커밋으로 분리(openapi-diff 게이트 통과 가시성).
- PR title: *"feat(story-1.2): Google OAuth + JWT user/admin 분리 + 로그아웃"*.

### 테스트 요구사항

[Source: architecture.md#Structure Patterns "테스트 위치", PRD NFR-M1, Story 1.1 Dev Notes "테스트 요구사항"]

- 백엔드 테스트 위치: `api/tests/` 미러 구조. 본 스토리 신규: `test_auth_security.py`, `test_auth_router.py`, `test_users_me.py`, `test_problem_details.py`.
- async fixture: 기존 `tests/conftest.py`의 `client` fixture(ASGITransport + lifespan_context) 재사용. `user_factory` async fixture 추가 — DB에 직접 INSERT(SQLAlchemy session) 또는 `POST /v1/auth/google`을 stub 후 호출.
- Google API mock: `monkeypatch`로 `app.adapters.google_oauth.verify_id_token` + `exchange_code` stub. `respx`는 도입 옵션(가볍게 가려면 monkeypatch 충분).
- coverage gate: `--cov=app --cov-fail-under=70`. Story 1.1의 `omit = ["app/core/security.py", "app/core/exceptions.py"]`는 본 스토리에서 두 모듈 모두 채워지므로 **omit 목록 비우기**. 신규 모듈 모두 측정 대상에 포함.
- TS 측 단위 테스트는 본 스토리 OUT (Story 1.6 또는 Epic 8). `tsc --noEmit` 게이트만 적용.

### CI 게이트 (변경 사항)

- `.github/workflows/ci.yml`은 Story 1.1에서 7잡 정의 완료. 본 스토리는 워크플로우 자체 수정 X — 단, `test-api` 잡은 신규 추가된 `tests/test_auth_*.py` 등을 자동 포함(`pytest`가 `tests/` 전체 수집).
- `openapi-diff` 잡은 본 스토리 종료 시점에 `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts`가 새 endpoint(`/v1/auth/*`, `/v1/users/me`)를 반영해야 통과. Task 8.1로 명시.
- Google OAuth는 외부 의존성이므로 `test-api` CI 잡에서 실 Google 호출 X — 모든 테스트는 mock/stub 기반.

### Project Structure Notes

- architecture.md 폴더 트리는 8주 종료 시점 *목표* 구조. 본 스토리는 위 "Story 1.2 종료 시점 신규 항목"에 명시된 항목만 생성. premature scaffolding 회피.
- `app/services/auth_service.py`는 본 스토리에서 도입 X — 라우터가 직접 `adapters/google_oauth.py` + `core/security.py`만 호출하면 충분. service layer 분리는 Story 5.x(회원 탈퇴 + 데이터 export 책임 추가) 또는 Story 7.1(admin 로그인 흐름) 시점에 도입.
- `app/db/models/`에 본 스토리는 `user.py`, `refresh_token.py` 2개만 생성. 나머지(`meal.py`, `consent.py` 등)는 해당 스토리가 도입.
- Web `(public)` / `(user)` / `(admin)` route group 컨벤션은 architecture.md (line 740-761) 정합. 본 스토리는 `(public)` + `(user)` 그룹 도입(`(admin)`은 Story 7.1).

### Detected Conflicts / Variances

| # | 이슈 | 해결 |
|---|------|-----|
| 1 | architecture.md A1(`/auth/google`)와 본 스토리(`/v1/auth/google`)의 path prefix 차이 | **`/v1/auth/google` 사용** — Story 1.1 Dev Notes "API URL"에 `/v1/` prefix 명시. PRD A1은 prefix 생략 표기. |
| 2 | `python-jose` maintenance 휴면 상태 vs Story 1.1 결정 | **Story 1.1 결정 존중** — `python-jose` 사용. PyJWT 마이그레이션은 Story 8 polish 검토 (deferred-work.md에 신규 항목 추가 권장) |
| 3 | refresh token: JWT vs opaque random | **opaque random 채택** — DB 저장 + rotation + replay detection 표준 패턴. JWT refresh + denylist는 90일 TTL로 denylist 폭증 anti-pattern |
| 4 | Google OAuth client id 분리(iOS/Android/Web) | Expo SDK 54 + expo-auth-session 표준 — 3종 client id 발급 후 platform별 동적 선택. README SOP에 Google Cloud Console 발급 절차 명시(Task 9.1). dev 환경(Expo Go)은 web client id 사용 |
| 5 | admin JWT 발급 시점 | **별도 endpoint `POST /v1/auth/admin/exchange`** — Story 1.2는 인프라 + endpoint 제공, Story 7.1이 admin 로그인 UI를 wire up. AC3가 발급 흐름 보장 |
| 6 | Web 측 OAuth callback이 백엔드 redirect vs Next.js route handler 처리 | **Next.js route handler가 백엔드 호출** — architecture.md(line 305) "Web은 백엔드 redirect"이지만 SSR 환경에서 Next.js middleware/route handler가 백엔드를 호출한 뒤 cookie를 forward하는 패턴이 더 표준. 백엔드는 동일 endpoint(`POST /v1/auth/google`) 처리. 결과 동등. |

### References

- Story 1.2 AC 원문: [Source: epics.md#Story 1.2 (line 428-441)]
- Authentication & Security 결정: [Source: architecture.md#Authentication & Security (line 301-313)]
- API & Communication Patterns (RFC 7807 + SSE 표준): [Source: architecture.md#API & Communication Patterns (line 314-326), Format Patterns (line 457-471)]
- Process Patterns 인증 401 흐름: [Source: architecture.md#인증 401 흐름 (line 533-537)]
- API 라우터 분할 표준: [Source: architecture.md#Structure Patterns (line 442-446)]
- 폴더 구조 목표: [Source: architecture.md#Complete Project Directory Structure (line 569-841)]
- Capability 매핑 (Identity & Account → auth.py + users.py): [Source: architecture.md#Requirements to Structure Mapping (line 874-884)]
- Cross-cutting Concerns 인증/권한: [Source: architecture.md#Cross-Cutting Concerns (line 87-100, "#2 인증/권한")]
- Anti-pattern 카탈로그: [Source: architecture.md#Anti-pattern 카탈로그 (line 557-565)]
- 사용자 journey J1 (OAuth 진입 happy path): [Source: prd.md#Journey 1 (line 273-285)]
- FR1 / FR4: [Source: prd.md#1. Identity & Account (line 940-947)]
- TC1 보안 / NFR-S1~S10: [Source: prd.md#Technical Constraints (line 463-477), prd.md#NFR Security (line 1041-1052)]
- 폴더·파일·env 명세 from Story 1.1: [Source: implementation-artifacts/1-1-프로젝트-부트스트랩.md Dev Notes "폴더 구조" + "환경변수"]
- Mobile permission 흐름 (M5): [Source: prd.md#M5 (line 661-670)]
- google-auth `verify_oauth2_token` 표준 사용: [Web Research, 2026-04 — google-auth>=2.36, accounts.google.com 또는 https://accounts.google.com issuer 검증, ValueError 예외 처리]
- expo-auth-session Google + PKCE: [Web Research, 2026-04 — `expo-auth-session/providers/google`, `responseType=code` + PKCE auto, OAuth 2.1 mandate 정합]

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (Amelia / bmad-dev-story workflow), 2026-04-27.

### Debug Log References

- 단위/통합 테스트 42건 — `cd api && uv run pytest` (76.18% coverage).
- ruff + ruff format + mypy strict — clean(0 errors / 0 warnings).
- `pnpm tsc --noEmit` (web + mobile), `pnpm build` (web), `pnpm lint` (web) — clean.
- alembic upgrade → downgrade → upgrade idempotency 로컬 검증.

### Completion Notes List

- **AC1 통과** — `POST /v1/auth/google` (mobile/web), Google id_token verify_oauth2_token + email_verified 검증, users UPSERT, HS256 user JWT (access 30일 + opaque refresh 90일).
- **AC2 통과** — mobile은 응답 body로 토큰 반환(secure-store 보관), web은 `bn_access`(Path=/) + `bn_refresh`(Path=/v1/auth) httpOnly+SameSite=Strict 쿠키 발급. `Secure` flag는 dev/ci/test 외 모든 환경에서 강제(`NON_SECURE_COOKIE_ENVIRONMENTS`).
- **AC3 통과** — `POST /v1/auth/admin/exchange` (8h, HS256 + admin secret + admin issuer + role==admin enforcement). Web 응답에 `bn_admin_access` Path=/v1/admin 쿠키. issuer mismatch 차단 단위 테스트로 검증.
- **AC4 통과** — refresh rotation + replay detection (family-wide revoke). 클라이언트 인터셉터: mobile `authFetch` + web `apiFetch` 모두 401 → refresh 1회 → 재시도, in-flight 단일화로 중복 차단. admin은 refresh 미지원 — 401 시 `/admin/login`.
- **AC5 통과** — `POST /v1/auth/logout` 204, refresh sha256 hash 매칭 row revoke + Web 응답에 `Max-Age=0` 쿠키 클리어. mobile은 클라이언트가 secure-store delete + `/(auth)/login` 라우팅.
- **AC6 통과** — mobile `app/index.tsx` redirect + `(tabs)/_layout.tsx` 가드(`useAuth().isAuthed`); web `src/middleware.ts` matcher(`/dashboard/*`, `/admin/*`) + `?next=` 보존.
- **AC7 통과** — `0002_users_and_refresh_tokens` 마이그레이션 — partial index `idx_users_role_admin`, CHECK `role IN ('user','admin')`, FK `refresh_tokens.user_id → users.id ON DELETE CASCADE`, 인덱스 5종(unique 자동 + 명시 3종). `gen_random_uuid()` Postgres 17 core.
- **AC8 통과** — `app/core/exceptions.py`에 ProblemDetail + 8건 auth 코드 카탈로그. main.py 핸들러 3개(BalanceNoteError → RequestValidationError → HTTPException). 401 응답에 `WWW-Authenticate: Bearer realm="balancenote", error="invalid_token"` 헤더 첨부 (RFC 6750).
- **AC9 통과** — `current_user` / `current_admin` Depends, `GET /v1/users/me` smoke endpoint(snake_case 응답).
- **AC10 통과** — Mobile: `secure-store.ts`(WHEN_UNLOCKED) + `auth.tsx`(QueryClient + AuthProvider) + `useGoogleSignIn.ts`(expo-auth-session/providers/google + Code + PKCE auto) + `(auth)/login.tsx` + `(tabs)/{_layout,index}.tsx`. `_layout.tsx`에 Provider 래핑.
- **AC11 통과** — Web: `(public)/login/page.tsx` + `api/auth/google/{start,callback}/route.ts` + `middleware.ts` + `lib/{auth,api-fetch,query-client}.ts`. start 핸들러는 state + PKCE를 SameSite=Lax 임시 쿠키로 발급(Strict이면 OAuth 흐름 깨짐).
- **AC12 통과** — `tests/test_auth_security.py`(14) + `test_problem_details.py`(5) + `test_auth_router.py`(13) + `test_users_me.py`(5) + 기존 `test_health.py`(5) = 42건 통과. coverage 76.18%(--cov-fail-under=70 통과).

**Detected variances vs. story spec (의도적 변경)**:
- `auth.token.issuer_mismatch` 코드는 user secret으로 서명된 admin issuer 위조 토큰에서만 발생. admin secret으로 서명된 토큰을 user 라우트에 보내면 jose가 서명 단계에서 차단해 `auth.access_token.invalid`로 노출됨 — 두 secret 분리가 1차 방어선이라 의도된 동작. 두 코드 모두 수용하도록 테스트 작성.
- replay 후 family 전체 revoke 시 같은 family의 다른 토큰 재제시도 `auth.refresh.replay_detected`로 응답(이미 revoked). 설계 정합 — 위협 신호.
- `_issue_user_session` helper는 `_upsert_user_from_google` + 인라인 토큰 발급 사이에 끼지 않아 제거. 라우터 직접 처리.
- `idx_users_email`은 본 스토리 OUT 명시대로 미생성.

**Story 1.1 deferred-work 반영**:
- mypy `[[tool.mypy.overrides]]`에 `google.*` 추가(deferred-work.md 항목 1건 처리).
- `path_separator = os` 미설정 alembic 경고는 단순 deprecation — 본 스토리 외 처리(Story 8 polish).

**Next.js 16 deprecation**:
- `middleware.ts` → `proxy.ts` 이름 변경은 Next.js 16 이상에서 권장 — 본 스토리는 Story spec 정합으로 `middleware.ts` 유지. Story 8 polish로 deferred.

### File List

**Backend (api/)**

신규:
- `api/app/db/__init__.py`
- `api/app/db/base.py`
- `api/app/db/session.py`
- `api/app/db/models/__init__.py`
- `api/app/db/models/user.py`
- `api/app/db/models/refresh_token.py`
- `api/app/adapters/__init__.py`
- `api/app/adapters/google_oauth.py`
- `api/app/api/__init__.py`
- `api/app/api/deps.py`
- `api/app/api/v1/__init__.py`
- `api/app/api/v1/auth.py`
- `api/app/api/v1/users.py`
- `api/alembic/versions/0002_users_and_refresh_tokens.py`
- `api/tests/test_auth_security.py`
- `api/tests/test_problem_details.py`
- `api/tests/test_auth_router.py`
- `api/tests/test_users_me.py`

수정:
- `api/pyproject.toml` — `google-auth>=2.36` 의존성 + mypy override `google.*` + coverage omit 비움.
- `api/app/core/config.py` — JWT audience/TTL/cookie 환경 상수 + `cors_allowed_origins` 필드.
- `api/app/core/security.py` — placeholder 제거, JWT/refresh 유틸 구현.
- `api/app/core/exceptions.py` — placeholder 제거, ProblemDetail + 도메인 예외 계층.
- `api/app/main.py` — CORS + RFC 7807 핸들러 3종 + `/v1/auth` `/v1/users` 라우터 등록.
- `api/alembic/env.py` — `target_metadata = Base.metadata` + 모델 import.
- `api/tests/conftest.py` — alembic upgrade head + truncate fixture + user_factory + auth_headers helper.
- `api/uv.lock`

**Mobile (mobile/)**

신규:
- `mobile/lib/secure-store.ts`
- `mobile/lib/auth.tsx`
- `mobile/features/auth/useGoogleSignIn.ts`
- `mobile/app/(auth)/_layout.tsx`
- `mobile/app/(auth)/login.tsx`
- `mobile/app/(tabs)/_layout.tsx`
- `mobile/app/(tabs)/index.tsx`

수정:
- `mobile/package.json` — `expo-auth-session`, `expo-crypto`, `expo-secure-store`, `@tanstack/react-query` 추가.
- `mobile/pnpm-lock.yaml`
- `mobile/app/_layout.tsx` — QueryClientProvider + AuthProvider + Stack 그룹 등록.
- `mobile/app/index.tsx` — Story 1.1 placeholder 제거 + 인증 분기.
- `mobile/lib/api-client.ts` — OpenAPI 재생성.
- `mobile/.env.example` — Google OAuth client ID 3종.
- `mobile/.expo/types/router.d.ts` — typed routes 갱신((auth)/login + (tabs) 추가).

**Web (web/)**

신규:
- `web/src/lib/auth.ts`
- `web/src/lib/api-fetch.ts`
- `web/src/lib/query-client.ts`
- `web/src/app/(public)/login/page.tsx`
- `web/src/app/api/auth/google/start/route.ts`
- `web/src/app/api/auth/google/callback/route.ts`
- `web/src/app/(user)/dashboard/page.tsx`
- `web/src/middleware.ts`

수정:
- `web/package.json` — `@tanstack/react-query` 추가.
- `web/pnpm-lock.yaml`
- `web/src/lib/api-client.ts` — OpenAPI 재생성.
- `web/.env.example` — Google OAuth + API base URL.

**Root**
- `README.md` — Google OAuth Client 발급 SOP + 인증 디버깅 SOP 추가.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — 1-2 → review.
- `_bmad-output/implementation-artifacts/1-2-google-oauth-로그인-jwt.md` — 본 파일.

### Change Log

| Date | Change |
|------|--------|
| 2026-04-27 | Story 1.2 dev 시작 — `Status: ready-for-dev → in-progress` 전환. |
| 2026-04-27 | Backend: 0002 마이그레이션 + JWT/Google adapter + RFC 7807 + `/v1/auth/*` + `/v1/users/me` 구현, 단위·통합 테스트 42건 통과. |
| 2026-04-27 | Mobile: secure-store + AuthProvider + useGoogleSignIn + (auth)/login + (tabs) placeholder + index 분기 구현, `pnpm tsc --noEmit` 통과. |
| 2026-04-27 | Web: login 페이지 + Google start/callback route + middleware 가드 + dashboard placeholder 구현, `pnpm tsc/build/lint` 통과. |
| 2026-04-27 | OpenAPI 클라이언트 재생성(4 auth + 1 users path 추가). README에 Google OAuth client SOP + 인증 디버깅 SOP 추가. `Status: review` 전환. |
