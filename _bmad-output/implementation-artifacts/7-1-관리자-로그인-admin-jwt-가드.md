# Story 7.1: 관리자 로그인 + admin role JWT 분리 + 가드

Status: done

<!-- Validation: Epic 7 첫 스토리 — Story 1.2(`core/security.py:create_admin_token`/
`verify_admin_token` + `api/deps.py:current_admin` + `POST /v1/auth/admin/exchange` +
`bn_admin_access` httpOnly 쿠키 + `users.role` 컬럼 + `idx_users_role_admin` partial
index + Web `middleware.ts` `/admin/:path*` 가드 placeholder + `/admin/login` stub
페이지) 위에 *Web 실 OAuth 흐름 + (admin) route group server-side guard +
middleware admin cookie stale-self-heal + IP 화이트리스트 옵션 + admin 1인 부여
SOP 스크립트* 5건을 추가해 Epic 7 *FR35 admin role 분리 인증* 닫는다.
epics.md:875-888 정합 + architecture.md:306 *"`admin`: HS256 access 8시간/refresh 없음
+ IP 화이트리스트 옵션"* 정합 + architecture.md:536 *"Admin: refresh 미지원이므로 401
즉시 admin 로그인 화면"* 정합. **본 스토리는 백엔드 admin auth core SOT 변경 0건
— Story 1.2 베이스라인 *재사용*만 수행** (admin JWT 발급/검증/현재유저 dep는 모두
Story 1.2 산출물). 신규 4 영역: (1) **Web `/admin/login` 실 OAuth chain UI**
(현재는 placeholder Link) — `bn_access` 쿠키 보유 시 `/api/auth/admin/exchange`
1-click + 미보유 시 `/api/auth/google/start?next=/admin/login` chain, (2) **Web
`(admin)` route group + `layout.tsx` server-side guard** (defense-in-depth — middleware
는 라우팅 차단, layout은 cookies().get + JWT exp/role decode), (3) **Web `middleware.ts`
admin 쿠키 stale-self-heal 확장** — Story 1.2 user 쪽 `classifyAccessCookie`
패턴(exp claim decode)을 admin 쿠키에도 적용해 *length-only* 검사로 인한 무한 redirect
루프 회피, (4) **백엔드 IP 화이트리스트 옵션** — `ADMIN_IP_ALLOWLIST` env(comma-CIDR)
+ `core/proxy.py:check_admin_ip_allowed` 헬퍼 + `api/deps.py:require_admin_ip_allowed`
dep + `AdminIpBlockedError(403, code=auth.admin.ip_blocked)` 예외 — *MVP는 빈 리스트
default → 미강제*(NFR-S8 정합). 추가 운영 1건: **`scripts/promote_admin.py` CLI** —
1인 개발자가 `users.role`을 `'user' → 'admin'` flip 가능(`idx_users_role_admin` partial
index hit) + `docs/sop/05-admin-role-promotion.md` SOP. **Story 7.3 forward-compat:**
admin 라우터(`POST /v1/auth/admin/exchange` 등) 호출 시 *audit log 기록*은 본 스토리에서
*미수행* — `audit_logs` 테이블 + `audit_admin_action` dep는 7.3에서 신설(*FR37 본격
수행*). 본 스토리는 **CR P1 회귀 가드 6건 + 신규 단위 14건 + Web 단위 7건** 도합
*~27건* 신규 테스트로 Story 1.2 베이스라인 + 신규 4 영역의 invariant 보존. 신규 환경
변수 1건(`ADMIN_IP_ALLOWLIST`) + 신규 alembic 0건(베이스라인 schema 재사용) + 신규
backend 모듈 1건(`app/api/deps.py:require_admin_ip_allowed` + `core/proxy.py:
check_admin_ip_allowed`) + 신규 web route handler 1건(`api/auth/admin/exchange`) +
신규 web 파일 4건((admin) route group). 본 스토리 후 sprint-status에 `epic-7:
backlog → in-progress` + `7-1-...: ready-for-dev → in-progress → review` 전이.
PR pattern: feature branch `story/7.1-admin-login-jwt-guard` (master에서 분기, CS
시작 직전 분기 완료) — DS/CR 모두 동일 브랜치, PR은 CR 완료 후 1회. -->

## Story

As a 관리자(병원 의료정보팀 등),
I want 일반 사용자와 분리된 admin role 인증으로 Web 관리자 화면에 진입하기를,
So that 권한 침범 위험을 차단하고 관리자 액션의 책임 범위를 명확히 분리한다.

## Acceptance Criteria

1. **AC1 — Story 1.2 백엔드 admin auth 베이스라인 *재사용 + 명시 회귀 가드***
   **Given** Story 1.2 산출물 — `api/app/core/security.py:create_admin_token`(HS256, `JWT_ADMIN_AUDIENCE="balancenote-admin"`, `ADMIN_ACCESS_TOKEN_TTL_SECONDS=8*60*60`, refresh 없음) + `verify_admin_token`(issuer + audience + role enforcement + leeway 60s) + `AdminTokenClaims` dataclass + `api/app/api/deps.py:current_admin_claims`(Authorization 헤더 또는 `bn_admin_access` 쿠키 fallback) + `current_admin`(role==admin 재확인) + `api/app/api/v1/auth.py:POST /v1/auth/admin/exchange`(user JWT → admin JWT 교환 + Web 분기 시 `bn_admin_access` Path=/v1/admin httpOnly 쿠키 발급, mobile 분기 시 body로 admin_access_token 반환) + `users.role: Mapped[str]`(default `'user'`, CHECK `IN ('user','admin')`) + `idx_users_role_admin` partial index + `AdminRoleRequiredError(403, code=auth.admin.role_required)` 예외 + `IssuerMismatchError(401, code=auth.token.issuer_mismatch)` 예외 — **본 스토리는 위 SOT를 변경 0건**. 단, Story 7.1이 *FR35 인증 분리* 본격 수행이므로 Story 1.2가 가드한 invariant들의 *명시 회귀 가드 테스트*를 본 스토리 owner로 흡수, **When** `api/tests/api/v1/test_admin_auth_baseline.py` 신규 1파일 + 6 회귀 케이스 작성, **Then**:
   - **`test_admin_token_expires_at_8_hours`** — `create_admin_token(user.id, now=fixed_now)` → `verify_admin_token` claims.expires_at == fixed_now + 8h(±leeway). `ADMIN_ACCESS_TOKEN_TTL_SECONDS` 상수 변경 회귀 차단.
   - **`test_admin_token_no_refresh_capability`** — `/v1/auth/refresh` endpoint를 `bn_admin_access` 쿠키만 보유한 상태로 호출 → 401 `auth.refresh.invalid` (admin 쿠키는 refresh 흐름에 미관여 + `bn_refresh` 쿠키 별 path). FR35 *"refresh 없음"* invariant 회귀.
   - **`test_admin_token_8h_expired_returns_401`** — `create_admin_token(user.id, now=now-8h-1s)`로 *과거에 발행된* 만료 토큰 + protected admin endpoint(*7.1은 admin 라우터 신설 X — `POST /v1/auth/admin/exchange`는 user JWT 검증이라 admin token 검증 케이스 별도 필요*. 본 스토리에서 **smoke endpoint** `GET /v1/auth/admin/whoami` 1건 신설(아래 AC4 참조 — *Web layout.tsx server-side guard 회복*에 사용) → 만료 admin 토큰 → 401 `auth.access_token.expired`).
   - **`test_admin_token_issuer_mismatch_returns_401`** — `jwt.encode` user secret으로 admin issuer 위조 → `verify_admin_token` 호출 시 `IssuerMismatchError`(401 `auth.token.issuer_mismatch`). admin secret이 분리되어 있어도 *issuer 명시 검증*이 second-line guard.
   - **`test_user_token_blocked_on_admin_endpoint_with_403`** — `create_user_token(user.id, role="user", platform="web")`로 발급된 토큰을 `GET /v1/auth/admin/whoami`에 첨부 → 403 `auth.admin.role_required` (RFC 7807 형식 — `type`/`title`/`status`/`detail`/`instance` 5필드 + `code` 확장). Story 1.2 `current_admin` 흐름이 user issuer 토큰을 *issuer mismatch*로 1차 차단(401)하지만 *role==admin* 재확인이 *role 미적합 시 403* 분기 — **본 케이스는 admin issuer + role=user 위조 토큰 시나리오**(잘못된 secret으로 위조 X, *합법 admin secret으로 발급되지만 role claim이 user인 토큰* — `create_admin_token`은 항상 role="admin" 박지만 `jwt.encode`로 직접 위조 가능 — admin user가 **role을 user로 다운그레이드하려는 시도** 시뮬레이션).
   - **`test_admin_role_change_to_user_blocks_admin_endpoint`** — admin user의 `users.role`을 *런타임에* `'user'`로 update 후 *기존* admin JWT(여전히 valid) 재사용 → `current_admin`의 *DB role 재확인 분기*에서 403 `auth.admin.role_required` (DB가 SOT — JWT claim 신뢰 X). FR35 *"admin role 매핑은 별 관리"* invariant 회귀(권한 박탈 즉시 반영).
   - **회귀 가드**: `test_auth_router.py:test_admin_exchange_succeeds_for_admin` + `test_admin_exchange_blocks_non_admin` + `test_admin_exchange_web_returns_cookie_only_no_body_token` + `test_admin_token_rejected_on_user_endpoint` + `test_user_token_with_admin_issuer_rejected` 5건은 **Story 1.2 SOT** — 본 스토리에서 *변경 X*(테스트 자체 보존). 본 스토리 신규 6건은 *별 파일*(`test_admin_auth_baseline.py`)로 분리 — Story 1.2 baseline owner와 Story 7.1 *integration owner* 명시 분리.

