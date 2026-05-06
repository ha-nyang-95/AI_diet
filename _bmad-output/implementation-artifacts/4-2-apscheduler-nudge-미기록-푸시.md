# Story 4.2: APScheduler nudge 미기록 푸시 + 딥링크

Status: done

<!-- Validation: Story 4.1에서 박은 baseline 4컬럼(`notifications_enabled`/`notification_time`/`notification_timezone`/`expo_push_token`) + 4 endpoint + 모바일 권한 흐름 + token 등록 SOT를 본 스토리가 *최초 소비*. 본 스토리에서 (1) `app/adapters/expo_push.py` 신규(Expo push send + receipts handling), (2) `app/workers/scheduler.py` AsyncIOScheduler SOT + lifespan wire, (3) `app/workers/nudge_scheduler.py` 미기록 sweep job, (4) `notifications` 테이블 0014 마이그레이션(멱등 가드), (5) 모바일 push tap → `(tabs)/meals/input` deep link wire, (6) DeviceNotRegistered receipts 처리(token 자동 NULL set + Story 4.1 `revoke_push_token` 재사용)을 박는다. 백엔드 신규 의존성 1건: `exponent-server-sdk>=2.2`. -->

## Story

As a 엔드유저,
I want 알림 ON + 권한 OK + 알림 시간 + 30분 경과 + 당일 식단 미입력 시 *"오늘 저녁 미기록 — 1분 안에 빠른 입력으로 일주일 일관성 유지하세요"* 푸시를 받고, 탭 시 모바일 식단 입력 화면으로 직행하기를,
So that 회식·이동·일정 변경 등으로 식단 입력을 깜빡한 날에도 일주일 일관성이 유지되고, 푸시에서 입력까지의 마찰이 1탭 수준으로 떨어진다.

## Acceptance Criteria

1. **AC1 — `app/adapters/expo_push.py` 신규 (Expo push send + receipts handling)**
   **Given** Story 4.1 AC4 `expo_push_token` 컬럼 + Story 1.1 `expo_access_token` Settings, **When** `api/app/adapters/expo_push.py` 신규, **Then**:
   - `exponent-server-sdk>=2.2` 신규 의존성 추가(`api/pyproject.toml` `[project.dependencies]` + `[[tool.mypy.overrides]]` `exponent_server_sdk.*` 등재).
   - `class ExpoPushAdapter:` 신규 — singleton 패턴(`get_expo_adapter()` 헬퍼). `__init__(access_token)`은 `PushClient(session=Session())` + `Authorization: Bearer {access_token}` header set(설정 시) — `expo_access_token=""` 빈 문자열일 때는 토큰 없이 동작(SDK 자체 허용 — dev 환경 정합, prod는 EAS Console에서 enhanced security mode 활성 시 token 필수).
   - `async def send_nudge(token: str, title: str, body: str, data: dict) -> PushTicket` — 단일 token 전송. `PushMessage(to=token, title=title, body=body, data=data, sound="default", priority="high", channel_id="default")` build → `client.publish_multiple([msg])` 호출 → ticket 1건 반환. `priority="high"`는 Android *"미기록 알림"* 채널(Story 4.1 AC6 `AndroidImportance.HIGH`)과 정합.
   - `async def send_nudges_bulk(messages: list[ExpoPushPayload]) -> list[PushTicket]` — 다건 전송. `client.publish_multiple(...)` chunking은 SDK 내부에서 100건씩 자동 분할(`PushClient.PUSH_NOTIFICATION_CHUNK_LIMIT = 100`) — 본 어댑터는 단일 호출만 wrap.
   - `async def fetch_receipts(ticket_ids: list[str]) -> dict[str, PushReceipt]` — 1-15분 후 receipt 조회. `client.get_receipts(ticket_ids)` 호출 → ticket_id → receipt 매핑 dict 반환. *비동기 polling 미도입* — sync 흐름(send 직후 ticket → 다음 sweep cycle에서 receipts 조회 1회)으로 단순화. MVP는 cron 30분 주기라 자연 polling.
   - **DeviceNotRegistered** receipt 처리는 본 어댑터가 *raw receipts 반환만* — 호출 측(`nudge_scheduler.py`)이 `revoke_push_token()` 호출(Story 4.1 SOT 재사용).
   - `class ExpoPushError(BalanceNoteError):` 5xx 매핑(adapter boundary error). 서브클래스 2: `ExpoPushUnavailableError`(EAS API 일시 장애 — 503 등) / `ExpoPushAuthError`(401 — `expo_access_token` 만료/회전 필요). transient 5xx는 `tenacity` retry 3회(1s/2s/4s backoff — Story 3.6 `llm_router.py` 패턴 정합). 영구 4xx는 즉시 raise(retry X).
   - **graceful**: send 자체 실패(네트워크/EAS API 장애) 시 nudge_scheduler가 swallow + Sentry capture — *cron 잡은 다음 사이클에서 재시도*(반복 발생 시 `expo_access_token` 회전 SOP `docs/runbook/secret-rotation.md` 갱신).
   - **NFR-S5 마스킹 정합**: push payload(`title`/`body`/`data`)에 사용자 PII 미포함 — 일반 카피 + URL deep link만(`data.url = "balancenote://meals/input"`). `expo_push_token` 자체는 PII 분류 외(Story 4.1 정합 — Sentry/LangSmith 룰셋 추가 X).

2. **AC2 — `app/workers/scheduler.py` 신규 (AsyncIOScheduler SOT + lifespan integration)**
   **Given** `apscheduler>=3.11` 기존 의존성(Story 1.1) + `architecture.md:1088` *APScheduler in-process AsyncIOScheduler + FastAPI lifespan SOT*, **When** `api/app/workers/__init__.py` + `api/app/workers/scheduler.py` 신규, **Then**:
   - `apscheduler.schedulers.asyncio.AsyncIOScheduler` 단일 인스턴스(module-level singleton — 1인 8주 단일 노드 정합, multi-replica는 Story 8.5 hardening forward).
   - `def build_scheduler() -> AsyncIOScheduler:` — `timezone="Asia/Seoul"` SOT(Story 4.1 `notification_timezone` default 컬럼 정합) + `executors={"default": AsyncIOExecutor()}` + `job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 600}` (10분 grace — 서버 재시작·short downtime 시 missed window 발사 정책).
   - `async def start_scheduler(app: FastAPI) -> None:` / `async def shutdown_scheduler(app: FastAPI) -> None:` — lifespan 통합 헬퍼.
   - **환경 분기**: `settings.environment in {"ci", "test"}` 시 `start_scheduler` 호출 즉시 return(테스트 안정성 — pytest 격리). `dev/staging/prod` 만 실 시작.
   - `app.state.scheduler: AsyncIOScheduler | None` (None이면 disabled — 테스트 외 진입 시 `app.state.scheduler is None`이면 잡 등록 skip + warn log).

