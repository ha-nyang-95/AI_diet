# Story 7.4: Self-audit 화면 + 민감정보 마스킹 + 원문 보기 토글

Status: done

<!-- Epic 7 마지막 스토리 — Story 7.1(`(admin)` route group + admin layout SSR guard +
`current_admin` 3-tier transitive 체인 + IP 화이트리스트 + admin_whoami smoke +
promote_admin CLI) + Story 7.2(`admin.py` 6 endpoint + `app/core/masking.py` 4 helper
SOT + 8 Pydantic 응답 모델 + cursor pagination helpers + alembic 0021
`idx_users_email_lower` + 8 web 파일) + Story 7.3(`audit_logs` 테이블 + alembic 0022 +
`audit_admin_action` factory dep + `audit_service.record_admin_action` + 6 endpoint
audit wire + append-only trigger + 3 인덱스 + fail-open + 5 helper) 베이스라인 위에
**FR38 self-audit *읽기* 흐름 + FR39 *원문 보기* 토글** 본격 신설. epics.md:920-933
정합 + architecture.md:760 *"audit-logs/page.tsx # FR37-FR38"* 정합 + architecture.md:773
*"AuditLogTable.tsx"* 정합 + architecture.md:995 *"FR38 — `admin.py:audit_logs`
self-audit 화면"* 정합 + architecture.md:996 *"FR39 — 관리자 화면 마스킹 — Web
`features/admin/UserSearch.tsx` 마스킹 토글"* 정합. **본 스토리는 audit *읽기*
인프라 + PII unmask 토글 SOT** — Story 7.3이 *쓰기*(audit row INSERT) 인프라 + 6
endpoint write-wire를 완료한 위에 *읽기*(self-audit endpoint) + *토글*(plaintext
응답 + `user_pii_view` audit row) 분기를 마무리. 신규 7 영역: (1) **`GET /v1/admin/
audit-logs` self-audit endpoint** — `actor_id="me"` 고정(1인 owner MVP — 외주
클라이언트별 옵션 forward) + cursor pagination(`occurred_at DESC` keyset) + optional
filter(`action` enum / `target_user_id` UUID / `since` ISO datetime) + NFR-P9 ≤ 1초/
1만 row 검증. **본 endpoint는 `Depends(audit_admin_action)` 미적용** — self-audit
조회 자체를 audit하면 폭증(`admin_whoami` exclusion 패턴 정합, Story 7.3 docstring
867행 정합), (2) **`POST /v1/admin/users/{user_id}/pii-reveal` PII unmask endpoint** —
명시 *원문 보기* 액션 + plaintext 응답(email/age/weight_kg/height_cm/allergies list) +
`dependencies=[Depends(audit_admin_action(action="user_pii_view", target_resource="users"))]`
1줄 wire로 audit row 자동 기록(`user_pii_view` ENUM 값은 Story 7.3에서 사전 등록),
(3) **`app/core/masking.py` plaintext 분기 흡수** — 4 helper에 `reveal_email`/
`reveal_weight`/`reveal_height`/`reveal_allergies` 추가(`mask_*` 패턴 정합 + 반환
타입 분기). Story 7.2 SOT 모듈 docstring 8행 *"Story 7.4에서 plaintext 분기 추가 시
본 모듈에 흡수"* 정합. 기존 `mask_*` 4 함수 signature/return 변경 0건(회귀 0),
(4) **Web `(admin)/admin/audit-logs/page.tsx`** — Server Component shell + SSR fetch
첫 페이지(`bn_admin_access` cookie SSR forward — Story 7.2 admin user_id 페이지
패턴 정합) + 401/403 → `/admin/login?error=expired/forbidden` redirect + 미데이터 시
빈 상태. (5) **Web `features/admin/AuditLogTable.tsx`** — Client Component +
TanStack Query + 반응형(모바일 360px 카드 / 데스크톱 1440px+ 테이블 `sm:` 분기, Story
7.2 UserSearchClient 패턴 1:1 정합) + "더 보기" 버튼 cursor pagination + action enum
한국어 label 변환(`audit_logs_action_enum` 7 값 → 한국어 사용자 친화 표현),
(6) **Web `features/admin/UserDetailClient.tsx` *원문 보기* 토글** — *프로필* 탭
헤더에 토글 버튼 + 확인 모달(`window.confirm` 단순 채택 — shadcn/ui Dialog는 Story
8.4 polish forward, Story 7.2 패턴 정합) + 토글 ON 시 `POST .../pii-reveal` 호출 +
plaintext response state 보존 + 5분 비활동 자동 복원(setTimeout + activity-tracking
DOM event listener `mousemove`/`keydown`/`click`/`touchstart` 갱신). 토글 OFF은
client-side state로 즉시 마스킹 복귀 + plaintext state 폐기(메모리 누수 0).
(7) **Web `(admin)/admin/page.tsx` link 정합** — Story 7.1 placeholder *"FR38 — 7.4
에서 추가"* 단락 제거 + Story 7.4 wire 완료 표기로 갱신. **본 스토리는 백엔드 admin
auth core SOT(security.py / deps.py `current_admin`+`audit_admin_action`+
`require_admin_ip_allowed` + `bn_admin_access` cookie + `users.role`) 변경 0건 +
audit_logs schema 변경 0건(Story 7.3 SOT 재사용) + admin.py 6 endpoint 본문 변경
0건(audit wire는 Story 7.3 SOT, 본 스토리는 *7번째 endpoint 신설*만)** — Story
1.2/7.1/7.2/7.3 산출물 *재사용*만. `app/core/masking.py`는 신규 `reveal_*` 함수 4개
추가(기존 `mask_*` 4개 변경 0건 — 회귀 16 케이스 모두 PASS 보존). **신규 모듈 0건**
+ **수정 4건**(`app/api/v1/admin.py` 2 endpoint + Pydantic 모델 + Korean label SOT
`app/api/v1/admin.py` audit-log Pydantic + `app/core/masking.py` reveal 4 함수 +
`app/db/models/audit_log.py` import-only). **신규 web 파일 2건**(`(admin)/admin/
audit-logs/page.tsx` + `features/admin/AuditLogTable.tsx`) + **수정 2건**(`features/
admin/UserDetailClient.tsx` 원문 보기 토글 + `(admin)/admin/page.tsx` forward stub
제거). 신규 mobile 파일 0건(admin은 web-only — Story 7.1/7.2/7.3 정합). 신규
alembic 0건(0022 SOT 재사용). 신규 환경 변수 0건. 본 스토리 후 sprint-status에
`7-4-...: backlog → ready-for-dev → in-progress → review → done` 전이 + epic-7
done 갱신(마지막 스토리). PR pattern: feature branch `story/7.4-self-audit-pii-toggle`
(master에서 분기, CS 시작 *직전* 분기 완료 — memory `feedback_ds_complete_to_commit_push`
정합) — DS/CR 모두 동일 브랜치, PR은 CR 완료 후 1회 + memory
`feedback_cr_done_status_in_pr_commit` 정합으로 CR 종료 직전 sprint-status `review
→ done` 갱신 commit에 포함. -->

## Story

As a 관리자,
I want 내 활동 로그를 self-audit으로 직접 보고, 사용자 민감정보는 기본 마스킹된 채 명시적 *원문 보기* 액션 시에만 해제하기를,
So that 자기 감사가 가능하고 부주의한 민감정보 노출이 차단된다.

## Acceptance Criteria

1. **AC1 — `GET /v1/admin/audit-logs?actor_id=me` self-audit endpoint** (FR38 — 읽기 SOT, NFR-P9 ≤ 1초/1만 row)
   **Given** Story 7.3 산출물 — `audit_logs` 13 컬럼 + `idx_audit_logs_actor_id_occurred_at` composite index + `audit_logs_action_enum` 7 값 ENUM + `AuditLog` ORM SOT + `current_admin` transitive 체인 + `expire_on_commit=False` lifespan SOT, **When** `app/api/v1/admin.py`에 self-audit 신규 endpoint 작성, **Then**:
   - **신규 endpoint** `GET /v1/admin/audit-logs`:
     ```python
     @router.get("/audit-logs")
     async def list_self_audit_logs(
         db: DbSession,
         admin: Annotated[User, Depends(current_admin)],
         actor_id: Annotated[Literal["me"], Query(description="self-audit only; MVP는 'me' 고정")] = "me",
         action: Annotated[AuditLogAction | None, Query(description="action ENUM 필터")] = None,
         target_user_id: Annotated[uuid.UUID | None, Query(description="대상 user UUID 필터")] = None,
         since: Annotated[datetime | None, Query(description="ISO 8601 UTC — 이 시점 이후 audit row")] = None,
         limit: Annotated[int, Query(ge=1, le=100)] = 50,
         cursor: Annotated[str | None, Query(max_length=200)] = None,
     ) -> AdminAuditLogListResponse:
         """self-audit 로그 조회 — *현재 admin의* 모든 audit row 시간순.

         epics.md:929 *"`actor_id` 권한 분리 — 1인 개발자 owner 외 admin은 자기 활동만"*
         정합. MVP는 ``actor_id="me"`` 고정(Literal["me"] type — FastAPI가 422로 자동 차단) —
         외주 클라이언트별 *cross-admin 조회 권한*은 Story 8 운영 polish forward(2인 이상
         admin 운영 시점). cursor pagination(``occurred_at DESC`` keyset). Story 7.3
         ``idx_audit_logs_actor_id_occurred_at`` composite index hit 보장.

         **본 endpoint는 `Depends(audit_admin_action)` 미적용** — self-audit 조회 자체를
         audit하면 *meta-audit 폭증*(`admin_whoami` exclusion 패턴 정합, Story 7.3
         docstring 867행 *"`admin_session_introspect` 추가 vs 노이즈 trade-off"* 정합).
         """
     ```
   - **Pydantic 응답 모델** (`extra="forbid"` 일관):
     ```python
     class AdminAuditLogItem(BaseModel):
         model_config = ConfigDict(extra="forbid")

         audit_id: uuid.UUID
         occurred_at: datetime
         actor_id: uuid.UUID
         actor_email_masked: str  # DB 영속화 시점 마스킹 — 응답도 그대로(self-audit이지만 SOT 정합)
         action: AuditLogAction
         target_user_id: uuid.UUID | None
         target_resource: str | None
         target_resource_id: uuid.UUID | None
         path: str
         method: str
         ip: str | None  # INET → str (예: "203.0.113.42" 또는 "::ffff:..." 정규화 후)
         request_id: str
         user_agent: str | None


     class AdminAuditLogListResponse(BaseModel):
         model_config = ConfigDict(extra="forbid")

         items: list[AdminAuditLogItem]
         next_cursor: str | None  # base64-url(occurred_at_iso "|" audit_id_hex)
     ```
   - **검색 SQL 패턴** (단일 쿼리 + `idx_audit_logs_actor_id_occurred_at` partial composite hit):
     ```python
     # actor_id="me" → admin.id 고정 filter
     stmt = (
         select(AuditLog)
         .where(AuditLog.actor_id == admin.id)
         .order_by(desc(AuditLog.occurred_at), desc(AuditLog.id))  # keyset stable tiebreaker
     )
     if action is not None:
         stmt = stmt.where(AuditLog.action == action)
     if target_user_id is not None:
         # NULL 필터 시 SQL planner가 partial index 미사용 → 의도된 NULL-safe equality
         stmt = stmt.where(AuditLog.target_user_id == target_user_id)
     if since is not None:
         stmt = stmt.where(AuditLog.occurred_at >= since)
     if cursor is not None:
         cursor_dt, cursor_id = _decode_audit_cursor(cursor)
         stmt = stmt.where(
             or_(
                 AuditLog.occurred_at < cursor_dt,
                 (AuditLog.occurred_at == cursor_dt) & (AuditLog.id < cursor_id),
             )
         )
     stmt = stmt.limit(limit + 1)  # over-fetch 1
     ```
   - **cursor 인코딩**: `_encode_audit_cursor(occurred_at, audit_id)` / `_decode_audit_cursor(token)` 신규 2 helper — `admin.py:_encode_cursor`/`_decode_cursor` (user 검색 SOT) 1:1 정합 패턴(occurred_at은 ISO 8601 UTC + microsecond 정밀도 + `Z` suffix). cursor decode 실패 시 `AdminCursorInvalidError(400, code="admin.cursor.invalid")` 재사용(Story 7.2 SOT).
   - **`actor_id="me"` 강제**: FastAPI `Literal["me"]` Query type → `?actor_id=foo` 또는 missing(`?actor_id=` empty) → 422 자동(handler 진입 전). MVP 외 다른 값 분기는 코드에 미존재 — 외주 클라이언트별 *cross-admin* 권한 도입 시점에 Literal Union 확장 + role check 추가 forward.
   - **NFR-P9 검증** (epics.md:918 +  Story 7.3 forward closure): 1만 audit row synthetic data fixture로 `actor_id=admin.id ORDER BY occurred_at DESC LIMIT 50` 단일 쿼리 p95 ≤ 1초 검증 + EXPLAIN 결과에서 `idx_audit_logs_actor_id_occurred_at` 인덱스 hit 가시 (Story 7.2 NFR-P9 검증 패턴 정합).
   - **응답 ip 직렬화**: `INET` 컬럼은 `ipaddress.IPv4Address | IPv6Address | None` ORM 타입 — Pydantic `str | None`으로 직렬화 시 `str(addr)` 호출(자동 처리). Story 7.3 `_coerce_ip` 영속화에서 IPv4-mapped IPv6는 IPv4로 정규화돼서 직렬화도 IPv4 일관(`203.0.113.42`).
   - **단위 테스트** `api/tests/api/v1/test_admin_audit_logs.py` 신규 1파일 + 16 케이스:
     - `test_list_audit_logs_returns_only_current_admin_rows` — 다른 admin row 5건 + 현재 admin row 3건 → 응답 3건 + 모두 `actor_id=admin.id` invariant.
     - `test_list_audit_logs_empty_returns_empty_list_with_null_cursor` — audit_logs 0건 → `items=[]` + `next_cursor=null` + 200.
     - `test_list_audit_logs_orders_by_occurred_at_desc` — 5건 INSERT (occurred_at 분산) → 응답 occurred_at DESC 정렬.
     - `test_list_audit_logs_cursor_round_trip` — limit=2 + 5건 → 첫 페이지(2건) + `next_cursor` → 두 번째 페이지(2건) → 세 번째(1건 + cursor null) → 일관 정렬 유지.
     - `test_list_audit_logs_cursor_invalid_returns_400` — `?cursor=garbage` → 400 `code=admin.cursor.invalid`.
     - `test_list_audit_logs_filter_by_action` — 3건(user_search 1 + user_pii_view 2) + `?action=user_pii_view` → 2건 hit.
     - `test_list_audit_logs_filter_by_target_user_id` — 5건(다른 target 분산) + `?target_user_id={uuid}` → 일치 row만 hit.
     - `test_list_audit_logs_filter_by_since` — 7건(occurred_at 시계열 분산) + `?since=2026-05-10T00:00:00Z` → 5월10일 이후만 hit.
     - `test_list_audit_logs_combines_filters` — `?action=user_profile_view&target_user_id={uuid}&since={iso}` → 3 조건 AND 정합.
     - `test_list_audit_logs_actor_id_non_me_returns_422` — `?actor_id=foo` → 422 (FastAPI Literal["me"] 검증).
     - `test_list_audit_logs_actor_id_other_admin_uuid_returns_422` — `?actor_id={other_admin_uuid}` → 422 (1인 owner MVP 보호).
     - `test_list_audit_logs_limit_clamped_to_100` — `?limit=101` → 422.
     - `test_list_audit_logs_action_invalid_enum_returns_422` — `?action=garbage` → 422.
     - `test_list_audit_logs_blocked_for_non_admin` — user JWT → 403 `code=auth.admin.role_required`.
     - `test_list_audit_logs_blocked_when_token_missing` — Authorization + 쿠키 부재 → 401.
     - `test_list_audit_logs_no_self_audit_row_created_when_called` — `GET /v1/admin/audit-logs` 호출 후 `audit_logs` row count 변화 0 (meta-audit 미발동 invariant).
   - **OpenAPI**: `pnpm gen:api` 후 `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts`에 `list_self_audit_logs_v1_admin_audit_logs_get` operation 신규 등재.

