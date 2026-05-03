# Deferred Work

리뷰·구현 과정에서 식별되었으나 다음 스토리·시점으로 미룬 항목 모음.

## Deferred from: code review of 3-3-langgraph-6노드-self-rag-saver (2026-05-02)

- **DF89 — `aresume`의 진짜 LangGraph resume semantics 미구현** — `api/app/services/analysis_service.py:aresume`. 현 구현은 `await self.graph.ainvoke(user_input, config=...)`로 START부터 재실행. 진짜 resume은 `Command(resume=...)` 또는 `ainvoke(None, config=...)` 패턴. 사유: spec line 125-126이 *인터페이스 박기만* 명시 — Story 3.4 needs_clarification 흐름에서 실 분기 갱신 로직과 함께 도입. **재검토 시점**: Story 3.4 — `needs_clarification = True` 후 사용자 응답 받아 parsed_items 갱신 후 재개 흐름 확정 시.
- **DF90 — `parse_meal` `raw[:50]` 그래프임 클러스터/이모지 mid-codepoint cut** — `api/app/graph/nodes/parse_meal.py:25-27`. 현 stub은 단순 `[:50]` 슬라이스로 multi-codepoint emoji/ZWJ 시퀀스 중간 절단 가능. 사유: Story 3.4가 실 LLM parse로 stub 대체 시 이 슬라이스 자체가 사라짐. **재검토 시점**: Story 3.4.
- **DF91 — `evaluate_retrieval_quality` 결정성 노드 retry 의미 0** — `_node_wrapper`가 모든 노드에 동일 retry 적용. 결정적 노드는 같은 입력으로 2회 실패 → 의미 없는 1회 추가 호출. 사유: 본 스토리는 stub만 — Story 3.6 실 LLM router 진입 시점에 retry 정책 분기(per-node opt-out 또는 deterministic 노드 wrapper override). **재검토 시점**: Story 3.6.
- **DF92 — `fetch_user_profile.health_goal` Literal 강제 변환 누락** — `api/app/graph/nodes/fetch_user_profile.py`. SQLAlchemy PG_ENUM이 raw string 반환 → DB enum drift 시 PydanticValidationError → wrapper retry 의미 없는 fallback. 사유: 현 단계 enum 안정. **재검토 시점**: Story 5.x 회원 프로필 수정 시 enum 마이그레이션과 함께.
- **DF93 — `AsyncConnectionPool max_size=4` 하드코딩** — `api/app/graph/checkpointer.py:74-75`. 동시 분석 호출 5+ 개 시 풀 starvation 가능. `RATE_LIMIT_LANGGRAPH = "10/minute"`와 정합 X. 사유: 실 부하 측정 전 premature optimization. **재검토 시점**: Story 8 운영 hardening + perf 측정.
- **DF94 — `WindowsSelectorEventLoopPolicy` conftest 글로벌 스코프** — `api/tests/conftest.py:21-22`. import-time 정책 변경이 모든 테스트에 영향 → 향후 subprocess 테스트 도입 시 충돌. 사유: 현 시점 subprocess 테스트 부재. **재검토 시점**: Story 8 hardening.
- **DF95 — `--cov-fail-under=70`을 신규 패키지 80% per-module로 강화** — `api/pyproject.toml:1900`. spec AC12 line 182는 `app/graph/` + `analysis_service.py` ≥ 80% 명시이나 게이트 미강화. 현 실측 86-100%로 충족. 사유: 게이트 강화는 cross-cutting CI 정책. **재검토 시점**: Story 8 polish CI 일괄.
- **DF96 — `psycopg-pool>=3.3` 명시 핀 부재** — `api/pyproject.toml`. `psycopg[pool]` extra가 transitive로 락(현 3.3.0). `open=False` deprecation 회피 패턴이 ≥3.3 의존. 사유: 현 lock 안정 + uv lock이 transitive 핀. **재검토 시점**: Story 8 polish — 외주 인수 readiness 정합 시 직접 핀.
- **DF97 — async fixture가 `app.state.session_maker` 공유** — `api/tests/graph/conftest.py`. pytest-xdist 병렬 도입 시 cross-test thread_id corruption 가능. 사유: 현 sequential mode 안전. **재검토 시점**: Story 8 CI 병렬화 도입 시.
- **DF98 — `_to_psycopg_dsn`이 `?driver=` query param 미스트립** — `api/app/graph/checkpointer.py:51-56`. `postgresql://...?driver=asyncpg` 같은 비표준 URL은 psycopg가 unknown param으로 거부. 사유: 현 codebase는 SQLAlchemy DATABASE_URL convention(`postgresql+asyncpg://...`)만 사용 — 발생 시나리오 X. **재검토 시점**: Story 8 polish 또는 외부 DSN convention 도입 시.
- **DF99 — `aresume`이 managed-field 주입 sanitize 부재** — `api/app/services/analysis_service.py:aresume`. 호출자가 `user_input={"rewrite_attempts": 99, "node_errors": [...]}` 같은 managed field 주입 가능 → state corruption. 사유: 본 스토리는 인터페이스만(spec line 125-126). 실 user_input shape는 Story 3.4가 정의. **재검토 시점**: Story 3.4 — 사용자 응답 payload 스키마 확정 시 sanitize layer 추가.

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
- ~~**W46 — 앱 백그라운드/킬 mid-mutation 시 중복 POST**~~ [mobile/features/meals/api.ts `useCreateMealMutation`] — ~~사용자가 "저장" 탭 후 OS가 앱을 background → 메모리 회수로 kill, 사용자 재개 후 재시도 시 같은 식단 2 row 생성 (서버는 `Idempotency-Key` 헤더 *수신*만 허용, 처리 X — AC2 정합). 사유: Story 2.5(오프라인 텍스트 큐잉) offline-queue.ts + `meals.idempotency_key UNIQUE` 컬럼 + 409 분기 일괄 도입 시 흡수.~~ **CLOSED — Story 2.5 (2026-04-30)**: `meals.idempotency_key TEXT NULL` 컬럼 + `idx_meals_user_id_idempotency_key_unique` partial UNIQUE index 추가, `POST /v1/meals`에서 `Idempotency-Key` 헤더 처리 + race-free SELECT-INSERT-CATCH-SELECT + 200 idempotent replay (RFC 9110), 모바일 `useCreateMealMutation`이 매 호출마다 `expo-crypto` `randomUUID()`로 헤더 자동 첨부. 회귀 차단: `test_post_meal_with_idempotency_key_duplicate_returns_200_same_row` + `test_post_meal_with_idempotency_key_race_simulated_two_inserts_same_key`.
- **W47 — `setError("raw_text", ...)` 미사용 (스펙 wording deviation)** [mobile/app/(tabs)/meals/input.tsx, MealInputForm.tsx] — 스펙 AC8 line 135은 400 응답 시 `setError("raw_text", { message })`로 RHF 필드-에러 API 사용 명시. 현 구현은 `setServerError(state)` + 별도 텍스트 렌더링 — 기능 동등이나 RHF `formState.errors` 통합 미활용(다음 입력 시 자동 클리어 등). 사유: P14(serverError 자동 클리어) 적용 후 추가 polish 가치 낮음, design polish 또는 RHF 통일 시점에 일괄.
- **W48 — `_create_meal_for(user)` 픽스처가 동의 게이트 우회 (의도 코멘트 부재)** [api/tests/test_meals_router.py:557-576] — `test_patch_meal_blocks_user_without_basic_consents_returns_403`은 동의 없는 사용자에게 직접 ORM insert로 meal 생성 후 PATCH 403 검증 — production에서는 같은 사용자가 *애초에* meal 생성 불가(POST에서 403). 시나리오 incoherent하나 dependency wiring 회귀 차단 목적은 유효. 의도 명시 코멘트 1줄 추가. 사유: 테스트 인프라 cleanup, Story 8 또는 메모이제이션 픽스처 도입 시점.
- ~~**W49 — `MealCard.formatHHmm` 디바이스 로컬 TZ 사용 (D1 결정에 종속)**~~ [mobile/features/meals/MealCard.tsx:14-21] — ~~`new Date(isoString).getHours()/getMinutes()`는 디바이스 TZ 기반 — 한국 사용자가 LA 출장 시 PST로 표시. 본 스토리 baseline에서 *정확한 KST pin* 의무 미명시. 사유: D1(date filter wire 시맨틱) 결정 시 wire TZ 정책에 정합 — KST 강제 시 `Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', ... })` 일괄 적용.~~ **CLOSED — Story 2.4 (2026-04-30)**: `formatHHmm` `Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul' })` 강제 적용. `[meal_id].tsx`도 동일 패턴 사용. W49 해소.
- ~~**W50 (D1 결정) — `from_date`/`to_date` wire 시맨틱 KST/UTC 드리프트**~~ [api/app/api/v1/meals.py GET /v1/meals + mobile/app/(tabs)/meals/index.tsx] — ~~모바일은 디바이스-로컬(`Date.getDate()`)로 "today"를 KST 형식 문자열 송신, 서버는 `date` 타입을 Postgres 세션 TZ(=UTC)로 캐스팅 → KST 0–9시 식사 *제외*.~~ **CLOSED — Story 2.4 (2026-04-30, D1 option B 결정)**: 백엔드 `_KST = ZoneInfo("Asia/Seoul")` + `datetime.combine(date, time.min, tzinfo=_KST)` 변환으로 `Asia/Seoul` TZ 자정 boundary 강제 — KST 0-9시 식단 누락 차단. ORDER BY 분기(D2): 날짜 필터 활성 시 ASC, 미적용 시 DESC. W50 해소.
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
- ~~**DF15 — `MealCard.tsx` `parsed_items` 표시 forward 미적용**~~ [mobile/features/meals/MealCard.tsx] — ~~Story 2.3 baseline은 *MealCard 변경 X* (Story 2.4가 일별 기록 화면 polish 시 *"인식: 짜장면 1인분, 군만두 4개"* 부제 추가). 본 스토리는 `MealResponse.parsed_items` 인터페이스 노출까지만.~~ **CLOSED — Story 2.4 (2026-04-30)**: `formatParsedItemsToInlineLabel` 헬퍼 + `MealCard.tsx` parsed_items 부제 wire(60자 ellipsis). DF15 해소.

