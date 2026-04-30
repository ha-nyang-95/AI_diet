# Story 2.5: 오프라인 텍스트 큐잉 + 온라인 자동 sync

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **엔드유저**,
I want **오프라인 상태에서 텍스트로 식단을 입력하면 큐잉되어 온라인 복귀 시 자동 sync되기를**,
So that **회식·이동·약한 신호 환경에서도 기록이 끊기지 않는다.**

본 스토리는 Epic 2의 마지막 스토리로, **(a) `mobile/lib/offline-queue.ts` 신규 — AsyncStorage 백킹 텍스트 식단 큐 (`bn:offline-queue:meal:<user_id>` namespace + FIFO 순차 flush + 단일 mutex) + 큐 항목 schema(`client_id`/`raw_text`/`ate_at?`/`parsed_items?`/`attempts`/`last_error?`/`last_attempt_at?`)**, **(b) 백엔드 `POST /v1/meals` `Idempotency-Key` 헤더 처리 — `meals.idempotency_key TEXT NULL` 컬럼 + `(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL` partial UNIQUE index + 동일 키 재송신 시 기존 row 200 반환(INSERT 0 race-free) — W46(Story 2.1 deferred — 앱 백그라운드/킬 mid-mutation 중복 POST) 흡수**, **(c) `useCreateMealMutation` 갱신 — 오프라인 시 큐잉(throw 대신 enqueue), 온라인 시 `Idempotency-Key` 헤더 첨부 POST + 큐 자동 flush 트리거**, **(d) `(tabs)/meals/index.tsx` *"동기화 대기 중"* 배지 — 큐 size > 0 시 헤더 영역에 노출 + 큐 항목들을 list 상단에 optimistic 카드(회색 + 동기화 대기 배지)로 함께 표시**, **(e) 사진 입력 오프라인 차단 — `useOnlineStatus()` `!isOnline` 시 `(tabs)/meals/input.tsx`의 카메라/갤러리 탭 onPress가 *"사진은 온라인에서 처리 가능 — 텍스트 입력 또는 온라인 시 다시 시도"* Alert + 진입 차단**, **(f) 지수 backoff 재시도 정책 — sync 실패 시 1초 → 2초 → 4초(+jitter) 3회 재시도 후 큐 잔존 + 사용자 manual retry CTA**, **(g) 4xx validation 에러는 큐에서 제거 + 사용자 안내(서버가 거부한 식단은 큐 잔존이 무의미 — 영구 실패)**, **(h) 네트워크 복귀 자동 flush — `useOnlineStatus()` offline → online 전이 시 `flushQueue()` 자동 호출(`mobile/lib/offline-queue.ts` 단일 진입점)**, **(i) Epic 2 종료 baseline 박음 — Story 2.1~2.4의 텍스트/사진/OCR/일별 기록 + 본 스토리의 오프라인 큐잉 = FR12-FR16 5건 모두 baseline 완료, Epic 3 AI 분석 진입 준비 완료**의 baseline을 박는다.

부수적으로 (a) **사진+OCR 흐름의 오프라인 큐잉은 OUT** — 사진 입력은 R2 presigned URL 발급 + R2 PUT + Vision API 호출 모두 *온라인 필수*이므로 큐잉 가능 stage 부재(epic AC line 576 — *"사진 입력은 오프라인 큐잉 대상 아님"*). 본 스토리는 *텍스트-only 큐잉*만, parsed_items는 schema 호환을 위해 큐 항목에 포함하되 *온라인에서 OCR 통과 후 입력 ate_at 갱신을 위해 PATCH로 미루는 케이스* 흐름은 OUT, (b) **Web 영향 0건** — 큐잉 + Idempotency 처리 mobile-only(NFR-L1 web responsive admin 정합), `web/src/lib/api-client.ts`는 자동 OpenAPI 재생성으로 헤더 첨부 인터페이스만 노출, (c) **MMKV 도입은 OUT** — 신규 native 의존성 + JSI 빌드 회귀 risk, AsyncStorage(이미 설치 + Story 1.6/2.4 패턴) 충분 — Growth 시점 재평가, (d) **conflict resolution은 OUT** — 큐는 FIFO 순차 sync(서버 last-write-wins), 같은 식단 동시 편집 등의 conflict는 단일 디바이스 가정으로 발생 빈도 낮음 — Story 5.x 다중 디바이스 시점 재검토, (e) **PATCH/DELETE 큐잉은 OUT** — POST 큐잉만(epic AC 명시 *"텍스트 식단 입력"*), 수정/삭제는 *온라인 필수*(편집 시 raw_text 표시 prefill을 위해 list cache hit 가정 — Story 2.1 정합) + 필요 시 사용자가 직접 retry, (f) **큐 size 무한 누적 가드** — 본 스토리 baseline은 *최대 100건* hard cap(`OFFLINE_QUEUE_MAX_SIZE`)으로 abuse 차단. 초과 시 enqueue 거부 + Alert *"오프라인 대기 항목이 너무 많아요(100+) — 온라인 복귀 후 동기화 시도해주세요"* — Story 8 polish에서 동적 cap 검토(DF deferred), (g) **partial 실패 retry granularity** — 개별 항목 단위 재시도(전체 큐 abort X) — flush 중 1건 실패 시 해당 항목만 attempts++ + 다음 항목 진행, (h) `meals.idempotency_key` 컬럼은 *POST 흐름만* — PATCH/DELETE는 본 스토리 영향 X. Idempotency-Key 헤더가 PATCH/DELETE에 송신돼도 무시(Pydantic 검증 통과만, 라우터 분기 X). 본 스토리 종료 시 Epic 2 5 스토리 모두 done → Epic 3 진입 준비 완료.

## Acceptance Criteria

> **BDD 형식 — 각 AC는 독립적 검증 가능. 모든 AC 통과 후 `Status: review`로 전환하고 code-review 워크플로우로 진입.**

1. **AC1 — 백엔드 `meals.idempotency_key` 컬럼 + partial UNIQUE index 마이그레이션 (`alembic 0009`)**
   **Given** Story 2.1 baseline `meals` 테이블 9 컬럼 + Story 2.5 Idempotency 처리 도입, **When** `alembic upgrade head` 실행, **Then**:
     - **신규 컬럼**: `idempotency_key TEXT NULL` (Postgres UUID 형식 가정 — 클라이언트 UUID v4 송신, 길이 36자 hard cap은 application-level Pydantic 검증).
     - **신규 partial UNIQUE index**: `idx_meals_user_id_idempotency_key_unique ON meals (user_id, idempotency_key) WHERE idempotency_key IS NOT NULL`. NULL은 unique 제약에서 제외 — 헤더 미송신 입력은 자유 INSERT 가능(회귀 0건).
     - **`Meal` ORM 갱신**: `idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)` 추가. `__table_args__`에 새 partial UNIQUE index 등재. nullable + index는 비파괴 — Story 2.1 baseline 200+ 회귀 0건.
     - **마이그레이션 파일 신규**: `api/alembic/versions/0009_meals_idempotency_key.py` — `down_revision: str | None = "0008_meals_parsed_items"`. `upgrade`에서 `add_column` + `create_index(postgresql_where=text("idempotency_key IS NOT NULL"))`. `downgrade`에서 `drop_index` + `drop_column` (populated row 가드는 P8 패턴 정합 X — `idempotency_key`는 부수 메타데이터로 손실 영향 미미, 단순 drop).
     - **CHECK 제약 X** — 형식 검증은 Pydantic + UUID v4 regex(application-level 충분, DB CHECK는 Story 8 hardening / DB 마이그레이션 마찰).
     - **응답 wire 변경 X** — `MealResponse`에 `idempotency_key` 필드 노출 X(클라이언트 입력 echo 회피 + payload 경량화). 응답은 Story 2.4 11 필드 그대로 유지.
     - **테스트**: `test_alembic_upgrade_downgrade_roundtrip`(존재 시) 회귀 통과 + Story 2.1+2.2+2.3+2.4 232 케이스 회귀 0건.

2. **AC2 — `POST /v1/meals` `Idempotency-Key` 헤더 처리 (W46 흡수, D1 결정)**
   **Given** Story 2.1 baseline `POST /v1/meals` + Story 2.5 Idempotency 도입, **When** 클라이언트가 `Idempotency-Key: <UUID v4>` 헤더 송신, **Then**:
     - **헤더 추출**: FastAPI `Header(default=None, alias="Idempotency-Key")` Annotated 의존성으로 추출 — alias 명시(헤더 case-insensitive forward 정합).
     - **UUID v4 형식 검증** (Pydantic `field_validator` 또는 라우터 inline): `^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$` regex — `MealIdempotencyKeyInvalidError(400, code="meals.idempotency_key.invalid")` 거부. 길이 36자 hard cap 동시 강제(over-length DoS 차단).
     - **Idempotency 흐름**:
       1. 헤더 미송신(None) → 기존 baseline 그대로(`insert(Meal)... .returning(Meal)` race-free, 회귀 0건). 응답 201.
       2. 헤더 송신 + 형식 검증 통과 → `select(Meal).where(Meal.user_id == user.id, Meal.idempotency_key == idempotency_key, Meal.deleted_at.is_(None))` 1차 조회. **존재 시**: 기존 row를 `_meal_to_response`로 응답 200(*201 X — RFC 9110 idempotent retry 시맨틱*). INSERT 미수행. logger.info(`meals.create.idempotent_replay`, meal_id=...) 1줄.
       3. 헤더 송신 + 1차 조회 미존재 → `insert(Meal).values(..., idempotency_key=key).returning(Meal)`. **race**: 두 동시 요청이 같은 key로 INSERT 시 partial UNIQUE 제약 위반 → `IntegrityError` catch + 재 SELECT(2차 조회) → 기존 row 응답 200. (POST returns 200 *only* in idempotent-hit/race path; first INSERT는 그대로 201.)
     - **race 처리 단일 helper**: `async def _create_meal_idempotent_or_replay(db, values, idempotency_key) -> tuple[Meal, bool]` — bool은 `was_replay` (200 분기). race-free SELECT-then-INSERT-then-SELECT 패턴 (`asyncpg`/`SQLAlchemy 2.0 async` `db.rollback()` 후 재 SELECT — 실패 시 5xx fallback).
     - **HTTP status 분기**:
       - 신규 INSERT → 201 Created (Story 2.1 baseline 정합).
       - Replay (idempotent hit 또는 race resolution) → **200 OK** + 기존 row 응답. FastAPI 라우터에서 `Response.status_code = status.HTTP_200_OK` 명시 setter (FastAPI는 default 201 — 분기 시 dynamic override).
     - **PATCH/DELETE Idempotency 처리 X** — 본 스토리는 *POST 흐름*만(epic AC `Idempotency-Key` 송신은 텍스트 식단 입력 흐름). PATCH/DELETE에 헤더 송신돼도 무시(Pydantic 통과 + 분기 X — 회귀 0건).
     - **soft-deleted row 처리**: 1차 SELECT는 `deleted_at IS NULL` 필터 — 삭제된 row와 같은 idempotency_key 재사용 가능(스코프 별도 운영). 단 partial UNIQUE index는 `WHERE idempotency_key IS NOT NULL`만 — `deleted_at` 무관 (전체 row에 unique). 즉 같은 키로 INSERT 시도 시 deleted row와 충돌 → race-free SELECT는 *active row 0건*이지만 *INSERT는 unique 위반*. catch 후 *deleted_at 포함* 재 SELECT → soft-deleted row 발견 시 *"이미 삭제된 식단입니다"* 409 (`MealIdempotencyKeyConflictDeletedError(409, code="meals.idempotency_key.conflict_deleted")`) 분기. 사용자가 새 key로 재시도하도록 안내. **이 분기 케이스는 회귀 차단 단언 필수**.
     - **`Idempotency-Key`는 *post-send 의미만 가짐*** — 클라이언트가 같은 raw_text/ate_at을 다른 key로 송신하면 별 row 생성(Idempotency는 *키 == 한 번* 시맨틱, *내용 dedup* 시맨틱 X — Stripe/Toss 표준 정합). 라우터 docstring 명시.
     - **OpenAPI 갱신**: `POST /v1/meals` description에 *"`Idempotency-Key` 헤더(UUID v4) 송신 시 같은 키 재송신은 idempotent 처리 — 기존 row 200 응답 (W46 흡수)"* 1줄 추가. response 200 추가 (현 201만). FastAPI 라우터에 `responses={200: {...}, 201: {...}, 400: {...}, 409: {...}}` 명시.