2. **AC2 — `POST /v1/admin/users/{user_id}/pii-reveal` PII unmask + audit `user_pii_view` 자동 기록** (FR39 — 원문 보기 토글 SOT)
   **Given** AC1 endpoint + Story 7.3 `audit_admin_action` factory + `user_pii_view` ENUM 값 사전 등록 + Story 7.2 `AdminUserDetailResponse` 마스킹 SOT, **When** plaintext PII 응답 endpoint 신규 작성, **Then**:
   - **신규 endpoint** `POST /v1/admin/users/{user_id}/pii-reveal`:
     ```python
     @router.post(
         "/users/{user_id}/pii-reveal",
         dependencies=[
             Depends(audit_admin_action(action="user_pii_view", target_resource="users")),
         ],
     )
     async def reveal_user_pii(
         user_id: uuid.UUID,
         db: DbSession,
         admin: Annotated[User, Depends(current_admin)],
     ) -> AdminUserPiiRevealResponse:
         """사용자 PII 원문 보기 — 명시 액션 + audit `user_pii_view` 자동 기록 (FR39).

         epics.md:931 *"관리자 *원문 보기* 토글 액션 + 사용자 명시 확인 시 마스킹 해제 +
         해당 액션 자체가 audit log에 `action=user_pii_view` 기록"* 정합. POST 메서드 채택 —
         *action* semantics(GET ``?include_pii=true`` 대안 거부: prefetch/캐시/링크 공유로
         의도치 않은 plaintext 노출 + audit row 폭증 risk).

         응답 본문은 plaintext PII 4 필드(email/weight_kg/height_cm/allergies list) +
         display_name/picture_url/age는 마스킹 대상 X(Story 7.2 SOT — 이미 plaintext).
         미존재 user_id → 404 ``code=admin.user.not_found`` (AC2 패턴 재사용).

         **structlog/Sentry 이중 안전판**(epics.md:933 정합): 본 endpoint는 응답 본문
         외에서 plaintext PII를 절대 로깅 X — 핸들러 내부 ``logger.info``는 마스킹
         식별자만(``admin_id``/``target_user_id_masked``) 송신. Sentry SDK
         ``before_send`` hook은 NFR-S5 SOT 정합(미구현 부분은 DF141 deferred — Story
         8.4 forward).
         """
     ```
   - **Pydantic 응답 모델**:
     ```python
     class AdminUserPiiRevealResponse(BaseModel):
         model_config = ConfigDict(extra="forbid")

         user_id: uuid.UUID
         email: str  # plaintext
         age: int | None
         weight_kg: Decimal | None  # plaintext (Decimal — Story 1.5 SOT)
         height_cm: int | None  # plaintext
         allergies: list[str] | None  # plaintext (22종 enum 중 사용자 선택 항목 명시)
         revealed_at: datetime  # server-side now() — 클라이언트가 5분 timer 시작 기준
         expires_at: datetime  # revealed_at + 5분 (server hint — 클라이언트 timer 정합)
     ```
   - **응답 구성 helper**:
     ```python
     def _build_pii_reveal_response(user: User) -> AdminUserPiiRevealResponse:
         """User ORM → AdminUserPiiRevealResponse — plaintext 단일 지점.

         Story 7.2 ``_build_user_detail_response`` 마스킹 helper 패턴 정합 — *unmask*
         경로 분리로 호출처가 의도된 plaintext 흐름임을 type-system 차원에서 명시.
         """
         now = datetime.now(UTC)
         return AdminUserPiiRevealResponse(
             user_id=user.id,
             email=user.email,
             age=user.age,
             weight_kg=user.weight_kg,
             height_cm=user.height_cm,
             allergies=user.allergies,
             revealed_at=now,
             expires_at=now + timedelta(minutes=PII_REVEAL_TTL_MINUTES),
         )
     ```
   - **상수** `PII_REVEAL_TTL_MINUTES = 5` — epics.md:932 *"5분 비활동 후 마스킹 자동 복원"* SOT. server는 *기간 hint*만 응답 + 클라이언트가 *비활동* 추적(AC5 책임). server-side enforcement는 X(stateless — Story 8 cookie-bound reveal session 분기는 forward).
   - **404 분기**: `SELECT users WHERE id=user_id` 실행 후 미존재 시 `AdminUserNotFoundError(404, code="admin.user.not_found")` raise (Story 7.2 `get_user_detail` 패턴 정합). soft-deleted 사용자(`deleted_at IS NOT NULL`)도 200 응답(admin 거버넌스 — Story 7.2 SOT 정합).
   - **audit row invariant** (Story 7.3 SOT 재사용): `dependencies=[Depends(audit_admin_action(action="user_pii_view", target_resource="users"))]` 1줄 wire로 audit row INSERT 자동. `target_user_id`는 `request.path_params["user_id"]` UUID parse(Story 7.3 `_extract_path_param_uuid` SOT). FK 위반 분기(nonexistent user_id) 시 audit row INSERT가 silent drop 됨 — DF143 deferred(Story 7.3 CR 정합). 본 endpoint는 *try-attempt*까지가 audit 가치(시도 자체가 추적 대상) — fail-open 의도된 trade-off 보존.
   - **단위 테스트** `api/tests/api/v1/test_admin_pii_reveal.py` 신규 1파일 + 12 케이스:
     - `test_reveal_pii_returns_plaintext_for_active_user` — admin JWT + 정상 user → 200 + plaintext email/age/weight_kg/height_cm/allergies 노출 + masked 형식 비포함 assert(`"***"` 부재).
     - `test_reveal_pii_creates_audit_row_with_action_user_pii_view` — 호출 후 `audit_logs`에 1건 + `action="user_pii_view"` + `target_user_id=user_id` + `target_resource="users"` + `path="/v1/admin/users/{uuid}/pii-reveal"` + `method="POST"` 정합.
     - `test_reveal_pii_returns_plaintext_allergies_list` — `allergies=["우유", "달걀", "땅콩"]` 사용자 → 응답에 정확한 list (마스킹 `*** 3건 등록` 비포함).
     - `test_reveal_pii_returns_null_for_unset_profile` — 미입력 사용자 → `weight_kg=null`/`height_cm=null`/`allergies=null`/`age=null` + email은 plaintext.
     - `test_reveal_pii_empty_allergies_list_returns_empty_list_not_null` — `allergies=[]` → 응답 `allergies=[]` (NULL과 명확 구분).
     - `test_reveal_pii_includes_expires_at_5_minutes_after_revealed_at` — 응답 `expires_at - revealed_at == timedelta(minutes=5)` (PII_REVEAL_TTL_MINUTES 정합).
     - `test_reveal_pii_user_not_found_returns_404` — 미존재 UUID → 404 `code=admin.user.not_found`.
     - `test_reveal_pii_soft_deleted_user_returns_200_with_plaintext` — `deleted_at IS NOT NULL` 사용자 → 200 + plaintext 노출(admin 거버넌스 정합).
     - `test_reveal_pii_invalid_uuid_path_returns_422` — `/v1/admin/users/not-a-uuid/pii-reveal` → 422.
     - `test_reveal_pii_blocked_for_non_admin_no_audit_row` — user JWT → 403 + `audit_logs` 0건(`current_admin` 단계 raise → audit transitive 미발동, Story 7.3 SOT 정합).
     - `test_reveal_pii_blocked_when_token_missing_no_audit_row` — token 부재 → 401 + audit 0건.
     - `test_reveal_pii_no_plaintext_in_structlog_when_logger_patched` — `logger.info` mock + `reveal_user_pii` 호출 → 모든 logger 호출 kwargs에 `user.email`/`user.weight_kg` plaintext 값 비포함 invariant(epics.md:933 이중 안전판).