## Deferred from: code review of story-2.3 (2026-04-30)

- **W1 — Vision 호출 client-side timeout/cancel 부재** [mobile/app/(tabs)/meals/input.tsx parseMealImage chain] — 백엔드 30s + tenacity 1회 retry로 60s까지 spinner 지속 — 사용자 escape 부재. AbortController + 35s 클라이언트 timeout + retry UI는 UX polish 영역. **재검토 시점**: Story 8 UX polish 또는 사용자 피드백 정량.
- **W2 — OpenAI SDK `client.beta.chat.completions.parse` GA 이동 시 fragile** [api/app/adapters/openai_adapter.py:155] — 현재 `beta.` 경로 채택 (spec 정합 + 2.32.0 alias 동작). 향후 SDK 버전이 `beta.` 제거 시 break — Completion Notes에 GA(`chat.completions.parse`) 마이그레이션 명시. **재검토 시점**: Story 8 dependency hardening 또는 SDK 신버전 도입 시점.
- **W3 — 같은 image_key parse 반복 호출 dedup/rate-limit 부재** [api/app/api/v1/meals_images.py POST /parse] — 호출당 새 Vision 호출 + cost 누적. 이미 DF6(Vision 응답 캐시 `cache:llm:{sha256(image_key)}` 24h TTL)와 통합 처리. **재검토 시점**: DF6과 동일 — Story 8 perf hardening.
- **W4 — `_get_client()` singleton API key 변경 무시** [api/app/adapters/openai_adapter.py:_get_client] — 첫 호출 시 캐시된 client는 settings 변경 후 재사용. runtime key rotation rare + `_reset_client_for_tests()` 우회 가능 → polish 영역. **재검토 시점**: 운영 시 key 회전 자동화 도입 시점.
- **W5 — `MealImageParseResponse` `extra="forbid"` 부재** [api/app/api/v1/meals_images.py:MealImageParseResponse] — request 모델은 `extra="forbid"`, response는 미설정. 응답 모델 일관성 polish. **재검토 시점**: Story 8 schema hardening.