3. **AC3 — `mobile/lib/offline-queue.ts` 신규 — AsyncStorage FIFO 큐 + 지수 backoff + mutex**
   **Given** 모바일 텍스트 식단 큐잉 요구, **When** `enqueueMealCreate(item)` / `flushQueue()` / `getQueueSnapshot()` / `removeQueueItem(client_id)` 호출, **Then**:
     - **큐 storage**: AsyncStorage key `bn:offline-queue:meal:<user_id>` (per-user namespace — Story 1.6 `bn:onboarding-tutorial-seen-<user_id>` 패턴 정합). 값은 JSON 직렬화 array.
     - **큐 항목 schema** (`OfflineQueueItem`):
       ```typescript
       export interface OfflineQueueItem {
         client_id: string; // UUID v4 — Idempotency-Key 헤더 송신값. 동시에 큐 식별자 + 클라이언트 list optimistic 표시 키.
         raw_text: string; // 큐잉 시점 사용자 입력. trim 후 비공백 보장.
         ate_at?: string; // ISO 8601 +09:00 송신 (ISO TZ-aware). 미지정 시 큐잉 시점 KST `now` 자동 채움 (서버 fallback 회피 — 사용자가 큐잉한 시점이 의미).
         parsed_items?: ParsedMealItem[] | null; // 인터페이스 호환만 — 본 스토리 baseline은 *항상 null* (사진 큐잉 OUT). Story 2.3 schema sharing.
         attempts: number; // 0-based — 시도 횟수. ≥ 3 후 `last_error`만 갱신, 큐 잔존 (사용자 manual retry).
         last_error?: string; // 마지막 sync 실패 메시지 (UI 표시 — *"오류 — 다시 시도"*).
         last_attempt_at?: string; // ISO 8601 — 마지막 시도 시각(다음 backoff 계산).
         enqueued_at: string; // ISO 8601 — 최초 큐잉 시각 (FIFO 정렬 키 + UI sub-text *"5분 전 입력"*).
       }
       ```
     - **`enqueueMealCreate(item: Omit<OfflineQueueItem, 'attempts' | 'enqueued_at'>): Promise<void>`** — `attempts=0` + `enqueued_at=new Date().toISOString()` 자동 채움 + 큐 끝(append)에 push. `OFFLINE_QUEUE_MAX_SIZE=100` 초과 시 throw `OfflineQueueFullError` — 호출 측이 Alert *"오프라인 대기 항목이 너무 많아요(100+)"*.
     - **`flushQueue(authFetch): Promise<FlushResult>`** — 큐를 head부터 순차 sync. 각 항목별:
       1. `attempts++` + `last_attempt_at` 갱신 (디스크 persist).
       2. `authFetch('/v1/meals', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': item.client_id }, body: JSON.stringify({ raw_text, ate_at, parsed_items? }) })`.
       3. **2xx (200/201)**: 큐에서 제거 + `flushed_count++`. (200은 idempotent replay — 서버가 이미 처리, 클라이언트는 동일 결과 처리.)
       4. **4xx (400/422)**: 영구 실패 — 큐에서 제거 + `failed_permanent_count++` + `last_error` 보존 (UI는 *"검증 실패 — 식단을 다시 입력해주세요"* 안내). 401/403은 `authFetch` 자동 처리(refresh + redirect) — 도달하지 않음 가정. 500/502/503은 transient.
       5. **5xx 또는 네트워크 에러**: 큐에 잔존(인덱스 advance X) + `last_error` 갱신 + flush 중단(다음 항목 시도 X — 일관 backoff 의미). `attempts >= 3` 시 `last_error` 갱신 후 큐 잔존 (manual retry는 사용자 명시 액션).
     - **지수 backoff scheduling**: `flushQueue`는 *호출자 책임*이지만 *항목 단위 backoff*은 큐 자체 — `attempts=0` 즉시 시도, `attempts=1` 1초 + jitter(±20%), `attempts=2` 2초 + jitter, `attempts=3` 4초 + jitter. `flushQueue`가 항목별 `setTimeout`로 backoff 후 시도. `attempts >= 3`은 retry 미수행(*"3회 재시도 실패 — 큐 잔존"*).
     - **mutex (single-flight)**: 동시 `flushQueue` 호출 race 차단 — module-level `let flushing: Promise<FlushResult> | null = null;` flag. 진행 중 호출은 같은 promise 반환(`if (flushing) return flushing`).
     - **user_id 격리**: 모듈 함수는 `userId: string` arg를 받아 storage key suffix로 forward. 다중 사용자 동일 디바이스 시 큐 격리(Story 1.6 W34 정합 패턴 — *"같은 디바이스, 다른 사용자, 다른 큐"*).
     - **schema migration 가드**: AsyncStorage에 저장된 큐가 *deserialize 실패* 시(schema 변경) — 큐 전체 폐기 + 사용자 안내 X(silent reset, 데이터 손실 미미 — 본 스토리 baseline). Story 8 polish 시점에 buster pattern 도입(deferred-work).
     - **`getQueueSnapshot(userId): Promise<OfflineQueueItem[]>`** — UI 표시용 read-only snapshot. clone 반환 (mutation 차단).
     - **`removeQueueItem(userId, client_id): Promise<void>`** — manual retry 후 사용자 *"폐기"* 액션 또는 server 4xx 응답 시 호출.

4. **AC4 — `useCreateMealMutation` 갱신 — 오프라인 분기 + Idempotency-Key 첨부**
   **Given** Story 2.1 baseline `useCreateMealMutation` + Story 2.5 큐잉 흐름, **When** `mutate(body)` 호출, **Then**:
     - **`Idempotency-Key` 첨부**: hook 내부에서 `crypto.randomUUID()` 또는 `expo-crypto` `randomUUID()` 생성 — `mutationFn`이 `createMeal(body, { idempotencyKey })`로 전달. `expo-crypto`는 이미 설치(`mobile/package.json` 정합) — 신규 의존성 0건.
     - **`createMeal(body, opts)` 시그니처 갱신** — `mobile/features/meals/api.ts`의 `createMeal` async 함수가 `idempotencyKey?: string` optional arg 받음. truthy 시 `headers['Idempotency-Key'] = idempotencyKey` 첨부.
     - **오프라인 분기 (mutationFn 외부)**: 호출 측(`(tabs)/meals/input.tsx`)이 `useOnlineStatus()` `isOnline` 체크 후 분기 — offline 시 `enqueueMealCreate({ client_id: uuid, raw_text, ate_at?, parsed_items? })` 호출 + `router.replace('/(tabs)/meals')` (Story 2.1 정합 success path와 동일 UX). hook 자체는 *온라인 가정*(throw on network error는 그대로 — 호출 측이 try/catch 외 분기).
     - **optimistic update 도입 X** — 본 스토리 baseline은 *큐잉 후 list에 client-side merge* 패턴(AC8). hook 변경은 헤더 첨부 + idempotencyKey 생성만. invalidateQueries는 그대로 (`onSuccess` 시 list refetch).
     - **회귀 차단**: hook이 Idempotency-Key 미송신(`opts.idempotencyKey === undefined`) 시 헤더 첨부 X — Story 2.1+2.2+2.3 회귀 0건. 모든 호출은 명시적으로 idempotencyKey 전달(default `undefined` 보존 X — Story 2.5 통합 시점).
     - **`useUpdateMealMutation` / `useDeleteMealMutation` 변경 X** — 본 스토리는 POST 흐름만 idempotency 처리.

5. **AC5 — `(tabs)/meals/input.tsx` — 텍스트 큐잉 분기 + 사진 오프라인 차단**
   **Given** Story 2.1+2.2+2.3 baseline 식단 입력 화면 + Story 2.5 오프라인 분기, **When** 사용자가 입력 화면에서 액션, **Then**:
     - **텍스트 입력 + 저장 — 오프라인 분기**:
       - `useOnlineStatus()` `!isOnline` 시 `onSubmit` 분기:
         - `body.image_key` 또는 `body.parsed_items` 존재 시 *Alert*(*"오프라인에서는 사진 입력을 저장할 수 없어요. 텍스트만 입력하거나 온라인 시 다시 시도해주세요."*) + early return.
         - 텍스트만 → `enqueueMealCreate({ client_id: uuid, raw_text: body.raw_text!, ate_at: new Date().toISOString(), parsed_items: null })` + Toast/Alert *"오프라인 — 동기화 대기 중"* + `router.replace('/(tabs)/meals')`.
       - 온라인 시 기존 흐름 그대로 (hook + Idempotency-Key 첨부, AC4 정합).
     - **사진 입력 — 오프라인 차단** (epic AC line 576):
       - 카메라/갤러리 탭 onPress 시 `!isOnline` 체크 → `Alert.alert('오프라인 상태', '사진은 온라인에서 처리 가능 — 텍스트 입력 또는 온라인 시 다시 시도해주세요.', [{ text: '확인' }])` + early return (권한 prompt 진입 차단 — UX 단순성).
       - PATCH 모드(편집)도 동일 — 오프라인에서 사진 첨부/제거 차단(`PATCH /v1/meals/{meal_id}` 자체가 *온라인 필수* — Story 2.5 PATCH 큐잉 OUT 정합).
     - **권한 거부 + 오프라인 우선순위**: 카메라 권한 거부 + 오프라인이면 *오프라인 차단 Alert*만 표시(권한 안내 후순위 — UX 명료성).
     - **PATCH 모드 — 오프라인 차단**:
       - 편집 화면 진입 시 `!isOnline` 체크 → Alert *"오프라인에서는 식단 수정/삭제가 불가합니다."* + `router.back()`. 본 스토리 baseline은 *진입 차단*만(Story 8에서 PATCH 큐잉 검토 — deferred-work).
       - 단 Story 2.4 [meal_id].tsx 상세 화면 *조회*는 영향 X(7일 캐시 client-side filter — 오프라인 read-only).
     - **NFR-A3 폰트 200%**: 오프라인 차단 Alert 텍스트는 RN Alert 기본 — 별도 wrap 처리 X(시스템 UI 정합).

6. **AC6 — `(tabs)/meals/index.tsx` — 동기화 대기 배지 + optimistic 큐 카드 + 자동 flush**
   **Given** Story 2.4 baseline 일별 기록 화면 + Story 2.5 큐잉 흐름, **When** 화면 진입 또는 상태 변경, **Then**:
     - **큐 snapshot 구독**: `useOfflineQueue()` hook 신규 (`mobile/lib/offline-queue.ts` export) — 큐 변경 시 re-render 트리거. 구현: `useState` + AsyncStorage subscription 패턴(Story 1.6 `tutorialState.ts` 정합) — module-level subscriber set + enqueue/remove 시 notify.
     - ***"동기화 대기 중"* 배지** (epic AC line 573):
       - `queueSize > 0` 시 화면 헤더 (`Stack.Screen options.headerRight` 또는 별도 bar) 노출 — *"동기화 대기 {n}건"* + 회색/주황 배지 (`#fff3cd` 배경 또는 `#fef3c7`).
       - 탭 시 작은 popover 또는 ActionSheet — 큐 항목별 *raw_text 발췌*(앞 30자) + *N분 전 입력* + *"지금 동기화"* / *"폐기"* 버튼 (manual retry / drop). manual retry는 `flushQueue(userId, authFetch)` 강제 호출. 폐기는 `removeQueueItem(client_id)`.
     - **optimistic 카드** (epic AC line 573 *"UI에 동기화 대기 중 배지 표시"*):
       - 큐 항목들을 list 상단(시간순 ASC 정합 — `enqueued_at` 기준 ASC 또는 *"오늘"*만 표시 — selectedDate가 오늘일 때만, 그 외 일자는 큐 항목 제외).
       - 큐 카드 visual: 회색 배경(`#f5f5f5` 또는 `#fafafa`) + raw_text + *"동기화 대기 중"* 배지(`#fff3cd`) + *N건 시도 실패* (attempts ≥ 1 시) + *manual retry* 버튼 (큰 *⏵* 또는 *"다시 시도"* 텍스트).
       - 큐 카드는 `onCardPress`/`onActionPress` callback 비활성(상세 진입/수정/삭제 모두 — 아직 server-side row 미존재). 대신 *"폐기"* / *"다시 시도"* 액션만.
     - **자동 flush 트리거**:
       - `useOnlineStatus()` 상태 변경 detect — `isOnline` `false → true` 전이 시 `flushQueue(userId, authFetch)` 자동 호출 (effect 내부). `useEffect`에 prev `isOnline` ref 비교 패턴.
       - flush 성공 시 큐 자동 비움 + `queryClient.invalidateQueries({ queryKey: ['meals'] })`로 list refetch (server 응답이 큐 카드 자리에 displace).
       - flush 실패 항목은 큐 잔존 + 배지 유지(*"동기화 대기 N건 — 재시도 실패"*).
     - **빈 화면 재계산**:
       - `selectedDate === todayKst()` + server meals 0건 + queue size > 0 → *"오늘 기록 없음"* 빈 화면 미노출 (큐 카드를 주 contents로 표시).
       - `selectedDate === todayKst()` + server meals 0건 + queue size 0 → 기존 *"오늘 기록 없음"* + CTA(Story 2.4 정합).
     - **NFR-A3 폰트 200%**: 큐 카드 + 배지 모두 `flexShrink + flexWrap + lineHeight` (Story 2.4 정합).
     - **accessibility**: 큐 카드 `accessibilityRole="button"` + `accessibilityLabel="동기화 대기 식단: ${preview}, ${attempts > 0 ? attempts + '회 시도 실패, ' : ''}${time} 입력"` + `accessibilityHint="다시 시도하거나 폐기할 수 있습니다"`. 배지는 `accessibilityLabel="동기화 대기 ${n}건"`.

7. **AC7 — 4xx validation 영구 실패 처리 + 사용자 안내**
   **Given** 큐 항목 sync 시 서버 400/422 응답 (raw_text whitespace 위반 등 — 클라이언트 가드 우회 또는 schema drift), **When** `flushQueue` 항목 처리, **Then**:
     - 4xx (400/422) 응답 → 큐에서 *즉시 제거* (`removeQueueItem`) + `failed_permanent_count++` + `last_error` 보존 (별 *영구 실패 list*는 OUT — 단순성 우선 — Story 8).
     - 사용자 안내: *"식단을 동기화할 수 없어요 (입력 오류) — 다시 입력해주세요"* Alert (1회 누적 노출 — flush 종료 시 1회). raw_text 발췌 포함(*"... 짜장면 ..."* 처음 20자) — 사용자가 어떤 항목인지 인식 가능.
     - 401/403은 `authFetch`가 자동 처리(refresh + redirect) — `flushQueue` 도달 X 가정.
     - 500/502/503/504 + 네트워크 에러는 transient — 큐 잔존(AC3 정합).
     - **회귀 차단**: 4xx 응답 후에도 다음 항목 진행 (loop 종료 X — partial 실패 granular).

8. **AC8 — `useOnlineStatus` 활용 + 네트워크 복귀 자동 flush**
   **Given** Story 2.4 `mobile/lib/use-online-status.ts` baseline + Story 2.5 큐잉 흐름, **When** 네트워크 상태 변화, **Then**:
     - `(tabs)/meals/index.tsx`의 `useEffect` — `isOnline` prev ref 비교 후 `false → true` 전이 시 `flushQueue(userId, authFetch)` 자동 호출. 단일 트리거(중복 호출 차단은 mutex AC3 정합).
     - 앱 cold start 시 `useOnlineStatus`의 initial fetch가 online을 즉시 보고 → useEffect 첫 trigger에서 `prev=undefined`/`current=true` 분기 → flush 1회 호출(앱 재실행 시점에 잔존 큐 자동 sync). 이 분기는 *intentional* — Story 2.4 `_stateToStatus`의 `isConnected !== false` 정합 (unknown은 online 가정).
     - 큐 size 0 + flush 호출은 no-op + 즉시 return (logger 미출력 — UX silent).
     - flush 진행 중 다른 트리거(예: prev/next/today 버튼 → useOnlineStatus 변경 X but 상태 갱신 trigger) 발생 시 mutex로 중복 차단 (AC3 정합).
     - 사진 OCR 흐름의 `useOnlineStatus()` 활용 X(차단은 onPress 시점 evaluation — useEffect 미사용 — render-side 차단 회피).