3. **AC3 — `app/workers/nudge_scheduler.py` 신규 (미기록 sweep cron job)**
   **Given** `app/workers/scheduler.py:start_scheduler` 진입 후, **When** `api/app/workers/nudge_scheduler.py` 신규 + 잡 등록, **Then**:
   - **잡 trigger**: `CronTrigger(minute="*/30", timezone="Asia/Seoul")` — 매 30분 sweep(00:00 / 00:30 / 01:00 / ...). architecture.md:1091 *"매일 19:30/20:30 KST"*는 *기본 알림 시간 20:00 + 30분 + 21:30 = 21:30/22:00*의 기존 가정 — 사용자별 `notification_time` 다양화로 30분 주기 sweep + 시간 매칭으로 일반화. 30분 주기 cron 부담은 무시 수준(SELECT 1건 + 적격 0-N건 push send).
   - **적격 사용자 sweep query**: `users` LEFT JOIN `meals` LEFT JOIN `notifications`(0014 신규).
     ```sql
     SELECT u.id, u.expo_push_token, u.notification_time
     FROM users u
     WHERE u.deleted_at IS NULL
       AND u.notifications_enabled = true
       AND u.expo_push_token IS NOT NULL
       AND ((u.notification_time + INTERVAL '30 minutes')::time
            BETWEEN ((:now_kst - INTERVAL '30 minutes')::time) AND :now_kst::time)
       AND NOT EXISTS (
         SELECT 1 FROM meals m
         WHERE m.user_id = u.id
           AND m.deleted_at IS NULL
           AND (m.ate_at AT TIME ZONE 'Asia/Seoul')::date = :today_kst
       )
       AND NOT EXISTS (
         SELECT 1 FROM notifications n
         WHERE n.user_id = u.id
           AND n.kind = 'unrecorded_meal'
           AND n.kst_date = :today_kst
       )
     ```
     - `now_kst`: `datetime.now(ZoneInfo("Asia/Seoul"))`. `today_kst`: `now_kst.date()`.
     - 30분 윈도우 매칭 — `notification_time + 30min`이 *"방금 지나간 30분 구간"*에 포함된 사용자만 sweep(예: now=20:30 KST sweep cycle은 `notification_time = 19:30~20:00` 사용자 발사). late-arrive 발사는 `misfire_grace_time=600`(10분)으로 짧은 downtime 보정.
     - 자정 cross 처리: KST `notification_time`이 23:30이면 +30분 = 24:00 = 다음날 0시. `(time + interval)::time`은 0시로 wrap — sweep cycle은 0시 시점에 매칭. 단순 시간 비교는 day boundary 미인식이라 `(notification_time + 30min)::time` cast로 wrap 강제.
     - **자정 cross 미기록 정의**: KST 자정 기준 *오늘* meals 0건. 23:30 알림 사용자가 24:00 cycle에서 발사되면 *내일* 자정 직후에 발사되는 셈 — `today_kst` 정의도 발사 cycle 기준이라 정합. (이론상 가능한 edge: 사용자가 23:00에 식단 1건 입력했는데 23:30 알림 — `today_kst.meals`가 1건이라 skip — 정상 동작).
   - **발사 흐름 (per 적격 사용자)**: (1) `expo_push_adapter.send_nudge(token, NUDGE_TITLE, NUDGE_BODY, {"url": "balancenote://meals/input", "kind": "unrecorded_meal"})` 호출 → ticket 반환. (2) ticket 결과 분기: `status="ok"` → `notifications` row INSERT(`kind='unrecorded_meal'`, `kst_date=today_kst`, `expo_ticket_id=ticket.id`). `status="error"` 즉시 응답: `details.error == "DeviceNotRegistered"` → `revoke_push_token()` 호출(Story 4.1 SOT 재사용) + `notifications` row INSERT 안함(다음 cycle 재발사 회피는 token NULL set으로 자동 차단). 그 외 error는 Sentry capture + skip(다음 cycle 재시도).
   - **Sentry transaction**: `op="nudge.sweep"` 1건 + 사용자별 child span `op="nudge.send"` — Story 3.3 `analysis.pipeline` 패턴 정합. attributes: `users_eligible_count` / `nudges_sent_count` / `device_not_registered_count` / `transient_error_count`.
   - **structlog**: `nudge.sweep.start`(now_kst, today_kst) → `nudge.sweep.eligible`(user_count) → 사용자별 `nudge.sent`(masked user_id `u_{8char}`) / `nudge.skipped`(reason) → `nudge.sweep.complete`(success_count, error_count). NFR-S5 정합 — token raw 로깅 X.

4. **AC4 — FastAPI lifespan에 scheduler start/shutdown wire (`app/main.py`)**
   **Given** `api/app/main.py` 기존 lifespan(Story 3.3 4 자원 + Story 3.8 LangSmith init), **When** scheduler init/shutdown 자원 5번째 추가, **Then**:
   - `lifespan()` 진입 후 `app.state.checkpointer` init 직후 try/except 블록 신규 — `from app.workers.scheduler import start_scheduler, shutdown_scheduler, build_scheduler` import + `app.state.scheduler = build_scheduler() if settings.environment not in {"ci", "test"} else None` + `if app.state.scheduler is not None: register_nudge_job(app.state.scheduler, app.state.session_maker, app.state.redis); app.state.scheduler.start()`.
   - **graceful 분기**: scheduler 시작 실패(`SchedulerAlreadyRunningError` 등) 시 log.error + `app.state.scheduler = None` (Story 3.3 checkpointer 패턴 정합 — 부팅 차단 X).
   - **자원 의존성**: `session_maker is None` 또는 `redis is None`이면 잡 등록 skip + warn — push send는 DB·Redis 양쪽 의존(USERS/MEALS sweep + 향후 멱등 캐시 옵션).
   - cleanup 단계 — `getattr(app.state, "scheduler", None) is not None`이면 `await shutdown_scheduler(app)`(`scheduler.shutdown(wait=False)` — async lifespan 정합 + 기존 잡 종료 무대기). 다른 자원 cleanup과 동일 try/except graceful.
   - lifespan 자원 5번째 등록 정합 — Story 3.3의 4 자원(checkpointer/pool/graph/analysis_service) 다음 위치, LangSmith init과 동급 *독립 try/except*.

5. **AC5 — `notifications` 테이블 0014 마이그레이션 (멱등 가드 SOT)**
   **Given** architecture.md:299/392/687 *`notifications` 테이블*, **When** `api/alembic/versions/0014_create_notifications.py` 신규, **Then**:
   - 컬럼: `id BIGSERIAL PRIMARY KEY` / `user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE` / `kind TEXT NOT NULL` / `kst_date DATE NOT NULL` / `sent_at TIMESTAMPTZ NOT NULL DEFAULT now()` / `expo_ticket_id TEXT NULL` / `expo_receipt_status TEXT NULL` / `expo_receipt_error TEXT NULL`.
   - **CHECK 제약**: `ck_notifications_kind` `kind IN ('unrecorded_meal')` — Story 4.4 `weekly_report_ready` / Story 5.x `account_deletion_grace` 등 미래 kind 추가는 본 CHECK drop+recreate(Story 1.5 R8 SOP 정합).
   - **UNIQUE 제약**: `ux_notifications_user_kind_date` `(user_id, kind, kst_date)` — *동일 날 동일 kind 1회 발사 SOT*. INSERT race 시 IntegrityError → cron이 swallow + warn(다음 cycle 재시도 시 이미 row 존재라 skip — 멱등 정합).
   - **인덱스**: `idx_notifications_user_kst_date` `(user_id, kst_date)` — Story 4.4 인사이트 카드의 *최근 7일 발사 이력 조회*(forward use)에 활용.
   - downgrade는 인덱스 → CHECK → UNIQUE → 테이블 drop 역순.
   - **ORM 모델 신규**: `api/app/db/models/notification.py:Notification` — Story 1.5 ORM 패턴 정합(`__table_args__`에 CheckConstraint + UniqueConstraint + Index 1지점 SOT, alembic 0014 SQL과 동일 SOT).
   - **`notifications` 테이블 컬럼 의도**: `expo_ticket_id`는 `expo_push_adapter.send_nudge` 직후 ticket id 저장(receipts 후속 polling은 옵션). `expo_receipt_status` / `expo_receipt_error`는 Story 4.4 또는 후속 polish에서 receipts API polling 흐름 도입 시 update — 본 스토리는 nullable로 박고 *send 직후 ticket immediate error*만 처리(`status="error"` from `publish_multiple` 응답).

6. **AC6 — DeviceNotRegistered 자동 token revoke (Story 4.1 `revoke_push_token` SOT 재사용)**
   **Given** `notification_service.revoke_push_token` 멱등 SOT(Story 4.1 AC4), **When** Expo push send ticket 응답 또는 receipts에서 `details.error == "DeviceNotRegistered"` 수신, **Then**:
   - `nudge_scheduler.py`의 ticket 분기에서 직접 호출 — `await revoke_push_token(db, user)` (Story 4.1 export 그대로 import).
   - 이후 sweep cycle은 `expo_push_token IS NOT NULL` 필터로 자동 제외 — 영구 token cleanup 정합.
   - 사용자가 재로그인 또는 *알림 설정*에서 *"다시 요청"* 액션 시 `register_push_token` 재호출(Story 4.1 AC11) → 새 token으로 회복.
   - **다른 receipt error 처리 (MVP scope)**: `MessageTooBig` / `MessageRateExceeded` / `MismatchSenderId` / `InvalidCredentials` 등 4xx 분류 받으면 Sentry `capture_message(level="error")` + skip. token revoke X(원인 다름). Story 8.4 polish에서 분류별 처리 정교화 forward.

7. **AC7 — Mobile push tap → `(tabs)/meals/input` deep link wire**
   **Given** Story 4.1 AC9 `setupNotificationTapListener` + `getLastNotificationResponse` 골격, **When** `mobile/lib/push.ts` + `mobile/app/_layout.tsx` 통합, **Then**:
   - **데이터 페이로드 SOT**: `data.kind = "unrecorded_meal"` + `data.url = "balancenote://meals/input"` (백엔드 `nudge_scheduler.py`가 동일 SOT로 발송).
   - `mobile/lib/push.ts`에 `setupGlobalPushHandler(router)` 신규 export — Expo Router `Router` instance를 받아서 (1) `addNotificationResponseReceivedListener` 등록 (foreground/background tap), (2) `Notifications.setNotificationHandler({ handleNotification: async () => ({ shouldShowAlert: true, shouldPlaySound: true, shouldSetBadge: false }) })` 등록(앱 활성 상태에서도 알림 노출 — UX 정합).
   - listener 핸들러: `response.notification.request.content.data?.url`이 `string` + 시작 prefix `balancenote://`이면 `router.push("/(tabs)/meals/input")` 호출. 그 외는 ignore(보안 — 외부 URL injection 차단).
   - **cold start 처리** (Story 4.1 W8 흡수 — `getLastNotificationResponse` deprecated → `useLastNotificationResponse` migration): `useLastNotificationResponse()` hook을 `mobile/app/_layout.tsx`(또는 `(tabs)/_layout.tsx`)에서 호출 → useEffect로 1회 처리(deps `[lastResponse?.notification.request.identifier]` — 동일 알림 중복 처리 차단). path matching + `router.replace("/(tabs)/meals/input")` (cold start는 replace로 history 정합).
   - `getLastNotificationResponse()` 함수는 deprecated 메모만 남기고 *유지*(기존 호출자 분리 후 다음 스토리에서 제거 — Story 8.4 polish forward). 본 스토리는 *신규 호출자가 useLastNotificationResponse를 사용*하도록만 강제.
   - **`app.json` plugin entry** (Story 4.1 AC6 정합 — 변경 X): `expo-notifications`의 `icon`/`color`만 명시. iOS push aps-environment / Android FCM v1 setup은 EAS dev build 시점에 자동 처리(Story 4.1 `docs/runbook/push-notifications-dev.md` §3-§4 정합).