## Deferred from: Story 2.4 implementation (2026-04-30, 일별 식단 기록 화면 + 7일 캐시 + KST 필터)

- **DF16 — 7일 캐시 maxAge 동적 조정** [mobile/lib/query-persistence.ts] — baseline은 `7 * 24 * 60 * 60 * 1000` hardcode. 사용자 설정 화면(*"오프라인 캐시 30일까지 보관"*) 또는 디바이스 storage limit 고려 동적 조정은 Growth UX polish. **재검토 시점**: Growth UX 또는 사용자 피드백 정량.
- **DF17 — `MealAnalysisSummary` cursor pagination 도입** [api/app/api/v1/meals.py list_meals] — Story 3.x `meal_analyses` JOIN 도입 시 *list 응답이 무거워짐*(macros 4 fields + feedback 120자) — cursor pagination 도입 검토. 본 스토리는 *날짜 필터 + limit=50*만. **재검토 시점**: Story 8 perf hardening 또는 사용자 식단 1k+ 누적 시 surface.
- **DF18 — `[meal_id].tsx` 단건 endpoint(`GET /v1/meals/{meal_id}`) 도입** [mobile/app/(tabs)/meals/[meal_id].tsx] — 7일 캐시 miss 시 *전체 fetch* 회피 + Story 3.7 SSE 채팅 진입 시점 단건 fetch 가능. 본 스토리는 *7일 client-side filter*만. **재검토 시점**: Story 8 hardening 또는 Story 3.7 SSE 통합 시.
- **DF19 — fit_score color/label 매핑 5단계 임계값 fine-tune** [mobile/features/meals/MealCard.tsx FIT_SCORE_COLORS/LABELS_KO] — baseline은 `low<40<moderate<60<good<80<excellent`. Story 3.5 알고리즘 도입 시 KDRIs AMDR 매크로 룰 기반 fine-tune. **재검토 시점**: Story 3.5 fit_score 알고리즘 도입.
- **DF20 — fit_score 헬퍼(`fit_score_color`/`fit_score_label_ko`) 모듈 분리** [mobile/features/meals/MealCard.tsx + [meal_id].tsx — 같은 매핑 inline duplicate] — Story 2.4 baseline은 `MealCard.tsx` + `[meal_id].tsx` 각각 inline 정의. Story 3.5 `fitScore.ts` 분리 시점에 통합. **재검토 시점**: Story 3.5 도입 시.
- **DF21 — 7일 캐시 `buster` 자동 bump SOP** [mobile/lib/query-persistence.ts] — baseline은 `buster: 'v1'` hardcode. Story 3.x `analysis_summary` 실제 wire 시 `'v2'` bump 누락 시 stale 캐시 형식 mismatch — *코드 리뷰 게이트*에 *persist schema 변경 시 buster bump* 명시 필요. README + CLAUDE.md SOP 1줄 추가 검토. **재검토 시점**: Story 3.3 시점에 SOP 정착.
- **DF22 — 오프라인 모드 ActionSheet 비활성 visual** [mobile/app/(tabs)/meals/index.tsx handleActionPress] — baseline은 *Alert "오프라인 — 온라인 시 가능" 1줄 안내*만. Story 8 polish — disabled visual + 아이콘 회색 + tooltip. **재검토 시점**: Story 8 UX polish.
- **DF23 — `[meal_id].tsx` accessibility — `AccessibilityInfo.announceForAccessibility`** [mobile/app/(tabs)/meals/[meal_id].tsx] — 화면 진입 시 시각 장애 사용자 자동 안내(*"19시 30분 식단 상세"*). baseline은 미수행. **재검토 시점**: Story 8 polish 또는 Growth NFR-A6.
- **DF24 — 날짜 picker calendar UI** [mobile/app/(tabs)/meals/index.tsx 헤더] — baseline은 prev/next/today 3 버튼만. *전체 calendar 진입*(@react-native-community/datetimepicker)은 yagni — Story 8 polish 또는 사용자 피드백 시점.
- **DF25 — historic limit (60일 전) 적용 부재** [mobile/app/(tabs)/meals/index.tsx handlePrevDay] — baseline은 *prev 무한*(60일 전 데이터도 fetch — 1일 단위 limit=50 충분). 무한 클릭 차단은 yagni — 사용자가 60일 이상 과거로 이동 시 빈 화면 + UX 친화적. **재검토 시점**: Story 8 polish.
- **DF26 — `useMealsQuery`의 `[meal_id].tsx` 호출 — 7일 윈도우 over-fetch** [mobile/app/(tabs)/meals/[meal_id].tsx useMealsQuery] — 단건 endpoint 부재로 *7일 전체 fetch* + client-side filter. 30일 누적 사용자에게 list 무거워짐. DF18과 통합 처리 — 단건 endpoint 도입 시 client-side filter 제거. **재검토 시점**: Story 8 또는 Story 3.7 — DF18과 동일.

## Deferred from: code review of 2-4-일별-식단-기록-화면 (2026-04-30)