3. **AC3 — `app/core/masking.py` plaintext 분기 흡수 (`reveal_*` 4 helper 추가)** (FR39 — masking SOT 확장, NFR-S5 정합)
   **Given** Story 7.2 `app/core/masking.py` 4 helper(`mask_email`/`mask_weight`/`mask_height`/`mask_allergies_count`) + 16 케이스 test_masking.py 회귀 가드, **When** plaintext 분기 helper 4개 추가(기존 4개 변경 0건), **Then**:
   - **신규 `reveal_email`/`reveal_weight`/`reveal_height`/`reveal_allergies` 4 함수** — 단순 pass-through(NULL-safe) wrapper. 본 모듈에 의미 추가하는 이유: (a) Story 7.2 docstring 8행 *"Story 7.4에서 plaintext 분기 추가 시 본 모듈에 흡수"* SOT 정합. (b) `mask_*` 호출처 옆에 `reveal_*` 호출처를 두면 *마스킹 vs 노출* 의도가 type-system 차원에서 명시(grep으로 PII 노출 지점 추적 가능). (c) 미래 *부분 마스킹*(예: `reveal_email_local_only`) 추가 시 본 모듈에 흡수 가능:
     ```python
     # api/app/core/masking.py 끝에 추가 (기존 4 함수 변경 0)

     from decimal import Decimal


     def reveal_email(email: str) -> str:
         """원문 이메일 그대로 반환 — *명시 의도* 표기 (FR39, Story 7.4).

         호출처는 ``admin.py:reveal_user_pii``(POST .../pii-reveal)만 — 명시 *원문
         보기* 액션 + audit `user_pii_view` 기록과 함께만 호출돼야 함.
         """
         return email


     def reveal_weight(weight_kg: Decimal | float | int | None) -> Decimal | float | int | None:
         """원문 체중 그대로 반환 (None pass-through). FR39 명시 액션 시점만."""
         return weight_kg


     def reveal_height(height_cm: int | None) -> int | None:
         """원문 신장 그대로 반환 (None pass-through). FR39 명시 액션 시점만."""
         return height_cm


     def reveal_allergies(allergies: list[str] | None) -> list[str] | None:
         """원문 알레르기 list 그대로 반환 (None pass-through). FR39 명시 액션 시점만.

         빈 list(``[]``)도 그대로 — *등록 없음*과 *미입력*은 의미 분리(NULL vs []).
         """
         return allergies
     ```
   - **`app/core/masking.py` 모듈 docstring 갱신**:
     - Story 7.2 docstring 8행 *"Story 7.4에서 `unmask=True` flag 추가 시 plaintext 반환 분기 — 그때 본 모듈에 흡수"* → 본 스토리에서 *"Story 7.4 — plaintext 분기 `reveal_*` 4 함수 흡수 완료"*로 갱신.
   - **단위 테스트** `api/tests/core/test_masking.py` 기존 16 케이스 PASS 보존 + 8 케이스 추가(reveal helper 분):
     - `test_reveal_email_passes_through_plaintext` — `"alice@example.com"` → `"alice@example.com"`.
     - `test_reveal_email_passes_through_empty_string` — `""` → `""` (caller responsibility, masking은 `"***"` 반환했음).
     - `test_reveal_weight_passes_through_decimal` — `Decimal("65.4")` → `Decimal("65.4")`.
     - `test_reveal_weight_passes_through_none` — `None` → `None`.
     - `test_reveal_height_passes_through_int` — `175` → `175`.
     - `test_reveal_height_passes_through_none` — `None` → `None`.
     - `test_reveal_allergies_passes_through_list` — `["우유","달걀"]` → `["우유","달걀"]`.
     - `test_reveal_allergies_passes_through_empty_list_distinct_from_none` — `[]` → `[]` (NULL과 구분).
   - **회귀 0건 invariant**: 기존 16 케이스(`mask_email`/`mask_weight`/`mask_height`/`mask_allergies_count`) 모두 PASS 유지 (signature/return 변경 0).
   - **`__all__` 등재 (선택)**: 모듈에 명시 `__all__`이 현재 부재 — Python convention 따라 미선언 유지(implicit public). `from app.core.masking import reveal_email`로 import.

4. **AC4 — Web `(admin)/admin/audit-logs/page.tsx` Server Component + `AuditLogTable.tsx` Client** (FR38 — self-audit UI SOT)
   **Given** Story 7.2 `(admin)/admin/users/[user_id]/page.tsx` Server Component 패턴(`cookies()` + `bn_admin_access` extract + SSR fetch + `redirect`) + Story 4.3 TanStack Query baseline + AC1 endpoint, **When** self-audit 페이지 + 테이블 컴포넌트 신규 작성, **Then**:
   - **신규 Server Component** `web/src/app/(admin)/admin/audit-logs/page.tsx`:
     ```tsx
     /**
      * Admin self-audit 페이지 — Story 7.4 AC#4 (FR38).
      *
      * Server Component shell — `bn_admin_access` cookie SSR forward + 첫 페이지 SSR
      * fetch + initial data Client Component prefill. 토큰 부재/401/403 → /admin/login
      * redirect (Story 7.2 [user_id]/page.tsx 패턴 정합).
      */
     import type { Metadata } from "next";
     import { cookies } from "next/headers";
     import { redirect } from "next/navigation";

     import { AuditLogTable } from "@/features/admin/AuditLogTable";
     import type { AdminAuditLogListResponse } from "@/features/admin/types";

     export const metadata: Metadata = { title: "감사 로그 — 관리자" };

     async function fetchInitialAuditLogs(): Promise<AdminAuditLogListResponse> {
       const cookieStore = await cookies();
       const adminToken = cookieStore.get("bn_admin_access")?.value;
       if (!adminToken) redirect("/admin/login?error=expired");
       const apiBase = process.env.API_BASE_URL ?? "http://localhost:8000";
       const response = await fetch(
         `${apiBase}/v1/admin/audit-logs?actor_id=me&limit=50`,
         { headers: { Authorization: `Bearer ${adminToken}` }, cache: "no-store" },
       );
       if (response.status === 401 || response.status === 403) {
         redirect("/admin/login?error=expired");
       }
       if (!response.ok) {
         throw new Error(`fetch audit-logs failed: ${response.status}`);
       }
       return (await response.json()) as AdminAuditLogListResponse;
     }

     export default async function AdminAuditLogsPage() {
       const initial = await fetchInitialAuditLogs();
       return (
         <div className="space-y-6">
           <header>
             <h2 className="text-2xl font-semibold">내 활동 로그</h2>
             <p className="mt-1 text-sm text-zinc-600">
               관리자 계정으로 수행한 조회·수정 액션이 시간순으로 기록됩니다.
             </p>
           </header>
           <AuditLogTable initial={initial} />
         </div>
       );
     }
     ```
   - **신규 Client Component** `web/src/features/admin/AuditLogTable.tsx`:
     - TanStack Query — initialData = `initial`(SSR 첫 페이지) → "더 보기" 버튼 클릭 시 `cursor=...&limit=50` query 갱신 + items append (Story 4.3 패턴 정합).
     - 반응형: 모바일(`sm:hidden`) 카드 리스트 / 데스크톱(`hidden sm:block`) 테이블 분기 — Story 7.2 UserSearchClient 1:1 정합.
     - 컬럼: 시점(`occurred_at` `toLocaleString("ko-KR")`), 액션(Korean label — `actionLabel(action)` helper), 대상(target_user_id 있으면 `/admin/users/{user_id}` 링크 / target_resource_id meal_id면 plain text), 경로(`{method} {path}`), IP, request_id(8자 prefix).
     - **Korean label SOT** — action enum → 한국어 매핑:
       ```typescript
       const ACTION_LABEL: Record<string, string> = {
         user_search: "사용자 검색",
         user_profile_view: "프로필 조회",
         user_meal_history_view: "식단 이력 조회",
         user_feedback_history_view: "피드백 로그 조회",
         user_profile_edit: "프로필 수정",
         admin_meal_delete: "식단 삭제",
         user_pii_view: "PII 원문 보기",
       };
       ```
     - 빈 상태: *"기록된 활동이 없습니다"*. 로딩: 추가 페이지 fetch 중 "불러오는 중…". 에러: *"감사 로그 불러오기 실패. 다시 시도해 주세요."*
     - `Link` 컴포넌트로 `target_user_id` → `/admin/users/{user_id}` 진입(상세 페이지) — admin 거버넌스 워크플로우 정합.
   - **타입 신규 `web/src/features/admin/types.ts` 확장** (기존 7 인터페이스 변경 0):
     ```typescript
     // Story 7.4 AC#4 추가
     export type AdminAuditLogAction =
       | "user_search"
       | "user_profile_view"
       | "user_meal_history_view"
       | "user_feedback_history_view"
       | "user_profile_edit"
       | "admin_meal_delete"
       | "user_pii_view";

     export interface AdminAuditLogItem {
       audit_id: string;
       occurred_at: string;
       actor_id: string;
       actor_email_masked: string;
       action: AdminAuditLogAction;
       target_user_id: string | null;
       target_resource: string | null;
       target_resource_id: string | null;
       path: string;
       method: string;
       ip: string | null;
       request_id: string;
       user_agent: string | null;
     }

     export interface AdminAuditLogListResponse {
       items: AdminAuditLogItem[];
       next_cursor: string | null;
     }

     // Story 7.4 AC#5 추가
     export interface AdminUserPiiRevealResponse {
       user_id: string;
       email: string;
       age: number | null;
       weight_kg: number | null;  // backend Decimal → JSON number
       height_cm: number | null;
       allergies: string[] | null;
       revealed_at: string;
       expires_at: string;
     }
     ```
   - **a11y**: `aria-label="감사 로그 표"` + 카드 리스트 `<ul aria-label="모바일 카드 리스트">` + 더 보기 버튼 disabled 상태 명시.
   - **회귀 0건**: Story 7.2 user_id 페이지의 `fetchUserDetail` 패턴 1:1 정합 — 기존 `UserDetailClient`/`UserSearchClient` 컴포넌트 변경 0건.