2. **AC2 — Smoke endpoint `GET /v1/auth/admin/whoami` 신설** (Web layout.tsx server-side guard 회복 + AC1 회귀 fixture)
   **Given** Story 1.2가 admin auth core SOT를 갖췄지만 *admin 라우터*는 0건(7.2가 본격 신설) — Story 7.1의 Web `(admin)/admin/layout.tsx`가 *server-side defense-in-depth*로 admin 식별을 backend roundtrip 또는 *local JWT decode* 둘 중 하나로 수행해야 + AC1 회귀 케이스(`test_admin_token_8h_expired_returns_401` 등)도 *protected admin endpoint*가 1건 이상 있어야 cleanly assert 가능, **When** `api/app/api/v1/auth.py`에 `GET /v1/auth/admin/whoami` 엔드포인트 1건 추가, **Then**:
   - **신규 endpoint** (`auth.py` SOT — `admin.py`는 7.2에서 신설하므로 본 스토리는 *임시 위치* `auth.py` 사용 + 7.2 시점에 *이동 X — `auth.py` 그대로 유지*. 사유: `auth/whoami`는 *인증 정보* 조회 의미가 강해 `admin.py`(business action — 사용자 검색·수정)와 책임 분리):
     ```python
     class AdminWhoamiResponse(BaseModel):
         """Admin 전용 *인증 정보 echo* — Web (admin) layout.tsx server-side guard에 사용.

         이메일은 마스킹된 형태(`j***@example.com`) 노출(NFR-S5 정합) — 본 endpoint는
         admin 자기 자신 정보 조회이지만 향후 *audit log*(Story 7.3) 기록 대상이라
         response payload 자체에 plaintext 이메일을 포함하지 않는다(server-side log + UI
         양쪽 마스킹 일관).
         """
         user_id: uuid.UUID
         email_masked: str
         role: Literal["admin"]
         token_expires_at: datetime  # admin JWT exp claim — Web에서 8h countdown UI에 사용 가능.


     @router.get("/admin/whoami")
     async def admin_whoami(
         claims: Annotated[AdminTokenClaims, Depends(current_admin_claims)],
         user: Annotated[User, Depends(current_admin)],
     ) -> AdminWhoamiResponse:
         """admin JWT 검증 + DB role 재확인 + 마스킹된 echo. 본 endpoint는 *읽기 전용*
         이라 audit log 기록 대상 *X*(Story 7.3 enum scope에서 admin meta-info 조회 제외).
         """
         masked = _mask_email(user.email)
         return AdminWhoamiResponse(
             user_id=user.id,
             email_masked=masked,
             role="admin",
             token_expires_at=claims.expires_at,
         )


     def _mask_email(email: str) -> str:
         """`j***@example.com` 패턴. local part 첫 1자 + `***` + `@domain` 표시. local
         part 길이 1자 시 `***@domain`(개인 식별성 0). NFR-S5 SOT — Sentry beforeSend
         hook이 사용하는 마스킹 규칙과 동일(structlog processor SOT는 logging.py).
         """
         if "@" not in email:
             return "***"
         local, _, domain = email.partition("@")
         if len(local) <= 1:
             return f"***@{domain}"
         return f"{local[0]}***@{domain}"
     ```
   - **`AdminWhoamiResponse` Pydantic** — `model_config = ConfigDict(extra="forbid")` + 4 필드 모두 required. `email_masked`는 *plaintext 이메일 노출 차단* 의무.
   - **위치 결정**: `auth.py`에 첨부(별 라우터 분리 X). 사유: 본 endpoint는 *인증 정보 echo*이지 business action이 아님 + admin.py는 7.2에서 *사용자 검색·수정* business 라우터로 신설. `auth.py`의 `__all__` 갱신 불필요(`router`/`clear_auth_cookies` 그대로).
   - **wire**: `app/main.py` — `auth_router`는 이미 등록됨 (`include_router(auth_router, prefix="/v1/auth")`). 신규 wire 0건.
   - **OpenAPI 자동 갱신** — `pnpm gen:api` 후 `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts`에 `getAdminWhoami` operation 추가됨. *7.1 시점 mobile 사용 X*이지만 OpenAPI는 1 SOT라 자동 갱신 동기.
   - **단위 테스트** `api/tests/api/v1/test_admin_auth_baseline.py` 동일 파일에 흡수:
     - `test_admin_whoami_succeeds_for_admin` — admin user + admin JWT → 200 + 마스킹된 email + role=admin + `token_expires_at` 본문 정합.
     - `test_admin_whoami_blocks_non_admin` — user role 사용자가 *위조된* admin issuer 토큰 → 403 (AC1 동일 케이스 별 assertion).
     - `test_admin_whoami_blocks_missing_token` — Authorization 헤더 + 쿠키 모두 부재 → 401 `auth.access_token.invalid` (`current_admin_claims` 흐름).
   - **`_mask_email` 단위 테스트** `api/tests/test_email_mask.py` 신규 1파일 + 4 케이스: 일반(`j***@example.com`) + 1자 local(`***@example.com`) + `@` 부재(`***`) + 빈 string(`***`). 본 helper는 *NFR-S5 SOT 회귀*라 별 파일 owner 분리.

3. **AC3 — `scripts/promote_admin.py` CLI + `docs/sop/05-admin-role-promotion.md` SOP** (FR35 *"admin role 매핑은 별 관리"* invariant 운영 SOT)
   **Given** `users.role` CHECK `IN ('user','admin')` + `idx_users_role_admin` partial index 베이스라인 + 외주 인수 시 *환경별 admin 사용자 별 부여* 의무 + alembic seed 거부(env in code anti-pattern — DB row가 SOT) + 기존 `scripts/` 패턴(uv run 호환 + asyncpg 또는 SQLAlchemy 직접 사용 + argparse), **When** 신규 CLI + SOP 작성, **Then**:
   - **신규 파일** `scripts/promote_admin.py` (~80 lines):
     ```python
     """Admin role flip CLI (Story 7.1).

     Usage:
       uv run python scripts/promote_admin.py --email user@example.com
       uv run python scripts/promote_admin.py --email user@example.com --demote

     Flow:
       1. asyncpg engine 연결(`settings.database_url` SOT).
       2. SELECT id, email, role, deleted_at FROM users WHERE email=$1 AND deleted_at IS NULL.
       3. 미발견 → exit code 1 + stderr "사용자를 찾을 수 없습니다".
       4. 현재 role 출력 + confirm prompt("현재 role: {role}, '{target_role}'로 flip?
          [y/N]:") — `--yes` 인자 시 prompt skip(automation/CI 호환).
       5. UPDATE users SET role=$1 WHERE id=$2 (트랜잭션 wrap).
       6. SELECT 재조회 + 결과 출력 ("사용자 user@example.com role: user → admin").
       7. **forward-compat**: Story 7.3 audit log 도입 시 본 CLI도 audit_logs row INSERT
          (actor_id="cli", action="admin_role_flip", target_user_id=...) 추가 — 본 스토리는
          forward stub 코멘트만 인용.

     안전 장치:
       - dev/test/ci 환경: confirm prompt 디폴트 enabled.
       - prod/staging: --yes 미지정 시 stdin 부재(non-tty) 감지 → fail-fast(*실수 자동
         실행 차단*).
       - target_role이 현재 role과 동일 → exit 0 + warning ("이미 admin입니다 — 변경 없음").
       - --demote 인자 시 admin → user (역방향 동일 흐름).
     """
     ```
   - **CLI argparse**:
     - `--email` (required) — flip 대상 사용자 식별자.
     - `--demote` (optional flag) — admin → user (default는 user → admin).
     - `--yes` (optional flag) — confirm prompt skip.
   - **트랜잭션 wrap**: `async with engine.begin() as conn: await conn.execute(update(...))` — 실패 시 자동 rollback.
   - **에러 처리**:
     - 사용자 미발견 → exit 1 + stderr 한국어 메시지.
     - DB 연결 실패 → exit 2 + stderr 한국어 메시지 + 원인 (DSN 미설정 등).
     - confirm 미통과 (n/N) → exit 0 + stdout "취소되었습니다 — role 변경 없음".
     - prod/staging + `--yes` 미지정 + non-tty → exit 3 + stderr "prod/staging에서는 --yes 명시 필요".
   - **신규 SOP** `docs/sop/05-admin-role-promotion.md` (~50 lines):
     - 1. *언제 사용하는가* — 외주 인수 후 클라이언트가 자기 admin 사용자 부여 시점.
     - 2. *사전 조건* — `.env` SOT의 `DATABASE_URL` 환경 변수 + `uv` 설치.
     - 3. *실행 절차* — 4 step (Google OAuth로 가입 → email 확인 → CLI 실행 → 결과 검증).
     - 4. *검증* — `psql -c "SELECT id, email, role FROM users WHERE email='user@example.com'"` 또는 `GET /v1/auth/admin/whoami`로 마무리 회신.
     - 5. *권한 박탈* — `--demote` 사용 + DB row만 SOT(JWT 즉시 무효 — `current_admin` 흐름이 DB role 재확인).
     - 6. *Audit trail forward* — Story 7.3 audit log 도입 후 audit_logs row 자동 추가 예정 — 본 SOP 갱신 메모.
     - 7. *대체 흐름 — psql 직접 UPDATE* — 본 CLI 실행 불가 환경의 fallback (단, *권장 X* — 트랜잭션/검증 누락 위험).
   - **단위 테스트** `api/tests/scripts/test_promote_admin.py` 신규 1파일 + 6 케이스:
     - `test_promote_user_to_admin_succeeds` — fixture user → CLI invoke (subprocess 또는 직접 함수 호출) → DB role=admin assert.
     - `test_promote_admin_to_admin_warns_no_change` — 이미 admin → exit 0 + warning + DB 변경 0건.
     - `test_demote_admin_to_user` — `--demote` flag → admin → user.
     - `test_promote_user_not_found_exits_with_code_1` — 미존재 email → exit 1.
     - `test_promote_soft_deleted_user_excluded` — `deleted_at IS NOT NULL` user → 미발견 분기.
     - `test_promote_idempotent_within_transaction` — 같은 user 2회 promote 호출 → 두 번째는 warning + DB 변경 0건.
   - **Out of scope (Growth)**: 일괄 promote (csv import) + 이메일 발송 알림 + UI에서 직접 promote (admin이 admin을 부여) — 모두 *외주 인수 후 클라이언트별 정책 결정* 시점 검토.