- **DF27 — `from_date` 단독 사용 시 미래 식단 무한 노출** [api/app/api/v1/meals.py:506-508 list_meals] — `from_date`만 주고 `to_date` 미지정 시 `Meal.ate_at >= from_dt` upper bound 부재로 미래 catch-up 식단까지 모두 반환. 현 모바일은 `from_date == to_date` 동시 송신이라 노출 표면 없음. limit=200 cap 있음. **재검토 시점**: Story 8 운영 hardening — `to_date` 미지정 시 자동 boundary(예: today + 1d) 강제 또는 `from_date 단독` 거부.
- **DF28 — `MealMacros` upper bound 미정의** [api/app/api/v1/meals.py:260-273 MealMacros] — `Field(ge=0)`만 강제, `le=` 미지정. Story 3.x LLM 환각 데이터(`carbohydrate_g=99999`) 저장 시 `MealCard` macros row UI 잘림. 본 스토리는 슬롯 정의만, 채우는 건 Story 3.3/3.5 책임. **재검토 시점**: Story 3.3 `meal_analyses` JOIN 도입 시 — `Field(ge=0, le=10000)` 등 upper bound 추가.
- **DF29 — `[meal_id].tsx` 7일 fetch useMemo 자정 cross stale** [mobile/app/(tabs)/meals/[meal_id].tsx:96-97] — `useMemo(() => addDays(todayKst(), -7), [])` + `useMemo(() => todayKst(), [])`가 마운트 시점 1회 계산. 화면 유지 중 자정 cross 시 윈도우 stale. detail은 단발 진입이라 빈도 미미. **재검토 시점**: Story 8 polish.
- **DF30 — `web/src/lib/api-client.ts` 사용처 타입 마이그레이션** [web/src/lib/api-client.ts] — `MealResponse.analysis_summary` 신규 non-optional 필드 추가로 웹 사용처가 객체 리터럴 mock 시 strict TS 컴파일 영향 가능. 본 스토리는 OpenAPI 자동 재생성만 — 웹 사용처 영향은 별건 PR. **재검토 시점**: Story 4.3 web 주간 리포트 또는 web 식단 화면 도입 시.
- **DF31 — `addDays` Invalid 입력 가드** [mobile/features/meals/dateUtils.ts] — `NaN`/`Infinity`/잘못된 ISO 입력 시 `Invalid Date` silent 통과 가능. 호출처에서 ±1 hardcoded라 노출 표면 작음. **재검토 시점**: Story 8 polish 또는 datetimepicker 도입 시(DF24).
- **DF32 — 삭제 mutation 후 `router.back()` `isMounted` 가드** [mobile/app/(tabs)/meals/[meal_id].tsx:118-130] — 삭제 in-flight 시 사용자가 iOS 가장자리 스와이프 백 → 응답 도착 시점에 `router.back()` 재호출 — stack에 따라 다른 탭으로 빠질 수 있음. 발생 빈도 낮음. **재검토 시점**: Story 8 polish.
- **DF33 — `invalidateQueries` 후 throttle 1초 내 강제 종료 stale 캐시** [mobile/lib/query-persistence.ts:26 throttleTime] — 삭제 → 1초 내 OOM/forced close 시 throttle window에서 disk write 누락 → 다음 실행 시 7일 캐시에 삭제된 meal 잔존. mutation 후 즉시 `persistClient` flush 호출 미적용. 발생 빈도 낮음. **재검토 시점**: Story 8 polish.
- **DF34 — `useMealsQuery` limit 명시(50→200)** [mobile/features/meals/api.ts useMealsQuery] — 모바일은 `limit` 미지정 → 백엔드 default 50. 일자별 51끼+ 시연 시나리오에서 일부 누락. 실서비스에서 비현실적. **재검토 시점**: Story 8 polish 또는 e2e 시연 데이터 수요 시.
- **DF35 — 자정 boundary cross 시 `selectedDate` 갱신 안 됨** [mobile/app/(tabs)/meals/index.tsx:38] — 23:59에 `selectedDate=today` mount → 00:00:05에 invalidate→refetch → `todayKst()` 재계산 안 됨. 어제 화면에 머물고 새 식단 미표시. **재검토 시점**: Story 8 polish — `AppState` listener 또는 자정 timer로 selectedDate 재평가.
- **DF36 — `Intl.DateTimeFormat` ICU `'24:00'` 회귀 가능성** [mobile/features/meals/MealCard.tsx + [meal_id].tsx formatHHmm] — `hour: '2-digit', hour12: false` + `timeZone: 'Asia/Seoul'` 설정이 일부 RN Hermes 빌드/ICU 버전에서 자정 시 `'00:00'` 대신 `'24:00'` 반환 가능. `hourCycle: 'h23'` 명시 미적용. 단위 테스트 부재로 회귀 잡기 어려움. **재검토 시점**: Story 8 hardening.
- **DF37 — 만료 presigned URL fallback** [mobile/features/meals/MealCard.tsx + [meal_id].tsx — `expo-image`] — R2 image_url presign 만료 시 `expo-image` `onError` 핸들러 부재로 회색 background 잔상. 현 image_url은 public URL 가정. **재검토 시점**: Story 2.2 R2 wire 또는 Story 8 polish — presign 만료 핸들링 + retry.
- **DF38 — 폰트 200% + `allergen_violation` 라벨 헤더 row 깨짐** [mobile/features/meals/MealCard.tsx:174-187 headerRow] — `flexShrink:1, flexWrap:'wrap'` 있으나 `headerRow justifyContent:'space-between'` + time `minWidth: 56`으로 right side가 잘릴 수 있음. baseline 항상 null 미노출 — Epic 3 wire 시점 회귀 위험. **재검토 시점**: Story 3.3 `analysis_summary` JOIN 도입 시 NFR-A3 회귀 검증.
- **DF39 — `parsed_items` 1000+ 렌더 비용** [mobile/features/meals/parsedItemsFormat.ts formatParsedItemsToInlineLabel] — 60자 cap 적용은 `formatParsedItemsToRawText` 전체 join 후 slice. 악의적 OCR 응답 또는 백엔드 회귀로 1000+ items 시 카드당 ms 단위 비용. Story 2.3 OCR 응답 cap으로 차단되나 방어 layer 부재. **재검토 시점**: Story 8 hardening.
- **DF40 — `formatHHmm` timezone offset 누락 가드** [mobile/features/meals/MealCard.tsx + [meal_id].tsx] — `ate_at` 문자열에 `+09:00`/`Z` suffix 누락 시 `new Date(...)`이 디바이스 로컬 TZ로 해석 → KST 표시 회귀. 백엔드 contract `+09:00` 신뢰. persister 7일 캐시 hydrate 시점 schema migration 가능성. **재검토 시점**: Story 8 hardening — 정규식 offset 강제 검증.
- **DF41 — `formatHHmm` Hermes 회귀 단위 테스트** [mobile/features/meals/MealCard.tsx + [meal_id].tsx] — `Intl.DateTimeFormat` `formatToParts` 출력 환경 차이(`'24:00'` 등 — DF36 정합) 회귀 차단 단위 테스트 부재. baseline은 fallback `'00'` 처리만. **재검토 시점**: Story 8 hardening 또는 모바일 단위 테스트 도입 시점.
- ~~**DF42 — `[meal_id].tsx` `index.tsx`의 7일 캐시 토폴로지 정합**~~ — ~~`index.tsx`는 일자별 queryKey, `[meal_id].tsx`는 7일 윈도우 queryKey~~ **CLOSED — Story 2.4 CR (2026-04-30, 옵션 b 채택)**: `index.tsx`도 7일 윈도우 fetch + client-side filter로 변경. queryKey 통일(detail과 캐시 공유) + NFR-R4 일자 무관 7일 보장 + 백엔드 ASC + client filter로 AC4 시간순 정합.