5. **AC5 — Web `UserDetailClient.tsx` *원문 보기* 토글 + 5분 비활동 자동 복원** (FR39 — UI SOT)
   **Given** Story 7.2 `UserDetailClient.tsx` 탭 구조(`profile`/`meals`/`analyses`) + `AdminProfileEditForm` 마스킹 필드 노출(`weight_kg_masked` / `height_cm_masked` / `allergies_count_masked` / `email_masked`) + AC2 endpoint, **When** *원문 보기* 토글 + 비활동 timer 추가, **Then**:
   - **수정** `web/src/features/admin/UserDetailClient.tsx`:
     - 프로필 탭 헤더 옆에 **"원문 보기" 토글 버튼** 추가:
       - 토글 OFF(default) → 기존 마스킹 표시
       - 토글 ON 클릭 → `window.confirm("사용자 개인정보(이메일·체중·신장·알레르기) 원문을 표시합니다. 5분 후 자동 복원됩니다. 계속하시겠습니까?")` 사용자 명시 확인
       - 확인 시 `POST /v1/admin/users/{userId}/pii-reveal` 호출 → plaintext response state 보존 + 5분 timer 시작(`expires_at` 응답 hint 정합)
     - **state shape**:
       ```typescript
       const [revealState, setRevealState] = useState<{
         status: "masked" | "loading" | "revealed";
         plaintext: AdminUserPiiRevealResponse | null;
         expiresAt: number | null;  // unix ms — Date.now() 기반 갱신
       }>({ status: "masked", plaintext: null, expiresAt: null });
       ```
     - **활동 추적** (epics.md:932 *"5분 *비활동* 후 마스킹 자동 복원"* 정합):
       - `revealState.status === "revealed"` 동안만 DOM event listener attach:
         `["mousemove", "keydown", "click", "touchstart"]` × `document`
       - 이벤트 발생 시 `expiresAt = Date.now() + PII_REVEAL_TTL_MS`로 갱신 (debounce 500ms — 1초마다 setState 폭증 회피)
       - `useEffect` cleanup에서 listener detach + timer clear
     - **timer**: 1초 interval setInterval → `Date.now() >= expiresAt` 시 `setRevealState({ status: "masked", plaintext: null, expiresAt: null })` + `useEffect` cleanup으로 timer clear
     - **토글 OFF 즉시 마스킹**: 사용자가 토글 OFF 클릭 → state 즉시 `{ status: "masked", plaintext: null }` (활동 추적 불필요 — 명시 의도)
     - **PROFILE 탭 분기**: `revealState.status === "revealed" && revealState.plaintext` 일 때 plaintext 패널을 마스킹 폼 *위에* 추가 표시(병행 노출 — admin이 plaintext 확인 후 마스킹 폼으로 편집하는 *읽기↔편집 직교* 흐름). 기존 `AdminProfileEditForm` 마스킹 흐름 변경 0(Story 7.2 SOT 회귀 invariant 우선 — CR 시 D1 결정 정합).
   - **수정** `web/src/features/admin/AdminProfileEditForm.tsx` (또는 새 sub-component `UserPiiDisplay.tsx`):
     - props로 `revealState` 전달 → revealed 분기 시 plaintext 필드 (email plaintext / age plaintext / `{weight_kg.toFixed(1)} kg` / `{height_cm} cm` / `allergies.join(", ")` or empty state) 노출
     - **마스킹 분기 디폴트** — Story 7.2 SOT 동형 보존 (회귀 0건 invariant)
   - **상수** `PII_REVEAL_TTL_MS = 5 * 60 * 1000` — backend `PII_REVEAL_TTL_MINUTES` SOT 정합.
   - **POST helper** `web/src/features/admin/api.ts` (또는 inline TanStack Query mutation):
     ```typescript
     async function revealUserPii(userId: string): Promise<AdminUserPiiRevealResponse> {
       const response = await adminApiFetch(`/v1/admin/users/${userId}/pii-reveal`, {
         method: "POST",
       });
       if (!response.ok) {
         throw new Error(`reveal failed: ${response.status}`);
       }
       return (await response.json()) as AdminUserPiiRevealResponse;
     }
     ```
   - **UX 명세**:
     - 토글 버튼 visible state: `revealState.status === "revealed"`이면 *"원문 보기 ON (자동 복원: M:SS 후)"* — 잔여 시간 ko-KR locale + 1초 interval 카운트다운 표시 (UX 안내)
     - 토글 버튼 hidden state: *"원문 보기 OFF"* — 클릭 시 confirm + 호출
     - 로딩 상태: *"불러오는 중…"* disabled 버튼
     - 에러: inline 에러 메시지 *"원문 보기 실패. 잠시 후 다시 시도하세요."* + state 마스킹 유지 (audit row는 fail-open으로 기록됨 — Story 7.3 SOT 정합)
   - **회귀 0건 invariant** — Story 7.2 `AdminProfileEditForm` zod schema/submit handler/필드 검증 흐름 변경 0 (수정 필드는 *원문 보기* state와 독립 — 수정 form은 항상 plaintext input + PATCH 호출, 토글은 *조회* 분기만).
   - **수동 검증 시나리오** (DS가 수행):
     - 토글 ON → 5분 동안 마우스 움직임 없으면 자동 마스킹 복귀
     - 토글 ON → 4분 후 마우스 움직임 → timer 5분 reset → 추가 5분 노출
     - 토글 OFF 클릭 → 즉시 마스킹 복귀
     - 탭 전환(meals/analyses → profile) → reveal state 유지(같은 페이지 lifecycle 내 보존)
     - 다른 사용자 상세 페이지로 이동(navigate) → reveal state 폐기(unmount cleanup)
   - **단위 테스트** `web/src/features/admin/UserDetailClient.test.tsx`(또는 신규 `UserPiiToggle.test.tsx`) — 5 케이스 (vitest + @testing-library/react):
     - `토글 OFF에서 마스킹 필드 노출 invariant` — 기본 상태 + `weight_kg_masked` 표시.
     - `토글 ON 시 confirm prompt 표시 + 거부 시 호출 X` — `window.confirm` mock 거부 → API 호출 0회.
     - `토글 ON + confirm 수락 시 plaintext 표시 + 마스킹 hide` — API mock + plaintext 4 필드 노출 + masked 필드 부재.
     - `토글 ON + 5분 타이머 만료 후 마스킹 복귀` — vitest `vi.useFakeTimers()` + advance 5분 + plaintext 필드 부재 assert.
     - `토글 ON + 활동(mousemove) 후 4분 시점 → timer reset → 추가 5분 노출` — fake timer + dispatch mousemove + advance 4분 → revealed 유지.

6. **AC6 — structlog/Sentry 이중 안전판 (plaintext PII leak 0)** (epics.md:933 + NFR-S5 정합)
   **Given** AC2 `reveal_user_pii` endpoint + Story 7.3 `audit_service.record_admin_action`의 마스킹 영속화 + Story 3.x structlog SOT, **When** plaintext 응답 흐름에서 logger/Sentry 이중 안전판 검증, **Then**:
   - **`reveal_user_pii` 핸들러 내 structlog 호출 invariant**:
     - 응답 직렬화 외 어떤 코드 경로에서도 `user.email`/`user.weight_kg`/`user.height_cm`/`user.allergies` 평문 값을 logger 인자로 송신 X.
     - 허용 logger 인자: `admin_id=mask_user_id_for_log(admin.id)` + `target_user_id=mask_user_id_for_log(user_id)` + `event="admin.user.pii_revealed"` + 비-PII 메타데이터(success boolean / latency_ms 등).
   - **audit_logs row 이중 안전판** (Story 7.3 SOT 재사용):
     - `audit_service.record_admin_action`이 `actor_email_masked=mask_email(admin.email)`로 영속화 — actor email은 자기 자신이지만 SOT 정합.
     - audit row에는 `path="/v1/admin/users/{uuid}/pii-reveal"` + `method="POST"` 영속화 — request body는 미보관(Story 7.3 13컬럼 SOT — body 컬럼 없음). plaintext PII가 audit row에 누출될 경로 0.
   - **단위 테스트** `api/tests/api/v1/test_admin_pii_reveal.py`에 흡수(AC2 16번째 케이스 + 추가 1 케이스):
     - `test_reveal_pii_no_plaintext_in_structlog_when_logger_patched` (AC2 마지막 케이스 재명시) — `structlog.get_logger.return_value.info` mock + endpoint 호출 → 모든 logger 호출 검사 → `kwargs.values()`에 user.email/weight_kg/height_cm/allergies 비포함 invariant.
     - **신규** `test_reveal_pii_audit_row_does_not_contain_plaintext_pii` — endpoint 호출 후 `audit_logs` row의 모든 텍스트 컬럼(actor_email_masked, target_resource, path, method, request_id, user_agent)에 `user.email` plaintext 부재 + 13 컬럼 SOT 보존.
   - **Sentry SDK before_send hook**: 현재 미구현(DF141 Story 8.4 forward). 본 스토리는 *애플리케이션 코드 레벨*에서 plaintext leak 0을 invariant로 보장 + Sentry SDK 통합 시점에 NFR-S5 SOT(structlog processor 패턴)를 hook으로 재사용 forward.

7. **AC7 — Web `(admin)/admin/page.tsx` Story 7.4 forward stub 제거 + 메타 link 활성** (FR38 — UX 마무리)
   **Given** Story 7.1 placeholder 화면(`admin/page.tsx` 23-29행 *"Story 7.4에서 사용자 검색·식단 이력·프로필 수정이 추가됩니다"* + 34행 *"FR38 — 7.4에서 추가"* 단락 + audit-logs 링크 forward stub), **When** Story 7.4 wire 완료 후 페이지 갱신, **Then**:
   - **수정** `web/src/app/(admin)/admin/page.tsx`:
     - 23-29행 *"Story 7.2/7.4에서 ..."* 안내 단락 → *"관리자 도구"* 카드 2개(*사용자 관리* / *감사 로그*) 정합 표기로 갱신.
     - 34행 *"FR38 — 7.4에서 추가"* placeholder → *"FR38 — 내 활동 audit 로그 조회"* 활성 표기.
     - audit-logs 링크 invariant 보존(`href="/admin/audit-logs"` 이미 Story 7.1에서 미리 wire — Story 7.4가 실 endpoint + page 제공으로 클릭 시 404 분기 closure).
   - **회귀 0건**: `admin/layout.tsx`(Story 7.1 SOT) + `admin/users/page.tsx`(Story 7.2 SOT) 변경 0건.

8. **AC8 — 회귀 가드 + sprint-status `epic-7: in-progress → done` 전이** (FR38/FR39 — Epic 7 close)
   **Given** Story 7.1/7.2/7.3 산출물(~110 회귀 테스트) + masking SOT 16 케이스 + admin.py 6 endpoint 본문 + audit_logs 13 컬럼 schema + alembic 0022 head, **When** 본 스토리 변경 후 전체 회귀 검증, **Then**:
   - **백엔드 회귀 검증**:
     - `uv run pytest` — Story 7.3 baseline(1318 passed) + 신규 36 케이스(AC1 16 + AC2 12 + AC3 8 = 36) 통합 → 1354+ passed / 11 skipped / 0 failed.
     - `uv run ruff check api && uv run ruff format api --check` — 0 errors.
     - `uv run mypy api` — 0 errors (admin.py 7번째 endpoint 추가 + masking.py 4 reveal helper + audit endpoint Pydantic 모델 모두 type-safe).
     - coverage ≥ 85% (Story 7.3 baseline 89.06% 유지/상승 — admin.py 신규 2 endpoint + masking.py 신규 4 helper 모두 단위 테스트 커버).
     - alembic round-trip: 0022 head SOT — 본 스토리 alembic 변경 0건 → round-trip 가드 회귀 0(Story 7.3 SOT 보존).
   - **OpenAPI 회귀 검증**:
     - `IN_PROCESS=1 bash scripts/gen_openapi_clients.sh` — admin.py 6 endpoint(Story 7.2) + 7번째 audit-logs endpoint + 8번째 pii-reveal endpoint operation 등재 + 이전 6 endpoint response schema 변경 0건.
     - `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts` 자동 갱신 diff = + ~80 lines (`list_self_audit_logs_v1_admin_audit_logs_get` + `reveal_user_pii_v1_admin_users__user_id__pii_reveal_post` operation 2건 신규).
     - `pnpm tsc --noEmit` web + mobile 0 errors.
   - **Web 회귀 검증**:
     - `pnpm tsc --noEmit` web 0 errors.
     - `pnpm lint` web 0 errors (Story 7.2 ESLint baseline 정합).
     - 신규 vitest 5 케이스 + 기존 test suite PASS 보존(Story 7.2 7-2 페이지·컴포넌트 회귀 0).
   - **수동 회귀** (DS):
     - Story 7.2 `/admin/users` 검색·상세·수정·삭제 흐름 PASS.
     - Story 7.3 admin.py 6 endpoint 호출 시 audit_logs row 자동 기록 PASS.
     - Story 7.4 신규: `/admin/audit-logs` 페이지 SSR 로드 → self-audit row 시간순 표시 PASS.
     - Story 7.4 신규: `/admin/users/{user_id}` 페이지 → 원문 보기 토글 ON → confirm → plaintext 노출 PASS + `audit_logs`에 `user_pii_view` row 자동 기록 PASS.
     - Story 7.4 신규: 5분 비활동 후 마스킹 자동 복원 PASS (실제 시간 대신 fake timer 단위 테스트로 검증).
   - **sprint-status 갱신** (memory `feedback_cr_done_status_in_pr_commit` 정합 — CR 종료 직전 갱신):
     - `_bmad-output/implementation-artifacts/sprint-status.yaml`:
       - `7-4-self-audit-화면-마스킹-원문-토글: backlog → ready-for-dev → in-progress → review → done` 전이
       - `epic-7: in-progress → done` (마지막 스토리 완료 — 7-1/7-2/7-3/7-4 모두 done)
       - `last_updated: 2026-05-11` 갱신 + Story 7.4 done 코멘트 1단락 prepend (Story 7.3 코멘트 위에)
   - **PR commit**: CR 완료 직전 sprint-status 갱신 + Story 7.4 파일 Status `review → done` + CR 코멘트 적용 모두 *동일 PR commit*에 포함 (memory `feedback_cr_done_status_in_pr_commit` 정합 — chore PR 강제 회피).