9. **AC9 — `MealError` 계층 확장 + RFC 7807 응답**
   **Given** Story 2.1 baseline `MealError` base + Story 2.5 신규 에러 코드, **When** 서버가 Idempotency 관련 검증 실패, **Then**:
     - **`MealIdempotencyKeyInvalidError(BalanceNoteError)`**: status=400, code=`meals.idempotency_key.invalid`, title=*"Idempotency-Key invalid"* — UUID v4 형식 위반. `MealError` 하위가 아님(`meals.*` 카탈로그는 식단 도메인이지만 Idempotency는 *cross-cutting* 가능 — 그러나 본 스토리는 *식단 흐름만* 도입이라 `MealError` 하위로도 가능). **D2 결정**: `MealIdempotencyKeyInvalidError(MealError)` 채택 — 카탈로그 일관성(`meals.idempotency_key.*` namespace) 우선, Story 6.x 결제 webhook idempotency 도입 시 별 도메인 base(`PaymentError`) 분리 검토.
     - **`MealIdempotencyKeyConflictDeletedError(MealError)`**: status=409, code=`meals.idempotency_key.conflict_deleted`, title=*"Idempotency key conflicts with deleted meal"* — soft-deleted row와 같은 key INSERT 시도 (race-rare 케이스). 사용자 안내 *"이미 삭제된 식단입니다 — 다시 입력해주세요"*.
     - 두 에러 모두 RFC 7807 `application/problem+json` 응답 (`main.py` 글로벌 핸들러 정합 — 별도 wire 추가 X).
     - **OpenAPI 갱신**: `POST /v1/meals` `responses={400: {...}, 409: {...}}` 신규 코드 노출 (FastAPI auto). 클라이언트(`api-client.ts`) 자동 재생성 — 모바일은 `MealSubmitError.code` 분기로 사용 (사용자 안내 매핑).

10. **AC10 — 백엔드 테스트 + Idempotency 회귀 + race 단언**
    **Given** Story 2.5 백엔드 변경(컬럼 + index + Idempotency 처리 + 신규 에러), **When** `pytest` 실행, **Then**:
      - **`test_meals_router.py` 갱신** — Idempotency 신규 9 케이스:
        - `test_post_meal_with_idempotency_key_first_time_returns_201_with_key_persisted` — 헤더 송신 + 첫 송신 → 201 + DB에 `idempotency_key` 저장 단언 (raw SQL `SELECT idempotency_key FROM meals WHERE id = ?`).
        - `test_post_meal_with_idempotency_key_duplicate_returns_200_same_row` — 같은 헤더 두 번 송신 → 두 응답 모두 같은 `meal.id` + 두 번째는 200 (`response2.status_code == 200` 단언) + DB row 1건만 (count == 1).
        - `test_post_meal_without_idempotency_key_creates_new_row` — 헤더 미송신 → 201 + `idempotency_key IS NULL` (회귀 차단).
        - `test_post_meal_with_idempotency_key_invalid_uuid_returns_400` — `Idempotency-Key: not-a-uuid` → 400 + code `meals.idempotency_key.invalid`.
        - `test_post_meal_with_idempotency_key_invalid_v4_format_returns_400` — UUID v1 형식 (예: `c232ab00-9414-11ec-b909-0242ac120002`) → 400 (`v4` 강제 — `4[0-9a-fA-F]{3}` 그룹 강제).
        - `test_post_meal_with_idempotency_key_different_users_isolated` — 사용자 A의 key를 사용자 B가 송신 → B의 user_id 정합 row 신규 생성 (200 X). 즉 키-스코프는 user_id 정합 (AC2 정합 D1 결정).
        - `test_post_meal_with_idempotency_key_conflicts_with_deleted_returns_409` — A 사용자가 key X로 식단 생성 → 삭제(soft delete) → 같은 key X로 재 POST → 409 + code `meals.idempotency_key.conflict_deleted`.
        - `test_post_meal_with_idempotency_key_race_simulated_two_inserts_same_key` — `asyncio.gather`로 동시 2 POST 같은 key → 둘 다 같은 `meal.id` 반환 (1건 INSERT, 1건 race-loser → SELECT replay 200). DB row 1건만.
        - `test_post_meal_idempotency_key_idempotent_replay_does_not_change_raw_text` — 첫 POST `raw_text="A"` + 같은 key + `raw_text="B"` 두 번째 POST → 두 응답 모두 `raw_text="A"` (Idempotency는 *키 기준 replay* 시맨틱 — body diff는 무시).
      - **PATCH/DELETE 회귀 0건**: 두 라우터에 `Idempotency-Key` 송신해도 정상 처리 (헤더 무시, body/path만 처리). 1 케이스 추가 (`test_patch_meal_with_idempotency_key_header_ignored`).
      - **conftest 갱신**: `_truncate_user_tables`에 `idempotency_key` 영향 X(`meals` 테이블 그대로 truncate).
      - **`test_meals_idempotency_key_schema.py` 신규** (선택 — alembic 마이그레이션 회귀): partial UNIQUE index 존재 확인 (`SELECT indexname FROM pg_indexes WHERE tablename='meals' AND indexname='idx_meals_user_id_idempotency_key_unique'`).
      - **`uv run pytest --cov=app --cov-fail-under=70` 통과** — 신규 10 케이스 + Story 2.1+2.2+2.3+2.4 232 회귀 0건 → 약 242 테스트 통과 + coverage ≥ 80%.
      - **`ruff check . && ruff format --check . && mypy app` clean**.

11. **AC11 — 모바일 테스트 + smoke 검증 + Pydantic 회귀**
    **Given** Story 2.5 모바일 변경(offline-queue + useCreateMealMutation + input.tsx + index.tsx), **When** smoke 검증 + tsc/lint, **Then**:
      - **`pnpm tsc --noEmit` + `pnpm lint`** 통과 — `mobile`/`web` 두 워크스페이스. `web/src/lib/api-client.ts` 자동 재생성 (200 응답 코드 + 새 에러 코드 노출).
      - **OpenAPI 클라이언트 자동 재생성**: `IN_PROCESS=1 bash scripts/gen_openapi_clients.sh` → 두 워크스페이스 갱신 + `openapi-diff` GitHub Actions 통과.
      - **smoke 검증 9 시나리오** (사용자 별도 수행 — Completion Notes 결과 기록):
        1. **온라인 텍스트 POST** — 정상 입력 → 201 + Idempotency-Key 헤더 송신 → DB row 1건. 회귀 0.
        2. **오프라인 텍스트 큐잉** — 비행기 모드 ON → 텍스트 입력 + 저장 → 큐잉 + *"동기화 대기 1건"* 배지 + list 상단 회색 카드.
        3. **네트워크 복귀 자동 flush** — 비행기 모드 OFF → 자동 flush → 카드가 server response로 displace + 배지 해제.
        4. **3회 backoff 재시도 실패** — 백엔드 5xx mock(또는 manual disconnect) → attempts 0→1→2→3 + *"3회 재시도 실패"* 배지 + manual retry 버튼 노출.
        5. **manual retry** — *"다시 시도"* 탭 → flush 강제 호출 → 성공 시 큐 비움.
        6. **사진 입력 오프라인 차단** — 비행기 모드 ON → 카메라 탭 → Alert *"사진은 온라인에서 처리 가능"* + 권한 prompt 미진입.
        7. **PATCH 모드 오프라인 차단** — 비행기 모드 ON → 카드 long-press → 수정 → Alert *"오프라인에서는 식단 수정/삭제가 불가합니다"* + back.
        8. **400 validation 영구 실패** — 큐에 raw_text 빈 항목 (강제 inject) → flush → 400 → 큐 제거 + Alert *"식단을 동기화할 수 없어요 (입력 오류)"*.
        9. **다중 사용자 큐 격리** — 사용자 A 로그인 → 큐잉 → 로그아웃 → 사용자 B 로그인 → 큐 빈 화면 (per-user namespace 정합).
      - **백엔드 게이트(pytest 242+ 통과 + ruff/format/mypy clean) + 모바일 게이트(tsc/lint clean) 통과**.
      - **smoke OUT**: actual 4G/Wi-Fi handover/지하철 시나리오는 *manual UAT* — 본 스토리 baseline은 *비행기 모드 토글*로 충분.

12. **AC12 — README + sprint-status + deferred-work + W46 closed 단언**
    - **README**: 기존 *"일별 식단 기록 화면 + 7일 로컬 캐시 SOP (Story 2.4)"* 단락 다음에 *"오프라인 텍스트 큐잉 + 자동 sync SOP (Story 2.5)"* 1 단락 추가 (간결 — 6 줄 이하):
      - (a) `mobile/lib/offline-queue.ts` AsyncStorage FIFO 큐 + `bn:offline-queue:meal:<user_id>` namespace 1줄
      - (b) 백엔드 `Idempotency-Key` 헤더 처리 — `meals.idempotency_key` 컬럼 + partial UNIQUE index + 200 idempotent replay (W46 흡수) 1줄
      - (c) 자동 flush — `useOnlineStatus` offline → online 전이 시 `flushQueue` 호출 + 지수 backoff 1s/2s/4s 3회 1줄
      - (d) 사진 입력 오프라인 차단 + PATCH/DELETE 오프라인 차단 (epic AC 정합) 1줄
      - (e) 큐 size 100 hard cap + 4xx validation은 영구 실패(큐 제거) 1줄
      - (f) Epic 2 5 스토리(2.1~2.5) 모두 done → Epic 3 AI 분석 진입 준비 완료 1줄
    - **.env.example**: 변경 X — 본 스토리 신규 환경변수 0건.
    - **sprint-status**: `2-5-오프라인-텍스트-큐잉-sync` → `review` 갱신 (DS 종료 시점 — memory `feedback_ds_complete_to_commit_push.md` 정합 — commit + push 후 CR 단계).
    - **deferred-work.md** 갱신 — W46 (Story 2.1) `meals.idempotency_key` 컬럼 + 409 분기 흡수로 closed 표기 + strikethrough. 본 스토리 신규 deferred 후보 추가 (*Dev Notes — 신규 deferred 후보* 섹션).
    - **W46 closed 단언**: `test_post_meal_with_idempotency_key_duplicate_returns_200_same_row` + `test_post_meal_with_idempotency_key_race_simulated_two_inserts_same_key` 2 테스트가 회귀 차단. Completion Notes에 *W46 closed (Story 2.5 — meals.idempotency_key 컬럼 + 200 replay + race partial UNIQUE)* 명시.
    - **W14 (Story 1.3) `require_basic_consents` 라우터 wire** — 본 스토리 영향 X (POST는 이미 wire — Story 2.1).
    - **DF1-DF14, DF16-DF26, W42-W51** (carry-over) — 본 스토리 영향 X (Story 8 / Story 3.x 책임 그대로).

## Tasks / Subtasks

> 순서는 의존성 위주. 각 task는 AC 번호 매핑 명시. 본 스토리는 **단일 PR 권장** (Story 2.1/2.2/2.3/2.4 정합).

### Task 1 — 백엔드 마이그레이션 + Meal ORM 갱신 (AC: #1)

- [x] 1.1 `api/alembic/versions/0009_meals_idempotency_key.py` 신규 — `down_revision = "0008_meals_parsed_items"` + `upgrade`에서 `add_column('meals', sa.Column('idempotency_key', sa.Text, nullable=True))` + `create_index('idx_meals_user_id_idempotency_key_unique', 'meals', ['user_id', 'idempotency_key'], unique=True, postgresql_where=sa.text('idempotency_key IS NOT NULL'))`. `downgrade`에서 `drop_index` + `drop_column` (단순 — 부수 메타데이터 손실 영향 미미).
- [x] 1.2 `api/app/db/models/meal.py` 갱신 — `idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)` 추가 + `__table_args__`에 `Index('idx_meals_user_id_idempotency_key_unique', 'user_id', 'idempotency_key', unique=True, postgresql_where=text('idempotency_key IS NOT NULL'))` 등재. docstring에 Story 2.5 등재 1줄.
- [x] 1.3 `cd api && uv run alembic upgrade head` 로컬 검증 (Postgres docker compose) → `idempotency_key` 컬럼 + partial UNIQUE index 존재 확인 (`\d+ meals` 또는 `SELECT indexname FROM pg_indexes WHERE tablename='meals'`).
- [x] 1.4 `cd api && uv run alembic downgrade 0008` → `cd api && uv run alembic upgrade head` 라운드트립 — 마이그레이션 멱등성 확인 (downgrade 후 upgrade 정상 + 데이터 유실 0건은 baseline DB 빈 상태로 검증).
- [x] 1.5 `ruff check . && ruff format --check . && mypy app` clean.

### Task 2 — 백엔드 신규 Exception + `MealError` 계층 확장 (AC: #9)

- [x] 2.1 `api/app/core/exceptions.py` 갱신 — `MealError` base 다음에 `MealIdempotencyKeyInvalidError(MealError)` (status=400, code=`meals.idempotency_key.invalid`, title=*"Idempotency-Key invalid"*) + `MealIdempotencyKeyConflictDeletedError(MealError)` (status=409, code=`meals.idempotency_key.conflict_deleted`, title=*"Idempotency key conflicts with deleted meal"*) 신규 추가. ClassVar 패턴 (Story 1.4 / 2.1+2.2+2.3 정합).
- [x] 2.2 docstring에 *"Story 2.5 — Idempotency-Key 처리"* 1줄 명시.

### Task 3 — 백엔드 `POST /v1/meals` Idempotency 흐름 + race-free helper (AC: #2)