## Deferred from: Story 2.5 implementation (2026-04-30, 오프라인 텍스트 큐잉 + Idempotency-Key)

- **DF43 — PATCH/DELETE 오프라인 큐잉** [mobile/lib/offline-queue.ts + (tabs)/meals/input.tsx] — 본 스토리 baseline은 PATCH/DELETE 오프라인 차단(Alert + back). 사용자가 오프라인에서 수정하려는 케이스(예: 제품 데모 중 회식 후 식단 수정)는 *Story 8 polish* — 큐잉 + 자동 flush 도입 검토. **재검토 시점**: Story 8 polish 또는 사용자 피드백.
- **DF44 — 사진 큐잉 (online deferred sync)** [mobile/lib/offline-queue.ts + (tabs)/meals/input.tsx] — 본 스토리 baseline은 사진 입력 오프라인 차단. *온라인 시 사진 첨부 + 텍스트는 큐잉(Vision 호출은 차후)* 부분 큐잉은 *Growth* — Vision 호출 비용 + UX 복잡도. **재검토 시점**: Growth UX polish.
- **DF45 — `OfflineQueueItem` schema buster 패턴** [mobile/lib/offline-queue.ts] — 본 스토리 baseline은 deserialize 실패 시 silent reset. *명시 buster 패턴*(`v1` → `v2` bump on schema change)은 Story 8 polish (Story 2.4 query-persistence DF21 정합). **재검토 시점**: Story 8 polish 또는 schema migration 발생 시점.
- ~~**DF46 — manual retry granular `attempts` reset 정책**~~ — ~~본 스토리 baseline은 manual retry 시 attempts reset 미적용(누적 유지). *attempts cap 도달 후 manual retry granular reset*은 Story 8 polish~~ **CLOSED — Story 2.5 CR (2026-04-30, DN2 결정 P16 승격)**: D4 baseline literal 충족 — `resetAttempts(userId, client_id)` 헬퍼 신규 + `triggerFlush`가 `flushQueue` 호출 전 attempts=0 reset.
- **DF47 — 큐 size 동적 cap** [mobile/lib/offline-queue.ts OFFLINE_QUEUE_MAX_SIZE] — 본 스토리 baseline은 100건 hard cap. *디바이스 storage / 사용자 설정 기반 동적 조정*은 Growth UX polish. **재검토 시점**: Growth UX polish.
- **DF48 — Sentry/PII 마스킹 큐 데이터** [mobile/lib/offline-queue.ts + 4xx Alert] — 본 스토리 baseline은 raw_text 그대로 큐 보관 + 4xx 시 Alert에 server detail 노출. *Sentry capture 시점에 raw_text 마스킹*은 Story 8 polish (NFR-S5). **재검토 시점**: Story 8 polish — Sentry wire 시점.
- **DF49 — `Idempotency-Key` cross-cutting 도메인 격리** [api/app/core/exceptions.py — `MealIdempotencyKeyInvalidError(MealError)`] — 본 스토리 baseline은 `MealError` 식단 도메인 하위. *Story 6.x 결제 webhook idempotency 도입* 시점에 *`IdempotencyError` cross-cutting base*로 분리 검토. **재검토 시점**: Story 6.x 결제 웨훅 도입.
- **DF50 — Idempotency-Key TTL** [api/app/db/models/meal.py idempotency_key] — 본 스토리 baseline은 `meals.idempotency_key`가 *영구 보존* (soft delete 후에도 unique 충돌 가능 — 409 분기). *TTL 정책*(예: 7일 후 NULL clear)은 Story 5.x 데이터 보존 정책 + Story 8 cron 도입 시점에 검토. **재검토 시점**: Story 5.x 또는 Story 8 cron.
- **DF51 — flush 중 transient 에러 시 다음 항목 진행 (batch parallel)** [mobile/lib/offline-queue.ts flushQueue] — 본 스토리 baseline은 transient 에러 시 flush 중단(첫 항목 backoff 의미 보존). *batch parallel sync*는 Story 8 polish — race + UX 트레이드오프 평가. **재검토 시점**: Story 8 polish.
- **DF52 — `OfflineMealCard.tsx` 재시도 횟수 visual progress** [mobile/features/meals/OfflineMealCard.tsx] — 본 스토리 baseline은 *"3회 시도 실패"* 텍스트만. *progress bar / step indicator*는 Story 8 UX polish. **재검토 시점**: Story 8 UX polish.
- **DF53 — 큐 항목 시간 ordering 일관성** [mobile/app/(tabs)/meals/index.tsx — 큐 카드 표시] — 사용자가 *어제 자정에 입력 → 오늘 sync* 시 일자 표시는 *어제* (`ate_at` 기준)지만 큐 표시는 *오늘 입력*(today 분기). UX 명료성은 Story 8 polish. **재검토 시점**: Story 8 polish.