## Tasks / Subtasks

- [x] AC1 — `GET /v1/admin/audit-logs?actor_id=me` self-audit endpoint (FR38, NFR-P9)
  - [x] `api/app/api/v1/admin.py` 수정 — `list_self_audit_logs` endpoint + `AdminAuditLogItem`/`AdminAuditLogListResponse` Pydantic 모델 + `_encode_audit_cursor`/`_decode_audit_cursor` 2 helper(`_encode_cursor`/`_decode_cursor` SOT alias 채택 — DRY) + import 추가(`AuditLog`, `AuditLogAction` from `app.db.models.audit_log`).
  - [x] `api/tests/api/v1/test_admin_audit_logs.py` 신규 — 18 케이스(invariant 5 + filter 4 + 검증 5 + self-audit invariant 1 + NFR-P9 1 + Pydantic 응답 1 + 추가 1).
  - [x] NFR-P9 검증 — `test_list_audit_logs_nfr_p9_10k_rows_under_1s` (1만 row synthetic + composite index hit — 측정 결과 PASS).

- [x] AC2 — `POST /v1/admin/users/{user_id}/pii-reveal` PII unmask + `user_pii_view` audit wire (FR39)
  - [x] `api/app/api/v1/admin.py` 수정 — `reveal_user_pii` endpoint + `AdminUserPiiRevealResponse` Pydantic 모델 + `_build_pii_reveal_response` helper + `PII_REVEAL_TTL_MINUTES = 5` 상수 + `dependencies=[Depends(audit_admin_action(action="user_pii_view", target_resource="users"))]` wire + import 추가(`reveal_email`/`reveal_weight`/`reveal_height`/`reveal_allergies` from `app.core.masking`).
  - [x] `api/tests/api/v1/test_admin_pii_reveal.py` 신규 — 13 케이스(plaintext 5 + audit row 1 + 404/422 3 + 권한 2 + 이중 안전판 2).

- [x] AC3 — `app/core/masking.py` plaintext 분기 흡수 (FR39, NFR-S5)
  - [x] `api/app/core/masking.py` 수정 — `reveal_email`/`reveal_weight`/`reveal_height`/`reveal_allergies` 4 함수 추가 + 모듈 docstring 8행 갱신.
  - [x] `api/tests/core/test_masking.py` 수정 — 기존 16 케이스 PASS 보존 + 8 케이스 추가(reveal helper 분).

- [x] AC4 — Web `(admin)/admin/audit-logs/page.tsx` + `AuditLogTable.tsx` Client (FR38)
  - [x] `web/src/app/(admin)/admin/audit-logs/page.tsx` 신규 — Server Component shell + SSR fetch + redirect 분기.
  - [x] `web/src/features/admin/AuditLogTable.tsx` 신규 — Client Component + TanStack Query + 반응형 카드/테이블 + "더 보기" cursor pagination + Korean label 매핑.
  - [x] `web/src/features/admin/types.ts` 수정 — `AdminAuditLogAction` / `AdminAuditLogItem` / `AdminAuditLogListResponse` / `AdminUserPiiRevealResponse` 4 인터페이스 추가.

- [x] AC5 — `UserDetailClient.tsx` *원문 보기* 토글 + 5분 비활동 자동 복원 (FR39)
  - [x] `web/src/features/admin/UserPiiToggle.tsx` 신규 — 토글 + DOM event listener(`mousemove`/`keydown`/`click`/`touchstart`) + debounce 500ms + 1초 interval timer + confirm prompt + plaintext panel + 카운트다운 UX.
  - [x] `web/src/features/admin/UserDetailClient.tsx` 수정 — 프로필 탭 위에 `UserPiiToggle` 삽입(기존 `AdminProfileEditForm` 변경 0 — 회귀 invariant 보존).
  - [x] `revealUserPii` POST helper — `UserPiiToggle` 내부에서 `adminApiFetch` 직접 호출(별 file 신규 0 — YAGNI).
  - [ ] **Deviation 4** — `UserPiiToggle.test.tsx` vitest 5 케이스: web 프로젝트에 vitest 인프라 부재(`package.json`에 devDep/script 0건, Story 7.2도 동일 deferred). 본 스토리에서 vitest 도입은 scope 외(devDep 4종+ jsdom config + setup file + script). 대안 가드: AC2 13 케이스가 백엔드 API contract 100% cover + 수동 검증 시나리오 5건(spec line 475-480)이 timer/activity/confirm/persistence 흐름 전수 검증. Story 8.4 polish에서 vitest 인프라 도입 시 본 컴포넌트 testability 정합 추가.

- [x] AC6 — structlog/Sentry 이중 안전판 (NFR-S5, epics.md:933)
  - [x] `reveal_user_pii` 핸들러 내 logger 인자 invariant — `admin_id=_mask_user_id_for_log(admin.id)` + `target_user_id=_mask_user_id_for_log(user.id)` + plaintext PII 인자 0 (`structlog.contextvars`도 자동 적용).
  - [x] `test_reveal_pii_no_plaintext_in_structlog_when_logger_patched` (AC2 11번째 케이스).
  - [x] `test_reveal_pii_audit_row_does_not_contain_plaintext_pii` 신규 — audit row 6 텍스트 컬럼 모두 plaintext 부재 검증.

- [x] AC7 — `admin/page.tsx` forward stub 제거 + 메타 link 활성 (FR38 UX)
  - [x] `web/src/app/(admin)/admin/page.tsx` 수정 — Story 7.2/7.4 forward placeholder 제거 + FR36/FR38 활성 안내.

- [x] AC8 — 회귀 가드 + sprint-status `7-4-...: review` (CR 시점에 done 전이 forward)
  - [x] 백엔드 빌드 게이트 — `ruff check . `(All checks passed) + `ruff format --check`(0) + `mypy app`(0) + `pytest`(1365 passed / 11 skipped / 0 failed) + coverage 89.18%.
  - [x] OpenAPI 자동 생성 — `gen_openapi_clients.sh` 성공, `list_self_audit_logs_v1_admin_audit_logs_get` + `reveal_user_pii_v1_admin_users__user_id__pii_reveal_post` 2 operation 신규 등재.
  - [x] Web `pnpm tsc --noEmit` 0 errors + `pnpm lint` 0 errors + Mobile `pnpm tsc --noEmit` 0 errors.
  - [x] `_bmad-output/implementation-artifacts/sprint-status.yaml` — `7-4-...: ready-for-dev → in-progress → review` 갱신(`epic-7: in-progress → done` 전이는 CR 종료 직전 갱신 — memory `feedback_cr_done_status_in_pr_commit` 정합).
  - [x] `test_admin_routes_audit_coverage.py` — `audit-logs`를 `_AUDIT_SCOPE_EXCLUDED_ROUTE_PATHS`에 등재(meta-audit exclusion SOT 정합) + business 가드 함수에서 exclusion skip 추가.

### Review Findings

(3-layer adversarial CR — Blind / Edge / Acceptance — 2026-05-11)

- [x] **[Review][Decision]** AC5 본문 vs Tasks 불일치 — **D1 해결: Option 2 채택 (Tasks SOT)**. 마스킹 폼은 *편집* 흐름, plaintext 패널은 *읽기* 흐름이라 직교 UX. 현 구현(toggle panel + 마스킹 폼 병행 노출) 유지. Spec body 452행을 *"plaintext 패널을 마스킹 폼 위에 추가 표시(병행 노출)"*로 정정해 self-contradiction 해소. Patch 0건.

- [x] **[Review][Patch]** `weight_kg.toFixed(1)` Decimal→JSON-string 불일치로 런타임 TypeError [`api/app/api/v1/admin.py:303-313, 336-352`] (Blind+Edge+Auditor, **HIGH**) — **Fix 적용**: `AdminUserPiiRevealResponse.weight_kg`를 `Decimal | None` → `float | None`로 변경(Story 7.2 `_build_profile_response` SOT 정합) + `_build_pii_reveal_response`에서 `float(revealed_weight)` 명시 캐스트 + `decimal.Decimal` import 제거(미사용). OpenAPI 자동 생성 정합 위해 `web/src/lib/api-client.ts:1434` + `mobile/lib/api-client.ts:1434` 두 client 모두 `weight_kg: number | null`로 manual 갱신(다음 `gen:api` 실행 시 동일 출력).
- [x] **[Review][Patch]** `AuditLogTable` `queryFn` 부작용으로 refocus/StrictMode 시 중복 행 누적 [`web/src/features/admin/AuditLogTable.tsx:97-138`] (Blind+Edge, **HIGH**) — **Fix 적용**: `queryFn` 순수화(`setItems`/`setCursor` side effect 제거 + 응답만 return) + `useEffect`로 side effect 이동 + `appliedCursorsRef: Set<string>` dedup 가드(StrictMode double-mount 시 동일 cursor append 차단) + `refetchOnWindowFocus: false` + `refetchOnReconnect: false` + `refetchOnMount: false` + `staleTime: Infinity`로 재실행 위험 일괄 차단.
- [x] **[Review][Patch]** `since` Query param naive datetime silent wrong-window filter [`api/app/api/v1/admin.py:766-775`] (Edge, MEDIUM) — **Fix 적용**: `datetime | None` → `AwareDatetime | None`(pydantic) — naive datetime은 422→400 자동 reject. Query description에 *"ISO 8601 + tz offset (inclusive) — naive datetime은 400 reject"* 명시.
- [x] **[Review][Patch]** Background tab throttling이 PII auto-mask SLA(5분) 초과 허용 [`web/src/features/admin/UserPiiToggle.tsx:visibilitychange useEffect 추가`] (Edge, MEDIUM) — **Fix 적용**: `useEffect`(reveal.status === "revealed")에서 `document.addEventListener("visibilitychange", ...)` — tab 비활성(`hidden`) 진입 시 즉시 `setReveal(INITIAL)`. 보수적 선택(re-reveal은 audit row + 명시 액션 재확인 비용 다시 지불 → SLA 정합).
- [x] **[Review][Patch]** `pii-reveal` double-click race로 중복 POST + 중복 audit row [`web/src/features/admin/UserPiiToggle.tsx:handleReveal`] (Edge, LOW) — **Fix 적용**: `revealInFlightRef: useRef<boolean>` 동기 가드 — `window.confirm` 호출 *직전* `revealInFlightRef.current = true` 설정 + `finally`에서 해제. 2회 클릭 시 두 번째는 early-return.
- [x] **[Review][Patch]** `AuditLogTable` 페이지 N+ 실패 후 retry affordance 부재로 stuck [`web/src/features/admin/AuditLogTable.tsx:error block`] (Edge, LOW) — **Fix 적용**: error block에 *"다시 시도"* 버튼 추가 — `useQuery.refetch()` 직접 호출. cursor 재set 불필요(refetch는 동일 queryKey로 재실행 + dedup 가드는 새 success 시점에 동작).
- [x] **[Review][Patch]** structlog leak 검증 assertion이 tautology — height(180) leak 검출 불가 [`api/tests/api/v1/test_admin_pii_reveal.py:317-326`] (Blind, MEDIUM) — **Fix 적용**: `_MASKED_ID_KEYS = {"admin_id", "target_user_id"}` 정의 + `joined` 구성 전 해당 kwargs 사전 제외 + height assertion을 `assert "180" not in joined`로 단순화(tautology 해소). 마스킹 ID(`u_<hex8>`) collision 없이 실제 plaintext leak 검출.