- [x] 3.1 `api/app/api/v1/meals.py` 갱신 — `from fastapi import Header` import 추가 (이미 있을 수 있음 — 라우터 의존성 추가).
- [x] 3.2 UUID v4 형식 검증 — module-level 상수 `_IDEMPOTENCY_KEY_PATTERN: Final[str] = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"` + helper `_validate_idempotency_key(key: str | None) -> None` (None은 통과, 형식 위반은 `MealIdempotencyKeyInvalidError`).
- [x] 3.3 race-free helper `_create_meal_idempotent_or_replay(db, values: dict, idempotency_key: str | None) -> tuple[Meal, bool]` 신규 — bool은 `was_replay`. 흐름:
  - `idempotency_key is None` → 기존 단순 INSERT … RETURNING (replay False, 회귀 0).
  - 아니면 `select(Meal).where(Meal.user_id == values['user_id'], Meal.idempotency_key == idempotency_key, Meal.deleted_at.is_(None))` 1차 조회 → 있으면 (existing, True) 반환.
  - 없으면 `insert(Meal).values(**values, idempotency_key=key).returning(Meal)` 시도. `IntegrityError` catch 시 `await db.rollback()` 후 *전체 row*(deleted_at 포함) 재 SELECT — soft-deleted hit이면 `MealIdempotencyKeyConflictDeletedError` raise, active hit이면 (existing, True) 반환, 둘 다 0건이면 (race lost) 5xx (`raise BalanceNoteError(detail="...")`).
- [x] 3.4 `create_meal` 라우터 갱신 — `Idempotency-Key: Annotated[str | None, Header(default=None, alias="Idempotency-Key")]` 의존성 추가 + `_validate_idempotency_key(idempotency_key)` 호출 + `_create_meal_idempotent_or_replay` 호출 + `was_replay` True 시 `response.status_code = status.HTTP_200_OK` setter.
- [x] 3.5 logger.info(`meals.create.idempotent_replay`, meal_id=str(meal.id), user_id=str(user.id)) 1줄 (replay 분기에서만 — sentry/grafana noise 차단).
- [x] 3.6 docstring 갱신 — *"Story 2.5 — Idempotency-Key 헤더 처리 (W46 흡수)"* 1줄 + *"replay는 200 응답 (RFC 9110)"* 1줄.
- [x] 3.7 OpenAPI `POST /v1/meals` `responses={200: {"description": "Idempotent replay"}, 201: {...}, 400: {...}, 409: {...}}` 명시 — FastAPI 라우터 데코레이터에 `responses=` dict 추가 (Story 1.4 패턴 정합).
- [x] 3.8 `ruff check . && ruff format --check . && mypy app` clean.

### Task 4 — 백엔드 테스트 — Idempotency 회귀 + race 단언 (AC: #10)

- [x] 4.1 `api/tests/test_meals_router.py` 갱신 — Idempotency 9 신규 케이스 (AC10 명시).
- [x] 4.2 race 시뮬레이션 — `asyncio.gather` 패턴으로 두 POST 동시 발사 + 같은 key (race winner는 INSERT, loser는 IntegrityError → SELECT replay). `httpx.AsyncClient` 두 인스턴스 사용 또는 단일 client + `asyncio.gather([client.post(...), client.post(...)])`.
- [x] 4.3 PATCH 회귀 — `test_patch_meal_with_idempotency_key_header_ignored` 1 케이스.
- [x] 4.4 `api/tests/test_meals_idempotency_key_schema.py` 신규 (선택 — alembic 회귀): `_run_pg_query(session)` 기반 `pg_indexes` 조회로 partial UNIQUE index 존재 단언.
- [x] 4.5 `uv run pytest --cov=app --cov-fail-under=70` 통과 — 신규 10 케이스 + Story 2.1+2.2+2.3+2.4 232 회귀 0건. coverage ≥ 80% 유지.
- [x] 4.6 `ruff check . && ruff format --check . && mypy app` clean.

### Task 5 — OpenAPI 클라이언트 자동 재생성 + 모바일 타입 sync (AC: #2, #4, #11)

- [x] 5.1 `IN_PROCESS=1 bash scripts/gen_openapi_clients.sh` 실행 → `mobile/lib/api-client.ts` + `web/src/lib/api-client.ts` 갱신. `POST /v1/meals` 200 응답 코드 + `meals.idempotency_key.invalid` / `meals.idempotency_key.conflict_deleted` code 노출 확인.
- [x] 5.2 두 워크스페이스 `pnpm tsc --noEmit` 통과.
- [x] 5.3 PR push 시 `openapi-diff` GitHub Actions 잡 통과 — schema dump commit (CI fresh 재생성과 비교 시 diff 0건).

### Task 6 — `mobile/lib/offline-queue.ts` 신규 + 단위 검증 (AC: #3, #7, #8)

- [x] 6.1 `mobile/lib/offline-queue.ts` 신규 — `OfflineQueueItem` interface + `OfflineQueueFullError` 클래스 + 모듈 함수:
  - `enqueueMealCreate(userId: string, item: Omit<OfflineQueueItem, 'attempts' | 'enqueued_at'>): Promise<void>` — 100건 cap + append + notify subscribers.
  - `flushQueue(userId: string, authFetch: typeof globalThis.fetch): Promise<FlushResult>` — mutex(`flushing` flag) + FIFO 순차 + 항목별 backoff (1s/2s/4s + jitter ±20%) + 4xx 즉시 제거 + 5xx 잔존 + `attempts >= 3` 후 잔존 + transient 에러 시 flush 중단.
  - `getQueueSnapshot(userId: string): Promise<OfflineQueueItem[]>` — clone 반환.
  - `removeQueueItem(userId: string, client_id: string): Promise<void>` — 항목 제거 + notify.
  - `subscribeQueue(userId: string, listener: () => void): () => void` — module-level subscriber set + unsubscribe (Story 1.6 `tutorialState.ts` 정합 패턴).
  - `useOfflineQueue(userId: string)` React hook — `useState` + `subscribeQueue` + `getQueueSnapshot` 통합 (mount 시 fetch + subscribe + unmount cleanup).
- [x] 6.2 jitter 구현 — `const backoffMs = baseMs * (1 + (Math.random() * 0.4 - 0.2))` (±20%).
- [x] 6.3 schema deserialize 실패 가드 — `JSON.parse` try/catch + 실패 시 빈 array 반환 + `AsyncStorage.removeItem` (silent reset).
- [x] 6.4 mutex 단언 — module-level `let flushing: Promise<FlushResult> | null = null;` + `if (flushing) return flushing` 분기.
- [x] 6.5 `pnpm tsc --noEmit` + `pnpm lint` 통과.

### Task 7 — `mobile/features/meals/api.ts` `createMeal` + `useCreateMealMutation` 갱신 (AC: #4)

- [x] 7.1 `createMeal` 시그니처 갱신 — `async function createMeal(body: MealCreateRequest, opts?: { idempotencyKey?: string }): Promise<MealResponse>`. `opts?.idempotencyKey` truthy 시 `headers['Idempotency-Key'] = opts.idempotencyKey` 첨부.
- [x] 7.2 `useCreateMealMutation` 갱신 — `mutate(body)` 시 mutation 내부에서 `expo-crypto` `randomUUID()` 호출 (또는 `globalThis.crypto.randomUUID()` polyfill — RN 0.81 기준 `expo-crypto`가 안전). `mutationFn: (body) => createMeal(body, { idempotencyKey: randomUUID() })` 갱신. `onSuccess` `invalidateQueries` 그대로.
- [x] 7.3 docstring에 *"Story 2.5 — Idempotency-Key 자동 첨부 (W46 흡수)"* 1줄.
- [x] 7.4 `pnpm tsc --noEmit` + `pnpm lint` 통과.

### Task 8 — `mobile/app/(tabs)/meals/input.tsx` 갱신 — 텍스트 큐잉 + 사진 차단 + PATCH 차단 (AC: #5)

- [x] 8.1 `useOnlineStatus` import + 분기 — `onSubmit` 함수에서 `!isOnline` 체크 → 텍스트만이면 `enqueueMealCreate(userId, {...})` + `router.replace`, 사진 첨부 시 Alert + return.
- [x] 8.2 카메라/갤러리 탭 onPress 핸들러 갱신 — `!isOnline` 시 즉시 Alert + early return (권한 prompt 진입 차단).
- [x] 8.3 PATCH 모드 진입 시 `useEffect`에서 `!isOnline` 체크 → Alert + `router.back()` (편집 자체 차단).
- [x] 8.4 `userId`는 `useCurrentUser()` 또는 `useAuthContext()`에서 추출 — `mobile/lib/auth.tsx` 정합. 없으면 `(auth)/login` redirect (정상 흐름).
- [x] 8.5 큐잉 후 Toast/Alert 안내 — 본 baseline은 Alert *"오프라인 — 동기화 대기 중"* (Toast 라이브러리 없음 — 단순). UX는 단순한 *"확인"* 1버튼 + `router.replace`.
- [x] 8.6 `pnpm tsc --noEmit` + `pnpm lint` 통과.

### Task 9 — `mobile/app/(tabs)/meals/index.tsx` 갱신 — 배지 + optimistic 카드 + 자동 flush (AC: #6, #8)

- [x] 9.1 `useOfflineQueue(userId)` hook 사용 — 큐 snapshot + 변경 트리거.
- [x] 9.2 헤더 영역 *"동기화 대기 중"* 배지 — `Stack.Screen options.headerRight` 또는 별도 row. `queueSize > 0` 시 노출. 탭 시 ActionSheet — 항목별 *"다시 시도"* / *"폐기"*.
- [x] 9.3 list 합치기 — `selectedDate === todayKst()` 시 `[...queueItems, ...serverMeals]` 또는 `[...serverMeals, ...queueItems]` (시간순 ASC 정합 — `enqueued_at` 기준 정렬). 큐 카드 visual 분리(회색 배경 + 배지).
- [x] 9.4 자동 flush — `useEffect`에서 `useOnlineStatus` 변경 detect 후 `flushQueue(userId, authFetch)` 호출. prev `isOnline` ref + current 비교 (`undefined → true`도 첫 fetch 분기 정합).
- [x] 9.5 큐 카드 컴포넌트 — `OfflineMealCard.tsx` 신규 또는 `MealCard.tsx` 내부 분기 (props 추가 — `mode: 'server' | 'queue'`). 본 baseline은 *별 컴포넌트 신규* 채택 (책임 분리 + Story 2.4 `MealCard` 회귀 차단).
- [x] 9.6 빈 화면 분기 갱신 — `selectedDate === todayKst()` + server 0건 + queue 0건만 *"오늘 기록 없음"* 노출. queue size > 0 시 큐 카드 표시.
- [x] 9.7 NFR-A3 폰트 200% 검증 + accessibility 라벨.
- [x] 9.8 `pnpm tsc --noEmit` + `pnpm lint` 통과.

### Task 10 — README + sprint-status + deferred-work + smoke 검증 + commit/push (AC: #11, #12)

- [x] 10.1 `README.md` — 기존 *"일별 식단 기록 화면 + 7일 로컬 캐시 SOP (Story 2.4)"* 단락 다음에 *"오프라인 텍스트 큐잉 + 자동 sync SOP (Story 2.5)"* 1 단락 추가 (간결 — 6 줄 이하, AC12 명시 6항목).
- [x] 10.2 `_bmad-output/implementation-artifacts/deferred-work.md` 갱신:
  - **W46 closed (Story 2.5)** — `meals.idempotency_key` 컬럼 + partial UNIQUE + 200 idempotent replay (W46 strikethrough + closed 표기).
  - 본 스토리 신규 deferred 후보 추가 — *Dev Notes — 신규 deferred 후보* 섹션 transcribe.
- [x] 10.3 smoke 검증 9 시나리오 — AC11 그대로(local 환경에서 사용자 별도 수행). 본 task는 *Dev Agent Record Completion Notes에 결과 기록*만 — 백엔드/모바일 게이트 통과로 충분.
- [x] 10.4 Dev Agent Record + File List + Completion Notes 작성 후 `Status: review` 전환.
- [x] 10.5 `_bmad-output/implementation-artifacts/sprint-status.yaml` — `2-5-오프라인-텍스트-큐잉-sync` `ready-for-dev` → `in-progress` → `review`로 갱신.
- [x] 10.6 commit + push (메모리 `feedback_ds_complete_to_commit_push.md` 정합 — DS 종료점은 commit + push, PR은 CR 완료 후). 브랜치 `story/2.5-offline-text-queue-sync`(이미 master에서 분기 — 메모리 `feedback_branch_from_master_only.md` 정합).

## Dev Notes

### Architecture decisions (반드시 따를 것)