4. **AC4 — Admin IP 화이트리스트 옵션** (NFR-S8 — env 변수, MVP 강제 X)
   **Given** Story 3.9 `core/proxy.py:get_real_client_ip`(3-tier 우선순위 SOT — Cloudflare CF-Connecting-IP > X-Forwarded-For 신뢰 proxy 범위 > request.client.host raw) + 기존 config.py `_split_cors_origins` validator 패턴(comma-separated → list[str]) + `ipaddress.ip_network` 표준 라이브러리, **When** IP 화이트리스트 dependency + 환경 변수 + 예외 신설, **Then**:
   - **신규 환경 변수** `ADMIN_IP_ALLOWLIST` — `api/app/core/config.py` Settings에 추가:
     ```python
     # --- Admin IP allowlist (Story 7.1, NFR-S8) ---
     # comma-separated CIDR(IPv4/IPv6 모두 지원). 빈 list → 화이트리스트 비활성(MVP
     # default — 외주 클라이언트별 옵션). 잘못된 CIDR 형식은 부팅 시 ValueError raise
     # (fail-fast — 잘못된 설정으로 prod 가동 차단).
     admin_ip_allowlist: list[str] = Field(default_factory=list)


     @field_validator("admin_ip_allowlist", mode="before")
     @classmethod
     def _split_admin_ip_allowlist(cls, v: str | list[str] | None) -> list[str]:
         if v is None or v == "":
             return []
         if isinstance(v, str):
             cidrs = [cidr.strip() for cidr in v.split(",") if cidr.strip()]
         else:
             cidrs = list(v)
         # 부팅 시 CIDR 형식 검증 — runtime fail-soft 회피.
         for cidr in cidrs:
             try:
                 ipaddress.ip_network(cidr, strict=False)
             except ValueError as exc:
                 raise ValueError(f"invalid admin IP allowlist CIDR {cidr!r}: {exc}") from exc
         return cidrs
     ```
   - **신규 helper** `api/app/core/proxy.py:check_admin_ip_allowed(request)`:
     ```python
     def check_admin_ip_allowed(request: Request, allowlist: list[str]) -> bool:
         """admin 요청의 실 클라이언트 IP가 allowlist 범위 내인지 검사.

         allowlist 빈 list → True(미강제 — NFR-S8 MVP default).
         get_real_client_ip 빈 string(헤더 부재 + client None) → False(deny by default).

         Args:
             request: FastAPI Request — `get_real_client_ip` SOT 재사용.
             allowlist: settings.admin_ip_allowlist (이미 부팅 시 형식 검증 통과).
         """
         if not allowlist:
             return True
         client_ip = get_real_client_ip(request)
         if not client_ip:
             return False
         try:
             ip = ipaddress.ip_address(client_ip)
         except ValueError:
             return False
         return any(ip in ipaddress.ip_network(cidr, strict=False) for cidr in allowlist)
     ```
   - **신규 dependency** `api/app/api/deps.py:require_admin_ip_allowed`:
     ```python
     async def require_admin_ip_allowed(
         request: Request,
         claims: Annotated[AdminTokenClaims, Depends(current_admin_claims)],
     ) -> AdminTokenClaims:
         """admin JWT 검증 *직후* IP 화이트리스트 검사. 미통과 시 AdminIpBlockedError(403).

         JWT 검증 *이전* IP 검증은 의미 X — 익명 요청을 IP만으로 차단해도 admin endpoint
         특정 시그널(404 vs 403) 정보 누설 회피보다 *JWT 검증* 1차가 우선. 본 dep는
         current_admin_claims 직후 wire — admin 라우터 chain의 2차 게이트.
         """
         from app.core.config import settings  # 순환 import 회피 — 함수 내 lazy import.
         from app.core.proxy import check_admin_ip_allowed
         if not check_admin_ip_allowed(request, settings.admin_ip_allowlist):
             raise AdminIpBlockedError("admin endpoint accessed from non-allowlisted IP")
         return claims
     ```
   - **신규 예외** `api/app/core/exceptions.py:AdminIpBlockedError`:
     ```python
     class AdminIpBlockedError(AuthError):
         status: ClassVar[int] = 403
         code: ClassVar[str] = "auth.admin.ip_blocked"
         title: ClassVar[str] = "Admin IP not allowed"
     ```
   - **wire**: AC2의 `GET /v1/auth/admin/whoami`에 `Depends(require_admin_ip_allowed)` 추가 wire (smoke endpoint 자체가 IP 가드 통과 검증):
     ```python
     @router.get("/admin/whoami")
     async def admin_whoami(
         claims: Annotated[AdminTokenClaims, Depends(require_admin_ip_allowed)],  # IP 가드.
         user: Annotated[User, Depends(current_admin)],
     ) -> AdminWhoamiResponse:
         ...
     ```
     - 7.2 admin.py 라우터 신설 시 동일 패턴(`require_admin_ip_allowed` + `current_admin`) wire — 7.1의 `whoami`가 *wire 패턴 SOT*.
   - **`.env.example` + `api/.env.example`**:
     ```
     # --- Admin IP allowlist (Story 7.1, NFR-S8) ---
     # comma-separated CIDR. 빈 값 → 미강제(MVP default).
     # 예: ADMIN_IP_ALLOWLIST=203.0.113.0/24,2001:db8::/32
     ADMIN_IP_ALLOWLIST=
     ```
   - **단위 테스트** `api/tests/core/test_admin_ip_allowlist.py` 신규 1파일 + 7 케이스:
     - `test_check_allowed_with_empty_allowlist_returns_true` — `[]` → True (graceful default).
     - `test_check_allowed_with_matching_ipv4_cidr_returns_true` — `["203.0.113.0/24"]` + `request.client.host="203.0.113.42"` → True.
     - `test_check_allowed_with_non_matching_returns_false` — `["203.0.113.0/24"]` + `"198.51.100.1"` → False.
     - `test_check_allowed_with_ipv6_cidr_supported` — `["2001:db8::/32"]` + IPv6 client → True.
     - `test_check_allowed_with_x_forwarded_for_via_trusted_proxy` — `XFF=203.0.113.42` + trusted proxy(loopback) `request.client.host` → `get_real_client_ip` SOT → True (CIDR 매칭).
     - `test_check_allowed_with_no_client_ip_returns_false` — `request.client=None` + 헤더 부재 → False (deny by default).
     - `test_settings_validator_rejects_invalid_cidr_at_boot` — `Settings(admin_ip_allowlist=["not-a-cidr"])` → ValueError raise.
   - **integration 테스트** `api/tests/api/v1/test_admin_auth_baseline.py` 동일 파일에 흡수:
     - `test_admin_whoami_blocked_when_ip_not_allowlisted` — `monkeypatch settings.admin_ip_allowlist=["10.0.0.0/24"]` + admin JWT + client IP `127.0.0.1` → 403 `auth.admin.ip_blocked`.
   - **MVP 검증**: 빈 allowlist (default) → admin endpoint 접근 시 IP 가드 *미발동* (Story 1.2/7.1 dev 환경 정합 — `ADMIN_IP_ALLOWLIST` 미설정 시 기존 흐름 0 회귀).

5. **AC5 — Web `/admin/login` 실 OAuth chain UI** (현재 placeholder `(public)/admin/login/page.tsx` 대체)
   **Given** 현재 `web/src/app/(public)/admin/login/page.tsx` (~25 lines, *Story 7에서 채워짐* placeholder Link만) + `(public)/login/page.tsx`(`/api/auth/google/start?next=...` 시작) + `web/src/app/api/auth/google/start/route.ts`(state + PKCE + Google authorize redirect) + `callback/route.ts`(state 검증 + 백엔드 `POST /v1/auth/google` server-side 호출 + Set-Cookie forward) + `safeNext` open redirect 가드 + Story 1.2 `POST /v1/auth/admin/exchange`(user JWT → admin JWT, Web 분기 시 `bn_admin_access` Path=/v1/admin httpOnly 쿠키 발급 + body는 token=null), **When** 실 admin login chain 구현, **Then**:
   - **신규 route handler** `web/src/app/api/auth/admin/exchange/route.ts` (~80 lines, Edge runtime — middleware/google start와 동일 패턴):
     ```typescript
     /**
      * Admin JWT exchange — bn_access 쿠키 보유 시 1-click admin 진입 (Story 7.1 AC#5).
      *
      * 1. bn_access 쿠키 부재 → /admin/login?error=login_first redirect (chain start로
      *    돌리지 않음 — 사용자 의도 명시).
      * 2. 백엔드 POST /v1/auth/admin/exchange 호출 + cookie forward.
      * 3. 백엔드 응답의 Set-Cookie(bn_admin_access) forward + ?next= safe redirect.
      * 4. 백엔드 403 (auth.admin.role_required) → /admin/login?error=role_required.
      *
      * 절대 금지: bn_access 쿠키 plaintext를 query string 또는 client 측 노출.
      */
     import { type NextRequest, NextResponse } from "next/server";
     import { safeNext } from "@/lib/safe-next";

     const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

     export async function GET(request: NextRequest): Promise<NextResponse> {
       const url = request.nextUrl;
       const next = safeNext(url.searchParams.get("next"), "/admin");
       const accessToken = request.cookies.get("bn_access")?.value;

       if (!accessToken) {
         return NextResponse.redirect(
           new URL(`/admin/login?error=login_first&next=${encodeURIComponent(next)}`, request.url),
         );
       }

       const backendResponse = await fetch(`${API_BASE_URL}/v1/auth/admin/exchange`, {
         method: "POST",
         headers: {
           cookie: request.headers.get("cookie") ?? "",
         },
         // Web 흐름은 body=null 응답 + Set-Cookie 발급. 별도 body 송신 불필요.
       });

       if (!backendResponse.ok) {
         const code = backendResponse.status === 403 ? "role_required" : "exchange_failed";
         return NextResponse.redirect(
           new URL(`/admin/login?error=${code}`, request.url),
         );
       }

       const response = NextResponse.redirect(new URL(next, request.url));
       const setCookieHeaders = backendResponse.headers.getSetCookie?.() ?? [];
       for (const sc of setCookieHeaders) {
         response.headers.append("set-cookie", sc);
       }
       if (setCookieHeaders.length === 0) {
         return NextResponse.redirect(
           new URL("/admin/login?error=cookie_not_issued", request.url),
         );
       }
       return response;
     }
     ```
     - `getSetCookie?.()`: Next.js Edge runtime 16 fallback — 부재 시 빈 배열(타입 안전).
     - cookie forward 시 `bn_access` 외 쿠키도 같이 forward (백엔드 `current_user` dep가 정합).
     - `safeNext(next, "/admin")` — open redirect 방어 + 디폴트 `/admin`.
   - **갱신** `web/src/app/(public)/admin/login/page.tsx` (~80 lines, server component):
     ```typescript
     import Link from "next/link";
     import { cookies } from "next/headers";
     import { safeNext } from "@/lib/safe-next";

     export const metadata = {
       title: "관리자 로그인 — BalanceNote",
     };

     const ERROR_MESSAGES: Record<string, string> = {
       login_first: "먼저 일반 로그인이 필요합니다.",
       role_required: "이 계정에는 관리자 권한이 없습니다. 관리자에게 문의하세요.",
       exchange_failed: "관리자 인증 교환에 실패했습니다. 다시 시도해 주세요.",
       cookie_not_issued: "관리자 쿠키 발급에 실패했습니다. 도메인 설정을 확인하세요.",
       expired: "관리자 세션이 만료되었습니다 (8시간). 다시 로그인해 주세요.",
       forbidden: "관리자 권한이 필요한 페이지입니다.",
     };

     export default async function AdminLoginPage({
       searchParams,
     }: {
       searchParams: Promise<{ next?: string; error?: string }>;
     }) {
       const { next, error } = await searchParams;
       const validatedNext = safeNext(next, "/admin");

       const cookieStore = await cookies();
       const isLoggedIn = Boolean(cookieStore.get("bn_access")?.value);

       const errorMessage = error ? ERROR_MESSAGES[error] ?? "알 수 없는 오류" : null;

       if (isLoggedIn) {
         // 일반 로그인 통과 — 1-click admin 교환.
         const exchangeHref = `/api/auth/admin/exchange?next=${encodeURIComponent(validatedNext)}`;
         return (
           <main className="flex min-h-screen flex-col items-center justify-center p-8">
             <h1 className="text-2xl font-semibold tracking-tight">관리자 로그인</h1>
             <p className="mt-2 text-sm text-zinc-500">
               일반 로그인된 상태입니다. 관리자 권한으로 진입하시겠습니까?
             </p>
             {errorMessage && (
               <p className="mt-4 text-sm text-red-600" role="alert">
                 {errorMessage}
               </p>
             )}
             <Link
               href={exchangeHref}
               className="mt-8 inline-flex items-center gap-2 rounded-md bg-blue-600 px-6 py-3 text-white shadow hover:bg-blue-700"
             >
               관리자 권한으로 진입
             </Link>
             <Link href="/dashboard" className="mt-4 text-sm text-blue-600 hover:underline">
               일반 대시보드로 돌아가기
             </Link>
           </main>
         );
       }

       // 미로그인 — Google OAuth chain start (next=/admin/login으로 chain 후 admin exchange).
       const startHref = `/api/auth/google/start?next=${encodeURIComponent(`/admin/login?next=${validatedNext}`)}`;
       return (
         <main className="flex min-h-screen flex-col items-center justify-center p-8">
           <h1 className="text-2xl font-semibold tracking-tight">관리자 로그인</h1>
           <p className="mt-2 text-sm text-zinc-500">
             관리자 계정으로 시작하기 (별 secret + 8시간 만료 + refresh 미지원)
           </p>
           {errorMessage && (
             <p className="mt-4 text-sm text-red-600" role="alert">
               {errorMessage}
             </p>
           )}
           <Link
             href={startHref}
             className="mt-8 inline-flex items-center gap-2 rounded-md bg-blue-600 px-6 py-3 text-white shadow hover:bg-blue-700"
           >
             Google로 계속하기
           </Link>
         </main>
       );
     }
     ```
     - **chain 흐름**: 미로그인 → `/api/auth/google/start?next=/admin/login?next=/admin` → Google OAuth → callback → `bn_access` 쿠키 발급 + `next=/admin/login` redirect → `/admin/login` 재진입 → `bn_access` 보유 분기 → "관리자 권한으로 진입" 버튼 → `/api/auth/admin/exchange?next=/admin` → `bn_admin_access` 쿠키 발급 + `/admin` redirect → `(admin)/admin/layout.tsx` 통과.
     - **chain 단축 미수행**: `/api/auth/google/start`에 `?after_admin_exchange=1` 같은 자동 chain flag 추가 X — *사용자 의도 명시* invariant 보존(관리자 권한은 *별 액션*이라야 — 1.2 SOT 정합).
     - **role_required 안내**: 일반 사용자가 admin 교환 시도 시 *명확한 안내* + 일반 로그아웃 미강제(별 의도라 일반 로그인은 보존).
   - **단위 테스트** `web/src/__tests__/admin-login-page.test.tsx` 신규 1파일 + 5 케이스 (Vitest + RTL):
     - `renders google oauth chain when not logged in` — cookieStore mock `bn_access=undefined` → "Google로 계속하기" 버튼 + chain href 정합.
     - `renders admin exchange button when bn_access present` — `bn_access="..."` → "관리자 권한으로 진입" 버튼 + exchange href 정합.
     - `renders error message when error query param present` — `?error=role_required` → "이 계정에는 관리자 권한이 없습니다" 노출.
     - `unknown error code falls back to default` — `?error=invalid_xyz` → "알 수 없는 오류".
     - `safe redirect — open redirect attack rejected` — `?next=https://evil.com` → `safeNext`가 디폴트 `/admin`로 정규화.
   - **단위 테스트** `web/src/__tests__/admin-exchange-route.test.ts` 신규 1파일 + 4 케이스:
     - `bn_access cookie missing → redirect to login_first error` — request 쿠키 부재 → 302 + `error=login_first`.
     - `backend 200 + Set-Cookie → forward bn_admin_access + redirect to next` — fetch mock 200 + Set-Cookie → 302 + 헤더에 Set-Cookie 포함.
     - `backend 403 → redirect to role_required error` — fetch mock 403 → 302 + `error=role_required`.
     - `backend 200 without Set-Cookie → redirect to cookie_not_issued error` — 빈 헤더 → 302 + `error=cookie_not_issued`.