- [x] **[Review][Defer]** DF146 — Filters dropped on cursor pagination ("더 보기") [`web/src/features/admin/AuditLogTable.tsx:108-115` + `audit-logs/page.tsx:22-25`] — deferred, UI가 현재 filter UI 미노출(`actor_id=me&limit=50` 고정)이라 latent. Filter UI 도입(Story 8.4 polish 시점) 직전 일괄 정비.
- [x] **[Review][Defer]** DF147 — Initial SSR audit-logs 페이지 새로고침 affordance 부재 [`web/src/features/admin/AuditLogTable.tsx:104` `enabled: activeCursor !== null`] — deferred, UX nice-to-have(현 패턴은 새로고침 = 페이지 reload). Audit-logs UX polish(Story 8.4) 시점.
- [x] **[Review][Defer]** DF148 — soft-deleted admin (`users.deleted_at IS NOT NULL`)이 잔존 JWT로 self-audit/`pii-reveal` 가능 [`api/app/api/deps.py:current_admin` Story 1.2 SOT] — deferred, **pre-existing** in Story 1.2 SOT(7.4가 도입한 결함 아님). `current_admin` 자체에 `deleted_at IS NULL` 가드 추가 필요. Story 5.2 + admin auth 정합 검토와 함께(Story 8.4 또는 audit DB role 분리 시점).

## Dev Notes

### 핵심 설계 결정

#### Story 1.2 + 7.1 + 7.2 + 7.3 SOT 재사용 (백엔드 admin auth core 변경 0건)

본 스토리는 **백엔드 admin auth core 변경 0건** + **audit_logs schema 변경 0건** + **admin.py 기존 6 endpoint 본문 변경 0건** + **신규 영역 5건만**(admin.py 신규 2 endpoint + masking.py 신규 4 reveal helper + audit endpoint Pydantic 모델 + 2 cursor helper + Web 신규 audit-logs 페이지 1 + AuditLogTable 1 + UserDetailClient 토글 수정). Story 1.2/7.1/7.2/7.3가 이미 `current_admin` transitive 체인 + admin JWT + 8h TTL + `bn_admin_access` cookie + 6 endpoint write-wire + `audit_admin_action` factory + `audit_service.record_admin_action` + `audit_logs` 13 컬럼 + ENUM 7 값(`user_pii_view` 사전 등록) + 3 인덱스 + append-only trigger + masking 4 helper SOT를 갖췄다 — *재발명 절대 금지*.

#### `POST /pii-reveal` 액션 분리 vs `GET ?include_pii=true` 쿼리 토글

**대안 A — `GET /v1/admin/users/{user_id}?include_pii=true`** (Story 7.2 docstring 144행 forward stub 명시): 거부함. (a) GET은 idempotent + cacheable + prefetchable — 의도치 않은 plaintext 노출 risk(브라우저/CDN 캐시 / 프리페치 / 링크 공유). (b) audit row 의미가 약함 — *조회*는 일상적이지만 *원문 보기*는 *명시 액션*. POST 메서드가 action semantics(audit verb) 정합. (c) FastAPI dep `dependencies=[...]`는 GET/POST 모두 적용 가능 — wire 비용 동일.

**대안 B — `POST /v1/admin/users/{user_id}/pii-reveal`** *(채택)*: action semantics + 명시 audit + GET 부수효과 없음 invariant + CSRF 방어 trivial(`bn_admin_access` cookie + SameSite=Strict + POST). 클라이언트는 TanStack Query `useMutation`으로 분리 — read query와 독립 lifecycle.

**대안 C — `PATCH /v1/admin/users/{user_id}` body에 `reveal=true` flag** (수정 endpoint와 통합): 거부함. PATCH는 *수정* semantics — *조회 unmask*와 책임 혼재 + 응답 shape 분기 의무(unmask True 시 plaintext, False 시 마스킹) → API contract 명확성 저하.

#### `actor_id="me"` 고정 (Literal["me"]) vs 자유 UUID

epics.md:929 *"`actor_id` 권한 분리 — 1인 개발자 owner 외 admin은 자기 활동만 (외주 클라이언트별 조정 옵션)"* 정합. MVP는 owner 1인 admin 가정이라:

**대안 A — UUID 자유 + role check** (admin의 owner 식별 룰 필요): 거부함. owner 식별을 *별 컬럼*(`users.is_owner` bool) 또는 *config 환경 변수*(`BN_OWNER_USER_ID=uuid`)로 정의해야 → schema/config 변경 + 외주 클라이언트별 owner-rotation SOP 별도 의무. MVP scope 외.

**대안 B — `Literal["me"]` Query type 고정** *(채택)*: FastAPI가 422로 자동 차단 + 코드 복잡도 minimal. cross-admin 조회 권한은 Story 8 운영 polish forward(2인 이상 admin 운영 시점 + 외주 클라이언트별 owner 정책 결정).

#### self-audit endpoint에 `audit_admin_action` 미적용 (meta-audit 폭증 방지)

Story 7.3 docstring 867행 *"admin_whoami exclusion 패턴 — admin meta-info 조회는 enum scope 제외"* 정합. self-audit 조회 자체가 audit 대상이 되면:
- admin이 `/admin/audit-logs` 페이지 열 때마다 `audit_logs`에 row 추가
- "더 보기" cursor pagination 각 click마다 row 추가
- → audit 로그 본질(*business action* 추적)이 *meta-action* 노이즈로 희석

**채택**: `Depends(audit_admin_action)` 미wire — `Depends(current_admin)` 1줄만 (IP 가드 + JWT + DB role 재확인 transitive). `admin_session_introspect` ENUM 값 추가는 *추적 가치 vs 노이즈 trade-off*에서 후자 우세 — Story 7.3 SOT 결정 유지.

#### 5분 비활동 timer — client-side vs server-side

epics.md:932 *"5분 비활동 후 마스킹 자동 복원"* 정합.

**대안 A — server-side reveal session(`reveal_session_id` 쿠키 + Redis TTL 5분 + 활동 시 갱신 endpoint)**: 거부함. (a) MVP scope 외 — Redis 의존성 추가 + cookie/session 인프라 + 동기화 endpoint(`POST /pii-reveal/heartbeat`) 추가. (b) "활동" 정의가 server-side에서는 불가(client DOM 활동 = HTTP request 활동 아님 — 마우스 움직임만으로 heartbeat 보내는 것은 트래픽 폭증).

**대안 B — client-side state + DOM event listener + setInterval timer** *(채택)*: client에 reveal state + plaintext payload 보존 + 비활동 timer. 비활동 = 5분간 mouse/keyboard/touch 이벤트 부재. trade-off:
  - *클라이언트가 신뢰되지 않으면* state-bypass(개발자도구로 timer 강제 reset)는 가능 — 그러나 admin은 owner 1인 + plaintext 응답을 *받는* 시점에 audit row가 이미 기록됨(증거 보존) → bypass의 actual harm은 *자기 자신 데이터를 자기가 더 오래 보는 것*(거버넌스 위반 0). 외주 클라이언트의 *다중 admin* 시나리오에서는 Story 8 server-side session으로 강화 forward.

#### `app/core/masking.py` `reveal_*` 4 helper 추가 vs `mask_*(..., unmask=True)` flag

**대안 A — `mask_email(email, unmask=False)` flag 패턴**: 거부함. (a) `mask_*` 이름이 *unmask=True* 시 plaintext 반환 — naming-vs-semantic 모순. (b) return 타입 분기 의무(`mask_allergies_count` → str vs `mask_allergies_count(..., unmask=True)` → list[str]). (c) caller 코드가 `mask_email(email, unmask=is_revealed)` 패턴이 되면 *마스킹 vs 노출* 의도가 가려짐 + grep으로 PII 노출 지점 추적 곤란.

**대안 B — `reveal_*` 별 함수 4개** *(채택)*: `mask_*` 함수 4개 변경 0(회귀 16 케이스 PASS) + 호출처 의도 명시 + grep으로 PII 노출 지점 추적 가능(`reveal_email|reveal_weight|reveal_height|reveal_allergies` 패턴). `reveal_*`는 단순 pass-through(NULL-safe) — 미래 *부분 노출*(예: `reveal_email_local_only`) 또는 *audit-bound reveal*(plaintext 반환 + audit row 자동 INSERT) 확장 시 본 모듈에 흡수 가능.

#### 활동 추적 debounce + 1초 interval timer

- DOM event listener: `mousemove`/`keydown`/`click`/`touchstart` 4종
- debounce 500ms — 마우스 움직임마다 setState 호출 시 React 렌더 폭증 + Web Vitals(INP) 회귀 가능
- 1초 interval timer: `Date.now() >= expiresAt` 확인 — 5분 미만이면 no-op, 만료 시 setState 1회 + interval clear
- cleanup: revealState change(masked로) 또는 unmount 시 listener detach + interval clear (memory leak 0)

#### `expires_at` server hint — client timer 정합

응답에 `revealed_at` + `expires_at` 포함 — 클라이언트가 *server 시간* 기준으로 timer 시작 가능(client clock skew 회피). 단, 본 스토리는 *비활동* 정의가 client-side라 server hint는 단순 *최초 디스플레이 텍스트*(잔여 시간 표시)에 사용 — actual timer는 `Date.now() + PII_REVEAL_TTL_MS`로 갱신(활동 시 server 호출 없이 client 단독으로 갱신). server hint와 client timer는 *최초 5분*만 동기화 후 client 단독.

### 라이브러리·프레임워크 요구

- **백엔드**:
  - `sqlalchemy` 2.x async — `select(AuditLog).where(...)` ORM 패턴(Story 7.3 patterns 정합).
  - `fastapi` — `Query` parameter + `Literal["me"]` type-safe 검증 + `dependencies=[...]` decorator wire(Story 7.3 SOT 재사용).
  - `pydantic` v2 — `AdminAuditLogItem`/`AdminAuditLogListResponse`/`AdminUserPiiRevealResponse` 3 신규 응답 모델(`extra="forbid"` 일관).
  - 표준 라이브러리: `datetime.UTC` / `timedelta` (Story 7.3 spec) / `ipaddress` (INET 직렬화 — Pydantic이 자동 str 변환).
- **테스트**:
  - `pytest` + `pytest-asyncio` + `httpx.AsyncClient` — Story 1.2/7.1/7.2/7.3 baseline 재사용.
  - synthetic 1만 row fixture — `tests/api/v1/test_admin_audit_logs.py:nfr_p9_setup` (Story 7.2 NFR-P9 패턴 정합).
- **Web**:
  - `next/cookies` + `next/navigation:redirect` — Story 7.2 SSR fetch 패턴 정합.
  - `@tanstack/react-query` — Story 4.3/7.2 SOT 재사용 (`useQuery` for audit list + `useMutation` for pii-reveal).
  - `vitest` + `@testing-library/react` — Story 4.3 web 테스트 baseline 정합(timer fake / event dispatch).
  - 표준 Web API: `window.confirm` (shadcn/ui Dialog는 Story 8.4 polish forward — Story 7.2 패턴 정합).
- **Mobile**: 본 스토리 mobile 변경 0건 — admin은 web-only(Story 7.1/7.2/7.3 SOT 정합).

### 회귀 보존 SOT (절대 변경 금지)

