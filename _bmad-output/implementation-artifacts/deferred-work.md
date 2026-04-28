# Deferred Work

리뷰·구현 과정에서 식별되었으나 다음 스토리·시점으로 미룬 항목 모음.

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

## Spec deviation: logout endpoint (2026-04-28, PR #2 review followup)

- **AC5 spec**: 모바일은 `Authorization: Bearer <access>` + body `{refresh_token}` 두 필드 동시 전송 (logout 시 access token 검증).
- **실제 구현**: refresh-only — `current_user` Depends 미사용. body / 쿠키의 refresh token sha256 hash 매칭 row만 revoke.
- **사유 (PR #2 Gemini Code Assist review comment #2 거부 결정)**:
  1. **만료 세션 강제 종료 보존**: access token 만료된 사용자가 logout 시도 시 `current_user` Depends가 401 발사 → 클라이언트 인터셉터가 refresh 시도 → 또 만료면 logout 자체 불가. *세션 정리* 흐름이 깨진다. refresh-only는 만료 세션도 정상 logout 가능.
  2. **CSRF 방어는 별도 layer**: JSON body 요구(`Content-Type: application/json` + `{refresh_token}` 필드)로 form POST CSRF 차단 + SameSite=Lax 쿠키. logout-CSRF 위협 모델은 *피해자 강제 로그아웃*(annoyance 수준) — refresh token 본인만 알기에 무차별 발사 불가.
  3. **refresh token = 본인 식별자**: 평문 32-byte URL-safe random + DB sha256 매칭. token 보유자만 logout 가능 — access token 검증과 동등한 보증.
- **재검토 시점**: 외부 보안 audit / 외주 클라이언트 보안 요구사항 변경 시. 또는 Story 5.x(전체 디바이스 로그아웃) 도입 시점에 access token 검증 layer 추가 검토.