## Deferred from: code review of 2-5-오프라인-텍스트-큐잉-sync (2026-04-30)

- **DF54 — `_flushOnce` iteration cap (defensive)** [mobile/lib/offline-queue.ts:_flushOnce] — 현 `while(true)` + 진행 가드(removeItem/break)로 정상 종료. 이론적 storage 부패 시 무한 루프 방어 미적용. **재검토 시점**: Story 8 hardening.
- **DF55 — race-fallback `MealIdempotencyKeyRaceResolutionError` 신규** [api/app/api/v1/meals.py:_create_meal_idempotent_or_replay] — race-loser SELECT가 0건일 때 `BalanceNoteError` (base 500) raise. catalog 일관성 위해 specialized error code(`meals.idempotency_key.race_resolution_failed` 등) 분리. **재검토 시점**: Story 8 또는 Story 6.3 결제 idempotency.
- **DF56 — `triggerFlush` UI 상태를 module mutex와 동기화** [mobile/app/(tabs)/meals/index.tsx:triggerFlush] — `useState(isFlushing)` + module `flushing` flag 분리 → UI 상태가 실제 mutex와 일시 divergence(cosmetic). subscribe 패턴 또는 single source of truth. **재검토 시점**: Story 8 polish.
- **DF57 — 큐 배지 `accessibilityLiveRegion="polite"` 재공지 노이즈** [mobile/app/(tabs)/meals/index.tsx 배지 영역] — 매 `queueSize` 변경마다 VoiceOver 재공지 — flush 진행 중 N→0 단계별 announce. offline→online 전이 시 1회만 공지로 정련. **재검토 시점**: Story 8 a11y polish.
- **DF58 — `expo-crypto.randomUUID()` 예외 fallback** [mobile/features/meals/api.ts + (tabs)/meals/input.tsx] — 일부 edge 디바이스에서 throw 가능. 현 try/catch 부재 → mutation/enqueue 자체 실패. fallback UUID 생성기 또는 명시 에러 처리. **재검토 시점**: Story 8 hardening.
- **DF59 — 컴포넌트 unmount 시 in-flight flush AbortController** [mobile/lib/offline-queue.ts:_flushOnce] — `setTimeout` backoff 도중 unmount 시 detached 실행 + AsyncStorage mutate. 메모리/잔여 mutate 위험. AbortSignal 도입. **재검토 시점**: Story 8 polish.
- **DF60 — `isInternetReachable` vs `isOnline` 분기 강화** [mobile/lib/use-online-status.ts + (tabs)/meals/index.tsx 자동 flush 트리거] — 현 Story 2.4 baseline `isConnected !== false`만 사용. `isInternetReachable === false` 케이스에서 useless 시도 누적. 조건 분기 강화. **재검토 시점**: Story 8 polish.
- **DF61 — `subscribeQueue` 알림 → `getQueueSnapshot` async 폭주 coalesce** [mobile/lib/offline-queue.ts] — 매 enqueue/remove 시 모든 subscriber가 AsyncStorage read. coalesce(microtask/idle) 또는 in-memory snapshot caching. **재검토 시점**: Story 8 perf polish.
- **DF62 — `enqueued_at` 미래 timestamp 음수 diff 가드** [mobile/features/meals/OfflineMealCard.tsx:formatRelativeTime] — 시계 skew 시 *"-2분 전 입력"* 가능. `if (diffMs < 0) return '방금 전 입력'`. **재검토 시점**: Story 8 polish.
- **DF63 — flush 도중 unmount → `setIsFlushing` mounted ref guard** [mobile/app/(tabs)/meals/index.tsx:triggerFlush finally] — React 19에서는 warning 제거됐으나 mounted ref 패턴은 baseline 안정성 향상. **재검토 시점**: Story 8 polish.
- **DF64 — `_create_meal_idempotent_or_replay` `values: dict` 타입 강화** [api/app/api/v1/meals.py:_create_meal_idempotent_or_replay] — 현 `dict[str, object]` — runtime mismatch 미감지. `MealInsertValues` TypedDict 또는 named args. **재검토 시점**: Story 8 type discipline.
- **DF65 — `AsyncStorage.setItem` quota 에러 명시 사용자 안내** [mobile/lib/offline-queue.ts:_writeQueue] — 현 Promise rejection으로 자연 surface. `enqueueMealCreate` 호출자가 `OfflineQueueFullError` 분기만 처리, 일반 `Error`는 *"입력이 저장되지 않았어요"* Alert 누락. **재검토 시점**: Story 8 hardening.
- **DF66 — 다중 `Idempotency-Key` 헤더 처리(프록시 coalescing 가드)** [api/app/api/v1/meals.py:create_meal Header 의존성] — FastAPI 기본은 first-only. 프록시 coalescing/clobber 시 멱등 우회 가능. 명시 single-value enforcement. **재검토 시점**: Story 8 또는 Story 6.3 결제.
- **DF67 — `db.rollback()` 후 `db.commit()` 향후 pre-INSERT write 단언** [api/app/api/v1/meals.py:create_meal + _create_meal_idempotent_or_replay] — 현 흐름은 안전(replay 시 helper 내부 rollback, 라우터 commit은 no-op txn). 향후 pre-INSERT DB write 추가 시 silent rollback 위험. 명시 분기 또는 `transaction` 컨텍스트 매니저. **재검토 시점**: Story 8 refactor.
- **DF68 — `OfflineQueueItem.attempts` JSDoc 의미(0-based vs post-send count) 정렬** [mobile/lib/offline-queue.ts:OfflineQueueItem] — JSDoc *"0-based"* vs 코드 *"post-send count"* 불일치(첫 send 후 1). 단순 doc 정정. **재검토 시점**: Story 8 doc polish.
- **DF69 — 큐 배지 탭 시 ActionSheet 도입(AC6 literal 복원)** [mobile/app/(tabs)/meals/index.tsx 배지 + ActionSheet] — 본 스토리 baseline은 카드 액션 단일 노출(redundant 회피, DN1 결정). *배지 탭 → ActionSheet*는 Story 8 UX polish — 큐 항목 多 시 빠른 일괄 retry/폐기 흐름 도입 평가. **재검토 시점**: Story 8 UX polish.
- **DF70 — 식약처 OpenAPI endpoint URL + 응답 키 매핑 운영 검증** [api/app/adapters/mfds_openapi.py:MFDS_API_BASE_URL + MFDS_RAW_KEY_MAP + MFDS_KOREAN_FOOD_CATEGORIES] — Story 3.1 baseline은 *추정값*(공공데이터포털 데이터셋 15127578 신/구 표준 혼재 + 데이터셋별 endpoint 변동 위험). 운영 부팅 시 실제 OpenAPI 문서 + 샘플 응답으로 *최종 endpoint URL + 키 매핑 + 카테고리 명* 확정 필요. 현 추정 endpoint로 401/404 시드 fail 가능. **재검토 시점**: 외주 운영 첫 부팅 직전 또는 Story 8 hardening.
- **DF71 — `embedding NULL` row 백필 — wakeful repair 호출** [api/app/rag/food/seed.py:_embed_batch graceful fallback] — D4 graceful로 batch 임베딩 실패 시 `embedding NULL` INSERT 허용. 검색 시점에 자동 제외되지만, 누적된 NULL row를 *백필 재호출*하는 운영 SOP 부재. cron-driven repair 또는 Story 3.4 시점에 unmatched 시 임베딩 재계산 분기. **재검토 시점**: Story 3.4 또는 Story 8 polish.
- **DF72 — `food_aliases.canonical_name` ↔ `food_nutrition.name` orphan 검증 SOP** [api/app/rag/food/aliases_seed.py + Story 3.4 normalize.py] — 본 스토리 baseline은 두 시드 *독립*(canonical_name이 food_nutrition.name과 1:1 매칭되지 않아도 시드 통과). Story 3.4 normalize.py가 unmatched 시 임베딩 fallback로 자연 처리. 운영 시점에 orphan 비율 모니터링 + 데이터 품질 KPI 도입. **재검토 시점**: Story 3.4 또는 Story 8 polish.
- **DF73 — `MFDS_RAW_KEY_MAP` const 미사용(deprecated 표기 가드)** [api/app/adapters/mfds_openapi.py:MFDS_RAW_KEY_MAP + _raw_to_standard] — 현 `_raw_to_standard`는 inline 매핑(`item.get("FOOD_NM_KR") or item.get("name")`) 사용. `MFDS_RAW_KEY_MAP` const는 *문서 + DS 검증용*만 — 실제 매핑 로직은 함수 내 inline. 운영 부팅 시 실제 키가 const와 정합 검증 후 함수 본문도 const-driven으로 리팩터(키 변경 시 한 곳만 수정). **재검토 시점**: Story 8 refactor.
- **DF74 — `data/mfds_food_nutrition_seed.csv` placeholder → 실데이터 commit SOP 자동화** [api/data/mfds_food_nutrition_seed.csv + scripts/refresh_food_data.py 신규] — 본 스토리 baseline은 헤더만 commit. 운영자가 data.go.kr 통합 자료집 ZIP 다운로드 → 컬럼 변환 → CSV commit 수동 SOP. 분기 1회 갱신 자동화 스크립트(다운로드 + 변환 + diff 검증) 도입 검토. **재검토 시점**: Story 8.5 운영 SOP.