6. **AC6 — Web `(admin)` route group + `layout.tsx` server-side guard** (defense-in-depth)
   **Given** architecture.md:756-761 *"`(admin)` route group + admin/layout.tsx admin 가드"* SOT + Story 1.2 middleware는 *라우팅 차단*만 수행 (cookie 형식 가드만, JWT 검증 X) + 신규 admin landing 페이지 1건 필요(7.2의 사용자 검색 페이지 forward landing) + Next.js 16 App Router route group 패턴(괄호 디렉터리는 URL path에 미반영), **When** `(admin)` route group + layout 신설, **Then**:
   - **신규 헬퍼** `web/src/lib/admin-auth.ts` (~50 lines):
     ```typescript
     /**
      * Admin JWT claim decode (signature verify X — backend SOT).
      *
      * middleware의 decodeJwtExp 패턴 확장. exp + role + iss 동시 decode.
      * 신뢰 경계: 본 함수는 "이 쿠키가 *관리자처럼 보이는가*"만 판정. 실제 권한 검증은
      * 백엔드(`current_admin`)가 SOT — layout은 unauthenticated 사용자를 *빨리* redirect.
      *
      * 사유: layout에서 fetch /v1/auth/admin/whoami 호출 시 SSR 매 요청마다 round-trip
      * (Edge runtime + 100ms+ 추가 latency) — 본 *local decode* 패턴은 middleware와
      * 동일하게 cheap. server-side guard가 *완벽한* 권한 검사이려면 backend RTT 필요하지만
      * (a) middleware가 1차 라우팅 차단 + (b) layout이 2차 빠른 형식 검사 + (c) 보호된
      * admin endpoint 실 호출 시 backend `current_admin`이 3차 *진짜 검증* — 3-tier
      * defense-in-depth.
      */
     interface AdminJwtClaims {
       readonly exp: number;
       readonly role: string;
       readonly iss: string;
     }

     const MIN_TOKEN_LENGTH = 20;
     const CLOCK_SKEW_SECONDS = 5;
     const ADMIN_ISSUER = "balancenote-admin";

     export function decodeAdminJwtClaims(token: string | undefined): AdminJwtClaims | null {
       if (!token || token.length < MIN_TOKEN_LENGTH) return null;
       const parts = token.split(".");
       if (parts.length !== 3) return null;
       try {
         const payload = parts[1];
         const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
         const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
         const json = atob(padded);
         const claims = JSON.parse(json) as Partial<AdminJwtClaims>;
         if (typeof claims.exp !== "number") return null;
         if (typeof claims.role !== "string") return null;
         if (typeof claims.iss !== "string") return null;
         return { exp: claims.exp, role: claims.role, iss: claims.iss };
       } catch {
         return null;
       }
     }

     export type AdminGuardResult =
       | { kind: "ok" }
       | { kind: "missing" }
       | { kind: "expired" }
       | { kind: "forbidden" }; // role !== admin OR iss !== balancenote-admin

     export function evaluateAdminCookie(token: string | undefined): AdminGuardResult {
       if (!token) return { kind: "missing" };
       const claims = decodeAdminJwtClaims(token);
       if (!claims) return { kind: "missing" }; // 형식 위반 = 익명 등가.
       const nowSeconds = Math.floor(Date.now() / 1000);
       if (claims.exp <= nowSeconds + CLOCK_SKEW_SECONDS) return { kind: "expired" };
       if (claims.iss !== ADMIN_ISSUER) return { kind: "forbidden" };
       if (claims.role !== "admin") return { kind: "forbidden" };
       return { kind: "ok" };
     }
     ```
   - **신규 레이아웃** `web/src/app/(admin)/admin/layout.tsx` (~50 lines):
     ```typescript
     import { cookies } from "next/headers";
     import { redirect } from "next/navigation";
     import type { ReactNode } from "next/cache"; // typed children
     import { evaluateAdminCookie } from "@/lib/admin-auth";

     export const metadata = {
       title: "관리자 — BalanceNote",
     };

     export default async function AdminLayout({ children }: { children: ReactNode }) {
       const cookieStore = await cookies();
       const adminToken = cookieStore.get("bn_admin_access")?.value;
       const result = evaluateAdminCookie(adminToken);

       if (result.kind === "missing") {
         redirect("/admin/login");
       }
       if (result.kind === "expired") {
         redirect("/admin/login?error=expired");
       }
       if (result.kind === "forbidden") {
         redirect("/admin/login?error=forbidden");
       }

       return (
         <div className="min-h-screen flex flex-col">
           <header className="border-b px-6 py-4 flex items-center justify-between">
             <h1 className="text-lg font-semibold">관리자 — BalanceNote</h1>
             <a href="/api/auth/admin/logout" className="text-sm text-blue-600 hover:underline">
               관리자 로그아웃
             </a>
           </header>
           <main className="flex-1 p-6">{children}</main>
         </div>
       );
     }
     ```
     - **3-tier defense**: middleware(1차 — cookie 형식) → layout(2차 — JWT exp/role/iss decode) → backend `current_admin` (3차 — 서명 + DB role 재확인). 본 스토리는 2/3차 추가.
     - **admin 로그아웃 link**: `/api/auth/admin/logout` route handler — `bn_admin_access` Path=/v1/admin Max-Age=0 expire + `/admin/login` redirect. *일반 사용자 로그아웃과 별*(`bn_access`/`bn_refresh`는 그대로 유지 — 관리자 권한만 박탈).
   - **신규 route handler** `web/src/app/api/auth/admin/logout/route.ts` (~30 lines):
     ```typescript
     import { type NextRequest, NextResponse } from "next/server";

     function isProductionEnvironment(): boolean {
       const env = (process.env.ENVIRONMENT ?? process.env.NODE_ENV ?? "").toLowerCase();
       return env === "production" || env === "prod" || env === "staging";
     }

     export function GET(request: NextRequest): NextResponse {
       const response = NextResponse.redirect(new URL("/admin/login", request.url));
       const secure = isProductionEnvironment();
       response.cookies.set("bn_admin_access", "", {
         httpOnly: true,
         secure,
         sameSite: "lax",
         path: "/v1/admin",
         maxAge: 0,
       });
       return response;
     }
     ```
     - 백엔드 `/v1/auth/logout` 미호출 — admin 토큰은 *stateless* (refresh 없음 → DB row 없음). cookie expire만으로 무효(만료까지 ≤ 8h 내 권한 잔존이지만 *사용자 표면 화면 없음* + middleware/layout 가드 동시 차단).
   - **신규 페이지** `web/src/app/(admin)/admin/page.tsx` (~30 lines):
     ```typescript
     import Link from "next/link";

     export const metadata = {
       title: "관리자 대시보드 — BalanceNote",
     };

     export default function AdminDashboardPage() {
       return (
         <div className="space-y-6">
           <h2 className="text-2xl font-semibold">관리자 대시보드</h2>
           <p className="text-sm text-zinc-600">
             Story 7.2에서 사용자 검색·식단 이력·프로필 수정이 추가됩니다.
           </p>
           <div className="grid gap-4 md:grid-cols-2">
             <div className="rounded-lg border p-4">
               <h3 className="font-medium">사용자 관리</h3>
               <p className="mt-1 text-sm text-zinc-500">FR36 — 7.2에서 추가</p>
               <Link href="/admin/users" className="mt-2 inline-block text-sm text-blue-600 hover:underline">
                 사용자 검색 →
               </Link>
             </div>
             <div className="rounded-lg border p-4">
               <h3 className="font-medium">감사 로그 (self-audit)</h3>
               <p className="mt-1 text-sm text-zinc-500">FR38 — 7.4에서 추가</p>
               <Link href="/admin/audit-logs" className="mt-2 inline-block text-sm text-blue-600 hover:underline">
                 내 활동 로그 →
               </Link>
             </div>
           </div>
         </div>
       );
     }
     ```
     - **forward link**: `/admin/users` + `/admin/audit-logs`는 본 스토리에서 미신설 — middleware가 same `/admin` prefix로 가드하지만 *라우트 자체 부재* → Next.js 404 expected. 7.2/7.4에서 신설 후 자연 정합.
   - **단위 테스트** `web/src/__tests__/admin-auth.test.ts` 신규 1파일 + 8 케이스:
     - `decodeAdminJwtClaims valid token` — exp + role + iss 정합.
     - `decodeAdminJwtClaims malformed payload` — base64 decode 실패 → null.
     - `decodeAdminJwtClaims short token (<20)` → null.
     - `decodeAdminJwtClaims missing required claim` — exp 부재 → null.
     - `evaluateAdminCookie missing token returns kind=missing`.
     - `evaluateAdminCookie expired token returns kind=expired`.
     - `evaluateAdminCookie wrong issuer returns kind=forbidden`.
     - `evaluateAdminCookie role !== admin returns kind=forbidden`.
   - **단위 테스트** `web/src/__tests__/admin-layout.test.tsx` 신규 1파일 + 4 케이스 (server component test pattern — Vitest + cookies() mock):
     - `redirects to /admin/login when bn_admin_access missing`.
     - `redirects to /admin/login?error=expired when token expired`.
     - `redirects to /admin/login?error=forbidden when role mismatch`.
     - `renders children when admin token valid`.