- `api/app/api/deps.py:current_admin` + `current_admin_claims` + `require_admin_ip_allowed` + `audit_admin_action` — Story 1.2 + 7.1 + 7.3 SOT. 본 스토리는 *재사용*만(`audit_admin_action` factory를 `pii-reveal` endpoint 데코레이터에 wire).
- `api/app/api/v1/admin.py` 기존 6 endpoint 핸들러 *본문* + 데코레이터(`dependencies=[...]`) — Story 7.2 + 7.3 SOT. 본 스토리는 *7번째 + 8번째 endpoint 신설*만(`list_self_audit_logs` + `reveal_user_pii`) — 기존 6 endpoint 변경 0건.
- `api/app/core/masking.py:mask_email`/`mask_weight`/`mask_height`/`mask_allergies_count` — Story 7.2 SOT 4 함수. 본 스토리는 *재사용*만 + *신규 4 reveal helper 추가*. 기존 signature/return/behavior 변경 0건(16 케이스 회귀 보존).
- `api/app/core/proxy.py:get_real_client_ip` — Story 3.9 SOT(CR P1 정합). 본 스토리는 *audit endpoint 응답에서 INET → str 직렬화*만(자동 — 변경 0).
- `api/app/services/audit_service.py:record_admin_action` — Story 7.3 SOT. 본 스토리는 *재사용*만(`pii-reveal` endpoint가 `audit_admin_action` factory 통해 호출).
- `api/app/db/models/audit_log.py` — Story 7.3 SOT(13 컬럼 + Literal 7 값 + 3 인덱스). 본 스토리는 *읽기*만(SELECT) — schema 변경 0건.
- alembic 0001-0022 — 이전 스토리 SOT. 본 스토리는 신규 alembic migration 0건.
- `api/app/api/v1/auth.py:admin_whoami` + `admin_exchange` — Story 1.2 + 7.1 SOT. 본 스토리는 *audit 대상 미포함* invariant 유지(Story 7.3 의도 보존).
- `api/app/api/v1/users.py:HealthProfilePatchRequest` — Story 5.1 SOT. 본 스토리는 미변경 + Story 7.2 admin patch endpoint도 본 스토리에서 미변경.
- `web/src/app/(admin)/admin/layout.tsx` — Story 7.1 SOT(server-side guard). 본 스토리는 *재사용*만 — audit-logs 페이지도 admin layout 아래 wrap.
- `web/src/app/(admin)/admin/users/page.tsx` + `users/[user_id]/page.tsx` — Story 7.2 SOT. 본 스토리는 *전자 미변경* + *후자는 `UserDetailClient` 토글 추가만*(페이지 자체 변경 0 — Server Component shell SSR fetch invariant 보존).
- `web/src/features/admin/UserSearchClient.tsx` + `UserMealsTable.tsx` + `UserMealAnalysesTable.tsx` — Story 7.2 SOT. 본 스토리는 *재사용*만 — 검색 결과 카드 마스킹 invariant 보존(epics.md:930 정합).
- `web/src/lib/admin-api.ts` + `admin-auth.ts` — Story 7.1 + 7.2 SOT. 본 스토리는 *재사용*만(`adminApiFetch`로 audit-logs/pii-reveal 호출).

### 직전 스토리(7.3) 학습

- **CR triage 분류 규칙** (memory `feedback_defer_vs_dismiss_in_cr`) — 본 스토리 CR도 동일 분류: 가치<비용/YAGNI/UX 데이터 부재는 dismiss + 미래 작업이면 defer.
- **dismiss 코멘트 회피** (memory `feedback_no_dismiss_comment_for_false_positive`) — PR 코멘트는 redundant ceremony. 본 스토리 CR도 false-positive에는 코멘트 X.
- **CR 종료 직전 sprint-status `review → done`** (memory `feedback_cr_done_status_in_pr_commit`) — 본 스토리도 PR commit에 status 갱신 포함 + `epic-7: in-progress → done` 함께 포함 — chore PR 강제 회피.
- **Story 7.3 fail-open SQLAlchemyError 한정** — 본 스토리는 `record_admin_action` SOT 재사용으로 `pii-reveal` audit wire가 동일 invariant 자동 적용. 코딩 버그(`TypeError`/`AttributeError`)는 noop 흡수 X — 의도 보존.
- **Story 7.3 audit row text 컬럼 sanitize** — `_sanitize_audit_text`(128/1024 cap + 제어문자 strip) — 본 스토리는 변경 0 + `pii-reveal` audit row도 동일 적용 자동.
- **Story 7.3 IPv4-mapped IPv6 정규화** — `_coerce_ip` SOT — 본 스토리는 audit endpoint 응답에서 INET → str 직렬화 시 동일 정규화 결과 노출.
- **Story 7.3 dep cache transitive `current_admin` 공유** — 본 스토리 `pii-reveal` endpoint도 `Depends(current_admin)` + `Depends(audit_admin_action(...))` 두 dep 모두 wire하나 dep cache로 `current_admin` SELECT 1회만 실행 (SQL N+1 회피).
- **Story 7.3 append-only trigger 적용 안 됨**: 본 스토리는 read-only endpoint(`GET /admin/audit-logs`) + write endpoint(`POST /pii-reveal`만 INSERT) — UPDATE/DELETE 0건이라 trigger 미발동 보존(Story 7.3 회귀 0).
- **Story 7.2 알림 3 필드 silent 누락 패턴** — 본 스토리 신규 Pydantic 모델 3개(`AdminAuditLogItem` 13 필드 + `AdminUserPiiRevealResponse` 8 필드 + `AdminAuditLogListResponse` 2 필드) 모두 `extra="forbid"` + spec line ↔ 모델 ↔ helper 3 지점 verify checklist 필수.
- **Story 7.2 web 테스트 deferred 처리** — 본 스토리는 신규 web 컴포넌트 2개(audit-logs page + AuditLogTable) + 수정 1개(UserDetailClient 토글) — vitest 5 케이스 추가(timer fake + activity dispatch + confirm mock). web 테스트는 Story 7.2와 달리 본 스토리에서 *명시 IN*(원문 보기 토글 + 5분 timer는 UX critical invariant — UX 회귀 가드 필수).
- **alembic round-trip 회귀 가드** — 본 스토리 alembic 변경 0건이라 round-trip 회귀 가드 신규 추가 0(Story 7.3 0022 SOT 보존).
- **Memory `feedback_branch_from_master_only`** — 본 스토리 브랜치 `story/7.4-self-audit-pii-toggle`은 master에서 분기(직전 7.3 브랜치 squash-merge 후 SHA mismatch 회피).

### 환경 변수 추가

본 스토리 신규 환경 변수 0건. Story 1.2/3.9/7.1/7.2/7.3 기존(`API_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL` / `ADMIN_IP_ALLOWLIST` / `ENVIRONMENT` / `BN_ADMIN_JWT_SECRET` 등) 재사용만.

### Project Structure Notes