[Source: architecture.md#Data Architecture (line 281-299), architecture.md#API Patterns (line 314-326, 455-505), architecture.md#Architectural Boundaries (line 845-868), architecture.md#Project Structure (line 661-728, 800-833), architecture.md#Naming Patterns (line 386-431), epics.md#Story 2.5 (line 565-577), prd.md#FR16, prd.md#NFR-R4, prd.md#M3 (line 644-650), prd.md#NFR-S5, deferred-work.md#W46, Story 2.1/2.2/2.3/2.4 패턴]

**Idempotency-Key 처리 (W46 흡수, D1 결정)**

- `meals.idempotency_key TEXT NULL` 컬럼 + `(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL` partial UNIQUE index 채택. `MealResponse`에 idempotency_key 노출 X(클라이언트 입력 echo 회피 + payload 경량화).
- D1 결정 사유 (option A/B/C 중 B 채택):
  - **A — `meals` 테이블 단일 컬럼 (채택)**: 단일 PG row 단위 멱등화 + Story 2.1 partial index 패턴 정합 + scope 단순. partial UNIQUE는 NULL 미포함 — 헤더 미송신 입력 회귀 0.
  - **B — 별도 `idempotency_keys` 테이블** (Stripe webhook 표준): 다중 도메인 활용 가능(future Story 6.x 결제), 스키마 격리. but 본 스토리는 `meals` POST만 도입 — over-engineering.
  - **C — Redis 캐시 (TTL)**: 빠른 lookup + 자동 만료. but Postgres 단일 출처 정합성 ↓ + Redis 다운 시 race 차단 부재. R2(메모리 / persist) 별 라인.
- 실제 W46 시나리오: 사용자가 *저장* 탭 후 OS가 앱을 background → kill → 사용자 재개 후 재시도 (모바일 표준 패턴) → 같은 식단 2 row 생성 (현 baseline). Story 2.5 `Idempotency-Key` 자동 첨부 + 서버 200 replay로 *2 row 생성 차단*.
- partial UNIQUE는 `WHERE idempotency_key IS NOT NULL` — Story 2.1 `idx_meals_user_id_ate_at_active` partial index 패턴 정합. NULL은 unique 제약 미적용 — 헤더 미송신 입력은 자유.
- 동시 race 처리 — DB UNIQUE 제약 위반 → `IntegrityError` catch + 재 SELECT (race-free pattern). soft-deleted row 충돌 분기는 별 409 (`MealIdempotencyKeyConflictDeletedError`).
- HTTP status 200 vs 201 — RFC 9110 idempotent retry는 *replay = 200 OK* (resource는 이미 존재). 첫 INSERT는 그대로 201.

**오프라인 큐잉 storage (D2 결정)**

- AsyncStorage 채택 (Story 1.6 `bn:onboarding-tutorial-seen-*` + Story 2.4 `bn-rq-cache` 정합). 신규 의존성 0건.
- D2 결정 사유 (option A/B 중 A 채택):
  - **A — AsyncStorage** (채택): 이미 설치 + Story 1.6/2.4 패턴 + 단일 디바이스 단일 사용자 가정에서 충분. 큐 size ≤ 100 hard cap → I/O 부담 미미.
  - **B — MMKV (`react-native-mmkv`)**: 100x 빠른 sync I/O + JSI native 통합. but 신규 native 의존성 + 빌드 회귀 risk + 8주 일정 정합. Growth 시점 재평가.
- per-user namespace (`bn:offline-queue:meal:<user_id>`) — 다중 사용자 동일 디바이스 시 격리 (Story 1.6 `tutorialState.ts` 정합). UUID v4 user_id 가정.
- AsyncStorage 키 컨벤션 — Story 1.6 `bn:onboarding-tutorial-seen-<user_id>` 패턴 정합 — `bn:<namespace>:<entity>:<scope_id>` 4-segment.
- schema migration 가드 — 큐 deserialize 실패 시 빈 큐 반환 + silent reset (사용자 안내 X — 데이터 손실 미미). Story 8 polish 시점에 buster 패턴 도입(deferred-work).

**큐 항목 schema 결정 (D3)**

- `client_id` = `Idempotency-Key` 값 — 단일 UUID v4 두 책임 (큐 식별자 + 서버 멱등 키). 유지보수 단순성 우선.
- `parsed_items?` 인터페이스 호환 유지 — 본 스토리 baseline은 *항상 null* (사진 큐잉 OUT). Story 2.3 schema sharing — 스토리 진화 시점에 사진+OCR 흐름의 부분 큐잉(예: 텍스트는 큐 + 사진은 사용자 retry 안내) 도입 가능.
- `attempts` `number` — 시도 횟수. backoff 계산 + UI 표시(*"3회 시도 실패"*). `last_error` 텍스트는 UI 노출 (raw text — Sentry/PII 마스킹은 Story 8).
- `enqueued_at` ISO 8601 — FIFO 정렬 키 + UI sub-text(*"5분 전 입력"*). KST `+09:00` 가정 (Story 2.4 D1 정합).
- `ate_at` 큐잉 시점 KST now 자동 채움 — 사용자가 큐잉한 시점이 식단 시점이라는 직관 정합. 서버 fallback(`server_default=now()`)은 *큐 flush 시점*이라 의미 differs — 큐잉 시점 우선.

**재시도 정책 (D4)**

- 지수 backoff `1s → 2s → 4s` + jitter ±20% — 표준 패턴(AWS / GCP / Stripe webhook). 3회 후 재시도 중단 + 큐 잔존(epic AC line 575).
- partial 실패 granular — 항목별 backoff (전체 큐 abort X). 단 5xx 또는 네트워크 에러 시 flush 중단 (다음 항목 시도 X — *전체 transient* 가정 + backoff 의미 보존).
- 4xx (validation) → 영구 실패 → 큐 즉시 제거 + 사용자 안내. retry 무의미.
- manual retry — 사용자가 큐 카드 *"다시 시도"* 탭 시 `flushQueue` 강제 호출 + `attempts` reset (또는 +1 — 본 baseline은 reset 채택, Story 8 정밀화).

**사진 입력 오프라인 차단 (D5)**

- 카메라/갤러리 탭 onPress 시 *즉시* `!isOnline` 체크 + 권한 prompt 진입 차단 — UX 명료성 (사용자가 권한 거부 흐름과 오프라인 흐름 혼동 차단).
- 사진+OCR 흐름은 R2 presigned URL + R2 PUT + Vision API 모두 *온라인 필수* — 큐잉 가능 stage 부재 (epic AC line 576 *"사진 입력은 오프라인 큐잉 대상 아님"*).
- PATCH/DELETE 흐름도 *온라인 필수* — 본 스토리 baseline은 PATCH 모드 진입 시 Alert + back 차단 (Story 8 polish에서 PATCH 큐잉 검토 — deferred-work).

**자동 flush 트리거 (D6)**

- `useOnlineStatus` offline → online 전이 시 `flushQueue` 자동 호출. 단일 트리거 (mutex로 중복 차단).
- 앱 cold start 시 `useOnlineStatus` initial fetch가 online 즉시 보고 → useEffect 첫 trigger에서 prev `undefined` → current `true` → flush 1회 호출 (잔존 큐 자동 sync). intentional — `_stateToStatus` `isConnected !== false` 정합.
- 큐 size 0 + flush 호출은 no-op (logger silent — UX 정합).

### Library / Framework 요구사항

[Source: architecture.md#Mobile (line 132-152), architecture.md#API Patterns, mobile/package.json 정합, Story 2.1/2.2/2.3/2.4 Dev Notes 패턴]

| 영역 | 라이브러리 | 정확한 사유 |
|------|-----------|-----------|
| 백엔드 partial UNIQUE | SQLAlchemy `Index('idx_meals_user_id_idempotency_key_unique', ..., unique=True, postgresql_where=text('idempotency_key IS NOT NULL'))` | Story 2.1 `idx_meals_user_id_ate_at_active` partial index 패턴 정합. NULL 제외 unique. |
| 백엔드 Idempotency 헤더 | FastAPI `Header(default=None, alias="Idempotency-Key")` | RFC 7240/9110 표준 헤더. CORS allow_headers는 main.py:140에 이미 등록. |
| 백엔드 race-free | SQLAlchemy `IntegrityError` catch + `db.rollback()` + 재 SELECT | Story 2.1 race-free RETURNING + Story 2.2 `head_object` HEAD-check 패턴 정합. |
| 백엔드 UUID v4 검증 | regex `^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$` | Python `uuid.UUID(version=4)` 회피 — application-level regex 명료성 + Story 2.2 `_IMAGE_KEY_PATTERN` 패턴 정합. |
| 모바일 큐 storage | `@react-native-async-storage/async-storage@2.2.0` (이미 설치) | Story 1.6/2.4 정합. 신규 의존성 0건. |
| 모바일 NetInfo | `@react-native-community/netinfo@^12.0.1` (이미 설치 — Story 2.4) | 자동 flush 트리거. 신규 의존성 0건. |
| 모바일 UUID 생성 | `expo-crypto` `randomUUID()` (이미 설치 — `mobile/package.json` `expo-crypto: ~15.0.9`) | RN `crypto.randomUUID()` 직접 호출은 Hermes 엔진 호환성 risk — `expo-crypto`가 RN 표준. UUID v4 보장. 신규 의존성 0건. |
| 모바일 Pub/Sub 패턴 | module-level subscriber set + notify (Story 1.6 `tutorialState.ts` 정합) | 신규 의존성 0건. zustand/jotai 회피 — 단일 큐 상태에 over-engineering. |
| 모바일 React hook | `useState` + `useEffect` + `subscribeQueue` 통합 | Story 1.6/2.4 정합. TanStack Query 미사용 — 큐는 *클라이언트 단독 상태*(server state X). |

### Naming 컨벤션

[Source: architecture.md#Naming Patterns (line 386-431), Story 2.1/2.2/2.3/2.4 정합]

- DB 컬럼: `idempotency_key` (snake_case line 411). nullable.
- DB 인덱스: `idx_meals_user_id_idempotency_key_unique` (Story 2.1 `idx_meals_user_id_ate_at_active` 패턴 정합 — `idx_<table>_<columns>_<modifier>`).
- API URL: `POST /v1/meals` 그대로 (헤더만 추가). 변경 X.
- API JSON wire: `idempotency_key` 응답 노출 X (헤더 송신만). `MealResponse` 11 필드 그대로.
- 헤더: `Idempotency-Key` (RFC 7240 표준 case — Header alias로 case-insensitive forward).
- Python 파일: 변경 0 — `api/app/api/v1/meals.py` + `api/app/db/models/meal.py` + `api/app/core/exceptions.py` 갱신만. 신규는 *마이그레이션*(`api/alembic/versions/0009_meals_idempotency_key.py`) + *테스트*(`api/tests/test_meals_router.py` 갱신).
- Python 클래스: `MealIdempotencyKeyInvalidError`/`MealIdempotencyKeyConflictDeletedError` (PascalCase line 420 — `MealError` 패턴 정합).
- Python 함수: `_create_meal_idempotent_or_replay`/`_validate_idempotency_key` (snake_case + leading underscore — module-private).
- TS/Mobile 파일: `mobile/lib/offline-queue.ts` (kebab-case + camelCase 모듈 패턴 — Story 2.4 `query-persistence.ts`/`use-online-status.ts` 정합).
- TS 함수: `enqueueMealCreate`/`flushQueue`/`getQueueSnapshot`/`removeQueueItem`/`subscribeQueue`/`useOfflineQueue` (camelCase + use- prefix hook 컨벤션).
- TS 타입: `OfflineQueueItem`/`OfflineQueueFullError`/`FlushResult` (PascalCase).
- AsyncStorage 키: `bn:offline-queue:meal:<user_id>` (Story 1.6 `bn:onboarding-tutorial-seen-<user_id>` 패턴 정합 — `bn:<namespace>:<entity>:<scope_id>`).
- 에러 코드 카탈로그: `meals.idempotency_key.invalid` (400) + `meals.idempotency_key.conflict_deleted` (409) — Story 2.1/2.2/2.3 `meals.*` 카탈로그 정합.
- 로깅 이벤트: `meals.create.idempotent_replay` (logger.info — replay 분기에서만 1줄. Story 1.4 `consents.basic.persisted` 패턴 정합).

### 폴더 구조 (Story 2.5 종료 시점에 *반드시* 존재해야 하는 신규/수정 항목)

[Source: architecture.md#Complete Project Directory Structure (line 661-728, 800-833), Story 2.1/2.2/2.3/2.4 종료 시점 골격]

```
api/
├── alembic/versions/
│   └── 0009_meals_idempotency_key.py                     # 신규 — meals.idempotency_key TEXT NULL + partial UNIQUE
├── app/
│   ├── api/v1/
│   │   └── meals.py                                       # 갱신 — Idempotency-Key 헤더 처리 + race-free helper + 200 분기
│   ├── core/
│   │   └── exceptions.py                                  # 갱신 — MealIdempotencyKeyInvalidError + MealIdempotencyKeyConflictDeletedError
│   └── db/models/
│       └── meal.py                                        # 갱신 — idempotency_key Mapped + partial UNIQUE Index
└── tests/
    ├── test_meals_router.py                               # 갱신 — Idempotency 9 신규 케이스 + PATCH 회귀 1 케이스
    └── test_meals_idempotency_key_schema.py               # 신규(선택) — alembic 마이그레이션 회귀

mobile/
├── app/
│   └── (tabs)/
│       └── meals/
│           ├── index.tsx                                  # 갱신 — useOfflineQueue + 배지 + optimistic 카드 + 자동 flush
│           └── input.tsx                                  # 갱신 — 오프라인 분기(텍스트 큐잉) + 사진 차단 + PATCH 차단
├── features/
│   └── meals/
│       ├── api.ts                                         # 갱신 — createMeal idempotencyKey opt + useCreateMealMutation Idempotency-Key 첨부
│       └── OfflineMealCard.tsx                            # 신규 — 큐 항목 표시 카드(회색 + 배지 + 다시시도/폐기)
└── lib/
    └── offline-queue.ts                                   # 신규 — AsyncStorage FIFO 큐 + mutex + backoff + subscribeQueue + useOfflineQueue

web/
└── src/lib/
    └── api-client.ts                                      # 갱신 (자동 — pnpm gen:api) — 200 응답 + 새 에러 코드 노출

README.md                                                  # 갱신 — 오프라인 텍스트 큐잉 + 자동 sync SOP 1 단락 추가
_bmad-output/implementation-artifacts/sprint-status.yaml   # 갱신 — 2-5 → review (DS 종료 시점)
_bmad-output/implementation-artifacts/deferred-work.md     # 갱신 — W46 closed + 본 스토리 신규 deferred 후보 추가
```

**중요**: 위에 명시되지 않은 항목(`meal_analyses` 테이블 + ALTER, `app/services/analysis_service.py`, `app/api/v1/analysis.py` SSE endpoint, `app/graph/*` LangGraph 노드, `app/domain/fit_score.py` 알고리즘, RAG 시드, react-native-sse 채팅, `cache:llm:*` Redis 캐시, MMKV/zustand 도입, 별 idempotency_keys 테이블)은 본 스토리에서 생성하지 않는다 (premature scaffolding 회피, Story 2.1/2.2/2.3/2.4 정합):

- `meal_analyses` 테이블 + ALTER: Story 3.3 책임. 본 스토리는 `meals` 1 컬럼만.
- `analysis_service.py` + `app/api/v1/analysis.py` SSE endpoint: Story 3.6/3.7 책임.
- `app/graph/*` LangGraph 노드: Story 3.3.
- `app/domain/fit_score.py` 알고리즘: Story 3.5.
- RAG 시드: Story 3.1/3.2.
- react-native-sse 채팅: Story 3.7.
- `cache:llm:*` Redis 캐시: Story 8 perf hardening.
- MMKV/zustand 도입: AsyncStorage + module-level subscriber 충분 (D2 정합 — Growth 재평가).
- 별 `idempotency_keys` 테이블: D1 정합 — `meals.idempotency_key` 컬럼 단일 출처. Story 6.x 결제 도입 시점에 별 도메인 base 검토.
- PATCH/DELETE 큐잉: epic AC line 573 *"텍스트 식단 입력"* — POST 흐름만. PATCH/DELETE 큐잉은 Story 8 polish.

### 보안·민감정보 마스킹 (NFR-S5)

[Source: prd.md#NFR-S5, architecture.md#Authentication & Security (line 309), Story 2.1/2.2/2.3/2.4 Dev Notes]

- **`idempotency_key` 로그 X** — 클라이언트 UUID는 PII 가능성 낮으나 *디바이스 fingerprint*에 활용 가능 — 라우터 logger.info에서 `idempotency_key` 직접 출력 금지(`meal_id` + `user_id`만). UUID v4 자체는 random — 식별자 leak 영향 0.
- **AsyncStorage 큐 보안** — `bn:offline-queue:meal:<user_id>` 키에 raw_text 저장. *디바이스 분실*에 leak risk — 토큰 + 저장된 식단 텍스트(*"점심 짜장면"* 등 식별자 포함 가능 텍스트). NFR-S5 *"raw_text 내용 로그 마스킹"* 정합 — 큐 내용 자체는 사용자 입력이므로 *원본 보존* 정상 (Sentry capture 시점에 마스킹은 Story 8). 디바이스 분실 + AsyncStorage 노출 시나리오는 *디바이스 OS-level 암호화*에 위임 (Expo SecureStore는 토큰 전용 — 식단 raw text는 일반 storage).
- **`Idempotency-Key` cross-user 격리** — `(user_id, idempotency_key)` partial UNIQUE — 사용자 A의 키를 사용자 B가 송신해도 user_id가 정합되어 별 row 생성 (테스트 단언 AC10 정합 — `test_post_meal_with_idempotency_key_different_users_isolated`).
- **race resolution 시 timing attack** — 동시 race에서 winner는 INSERT (즉시), loser는 IntegrityError + 재 SELECT (latency ↑). 클라이언트는 두 경우 모두 동일 응답 (timing leak 무의미 — 사용자 본인 식단만 영향).
- **soft-deleted row와 같은 키 race** — `MealIdempotencyKeyConflictDeletedError(409)` 분기 — *삭제된 식단을 알리는* leak 가능. but soft delete는 *본인 row만* — 사용자 본인 정보로 leak 영향 0. 문구 *"이미 삭제된 식단입니다"*는 명료성 우선.
- **`MealIdempotencyKeyInvalidError(400)` enumeration 차단** — 형식 위반은 즉시 거부 (catalog code `meals.idempotency_key.invalid`). 사용자 input echo 회피 — Pydantic raw msg 노출 X (W10 carry-over).

### Anti-pattern 카탈로그 (본 스토리 영역)

[Source: Story 2.1/2.2/2.3/2.4 Anti-pattern 카탈로그, architecture.md#Anti-pattern (line 557-565)]

- ❌ Backend `idempotency_keys` 별 테이블 + JOIN 조회 — single-row 단순 멱등화에 over-engineering. **채택**: `meals.idempotency_key` 단일 컬럼 + partial UNIQUE.
- ❌ Backend Idempotency 처리 시 *body 내용 dedup* — *키 == 한 번* 시맨틱과 다름. **채택**: Stripe/Toss 표준 — 같은 키 = 같은 응답 (body diff 무시).
- ❌ Backend Idempotency replay 시 *201* 응답 — RFC 9110 위반(자원 *생성* 의미). **채택**: replay = 200 OK + 기존 row.
- ❌ Backend race resolution 시 *single SELECT-then-INSERT* (TOCTOU race) — 동시 INSERT 시 partial UNIQUE 위반 → 5xx 누출. **채택**: SELECT-then-INSERT-then-CATCH-then-SELECT race-free 패턴.
- ❌ Backend `Idempotency-Key` Pydantic body validator — 헤더는 body 외부. **채택**: FastAPI `Header(alias="Idempotency-Key")` 의존성.
- ❌ Backend UUID v4 검증을 `uuid.UUID(version=4)` Python 표준 — Python은 v1/v2/v3/v4 구분 시 `version` arg 무시 케이스 존재. **채택**: regex 명시 (Story 2.2 `_IMAGE_KEY_PATTERN` 정합).
- ❌ Mobile `localStorage`/`SecureStore` 큐 storage — RN `localStorage` 부재 + SecureStore는 토큰 전용. **채택**: AsyncStorage (Story 1.6/2.4 정합).
- ❌ Mobile MMKV 도입 — 신규 native 의존성 + 빌드 회귀 risk. **채택**: AsyncStorage 100건 cap에서 충분.
- ❌ Mobile zustand/jotai 큐 상태 — 단일 큐 상태에 over-engineering. **채택**: module-level subscriber set + `useState` (Story 1.6 정합).
- ❌ Mobile `setInterval`로 주기적 flush — 배터리 + 네트워크 abuse. **채택**: 이벤트 기반 (`useOnlineStatus` 변경 + manual retry).
- ❌ Mobile `optimisticUpdate` `useMutation` — 큐잉은 *server-side absent* 시점이라 optimistic 의미 differs. **채택**: 큐 카드를 list에 client-side merge (별 visual + 실 row와 분리).
- ❌ Mobile `Idempotency-Key` 사용자 input — UUID 자동 생성 + 사용자 미노출. **채택**: `expo-crypto` `randomUUID()` 자동.
- ❌ Mobile flush 중 `Promise.all` 동시 sync — 멱등화는 race에서 *다중 200* 가능이지만 transient 에러 시 backoff 의미 손실. **채택**: 순차 FIFO + transient 에러 시 flush 중단.
- ❌ Mobile 큐에 PATCH/DELETE 항목 추가 — epic AC 명시 *"텍스트 식단 입력"* (POST). **채택**: POST 큐잉만 + PATCH/DELETE 오프라인 차단.
- ❌ Mobile 사진 큐잉 — 사진+R2+Vision 모두 *온라인 필수* 단계 (epic AC line 576). **채택**: 사진 입력 오프라인 차단.
- ❌ Mobile 큐 무제한 누적 — 디바이스 storage abuse. **채택**: 100건 hard cap + Alert.
- ❌ Mobile 4xx (validation) 응답 시 큐 잔존 + 무한 재시도 — abuse + UX 혼란. **채택**: 4xx 즉시 제거 + 사용자 안내.
- ❌ Mobile cross-user 큐 공유 — 같은 디바이스 다른 사용자 격리 부재 시 leak. **채택**: per-user namespace (`bn:offline-queue:meal:<user_id>`).

### Previous Story Intelligence (Story 2.1/2.2/2.3/2.4 학습)

[Source: `_bmad-output/implementation-artifacts/2-1-식단-텍스트-입력-crud.md` + `2-2-식단-사진-입력-권한-흐름.md` + `2-3-ocr-vision-추출-확인-카드.md` + `2-4-일별-식단-기록-화면.md` Dev Agent Record + Review Findings + `deferred-work.md`]

**적용 패턴(반드시 재사용):**

- **race-free RETURNING 단일 statement** (Story 2.1 P5 / 2.2 / 2.3 정합): 본 스토리는 *Idempotency replay race* 처리 — 동일 패턴 확장(`IntegrityError` catch + 재 SELECT). race-free 단일 statement는 INSERT … RETURNING 그대로 + 추가 SELECT layer.
- **DB-side `func.now()` 단일 시계** (Story 2.1 P10 / 2.2 정합): 본 스토리는 시계 영향 0 (Idempotency는 시간 무관).
- **OpenAPI 자동 재생성** (Story 1.4 P20 / 1.5 / 1.6 / 2.1 / 2.2 / 2.3 / 2.4 패턴): 신규 200 응답 코드 + 신규 에러 코드 추가 시 `pnpm gen:api` 후 클라이언트 재생성 + commit. CI `openapi-diff` 게이트.
- **`extra="forbid"` Pydantic 모델** (Story 1.5/2.1/2.2/2.3/2.4 정합): 본 스토리는 신규 Pydantic 모델 0건 (헤더 의존성만).
- **`extractSubmitErrorMessage` 패턴** (Story 1.5/2.1/2.2/2.3/2.4 정합): 본 스토리는 큐 flush 4xx 처리 시 *raw_text 발췌 + 에러 메시지* Alert. extractSubmitError 직접 호출 X — 큐 flush context는 hook 외부.
- **conftest TRUNCATE 갱신 X**: `meals` 그대로 + 신규 컬럼은 nullable이라 TRUNCATE 영향 0.
- **`accessibilityRole`/`accessibilityLabel` 명시**: 큐 카드 + 배지 + ActionSheet 액션 모두 (Story 2.4 정합).
- **typed-routes cast** (Story 2.1 W9 / 2.2 / 2.3 / 2.4 정합): 본 스토리는 라우팅 변경 0 (input.tsx + index.tsx 화면 내 처리).
- **partial UNIQUE index** (Story 2.1 `idx_meals_user_id_ate_at_active` 정합): 본 스토리 `idx_meals_user_id_idempotency_key_unique` 동일 패턴 (NULL 제외 unique).

**Story 2.1/2.2/2.3/2.4 deferred-work.md 항목 — 본 스토리 처리:**

- ✅ **W46 (Story 2.1) — 앱 백그라운드/킬 mid-mutation 시 중복 POST** — **본 스토리에서 흡수** (AC2/AC10/AC12 정합 — `meals.idempotency_key` 컬럼 + 200 idempotent replay + race partial UNIQUE). deferred-work.md에 closed 표기 + strikethrough.
- 🔄 **DF1-DF14 (Story 2.2/2.3)** — 본 스토리 영향 X (Story 8 / Story 3.x 책임 그대로).
- 🔄 **DF15 (Story 2.3) — `MealCard.tsx` parsed_items 표시 forward** — Story 2.4에서 해소 (carry-over closed).
- 🔄 **DF16-DF26 (Story 2.4)** — 본 스토리 영향 X (Story 8 polish / Growth UX 책임 그대로).
- 🔄 **W42 (Story 2.1) — `MealError` base 클래스 추상 가드** — **재 deferred** Story 8. 본 스토리는 신규 두 예외 추가만 — base 추상 가드 미도입.
- 🔄 **W43-W45 (Story 2.1)** — 재 deferred Story 8.
- 🔄 **W47-W51 (Story 2.1)** — 본 스토리 영향 X.
- 🔄 **W49 (Story 2.1) — `formatHHmm` 디바이스 로컬 TZ** — Story 2.4에서 해소 (carry-over closed).
- 🔄 **W50 (Story 2.1) — KST/UTC 드리프트** — Story 2.4에서 해소 (carry-over closed).
- 🔄 **W14 (Story 1.3) — `require_basic_consents` 라우터 wire** — 본 스토리는 *POST 흐름*(Story 2.1에서 wire 완료) 그대로 — 추가 wire 0.

**신규 deferred 후보 (본 스토리 종료 시 `deferred-work.md` 추가):**

- *DF27 — PATCH/DELETE 오프라인 큐잉* — 본 스토리 baseline은 PATCH/DELETE 오프라인 차단(Alert + back). 사용자가 오프라인에서 수정하려는 케이스(예: 제품 데모 중 회식 후 식단 수정)는 *Story 8 polish* — 큐잉 + 자동 flush 도입 검토.
- *DF28 — 사진 큐잉 (online deferred sync)* — 본 스토리 baseline은 사진 입력 오프라인 차단. *온라인 시 사진 첨부 + 텍스트는 큐잉(Vision 호출은 차후)* 부분 큐잉은 *Growth* — Vision 호출 비용 + UX 복잡도.
- *DF29 — `OfflineQueueItem` schema buster* — 본 스토리 baseline은 deserialize 실패 시 silent reset. *명시 buster 패턴*(`v1` → `v2` bump on schema change)은 Story 8 polish (Story 2.4 query-persistence DF21 정합).
- *DF30 — manual retry granular `attempts` reset 정책* — 본 스토리 baseline은 reset 채택. *attempts 누적 + 재시도 횟수 cap*은 Story 8 polish (사용자 manual retry 무한 재시도 차단).
- *DF31 — 큐 size 동적 cap* — 본 스토리 baseline은 100건 hard cap. *디바이스 storage / 사용자 설정 기반 동적 조정*은 Growth UX polish.
- *DF32 — Sentry/PII 마스킹 큐 데이터* — 본 스토리 baseline은 raw_text 그대로 큐 보관 + 4xx 시 Alert에 raw 노출. *Sentry capture 시점에 raw_text 마스킹*은 Story 8 polish.
- *DF33 — `Idempotency-Key` 도메인 격리* — 본 스토리 baseline은 `MealIdempotencyKeyInvalidError(MealError)` 식단 도메인 하위. *Story 6.x 결제 webhook idempotency 도입* 시점에 *`IdempotencyError` cross-cutting base*로 분리 검토.
- *DF34 — Idempotency-Key TTL* — 본 스토리 baseline은 `meals.idempotency_key`가 *영구 보존* (soft delete 후에도 unique 충돌 가능 — 409 분기). *TTL 정책*(예: 7일 후 NULL clear)은 Story 5.x 데이터 보존 정책 + Story 8 cron 도입 시점에 검토.
- *DF35 — flush 중 transient 에러 시 다음 항목 진행* — 본 스토리 baseline은 transient 에러 시 flush 중단(첫 항목 backoff 의미 보존). *batch parallel sync*는 Story 8 polish — race + UX 트레이드오프 평가.
- *DF36 — `OfflineMealCard.tsx` 재시도 횟수 visual progress* — 본 스토리 baseline은 *"3회 시도 실패"* 텍스트만. *progress bar / step indicator*는 Story 8 UX polish.
- *DF37 — 큐 항목 *시간 ordering*은 `enqueued_at` 기준 — 사용자가 *어제 자정에 입력 → 오늘 sync* 시 일자 표시는 *어제* (`ate_at` 기준)지만 큐 표시는 *오늘 입력*으로 처리. UX 명료성은 Story 8 polish.

**Detected Conflict 처리:**

- Story 2.1/2.2/2.3/2.4 결정(`/v1/meals/*` REST CRUD, race-free RETURNING, 404 일원화, raw_text NOT NULL invariant, soft delete, image_key + ownership 검증, R2 head_object HEAD-check, 11 필드 응답 + analysis_summary 슬롯, parsed_items jsonb, OCR 흐름, KST 필터, 7일 캐시) 그대로 활용.
- 새로운 충돌: **없음** — 본 스토리는 epic AC + architecture 명시 정합 패턴 그대로 구현.
- *epic AC line 575 *"지수 backoff 재시도 정책 3회"** vs *AC3/D4 결정 — `1s/2s/4s` 명시* — epic은 *3회*만 명시 + interval은 구현 책임. **채택**: `1s → 2s → 4s` 표준 (AWS/GCP/Stripe).
- *architecture line 150 `@react-native-async-storage/async-storage` — FR16 오프라인 큐잉* — 본 스토리에서 wire 완료. architecture 표기 정합.
- *architecture line 832 `mobile/lib/offline-queue.ts` — FR16 텍스트 큐잉* — 본 스토리에서 신규 생성. architecture 표기 정합.
- *architecture line 524-531 *Idempotency-Key 카탈로그 — Stripe/Toss webhook* — 본 스토리는 식단 도메인에 첫 적용. *결제 webhook*(Story 6.3)와 패턴 sharing 가능 — Story 6.3 시점에 cross-cutting base 분리 검토(deferred DF33).
- *architecture line 974 *Meals FR16 → mobile lib/offline-queue.ts (AsyncStorage)** — 본 스토리에서 해소. architecture 표기 정합.

### Git Intelligence (최근 커밋 패턴)

```
405a911 fix(story-2.4): Gemini Code Assist 3 patches — query window dynamic + tomorrow 포함 + offline edit/delete 가드
7f7411c feat(story-2.4): CR 11 patches — KST overflow + gcTime 7d + score-label validator + 다음 일자 disable + 7일 윈도우 client filter (D1 옵션 b) + DF42 closed
f5e38c9 feat(story-2.4): 일별 식단 기록 화면(시간순 + 날짜 picker) + 7일 로컬 캐시 + KST 필터(W50 해소) + analysis_summary 슬롯
40403f3 feat(story-2.3): OCR Vision 추출 + 사용자 확인 카드 + parsed_items 영속화 + CR 8 patch (#14)
cf93900 chore(story-2.2): mark done — sprint-status + spec Status review → done (post-merge fix) (#13)
```

**최근 커밋 패턴에서 학습:**

- 커밋 메시지: `feat(story-X.Y): <한국어 요약> + <부수 작업>` 형식 — 본 스토리도 `feat(story-2.5): 오프라인 텍스트 큐잉(AsyncStorage FIFO + 지수 backoff) + Idempotency-Key 처리(W46 흡수) + 자동 flush(useOnlineStatus 트리거) + 사진/PATCH 오프라인 차단` 패턴.
- *spec 모순 fix 커밋*: `docs(story-X.Y): spec ACN <줄번호> 모순 fix`.
- OpenAPI 재생성 커밋 분리 권장 (Story 2.1/2.2/2.3/2.4 정합).
- CR patches 커밋 분리 — code review 후 패치는 별 커밋(`fix(story-2.5): CR <N> patches`).
- master 직접 push 금지 — feature branch + PR + merge 버튼 (memory: `feedback_pr_pattern_for_master.md`).
- 새 스토리 브랜치는 master에서 분기 — `git checkout master && git pull && git checkout -b story/2.5-offline-text-queue-sync` (memory: `feedback_branch_from_master_only.md`). **이미 분기 완료** (CS 시작 전 — memory: `feedback_ds_complete_to_commit_push.md` 정합).
- DS 종료점은 commit + push (memory: `feedback_ds_complete_to_commit_push.md`). PR(draft 포함)은 CR 완료 후 한 번에 생성.
- CR 종료 직전 sprint-status/story Status를 review → done 갱신해 PR commit에 포함 (memory: `feedback_cr_done_status_in_pr_commit.md`).

### References

- [Source: epics.md:565-577] — Story 2.5 epic AC 5건 (오프라인 텍스트 큐잉 + 자동 flush + 지수 backoff 3회 + 사진 차단 + Idempotency-Key 멱등)
- [Source: prd.md:963] — FR16 오프라인 텍스트 큐잉 + 자동 sync
- [Source: prd.md:644-650] — M3 Offline Mode 정책 (텍스트 큐잉 + 7일 읽기 캐시)
- [Source: prd.md:1059] — NFR-R4 모바일 7일 캐시 (Story 2.4에서 wire 완료, 본 스토리는 큐잉 별 layer)
- [Source: prd.md:1086] — NFR-A3 폰트 스케일 200% (큐 카드/배지 정합)
- [Source: prd.md:1031] — NFR-L2 한국어 1차 (Alert 메시지 정합)
- [Source: architecture.md:132-152] — Mobile 의존성 카탈로그 (`@react-native-async-storage/async-storage` FR16 정합)
- [Source: architecture.md:281-299] — Data Architecture (`meals` 테이블 partial index 패턴 정합)
- [Source: architecture.md:386-431] — Naming Patterns (DB / API URL / JSON / 헤더 / 파일)
- [Source: architecture.md:455-505] — Format Patterns (RFC 7807 + Idempotency-Key 헤더 표준)
- [Source: architecture.md:524-531] — Idempotency-Key 카탈로그 (결제 webhook + 식단 입력)
- [Source: architecture.md:557-565] — Anti-pattern 카탈로그
- [Source: architecture.md:634-700] — Backend 폴더 구조 (`app/api/v1/meals.py`, `app/db/models/meal.py`, `app/core/exceptions.py`)
- [Source: architecture.md:800-833] — Mobile 폴더 구조 (`(tabs)/meals/index.tsx`, `(tabs)/meals/input.tsx`, `lib/offline-queue.ts`)
- [Source: architecture.md:974] — Meals FR16 → `mobile lib/offline-queue.ts` (AsyncStorage)
- [Source: 2-1-식단-텍스트-입력-crud.md] — race-free RETURNING / partial UNIQUE / `meals` ORM 패턴 / W46 deferred 등재
- [Source: 2-2-식단-사진-입력-권한-흐름.md] — `meals_images.py` 분리 라우터 / `image_key` ownership 검증 / R2 head_object HEAD-check 패턴
- [Source: 2-3-ocr-vision-추출-확인-카드.md] — `parsed_items` jsonb / OCRConfirmCard 패턴 / Vision API 흐름
- [Source: 2-4-일별-식단-기록-화면.md] — `useOnlineStatus` 훅 / `query-persistence` 패턴 / KST 강제 / typed-routes cast / NFR-A3 정합
- [Source: deferred-work.md W46 (Story 2.1)] — 앱 백그라운드/킬 mid-mutation 중복 POST — *본 스토리에서 흡수*
- [Source: deferred-work.md DF1-DF26] — 본 스토리에서 carry-over (영향 0)
- [Source: api/app/api/v1/meals.py] — Story 2.1+2.2+2.3+2.4 라우터 baseline (POST/GET/PATCH/DELETE 4 endpoint + image_key + parsed_items + KST 필터 + analysis_summary 슬롯)
- [Source: api/app/db/models/meal.py] — Story 2.1+2.2+2.3 Meal ORM (9 컬럼 + parsed_items jsonb + partial index)
- [Source: api/app/core/exceptions.py] — `MealError` base + `MealNotFoundError`/`MealQueryValidationError`/`MealImageError` 카탈로그
- [Source: api/app/main.py:140] — CORS `allow_headers` Idempotency-Key 등록 (이미 적용)
- [Source: mobile/lib/use-online-status.ts] — Story 2.4 NetInfo subscription helper (자동 flush 트리거 활용)
- [Source: mobile/lib/query-persistence.ts] — Story 2.4 AsyncStorage persister (큐 storage와 별 namespace 정합)
- [Source: mobile/features/onboarding/tutorialState.ts] — Story 1.6 module-level subscriber 패턴 정합
- [Source: mobile/features/meals/api.ts] — Story 2.1+2.2+2.3 hooks + 인터페이스 (`createMeal` + `useCreateMealMutation` 갱신 대상)
- [Source: mobile/app/(tabs)/meals/input.tsx] — Story 2.1+2.2+2.3 식단 입력 화면 baseline
- [Source: mobile/app/(tabs)/meals/index.tsx] — Story 2.4 일별 기록 화면 baseline (배지/optimistic 카드 통합 대상)
- [Source: RFC 7240 / RFC 9110] — `Idempotency-Key` 헤더 표준 + 200 idempotent retry 시맨틱
- [Source: Stripe/Toss webhook docs] — Idempotency-Key 처리 표준 패턴 (키-스코프 멱등 + body diff 무시)

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] (Amelia / Senior Software Engineer)

### Debug Log References

- 백엔드 alembic 0009 라운드트립: `cd api && uv run alembic upgrade head` → `alembic downgrade 0008_meals_parsed_items` → `alembic upgrade head` 정상 (스키마 검증: `idempotency_key` TEXT NULL + `idx_meals_user_id_idempotency_key_unique` partial UNIQUE 존재 확인).
- 백엔드 pytest: 244 케이스 통과(기존 232 + Idempotency 9 + PATCH ignore 1 + alembic schema 2), coverage 83.13% (≥ 70% 게이트 통과). race 테스트는 `asyncio.gather` 패턴 사용 — race winner는 INSERT(201), loser는 IntegrityError → SELECT replay(200), 두 응답 같은 `meal.id` + DB row 1건만.
- 백엔드 ruff/format/mypy clean.
- OpenAPI 재생성: `IN_PROCESS=1 bash scripts/gen_openapi_clients.sh` → mobile/web `api-client.ts` 모두 갱신, 200 응답 코드 + `Idempotency-Key` 헤더 + 400/409 에러 노출 확인.
- 모바일 tsc + lint clean. `AuthFetch` type 시그니처 `string` arg로 align (initial RequestInfo|URL이 `authFetch`와 호환 X).

### Completion Notes List

- **W46 closed (Story 2.5)** — `meals.idempotency_key` 컬럼 + partial UNIQUE + 200 idempotent replay + race partial UNIQUE 패턴으로 *앱 백그라운드/킬 mid-mutation 중복 POST* 차단. 회귀 차단 테스트 2건 — `test_post_meal_with_idempotency_key_duplicate_returns_200_same_row`, `test_post_meal_with_idempotency_key_race_simulated_two_inserts_same_key`. deferred-work.md 갱신 (W46 strikethrough + closed 표기).
- **D1 결정 (option A `meals` 테이블 단일 컬럼)** 채택 — Story 2.1 `idx_meals_user_id_ate_at_active` partial index 패턴 정합. `idempotency_keys` 별 테이블은 over-engineering으로 회피, Story 6.x 결제 webhook 도입 시점에 cross-cutting base 분리 검토(deferred-work DF49).
- **D2 결정 (AsyncStorage 채택)** — Story 1.6 `bn:onboarding-tutorial-seen-*` + Story 2.4 `bn-rq-cache` 정합. MMKV는 신규 native 의존성 + JSI 빌드 회귀 risk로 회피, 100건 cap에서 충분.
- **D3 결정 (`client_id` = `Idempotency-Key` 단일 UUID 두 책임)** — 큐 식별자 + 서버 멱등 키 통합. 유지보수 단순성 우선.
- **D4 재시도 정책 (지수 backoff 1s/2s/4s + jitter ±20%, 3회 후 큐 잔존)** — AWS/GCP/Stripe 표준. 4xx 영구 실패 즉시 제거, 5xx/네트워크 transient 잔존 + flush 중단(다음 항목 시도 X — backoff 의미 보존).
- **D5 사진/PATCH 오프라인 차단** — 사진은 R2/Vision 모두 *온라인 필수*(epic AC line 576), PATCH/DELETE는 *진입 차단*만(Story 8 polish 시점에 PATCH 큐잉 검토 — DF43).
- **D6 자동 flush** — `useOnlineStatus` offline → online 전이 시 `flushQueue` 자동 호출. 앱 cold start 시 `prev=undefined → current=true` 분기는 *intentional* (잔존 큐 자동 sync).
- **smoke 검증 9 시나리오** (AC11 명시) — 사용자 별도 수행 권장. 백엔드 게이트(pytest 244+ 통과 + ruff/format/mypy clean) + 모바일 게이트(tsc/lint clean) + OpenAPI 재생성 통과로 *코드 정합성 + 회귀 차단*은 baseline 충족. 비행기 모드 토글 기반 manual UAT 가능.
- **신규 deferred 후보 11건** (DF43-DF53) — PATCH 큐잉 / 사진 큐잉 / schema buster / attempts reset / 동적 cap / Sentry 마스킹 / cross-cutting base / TTL / batch parallel / progress visual / 시간 ordering. deferred-work.md 등재.

### File List

신규:
- `api/alembic/versions/0009_meals_idempotency_key.py` — `idempotency_key` TEXT NULL + partial UNIQUE 마이그레이션.
- `api/tests/test_meals_idempotency_key_schema.py` — alembic 0009 schema 회귀 (2 케이스).
- `mobile/lib/offline-queue.ts` — AsyncStorage FIFO 큐 + 100건 cap + mutex + backoff + subscribe + useOfflineQueue hook.
- `mobile/features/meals/OfflineMealCard.tsx` — 큐 항목 표시 카드(회색 + 배지 + 다시시도/폐기).

수정:
- `api/app/db/models/meal.py` — `idempotency_key` Mapped + `idx_meals_user_id_idempotency_key_unique` partial UNIQUE 등재.
- `api/app/core/exceptions.py` — `MealIdempotencyKeyInvalidError(400)` + `MealIdempotencyKeyConflictDeletedError(409)` 신규 추가.
- `api/app/api/v1/meals.py` — `_validate_idempotency_key` + `_create_meal_idempotent_or_replay` race-free helper + POST `Idempotency-Key` 헤더 처리 + 200/400/409 responses.
- `api/tests/test_meals_router.py` — Idempotency 9 신규 케이스 + PATCH 헤더 무시 1 케이스.
- `mobile/features/meals/api.ts` — `createMeal` opts.idempotencyKey 시그니처 갱신 + `useCreateMealMutation` `expo-crypto randomUUID` 자동 첨부.
- `mobile/app/(tabs)/meals/input.tsx` — 텍스트 큐잉 분기 + 사진 onPress 오프라인 차단 + PATCH 모드 진입 차단(useEffect).
- `mobile/app/(tabs)/meals/index.tsx` — `useOfflineQueue` + 동기화 대기 배지 + 자동 flush(`useOnlineStatus` 전이) + list에 큐 카드 통합 + 빈 화면 분기 갱신.
- `mobile/lib/api-client.ts` — OpenAPI 자동 재생성(200 응답 + Idempotency-Key 헤더 + 400/409 노출).
- `web/src/lib/api-client.ts` — OpenAPI 자동 재생성.
- `README.md` — *오프라인 텍스트 큐잉 + 자동 sync SOP (Story 2.5)* 1 단락 추가.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `2-5` ready-for-dev → in-progress → review.
- `_bmad-output/implementation-artifacts/deferred-work.md` — W46 closed + DF43-DF53 신규 추가.

### Change Log

| Date | Author | Note |
|------|--------|------|
| 2026-04-30 | Amelia (claude-opus-4-7[1m]) | Story 2.5 ready-for-dev — 오프라인 텍스트 큐잉(AsyncStorage FIFO + per-user namespace + mutex + 지수 backoff 1s/2s/4s 3회) + 백엔드 Idempotency-Key 헤더 처리(`meals.idempotency_key` 컬럼 + partial UNIQUE index + 200 idempotent replay + race-free SELECT-INSERT-CATCH 패턴 — W46 흡수) + `useCreateMealMutation` Idempotency-Key 자동 첨부(expo-crypto randomUUID) + `(tabs)/meals/input.tsx` 텍스트 큐잉 분기 + 사진/PATCH 오프라인 차단 + `(tabs)/meals/index.tsx` 동기화 대기 배지 + optimistic 큐 카드 + `useOnlineStatus` 자동 flush 트리거 + 4xx 영구 실패 + 100건 hard cap baseline 컨텍스트 작성. Status: backlog → ready-for-dev. |
| 2026-04-30 | Amelia (claude-opus-4-7[1m]) | Story 2.5 DS 완료 — 백엔드(alembic 0009 + Meal ORM + MealError 2종 + race-free helper + 라우터 Idempotency 흐름 + pytest 244 통과 83% coverage) + 모바일(offline-queue.ts 신규 + useCreateMealMutation 헤더 자동 첨부 + input.tsx 오프라인 분기 + 사진/PATCH 차단 + index.tsx 배지 + 큐 카드 + 자동 flush) + OpenAPI 재생성(200/400/409 노출) + README/deferred-work 갱신. W46 closed (Story 2.1 deferred 흡수). 신규 deferred 11건(DF43-DF53). Status: in-progress → review. |
| 2026-04-30 | Amelia (claude-opus-4-7[1m]) | Story 2.5 CR 완료 — 3 layer adversarial review(Blind/Edge/Auditor) + 66 raw → 43 unique. 3 decision-needed 해결(DN1 카드 액션 단일 노출 + DN2 P16 승격 DF46 closed + DN3 `summary` 유지 스펙 정정) + 16 patches 적용(P1~P16): 백엔드(P3 IntegrityError 인덱스명 한정 + P4 race [200,201] 단일 + P12 Idempotency-Key trim/empty None) / offline-queue.ts(P1 per-userId mutex + P2 R-M-W 직렬화 + P6 401abort/429transient/400-422 영구 + P8 3회 send cap + P9 UUID v4 검증 + P10 빈 userId 가드 + P13 last_error 마스킹 + P14 item shape 검증 + P15 stuck_count + P16 resetAttempts 헬퍼) / input.tsx(P5 PATCH offline ref guard + P7 ate_at +09:00 KST) / index.tsx(P11 4xx Alert raw_text 발췌 + P15 stuck Alert + P16 manual retry reset). 15 deferred 등재(DF54-DF68 + DF69 ActionSheet). 백엔드 pytest 244 + ruff/format/mypy clean + 모바일 tsc/lint clean. Status: review → done. |

### Review Findings

> **CR (2026-04-30, claude-opus-4-7[1m])** — 3 layer adversarial review (Blind Hunter / Edge Case Hunter / Acceptance Auditor). 66 raw findings → 43 unique post-dedupe. **3 decision-needed (resolved) / 16 patch / 15 defer / 10 dismissed**.

**Decision-needed (3) — resolved:**

- [x] [Review][Decision] **DN1 — AC6 ActionSheet on badge tap missing → 카드 액션 단일 노출로 스펙 정정** — AC6 line 108 mandates tap-badge → 작은 popover/ActionSheet. 현 구현은 동일 액션을 카드별 버튼(`OfflineMealCard.tsx:1804-1820`)으로 노출. **결정**: ActionSheet 신규 구현은 카드 버튼과 redundant pattern (memory `feedback_out_criteria_must_be_redundant_or_antipattern.md` 정합) — UIUX 가시 기본기능(retry/폐기/raw_text/시간)이 카드에 모두 노출되므로 영업 demo 충실도 충족. AC6 line 108은 *"카드 액션으로 대체"*로 스펙 정정 — Story 8 polish에서 ActionSheet 도입 재평가(DF69).
- [x] [Review][Decision] **DN2 — D4 manual retry attempts reset → 즉시 수정 (P16 승격)** — D4 baseline은 "manual retry 시 attempts reset 채택" 그러나 현 구현 reset 미적용 → attempts ≥ cap 항목은 manual retry no-op. **결정**: user-visible UIUX 가시 기본기능 실패(*"다시 시도"* 눌렀는데 무동작은 demo killer). P16으로 승격 — DF46는 closed 표기 후 strikethrough.
- [x] [Review][Decision] **DN3 — `OfflineMealCard accessibilityRole="summary"` vs AC6 "button" → `"summary"` 유지 (스펙 정정)** — 카드 root는 onPress 부재(non-interactive container). `"summary"`가 VoiceOver에 정확(inner Pressable만 `"button"`). AC6 line 153 *"button"* 명시는 스펙 작성 시 root vs inner 혼동으로 판단 — *"카드 root `summary`, inner 버튼 `button`"* 으로 스펙 정정.

**Patch (15):**

- [x] [Review][Patch] **P1 — `flushing` mutex per-userId Map화** [`mobile/lib/offline-queue.ts:flushQueue`] — 현 module-level `let flushing` 단일 promise. 사용자 A flush 중 B로 전환 시 B가 A의 promise/result를 받아 cross-user storage write 위험.
- [x] [Review][Patch] **P2 — AsyncStorage R-M-W 직렬화** [`mobile/lib/offline-queue.ts: _readQueue/_writeQueue 호출자`] — `enqueueMealCreate`/`_persistItemUpdate`/`_removeItemSilent`/`removeQueueItem` 동시 호출 시 last-write-wins로 enqueue 항목 유실. 단일 mutex로 직렬화 또는 atomic merge.
- [x] [Review][Patch] **P3 — `IntegrityError` catch를 partial UNIQUE index 위반에만 한정** [`api/app/api/v1/meals.py:_create_meal_idempotent_or_replay`] — FK/CHECK 위반도 잡혀 잘못된 replay SELECT 진입. `e.orig` 메시지에 `idx_meals_user_id_idempotency_key_unique` 포함 여부 확인 후 분기.
- [x] [Review][Patch] **P4 — race 테스트 assertion 강화** [`api/tests/test_meals_router.py:1394`] — 현 `[200, 201] or [200, 200]` 허용. `[200, 200]`은 INSERT 미발생 의미라 잘못된 구현(둘 다 SELECT만)도 통과. `statuses == [200, 201]` 단일 outcome + 201 row 확인.
- [x] [Review][Patch] **P5 — PATCH-mode 오프라인 useEffect ref guard** [`mobile/app/(tabs)/meals/input.tsx:1698-1713`] — `isPatchMode && !isOnline` 매 render마다 Alert + `router.back()` 호출 — Alert 스택 + back 과다 pop. `useRef<boolean>` 1회 fire guard.
- [x] [Review][Patch] **P6 — 영구 실패 4xx를 400/422로 한정** [`mobile/lib/offline-queue.ts:_flushOnce`] — 현 `400 ≤ status < 500` 전체가 영구 drop. 401(`authFetch` redirect 도달 X 가정 위반 시), 429(rate limit) 항목 영구 손실. 401: flush abort, 429: transient(잔존 + backoff), 400/422만 영구 drop.
- [x] [Review][Patch] **P7 — `ate_at` `+09:00` KST format** [`mobile/app/(tabs)/meals/input.tsx:1761`] — 현 `new Date().toISOString()`은 `Z`(UTC). AC3 line 56 + D3 line 328은 `+09:00` TZ-aware 명시. Story 2.4 D1 KST pin 패턴 정합.
- [x] [Review][Patch] **P8 — backoff 재시도 횟수 3회로 확정** [`mobile/lib/offline-queue.ts:2378`] — 현 `BACKOFF_BASE_MS.length === 4` → 4 sends. AC3 line 71 "attempts >= 3 retry 미수행" + AC11 smoke #4 "0→1→2→3 + 3회 재시도 실패". 가드를 `>= 3`으로 또는 BASE_MS 3개로 정렬.
- [x] [Review][Patch] **P9 — `client_id` UUID v4 클라이언트 검증** [`mobile/lib/offline-queue.ts:enqueueMealCreate` or `input.tsx`] — 일부 RN/expo-crypto 빌드가 비-v4 반환 시 모든 flush가 400 → 영구 drop(silent 데이터 손실). 백엔드와 동일 regex로 enqueue 전 검증.
- [x] [Review][Patch] **P10 — 빈/누락 `userId` 가드** [`mobile/lib/offline-queue.ts` enqueue/flush 진입점] — `userId === ''` 시 storage key가 `bn:offline-queue:meal:`로 rogue namespace 생성. 토큰 갱신 중 transient null 케이스. 진입점에서 throw/no-op.
- [x] [Review][Patch] **P11 — 4xx Alert에 raw_text 발췌(20자) 포함** [`mobile/app/(tabs)/meals/index.tsx:1502-1505`] — AC7 line 126 *"... 짜장면 ..."* 처음 20자 명시. 현 Alert 텍스트만, 어떤 항목이 거부됐는지 미식별. `FlushResult.failed_permanent_excerpts: string[]` 필드 추가 → Alert에 첫 항목 발췌 노출.
- [x] [Review][Patch] **P12 — 빈/공백 `Idempotency-Key` 헤더 처리** [`api/app/api/v1/meals.py:_validate_idempotency_key`] — 현 `None` 체크만 — 빈 문자열/공백 패딩은 regex 위반으로 400. `key = key.strip(); if not key: return None`로 *"미송신과 동등"* 처리.
- [x] [Review][Patch] **P13 — `last_error` 영속 시 raw_text 마스킹** [`mobile/lib/offline-queue.ts:_extractErrorMessage` + `_persistItemUpdate`] — Pydantic ValidationError detail에 raw_text 조각 echo 가능. NFR-S5 raw_text 마스킹 위반 — 영속/UI 노출 전 길이 cap + 위험 substring 마스킹.
- [x] [Review][Patch] **P14 — JSON parse 후 item shape 검증** [`mobile/lib/offline-queue.ts:_readQueue`] — 현 `JSON.parse` 실패만 silent reset. parse 성공이지만 item에 `client_id`/`raw_text` 누락 시 POST가 `undefined` 송신 → 400 → 영구 drop. parse 후 schema 가드 추가.
- [x] [Review][Patch] **P15 — stuck 항목(attempts ≥ cap) UI 신호** [`mobile/lib/offline-queue.ts:FlushResult` + `index.tsx`] — 현 4xx만 사용자 안내, attempts cap 도달은 silent jam. `stuck_count` 필드 + manual retry 안내 Alert.
- [x] [Review][Patch] **P16 — manual retry 시 `attempts` reset (D4 literal, DN2 결정)** [`mobile/lib/offline-queue.ts:resetAttempts(userId, client_id)` 신규 + `index.tsx:triggerFlush`] — D4 baseline mandate. attempts ≥ cap 항목이 manual retry로 재시도 가능하도록 reset 헬퍼 신규 + `triggerFlush`에서 모든 큐 항목 attempts=0으로 reset 후 `flushQueue` 호출. DF46 closed.

**Defer (15) — `deferred-work.md`에 DF54-DF68로 등재:**

- [x] [Review][Defer] DF54 — `_flushOnce` iteration cap (defensive)
- [x] [Review][Defer] DF55 — race-fallback `MealIdempotencyKeyRaceResolutionError` 신규 (현 `BalanceNoteError` 일반 500)
- [x] [Review][Defer] DF56 — `triggerFlush` UI 상태를 module mutex와 동기화
- [x] [Review][Defer] DF57 — 큐 배지 `accessibilityLiveRegion="polite"` 재공지 노이즈
- [x] [Review][Defer] DF58 — `expo-crypto.randomUUID()` 예외 fallback
- [x] [Review][Defer] DF59 — 컴포넌트 unmount 시 in-flight flush AbortController
- [x] [Review][Defer] DF60 — `isInternetReachable` vs `isOnline` 분기 강화
- [x] [Review][Defer] DF61 — `subscribeQueue` 알림 → `getQueueSnapshot` async 폭주 coalesce
- [x] [Review][Defer] DF62 — `enqueued_at` 미래 timestamp 음수 diff 가드
- [x] [Review][Defer] DF63 — flush 도중 unmount → `setIsFlushing` mounted ref guard
- [x] [Review][Defer] DF64 — `_create_meal_idempotent_or_replay` `values: dict` 타입 강화
- [x] [Review][Defer] DF65 — `AsyncStorage.setItem` quota 에러 명시 사용자 안내
- [x] [Review][Defer] DF66 — 다중 `Idempotency-Key` 헤더 처리(프록시 coalescing 가드)
- [x] [Review][Defer] DF67 — `db.rollback()` 후 `db.commit()` 향후 pre-INSERT write 추가 시 의도 단언
- [x] [Review][Defer] DF68 — `OfflineQueueItem.attempts` JSDoc 의미(0-based vs post-send count) 정렬

**Dismissed (10):** sprint-status 중간 상태 skip(현 review 정합 — 전이 ephemeral) / queueSize 0→N 자동 flush gap(enqueue는 오프라인만 — 발생 X) / `randomUUID` dual import(같은 라이브러리·소스) / 1xx·3xx 응답(REST contract 외) / response body 재소비(`_extractErrorMessage` 1회 호출) / `flushQueue` 동기 throw(코드 경로 부재) / `values` dict 로깅 leak(logger가 dict 미참조) / alembic downgrade populated row 손실(AC1 명시 결정) / `ocrConfirmed=true` + `parsedItems=[]` 빈 array 차단(`ocrConfirmed` 게이트가 length-independent) / `attempts` 0-based code/doc 중복(P15+DF68 흡수).