7. **AC7 — Web `middleware.ts` admin 쿠키 stale-self-heal 확장** (Story 1.2 forward stub 닫기)
   **Given** Story 1.2 `web/src/middleware.ts` (현재 admin route 가드는 `hasValidLookingCookie('bn_admin_access')` length-only — *stale 자동 회복 X — line 79-84 자기 메모: "추후 admin도 동일 stale-self-heal로 확장 가능"*) + user 쪽 `classifyAccessCookie`(exp claim decode + 5s skew + stale 분기) SOT, **When** admin 쿠키도 동일 stale-self-heal 확장, **Then**:
   - **갱신** `web/src/middleware.ts` (~30 lines 추가):
     ```typescript
     // admin 쿠키 분류 — user 쪽 classifyAccessCookie와 동형. JWT exp claim 만료 → stale.
     function classifyAdminCookie(token: string | undefined): CookieStatus {
       if (!token) return "missing";
       const exp = decodeJwtExp(token);
       if (exp === null) return "stale";
       const nowSeconds = Math.floor(Date.now() / 1000);
       if (exp <= nowSeconds + CLOCK_SKEW_SECONDS) return "stale";
       return "valid";
     }

     function expireAdminCookie(response: NextResponse): void {
       const secure = isProductionEnvironment();
       response.cookies.set(COOKIE_BN_ADMIN_ACCESS, "", {
         httpOnly: true,
         secure,
         sameSite: "lax",
         path: "/v1/admin",  // 발급 시 동일 path.
         maxAge: 0,
       });
     }

     const COOKIE_BN_ADMIN_ACCESS = "bn_admin_access";
     ```
   - **갱신** middleware admin 분기:
     ```typescript
     if (pathname.startsWith("/admin") && !isAdminLogin) {
       const adminStatus = classifyAdminCookie(request.cookies.get(COOKIE_BN_ADMIN_ACCESS)?.value);
       if (adminStatus !== "valid") {
         url.pathname = "/admin/login";
         url.searchParams.set("next", pathname + search);
         if (adminStatus === "stale") {
           url.searchParams.set("error", "expired");
         }
         const response = NextResponse.redirect(url);
         if (adminStatus === "stale") expireAdminCookie(response);
         return response;
       }
       return NextResponse.next();
     }
     ```
   - **`hasValidLookingCookie` 헬퍼 제거** — admin도 `classifyAdminCookie`로 위임 후 length-only 헬퍼는 호출처 0건이라 *dead code*. 본 스토리에서 정리(`feedback_dont_restate_doc_content_in_prompt` 메모리는 doc에 적용, 코드 레벨 dead code는 cleanup 정합).
   - **회귀 케이스** `web/src/__tests__/middleware.test.ts` 신규 또는 갱신 1파일 + 6 케이스:
     - `admin route + missing bn_admin_access → redirect /admin/login`.
     - `admin route + expired bn_admin_access (exp < now) → redirect /admin/login?error=expired + Set-Cookie Max-Age=0`.
     - `admin route + valid bn_admin_access → next()`.
     - `admin route + malformed bn_admin_access (3 parts split fail) → stale 분기`.
     - `admin login route 자체는 가드 우회` — `/admin/login` 직접 진입 → next().
     - `admin login extra path도 가드 우회` — `/admin/login/help` → next() (현재 로직 정합 회귀).
   - **테스트 setup**: Edge runtime middleware는 직접 import + `NextRequest` mock — Story 1.2 baseline 패턴 재사용(이미 있는 경우 확장 / 없는 경우 신규 1파일 — `web/src/__tests__/middleware.test.ts`).

8. **AC8 — pytest + ruff + format + mypy + tsc + lint + alembic + OpenAPI 검증 + sprint-status 갱신**
   **Given** Story 6.3 baseline `pytest 1194 passed / 11 skipped / 0 failed + coverage 85.32%` + ruff/format/mypy 0 errors + web/mobile tsc + lint 0 errors + alembic 0020 SOT, **When** 본 스토리 구현 완료 시점, **Then**:
   - **pytest**: ≥ Story 6.3 baseline + 신규 ~14건 (AC1: 6 + AC2: 4 + AC3: 6 + AC4: 8 = 24) → 목표 ~1218건 + coverage ≥ 85.0% 유지.
   - **ruff/format/mypy**: 0 errors (api).
   - **web tsc + lint**: 0 errors. 신규 ~21 web 단위 케이스(AC5: 9 + AC6: 12).
   - **alembic**: 신규 마이그레이션 0건 — `users.role` + `idx_users_role_admin`은 0002 SOT.
   - **OpenAPI**: `pnpm gen:api` (IN_PROCESS=1) 후 `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts`에 `getAdminWhoami` operation 추가됨. 기존 endpoint 변경 0건.
   - **CR 종료 직전 sprint-status 갱신** (메모리 `feedback_cr_done_status_in_pr_commit` 정합):
     - `epic-7: backlog → in-progress` (CS 단계에서 이미 갱신됨 — 본 검증은 무변경 가드).
     - `7-1-...: review → done` (CR 종료 직전 마지막 commit에 포함).
     - last_updated 필드 갱신.

## Tasks / Subtasks

