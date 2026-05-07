# Story 5.2: 회원 탈퇴 + soft delete + 30일 grace + 물리 파기 worker

Status: done

<!-- Validation: Epic 5 두 번째 스토리. Story 1.2(`users.deleted_at` 컬럼 + `current_user`의 `deleted_at IS NULL` 가드 + `AccountDeletedError` 403) baseline + Story 4.2(APScheduler `AsyncIOScheduler` lifespan SOT + `register_*_job` 패턴 + Sentry transaction op `*.sweep`) baseline + Story 5.1 PATCH endpoint + 3 timestamp 의미 분리 baseline 위에 *PIPA 정보주체 권리(즉시 삭제 의무) + 30일 grace + 물리 파기 cron* 흐름 신설. epics.md:794-807 정합 — `DELETE /v1/users/me` 신규(soft delete + active refresh_tokens revoke) + `app/workers/soft_delete_purge.py` 신규 cron(매일 새벽 3시 KST) + R2 dump bucket 30일 추가 보관(settings env 미설정 시 skip + 운영 SOP 1줄) + `AccountDeletedError` detail 강화(N일 grace 한국어 안내). 모든 user-FK 모델(`consents`/`meals`/`meal_analyses`/`notifications`/`refresh_tokens`)이 이미 `ondelete="CASCADE"`라 `DELETE FROM users WHERE id = X` 1건이 자동 cascade — 별도 명시 cascade 코드 0건. R2 meal images cleanup은 `meals/{user_id}/` prefix list_objects + delete_objects 1패스. 일반 사용자 자기 탈퇴는 Story 5.1 정합으로 audit 미기록(자기 데이터 권리). -->

## Story

As a 엔드유저,
I want 모바일 또는 Web에서 회원 탈퇴를 요청하면 30일 grace 후 모든 데이터가 물리 파기되기를,
so that PIPA 정보주체 권리(즉시 삭제 의무 + Art.35)를 보장받으며 단순 실수 탈퇴에 대한 30일 회복 창구를 갖는다.

## Acceptance Criteria

1. **AC1 — `users.deletion_reason` 컬럼 + `idx_users_deleted_at_pending_purge` partial index + alembic 0017**
   **Given** 0016 chain HEAD `0016_users_profile_updated_at` + 기존 `users.deleted_at` 컬럼(Story 1.2 0002 baseline) + Story 1.5 0005 R8 SOP(`drop+recreate`), **When** `api/alembic/versions/0017_users_deletion_reason_and_purge_index.py` 신규 + `api/app/db/models/user.py` 컬럼 1건 + index 1건 추가, **Then**:
   - 0017 revision = `0017_users_deletion_reason_and_purge_index`, down_revision = `0016_users_profile_updated_at`. upgrade는 (a) `op.add_column("users", sa.Column("deletion_reason", sa.Text(), nullable=True))` (b) `op.create_index("idx_users_deleted_at_pending_purge", "users", ["deleted_at"], postgresql_where=sa.text("deleted_at IS NOT NULL"))` 2건. downgrade는 역순 `op.drop_index` + `op.drop_column`.
   - `app/db/models/user.py:User.deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)` 추가(Story 5.1 패턴 정합 — 컬럼 위치는 `deleted_at` 바로 아래).
   - `__table_args__`에 `Index("idx_users_deleted_at_pending_purge", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL"))` 등재(`idx_users_role_admin` partial index SOT 패턴 정합).
   - **컬럼 의미**: `deletion_reason` = *사용자가 탈퇴 시 선택한 자유 텍스트 사유*(epics.md:802 *"사유 선택(선택)"*). 미송신 시 NULL. enum 미사용(MVP — 후속 polish에서 카테고리 분류 운영 분석 시 enum 도입 검토 — Story 8.x forward).
   - **회귀 0건**: 기존 사용자 row는 `deletion_reason=NULL` default. partial index는 `deleted_at IS NOT NULL`인 행만 색인 — 활성 사용자 INSERT/UPDATE 비용 0(가장 비용 큰 hot path 가드).
   - 0016 → 0017 upgrade/downgrade roundtrip 멱등 검증(test 1건).