## Deferred from: code review of 3-1-음식-영양-rag-시드-pgvector (2026-05-01)

- **DF75 — `food_nutrition.updated_at` ON UPDATE DB-level 트리거** [api/alembic/versions/0010_food_nutrition_and_aliases.py L731-736, L772-777] — ORM `onupdate=text("now()")`만 적용 — psql 직접 UPDATE(외주 인수 클라이언트 SOP 경로 B)는 `updated_at` 자동 갱신 X. trigger 또는 generated column으로 DB-level enforcement. **재검토 시점**: Story 8 polish 또는 외주 인수 클라이언트 첫 부팅 SOP 정합 시.
- **DF76 — `_SEED_CSV_PATH = __file__.parents[3]` 경로 fragile** [api/app/rag/food/seed.py L1755-1759] — wheel/installed layout 또는 모듈 이동 시 silent miss(다른 경로 찾기). `settings.seed_data_dir` 도입 + startup 검증 로그. **재검토 시점**: Story 8 hardening.
- **DF77 — `MFDS_RAW_KEY_MAP` dead const 정리** [api/app/adapters/mfds_openapi.py L863-877 vs _raw_to_standard L996-1025] — `_raw_to_standard`가 const를 사용하지 않고 inline 매핑 — SOT 분리(DF73과 정합). const-driven으로 일원화. **재검토 시점**: Story 8 refactor (DF73 흡수).
- **DF78 — HNSW partial index `WHERE embedding IS NOT NULL`** [api/alembic/versions/0010_food_nutrition_and_aliases.py L745-752] — D4 graceful로 NULL embedding 행 발생 시 인덱스 bloat. `postgresql_where=sa.text("embedding IS NOT NULL")` 추가 검토. **재검토 시점**: Story 3.3 retrieve_nutrition perf 측정 후.
- **DF79 — `_get_client` MFDS API key 회전 캐시 무효화** [api/app/adapters/mfds_openapi.py:_get_client L955-975] — rolling deploy 시 MFDS_OPENAPI_KEY 회전 후 stale auth로 retry 실패 가능(현 `_fetch_page`는 매 호출 read이므로 부분 mitigation). prod 모드에서만 강한 invalidation 필요 시. **재검토 시점**: Story 8 prod hardening.
- **DF80 — Migration 부분 실패 복구 — `DROP INDEX IF EXISTS`** [api/alembic/versions/0010_food_nutrition_and_aliases.py upgrade/downgrade] — `op.create_index` 실패로 부분 commit된 상태에서 downgrade 재시도 시 IF EXISTS 누락으로 fail. defensive `op.execute("DROP INDEX IF EXISTS ...")`. **재검토 시점**: Story 8 hardening.
- **DF81 — `_read_zip_fallback` CSV header schema 검증** [api/app/rag/food/seed.py:_read_zip_fallback] — header typo 시 모든 row의 `source_id`가 synthetic fallback로 빠짐 — silent corruption 위험. 첫 행 키 set이 expected schema와 정합 검증 + 비-graceful 환경에서는 raise. **재검토 시점**: Story 8 polish.
- **DF82 — `bootstrap_seed.py` outer Sentry capture (ImportError edge)** [scripts/bootstrap_seed.py L32-36] — sys.path 미설정으로 `from seed_food_db import` 실패 시 stderr trace만 남고 Sentry capture 부재. `seed_food_db.main`은 자체 capture가 있으나 이 outer는 부재. **재검토 시점**: Story 8 polish.
- **DF83 — bootstrap test `>=` → `==` 정확 매칭 가드** [api/tests/integration/test_bootstrap_seed.py:test_bootstrap_seed_normal] — `food_total >= 50` 단언 → over-insertion 회귀 미감지. `== target_count` 정확 매칭으로 truncation 로직 회귀 가드. **재검토 시점**: Story 8 polish.