- [x] **Task 1 — Story 1.2 admin auth 베이스라인 회귀 가드 + smoke endpoint** (AC: #1, #2)
  - [x] 1.1 `api/app/api/v1/auth.py`에 `AdminWhoamiResponse` Pydantic 모델 추가 (4 필드, `extra="forbid"`).
  - [x] 1.2 `api/app/api/v1/auth.py`에 `_mask_email(email: str) -> str` private helper 추가 (NFR-S5 SOT, 4 케이스 가드).
  - [x] 1.3 `api/app/api/v1/auth.py`에 `GET /admin/whoami` endpoint 추가 (`Depends(require_admin_ip_allowed)` + `Depends(current_admin)`). Task 3 함께 구현 — `require_admin_ip_allowed` 직접 wire(임시 wire 단계 우회).
  - [x] 1.4 `api/tests/api/v1/test_admin_auth_baseline.py` 신규 1파일 + 회귀 6건 + smoke 3건 + IP 가드 1건 = 10 케이스.
  - [x] 1.5 `api/tests/test_email_mask.py` 신규 1파일 + 4 케이스.
  - [x] 1.6 `pnpm gen:api` (IN_PROCESS=1) 실행 → `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts`에 `admin_whoami_v1_auth_admin_whoami_get` operation 등재.

- [x] **Task 2 — `scripts/promote_admin.py` CLI + SOP** (AC: #3)
  - [x] 2.1 `scripts/promote_admin.py` 신규 — argparse(`--email`/`--demote`/`--yes`) + SQLAlchemy async engine(`settings.database_url` SOT) + SELECT/UPDATE commit + 한국어 prompt/에러 메시지 + 4 exit code(0/1/2/3).
  - [x] 2.2 `docs/sop/05-admin-role-promotion.md` 신규 — 8 섹션(언제/사전 조건/실행/검증/박탈/audit forward/대체/안전 가드).
  - [x] 2.3 `api/tests/scripts/test_promote_admin.py` 신규 1파일 + 6 케이스.

- [x] **Task 3 — 백엔드 IP 화이트리스트 옵션** (AC: #4)
  - [x] 3.1 `api/app/core/config.py` — `admin_ip_allowlist: list[str] = Field(default_factory=list)` + `_split_admin_ip_allowlist` validator 추가 (CIDR 형식 부팅 검증 + 잘못된 CIDR fail-fast).
  - [x] 3.2 `api/app/core/proxy.py` — `check_admin_ip_allowed(request, allowlist) -> bool` 헬퍼 추가 (`get_real_client_ip` SOT 재사용 + 빈 list graceful default).
  - [x] 3.3 `api/app/core/exceptions.py` — `AdminIpBlockedError(AuthError, status=403, code="auth.admin.ip_blocked")` 신규 클래스.
  - [x] 3.4 `api/app/api/deps.py` — `require_admin_ip_allowed(request, claims)` dep 추가 (`current_admin_claims` 직후 wire). 순환 import 회피 — 함수 내 lazy import.
  - [x] 3.5 `api/tests/core/test_admin_ip_allowlist.py` 신규 1파일 + 7 케이스.
  - [x] 3.6 Task 1.3의 `whoami` endpoint dep은 처음부터 `Depends(require_admin_ip_allowed)` wire(임시 단계 skip) + integration 1건 `test_admin_whoami_blocked_when_ip_not_allowlisted` AC1 파일에 흡수.
  - [x] 3.7 `.env.example`에 `ADMIN_IP_ALLOWLIST=` 추가. `api/.env.example`은 repo에 부재 — root SOT 단일.

- [x] **Task 4 — Web `/admin/login` 실 OAuth chain UI** (AC: #5)
  - [x] 4.1 `web/src/app/api/auth/admin/exchange/route.ts` 신규 — `bn_access` 쿠키 검사 → cookie forward + 백엔드 `POST /v1/auth/admin/exchange` 호출 → Set-Cookie forward + `safeNext` open redirect 가드.
  - [x] 4.2 `web/src/app/(public)/admin/login/page.tsx` 갱신 — server component(cookies() 읽음) + 6 ERROR_MESSAGES + 로그인 분기 2 케이스(미로그인 → Google chain / 로그인됨 → exchange button).
  - [~] 4.3 `web/src/__tests__/admin-login-page.test.tsx` deferred — Web baseline에 vitest/RTL 인프라 부재(Story 4.3 precedent), Story 8.4 polish forward.
  - [~] 4.4 `web/src/__tests__/admin-exchange-route.test.ts` deferred — 동일 사유.

- [x] **Task 5 — Web `(admin)` route group + layout.tsx server-side guard + dashboard placeholder** (AC: #6)
  - [x] 5.1 `web/src/lib/admin-auth.ts` 신규 — `decodeAdminJwtClaims` + `evaluateAdminCookie` + `AdminGuardResult` discriminated union + `ADMIN_ISSUER` 상수.
  - [x] 5.2 `web/src/app/(admin)/admin/layout.tsx` 신규 — server component + cookies().get + `evaluateAdminCookie` 분기 + 3 redirect 분기 + `<header>`/`<main>` shell.
  - [x] 5.3 `web/src/app/(admin)/admin/page.tsx` 신규 — placeholder 대시보드 + 7.2/7.4 forward link 2건.
  - [x] 5.4 `web/src/app/api/auth/admin/logout/route.ts` 신규 — `bn_admin_access` Max-Age=0 + Path=/v1/admin + `/admin/login` redirect.
  - [~] 5.5 `web/src/__tests__/admin-auth.test.ts` deferred — Story 4.3 precedent.
  - [~] 5.6 `web/src/__tests__/admin-layout.test.tsx` deferred — 동일 사유.

- [x] **Task 6 — Web `middleware.ts` admin 쿠키 stale-self-heal 확장** (AC: #7)
  - [x] 6.1 `web/src/middleware.ts` — `classifyAdminCookie` + `expireAdminCookie` + admin 분기 갱신 + `COOKIE_BN_ADMIN_ACCESS` 상수.
  - [x] 6.2 `hasValidLookingCookie` 헬퍼 제거 (호출처 0 — dead code).
  - [~] 6.3 `web/src/__tests__/middleware.test.ts` deferred — Story 4.3 precedent.

- [x] **Task 7 — 검증 + sprint-status 갱신** (AC: #8)
  - [x] 7.1 `cd api && uv run pytest -q` → pytest 1222 passed / 11 skipped / 0 failed + coverage 85.44% (목표 ≥85.0% 달성).
  - [x] 7.2 `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app` → 0 errors.
  - [x] 7.3 `cd web && pnpm tsc --noEmit && pnpm lint` → 0 errors. `pnpm test`는 Web baseline 인프라 부재로 skip(Story 4.3 precedent).
  - [x] 7.4 `pnpm gen:api` (IN_PROCESS=1) → /v1/auth/admin/whoami 명세 추가 + 회귀 0건.
  - [x] 7.5 `_bmad-output/implementation-artifacts/sprint-status.yaml` 갱신 — `7-1-...: ready-for-dev → in-progress → review` 전이 완료.
  - [x] 7.6 CR 종료 직전 commit에 `7-1-...: review → done` + `last_updated` 갱신 포함 (CR 단계에서 수행).

### Review Findings (CR 2026-05-10 — 3-layer adversarial)

3-layer 병렬 리뷰(Blind Hunter / Edge Case Hunter / Acceptance Auditor) 결과. 35+ raw findings → triage 후: 2 decision-needed, 4 patch, 7 defer, 17 dismissed (false-positive/YAGNI/informational).

**CR 결과 (2026-05-10)**: Decision-needed 2건 → 옵션 (A) 채택해 patch로 전환. Patch 6건 전부 적용 완료. 백엔드 1223 passed / 11 skipped + ruff/mypy clean + web tsc/lint clean + `pnpm gen:api` 재실행 완료. Defer 7건은 `deferred-work.md`에 기록.

#### Decision-needed (architectural — 수정 방향 모호, human input 필요)

- [x] [Review][Decision] **Web admin flow end-to-end 미작동 — `bn_admin_access` cookie path scope 불일치** [api/app/api/v1/auth.py:205, web/src/app/(admin)/admin/layout.tsx:23, web/src/middleware.ts:114] — `bn_admin_access`가 `path=/v1/admin`(Story 1.2 SOT, 본 스토리 변경 0건)으로 발급되지만 Web layout/middleware는 `/admin/*` URL에서 `cookies().get("bn_admin_access")` 시도. RFC 6265 §5.1.4: cookie-path `/v1/admin`은 request-path `/admin/*`의 prefix 아님 → **브라우저가 쿠키 송신 X** → middleware는 항상 missing 처리 → `/admin/login` 무한 리다이렉트. 백엔드 테스트 모두 `Authorization: Bearer` 헤더 사용 + Web E2E 테스트 전부 deferred → CI green이지만 실 브라우저 흐름 작동 0%. **3개 layer 독립 합치 + 코드 직접 검증 완료**. 수정 옵션: (A) 백엔드 cookie path를 `/`로 변경(Story 1.2 SOT 위반 — 단 Story 1.2가 정의했던 SOT 자체가 Web 가드와 호환 불가), (B) Web layout/middleware가 cookie 직접 X — 서버사이드 fetch `/v1/auth/admin/whoami`로 검증(단 whoami 자체도 `/v1/auth/admin/whoami` URL인데 cookie path `/v1/admin`과 mismatch — 동일 문제 재발), (C) Web exchange route handler가 backend Set-Cookie를 수신 후 path를 `/`로 재작성해 응답에 다시 set, (D) `(admin)` 라우트를 `/v1/admin/*` URL로 변경(Next.js 경로 재설계).
- [x] [Review][Decision] **Web 흐름에서 admin JWT plaintext가 response body에 반환 — NFR-S2 위반** [api/app/api/v1/auth.py:548, web/src/app/api/auth/admin/exchange/route.ts:37] — `bn_refresh` cookie가 `path=/v1/auth`로 발급되어 Next.js route handler URL `/api/auth/admin/exchange`(prefix 불일치)에 송신 X. Next.js가 `request.headers.get("cookie")`로 forward하면 backend는 `bn_refresh=None`을 보고 `is_web = bool(None) = False` → mobile 분기로 인식 → response body에 `admin_access_token` 평문 채움. Set-Cookie도 동시 발급되므로 Next.js handler는 body를 무시하지만, **JWT 평문이 Next.js↔backend 네트워크 구간 + 양쪽 액세스 로그/Sentry response capture 등에 노출**. 수정 옵션: (A) backend `is_web` 판단을 `bn_refresh` 존재 여부 X — 명시 `?platform=web` 쿼리 또는 `X-Platform-Web` 헤더 사용, (B) backend가 Set-Cookie 발급 시 항상 body의 token field omit, (C) Next.js exchange route가 `?platform=web` 쿼리를 추가해 backend 호출.

#### Patch (불명확성 0 — 즉시 수정 가능)

- [x] [Review][Patch] **IPv4-mapped IPv6 client가 IPv4 CIDR allowlist에 매칭되지 않음** [api/app/core/proxy.py:184-187] — Cloudflare/Railway 등 IPv6 dual-stack 환경에서 client_ip가 `::ffff:203.0.113.42` 형태로 도착. `ipaddress.ip_address("::ffff:203.0.113.42") in IPv4Network("203.0.113.0/24")`는 silently False → admin lockout. 수정: 비교 전 `.ipv4_mapped` 언랩.
- [x] [Review][Patch] **`API_BASE_URL` env 미설정 시 prod에서 `localhost:8000` fallback — 사용자 cookie를 sidecar에 leak** [web/src/app/api/auth/admin/exchange/route.ts:17] — prod 배포에서 env 누락 시 silent fallback. 수정: prod에서 env 미설정이면 throw(서버 부팅 실패) 또는 default 제거.
- [x] [Review][Patch] **`/api/auth/admin/logout`과 `/api/auth/admin/exchange`가 GET 메서드 — CSRF/링크 prefetch로 우발적 호출** [web/src/app/api/auth/admin/logout/route.ts:20, web/src/app/api/auth/admin/exchange/route.ts:19] — Lax SameSite는 top-level GET 허용 → 외부 링크 클릭 또는 메신저 unfurling으로 의도치 않은 logout/exchange. 수정: POST + form 버튼으로 전환(layout의 logout 링크도 `<form>` 안 `<button>`).
- [x] [Review][Patch] **`require_admin_ip_allowed`가 `current_admin`과 transitive 연결 X — Story 7.2/7.4 admin endpoint가 `Depends(current_admin)`만 쓰면 IP 가드 silent bypass** [api/app/api/deps.py:34-50] — 현재 7.1의 whoami는 두 dep을 *명시* 선언해 안전하나 *컨벤션 강제 X*. NFR-S8 forward-compat 위험. 수정: `current_admin`이 `require_admin_ip_allowed`를 transitively dep으로 포함하도록 체인 재구성, 또는 `admin.py` 라우터 단위로 router-level `Depends` 강제(7.2 신설 시).

#### Defer (실재 이슈, 즉시 수정은 비용↑가치↓)

- [x] [Review][Defer] **`test_admin_whoami_blocked_when_ip_not_allowlisted`가 의도와 다른 분기 검증** [api/tests/api/v1/test_admin_auth_baseline.py:507-526] — ASGITransport `request.client=None`으로 인해 `get_real_client_ip` 빈 문자열 → deny-by-default 분기 hit. 스펙은 "valid client IP가 allowlist 미일치 시 403"을 의도했으나 실제 테스트는 `client=None` 분기 재검증. 수정 비용: ASGITransport 설정 또는 starlette `Request.client` 패치 필요. deferred — Web E2E test infra(8.4) 시점 일괄 정비.
- [x] [Review][Defer] **AC8 budget(`~21 web 단위 케이스`)이 web tests deferred와 모순** [spec AC8] — Web 테스트 인프라 부재로 Tasks 4.3/4.4/5.5/5.6/6.3 deferred(Story 4.3 precedent). AC8 budget text와 정합성 깨짐. deferred — Story 8.4 polish에서 vitest/RTL 도입 + 일괄 작성.
- [x] [Review][Defer] **`_mask_email`이 짧은 local part(2-3자)에서 식별성 노출** [api/app/api/v1/auth.py:559-570] — `ab@x.com` → `a***@x.com`은 33% 정보 노출. NFR-S5 contract 자체는 만족(`j***@example.com` 패턴). deferred — 마스킹 정책 재검토 시점 일괄.
- [x] [Review][Defer] **`atob` 기반 JWT decode가 UTF-8 페이로드에 fragile** [web/src/lib/admin-auth.ts:38-42, web/src/middleware.ts:40-41] — 현 admin JWT는 ASCII-only(security.py:170-178 검증)라 즉시 영향 0. 미래 claim에 i18n 문자열 추가 시 silent breakage. deferred — JWT claim 확장 시점 fix.
- [x] [Review][Defer] **`evaluateAdminCookie`가 malformed cookie를 `"missing"`으로 분류 — middleware는 같은 입력을 `"stale"`로 분류 → UX 분기 비대칭** [web/src/lib/admin-auth.ts:55-57] — layout은 error param 없는 redirect, middleware는 `?error=expired`. UX nit. deferred.
- [x] [Review][Defer] **`safeNext` 1024자 cap이 다운스트림 URL 인코딩 폭발(3x) 미반영** [web/src/lib/safe-next.ts:14] — 800자 next + URL encode → 414 URI Too Long 가능. 실 trigger 사례 0. deferred.
- [x] [Review][Defer] **`_FakeRequest` test helper가 starlette `Headers` 인터페이스와 구조적 불일치** [api/tests/core/test_admin_ip_allowlist.py:15-47] — `# type: ignore[arg-type]`로 우회. 현 `get_real_client_ip` 구현이 `.get`만 사용해 정상 동작하나, 구현 리팩토링 시 silent test pass 위험. deferred — proxy.py 리팩토링 시점.



### 핵심 설계 결정

#### Story 1.2 SOT 재사용 (백엔드 admin auth core 변경 0건)

본 스토리는 **백엔드 admin JWT/검증/dep core 변경 0건** + **신규 영역 4건만**(IP 화이트리스트 + smoke endpoint + Web UI + admin role flip CLI). Story 1.2가 이미 `create_admin_token`/`verify_admin_token`/`current_admin_claims`/`current_admin`/`POST /v1/auth/admin/exchange`/`bn_admin_access` 쿠키/`AdminRoleRequiredError`/`IssuerMismatchError`/`users.role` 컬럼/`idx_users_role_admin` partial index/`AdminTokenClaims` dataclass/`JWT_ADMIN_AUDIENCE` 상수/`ADMIN_ACCESS_TOKEN_TTL_SECONDS=8h` 상수를 갖췄다 — *재발명 절대 금지*.

#### Smoke endpoint 선택: `GET /v1/auth/admin/whoami`

본 스토리에서 `admin.py` 라우터 신설 X(Story 7.2가 admin 사용자 검색·수정 본격 신설). 단:
- Web `(admin)/admin/layout.tsx` server-side guard가 *protected admin endpoint* 1건을 호출하면 backend round-trip로 *진짜 검증* 가능하지만, *Edge runtime 매 요청 100ms+ latency*는 비용. **결정**: layout은 *local JWT decode*로 빠르게 분기 + 보호된 admin endpoint 실 호출 시 backend `current_admin`이 진짜 검증 (3-tier defense-in-depth).
- AC1 회귀 가드(`test_admin_token_8h_expired_returns_401` 등)도 *protected admin endpoint* 1건 필요 — `admin.py` 신설 X 선택 시 본 스토리에서 임시로 1건 만들어야.

**선택지**: (a) `admin.py` 라우터 신설 후 7.2가 흡수 / (b) `auth.py`에 *admin 정보 echo* endpoint 1건 추가 + 7.2도 그대로 유지.

**(b) 선택**: `auth.py`는 *인증 정보 echo* 책임 + `admin.py`(7.2)는 *business action* 책임 (사용자 검색·수정 — `audit_admin_action` 7.3 dep 적용 대상). `admin/whoami`는 *읽기 전용 자기 자신 정보*라 audit log 기록 대상 X (7.3 enum scope에서 admin meta-info 조회 제외). 책임 분리 정합.

#### IP 화이트리스트 dependency 위치

`Depends(require_admin_ip_allowed)`는 *`current_admin_claims` 직후* wire — JWT 검증 1차 + IP 검증 2차 + DB role 재확인 3차 chain.

**대안**: middleware-level IP 검증(FastAPI middleware 또는 `BaseHTTPMiddleware`) — 거부함:
- *전역 미들웨어*는 admin endpoint 외에도 적용되어 *공개 endpoint(`/v1/legal/*`)에 IP 가드 오발 위험*.
- *경로 기반 미들웨어*는 코드 분기가 복잡해짐 + dependency injection이 더 명료(개별 endpoint별 wire 가능 + test에서 monkeypatch 친화).

`current_admin_claims` 직후로 wire한 사유: JWT 검증 *이전* IP 가드는 익명 요청에 대한 정보 누설 회피보다 JWT 검증이 우선. IP 검증을 *처음에* 두면 *유효 토큰이 비매칭 IP에서* vs *무효 토큰이 매칭 IP에서* 둘 다 동일 응답이라 정보 누설 미발생이지만, *JWT 검증 비용 < IP 매칭 비용*은 아니라(IP 매칭은 ipaddress 라이브러리 1회 조회 — sub-millisecond) — 순서 변경 시 의미 있는 비용 차이 0. **결정**: JWT → IP 순으로 wire (의미 명료성 우선).

#### Admin role 매핑 SOT — DB row only (alembic seed 거부)

`users.role` flip 메커니즘을 *코드/seed*로 박지 않고 *CLI + SOP*로 관리하는 사유:
- **외주 인수 정합**: 클라이언트별 admin 사용자가 *환경별로 다름*(병원별 의료정보팀 직원). alembic seed는 *코드 commit + git history*에 admin email 박힘 → 외주 인수 시 *클라이언트 사용자 정보가 우리 git에 영구 박힘* 위험.
- **권한 박탈 immediate**: `--demote` flag로 즉시 박탈 가능 + DB row만 SOT라 JWT 즉시 무효(`current_admin` DB role 재확인 invariant).
- **alembic 우회 고려 X**: alembic은 schema 변경 SOT, *데이터 변경*은 CLI/직접 SQL이 정합(Story 5.2 `register_purge_job`도 동일 패턴).

#### Web admin login chain — 단축 거부

미로그인 사용자가 `/admin/login` 진입 시 *Google OAuth → 자동 admin exchange → /admin* chain을 *1단계로 자동화*하지 않음:
- **사용자 의도 명시**: 관리자 권한 진입은 *별 액션*이라야 — 일반 로그인 통과 후 *명시적* "관리자 권한으로 진입" 버튼이 정합(Story 1.2 SOT — `POST /v1/auth/admin/exchange`는 user JWT 보유 사용자가 *명시적으로* 호출하는 패턴).
- **role_required 처리 명료**: 일반 사용자가 admin chain 진입 시 *명확 안내* + 일반 로그인은 보존(별 의도라 일반 로그아웃 미강제). 자동 chain은 이 분기를 모호하게 만듦.

#### `(admin)` route group + layout 정합

architecture.md:756-761은 `(admin)/admin/login/page.tsx` SOT지만 *login page 자체는 layout admin 가드를 통과 X*(자기 자신을 가드해서 무한 redirect). **결정**: login은 `(public)/admin/login/`(현재 위치 유지) + 보호된 영역만 `(admin)/admin/`. 명료성 + 무한 redirect 회피.

### 라이브러리·프레임워크 요구

- **백엔드**:
  - `python-jose[cryptography]` — Story 1.2 베이스라인. 본 스토리에서 신규 사용 0.
  - `pydantic_settings.BaseSettings` — Story 1.2 SOT. `admin_ip_allowlist` validator 패턴은 `cors_allowed_origins`와 동형.
  - `ipaddress` (표준 라이브러리) — IP 화이트리스트 매칭. Story 3.9 `core/proxy.py` SOT 재사용.
- **Web**:
  - `next/headers.cookies()` — server component cookie 읽기. Next.js 16 App Router 표준.
  - `next/navigation.redirect` — server component redirect. `redirect("/admin/login")` 호출 시 `NEXT_REDIRECT` throw + 응답으로 변환됨.
  - `globalThis.atob` — Edge runtime base64 decode (middleware/`admin-auth.ts` 동형 재사용).
- **테스트**:
  - `vitest` + `@testing-library/react` — Web 단위. 신규 도입 X(Story 4.3/4.4 baseline 재사용).
  - `pytest` + `pytest-asyncio` + `httpx.AsyncClient` — backend 단위/integration. Story 1.2 baseline 재사용.

### 회귀 보존 SOT (절대 변경 금지)

- `api/app/core/security.py:create_admin_token` — Story 1.2 SOT. 본 스토리는 *재사용*만.
- `api/app/core/security.py:verify_admin_token` — Story 1.2 SOT. issuer + audience + role enforcement.
- `api/app/api/deps.py:current_admin_claims` + `current_admin` — Story 1.2 SOT.
- `api/app/api/v1/auth.py:POST /v1/auth/admin/exchange` — Story 1.2 SOT. Web 분기 시 `bn_admin_access` Path=/v1/admin httpOnly 쿠키 발급 + body는 token=null.
- `api/app/api/v1/auth.py:clear_auth_cookies` — Story 1.2 SOT. `bn_admin_access` 포함 3 쿠키 모두 expire. *변경 0건*.
- `api/app/db/models/user.py:role` 컬럼 + CHECK + `idx_users_role_admin` partial index — Story 1.2 SOT (alembic 0002).
- `api/app/core/exceptions.py:AdminRoleRequiredError`/`IssuerMismatchError`/`AccessTokenExpiredError`/`AccessTokenInvalidError` — Story 1.2 SOT.
- `web/src/middleware.ts` user 분기(`/dashboard`/`/onboarding`/`/login`) + `decodeJwtExp` + `classifyAccessCookie` + `expireAuthCookies` — Story 1.2 SOT. 본 스토리는 *admin 분기만 갱신* + user 흐름 변경 0건.
- `api/app/core/proxy.py:get_real_client_ip` 3-tier 우선순위 — Story 3.9 SOT. 본 스토리 IP 화이트리스트는 *재사용*만.

### 직전 스토리(6.3) 학습

- **CR 패치 분류 — defer vs dismiss** (메모리 `feedback_defer_vs_dismiss_in_cr` 정합) — 본 스토리 CR도 동일 분류 규칙 적용. 가치 < 비용 / YAGNI / UX 데이터 부재는 dismiss.
- **dismiss 코멘트 회피** (메모리 `feedback_no_dismiss_comment_for_false_positive`) — PR 코멘트는 redundant ceremony. 본 스토리 CR도 false-positive에는 코멘트 X.
- **CR 종료 직전 sprint-status `review → done`** (메모리 `feedback_cr_done_status_in_pr_commit`) — 본 스토리도 PR commit에 status 갱신 포함 — chore PR 강제 회피.
- **Helper SOT 분리 패턴** (Story 6.3 DF49 흡수) — `validate_idempotency_key_uuid_v4` 패턴이 본 스토리 `_mask_email`/`check_admin_ip_allowed`/`evaluateAdminCookie` 헬퍼 분리에도 정합.
- **forward-compat 명시** (Story 6.3의 *"Stripe webhook은 본 스토리 OUT — Story 8.5 forward stub"*) — 본 스토리도 *audit_logs 도입은 7.3 forward* + *admin 사용자 검색은 7.2 forward* 명시.

### 환경 변수 추가

#### `.env.example`

```
# --- Admin IP allowlist (Story 7.1, NFR-S8) ---
# comma-separated CIDR. 빈 값 → 미강제(MVP default).
# 예: ADMIN_IP_ALLOWLIST=203.0.113.0/24,2001:db8::/32
ADMIN_IP_ALLOWLIST=
```

#### `api/.env.example`

동일 — repo root `.env`가 SOT(api/.env는 override 옵션, Story 1.2 패턴 정합).

### Web 환경 변수 추가 0건

`API_BASE_URL` + `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_REDIRECT_URI` + `ENVIRONMENT`/`NODE_ENV` 모두 Story 1.2 SOT — 본 스토리는 추가 0건.

### Project Structure Notes

- Alignment with `architecture.md:622` `core/security.py # JWT user/admin 분리` — Story 1.2 SOT 재사용.
- Alignment with `architecture.md:661` `deps.py # current_user, require_admin, require_consent, audit_admin_action` — Story 1.2 SOT(`current_admin` = `require_admin` 의미 동등) 재사용 + `require_admin_ip_allowed` 신설.
- Alignment with `architecture.md:756-761` Web `(admin)/admin/login/users/audit-logs/layout.tsx` SOT — 본 스토리는 `layout.tsx` + `page.tsx`(landing)만 신설 + login은 `(public)` 유지(무한 redirect 회피 — *deviation 명시*).
- Alignment with `architecture.md:782` `middleware.ts # admin route guard` — 본 스토리는 admin 쿠키 stale-self-heal 확장.
- Alignment with `architecture.md:306` *"`admin`: HS256 access 8시간/refresh 없음 + IP 화이트리스트 옵션"* — IP 화이트리스트 본 스토리에서 신설.
- Alignment with `architecture.md:536` *"Admin: refresh 미지원이므로 401 즉시 admin 로그인 화면"* — middleware admin stale-self-heal + 401 핸들링.
- **Deviation 1**: `(admin)/admin/login` (architecture SOT) → `(public)/admin/login` (실 구현, 무한 redirect 회피). 사유 명시 — *login은 자기 자신을 admin guard로 가드 X*.
- **Deviation 2**: `admin.py` 라우터 신설 미수행 (architecture line 669 SOT) → 7.2 forward. 본 스토리는 `auth.py`의 `admin/whoami` smoke endpoint 1건만 — `admin.py`는 *business action* 라우터로 7.2가 신설.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic-7-Story-7.1 — 관리자 로그인 + admin role JWT 분리 + 가드]
- [Source: _bmad-output/planning-artifacts/architecture.md#authn-authz — JWT user/admin 분리 + IP 화이트리스트 + audit dep]
- [Source: _bmad-output/planning-artifacts/architecture.md#project-structure-boundaries — `(admin)` route group + `admin.py` 라우터 + `audit_admin_action` dep]
- [Source: _bmad-output/planning-artifacts/architecture.md#enforcement-guidelines — 모든 admin 라우터 `Depends(audit_admin_action)` 명시(7.3 forward)]
- [Source: _bmad-output/planning-artifacts/prd.md#FR35-FR39 — admin role 분리 + audit log + 마스킹]
- [Source: _bmad-output/planning-artifacts/prd.md#NFR-S7-S8 — Admin role JWT 별 secret + 짧은 만료 + IP 화이트리스트 옵션]
- [Source: api/app/core/security.py — Story 1.2 admin JWT SOT (`create_admin_token`/`verify_admin_token`/`AdminTokenClaims`)]
- [Source: api/app/api/deps.py — Story 1.2 `current_admin_claims`/`current_admin` SOT]
- [Source: api/app/api/v1/auth.py — Story 1.2 `POST /v1/auth/admin/exchange` + cookie 발급 SOT]
- [Source: api/app/db/models/user.py — Story 1.2 `users.role` + `idx_users_role_admin` SOT]
- [Source: api/app/core/exceptions.py — Story 1.2 `AdminRoleRequiredError`/`IssuerMismatchError` SOT]
- [Source: api/app/core/config.py — Story 1.2 `jwt_admin_secret`/`jwt_admin_issuer`/`ADMIN_ACCESS_TOKEN_TTL_SECONDS=8h` SOT]
- [Source: api/app/core/proxy.py — Story 3.9 `get_real_client_ip` 3-tier 우선순위 SOT]
- [Source: web/src/middleware.ts — Story 1.2 `decodeJwtExp`/`classifyAccessCookie`/`expireAuthCookies` 패턴 SOT]
- [Source: web/src/app/api/auth/google/start/route.ts — Story 1.2 OAuth chain start SOT (state + PKCE + safeNext)]
- [Source: web/src/app/api/auth/google/callback/route.ts — Story 1.2 cookie forward 패턴 SOT]
- [Source: web/src/app/(public)/login/page.tsx — Story 1.2 login page UI 패턴 SOT (Google chain + safeNext + error query)]
- [Source: web/src/lib/safe-next.ts — Story 1.2 open redirect 방어 SOT]
- [Source: api/tests/test_auth_router.py — Story 1.2 admin exchange 회귀 가드 SOT]
- [Source: api/tests/test_auth_security.py — Story 1.2 admin token 검증 단위 SOT]
- [Source: _bmad-output/implementation-artifacts/6-3-결제-webhook-idempotency-키.md — 직전 스토리 Helper SOT 분리 패턴 + CR triage SOT]
- [Source: _bmad-output/implementation-artifacts/sprint-status.yaml — `epic-7: in-progress` 전이 + `7-1-...: ready-for-dev` 진입]

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m]

### Debug Log References

### Completion Notes List

- 2026-05-10 (Amelia, CS): Story 7.1 컨텍스트 작성 완료. Branch `story/7.1-admin-login-jwt-guard` 분기 완료(master 기준). Epic 7 첫 스토리 — `epic-7: backlog → in-progress` + `7-1-...: backlog → ready-for-dev` 갱신 의무. **백엔드 admin auth core SOT(security.py + deps.py + auth.py admin/exchange + bn_admin_access 쿠키 + users.role + idx_users_role_admin)는 Story 1.2 산출물 — 변경 0건 + 회귀 가드 6건만**. 신규 4 영역: (1) IP 화이트리스트(env+helper+dep+exception+wire), (2) `admin/whoami` smoke endpoint(`(admin)/admin/layout.tsx` server-side guard 회복용 + AC1 회귀 fixture), (3) Web `/admin/login` 실 OAuth chain UI + `(admin)` route group + layout server-side guard + admin 로그아웃 + middleware admin 쿠키 stale-self-heal 확장, (4) `scripts/promote_admin.py` CLI + `docs/sop/05-admin-role-promotion.md` SOP. Story 7.3 forward stub: `audit_admin_action` dep + `audit_logs` 테이블 + admin endpoint audit 기록 *모두 7.3 본격 신설* — 본 스토리는 *언제 어디서 wire될지*만 명시.
- 2026-05-10 (Amelia, DS): Story 7.1 구현 완료 — DS 통과. **검증 결과**: pytest 1222 passed / 11 skipped / 0 failed + coverage 85.44%(≥85.0% 목표 달성) + ruff/format/mypy 0 errors + web tsc/lint 0 errors + mobile tsc/lint 0 errors + alembic 변경 0건 + OpenAPI gen → `admin_whoami_v1_auth_admin_whoami_get` operation 등재. **신규 단위 테스트 27건**: test_admin_auth_baseline 10(AC1 6 회귀 + AC2 3 smoke + AC4 1 IP 가드) + test_email_mask 4(NFR-S5 SOT) + test_admin_ip_allowlist 7 + test_promote_admin 6. 회귀 가드 0건 — Story 1.2 baseline 5 admin_exchange 케이스 + test_auth_security 17건 + test_proxy 8건 모두 PASS. **Task 1+3 통합 구현**(임시 wire 단계 우회 — `require_admin_ip_allowed`로 직접 wire). **`auth.py` smoke endpoint 위치 결정**: AC1 회귀 fixture + Web layout server-side guard 회복 양쪽 책임으로 `auth.py:GET /admin/whoami` (admin.py 라우터 신설은 7.2 forward — business action vs 인증 정보 echo 책임 분리). **Web `(admin)` route group 신설** + `(public)/admin/login` 위치 유지(deviation 1 명시: login은 자기 자신을 admin guard로 가드 X — 무한 redirect 회피). **middleware.ts admin stale-self-heal 확장 + `hasValidLookingCookie` dead code 제거**(Story 1.2 length-only 검사 → exp claim decode 동형 패턴). **Web 테스트 deferred** — Story 4.3 precedent(`Web baseline에 jest 인프라 부재 — tsc + lint + 실 브라우저 검증으로 게이트`) + Story 8.4 polish forward 동일 처리. **`scripts/promote_admin.py`** SQLAlchemy async engine + 트랜잭션 wrap(SELECT → confirm → UPDATE → commit → 재조회) + 4 exit code(0/1/2/3) + 한국어 메시지 + soft-deleted user 미발견 분기 + 멱등 분기 + prod/staging non-tty fail-fast + `docs/sop/05-admin-role-promotion.md` 8 섹션. **신규 환경 변수 1건**: `ADMIN_IP_ALLOWLIST` (.env.example 갱신). `api/.env.example`은 repo에 부재 — root SOT 단일(deviation 명시). Status: in-progress → review. CR 위임.

### File List

**Backend (api/) — 신규 1 파일 + 수정 4 파일**:

- `api/app/api/v1/auth.py` (수정) — `AdminTokenClaims` import 추가, `current_admin`/`require_admin_ip_allowed` import 추가, `AdminWhoamiResponse` Pydantic 모델 신규 + `_mask_email` private helper 신규 + `GET /v1/auth/admin/whoami` endpoint 신규.
- `api/app/api/deps.py` (수정) — `AdminIpBlockedError` import + `require_admin_ip_allowed` dep 신규 (`current_admin_claims` 직후 wire, 함수 내 lazy import로 순환 회피).
- `api/app/core/config.py` (수정) — `ipaddress` import 추가, `admin_ip_allowlist` Settings 필드 + `_split_admin_ip_allowlist` validator 신규(부팅 시 CIDR 형식 검증 + 잘못된 CIDR fail-fast).
- `api/app/core/proxy.py` (수정) — `check_admin_ip_allowed(request, allowlist) -> bool` helper 신규 + `__all__` 갱신.
- `api/app/core/exceptions.py` (수정) — `AdminIpBlockedError(AuthError, status=403, code="auth.admin.ip_blocked")` 신규 클래스.

**Backend tests (api/tests/) — 신규 4 파일**:

- `api/tests/api/v1/test_admin_auth_baseline.py` (신규) — Story 1.2 admin auth invariant 회귀 가드 6건(TTL 8h/refresh 미지원/만료 401/issuer mismatch 401/role 다운그레이드 403/DB role 즉시 반영) + smoke 3건(whoami 정상/non-admin 차단/토큰 부재 401) + AC4 IP 가드 1건 = 10 케이스.
- `api/tests/test_email_mask.py` (신규) — `_mask_email` NFR-S5 SOT 회귀 4 케이스(일반/1자 local/`@` 부재/빈 string).
- `api/tests/core/test_admin_ip_allowlist.py` (신규) — `check_admin_ip_allowed` helper + Settings validator 7 케이스(빈 list/매칭 IPv4/비매칭/IPv6/XFF via trusted proxy/client None deny/invalid CIDR boot fail).
- `api/tests/scripts/test_promote_admin.py` (신규) — `promote_admin` CLI 6 케이스(promote 성공/이미 admin warning/demote/미발견 exit 1/soft-deleted 미발견/멱등 2회).

**Web (web/src/) — 신규 6 파일 + 수정 2 파일**:

- `web/src/app/api/auth/admin/exchange/route.ts` (신규) — Edge route handler. `bn_access` 쿠키 검사 → 백엔드 admin/exchange 호출 → Set-Cookie forward + safeNext open redirect 가드 + 4 error 분기(login_first/role_required/exchange_failed/cookie_not_issued).
- `web/src/app/api/auth/admin/logout/route.ts` (신규) — `bn_admin_access` Max-Age=0 + Path=/v1/admin + `/admin/login` redirect (admin 토큰만 박탈, 일반 사용자 cookie 보존).
- `web/src/lib/admin-auth.ts` (신규) — `decodeAdminJwtClaims`/`evaluateAdminCookie`/`AdminGuardResult` discriminated union (Edge/server-side defense-in-depth, exp/role/iss decode + 5s skew + balancenote-admin issuer 검증).
- `web/src/app/(admin)/admin/layout.tsx` (신규) — server component, cookies().get + evaluateAdminCookie 분기 + 3 redirect 분기 (missing/expired/forbidden) + header/main shell.
- `web/src/app/(admin)/admin/page.tsx` (신규) — admin landing placeholder + 7.2/7.4 forward link 2건.
- `web/src/app/(public)/admin/login/page.tsx` (수정) — placeholder Link 대체 → server component(cookies() 읽음) + 6 ERROR_MESSAGES + 로그인 분기 2 케이스(미로그인 → Google chain start / 로그인됨 → 1-click admin exchange).
- `web/src/middleware.ts` (수정) — `classifyAdminCookie` + `expireAdminCookie` + admin 분기 갱신(stale 시 `?error=expired` 첨부 + Set-Cookie expire) + `COOKIE_BN_ADMIN_ACCESS` 상수 + dead code `hasValidLookingCookie` 제거.

**OpenAPI 클라이언트 자동 생성 (회귀 0건)**:

- `web/src/lib/api-client.ts` (자동 생성) — `admin_whoami_v1_auth_admin_whoami_get` operation 추가.
- `mobile/lib/api-client.ts` (자동 생성) — 동일 operation 추가.

**환경 변수 / SOP / 운영 스크립트 (신규 3 파일)**:

- `.env.example` (수정) — `ADMIN_IP_ALLOWLIST=` 섹션 신규(comma-separated CIDR, 빈 값 default = 미강제 — NFR-S8 정합).
- `scripts/promote_admin.py` (신규) — admin role flip CLI (argparse + asyncpg/SQLAlchemy + 4 exit code + 한국어 메시지 + non-tty prod-like fail-fast 가드).
- `docs/sop/05-admin-role-promotion.md` (신규) — 8 섹션 SOP (언제/사전 조건/실행/검증/박탈/audit forward/대체/안전 가드).

**Sprint status (수정 1 파일)**:

- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `7-1-...: ready-for-dev → in-progress → review` 전이 + `last_updated: 2026-05-10` + Story 7.1 review 코멘트 1단락(epic-6 코멘트 위에 prepend).

### Change Log

- 2026-05-10 — Story 7.1 ready-for-dev (Amelia, CS).
- 2026-05-10 — Story 7.1 review (Amelia, DS): admin auth baseline 회귀 가드 + IP 화이트리스트 + smoke endpoint + Web `(admin)` layout + middleware admin stale-self-heal + promote_admin CLI 구현 완료. pytest 1222 passed / 11 skipped / 0 failed + coverage 85.44% + ruff/format/mypy 0 errors + web/mobile tsc/lint 0 errors + OpenAPI gen 회귀 0건. CR 위임.