2. **AC2 — `DELETE /v1/users/me` endpoint + soft delete + active refresh_tokens revoke + 쿠키 clear**
   **Given** Story 1.5 `POST /me/profile` SOT + Story 5.1 `PATCH /me/profile` SOT + Story 1.2 `auth.py:logout` _clear_auth_cookies SOT + `current_user` Depends가 `User.deleted_at.is_(None)` 가드 baseline, **When** `api/app/api/v1/users.py`에 `DELETE /me` endpoint + body 모델 추가, **Then**:
   - **Endpoint 경로 결정**: epics.md:802 *"`DELETE /v1/users/me`"* 그대로 채택(생략 X). architecture.md:704 *"`/users/me` (DELETE — 회원 탈퇴 IN #15)"* 1:1 정합. `/v1/users/me/account` 같은 sub-path 회피(자기 사용자 row 자체 삭제는 `/me` SOT 수준).
   - **`AccountDeleteRequest` Pydantic BaseModel 신규**(`app/api/v1/users.py` 모듈 — `HealthProfilePatchRequest` 옆 collocated):
     - `model_config = ConfigDict(extra="forbid")` — Story 1.5/5.1 SOT 정합.
     - `reason: str | None = Field(default=None, max_length=200)` — *선택*. 빈 body `{}` 또는 body 미송신 모두 valid. 200자 cap은 DoS 방지(Story 4.4 `MacroGoal` Field 가드 패턴 정합 — domain 상한 명시 + content_length 우회 attack 차단).
     - `@field_validator("reason")` 1건 — strip whitespace + 빈 문자열은 None으로 normalize(`""` 송신 = 미송신 의미 동등, DB NULL set 정합).
   - **`DELETE /me` endpoint 신규**:
     - body: `AccountDeleteRequest | None = None`(FastAPI Body 미수신 허용 — DELETE는 body 옵션 RFC 9110 정합).
     - **Dependency**: `Depends(current_user)` 단독 — `Depends(require_basic_consents)` 미적용. 사유: PIPA Art.35 정보주체 권리(열람·정정·삭제·처리정지)는 *동의 철회와 독립*된 권리(deps.py:202-206 docstring 정합 — *조회 경로 GET은 인증만*과 같은 논리. 본 endpoint는 *삭제 경로*로 자기 데이터 권리 행사 — basic_consents 미통과 사용자도 탈퇴 가능해야 권리 봉쇄 X).
     - 흐름:
       1. body 검증(없으면 None 그대로 → reason=None).
       2. `users.deleted_at = func.now()` + `users.deletion_reason = body.reason if body else None` + `users.updated_at = func.now()` 단일 UPDATE. `UPDATE users SET deleted_at=now(), deletion_reason=:reason, updated_at=now() WHERE id = :user_id AND deleted_at IS NULL` — `deleted_at IS NULL` 가드로 *이미 탈퇴 진행 중* 재호출 멱등 처리(rowcount=0 분기). race-free.
       3. 모든 active refresh_tokens revoke — `UPDATE refresh_tokens SET revoked_at=now() WHERE user_id = :user_id AND revoked_at IS NULL`(logout endpoint 정합). 다른 디바이스 활성 세션도 즉시 무효화.
       4. **`response.delete_cookie` X — 대신 `_clear_auth_cookies(response)` Story 1.2 SOT 재사용**(auth.py 모듈 외 import 회피 위해 helper를 _shared 모듈로 이동? 또는 inline 5-line 복사? **결정: helper는 auth.py에 남기고 users.py에서 `from app.api.v1.auth import _clear_auth_cookies`로 명시 import — 양 모듈 모두 `app.api.v1` namespace 내부, 내부 helper 공유는 자연스러움**. underscore prefix 함수의 cross-module import는 일반적이진 않으나 Story 5.2 도입 후 본 helper의 *2nd consumer*가 생기는 시점이라 *이름 underscore 제거 + `__all__` 노출*을 함께 진행하는 것이 더 자연스럽다 — **결정 변경: `auth.py`의 `_clear_auth_cookies` → `clear_auth_cookies`로 rename + `__all__` 추가, users.py가 import.** Story 1.2 회귀 0건(라우터 외부 호출 X).
       5. response.status_code = 204(`status.HTTP_204_NO_CONTENT` — auth.logout SOT 정합). body 없음.
     - **Idempotency**: 이미 `deleted_at IS NOT NULL` 사용자가 다시 호출 → `current_user`가 401(`User.deleted_at.is_(None)` 필터)로 차단 — *idempotent 204* 분기 미진입(이미 인증 무효). 클라이언트는 401을 정상 흐름으로 처리(`/login` redirect).
     - **로깅**: `logger.info("users.account.deleted", user_id=_mask_user_id(user.id), reason_provided=body.reason is not None)` — NFR-S5 정합(reason raw 본문 X — *제공 여부*만 boolean. 사유 raw text는 `users.deletion_reason` DB 컬럼 SOT, 운영 분석 시 admin 권한으로 직접 SELECT). Story 5.1 `users.profile.patched` 패턴 정합.
     - **에러 매핑**: 정상 흐름은 401(인증 미통과) / 204(성공). 422 미발생(body Optional + Pydantic Field 가드만). 5xx는 글로벌 핸들러.
     - **Rate limit**: default `["1000/hour", "60/minute"]` 자동 적용(별도 데코레이터 X — Story 5.1 PATCH 패턴 정합).

3. **AC3 — `AccountDeletedError` detail 강화 + 30일 grace 한국어 안내 + `purge_at` 메타데이터**
   **Given** Story 1.2 `app/core/exceptions.py:AccountDeletedError`(status 403, code `auth.account.deleted`, title *"Account deleted"*) baseline + Story 1.2 `auth.py:_upsert_user_from_google`이 `deleted_at IS NOT NULL` row 발견 시 raise + `app/main.py:balancenote_exception_handler` 글로벌 핸들러, **When** error 클래스에 `purge_at` instance attribute + `auth.py` raise site에서 datetime 전달, **Then**:
   - **`AccountDeletedError.__init__` 확장**: `purge_at: datetime | None = None` keyword-only 파라미터 추가. instance attribute로 보존. Story 1.4 `ConsentVersionMismatchError`의 `latest_versions` 패턴 정합 — base `BalanceNoteError.__init__`은 그대로(detail만), 서브클래스가 `__init__` override + `super().__init__(detail)` 호출 후 `self.purge_at = purge_at`.
   - **detail 자동 합성**: `purge_at` 제공 시 `detail` 미제공이면 `f"탈퇴 진행 중입니다. {N}일 후 모든 데이터가 영구 파기됩니다. 복구를 원하시면 고객문의로 연락해 주세요."` 자동 생성(N = `(purge_at - now()).days`, 최소 0). detail이 명시적으로 제공된 케이스(테스트/명시 안내)는 override.
   - **`auth.py:_upsert_user_from_google` raise 강화**: 두 raise site 모두(line 262, 276) `purge_at = user.deleted_at + timedelta(days=30)` 계산 + `AccountDeletedError(purge_at=purge_at)` 송신. detail은 자동 합성(직접 string 미전달).
   - **글로벌 핸들러는 변경 0건**: `to_problem(instance=...)`이 self.detail을 그대로 ProblemDetail에 forward — 추가 헤더/필드 X(Story 1.4 `latest_versions`처럼 헤더 wire 회로는 본 케이스에 미적용 — UX는 detail 한국어 안내로 충분). 단, **N일 카운트가 매 호출마다 변동**(서버 시계 기반)이라 OpenAPI schema에는 detail 패턴만 명시(static example 제공 X).
   - **회귀 가드**: Story 1.2 `auth.py` 기존 테스트(`test_auth_router.py`의 `test_login_returns_403_when_account_deleted` 등)는 status=403 + code=`auth.account.deleted`만 검증 — detail 자동 합성 후에도 본 회귀 가드 통과. 신규 테스트 1건 추가(`test_auth_router.py`): detail에 *"탈퇴 진행 중"* + N일 한국어 안내 substring 검증 + `now()` ± 1일 tolerance(테스트 시계 차이 흡수).
   - **클라이언트 노출**: 모바일/Web auth 화면이 401/403 응답의 `detail` 필드를 alert/banner로 그대로 표시(Story 1.2 SOT 패턴 — RFC 7807 detail은 사용자 노출 정합 — 영어 *"account is deleted"* 직역보다 한국어 안내가 UX 명확성 우위). 클라이언트 코드 변경 0건(detail 표시 흐름은 이미 wire).

4. **AC4 — `app/workers/soft_delete_purge.py` cron worker + lifespan 등록 + R2 dump + cascade hard delete**
   **Given** Story 4.2 `app/workers/scheduler.py`(AsyncIOScheduler + KST timezone + `coalesce/max_instances/misfire_grace_time` SOT) + `app/workers/nudge_scheduler.py`(`register_nudge_job`/`sweep_unrecorded_meals` 패턴 SOT) + 모든 user-FK 모델 `ondelete="CASCADE"` baseline + R2 adapter `app/adapters/r2.py`, **When** 신규 worker 모듈 + `main.py:lifespan`에 `register_purge_job` 호출 추가, **Then**:
   - **`app/workers/soft_delete_purge.py` 신규** 모듈:
     - **`PURGE_JOB_ID: Final[str] = "soft_delete_purge_expired"`**(`replace_existing=True` lifespan 재등록 race 차단, nudge SOT 정합).
     - **`PURGE_GRACE_DAYS: Final[int] = 30`** — epics.md:798 + architecture.md:351 SOT(`grace 30일`).
     - **`purge_expired_soft_deleted_users(session_maker, r2_adapter=None)` async function**:
       1. `now = datetime.now(UTC)` + `cutoff = now - timedelta(days=PURGE_GRACE_DAYS)` 계산.
       2. **eligible SELECT** — `SELECT u.id FROM users u WHERE u.deleted_at IS NOT NULL AND u.deleted_at < :cutoff` (단일 쿼리 — `idx_users_deleted_at_pending_purge` partial index hit). 결과는 user_id 리스트.
       3. **각 user_id별 격리 트랜잭션**:
          - (선택) **R2 dump**: `settings.r2_purge_dump_bucket`이 truthy하면 `_dump_user_to_r2(session, r2_adapter, user_id, dump_bucket)` 호출 — user 데이터(profile/consents/meals 메타/notifications) JSON dump를 별 bucket에 `purge-dumps/{user_id}/{yyyy-mm-dd}.json` key로 PUT. 미설정 시 dump skip + `logger.info("purge.dump_skipped", reason="bucket_unset")`.
          - **R2 meal images cleanup**: `_cleanup_user_r2_images(r2_adapter, user_id)` 호출 — `meals/{user_id}/` prefix `list_objects_v2` + `delete_objects`(batch 1000건 cap, 페이지네이션). r2_adapter None이면 skip + warning.
          - **DB hard delete**: `DELETE FROM users WHERE id = :user_id AND deleted_at IS NOT NULL AND deleted_at < :cutoff` 1건. **CASCADE 자동** — `consents`/`meals`/`meal_analyses`/`notifications`/`refresh_tokens` 모두 `ondelete="CASCADE"`라 별도 cascade SQL 0건. rowcount=0(이미 다른 sweep cycle이 처리)은 멱등 skip.
       4. **격리 트랜잭션 사유**: per-user 별 `async with session_maker() as session: try: ... await session.commit() except Exception: await session.rollback() + sentry capture + continue`. 한 사용자 dump/cleanup/delete 실패가 sweep 전체를 중단시키지 않도록.
       5. Returns `dict[str, int]` stats — `users_eligible_count` / `users_purged_count` / `r2_dumps_count` / `r2_images_cleaned_count` / `errors_count`.
     - **`register_purge_job(scheduler, session_maker, r2_adapter=None, redis=None)`**:
       - `CronTrigger(hour=3, minute=0, timezone="Asia/Seoul")` — 매일 새벽 3시 KST. 사유: nudge가 0~24시 매 30분이고 새벽 3시는 push 발사 ↓ 사용자 활동 ↓ DB load idle peak. 단일 노드라 cron 충돌 0.
       - `args=[session_maker, r2_adapter]`. `id=PURGE_JOB_ID`, `replace_existing=True`(nudge SOT 정합). `redis`는 forward use(현 스토리 미사용).
     - **Sentry transaction**: `op="purge.sweep"` + per-user span `op="purge.user"`(nudge `*.sweep` 패턴 정합).
     - **structlog**: `purge.sweep.start` / `purge.sweep.eligible` / `purge.user.dumped` / `purge.user.images_cleaned` / `purge.user.deleted` / `purge.sweep.complete` / `purge.user.failed`. user_id 모두 `_mask_user_id`(NFR-S5).
   - **`app/main.py:lifespan` 갱신**:
     - `register_purge_job(scheduler, app.state.session_maker, r2_adapter=None)` 1줄 추가 — `register_nudge_job` 다음. r2_adapter는 `app.adapters.r2` 모듈(boto3 lazy singleton SOT). 별 instance 주입 없이 모듈 자체를 함수에 넘겨 dump/cleanup이 모듈 함수 호출.
     - test/ci 환경은 scheduler 자체가 disabled(scheduler.py:_DISABLED_ENVIRONMENTS) — purge 잡도 자동 등록 X. 단위 테스트는 `purge_expired_soft_deleted_users` 직접 호출.
   - **R2 dump bucket 설정**: `app/core/config.py:Settings`에 `r2_purge_dump_bucket: str = ""` 추가(default empty). 미설정 시 dump skip + 운영 SOP 1줄(README 또는 `docs/runbook/account-deletion.md` forward — 본 스토리 OUT, **dev notes 운영 SOP forward-hook 1줄로 대체**).
   - **R2 dump bucket 30일 자동 만료**: bucket lifecycle policy로 30일 후 자동 객체 삭제 — Cloudflare 콘솔 측 설정. 본 스토리 코드 변경 0건(NFR-R5 + C6 정합 — *"30일 추가 보관 후 자동 파기"*는 인프라 측 lifecycle SOT). dev notes 운영 SOP forward-hook 1줄.

5. **AC5 — Mobile `(tabs)/settings/account-delete.tsx` 신규 + settings index 메뉴 + AccountDeleteForm**
   **Given** epics.md:802 *"모바일 `(tabs)/settings/account-delete`"* + Story 5.1 `mobile/app/(tabs)/settings/profile.tsx` 가드 패턴 SOT + `mobile/lib/auth.ts` `signOut` SOT + `useAuth` consentStatus SOT, **When** 신규 화면 + 메뉴 항목 추가, **Then**:
   - **`mobile/app/(tabs)/settings/account-delete.tsx` 신규** Expo Router 화면:
     - 진입 가드 ① `useAuth().consentStatus === null` → `<ActivityIndicator />`(bootstrap, Story 5.1 패턴).
     - 진입 가드 ② **`!consentStatus.basic_consents_complete` 가드 미적용** — PIPA Art.35 권리(deps.py:202-206 docstring 정합) — 미동의 사용자도 탈퇴 가능해야 정보주체 권리 봉쇄 X. 안전망 가드 X (탈퇴 자체가 *동의 철회의 최종 형태*).
     - **Confirmation 다이얼로그** — React Native `Alert.alert` 또는 modal 컴포넌트. 본문: *"탈퇴 시 30일 후 모든 데이터가 영구 파기됩니다. 30일 내 같은 Google 계정으로 재로그인 시 안내됩니다."* + 사용자 명시 *"탈퇴 확인"* / *"취소"* 2 버튼.
     - 사유 입력(선택) — `<TextInput multiline maxLength={200}>` 1건. placeholder *"불편한 점이 있으셨다면 알려주세요 (선택)"*. 200자 cap(server-side AC2 SOT 정합).
     - **submit handler**: `useDeleteAccount` mutation 호출(아래) → 성공 시 `signOut()` 호출 → `router.replace("/(auth)/login")`. 실패 시 alert(*"탈퇴 처리 중 오류가 발생했습니다. 다시 시도해 주세요."*).
   - **`mobile/features/settings/useDeleteAccount.ts` 신규** 또는 `mobile/features/onboarding/useHealthProfile.ts` 패턴 정합으로 **`mobile/features/settings/useAccountDelete.ts` 신규**(naming 분리 — Story 5.1 `useUpdateHealthProfile`이 `useHealthProfile.ts`에 collocated이듯, 본 hook은 신규 settings feature directory에 단독):
     - **결정**: 별 feature directory 생성 — `mobile/features/settings/useAccountDelete.ts` + 향후 5.3(데이터 내보내기)도 같은 directory 사용(forward-hook). Story 5.1의 `mobile/features/settings/HealthProfileEditForm.tsx`가 이미 `features/settings/`를 첫 도입했으므로 정합.
     - `mutationFn`: `DELETE /v1/users/me` body 송신(`{reason}` 또는 빈 body). `authFetch`(Story 1.2 SOT) 재사용. `Content-Type: application/json`(reason 송신 시) 또는 헤더 미설정(빈 body).
     - `onSuccess`: callback 노출만 — `signOut`/`router.replace` 호출은 화면 측. `queryClient.clear()` 호출 — 모든 query cache 초기화(profile/macro_goal/notifications 등 stale 데이터가 logout 후 잠시 남는 회귀 차단).
     - 에러 매핑: `AuthError` 클래스(Story 1.5 `ProfileSubmitError` 패턴 정합) — status/code/detail. 5xx → 일시 오류 + 다시 시도.
   - **`mobile/app/(tabs)/settings/index.tsx` 메뉴 추가**: items 배열 마지막 항목으로 `'회원 탈퇴'`(로그아웃 다음). 사유: 로그아웃은 일상 액션, 탈퇴는 *되돌리기 어려운* 액션 — UX 정합으로 *마지막 항목*에 배치(이탈 시점 사용자가 의도 확인 1단계). label 색상은 styles 변경 0건(다이얼로그 confirmation으로 의도 확인 충분 — destructive 색상은 다이얼로그 버튼만).
   - **`mobile/app/(tabs)/settings/_layout.tsx` Stack 등록**: `<Stack.Screen name="account-delete" options={{ title: "회원 탈퇴" }} />` 추가(Story 5.1 `profile` 등록 패턴 정합).
   - **사유 입력 UX**: 빈 사유 송신 시 클라이언트는 body `{reason: ""}` 또는 body 미송신 — server side `_validate_reason`이 `""` → None normalize(AC2 SOT). 클라이언트 분기 코드 단순(빈 string 그대로 송신 OK).

6. **AC6 — Web `/account/delete/page.tsx` 신규 + `AccountDeleteForm` client component**
   **Given** epics.md:802 *"Web `/account/delete`"* + Story 5.1 `/settings/profile/page.tsx`(4가드 SSR + Server Component 패턴 SOT) + Story 4.4 `/settings/macro-goal` SOT + `web/src/lib/auth.ts:getServerSideUser` SOT + `web/src/lib/api-fetch.ts:apiFetch`, **When** 신규 페이지 + 폼 + lib 추가, **Then**:
   - **`web/src/app/(user)/account/delete/page.tsx` 신규** Server Component:
     - Next.js 16 metadata: `metadata = { title: "회원 탈퇴 — BalanceNote" }`.
     - **1가드만(Story 5.1과 분리)**: `getServerSideUser()` → `!user` → `redirect("/api/auth/cleanup")`. **basic_consents/automated_decision_consent/profile_completed_at 가드 미적용** — PIPA Art.35 권리(deps.py:202-206 + AC5 정합). 사용자가 어느 동의 단계든 탈퇴 가능.
     - 본문: 한국어 경고 + 30일 grace 안내(epics.md:802 *"탈퇴 시 30일 후 모든 데이터가 영구 파기됩니다"* literal 정합) + `<AccountDeleteForm />` 렌더(client component).
     - **Path 분리 결정**: `/account/delete`는 Story 5.1 `/settings/profile`과 *별 namespace*. 사유: epics.md:802 명시(`Web /account/delete`) + *settings* 네임스페이스는 *프로필/매크로 목표* 같은 *설정 변경*이고 *탈퇴*는 별 격리(우발 진입 차단 — settings menu에서 1단계 더 들어간 path).
     - **메뉴 노출**: web에는 *별 settings index 페이지*가 미존재(Story 5.1 OUT 결정 정합). 본 스토리도 별 menu 통합 OUT — 대시보드 또는 settings/profile 페이지 푸터에 *"회원 탈퇴"* link 1건만 추가(`<Link href="/account/delete">`). **결정 단순화**: dashboard 페이지에 menu 추가 OUT(영업 데모 화면 깔끔함 우위) — *"회원 탈퇴"* link는 `/settings/profile` 페이지 푸터 1건만 추가(Story 5.1 페이지를 import 추가로 1줄 갱신). 사용자가 *프로필 수정* 흐름 끝에서 발견 — UX 정합(자기 데이터 컨트롤 흐름).
   - **`web/src/features/settings/AccountDeleteForm.tsx` 신규** `"use client"`:
     - `react-hook-form` + `zod`(Story 4.4 macro-goal SOT 정합 — Web 폼 표준): `accountDeleteSchema = z.object({ reason: z.string().max(200).optional() })`.
     - confirmation checkbox 1건 — `<input type="checkbox" required>` *"30일 후 모든 데이터가 영구 파기됨을 이해했습니다"* — 미체크 시 zod required 위반 → submit 차단(우발 클릭 차단).
     - 사유 textarea 1건(maxLength=200, placeholder 동일).
     - submit handler: `apiFetch("/v1/users/me", { method: "DELETE", body: JSON.stringify({reason}) })` — 204 응답 → `window.location.href = "/login"` redirect(쿠키 clear는 server 측에서 완료). 실패 시 RFC 7807 분기(detail 표시).
     - **destructive 버튼 스타일**: Tailwind `bg-red-600 hover:bg-red-700` — 사용자 시각 cue(되돌리기 어려운 액션 — Tailwind 토큰 + 명시 라벨 *"탈퇴 확정"*).
   - **`web/src/lib/auth.ts` 변경 0건** — 본 스토리는 신규 SSR fetch 함수 추가 X(`getServerSideUser`만 사용). DELETE는 client component 측에서 `apiFetch` 사용.
   - **OpenAPI schema**: `DELETE /v1/users/me` 신규 endpoint 자동 추가(`pnpm gen:api` 실행으로 web/mobile `api-client.ts` 동기화 — Story 5.1 패턴 정합).

7. **AC7 — `consents`/`meals`/`meal_analyses`/`notifications`/`refresh_tokens` cascade 가드 + Story 1.2 회귀 0건**
   **Given** 모든 user-FK 모델 `ondelete="CASCADE"` baseline + Story 1.2 `current_user`의 `User.deleted_at.is_(None)` 가드 + Story 1.2 `auth.py:_upsert_user_from_google`의 `AccountDeletedError` raise + Story 4.2 `nudge_scheduler.py:_build_eligible_users_query`의 `WHERE u.deleted_at IS NULL` 필터, **When** 본 스토리 추가 cascade 코드 0건 가드, **Then**:
   - **DB FK CASCADE 검증**: `DELETE FROM users WHERE id = X` 1건이 자동으로 `consents`/`meals`/`meal_analyses`/`notifications`/`refresh_tokens` 모든 child rows 삭제(SQL FK constraint level — 명시 cascade 코드 0건). integration test 1건(`api/tests/api/v1/test_users_account_delete.py`): 사용자 + 식단 3건 + 분석 1건 + 알림 1건 + refresh_token 2건 → soft delete + worker hard delete 후 모든 child rows 0건 검증.
   - **soft delete 후 인증 라우트 401 가드**: `current_user`(deps.py:94)가 `User.deleted_at.is_(None)` 필터 — soft-deleted 사용자가 valid JWT로 어떤 endpoint 호출하든 즉시 401(`AccessTokenInvalidError("user not found or deleted")`). 신규 코드 변경 0건 — Story 1.2 baseline. **단위 테스트 1건 추가**: soft delete 직후 `GET /v1/users/me` 호출 → 401 + `code=auth.access_token.invalid`.
   - **soft delete 후 OAuth 재로그인 403 + 한국어 안내 가드**: `auth.py:_upsert_user_from_google`이 `AccountDeletedError(purge_at=...)` raise → 글로벌 핸들러가 RFC 7807 403 + detail 한국어 N일 안내(AC3 SOT). **단위 테스트 1건 추가**(`test_auth_router.py` 확장): soft-deleted 사용자가 `POST /v1/auth/google` 호출 → 403 + `code=auth.account.deleted` + detail substring *"탈퇴 진행 중"* + N일 검증.
   - **nudge sweep cron 가드**: Story 4.2 `_build_eligible_users_query`이 이미 `u.deleted_at IS NULL` 필터(line 89) — soft-deleted 사용자가 활성 상태 push 받지 않음. 신규 코드 변경 0건. 회귀 가드 통합 검증 1건(`test_nudge_scheduler.py` 확장 또는 본 스토리 conftest 통합 — 본 스토리 신규 회귀 테스트 1건: soft delete 후 sweep tick → eligible_count = 0).
   - **회귀 0건 — Story 1.2 / 4.2 / 5.1 baseline**:
     - Story 1.2 `_upsert_user_from_google` raise site는 raise 인자만 변경(`AccountDeletedError(purge_at=...)`) — 기존 `AccountDeletedError("account is deleted")` 호출 1건을 patch.
     - Story 4.2 `_build_eligible_users_query` 변경 0건.
     - Story 5.1 PATCH endpoint 변경 0건(soft-deleted 사용자는 current_user에서 401 차단 — PATCH 진입 미발생).
   - **payment_logs/subscriptions forward-compat**: Epic 6 미구현 — 현 스토리 cascade 대상 X. Epic 6 신규 모델 추가 시 `ondelete="CASCADE"` 강제(deferred-work.md DF134 forward-hook). 현 worker는 모델 신규 추가 시 코드 변경 0건(FK level cascade가 자동).

8. **AC8 — 일반 사용자 자기 탈퇴 audit 미기록 + PIPA Art.35 정합**
   **Given** Story 5.1 AC8 + epics.md:792 *"일반 사용자 자기 수정은 audit 대상 아님 (자기 데이터 권리 — 관리자 수정만 audit 대상, Epic 7)"* + prd.md:1010 NFR-S5 마스킹 + PIPA Art.35 정보주체 권리 정합, **When** 본 스토리 DELETE endpoint, **Then**:
   - DELETE endpoint에 `Depends(audit_admin_action)` 미적용. Story 7.x admin endpoint(`DELETE /v1/admin/users/{user_id}` 가설)와 *분리* — Story 5.1 패턴 1:1 정합.
   - **사용자 권리 정당화**: PIPA Art.35 정보주체 권리(열람·정정·삭제·처리정지)는 자기 데이터에 대한 *권리*. 자기가 자기를 탈퇴한 액션을 audit log에 기록 + 30일 grace 후에도 audit log 보존하는 것은 *권리 봉쇄 + 과잉 추적*(deletion 후에도 audit log가 사용자 식별자 유지하면 PIPA 즉시 삭제 의무 위반).
   - structlog `users.account.deleted` event는 *system log SOT*(Sentry/Loki/Railway 로그) — 운영 모니터링 목적, audit_log 테이블 아님. NFR-S5 마스킹(`user_id u_{8char}` + `reason_provided` boolean only — *사유 raw text 본문 X*).
   - **운영 모니터링 SOT**: `users.deletion_reason` DB 컬럼(soft delete 후 30일 grace 동안 보존, hard delete 시 cascade 사라짐). 운영자/admin이 *exit interview* 분석 시 본 컬럼 SELECT(Epic 7 admin 화면 forward — 본 스토리 OUT). 30일 후 자동 파기 — 데이터 최소화 정합.
   - **회귀 가드**: `app/api/deps.py:audit_admin_action` Dependency가 본 endpoint에 wire 미진입 검증(unit test 1건 — endpoint signature inspection, Story 5.1 `audit_admin_action` 가드 패턴 1:1 정합).

9. **AC9 — 단위 테스트 + 회귀 0건 + 통합 검증**
   **Given** Story 5.1 baseline pytest 1020 passed/11 skipped/0 failed + coverage 85.20% + ruff/format/mypy/tsc/lint 0 errors, **When** 본 스토리 종료, **Then**:
   - **신규 단위 테스트 ~22건**:
     - `api/tests/api/v1/test_users_account_delete.py` 신규 ~9건:
       1. DELETE happy-path 사유 미송신(204 + `users.deleted_at` set + `deletion_reason=NULL` + `updated_at` bump).
       2. DELETE happy-path 사유 송신(`{reason: "..."}` → 204 + `deletion_reason=raw text`).
       3. DELETE 사유 빈 string(`{reason: ""}` → 204 + `deletion_reason=NULL` — `_validate_reason` normalize 회귀 가드).
       4. DELETE 사유 200자 초과(`{reason: "x"*201}` → 400 + `code=validation.error`).
       5. DELETE 인증 미통과(401 — Authorization 헤더 미포함).
       6. DELETE extra forbid(`{reason: "...", unknown: "x"}` → 400).
       7. DELETE 후 GET `/me` 호출 → 401(`User.deleted_at.is_(None)` 가드 회귀).
       8. DELETE 후 다른 active refresh_tokens 모두 revoked(`revoked_at IS NOT NULL`) — 다중 device 격리 검증.
       9. DELETE 멱등성 — 이미 `deleted_at IS NOT NULL` 사용자가 (이론상 401 차단되지만 가설 시나리오) DELETE 호출 시 `deleted_at IS NULL` WHERE 가드로 rowcount=0 + 안전 분기 + audit_admin_action Dependency 미wire 가드(endpoint signature inspection).
     - `api/tests/test_auth_router.py` 확장 ~3건:
       1. soft-deleted 사용자 `POST /v1/auth/google` 재로그인 → 403 + detail substring *"탈퇴 진행 중"* + N일 검증(now() ± 1일 tolerance).
       2. 기존 `test_login_returns_403_when_account_deleted` 회귀 가드 — status=403 + code 검증 invariant.
       3. AccountDeletedError 직접 raise 테스트 — `purge_at` 자동 detail 합성 검증(detail string format).
     - `api/tests/workers/test_soft_delete_purge.py` 신규 ~7건:
       1. 31일 경과 사용자 1건 + 미경과 사용자 1건 → eligible=1, purged=1, 미경과 사용자 보존 검증.
       2. CASCADE 검증 — purge 후 `consents`/`meals`/`meal_analyses`/`notifications`/`refresh_tokens` child rows 0건.
       3. R2 dump bucket 미설정 시 dump skip + 운영 로그 검증(`r2_purge_dump_bucket=""`).
       4. R2 dump bucket 설정 시 PUT 호출 검증(boto3 monkeypatch — `_dump_user_to_r2` 호출 1건 verify).
       5. R2 meal images cleanup — `meals/{user_id}/` prefix list_objects + delete_objects 호출(boto3 monkeypatch).
       6. dump 실패 시 sweep 전체 미중단(per-user 격리 try/except 검증) — 1번 사용자 dump 예외 → 2번 사용자 정상 진행.
       7. cron 등록 검증 — `register_purge_job(scheduler, ...)` 호출 후 `scheduler.get_job(PURGE_JOB_ID)` 존재 + CronTrigger hour=3.
     - `api/tests/db/test_users_deletion_reason_and_index.py` 신규 ~2건:
       1. 0017 alembic upgrade/downgrade roundtrip 멱등.
       2. ORM `User.deletion_reason` nullable=True 직접 set/get + partial index `idx_users_deleted_at_pending_purge` 존재 검증(`pg_indexes`).
     - **Mobile/Web 단위 테스트 0건 추가** — Story 5.1 baseline 정합. tsc + lint baseline 회귀 0건 가드.
   - **본 스토리 종료 시 목표**: pytest **~1042 passed / 11 skipped / 0 failed** + coverage ≥84% 유지(신규 코드 ~600 lines + 신규 테스트 ~22건 = +~70 lines covered, 비례).
   - **회귀 0건 가드**:
     - Story 1.2 `_upsert_user_from_google` 두 raise site는 인자만 변경 — 기존 `test_login_returns_403_when_account_deleted` invariant.
     - Story 4.2 `_build_eligible_users_query`의 `u.deleted_at IS NULL` 필터 — 변경 0건.
     - Story 5.1 PATCH endpoint — 변경 0건.
     - `auth.py:_clear_auth_cookies` rename → `clear_auth_cookies` — auth.py 내부 호출 4건 모두 신규 이름으로 갱신, 외부 호출 0건(grep 검증).
   - **타입 체크**: ruff/format/mypy 0 에러(api) + web/mobile tsc + web lint 0 에러.
   - **OpenAPI schema diff**: 신규 endpoint 1건(`DELETE /v1/users/me`) + `AccountDeleteRequest` type 신규 + `users.deletion_reason` 컬럼은 응답 모델에 노출 X(자기 사용자 응답 schema 변경 0). CI 게이트 통과 의무.
   - **NFR-A5 검증**: mobile/web 폼 Tab 순서 자연(다이얼로그 → 사유 → 확인 버튼). react-hook-form inline error aria-live 자동.

10. **AC10 — sprint-status / Story Status 갱신 흐름 (메모리 정합)**
    **Given** 메모리 정합 *"CS 시작 전 master에서 브랜치 분기 — DS 종료시 commit + push만"* + *"CR 종료 직전 sprint-status/story Status를 review → done으로 갱신해 PR commit에 포함"* + *"새 스토리 브랜치는 항상 master에서 분기"*, **When** 본 스토리 `ready-for-dev` 시점(CS 종료) 및 후속 단계, **Then**:
    - Branch: `story/5.2-account-delete`(master에서 분기 완료 — CS 시작 전 분기 완료).
    - DS 시작: `5-2-회원-탈퇴-soft-delete-grace: ready-for-dev → in-progress` (sprint-status.yaml).
    - DS 종료: `5-2-회원-탈퇴-soft-delete-grace: in-progress → review` + commit + push(메모리 정합 *PR pattern* — DS 종료 시점 PR 생성 X, CR 완료 후 일괄).
    - CR 종료 직전: `review → done` + commit + push(같은 commit에 sprint-status 갱신 포함).
    - PR 생성: CR 완료 후 1회. PR title: `Story 5.2: 회원 탈퇴 + soft delete + 30일 grace + 물리 파기 worker (DS+CR)`. PR body에 *"Closes Story 5.2, AC1-10 + N Task / Subtasks 모두 완료. Epic 5 두 번째 스토리(epic-5 status `in-progress` 유지 — Story 5.3까지 마지막 스토리 진행 후 done 전환)"*.
    - **Epic 5 in-progress 유지**: Story 5.1 시점에 `epic-5: backlog → in-progress` 전환 완료 — 본 스토리는 *epic 첫 스토리 X*라 자동 전환 X. CR 종료까지 in-progress 유지.

## Tasks / Subtasks

### Task 1 — DB 마이그레이션 + ORM 컬럼 + partial index (AC: #1)

- [x] 1.1 `api/alembic/versions/0017_users_deletion_reason_and_purge_index.py` 신규 — 0016 chain + (a) `deletion_reason` Text nullable 컬럼 (b) `idx_users_deleted_at_pending_purge` partial index (`WHERE deleted_at IS NOT NULL`). upgrade/downgrade 멱등.
- [x] 1.2 `api/app/db/models/user.py` — `deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)` 추가(컬럼 위치 `deleted_at` 바로 아래) + `__table_args__`에 `Index("idx_users_deleted_at_pending_purge", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL"))` 등재 + 모듈 docstring에 *"Story 5.2 — `deletion_reason` 컬럼 + partial index (0017 마이그레이션). 본 컬럼은 사용자 탈퇴 시점에 set, 30일 grace 후 cascade hard delete와 함께 사라짐."* 명시.
- [x] 1.3 `api/tests/db/test_users_deletion_reason_and_index.py` 신규 — 0017 alembic upgrade/downgrade roundtrip 1 + ORM nullable=True 직접 set/get + `pg_indexes`에서 partial index 존재 검증 1.

### Task 2 — `AccountDeleteRequest` Pydantic 모델 + `DELETE /me` endpoint + 쿠키/refresh_tokens revoke (AC: #2)

- [x] 2.1 `api/app/api/v1/auth.py` — `_clear_auth_cookies` → `clear_auth_cookies` rename + `__all__` 등재(외부 모듈 사용 정합화). 내부 호출 4건 모두 신규 이름으로 갱신.
- [x] 2.2 `api/app/api/v1/users.py` — `AccountDeleteRequest` BaseModel 신규(`extra="forbid"` + `reason: str | None = Field(default=None, max_length=200)` + `_validate_reason` validator strip + 빈 string normalize None).
- [x] 2.3 `api/app/api/v1/users.py` — `DELETE /me` endpoint 신규(`Depends(current_user)` 단독 + body Optional + `UPDATE users SET deleted_at=now(), deletion_reason=:reason, updated_at=now() WHERE id=:user_id AND deleted_at IS NULL` + `UPDATE refresh_tokens SET revoked_at=now() WHERE user_id=:user_id AND revoked_at IS NULL` + `clear_auth_cookies(response)` + 204 응답).
- [x] 2.4 `api/app/api/v1/users.py` — `users.account.deleted` 이벤트 logging(`_mask_user_id` + `reason_provided` boolean — NFR-S5 정합).
- [x] 2.5 `api/tests/api/v1/test_users_account_delete.py` 신규 ~9건(AC9 정의 — happy/사유/빈사유/200자초과/auth/extra/post-delete-401/refresh-revoke/audit-gate).

### Task 3 — `AccountDeletedError` detail 강화 + 30일 grace 한국어 안내 (AC: #3)

- [x] 3.1 `api/app/core/exceptions.py:AccountDeletedError` — `__init__(detail=None, *, purge_at=None)` 확장 + instance attribute 보존 + `purge_at` 제공 + `detail` 미제공 시 자동 한국어 합성(*"탈퇴 진행 중입니다. {N}일 후 모든 데이터가 영구 파기됩니다. 복구를 원하시면 고객문의로 연락해 주세요."*, N = max(0, (purge_at - now()).days)).
- [x] 3.2 `api/app/api/v1/auth.py:_upsert_user_from_google` — 두 raise site(line 262, 276) 모두 `purge_at = user.deleted_at + timedelta(days=PURGE_GRACE_DAYS)` 계산 후 `AccountDeletedError(purge_at=purge_at)` 송신. `from app.workers.soft_delete_purge import PURGE_GRACE_DAYS` import.
- [x] 3.3 `api/tests/test_auth_router.py` — soft-deleted 재로그인 detail 한국어 substring + N일 검증 1건 + AccountDeletedError 직접 raise detail 합성 검증 1건 + status=403/code invariant 회귀 가드 1건 = 총 3건.

### Task 4 — `app/workers/soft_delete_purge.py` cron worker + lifespan 등록 + R2 dump/cleanup (AC: #4)

- [x] 4.1 `api/app/core/config.py:Settings` — `r2_purge_dump_bucket: str = ""` 추가(default empty, 미설정 시 dump skip).
- [x] 4.2 `api/app/workers/soft_delete_purge.py` 신규 — `PURGE_JOB_ID` / `PURGE_GRACE_DAYS=30` 상수 + `_dump_user_to_r2` helper(JSON dump → `purge-dumps/{user_id}/{date}.json`) + `_cleanup_user_r2_images` helper(`meals/{user_id}/` prefix list/delete batch) + `purge_expired_soft_deleted_users(session_maker, r2_adapter=None)` async function(eligible SELECT + per-user 격리 트랜잭션 + dump → cleanup → DB hard DELETE + stats dict 반환) + `register_purge_job(scheduler, session_maker, r2_adapter=None, redis=None)`(CronTrigger hour=3 KST + replace_existing=True). Sentry transaction `op="purge.sweep"` + per-user span. structlog 마스킹.
- [x] 4.3 `api/app/main.py:lifespan` — `register_purge_job(scheduler, app.state.session_maker, r2_adapter=None)` 1줄 추가(`register_nudge_job` 호출 다음). r2_adapter는 `from app.adapters import r2`로 모듈 자체 주입(boto3 client는 모듈 내부 lazy singleton — 별 instance 주입 불필요).
- [x] 4.4 `api/tests/workers/test_soft_delete_purge.py` 신규 ~7건(AC9 — 31일 경과/미경과 분기 + CASCADE + dump skip/PUT + images cleanup + per-user 격리 + cron 등록).

### Task 5 — Mobile `(tabs)/settings/account-delete` 화면 + `useAccountDelete` 훅 (AC: #5)

- [x] 5.1 `mobile/features/settings/useAccountDelete.ts` 신규 — `useDeleteAccount` mutation(`authFetch` DELETE `/v1/users/me` + body `{reason}` 또는 빈 body + `AccountDeleteError` 클래스 + `queryClient.clear()` onSuccess).
- [x] 5.2 `mobile/app/(tabs)/settings/account-delete.tsx` 신규 — 진입 가드 ① bootstrap (basic_consents 가드 미적용 — PIPA Art.35) + Alert.alert 명시 confirmation 다이얼로그 + TextInput multiline maxLength=200 사유(선택) + submit handler(`signOut` + `router.replace("/(auth)/login")`).
- [x] 5.3 `mobile/app/(tabs)/settings/_layout.tsx` — `<Stack.Screen name="account-delete" options={{ title: "회원 탈퇴" }} />` 추가(Story 5.1 `profile` 등록 패턴 정합).
- [x] 5.4 `mobile/app/(tabs)/settings/index.tsx` — items 마지막 항목 `'회원 탈퇴'` → `navigateTo('/(tabs)/settings/account-delete')` 추가(로그아웃 다음).

### Task 6 — Web `/account/delete` 페이지 + `AccountDeleteForm` (AC: #6)

- [x] 6.1 `pnpm gen:api` — 백엔드 OpenAPI 갱신 후 `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts` 자동 reg. 신규 `DELETE /v1/users/me` endpoint + `AccountDeleteRequest` type 자동 추가.
- [x] 6.2 `web/src/features/settings/AccountDeleteForm.tsx` 신규 `"use client"` — react-hook-form + zod schema(`reason.max(200).optional()`) + confirmation checkbox required + `apiFetch DELETE` + 204 응답 → `window.location.href = "/login"` redirect + RFC 7807 분기 + destructive 버튼 스타일(`bg-red-600`).
- [x] 6.3 `web/src/app/(user)/account/delete/page.tsx` 신규 Server Component — 1가드(`!user` → cleanup, basic_consents/automated_decision_consent 가드 미적용 PIPA Art.35) + 한국어 30일 grace 본문 + `<AccountDeleteForm />` 렌더 + Next.js metadata.
- [x] 6.4 `web/src/app/(user)/settings/profile/page.tsx` — 페이지 푸터에 `<Link href="/account/delete">회원 탈퇴</Link>` 1건 추가(Story 5.1 baseline 회귀 0 — 폼 markup invariant).

### Task 7 — Cascade 가드 + Story 1.2/4.2 회귀 가드 (AC: #7, #8)

- [x] 7.1 `api/tests/api/v1/test_users_account_delete.py` 확장 — integration test 1건(사용자 + 식단 3 + 분석 1 + 알림 1 + refresh_token 2 → soft delete + worker hard delete 후 모든 child rows 0건 검증).
- [x] 7.2 `api/tests/api/v1/test_users_account_delete.py` 확장 — soft delete 후 GET `/v1/users/me` 401 가드 1건 + audit_admin_action Dependency 미wire 가드 1건(endpoint signature inspection).
- [x] 7.3 `api/tests/workers/test_soft_delete_purge.py` 확장 — soft delete 후 nudge sweep tick → eligible_count=0 회귀 가드 1건(또는 `test_nudge_scheduler.py` 확장 — 본 스토리 conftest 통합 결정에 따름).

### Task 8 — sprint-status + 통합 검증 + 회귀 가드 (AC: #9, #10, 전체)

- [x] 8.1 sprint-status `5-2-회원-탈퇴-soft-delete-grace: ready-for-dev → in-progress` (DS 시작 시).
- [x] 8.2 `cd api && uv run pytest -q` — 1020 baseline + ~22 신규(account_delete 9 + auth 3 + purge worker 7 + 0017 + index 2 + cascade 1) = ~1042 passed/11 skipped/0 failed. 회귀 0건. coverage ≥84% 유지.
- [x] 8.3 `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app` 0 에러.
- [x] 8.4 `cd web && pnpm tsc --noEmit && pnpm lint` 0 에러.
- [x] 8.5 `cd mobile && pnpm tsc --noEmit && pnpm lint` 0 에러.
- [x] 8.6 OpenAPI schema diff 검증 — 신규 endpoint 1건(`DELETE /v1/users/me`) + `AccountDeleteRequest` 1 type. `users.deletion_reason` 컬럼은 응답 모델 노출 X(자기 사용자 응답 변경 0).
- [x] 8.7 dev 검증 — 브라우저/Expo manual smoke는 CR/QA 단계로 위임. DS 단계는 단위 테스트 ~1042 passed + tsc/lint 0 errors로 functional verification 완료(DELETE happy/사유/auth + worker eligible/CASCADE + 1.2 회귀 + 4.2 회귀 모두 unit test로 가드).
- [x] 8.8 sprint-status `5-2-회원-탈퇴-soft-delete-grace: in-progress → review` 갱신 완료. commit + push는 본 단계 종료 직후.

## Dev Notes

### 핵심 — 본 스토리는 *PIPA 정보주체 권리 + 30일 grace + 물리 파기 cron*

Story 1.2(`users.deleted_at` 컬럼 + `current_user`의 `deleted_at IS NULL` 가드 + `AccountDeletedError` 403) baseline → Story 4.2(APScheduler `AsyncIOScheduler` lifespan SOT + `register_*_job` 패턴) baseline → Story 5.1(`PATCH /me/profile` + 3 timestamp 의미 분리) baseline 위에 *DELETE endpoint + soft delete 마킹 + 30일 grace cron + 물리 파기*를 신설. epics.md:794-807 정합 — FR5 *"엔드유저는 자기 계정을 삭제(회원 탈퇴)할 수 있다. 시스템은 PIPA 외 관련법 보존 의무 항목 외 모든 사용자 데이터를 즉시 파기한다."*.

**3 cascade 자동 채널**(코드 변경 0건 — DB FK level SOT):
1. **`DELETE FROM users WHERE id = X`** → `consents` / `meals` / `meal_analyses` / `notifications` / `refresh_tokens` 모두 `ondelete="CASCADE"` 자동 cascade.
2. **`current_user` 가드** → soft-deleted 사용자가 valid JWT로 어떤 endpoint 호출해도 즉시 401 (deps.py:94 baseline).
3. **`nudge_scheduler._build_eligible_users_query`** → soft-deleted 사용자 push 자동 제외 (line 89 baseline).

**검증 시점 분리**:
- AC1-3(DB + endpoint + auth) — 단위 테스트로 100% 가드.
- AC4(worker) — 단위 테스트(boto3 monkeypatch + per-user 격리)로 100% 가드.
- AC5-6(mobile/web 폼) — tsc/lint + manual smoke(CR/QA).
- AC7-8(cascade + audit) — integration test + signature inspection.

### `_clear_auth_cookies` → `clear_auth_cookies` rename 사유

Story 1.2 시점에 underscore prefix는 *내부 helper* 의미였으나, 본 스토리에서 **2nd consumer**(`users.py:DELETE /me`)가 등장. underscore prefix 그대로 두고 cross-module import는 *rule-bending* 신호 — Python 컨벤션 정합으로 *명시 public + `__all__` 등재*가 자연스러움. 본 스토리에서 1줄 rename + auth.py 내부 호출 4건 패치 + `__all__` 추가. 외부 호출 0건(grep 검증) — 회귀 영향 0.

대안(검토 후 미채택): (a) `_clear_auth_cookies`를 `app/core/cookies.py` 같은 별 모듈로 추출 — over-engineering(현 baseline 5-line helper는 auth namespace 안에 자연스러움). (b) inline 5-line 복사 — DRY 위반 + 향후 cookie path/SameSite 변경 시 양 site 동시 수정 강제(drift 위험).

### `payment_logs` / `subscriptions` cascade forward-compat (Epic 6 미구현)

epics.md:804 *"cascade 파기(`meals`, `meal_analyses`, `consents`, `subscriptions`, `payment_logs`, `notifications`)"* 명시. 현 baseline에서 `subscriptions` / `payment_logs` 테이블 미존재(Epic 6 backlog). 본 스토리 worker는 *명시 cascade 코드 0건*(DB FK level SOT) — Epic 6 추가 시 신규 모델 `ondelete="CASCADE"` 강제로 자동 통합. 위반 시 worker 코드 변경 0건이지만 *child rows orphan*이 됨 → Epic 6 코드 리뷰에서 ondelete 가드 강제(deferred-work.md DF134 forward-hook).

PIPA 외 보존 의무 항목(epics.md:807 *"`consents`, `payment_logs` 일부"*) — *별 보존 영역에 격리*: 본 스토리에서 `consents`는 `ondelete=CASCADE`로 hard delete 함께 삭제(baseline). 사유: 한국 웰니스 앱은 *의료법 진료기록 10년* 외 상수 보존 의무 부재 — `consents`의 동의 시점·버전·IP 같은 footprint는 *audit log 별 테이블*(Epic 7 audit_logs)에 분리 보존하면 cascade 영향 0(별 keypath FK = `audit_log.actor_id` NULLABLE + `ondelete="SET NULL"`). 본 스토리는 audit_logs 미존재 — Story 7.x 추가 시 결정 wire(deferred-work.md DF135 forward-hook).

`payment_logs`(Epic 6 forward) — 결제 영수증·세금계산서는 한국 부가가치세법 *5년 보존* 의무. Epic 6 추가 시 `payment_logs.user_id` FK는 `ondelete="SET NULL"` + `payment_logs.user_email` 별 컬럼 보존(masked) 패턴 권장 — 본 스토리는 코드 변경 0(forward-hook).

### R2 dump bucket 운영 SOP forward-hook

architecture.md:351 *"회원 탈퇴 grace 30일 데이터는 별 dump bucket(R2) 보관 후 파기"* — 본 스토리는 worker 코드 측 dump 흐름만 구현. *bucket 신규 생성* + *30일 lifecycle policy* 자체는 Cloudflare 콘솔 측 인프라 작업 — 본 스토리 코드 변경 0건. 운영 SOP 1줄(forward-hook for `docs/runbook/account-deletion.md`):

> Cloudflare R2 dashboard에서 `balancenote-purge-dumps` bucket 생성 → Lifecycle Rule 추가 → `Delete objects 30 days after creation` → settings env `R2_PURGE_DUMP_BUCKET=balancenote-purge-dumps` set → app 재시작.

dev/CI 환경은 env 미설정 → dump skip(코드 측 graceful — `r2_purge_dump_bucket=""` 분기). prod 환경은 운영자가 SOP 따라 wire. 본 스토리 OUT(별 polish/runbook 스토리 forward — Story 8.x).

### Cron 시간대 결정 — 새벽 3시 KST

Story 4.2 `nudge_scheduler` SOT 시간대(`_KST = ZoneInfo("Asia/Seoul")`) 정합. 매일 새벽 3시 KST 사유:
- nudge sweep는 매 30분 cycle(0~24시 모두) — peak는 사용자 알림 시간(저녁 8시) 전후. 새벽 3시는 push 발사 ↓ DB load idle peak.
- R2 list_objects + delete_objects는 *I/O 집중* — 단일 노드 fastapi event loop blocking 가능성 ↓.
- *coalesce=True + max_instances=1*(scheduler.py SOT) — 컨테이너 재시작 시 missed window 1회 합쳐 발사 + 동시 실행 cap.

대안(검토 후 미채택): (a) 매시간 — *wasteful*(eligible 사용자 수가 일별 단위라 sweep 빈도 시간 단위 X). (b) `apscheduler-postgres` JobStore 분산 — *over-engineering*(1인 단일 노드 8주 정합 외).

### `data_export_service.py` (Story 5.3) vs purge dump 형식 분리

Story 5.3 `data_export_service.py`(`/v1/users/me/export?format=json|csv`)는 *사용자 권리 행사 시점* — JSON/CSV 다운로드 응답. 본 스토리 dump는 *cron 내부 R2 PUT* — JSON 형식만(CSV 불필요). 두 코드 패스는 별 모듈 — Story 5.3 추가 시 *JSON 형식 SOT*(데이터 모델·키·timestamp 포맷)는 `services/data_export_service.py`로 통합 검토 가능(deferred-work.md DF136 forward-hook). 본 스토리는 dump JSON shape를 *최소 set*(profile + meals 메타 + consents + notifications)으로 신설 — 향후 5.3 추가 시 helper 통합 후 본 worker가 `data_export_service.export_user_data_json(...)` 호출로 갈아끼움(코드 변경 ~5 lines).

### Architecture Compliance

| 영역 | 영향 패턴 | 정합 |
|---|---|---|
| Router (AC2) | architecture.md:704 `users.py` `/users/me DELETE` SOT + Story 5.1 `PATCH /me/profile` 패턴 | 정합 — `DELETE /me` 신규 1 endpoint |
| DB schema (AC1) | architecture.md:297 *Soft delete 사용자 데이터: `users.deleted_at` 마킹 → 30일 grace → 물리 파기 cron* SOT | 정합 — `deletion_reason` 1 컬럼 + partial index 1건 + 0017 alembic |
| Worker (AC4) | architecture.md:705 `workers/soft_delete_purge.py` SOT + Story 4.2 APScheduler 패턴 | 정합 — 신규 worker + lifespan 등록 1줄 |
| OAuth grace (AC3) | architecture.md:874 `auth.py` SOT + Story 1.2 `_upsert_user_from_google`의 `AccountDeletedError` raise | 정합 — `purge_at` instance attr 추가 + 자동 detail 합성 |
| FK CASCADE (AC7) | architecture.md:299 ER 골격(`users → consents/meals/meal_analyses/notifications/refresh_tokens`) + 모든 FK `ondelete="CASCADE"` baseline | 정합 — 코드 변경 0건, FK level SOT 자동 |
| R2 dump (AC4) | architecture.md:351 *grace 30일 데이터 별 dump bucket(R2) 보관 후 파기* + Story 2.2 R2 adapter SOT | 정합 — `_dump_user_to_r2` helper 신규 + `r2_purge_dump_bucket` env 추가 |
| R2 images cleanup (AC4) | architecture.md:702 `data_export_service.py` 분리 + Story 2.2 `meals/{user_id}/` prefix SOT | 정합 — `_cleanup_user_r2_images` `meals/{user_id}/` prefix list/delete |
| Audit 분리 (AC8) | architecture.md:891 `audit_admin_action` Dependency + Story 5.1 AC8 + PIPA Art.35 | 정합 — 자기 탈퇴 미기록, admin 측만 audit (Epic 7) |
| NFR-S5 (AC2 logging) | prd.md masking SOT + Story 5.1 `_mask_user_id` 패턴 | 정합 — `user_id u_{8char}` + `reason_provided` boolean only |

### Library / Framework Requirements

- **Backend**: 신규 의존성 0건. 기존 의존성 모두 활용:
  - `fastapi`/`pydantic`/`sqlalchemy`/`alembic`/`asyncpg`/`structlog` — Story 1.5/4.4/5.1 baseline.
  - `apscheduler` (`AsyncIOExecutor` + `CronTrigger`) — Story 4.2 baseline.
  - `boto3` (`list_objects_v2` + `delete_objects` + `put_object`) — Story 2.2 baseline.
  - `sentry-sdk` (`start_transaction` + `start_span`) — Story 4.2 baseline.
- **Mobile**: 신규 의존성 0건. 기존:
  - `@tanstack/react-query` (Story 1.5 SOT) — `useDeleteAccount` mutation + `queryClient.clear()`.
  - `expo-router` (Story 4.1 + 5.1 SOT) — Stack.Screen 등록 + `router.replace`.
  - React Native `Alert.alert` (RN core, 추가 의존성 0).
- **Web**: 신규 의존성 0건. 기존:
  - `react-hook-form ^7.55` + `@hookform/resolvers ^5.0` + `zod ^3.23` (Story 4.4 + 5.1 SOT 정합).
  - Next.js 16 App Router Server Component(Story 5.1 SOT).
  - `apiFetch` (Story 1.2 SOT) — DELETE method 첫 사용처.

### File Structure Requirements

#### 신규 파일

**Backend (api/):**
- `api/alembic/versions/0017_users_deletion_reason_and_purge_index.py`
- `api/app/workers/soft_delete_purge.py`
- `api/tests/api/v1/test_users_account_delete.py`
- `api/tests/workers/test_soft_delete_purge.py`
- `api/tests/workers/__init__.py`(test directory init — 신규 디렉토리 첫 도입 시)
- `api/tests/db/test_users_deletion_reason_and_index.py`

**Mobile:**
- `mobile/features/settings/useAccountDelete.ts`
- `mobile/app/(tabs)/settings/account-delete.tsx`

**Frontend (web/):**
- `web/src/features/settings/AccountDeleteForm.tsx`
- `web/src/app/(user)/account/delete/page.tsx`

#### 수정 파일 (기존)

**Backend:**
- `api/app/db/models/user.py` — `deletion_reason` 컬럼 + partial index + docstring 갱신.
- `api/app/api/v1/auth.py` — `_clear_auth_cookies` → `clear_auth_cookies` rename + `__all__` + 두 raise site `purge_at` 전달.
- `api/app/api/v1/users.py` — `AccountDeleteRequest` + `DELETE /me` endpoint + `users.account.deleted` 로깅.
- `api/app/core/exceptions.py` — `AccountDeletedError.__init__` 확장(`purge_at` keyword-only + 자동 detail 합성).
- `api/app/core/config.py` — `r2_purge_dump_bucket` settings 추가.
- `api/app/main.py` — lifespan에 `register_purge_job` 1줄 추가.
- `api/tests/test_auth_router.py` — soft-deleted 재로그인 detail 한국어 검증 ~3건 추가.

**Mobile:**
- `mobile/app/(tabs)/settings/index.tsx` — `'회원 탈퇴'` items 마지막 항목 추가.
- `mobile/app/(tabs)/settings/_layout.tsx` — `<Stack.Screen name="account-delete" />` 추가.
- `mobile/lib/api-client.ts` — `pnpm gen:api` 자동 갱신(DELETE endpoint + AccountDeleteRequest type).

**Frontend (web/):**
- `web/src/app/(user)/settings/profile/page.tsx` — 페이지 푸터에 `<Link href="/account/delete">` 1건 추가.
- `web/src/lib/api-client.ts` — `pnpm gen:api` 자동 갱신(동일).

### Testing Requirements

- **신규 단위 테스트 ~22건** (AC9 Task 분포):
  - Backend pytest:
    - `test_users_account_delete.py` 9 + cascade integration 1 + soft-delete-401 가드 1 + audit gate 1 = ~12건
    - `test_auth_router.py` 확장 3건
    - `test_soft_delete_purge.py` 7건
    - `test_users_deletion_reason_and_index.py` 2건
  - Mobile/Web: 0건(Story 5.1 baseline 정합 — Web jest 미도입). tsc + lint 0 errors 회귀 가드.
- **종료 시 목표**: pytest **~1042 passed / 11 skipped / 0 failed**, coverage ≥84% 유지.
- **회귀 0건 핵심 가드**:
  - Story 1.2 `_upsert_user_from_google` 두 raise site는 인자만 변경 — `test_login_returns_403_when_account_deleted` invariant.
  - Story 1.2 `clear_auth_cookies` rename — auth.py 내부 호출 4건 패치, 외부 grep 호출 0건.
  - Story 4.2 `_build_eligible_users_query`의 `u.deleted_at IS NULL` 필터 변경 0건.
  - Story 5.1 PATCH endpoint 변경 0건(soft-deleted 사용자는 current_user에서 401 차단).
- **OpenAPI schema diff**: `DELETE /v1/users/me` endpoint 1건 + `AccountDeleteRequest` type 1건. CI 게이트 통과 의무.
- **NFR-A5 검증**: mobile `Alert.alert` 다이얼로그 + web checkbox/textarea Tab 순서 자연. react-hook-form aria-live 자동.

### Previous Story Intelligence (Story 5.1)

Story 5.1 CR 결과 적용 학습(2026-05-07):
- **Mobile 저장 toast 가시성** — `setSavedAt + router.back()` 동기 호출은 React Native paint 전 unmount 트리거 → 토스트 0ms 노출. **본 스토리 적용**: 탈퇴 성공 후 `signOut` + `router.replace`는 *즉시 logout flow*라 toast 표시 불필요(login 화면이 자체 컨텍스트). 단, 실패 시 `Alert.alert`로 동기 노출(다이얼로그는 사용자 명시 dismiss까지 보임 — 가시성 0ms 회귀 X).
- **가드 순서 SOT 통일** — `useAuth().user`와 `useHealthProfileQuery().data` 양 SOT race window. **본 스토리 적용**: `useAuth().consentStatus` 단일 SOT만 사용(profile/macro_goal query 미사용 — 탈퇴는 사용자 데이터 prefill 불필요).
- **Defer 누적**: DF130(api-client.ts mobile/web 중복) + DF132(동일 재발) + DF133(OpenAPI 400/403 미선언) — 본 스토리도 *2 SOT 정합* + DELETE endpoint OpenAPI `responses={400, 401}` 미선언으로 동일 패턴 재발. Story 8.4 polish forward 일괄 정리 — 본 스토리 OUT.

### Git Intelligence

최근 5 커밋 분석(2026-05-07 master):
- `a020e6e` Story 5.1 — Epic 5 첫 스토리 정합 + `mobile/features/settings/HealthProfileEditForm.tsx` 첫 도입(본 스토리 `useAccountDelete.ts`도 동일 directory 사용 — settings feature SOT 정합).
- `2e21d8d` Story 4.4 — `MacroGoalPatchRequest` `model_fields_set` SOT(본 스토리 `AccountDeleteRequest` `_validate_reason` validator 패턴 정합 — extra="forbid" + Optional Field).
- `b7f6819` Story 4.2 — APScheduler `register_*_job` 패턴 SOT(본 스토리 `register_purge_job`이 1:1 정합).
- `127134c` Story 4.1 — Stack.Screen 등록 패턴(본 스토리 `account-delete` Stack.Screen 등록 정합).

### Latest Tech Information

- **APScheduler** `4.x` baseline — `AsyncIOScheduler` + `AsyncIOExecutor` + `CronTrigger`. Python 3.13 호환(api/.python-version 정합). 본 스토리 신규 import 0건.
- **boto3** `1.35.x` baseline — `list_objects_v2` paginator + `delete_objects` batch(1000건 cap, R2/S3 표준). 신규 사용처 1 함수(`_cleanup_user_r2_images`).
- **PostgreSQL `partial index`** — `WHERE deleted_at IS NOT NULL` predicate. PG 16+ baseline 정합(Railway PG 16). hot path INSERT/UPDATE 비용 0(deleted=NULL인 활성 사용자 row는 색인 안 함).
- **Next.js 16 App Router** — `metadata` API + Server Component / Client Component 분리. Story 5.1 SOT 정합 — 본 스토리 `/account/delete/page.tsx`도 동일 패턴.
- **React Native `Alert.alert`** — Expo SDK 54 baseline 표준 (Native modal API 호환 — Android/iOS 양 플랫폼 동일 동작). 추가 의존성 0건.

### Project Context Reference

- 프로젝트 메모리 정합:
  - **외주 영업용 포트폴리오** — 본 스토리는 *PIPA 권리 + 30일 grace + 물리 파기 cron*으로 **B4 KPI(컴플라이언스 안전판 명문화)**에 직접 기여. 영업 답변 5종 closing FAQ에서 *"PIPA 정보주체 권리는 어떻게 보장하나요?"* 질문에 본 endpoint + worker + grace 정책으로 SOP 답변(외주 인수인계 시 README 1페이지 forward-hook).
  - **9포인트 데모 시나리오** — 본 스토리는 *데모 시나리오에 직접 노출 X*(영업 데모는 *식단 분석 흐름* 위주). 단, 컴플라이언스 SOP 문서 + 운영 답변 패키지에 명시 — *"우리 앱은 PIPA Art.35 + 즉시 삭제 의무 + 30일 grace 모두 wired되어 있습니다"*.
  - **8주 부팅 + Docker 1-cmd** — APScheduler in-process 단일 노드(Story 4.2 SOT 정합) + boto3 R2 (Story 2.2 SOT 정합) — 추가 인프라 0건. 외주 클라이언트 인수 시 `R2_PURGE_DUMP_BUCKET` env만 set하면 wire 완료(SOP 1페이지).

### References

- [Source: epics.md#794-807] Story 5.2 ACs SOT.
- [Source: prd.md#946] FR5 *"엔드유저는 자기 계정을 삭제(회원 탈퇴)할 수 있다. 시스템은 PIPA 외 관련법 보존 의무 항목 외 모든 사용자 데이터를 즉시 파기한다."*.
- [Source: prd.md#459] C6 *"사용자 데이터 보존: 회원 탈퇴 시(IN #15) 즉시 삭제. 단 법정 보존 의무 항목... PIPA 외 관련법 보존 기간 준수 후 파기."*.
- [Source: architecture.md#297] Soft delete 패턴 SOT.
- [Source: architecture.md#351] R2 dump bucket 30일 추가 보관 SOT.
- [Source: architecture.md#704-705] `users.py DELETE` endpoint + `workers/soft_delete_purge.py` SOT.
- [Source: architecture.md#1088-1092] APScheduler in-process AsyncIOScheduler SOT.
- [Source: api/app/api/deps.py#94] `current_user`의 `User.deleted_at.is_(None)` 가드 baseline (Story 1.2).
- [Source: api/app/api/deps.py#202-206] PIPA Art.35 정보주체 권리 정합 — 자기 데이터 조회/삭제는 동의 게이트와 독립.
- [Source: api/app/api/v1/auth.py#262, #276] `AccountDeletedError` raise site (Story 1.2 baseline).
- [Source: api/app/core/exceptions.py#130-133] `AccountDeletedError` baseline (status=403, code=auth.account.deleted).
- [Source: api/app/workers/scheduler.py] APScheduler lifespan SOT (Story 4.2).
- [Source: api/app/workers/nudge_scheduler.py] `register_*_job` + `_build_eligible_users_query` + `_mask_user_id` 패턴 SOT (Story 4.2).
- [Source: api/app/adapters/r2.py] R2 boto3 client lazy singleton SOT (Story 2.2).
- [Source: api/app/api/v1/users.py#293-352] Story 5.1 `PATCH /me/profile` endpoint 패턴 SOT.
- [Source: api/alembic/versions/0016_users_profile_updated_at.py] alembic chain HEAD + 0017 base.
- [Source: api/app/db/models/refresh_token.py#30] `ondelete="CASCADE"` SOT (FK level cascade — 본 스토리 코드 변경 0건 baseline).
- [Source: api/app/db/models/{consent,meal,meal_analysis,notification}.py] 모든 user-FK ondelete=CASCADE baseline.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m]

### Debug Log References

- alembic 0017 revision name이 `0016_users_profile_updated_at`처럼 32자 한도(`alembic_version.version_num varchar(32)`)에 걸려 `0017_users_deletion_reason_and_purge_index`(42자) → `0017_users_deletion_reason_idx`(30자)로 축약. 실제 partial index 이름은 `idx_users_deleted_at_pending_purge` 그대로 유지.
- `_clear_auth_cookies` → `clear_auth_cookies` rename은 `users.py`가 *2nd consumer*로 cross-module import 시점에 underscore prefix 컨벤션 위배 신호 — `__all__` 등재로 정합화. 외부 호출 0건(grep 검증) — 회귀 0.
- `web/src/features/settings/AccountDeleteForm.tsx`의 `window.location.href = "/login"`이 ESLint `react-hooks/immutability` 경고 발화 → `window.location.assign("/login")`으로 교체(setter X, side-effect는 동등).
- `app/workers/soft_delete_purge.py`의 `result.rowcount` 접근이 SQLAlchemy 정적 타입 `Result[Any]`에서 미노출 → `getattr(result, "rowcount", 0) or 0` 우회.

### Completion Notes List

- **Task 1** — `0017_users_deletion_reason_idx` alembic + `users.deletion_reason` Text nullable + `idx_users_deleted_at_pending_purge` partial index 추가. ORM `User.deletion_reason` Mapped + `__table_args__` 등재. `tests/db/test_users_deletion_reason_and_index.py` 2건 통과(default NULL/ORM round-trip + partial index 존재 검증).
- **Task 2** — `app/api/v1/auth.py` `_clear_auth_cookies` → `clear_auth_cookies` rename + `__all__` 등재. `app/api/v1/users.py` `AccountDeleteRequest` Pydantic(`extra="forbid"` + `reason` Optional + `_validate_reason` validator) + `DELETE /me` endpoint(`Depends(current_user)` 단독 + body Optional + soft delete UPDATE + 활성 refresh_tokens revoke + `clear_auth_cookies` + 204 + `users.account.deleted` 로깅 NFR-S5 마스킹). `tests/api/v1/test_users_account_delete.py` 9 + 통합 1 + 401/audit 가드 1 = 10건 통과.
- **Task 3** — `AccountDeletedError.__init__` 확장(`purge_at` keyword-only + 한국어 detail 자동 합성). `auth.py:_upsert_user_from_google` 두 raise site `purge_at = user.deleted_at + timedelta(days=PURGE_GRACE_DAYS)` 송신. `tests/test_auth_router.py` 확장 3건(invariant 회귀 + 한국어 detail substring + AccountDeletedError 직접 raise unit).
- **Task 4** — `app/workers/soft_delete_purge.py` 신규(`PURGE_GRACE_DAYS=30` + `PURGE_JOB_ID` + `_build_user_dump_payload` JSON shape + `_dump_user_to_r2` PUT + `_cleanup_user_r2_images` list/delete + `_process_single_user_purge` per-user 격리 + `purge_expired_soft_deleted_users` async + `register_purge_job` CronTrigger hour=3 KST + Sentry transaction `op="purge.sweep"` + structlog 마스킹). `app/main.py:lifespan` `register_purge_job` 1줄 추가. `app/core/config.py` `r2_purge_dump_bucket: str = ""` 추가. `tests/workers/test_soft_delete_purge.py` 7 + nudge 회귀 1 = 8건 통과.
- **Task 5** — `mobile/features/settings/useAccountDelete.ts` 신규(`AccountDeleteError` 클래스 + `authFetch DELETE /v1/users/me` mutation + `queryClient.clear()` onSuccess). `mobile/app/(tabs)/settings/account-delete.tsx` 신규(bootstrap 가드만 — basic_consents 가드 미적용 PIPA Art.35 + `Alert.alert` 명시 confirmation + `TextInput multiline maxLength=200` 사유 + 성공 시 `signOut` + `router.replace("/(auth)/login")`). `_layout.tsx` Stack.Screen + `index.tsx` 마지막 항목 메뉴 추가. mobile tsc/lint 0.
- **Task 6** — `IN_PROCESS=1 pnpm gen:api` 실행으로 web/mobile `api-client.ts` 자동 갱신(신규 endpoint 1 + `AccountDeleteRequest` type 1). `web/src/features/settings/AccountDeleteForm.tsx` 신규 client component(react-hook-form + zod `reason.max(200).optional()` + confirmation checkbox required + `apiFetch DELETE` + 204 → `window.location.assign("/login")` + RFC 7807 분기 + destructive 버튼 `bg-red-600`). `web/src/app/(user)/account/delete/page.tsx` 신규 Server Component(1가드 — `!user`만 PIPA Art.35 정합 + 한국어 30일 grace 본문). `/settings/profile/page.tsx` 푸터에 회원 탈퇴 링크 1건 추가. web tsc/lint 0.
- **Task 7** — `tests/api/v1/test_users_account_delete.py` 통합 cascade 테스트 1건 추가(사용자 + consents + meals 3 + meal_analysis 1 + notification 1 + refresh_tokens 2 → DELETE /me → cutoff 31일 강제 → worker → 모든 child rows 0건). `tests/workers/test_soft_delete_purge.py` Story 4.2 회귀 가드 1건 추가(soft-deleted 사용자 nudge sweep eligible_count=0). post-delete 401 + audit gate inspection은 Task 2에 통합.
- **Task 8** — pytest **1042 passed / 11 skipped / 0 failed** (+22 신규) + coverage **85.27%** (+0.07pp). ruff/format/mypy 0 errors. web tsc + lint 0. mobile tsc + lint 0. OpenAPI schema diff: 신규 endpoint 1 (`DELETE /v1/users/me`) + 신규 type 1 (`AccountDeleteRequest`). Story 1.2 / 4.2 / 5.1 회귀 0건. sprint-status `5-2-회원-탈퇴-soft-delete-grace: in-progress → review` 갱신 완료.

### File List

**Backend (api/) — 신규**:
- `api/alembic/versions/0017_users_deletion_reason_idx.py`
- `api/app/workers/soft_delete_purge.py`
- `api/tests/api/v1/test_users_account_delete.py`
- `api/tests/workers/test_soft_delete_purge.py`
- `api/tests/db/test_users_deletion_reason_and_index.py`

**Backend (api/) — 수정**:
- `api/app/db/models/user.py` — `deletion_reason` Text nullable + `idx_users_deleted_at_pending_purge` partial index __table_args__ 등재 + 모듈 docstring 갱신.
- `api/app/api/v1/auth.py` — `_clear_auth_cookies` → `clear_auth_cookies` rename + `__all__` 등재 + 두 raise site `purge_at = user.deleted_at + timedelta(days=PURGE_GRACE_DAYS)` 계산 후 `AccountDeletedError(purge_at=...)` 송신 + `from app.workers.soft_delete_purge import PURGE_GRACE_DAYS` import.
- `api/app/api/v1/users.py` — `AccountDeleteRequest` Pydantic + `DELETE /me` endpoint + `from app.api.v1.auth import clear_auth_cookies` + `from app.db.models.refresh_token import RefreshToken` + 모듈 docstring 갱신.
- `api/app/core/exceptions.py` — `AccountDeletedError.__init__` 확장(`purge_at` keyword-only + 한국어 detail 자동 합성) + `from datetime import UTC, datetime` import.
- `api/app/core/config.py` — `r2_purge_dump_bucket: str = ""` 추가.
- `api/app/main.py` — `register_purge_job` import + lifespan 1줄 등록(scheduler + r2 module 주입).
- `api/tests/test_auth_router.py` — Story 5.2 확장 3건(invariant 회귀 + 한국어 detail substring + AccountDeletedError 직접 raise unit).

**Mobile — 신규**:
- `mobile/features/settings/useAccountDelete.ts`
- `mobile/app/(tabs)/settings/account-delete.tsx`

**Mobile — 수정**:
- `mobile/app/(tabs)/settings/_layout.tsx` — `<Stack.Screen name="account-delete" />` 추가.
- `mobile/app/(tabs)/settings/index.tsx` — items 마지막 항목 `'회원 탈퇴'` 추가.
- `mobile/lib/api-client.ts` — `pnpm gen:api` 자동 갱신(`DELETE /v1/users/me` + `AccountDeleteRequest`).

**Web — 신규**:
- `web/src/features/settings/AccountDeleteForm.tsx`
- `web/src/app/(user)/account/delete/page.tsx`

**Web — 수정**:
- `web/src/app/(user)/settings/profile/page.tsx` — 푸터에 `/account/delete` 링크 1건 추가.
- `web/src/lib/api-client.ts` — `pnpm gen:api` 자동 갱신(동일).

**BMad — 수정**:
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — Story 5.2 status `ready-for-dev → in-progress → review`.
- `_bmad-output/implementation-artifacts/5-2-회원-탈퇴-soft-delete-grace.md` — Status `ready-for-dev → review` + Tasks 모두 [x] + Dev Agent Record 갱신 + Change Log entry.

### Change Log

| Version | Date | Description |
|---------|------|-------------|
| 0.1 | 2026-05-07 | DS 완료 (Amelia) — Story 5.2 회원 탈퇴 + soft delete + 30일 grace + 물리 파기 worker. pytest 1042/11/0 + coverage 85.27% + ruff/mypy 0 + web/mobile tsc/lint 0. Status: in-progress → review. |
| 0.2 | 2026-05-07 | CR 완료 (Amelia, bmad-code-review) — 12 patch(D1 PIPA 우선 dump-failure isolation 포함) + DF132/133/134 defer. PURGE_GRACE_DAYS를 core/config로 이동(api → workers 의존 역전 정정), boto3 sync → asyncio.to_thread, dump key timestamp suffix, math.ceil 보정, tz-naive 가드, cleanup error 분리, misfire_grace=21600s, mobile signOut→clear 순서 정렬, audit-gate route-level 검증, Decimal 명시 직렬화, dump payload None signal. pytest 1043/11/0 + coverage 85.20%. Status: review → done. |

### Review Findings

**Code review** — 2026-05-07 (Amelia, bmad-code-review). Blind Hunter / Edge Case Hunter / Acceptance Auditor 3-layer adversarial. 23 files / +2,764 / -13. 결과: 12 patch 적용, 3 defer(DF132/DF133/DF134), ~21 dismiss.

#### Decision Resolved

- [x] [Review][Decision] **R2 dump 실패 시 DB 물리 삭제 차단 vs 진행** → **(a) PIPA 우선 — dump 실패 시에도 cleanup+DELETE 진행**. `_process_single_user_purge`에서 dump를 inner try/except로 격리, 실패 시 `stats["dump_errors"] += 1` + sentry capture, cleanup + DB DELETE는 계속 진행. PIPA Art.21 30일 mandate 위반 위험 차단. 신규 P12 patch로 적용.
- [x] [Review][Decision] **`meal_analyses` dump payload 포함 여부** → **(a) spec 유지 — 제외**. 분석 결과는 LLM 출력 재계산 가능, dump는 *cold archive* 성격(profile/consents/meals raw + notifications). 운영 복구 완전성 vs 비용/속도 트레이드오프에서 비용 우위. dismiss.

#### Patch (모두 적용)

- [x] [Review][Patch] **`(purge_at - now).days` ceil 보정** [api/app/core/exceptions.py:155-167] — `math.ceil(seconds/86400)`로 변경. 첫 호출 시 "30일 후" 표기 보장.
- [x] [Review][Patch] **boto3 sync → `asyncio.to_thread`** [api/app/workers/soft_delete_purge.py:_dump_user_to_r2/_cleanup_user_r2_images] — `put_object`/`list_objects_v2`/`delete_objects` 모두 `asyncio.to_thread` 위임. event loop 차단 회피.
- [x] [Review][Patch] **R2 dump 키 timestamp suffix** [_dump_user_to_r2:144-156] — `purge-dumps/{user_id}/{yyyy-mm-ddTHHMMSSZ}.json`. same-day 재시도 시 이전 dump 보존.
- [x] [Review][Patch] **cross-module import 방향 정정** [api/app/core/config.py:24-27 + api/app/api/v1/auth.py:42-49 + api/app/workers/soft_delete_purge.py:42] — `PURGE_GRACE_DAYS`를 `app.core.config`로 이동. `auth.py`와 worker 모두 config에서 import. worker는 `__all__`에 재export로 backward-compat.
- [x] [Review][Patch] **AccountDeletedError tz-naive 가드** [api/app/core/exceptions.py:160-164] — `purge_at.tzinfo is None`이면 `replace(tzinfo=UTC)` 정규화. 미래 caller TypeError → 500 변환 차단.
- [x] [Review][Patch] **R2 cleanup 실패 stat 분리** [api/app/workers/soft_delete_purge.py:_process_single_user_purge cleanup catch + sweep aggregation] — `stats["cleanup_errors"]` 신규 + sweep aggregation `cleanup_errors_count` 추가. dump_errors와 분리해 원인 분석 가능.
- [x] [Review][Patch] **register_purge_job misfire_grace_time=21600(6h)** [api/app/workers/soft_delete_purge.py:_PURGE_MISFIRE_GRACE_SECONDS + register_purge_job:add_job] — daily cron 컨테이너 down 흡수. sweep 멱등성으로 늦은 실행 안전.
- [x] [Review][Patch] **`queryClient.clear()` 순서 정렬** [mobile/features/settings/useAccountDelete.ts:78-82 + mobile/app/(tabs)/settings/account-delete.tsx:74-92] — `useAccountDelete` onSuccess에서 `clear()` 제거. 화면 측에서 `signOut → queryClient.clear() → router.replace` 순서로 정렬해 401 refresh race 차단.
- [x] [Review][Patch] **audit_admin_action route-level deps 검증** [api/tests/api/v1/test_users_account_delete.py:test_delete_me_endpoint_does_not_wire_audit_admin_action] — `app.routes` walk + `route.dependant.dependencies` 재귀 검증 추가. signature + route-level 양쪽 channel 모두 가드.
- [x] [Review][Patch] **Decimal 명시 직렬화** [api/app/workers/soft_delete_purge.py:_serialize_value Decimal 분기] — `format(d, 'f')`로 결정성 + scientific notation 차단.
- [x] [Review][Patch] **`_build_user_dump_payload` None 반환** [api/app/workers/soft_delete_purge.py:_build_user_dump_payload + caller] — race(이미 hard-deleted) 시 `None` + caller `if payload is not None` + `purge.dump_user_missing` 경고 로그.
- [x] [Review][Patch] **(D1 신규) dump 실패 isolated → DB DELETE 계속 진행** [api/app/workers/soft_delete_purge.py:_process_single_user_purge dump inner try] — dump를 inner try/except로 격리. 실패 시 `stats["dump_errors"] += 1` + sentry capture 후 cleanup+DELETE 진행. PIPA Art.21 30일 mandate 우선. test `test_purge_dump_failure_does_not_block_hard_delete`로 invariant 가드.

#### Deferred

- [x] [Review][Defer] **dump↔delete 트랜잭셔널 tie 부재** — DF132 (재검토: Epic 8 hardening).
- [x] [Review][Defer] **OpenAPI 422 only declared / 클라이언트 400 분기 (DF99 계열 baseline)** — DF133 (재검토: Story 8.4).
- [x] [Review][Defer] **Android Alert.alert `style: 'destructive'` 미지원** — DF134 (재검토: Story 8.4 모바일 UX polish).

#### Test 결과 (CR 후)

- pytest **1043 passed / 11 skipped / 0 failed** (+1 from CR — D1 invariant test rename + 1 worker isolation test 흡수).
- coverage **85.20%** (-0.07pp vs DS — worker 모듈 라인 증가 흡수).
- ruff/format/mypy 0 errors. mobile tsc/lint 0 errors(pre-existing 4 warnings 무관).
- `soft_delete_purge.py` 87% 커버리지.