8. **AC8 — 푸시 메시지 카피 + 모듈 SOT**
   **Given** epics.md:741 *"오늘 저녁 미기록 — 1분 안에 빠른 입력으로 일주일 일관성 유지하세요"*, **When** `app/workers/nudge_scheduler.py`에 카피 module-level 상수 SOT, **Then**:
   - `NUDGE_TITLE = "오늘 저녁 미기록"` / `NUDGE_BODY = "1분 안에 빠른 입력으로 일주일 일관성 유지하세요"` — module-level frozen.
   - **i18n forward**: 영어 카피는 Story 8.6 영업 자료 시점에 추가(외주 클라이언트별 카피 customization은 인수 후 — 본 스토리는 KO 1지점 SOT). 위치는 `app/workers/nudge_scheduler.py` (도메인 카피 — `app/i18n/`이 만들어지면 forward 이전).
   - 카피 변경 SOP: 본 모듈 상수 변경 + Sentry transaction attribute 갱신 + 단위 테스트 갱신(`test_nudge_scheduler.py:test_payload_uses_canonical_copy`). DB row(`notifications`)에는 카피 미저장 — 사후 카피 변경 시 history 호환 정합.

9. **AC9 — 단위 테스트 ~22건 신규 + 회귀 0건**
   **Given** 본 스토리 변경 영역, **When** `pytest` + `tsc --noEmit` 실행, **Then**:
   - **`api/tests/adapters/test_expo_push.py`** ~6건: `send_nudge` ticket success / `send_nudge` 401 → `ExpoPushAuthError` raise / `send_nudge` 503 → tenacity retry 3회 후 `ExpoPushUnavailableError` / `send_nudge` 4xx 영구 → 즉시 raise / `send_nudges_bulk` 100건 chunking 위임 검증 / `fetch_receipts` happy path.
   - **`api/tests/workers/test_nudge_scheduler.py`** ~10건: sweep query 적격 0건 → 발사 0 / 적격 1건 happy → ticket success + notifications row INSERT / `notifications_enabled=false` 사용자 제외 / `expo_push_token IS NULL` 사용자 제외 / `deleted_at IS NOT NULL` 사용자 제외 / 당일 KST `meals` 1건 이상 사용자 제외 / 동일 날 동일 kind row 존재 시 skip (멱등) / DeviceNotRegistered ticket → `revoke_push_token` 호출 검증 / transient EAS API 실패 시 swallow + Sentry capture / 자정 cross 23:30 + 30분 → 0:00 sweep 시 매칭.
   - **`api/tests/db/test_notifications_table.py`** ~2건: 0014 upgrade 후 컬럼·CHECK·UNIQUE 검증 / `(user_id, kind, kst_date)` UNIQUE 위반 IntegrityError.
   - **`api/tests/test_main_lifespan.py`** ~2건: scheduler init 성공 시 `app.state.scheduler` 존재 + jobs ≥ 1 / `environment="test"` 시 `app.state.scheduler is None`.
   - **`api/tests/workers/test_scheduler.py`** ~2건: `build_scheduler` timezone `Asia/Seoul` 정합 / `start/shutdown` 호출 시 `running` 상태 transition.
   - **모바일 (`pnpm tsc --noEmit` + `pnpm lint` 게이트만)**: jest 인프라 부재(Story 4.1 W1 deferred — Story 8.4 polish forward) — `mobile/lib/push.ts:setupGlobalPushHandler` / `_layout.tsx` `useLastNotificationResponse` wire는 tsc + lint 통과만 검증. 실 device 검증은 CR/QA 단계 책임.
   - **회귀 가드**: Story 1.x/2.x/3.x/4.1 기존 테스트 모두 통과 의무. `users` 테이블 변경 X / 기존 테이블 회귀 0건. lifespan 변경은 Story 3.3 4 자원 + Story 3.8 LangSmith init 동작 무영향 가드(`test_main_lifespan.py` 기존 테스트 통과).
   - **타입 체크**: ruff/format/mypy 0 에러 + mobile/web tsc 0 에러.
   - **coverage**: 현 baseline 84.90%(Story 4.1 done) → 본 스토리 종료 시 ≥84% 유지.

10. **AC10 — `docs/runbook/push-notifications-dev.md` §5 갱신 + Story 4.4 forward 메모**
    **Given** Story 4.1 신규 doc, **When** 본 스토리 시점 §5 갱신, **Then**:
    - §5 *실 push 발송 dev 검증* 단락에 *"서버 측 send는 Story 4.2(본 스토리)에서 도입"* → *"본 스토리 도입됨 — `app/workers/nudge_scheduler.py` cron이 30분 주기 sweep + Expo push send"* 갱신.
    - 신규 §8 *Cron sweep dev 검증* 신규: (1) `EXPO_ACCESS_TOKEN` env 설정 또는 빈 문자열 dev 모드, (2) `apscheduler --debug` 활성 SOP, (3) 사용자 테스트 fixture 셋업(`notification_time=now+30min - 5min` + `meals` 0건 + `notifications_enabled=true` + `expo_push_token=ExponentPushToken[…]`), (4) sweep 직접 호출(`python -m app.workers.nudge_scheduler --once`) 또는 자연 cron 대기.
    - **`docs/runbook/secret-rotation.md` §4** 신규 — `EXPO_ACCESS_TOKEN` 키 회전 5단계(EAS Console *"Access Tokens"* > *Generate* → Railway prod env 갱신 → 신구 동시 운영 24h overlap → 구 token revoke → Sentry alert 모니터링).

11. **AC11 — 의존성 + Settings + .env.example 갱신**
    **Given** 백엔드 Settings, **When** 신규 의존성 + env 추가, **Then**:
    - `api/pyproject.toml` `[project.dependencies]`에 `"exponent-server-sdk>=2.2"` 1줄 추가. `[[tool.mypy.overrides]]` `module = ["exponent_server_sdk.*"]` 등재 (현 mypy strict 정합).
    - `api/app/core/config.py` Settings 변경 X — `expo_access_token: str = ""` 이미 Story 1.1에 등록되어 있음.
    - `.env.example`에 `EXPO_ACCESS_TOKEN=` 1 줄 주석 형태 추가(*"EAS Console > Access Tokens — prod에서 enhanced security mode 활성 시 필수"*).
    - `uv lock` 실행 후 `uv.lock` 갱신 — 신구 lock SHA diff는 1 패키지(`exponent-server-sdk` + transitive deps `requests`/`urllib3` 등 — 기존 의존성에 이미 있을 가능성 높음).

12. **AC12 — Story 4.1 forward hooks 흡수 (W8 deprecated migration)**
    **Given** Story 4.1 deferred-work `W8 — getLastNotificationResponse deprecated`, **When** 본 스토리 시점 흡수, **Then**:
    - `mobile/app/_layout.tsx`(또는 `(tabs)/_layout.tsx`) cold start deep link 처리에 `useLastNotificationResponse()` hook 사용 — React 스케줄링 통합 (AC7 정합).
    - `getLastNotificationResponse` 함수는 본 스토리에서는 *유지* — 외부 호출자 0건이면 Story 8.4 polish에서 제거 forward. 변경 시 deferred-work.md `W8 → CLOSED (2026-05-XX, Story 4.2)` 업데이트.

13. **AC13 — Architecture compliance + 신규 SOT 체크리스트**
    **Given** architecture.md, **When** 본 스토리 신규 컴포넌트 위치, **Then**:
    - `api/app/adapters/expo_push.py` ↔ architecture.md:696 / 880 / 914 정합.
    - `api/app/workers/scheduler.py` + `api/app/workers/nudge_scheduler.py` ↔ architecture.md:703-705 / 1088-1092 정합.
    - `api/app/db/models/notification.py` ↔ architecture.md:687 정합.
    - `notifications` 테이블 ↔ architecture.md:299 / 392 정합.
    - 모바일 deep link wire ↔ architecture.md:988 *FR31 mobile push handler + Expo Router deep link* 정합.
    - **alembic revision chain**: `0014_create_notifications` + `down_revision="0013_users_notification_settings"` (Story 4.1 마지막 revision). 본 스토리는 0014 단일 revision — 충돌 0.