## Deferred from: code review of 3-2-가이드라인-rag-시드-chunking (2026-05-01)

- **DF84 — `pypdf` 6.10.2 vs spec/dev-notes `>=5.1` 가이드 drift** [api/uv.lock:1630 + api/pyproject.toml:41] — `>=5.1` 제약은 6.x 허용으로 lock 자체는 합법. spec/dev-notes는 5.1 동작 기준이지만 6.x로 한국어 PDF 추출 parity 미검증. PDF chunker는 MVP 시드 경로 호출 X(D1)이므로 prod 영향 0. pyproject `pypdf>=5,<7` 정합 또는 spec 갱신. **재검토 시점**: Story 8 polish 또는 외주 인수 PDF 자동 시드 활성화 시점.
- **DF85 — `verify_allergy_22.py` 하드코딩 MFDS CMS IDs 부패 방어** [scripts/verify_allergy_22.py:36-49] — `flSeq=42533884` / `bbs_no=bbs001` / `seq=31242` ephemeral CMS ID. 식약처 사이트 재구성 시 dead URL. 분기 SOP에서 운영자가 수동 검색하지만, `last_verified_at` 메타 + 식약처 별표 PDF 자동 다운으로 흡수. **재검토 시점**: Story 8.4 운영 SOP polish.
- **DF86 — `bootstrap_seed.main()` 직접 통합 테스트 부재 (asyncio.run 충돌)** [api/tests/integration/test_bootstrap_seed.py:278-280] — `bootstrap_seed.main`은 sync wrapper(`asyncio.run` 내부)이므로 pytest-asyncio 환경에서 직접 호출 시 "running event loop" 충돌. 테스트는 `_run_seeds()`를 직접 await로 sequencing 검증 + docker compose 통합 smoke로 main 자체 검증(AC11). sync subprocess test 추가 검토. **재검토 시점**: Story 8 polish.
- **DF87 — `KnowledgeChunk.updated_at` ORM `onupdate=now()`가 raw-SQL 경로에서 dead** [api/app/db/models/knowledge_chunk.py + api/alembic/versions/0011_knowledge_chunks.py] — 시드는 raw INSERT의 `ON CONFLICT DO UPDATE SET ... updated_at = now()`로 명시 set하므로 운영 issue 0. ORM `onupdate`는 ORM session.flush 시점에만 작동. Postgres `ON UPDATE` 트리거 또는 generated column으로 DB-level enforcement(DF75와 정합). **재검토 시점**: Story 3.6+ ORM update 패턴 도입 시 또는 Story 8 hardening.
- **DF88 — `chunk_pdf` `for page in reader.pages` 루프가 try-block 외부 (lazy load 시점 leak)** [api/app/rag/chunking/pdf.py:48] — `PdfReader(...)` 생성자 try block 내부지만 `reader.pages` iteration은 외부. pypdf 6.x는 lazy load이므로 page 접근 시 `PdfReadError` 가능 → 외부로 leak하여 `GuidelineSeedAdapterError` 미래핑. PDF chunker는 MVP 시드 경로 호출 X(D1)로 운영 영향 0. **재검토 시점**: 외주 인수 PDF 자동 시드 활성화 시점.

## Deferred from: code review of 3-4-음식명-정규화-매칭-fallback (2026-05-03)

- **DF100 — `parse_meal._load_parsed_items_from_db` per-call session — retrieve_nutrition 세션과 batching 미실현 (per-analysis 2x connection churn)** [api/app/graph/nodes/parse_meal.py:32-49] — 한 분석 파이프라인 안에서 parse_meal과 retrieve_nutrition 노드가 각각 별도 `async with deps.session_maker()` 컨텍스트 → connection 2개 순차 점유. NFR-P4 ≤ 3s 게이트는 통과(현 측정 안전권)하지만 부하 시 pool 압박 가능. NodeDeps에 session 선택적 주입 패턴 또는 노드 간 단일 트랜잭션 공유 도입. **재검토 시점**: Story 8.4 운영 polish — Sentry latency p95 측정 후 + connection pool exhaustion alert 발동 시.
- **DF101 — `_mock_llm_adapters` fixture 4 모듈 중복 — DRY 위반, LLM 어댑터 추가 시 다중 touch point** [tests/services/test_analysis_service.py:28-50 + tests/graph/test_pipeline.py + tests/graph/test_self_rag.py + tests/test_main_lifespan.py] — 동일 mock 패턴(parse_meal_text + rewrite_food_query + generate_clarification_options)이 4 테스트 모듈에 복사. `tests/conftest.py`로 단일 SOT 추출 시 중복 제거 + 신규 LLM adapter 추가 시 단일 touch point. 본 스토리 회귀 0건 + 정상 동작. **재검토 시점**: Story 3.6(generate_feedback 실 LLM) 또는 Story 3.7(dual-LLM router) 도입 시점에 동시 conftest 통합.