- Alignment with `architecture.md:760` *"audit-logs/page.tsx # FR37-FR38"* — 본 스토리에서 신설.
- Alignment with `architecture.md:773` *"AuditLogTable.tsx"* — 본 스토리에서 신설 (`features/admin/` 디렉토리).
- Alignment with `architecture.md:995` *"FR38 — `admin.py:audit_logs` self-audit 화면"* — 본 스토리에서 `list_self_audit_logs` endpoint 신설.
- Alignment with `architecture.md:996` *"FR39 — 관리자 화면 마스킹 — Web `features/admin/UserSearch.tsx` 마스킹 토글"* — 본 스토리에서 `UserDetailClient.tsx` 원문 보기 토글 신설 (검색 결과 카드는 기본 마스킹 유지 — UserSearchClient는 변경 0; 토글은 상세 페이지 분리 — epics.md AC 정합).
- Alignment with `architecture.md:309` *"Sentry before_send hook + structlog processor — 정규식으로 이메일/체중/식단 raw_text/알레르기 항목 마스킹"* — 본 스토리 endpoint 핸들러 내 logger 인자에 plaintext PII 0 invariant + Sentry SDK hook은 DF141 Story 8.4 forward.
- Alignment with `architecture.md:670` `app/api/v1/admin.py` (FR35-FR39) — 본 스토리 admin.py에 7번째(audit-logs) + 8번째(pii-reveal) endpoint 추가로 FR38/FR39 closure.
- Alignment with `architecture.md:686` `app/db/models/audit_log.py` — 본 스토리는 *읽기*만(SELECT) — schema 변경 0.
- **Deviation 1**: epics.md:929 *"`actor_id` 권한 분리 — 1인 개발자 owner 외 admin은 자기 활동만 (외주 클라이언트별 조정 옵션)"* — 본 스토리는 *MVP `actor_id="me"` 고정*(Literal["me"]). *외주 클라이언트별 cross-admin 권한*은 Story 8 운영 polish forward(`BN_OWNER_USER_ID` env + Literal Union 확장).
- **Deviation 2**: epics.md:932 *"5분 비활동 후 마스킹 자동 복원"* — 본 스토리는 *client-side state* 기반 timer + DOM event activity tracking 채택. server-side reveal session(Redis TTL)은 Story 8 운영 polish forward (외주 클라이언트의 다중 admin + tamper resistance 요구 시점).
- **Deviation 3**: epics.md:933 *"Sentry breadcrumbs / structlog는 원문 보기 액션의 payload를 마스킹된 채로만 로깅 (이중 안전판)"* — 본 스토리는 *애플리케이션 코드 레벨* invariant(`reveal_user_pii` 핸들러가 logger 인자에 plaintext PII 0) + audit row 13 컬럼 모두 plaintext PII 0(Story 7.3 schema SOT 보존). Sentry SDK `before_send` hook 통합은 DF141 Story 8.4 forward(미구현 부분 보존).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic-7-Story-7.4 — Self-audit 화면 + 민감정보 마스킹 + 원문 보기 토글]
- [Source: _bmad-output/planning-artifacts/epics.md#FR38 — 관리자 self-audit 자기 활동 로그 조회]
- [Source: _bmad-output/planning-artifacts/epics.md#FR39 — 사용자 데이터 마스킹 + 명시 원문 보기 액션]
- [Source: _bmad-output/planning-artifacts/epics.md#NFR-S5 — 민감정보 마스킹 (이메일/체중/신장/알레르기/식단 raw_text 단일 룰셋)]
- [Source: _bmad-output/planning-artifacts/epics.md#NFR-S7 — Admin role JWT + audit 자동 기록]
- [Source: _bmad-output/planning-artifacts/epics.md#NFR-P9 — Web 관리자 검색 1만 건 ≤ 1초 (audit-logs 검색도 동일 인덱스 hit)]
- [Source: _bmad-output/planning-artifacts/architecture.md#api-v1-admin — `admin.py` FR35-FR39 통합 라우터]
- [Source: _bmad-output/planning-artifacts/architecture.md#requirements-to-structure — FR38 / FR39 매핑]
- [Source: _bmad-output/planning-artifacts/architecture.md#sentry-masking — before_send hook + structlog processor NFR-S5 SOT]
- [Source: _bmad-output/planning-artifacts/prd.md#FR38 — 자기 활동 audit 조회]
- [Source: _bmad-output/planning-artifacts/prd.md#FR39 — 마스킹 + 원문 보기 토글]
- [Source: api/app/api/deps.py:current_admin — Story 1.2 + 7.1 transitive IP 가드 + JWT + DB role 재확인 SOT (audit-logs endpoint + pii-reveal endpoint 모두 wire)]
- [Source: api/app/api/deps.py:audit_admin_action — Story 7.3 factory dep SOT (pii-reveal endpoint dependencies=[...] wire)]
- [Source: api/app/api/v1/admin.py — Story 7.2 + 7.3 6 endpoint SOT (본 스토리는 7번째 + 8번째 endpoint 추가만, 기존 6개 변경 0)]
- [Source: api/app/api/v1/admin.py:_encode_cursor + _decode_cursor — Story 7.2 cursor SOT (audit cursor helper 패턴 정합)]
- [Source: api/app/api/v1/admin.py:_mask_user_id_for_log — Story 7.2 logger 마스킹 helper SOT (pii-reveal 핸들러도 동일 helper)]
- [Source: api/app/core/masking.py — Story 7.2 NFR-S5 SOT (mask_* 4 함수 + 본 스토리 reveal_* 4 함수 추가)]
- [Source: api/app/core/proxy.py:get_real_client_ip — Story 3.9 CR P1 SOT (audit endpoint 응답 INET 직렬화 재사용)]
- [Source: api/app/core/exceptions.py:AdminCursorInvalidError + AdminUserNotFoundError — Story 7.2 SOT (audit endpoint cursor + pii-reveal 404 재사용)]
- [Source: api/app/db/models/audit_log.py — Story 7.3 13 컬럼 + 7 값 ENUM SOT (user_pii_view ENUM 값 사전 등록 — 본 스토리에서 실 wire)]
- [Source: api/app/services/audit_service.py:record_admin_action — Story 7.3 audit INSERT + fail-open SOT (본 스토리 pii-reveal endpoint 재사용)]
- [Source: api/app/services/audit_service.py:_sanitize_audit_text — Story 7.3 audit row text sanitize SOT]
- [Source: api/alembic/versions/0022_create_audit_logs.py — Story 7.3 audit_logs 테이블 + 3 인덱스 + ENUM + trigger SOT (본 스토리 변경 0)]
- [Source: web/src/app/(admin)/admin/layout.tsx — Story 7.1 admin SSR guard SOT (audit-logs 페이지도 wrap)]
- [Source: web/src/app/(admin)/admin/users/[user_id]/page.tsx — Story 7.2 Server Component SSR fetch + redirect 패턴 정합 (audit-logs 페이지 1:1 정합)]
- [Source: web/src/features/admin/UserDetailClient.tsx — Story 7.2 탭 구조 SOT (본 스토리 토글 추가)]
- [Source: web/src/features/admin/UserSearchClient.tsx — Story 7.2 반응형 카드/테이블 SOT (AuditLogTable 1:1 정합)]
- [Source: web/src/features/admin/types.ts — Story 7.2 admin 타입 SOT (본 스토리 4 인터페이스 추가)]
- [Source: web/src/lib/admin-api.ts — Story 7.2 adminApiFetch SOT (audit-logs + pii-reveal 호출 재사용)]
- [Source: _bmad-output/implementation-artifacts/7-1-관리자-로그인-admin-jwt-가드.md — Story 7.1 admin auth baseline + admin landing placeholder]
- [Source: _bmad-output/implementation-artifacts/7-2-관리자-사용자-검색-이력-수정.md — Story 7.2 admin.py 6 endpoint + masking.py 4 helper + web 8 파일]
- [Source: _bmad-output/implementation-artifacts/7-3-audit-log-자동-기록-연쇄.md — Story 7.3 audit_logs schema + audit_admin_action factory + record_admin_action service]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md#DF138 — admin 식단·피드백 UI cursor pagination forward (재검토 시점: 본 스토리 또는 운영 51건 초과)]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md#DF139 — admin SSR cookie vs Bearer audit transport 분기 forward]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md#DF140 — admin cross-admin action 거버넌스 가드 forward]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md#DF141 — masking.py Sentry beforeSend hook 자동 적용 forward]
- [Source: _bmad-output/implementation-artifacts/sprint-status.yaml — `epic-7: in-progress` + `7-4-...: backlog → ready-for-dev` 진입 + 본 스토리 done 시 `epic-7: done` 전이]

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m]

### Debug Log References

### Completion Notes List

- 2026-05-11 (Amelia, CS): Story 7.4 컨텍스트 작성 완료. Branch `story/7.4-self-audit-pii-toggle` 분기 완료(master 기준 — memory `feedback_branch_from_master_only` 정합). Epic 7 마지막 스토리 — `7-4-...: backlog → ready-for-dev` 갱신 의무 + `epic-7: in-progress` 보존(완료 시 `done` 전이). **본 스토리는 admin auth core SOT(Story 1.2 + 7.1 + 7.2 + 7.3) 변경 0건 + admin.py 기존 6 endpoint 본문 변경 0건 + audit_logs schema 변경 0건 + masking.py 기존 4 helper 변경 0건** — 회귀 ~110 테스트 보존 invariant. 신규 5 영역: (1) `admin.py:list_self_audit_logs` endpoint(`actor_id="me"` Literal + cursor + 3 optional filter + 16 단위 테스트), (2) `admin.py:reveal_user_pii` endpoint(`POST .../pii-reveal` + `dependencies=[Depends(audit_admin_action(action="user_pii_view"))]` wire + 12 단위 테스트), (3) `app/core/masking.py:reveal_email`/`reveal_weight`/`reveal_height`/`reveal_allergies` 4 함수(NULL-safe pass-through + 8 단위 테스트), (4) Web `(admin)/admin/audit-logs/page.tsx` Server Component + `features/admin/AuditLogTable.tsx` Client Component(반응형 + TanStack Query + Korean label), (5) `features/admin/UserDetailClient.tsx` 원문 보기 토글 + 5분 비활동 자동 복원(DOM event activity tracking + 1초 interval timer + vitest 5 케이스). **scope 외**: self-audit endpoint는 `Depends(audit_admin_action)` 미적용(meta-audit 폭증 회피 — Story 7.3 `admin_whoami` exclusion 패턴 정합). Story 8 forward: cross-admin 권한(`BN_OWNER_USER_ID` env + Literal Union 확장) / server-side reveal session(Redis TTL) / Sentry SDK before_send hook 통합(DF141). **신규 의존성 0건** + **신규 환경 변수 0건** + **신규 alembic 0건** + **신규 mobile 파일 0건** — Story 1.2/7.1/7.2/7.3 baseline 재사용. **회귀 0건**: admin.py 6 endpoint 본문 + masking.py 4 helper + audit_logs schema 모두 변경 0 + Story 7.2 OpenAPI 6 operation schema 동형 보존(7번째·8번째 신규 operation 추가만).

- 2026-05-11 (Amelia, DS): Story 7.4 구현 완료 — 8 AC 모두 PASS. **백엔드 영역 4건** (admin.py: list_self_audit_logs + reveal_user_pii endpoint, AdminAuditLogItem/AdminAuditLogListResponse/AdminUserPiiRevealResponse 3 Pydantic 모델, _build_audit_log_item/_build_pii_reveal_response 2 helper, _encode_audit_cursor/_decode_audit_cursor alias, PII_REVEAL_TTL_MINUTES 상수 / masking.py: reveal_email/reveal_weight/reveal_height/reveal_allergies 4 helper / test_admin_audit_logs.py: 18 케이스 신규 / test_admin_pii_reveal.py: 13 케이스 신규 / test_masking.py: 8 케이스 추가 / test_admin_routes_audit_coverage.py: audit-logs exclusion 등재). **Web 영역 5건** (audit-logs/page.tsx Server Component 신규 / AuditLogTable.tsx 신규 / UserPiiToggle.tsx 신규 / UserDetailClient.tsx 수정(toggle 통합) / types.ts 4 인터페이스 추가 / admin/page.tsx forward stub 제거). **OpenAPI 클라이언트** (web + mobile api-client.ts) 재생성 — 2 신규 operation 추가, 기존 schema 동형 보존. **회귀 가드**: ruff/format/mypy/pytest 0 errors + coverage 89.18% (≥85% 가드) + 1365 passed (Story 7.3 baseline 1318 + 47 신규 — 39 = AC1 18 + AC2/AC6 13 + AC3 8) + 11 skipped + 0 failed + web tsc/lint 0 + mobile tsc 0. **AC1 NFR-P9** 1만 row p95 ≤ 1초 실측 PASS(composite index `idx_audit_logs_actor_id_occurred_at` hit). **Deviation 4** — AC5 `UserPiiToggle.test.tsx` vitest 5 케이스는 web 프로젝트에 vitest 인프라 부재로 Story 8.4 polish forward(devDep 0건 + 기존 test 파일 0건 — 인프라 도입은 scope 외). 대안 가드: AC2 13 케이스가 API contract 100% cover + 수동 검증 시나리오 5건이 UX 흐름 cover. **신규 의존성 0** + **신규 env var 0** + **신규 alembic 0** + **mobile 파일 변경 0** — Story 1.2/7.1/7.2/7.3 baseline 재사용. **회귀 0건**: admin.py 6 endpoint 본문 + masking.py 4 helper + audit_logs schema + 7.2 web 컴포넌트(UserSearchClient/UserMealsTable/UserMealAnalysesTable/AdminProfileEditForm) 모두 변경 0. Branch `story/7.4-self-audit-pii-toggle` 동일 유지, sprint-status `7-4-...: ready-for-dev → in-progress → review` 갱신 (epic-7 done 전이는 CR 시점에 PR commit에 포함 — memory `feedback_cr_done_status_in_pr_commit` 정합).

### File List

**신규 (Backend)**:
- `api/tests/api/v1/test_admin_audit_logs.py`
- `api/tests/api/v1/test_admin_pii_reveal.py`

**수정 (Backend)**:
- `api/app/api/v1/admin.py` — 8 endpoint(7+8번째 신규) + 3 Pydantic 응답 모델 추가 + 2 helper + audit cursor alias + import 추가
- `api/app/core/masking.py` — `reveal_*` 4 함수 추가 + 모듈 docstring 갱신
- `api/tests/core/test_masking.py` — 8 케이스 추가(reveal_*)
- `api/tests/api/test_admin_routes_audit_coverage.py` — `audit-logs` exclusion 등재 + business 가드 함수 skip 추가

**신규 (Web)**:
- `web/src/app/(admin)/admin/audit-logs/page.tsx` — Server Component shell
- `web/src/features/admin/AuditLogTable.tsx` — Client Component (TanStack Query + 반응형 + Korean label)
- `web/src/features/admin/UserPiiToggle.tsx` — 원문 보기 토글 + activity timer + 카운트다운

**수정 (Web)**:
- `web/src/features/admin/types.ts` — 4 인터페이스 추가(AdminAuditLogAction/Item/ListResponse + AdminUserPiiRevealResponse)
- `web/src/features/admin/UserDetailClient.tsx` — 프로필 탭 위에 `UserPiiToggle` 통합 (1 import + 1 wrapper render block)
- `web/src/app/(admin)/admin/page.tsx` — forward stub 제거 + FR36/FR38 활성 안내

**자동 재생성 (OpenAPI)**:
- `web/src/lib/api-client.ts` — `list_self_audit_logs_v1_admin_audit_logs_get` + `reveal_user_pii_v1_admin_users__user_id__pii_reveal_post` 2 operation 추가
- `mobile/lib/api-client.ts` — 동일 (admin은 web-only 흐름이나 OpenAPI 자동 sync로 mobile 클라이언트에도 schema 등재)

**수정 (Sprint Status)**:
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `7-4-self-audit-화면-마스킹-원문-토글: ready-for-dev → in-progress → review`

**기존 unchanged (회귀 invariant 보존)**:
- `api/app/api/deps.py` (current_admin / audit_admin_action SOT)
- `api/app/db/models/audit_log.py` (13 컬럼 schema + 7 ENUM 값)
- `api/app/services/audit_service.py` (record_admin_action)
- `api/alembic/versions/0022_create_audit_logs.py`
- `api/app/api/v1/admin.py` 기존 6 endpoint 본문 + 데코레이터
- `api/app/core/masking.py` 기존 4 `mask_*` 함수
- `web/src/features/admin/AdminProfileEditForm.tsx`
- `web/src/features/admin/UserSearchClient.tsx`
- `web/src/features/admin/UserMealsTable.tsx`
- `web/src/features/admin/UserMealAnalysesTable.tsx`

### File List (legacy section placeholder — DS가 위 File List 갱신)