## Tasks / Subtasks

### Task 1 — 신규 의존성 + Settings + .env (AC: #1, #11)

- [x] 1.1 `api/pyproject.toml` `[project.dependencies]`에 `"exponent-server-sdk>=2.2"` 추가.
- [x] 1.2 `[[tool.mypy.overrides]]`에 `exponent_server_sdk.*` module ignore 등재.
- [x] 1.3 `api/.env.example`에 `EXPO_ACCESS_TOKEN=` 주석 형태 추가.
- [x] 1.4 `cd api && uv lock && uv sync --all-extras` 실행 → lock 갱신 + import smoke `python -c "import exponent_server_sdk; print(exponent_server_sdk.__version__)"`.

### Task 2 — `app/adapters/expo_push.py` 신규 (AC: #1, #6)

- [x] 2.1 `api/app/adapters/expo_push.py` 신규 — `ExpoPushAdapter` 클래스 + `get_expo_adapter()` lazy singleton(Story 3.6 `anthropic_adapter.py:_get_anthropic_client` 패턴 정합).
- [x] 2.2 `send_nudge(token, title, body, data) -> PushTicket` async 헬퍼.
- [x] 2.3 `fetch_receipts(ticket_ids) -> dict[str, PushReceipt]` async 헬퍼.
- [x] 2.4 `tenacity` retry — `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), retry=retry_if_exception_type((ConnectionError, TimeoutError, ExpoPushUnavailableError)))` 패턴.
- [x] 2.5 `ExpoPushError` / `ExpoPushUnavailableError` / `ExpoPushAuthError` 3 도메인 예외 (`api/app/core/exceptions.py`에 추가, Story 4.1 `NotificationTimeInvalidFormatError` 패턴 정합).
- [x] 2.6 `api/tests/adapters/test_expo_push.py` 6건 PASS.

### Task 3 — `notifications` 테이블 + ORM 모델 (AC: #5, #13)

- [x] 3.1 `api/alembic/versions/0014_create_notifications.py` 신규 — `revision="0014_create_notifications"`, `down_revision="0013_users_notification_settings"`.
- [x] 3.2 upgrade: 테이블 + CHECK + UNIQUE + 인덱스 1건. downgrade: 역순.
- [x] 3.3 `api/app/db/models/notification.py:Notification` ORM 모델 — `__table_args__` SOT.
- [x] 3.4 dev DB에서 `alembic upgrade head` 실행 → 검증 → `alembic downgrade -1` → 재 upgrade 멱등 검증.
- [x] 3.5 `api/tests/db/test_notifications_table.py` 2건 PASS.

### Task 4 — `app/workers/scheduler.py` SOT (AC: #2, #4)

- [x] 4.1 `api/app/workers/__init__.py` 빈 모듈 신규.
- [x] 4.2 `api/app/workers/scheduler.py` — `build_scheduler` / `start_scheduler` / `shutdown_scheduler` 3 helper.
- [x] 4.3 `api/tests/workers/__init__.py` + `api/tests/workers/test_scheduler.py` 2건 PASS.

### Task 5 — `app/workers/nudge_scheduler.py` 잡 (AC: #3, #6, #8)

- [x] 5.1 `api/app/workers/nudge_scheduler.py` 신규 — `NUDGE_TITLE` / `NUDGE_BODY` 상수 + `register_nudge_job(scheduler, session_maker, redis)` + 잡 함수 `async def sweep_unrecorded_meals(session_maker)`.
- [x] 5.2 sweep query — `select(User).where(...).join_left(...)` SQLAlchemy 2.0 async 패턴 + `with session_maker() as db: ...`.
- [x] 5.3 적격 사용자별 push send + ticket 분기 (DeviceNotRegistered → revoke_push_token / 그 외 error → Sentry capture).
- [x] 5.4 `notifications` row INSERT (ticket success 시) + UNIQUE 충돌 IntegrityError swallow + warn(멱등 정합).
- [x] 5.5 Sentry transaction `op="nudge.sweep"` + 사용자별 child span `op="nudge.send"`.
- [x] 5.6 structlog NFR-S5 정합 — token raw 로깅 X, user_id `u_{8char}` 마스킹.
- [x] 5.7 `api/tests/workers/test_nudge_scheduler.py` 10건 PASS.

### Task 6 — `app/main.py` lifespan wire (AC: #4)

- [x] 6.1 `lifespan()` 진입 후 `app.state.checkpointer` init 직후 scheduler init try/except 블록 추가.
- [x] 6.2 `register_nudge_job(...)` 호출 + `app.state.scheduler.start()` (env in {"ci","test"} 분기 적용).
- [x] 6.3 cleanup 단계에 `await shutdown_scheduler(app)` graceful 추가.
- [x] 6.4 `api/tests/test_main_lifespan.py` 2건 신규 PASS — 기존 테스트 회귀 0건.

### Task 7 — Mobile push tap deep link wire + cold start (AC: #7, #12)

- [x] 7.1 `mobile/lib/push.ts`에 `setupGlobalPushHandler(router)` 신규 export — `Notifications.setNotificationHandler` + `addNotificationResponseReceivedListener`.
- [x] 7.2 `mobile/app/_layout.tsx`(또는 `(tabs)/_layout.tsx`)에 `setupGlobalPushHandler` mount + `useLastNotificationResponse()` cold start 1회 wire.
- [x] 7.3 deferred-work.md `W8` CLOSED 업데이트(같은 PR commit).
- [x] 7.4 `cd mobile && pnpm tsc --noEmit && pnpm lint` 0 에러.
- [x] 7.5 dev 검증 — DS 스코프는 자동 게이트만. 실 device push tap 통합 검증은 CR/QA 단계.

### Task 8 — Runbook 갱신 (AC: #10)

- [x] 8.1 `docs/runbook/push-notifications-dev.md` §5 *실 push 발송 dev 검증* 갱신.
- [x] 8.2 §8 *Cron sweep dev 검증* 신규(4 단계 SOP).
- [x] 8.3 `docs/runbook/secret-rotation.md` §4 *EXPO_ACCESS_TOKEN 회전* 5단계 신규.

### Task 9 — 통합 검증 + sprint-status 갱신 (AC: 전체)

- [x] 9.1 `cd api && uv run pytest -q` — 843 baseline + ~22 신규 = ~865 passed/11 skipped/0 failed. 회귀 0건.
- [x] 9.2 `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app` 0 에러. coverage ≥84%.
- [x] 9.3 `cd mobile && pnpm tsc --noEmit && pnpm lint` 0 에러.
- [x] 9.4 `cd web && pnpm tsc --noEmit` 0 에러(영향 없음 — 회귀 가드).
- [x] 9.5 OpenAPI schema diff 검증 — 신규 endpoint 0건(라우터 변경 X — cron 잡만 추가).
- [x] 9.6 sprint-status `4-2-apscheduler-nudge-미기록-푸시: review` 전환 + commit + push.

## Dev Notes

### 핵심 — 본 스토리는 *Story 4.1 baseline 자원의 첫 실 소비*

Story 4.1이 박은 **(a) `users` 4컬럼 + (b) 백엔드 4 endpoint + (c) 모바일 권한 흐름 + (d) token 등록·해제 흐름**을 본 스토리가 *실 push 발송 cron + 딥링크*로 활성화한다. 회귀 0건 가드 우선 — 백엔드 lifespan에 자원 5번째(scheduler) 추가가 Story 3.3(checkpointer/pool/graph/analysis_service) + Story 3.8(LangSmith init) 동작을 깨면 안 된다.

### 동의 게이트 정합 (PIPA Art.22(3) marketing 분리 — 미기록 알림은 서비스 이행)

- 미기록 알림은 *마케팅 메시지가 아닌 서비스 이행*(식단 관리 앱 본연 기능 — 사용자가 입력 의지 있는 흐름의 정상 진행)이다 → PIPA Art.22(3) marketing 별 동의 게이트 무필요(Story 4.1 정합).
- *광고/프로모션* 알림은 별 게이트 — Growth 단계 forward.
- `users.notifications_enabled = true` (Story 4.1 default `true`) AND `expo_push_token IS NOT NULL` (사용자 명시 토큰 등록) 두 가드가 *암묵 opt-in* 정합.

### Architecture Compliance

| 영역 | 영향 패턴 | 정합 |
|---|---|---|
| Adapter (AC1) | architecture.md:696 / 880 / 914 `expo_push.py` adapter | 정합 — 본 스토리에서 신규 |
| Worker — scheduler (AC2) | architecture.md:703-705 / 1088-1092 APScheduler in-process | 정합 — `app/workers/scheduler.py` SOT 신규 |
| Worker — nudge job (AC3) | architecture.md:704 `nudge_scheduler.py` | 정합 — 본 스토리에서 신규 |
| DB Schema (AC5) | architecture.md:299 / 392 / 687 `notifications` 테이블 | 정합 — 0014 마이그레이션 + ORM 모델 |
| FastAPI lifespan (AC4) | architecture.md:1090 *FastAPI lifespan에 시작/종료* | 정합 — Story 3.3 4 자원 패턴 정합 |
| Frontend mobile (AC7) | architecture.md:988 FR31 mobile push handler + Expo Router deep link | 정합 — `mobile/lib/push.ts` + `_layout.tsx` wire |
| Settings (AC11) | architecture.md `expo_access_token` (Story 1.1 등록) | 정합 — 변경 X |

### Library / Framework Requirements

- **`exponent-server-sdk>=2.2`** (신규 백엔드 의존성). PyPI [exponent-server-sdk 2.2.0](https://pypi.org/project/exponent-server-sdk/), maintainer expo-community. 핵심 API:
  - `PushClient(session=Session(), access_token=...)` — singleton.
  - `client.publish_multiple([PushMessage(to, title, body, data, sound, priority, channel_id)])` → `list[PushTicket]`. SDK 내부 100건 chunking 자동.
  - `client.get_receipts([ticket_id])` → `dict[ticket_id, PushReceipt]`.
  - `PushTicketError` / `PushReceiptError` typed exceptions.
- **`apscheduler>=3.11`** (Story 1.1 기존 의존성). 핵심 API:
  - `AsyncIOScheduler(timezone="Asia/Seoul", executors={"default": AsyncIOExecutor()})`.
  - `scheduler.add_job(func, CronTrigger(minute="*/30"), id="nudge_sweep", coalesce=True, max_instances=1, misfire_grace_time=600)`.
  - `scheduler.start()` / `scheduler.shutdown(wait=False)`.
  - **APScheduler 4.0**은 2026-05 시점 미정식 — `add_schedule`/`Task` 분리 등 breaking. 본 스토리는 3.11.x 유지(架構 정합 + production stable).
- **모바일 신규 의존성 0건** — `expo-notifications` ~55(Story 4.1) `useLastNotificationResponse` hook + `setNotificationHandler` API 그대로 사용. `expo-router` ~6(Story 1.x) `Router.push` SOT.
- **DeviceNotRegistered 처리 패턴**: Expo 공식 권고 — *"receipt error 시 token DB에서 즉시 삭제 + 다음 재등록 round-trip 시 회복"*([Expo Push API docs 2026](https://docs.expo.dev/push-notifications/sending-notifications/)).

### File Structure Requirements

#### 신규 파일

**Backend:**
- `api/app/adapters/expo_push.py`
- `api/app/workers/__init__.py`
- `api/app/workers/scheduler.py`
- `api/app/workers/nudge_scheduler.py`
- `api/app/db/models/notification.py`
- `api/alembic/versions/0014_create_notifications.py`
- `api/tests/adapters/test_expo_push.py`
- `api/tests/workers/__init__.py`
- `api/tests/workers/test_scheduler.py`
- `api/tests/workers/test_nudge_scheduler.py`
- `api/tests/db/test_notifications_table.py`

#### 수정 파일 (기존)

**Backend:**
- `api/pyproject.toml` — `exponent-server-sdk>=2.2` + mypy override 추가
- `api/app/main.py` — lifespan에 scheduler init/shutdown 5번째 자원 wire
- `api/app/core/exceptions.py` — `ExpoPushError`/`ExpoPushUnavailableError`/`ExpoPushAuthError` 3건 추가
- `api/.env.example` — `EXPO_ACCESS_TOKEN=` 주석 형태
- `api/tests/test_main_lifespan.py` — scheduler init 검증 2건 추가

**Mobile:**
- `mobile/lib/push.ts` — `setupGlobalPushHandler(router)` 신규 export
- `mobile/app/_layout.tsx` (또는 `(tabs)/_layout.tsx`) — `setupGlobalPushHandler` mount + `useLastNotificationResponse` cold start wire

**Docs:**
- `docs/runbook/push-notifications-dev.md` — §5 갱신 + §8 신규
- `docs/runbook/secret-rotation.md` — §4 신규

**Sprint:**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `ready-for-dev → in-progress → review`
- `_bmad-output/implementation-artifacts/deferred-work.md` — `W8 CLOSED (2026-05-XX, Story 4.2)` 갱신

### Testing Requirements

- **단위 테스트 신규 ~22건**: adapter 6 + scheduler 2 + nudge_scheduler 10 + notifications table 2 + lifespan 2.
- **현 baseline (Story 4.1 done)**: pytest 843 passed / 11 skipped / 0 failed + coverage 84.90%.
- **본 스토리 종료 시 목표**: pytest ~865 passed / 11 skipped / 0 failed + coverage ≥84% 유지.
- **회귀 0건 가드**: Story 1.x/2.x/3.x/4.1 기존 모든 테스트 통과 의무. 특히 `test_main_lifespan.py` 기존 4 자원(checkpointer/pool/graph/analysis_service) 회귀 가드 + Story 3.8 LangSmith init 회귀 가드.
- **타입 체크**: ruff/format/mypy 0 에러 + mobile/web tsc 0 에러.
- **Mobile 단위 테스트**: jest 인프라 부재(Story 4.1 W1) — Story 8.4 polish forward. 본 스토리 모바일 변경(`push.ts:setupGlobalPushHandler` + `_layout.tsx` cold start wire)은 tsc + lint + 실 device 검증(CR/QA 단계).
- **OpenAPI schema diff**: 0건 — cron 잡만 추가, 라우터 변경 X.

### NFR-S5 마스킹 정합

- **Push payload (`title`/`body`/`data`)**: PII 미포함 — `NUDGE_TITLE` / `NUDGE_BODY` 상수 + `data.url` deep link만. Sentry/LangSmith 마스킹 룰셋 추가 X.
- **`expo_push_token` 자체**: Expo 자체 식별자, 사용자 신원과 결합 X(Story 4.1 정합). `_SENTRY_MASKED_KEYS` 변경 X.
- **structlog `nudge.send` 이벤트**: `user_id`는 `u_{first8char}` 마스킹(Story 1.5 NFR-S5 패턴 정합). `expo_push_token` raw 로깅 X — `token_prefix=token[:20]`만 디버깅 용도.
- **`notifications` 테이블 row**: `expo_ticket_id` / `expo_receipt_status` / `expo_receipt_error`는 PII 분류 외(Expo 자체 식별자/표준 error code). audit_log 연동 무필요(자기 데이터, FR37 정합 — admin 액션만 audit 대상).

### Story 4.4 Forward Hooks

본 스토리에서 박는 자원을 Story 4.4(인사이트 카드 + 매크로 목표 조정)가 소비 가능:
- `notifications` 테이블 — Story 4.4 *주간 리포트 도착 알림*(architecture.md `kind = 'weekly_report_ready'` 추가) + Story 5.x *회원 탈퇴 grace 알림* 등 미래 kind 흡수 가능.
- `app/workers/scheduler.py` SOT — Story 4.3/4.4 weekly report aggregation cron 또는 Story 5.2 soft-delete purge cron(architecture.md:705) 등 추가 잡 등록 가능.
- `app/adapters/expo_push.py` — Story 4.4 인사이트 카드 *"매크로 목표 조정 알림"* 또는 Story 5.x *알레르기 위반 즉시 경고* 등 추가 push 카피 추가 가능(`send_nudge` 시그니처는 일반화되어 있음).

## Previous Story Intelligence

### Story 4.1 Done (2026-05-06) 핵심 학습

- **CR 3-layer adversarial 패턴**: Blind Hunter / Edge Case Hunter / Acceptance Auditor 3 레이어 → ~50 raw → 5 patch + 16 defer + 16 dismiss. 본 스토리 CR도 동일 — cron edge case(자정 cross / 시계 drift / scheduler 중복 시작 / DeviceNotRegistered race / 멱등 윈도우 등) 유효.
- **lifespan 독립 try/except 패턴**: Story 3.3 4 자원이 *각 자원 init 실패가 다른 자원·앱 부팅 자체를 막지 않음*. 본 스토리 scheduler 5번째 자원도 동일 패턴 — DB 미가동 / Redis 실패 / scheduler 시작 실패 모두 graceful 분기 + 잡 등록 skip + warn.
- **race-free `UPDATE ... RETURNING` 패턴**: Story 1.5 / 4.1 `update_settings`. 본 스토리 `notifications` INSERT는 UNIQUE `(user_id, kind, kst_date)` SOT — IntegrityError swallow로 멱등 정합(retry 시 자동 차단).
- **Story 4.1 PUSH_PROMPTED_STORAGE_KEY SOT 통합 패턴**: 양 callsite의 키를 push.ts SOT 1지점으로 통합 → 변경 시 한 곳만 수정. 본 스토리 `NUDGE_TITLE`/`NUDGE_BODY` 카피도 동일 — `nudge_scheduler.py` 모듈 상수 SOT.
- **Story 4.1 `register_push_token` user-swap atomic 패턴**: race window 가드 + Story 8.4 hardening note. 본 스토리 receipts DeviceNotRegistered 분기는 *기존 `revoke_push_token` 멱등 SOT* 그대로 재사용 — 추가 race 가드 무필요(`UPDATE users SET expo_push_token = NULL WHERE id = ...`는 atomic).
- **Story 4.1 `Platform.OS` resolveDevicePlatform 패턴**: 하드코드 `'ios'` 회귀 차단. 본 스토리는 *모바일 → 백엔드* 방향 변경 X — backend → mobile 발사 흐름이라 platform 분기 무영향(Expo Push API가 token 자체에 platform 인코딩).

### Story 3.9 Done (2026-05-06) 핵심 학습

- **TOCTOU race 가드**: Vision cost cap의 INCR-first atomic charge + refund 패턴. 본 스토리는 `notifications` UNIQUE constraint가 atomic 가드 — Redis 카운터 회피 정합(DB UNIQUE가 SOT).
- **CF-Connecting-IP source 검증 패턴**: trust 검증 통과 시에만 trust. 본 스토리는 IP 영역 무영향(cron 잡은 사용자 인증 흐름 X).
- **결정성 노드 retry 0회 패턴**: `_node_wrapper(deterministic=True)` Story 3.6/3.9. 본 스토리 `expo_push_adapter`는 *transient* error retry(network/5xx 3회 backoff) — 결정적 노드와 별 카테고리.

### Story 3.8 Done (2026-05-05) 핵심 학습

- **Sentry transaction `op=...pipeline` 패턴**: `analysis.pipeline` op + 노드별 child span. 본 스토리 `op="nudge.sweep"` + 사용자별 `op="nudge.send"` child span 동일 패턴.
- **fail-closed 강제 분기**: LangSmith init 실패 시 `LANGCHAIN_TRACING_V2=false` 강제. 본 스토리 scheduler 시작 실패 시 `app.state.scheduler = None` + 잡 등록 skip — graceful 정합(차단 X, 다음 재시작 시 재시도).

### Story 3.6 Done (2026-05-04) 핵심 학습

- **`llm_router.py` 듀얼-LLM fallback 패턴**: tenacity retry 3회 1s/2s/4s. 본 스토리 `expo_push_adapter`도 동일 패턴 — `(ConnectionError, TimeoutError, ExpoPushUnavailableError)` retry, 4xx 영구 즉시 raise.
- **Adapter boundary error translation**: openai/anthropic permanent error → typed `LLMRouterUnavailable`/`PayloadInvalid`. 본 스토리 `expo_push.py`도 raw `requests.HTTPError` → typed `ExpoPushAuthError`/`ExpoPushUnavailableError` 매핑 boundary.

### Story 1.1 Done (2026-04-27) 핵심 학습

- **`apscheduler>=3.11` 등록**: pyproject.toml 첫 declaration. 본 스토리 첫 실 사용. mypy override 이미 등재 — 추가 작업 X.
- **`expo_access_token` Settings 등록**: Story 1.1 첫 declaration. 본 스토리 첫 실 사용. .env.example placeholder만 추가.

## Project Structure Notes

- **Branch**: `story-4-2` (master에서 분기 — 메모리 정합 *"새 스토리 브랜치는 항상 master에서 분기"*).
- **PR 패턴**: feature branch + PR + merge 버튼(메모리 정합 *"PR pattern for master integration"*).
- **DS 종료 시점**: commit + push만(메모리 정합 — PR은 CR 완료 후 한 번에 생성).
- **CR 종료 직전**: sprint-status / Story Status `review → done` 갱신을 PR commit에 포함(메모리 정합 *"CR 종료 직전 sprint-status/story Status를 review → done으로 갱신"*).

### Sprint Status 갱신 흐름

- 현재: `4-2-apscheduler-nudge-미기록-푸시: ready-for-dev` (CS 종료 시점, `epic-4: in-progress` 유지).
- DS 시작: `4-2-apscheduler-nudge-미기록-푸시: in-progress`
- DS 종료: `4-2-apscheduler-nudge-미기록-푸시: review`
- CR 종료: `4-2-apscheduler-nudge-미기록-푸시: done`(`epic-4`는 in-progress 유지 — Story 4.3/4.4 잔여)

## References

- [Source: `_bmad-output/planning-artifacts/epics.md:731`] — Story 4.2 AC 6건 (AsyncIOScheduler 잡 + Expo Notifications + lifespan + 푸시 메시지 + deep link + 제외 사용자 + 멱등)
- [Source: `_bmad-output/planning-artifacts/epics.md:715`] — Epic 4 목표 + APScheduler in-process + 19:30/20:30 KST 잡 등록
- [Source: `_bmad-output/planning-artifacts/prd.md:652`] — M4 Push Notifications 공급자/트리거(미기록 nudge 자동 전송)
- [Source: `_bmad-output/planning-artifacts/prd.md:982`] — FR29 (사용자 설정 시간 + 30분 + 당일 미기록 자동 푸시) / FR30 (ON/OFF) / FR31 (탭 시 식단 입력 화면 직행)
- [Source: `_bmad-output/planning-artifacts/prd.md:1047`] — NFR-S5 마스킹(push payload PII 미포함 정합)
- [Source: `_bmad-output/planning-artifacts/prd.md:1056-1062`] — NFR-R1~R6 가용성·외부 API fallback·구조화 로깅
- [Source: `_bmad-output/planning-artifacts/architecture.md:299/392/687`] — `notifications` 테이블 SOT
- [Source: `_bmad-output/planning-artifacts/architecture.md:696/880/914`] — `expo_push.py` adapter 위치
- [Source: `_bmad-output/planning-artifacts/architecture.md:703-705`] — `app/workers/` 디렉토리 (`nudge_scheduler.py` + `soft_delete_purge.py`)
- [Source: `_bmad-output/planning-artifacts/architecture.md:1088-1092`] — APScheduler in-process AsyncIOScheduler + FastAPI lifespan SOT + 1인 8주 정합
- [Source: `_bmad-output/planning-artifacts/architecture.md:986-988`] — FR29-31 매핑(`workers/nudge_scheduler.py` + `expo_push.py` + mobile push handler + Expo Router deep link)
- [Source: `_bmad-output/implementation-artifacts/4-1-알림-설정-푸시-권한.md`] — 직전 스토리 SOT(notification_service / notifications router / users 4컬럼 / push.ts) + Dev Notes + CR 5 patches + W8 deferred
- [Source: `_bmad-output/implementation-artifacts/3-9-에픽-3-후-polish.md`] — TOCTOU race 가드 + Sentry transaction 패턴 + 결정성 노드 retry 패턴
- [Source: `_bmad-output/implementation-artifacts/3-8-langsmith-옵저버빌리티-평가-데이터셋.md`] — fail-closed lifespan 분기 패턴
- [Source: `_bmad-output/implementation-artifacts/3-6-인용형-피드백-광고-가드-듀얼-llm.md`] — `llm_router.py` tenacity retry + adapter boundary error translation 패턴
- [Source: `_bmad-output/implementation-artifacts/deferred-work.md`] — W8 (`getLastNotificationResponse` deprecated, Story 4.1 deferred → 본 스토리 흡수)
- [Source: https://pypi.org/project/exponent-server-sdk/] — `exponent-server-sdk` 2.2.0 (latest) PyPI
- [Source: https://github.com/expo-community/expo-server-sdk-python] — Python SDK README + `PushClient` API + chunking + receipts handling
- [Source: https://docs.expo.dev/push-notifications/sending-notifications/] — Expo push API server-side + DeviceNotRegistered receipt 권고 처리
- [Source: https://docs.expo.dev/versions/latest/sdk/notifications/] — `useLastNotificationResponse` hook + `setNotificationHandler` API
- [Source: https://apscheduler.readthedocs.io/en/3.x/userguide.html] — APScheduler 3.11 AsyncIOScheduler + CronTrigger + `timezone='Asia/Seoul'` SOT

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] (Amelia / bmad-create-story workflow, 2026-05-06).

### Debug Log References

- DS 진행 중 단위 테스트 통합 회귀 0건. 모든 13 AC + 9 Task / Subtasks `[x]` 체크 완료.
- DS 검증 게이트 통과: `pytest 867 passed/11 skipped/0 failed` + coverage `84.85%` + ruff/format/mypy 0 에러 + mobile/web tsc 0 에러. Story 4.1 baseline 843 → 867 (+24 신규).
- AsyncIOScheduler `shutdown(wait=False)`은 `@run_in_event_loop` 데코레이션이라 schedule 후 동기 return — 테스트에서 state 전환 검증은 event loop tick 1회 await로 해결. cron 관련 환경 격리: `tests/conftest.py`에서 `settings.environment = "test"` 강제로 lifespan이 scheduler init skip(NFR pytest 격리 정합).
- Self-cron 자정 cross 처리: `(notification_time + 30min)::time` cast 시 `23:30 → 00:00` wrap. lower>upper 분기는 OR 두 범위로 SQL 분기 — 단순 BETWEEN으로는 day boundary 미인식.

### Completion Notes List

- **AC1 — `app/adapters/expo_push.py`**: `ExpoPushAdapter` lazy singleton(`threading.Lock` double-checked locking) + `send_nudge` / `send_nudges_bulk` / `fetch_receipts` 3 helper. SDK가 sync(`requests.Session`)라 `asyncio.to_thread` 위임. tenacity 3회 backoff(1s/2s/4s) + transient subset(`ConnectionError`/`Timeout`/`ExpoPushUnavailableError`) — 영구 4xx는 `_classify_http_error` 매핑 후 즉시 raise(retry X). HTTPError 401 → `ExpoPushAuthError`, 5xx → `ExpoPushUnavailableError`, 그 외 4xx → `ExpoPushError` base. `PushServerError` 5xx는 transient 분류. priority="high" + channel_id="default"는 Android Story 4.1 AC6 채널 SOT 정합.
- **AC2 — `app/workers/scheduler.py`**: `AsyncIOScheduler(timezone="Asia/Seoul")` SOT + `AsyncIOExecutor` + `coalesce=True` / `max_instances=1` / `misfire_grace_time=600`. 3 helper(`build_scheduler` / `start_scheduler` / `shutdown_scheduler`) + environment in {ci,test} 분기. `app.state.scheduler: AsyncIOScheduler | None`.
- **AC3 — `app/workers/nudge_scheduler.py`**: `CronTrigger(minute="*/30", timezone="Asia/Seoul")` 30분 sweep + 적격 SQL 4 가드(`notifications_enabled=true` AND `expo_push_token IS NOT NULL` AND `deleted_at IS NULL` AND 당일 KST `meals` 0건 AND 동일 날 동일 kind row 미존재). 자정 cross는 lower>upper 분기로 OR 두 범위 SQL. ticket 분기: `status="ok"` → `notifications` row INSERT(IntegrityError swallow), `details.error="DeviceNotRegistered"` → `revoke_push_token`(Story 4.1 SOT) + INSERT skip, 그 외 ticket error → Sentry capture + skip. Sentry transaction `op="nudge.sweep"` + 사용자별 child span `op="nudge.send"` + tags(`users_eligible_count` / `nudges_sent_count` / `device_not_registered_count` / `transient_error_count`). structlog 4 이벤트(`nudge.sweep.start` / `nudge.sweep.eligible` / `nudge.sent` / `nudge.skipped` / `nudge.sweep.complete`) — `user_id`는 `u_{first8char}` 마스킹.
- **AC4 — `app/main.py` lifespan**: scheduler 5번째 자원으로 wire. `app.state.checkpointer` init 직후 독립 try/except 블록 — environment in {ci,test} skip / `session_maker is None` skip / 일반 init 실패 graceful(`scheduler = None`). cleanup은 다른 자원 cleanup보다 먼저(잡 백그라운드 thread 우선 정리). Story 3.3 4 자원(checkpointer/pool/graph/analysis_service) 회귀 0건 가드.
- **AC5 — `notifications` 테이블 + ORM (alembic 0014)**: 8 컬럼 + `ck_notifications_kind` IN('unrecorded_meal') + `ux_notifications_user_kind_date` UNIQUE + `idx_notifications_user_kst_date` 인덱스. ORM 모델 `app/db/models/notification.py:Notification` + `__table_args__` SOT(alembic SQL과 동일). `down_revision="0013_users_notification_settings"` chain. dev DB에서 upgrade → downgrade → re-upgrade 멱등 검증 통과. `tests/conftest.py`의 TRUNCATE 목록에 `notifications` 추가(per-test 격리).
- **AC6 — DeviceNotRegistered 자동 token revoke**: `nudge_scheduler.py`의 ticket 분기에서 `revoke_push_token`(Story 4.1 SOT) 직접 호출. 다음 cycle은 `expo_push_token IS NOT NULL` 필터로 자동 제외. 다른 receipt error(MessageTooBig / MessageRateExceeded 등)는 Sentry `capture_message(level="error")` + skip(token revoke X).
- **AC7 — Mobile push tap deep link wire**: `mobile/lib/push.ts`에 `setupGlobalPushHandler(router)` 신규 export — `Notifications.setNotificationHandler` + `addNotificationResponseReceivedListener` 등록. `resolveDeepLinkTarget` 헬퍼가 `data.url`의 `balancenote://` prefix 검증 후 `/(tabs)/meals/input` 반환(외부 URL injection 차단). `mobile/app/_layout.tsx`에 mount + `Notifications.useLastNotificationResponse()` cold-start hook 1회 wire(deps `[lastResponse?.notification.request.identifier]` — 동일 알림 중복 처리 차단). cold-start는 history 정합 위해 `router.replace`. `_globalHandlerInstalled` flag로 멱등(중복 호출 시 listener 1개만 유지).
- **AC8 — 푸시 메시지 카피 SOT**: `NUDGE_TITLE = "오늘 저녁 미기록"` / `NUDGE_BODY = "1분 안에 빠른 입력으로 일주일 일관성 유지하세요"` + `NUDGE_DATA = {"url": "balancenote://meals/input", "kind": "unrecorded_meal"}` (`Final` module-level frozen). epics.md:741 정합. i18n forward는 Story 8.6.
- **AC9 — 단위 테스트 + 회귀 0건**: 신규 24건 — `test_expo_push.py` 7건 + `test_nudge_scheduler.py` 10건 + `test_notifications_table.py` 2건 + `test_main_lifespan.py` 2건 + `test_scheduler.py` 3건. pytest **867 passed/11 skipped/0 failed** + coverage **84.85%** + ruff/format/mypy 0 에러 + mobile/web tsc 0 에러. Story 1.x/2.x/3.x/4.1 회귀 0건 가드 통과.
- **AC10 — Runbook 갱신**: `docs/runbook/push-notifications-dev.md` §5 *서버 측 send Story 4.2 도입됨* 갱신 + §8 *Cron sweep dev 검증* 신규(환경변수/사용자 fixture/직접 호출 SOP/자연 cron/트러블슈팅 5단계). `docs/runbook/secret-rotation.md` §0 표 갱신 + §4 *EXPO_ACCESS_TOKEN 회전 5단계*(신규 token 발급 → Railway secrets 갱신 + 24h overlap → send 도착 검증 → 기존 token revoke → rollback 절차 + 변경 트리거).
- **AC11 — 의존성**: `api/pyproject.toml`에 `exponent-server-sdk>=2.2` 추가 + `[[tool.mypy.overrides]]`에 `exponent_server_sdk.*` + `requests.*` 추가(types-requests 미설치 — `requests`는 SDK transitive). `.env.example` `EXPO_ACCESS_TOKEN=` 코멘트 갱신(Story 4.2 nudge push send + EAS Console enhanced security mode + secret-rotation §4 cross-link). `uv lock` 실행 — `exponent-server-sdk v2.2.0` 추가됨. import smoke 통과.
- **AC12 — Story 4.1 W8 흡수**: `useLastNotificationResponse` hook으로 cold-start 처리 migration 완료. `getLastNotificationResponse` 함수는 deprecated 메모만 남기고 유지(외부 호출자 0건 시 Story 8.4 polish forward). `deferred-work.md` W8 CLOSED 갱신.
- **AC13 — Architecture compliance**: `expo_push.py` (architecture.md:696/880/914) / `app/workers/scheduler.py` + `nudge_scheduler.py` (703-705/1088-1092) / `notifications` 테이블 (299/392/687) / FR31 mobile push handler + Expo Router deep link (988) — 모든 정합. alembic 0014 chain 충돌 0.
- **DS 검증 SOT 게이트**: `pytest 867 passed/11 skipped/0 failed` + coverage `84.85%` + `ruff check` 0 에러 + `ruff format --check` 0 에러 + `mypy app` 0 에러 + `mobile pnpm tsc --noEmit` 0 에러 + `mobile pnpm lint` 0 에러 + `web pnpm tsc --noEmit` 0 에러. Story 1.x/2.x/3.x/4.1 회귀 0건.

### Review Findings

**3-layer adversarial CR (2026-05-06)** — Blind Hunter 33 / Edge Case Hunter 30 / Acceptance Auditor 5 = **68 raw findings → 5 patch + 7 defer + 56 dismiss**.

Patches (적용 완료 — 2026-05-06):

- [x] [Review][Patch] P1 — cold-start `useLastNotificationResponse` + foreground tap listener가 동일 알림에 대해 `router.replace`/`router.push` double-fire — `_handledIdentifiers` Set + `markPushResponseHandled` export로 dedupe [`mobile/lib/push.ts` / `mobile/app/_layout.tsx`]
- [x] [Review][Patch] P2 — `ticket.status` unknown 또는 `ticket.details` non-dict 시 AttributeError 가능 + None error_code Sentry 메시지 비유익 — `if ticket.status != "error"` 명시 분기 + `isinstance(ticket.details, dict)` 가드 + `error_code or 'unknown'` 라벨링 [`api/app/workers/nudge_scheduler.py:sweep_unrecorded_meals`]
- [x] [Review][Patch] P3 — Sentry transaction이 sweep loop raise 시 status 미설정 — `except Exception: transaction.set_status("internal_error"); raise` 추가 [`api/app/workers/nudge_scheduler.py:sweep_unrecorded_meals`]
- [x] [Review][Patch] P4 — `_record_notification`이 IntegrityError 외 transient DB 에러 미잡음 — post-send 블록을 `try/except Exception` 으로 감싸 per-user skip + `transient_error_count` 증가 + Sentry capture로 sweep loop 보존 [`api/app/workers/nudge_scheduler.py:sweep_unrecorded_meals`]
- [x] [Review][Patch] P5 — `test_lifespan_scheduler_initializes_in_dev_environment` 실 scheduler thread leak — `start_scheduler`를 no-op `monkeypatch`로 교체해 thread 생성 자체 차단 [`api/tests/test_main_lifespan.py`]

신규 회귀 가드 테스트 3건 추가(`test_nudge_scheduler.py`):
- `test_sweep_unknown_ticket_status_handled_explicitly` — P2 unknown status 분기 + `capture_message` warning 레벨 검증
- `test_sweep_ticket_details_non_dict_isinstance_guard` — P2 `details=None` + `error_code or 'unknown'` 라벨 검증
- `test_sweep_record_notification_db_transient_does_not_break_loop` — P4 OperationalError raise 시 sweep loop 보존 + Sentry capture 검증

Defer (deferred-work.md 등재):

- [x] [Review][Defer] D1 — push-then-INSERT race window + multi-worker 동시 sweep 시 중복 알림 / shutdown wait=False in-flight 중단(reservation 패턴 도입) — Story 8.5 hardening forward [`api/app/workers/nudge_scheduler.py`]
- [x] [Review][Defer] D2 — `fetch_receipts` 시그니처가 spec(`get_receipts(ticket_ids)`)과 SDK reality(`check_receipts(tickets)`) 차이 + 본 스토리에서 미호출(forward use) — Story 4.4 receipts polling wire-up 시점에 정리 [`api/app/adapters/expo_push.py:fetch_receipts`]
- [x] [Review][Defer] D3 — Mobile jest 인프라 부재로 `setupGlobalPushHandler` / `resolveDeepLinkTarget` / cold-start hook 단위 테스트 0건(tsc + lint만) — Story 8.4 polish forward(Story 4.1 W1 정합) [`mobile/lib/push.ts` / `mobile/app/_layout.tsx`]
- [x] [Review][Defer] D4 — `users` 테이블 sweep query에 `notification_time + INTERVAL '30 minutes'` expression partial index 부재(1k+ 사용자 시 sequential scan) — Story 8.5 performance hardening [`api/alembic/versions/0014_create_notifications.py`]
- [x] [Review][Defer] D5 — `resolveDeepLinkTarget`가 `data.kind` 무시 + 모든 `balancenote://` URL을 `meals/input`로 라우팅 → 미래 `weekly_report_ready` kind 도입 시 misroute — Story 4.4 path 매핑 SOT 도입 시점 정리 [`mobile/lib/push.ts:resolveDeepLinkTarget`]
- [x] [Review][Defer] D6 — receipts polling 미구현 → ticket OK 후 receipt 단계 DeviceNotRegistered 영구 미감지 → 영원히 발사 안 가는 푸시 매일 시도 — Story 4.4 receipt polling wire-up [`api/app/workers/nudge_scheduler.py`]
- [x] [Review][Defer] D7 — `today_kst`가 wrap_midnight cycle(00:00 KST)에서 *발사 cycle 기준* day N+1로 박혀, notification_time=23:30 사용자가 day N에 식단 정상 기록했어도 day N+1 첫 cron tick에서 "오늘 저녁 미기록" 알림 수신. 멱등 가드(NOT EXISTS notifications + UNIQUE)는 정상이지만 *해당 cycle의 alarm semantic*이 "어제 알림 시간의 미기록"인지 "오늘 새 날의 시작"인지 spec 자체 모호. 수정 시 sweep window 범위 + target_kst 매핑 + 회귀 테스트 일괄 갱신 필요 — Story 8.4 polish forward(UX 의사결정 + boundary 테스트 정합) [`api/app/workers/nudge_scheduler.py:sweep_unrecorded_meals` / `_fetch_eligible_users`]

Dismiss 56건 — 자세한 사유는 본 CR 세션 내(triage). 대표 분류: (a) 1인 8주 단일 노드 정합 acknowledged(`apscheduler-postgres` 외부 lock / SELECT FOR UPDATE 등 multi-replica 가드 — Story 8.5 forward); (b) 정합 의도(`_NON_PROD_ENVIRONMENTS == _DISABLED_ENVIRONMENTS` 동일 set / `revoke_push_token` SOT 재사용 / `priority="high"` Expo 표준); (c) cosmetic/over-engineering(useEffect deps 중복 / Fast Refresh leak / alembic CHECK explicit drop / kind magic string 중복); (d) spec wording 정합(`PushMessage` vs `ExpoPushPayload` / `redis is None` 가드 functional impact 0 / 테스트 24건 `~22` 초과 OK); (e) 멱등 SOT가 push API double-call 차단(BETWEEN inclusive boundary user는 `NOT EXISTS notifications` SQL filter가 다음 cycle 자동 제외 — defensive 가드 충분).


**Backend 신규**:
- `api/app/adapters/expo_push.py`
- `api/app/workers/__init__.py`
- `api/app/workers/scheduler.py`
- `api/app/workers/nudge_scheduler.py`
- `api/app/db/models/notification.py`
- `api/alembic/versions/0014_create_notifications.py`
- `api/tests/adapters/test_expo_push.py`
- `api/tests/workers/__init__.py`
- `api/tests/workers/test_scheduler.py`
- `api/tests/workers/test_nudge_scheduler.py`
- `api/tests/db/test_notifications_table.py`

**Backend 수정**:
- `api/pyproject.toml` — `exponent-server-sdk>=2.2` 추가 + mypy override `exponent_server_sdk.*`/`requests.*`
- `api/uv.lock` — `exponent-server-sdk v2.2.0` 추가
- `api/app/main.py` — lifespan에 scheduler 5번째 자원 wire(init + cleanup)
- `api/app/core/exceptions.py` — `ExpoPushError` / `ExpoPushUnavailableError` / `ExpoPushAuthError` 3건 추가
- `api/app/db/models/__init__.py` — `Notification` ORM 등록
- `api/tests/conftest.py` — `notifications` 테이블 TRUNCATE 추가 + `settings.environment = "test"` 강제
- `api/tests/test_main_lifespan.py` — scheduler init 검증 2건 추가

**Mobile 수정**:
- `mobile/lib/push.ts` — `setupGlobalPushHandler(router)` + `resolveDeepLinkTarget` 신규 export + `getLastNotificationResponse` deprecated 메모
- `mobile/app/_layout.tsx` — `setupGlobalPushHandler` mount + `useLastNotificationResponse` cold-start wire

**Root 수정**:
- `.env.example` — `EXPO_ACCESS_TOKEN=` 코멘트 갱신(Story 4.2 nudge push send + secret-rotation §4)

**Docs 수정**:
- `docs/runbook/push-notifications-dev.md` — §5 갱신 + §8 *Cron sweep dev 검증* 신규
- `docs/runbook/secret-rotation.md` — §0 표 갱신 + §4 *EXPO_ACCESS_TOKEN 회전* 5단계 신규

**Sprint**:
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `4-2-apscheduler-nudge-미기록-푸시: ready-for-dev → in-progress → review`
- `_bmad-output/implementation-artifacts/deferred-work.md` — `W8 CLOSED (2026-05-06, Story 4.2)` 갱신
- `_bmad-output/implementation-artifacts/4-2-apscheduler-nudge-미기록-푸시.md` — Status `ready-for-dev → review` + Tasks/Subtasks `[x]` + Dev Agent Record + File List + Change Log

### Change Log

| Date | Author | Change |
|---|---|---|
| 2026-05-06 | Amelia (DS) | Story 4.2 DS 완료 — APScheduler nudge cron + Expo push adapter + notifications 테이블 + lifespan 5번째 자원 wire + mobile cold-start deep link migration. Status: ready-for-dev → in-progress → review. |
| 2026-05-06 | Amelia (CR) | Story 4.2 CR 완료 — 3-layer adversarial(Blind 33 / Edge 30 / Auditor 5) → 5 patch + 7 defer + 56 dismiss. P1(cold-start dedupe) + P2(ticket defensive) + P3(Sentry status) + P4(DB transient guard) + P5(test thread leak). 회귀 0건: pytest 870/11/0 + coverage 84.91% + ruff/format/mypy 0 + mobile/web tsc 0 + mobile lint 0. Status: review → done. |
