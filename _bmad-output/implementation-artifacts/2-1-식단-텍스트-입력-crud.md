# Story 2.1: 식단 텍스트 입력 + CRUD

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **엔드유저**,
I want **모바일에서 식단을 텍스트로 입력하고 조회·수정·삭제하기를**,
So that **사진을 찍지 않아도 빠르게 한 끼를 기록할 수 있다.**

본 스토리는 Epic 2(식단 입력 + 일별 기록 + 권한 흐름)의 첫 스토리로, **단일 출처 `meals` 테이블** + **`/v1/meals/*` REST CRUD 4종 endpoint** + **모바일 `(tabs)/meals/{index, input}` 화면**의 baseline을 박는다. 

부수적으로 (a) `meals` ORM/마이그레이션(`0006_meals.py`)으로 Epic 2의 단일 데이터 모델을 확정 — `image_key`(Story 2.2), `meal_analyses`(Epic 3) 같은 후속 컬럼/테이블은 본 스토리에서 추가하지 않는다(YAGNI), (b) `(tabs)/_layout.tsx`에 `meals` 탭을 등록하고 `(tabs)/index.tsx`를 `/(tabs)/meals` redirect로 전환해 *기본 진입 화면*을 식단 화면으로 박는다, (c) Story 1.5에서 처음 wire된 `Depends(require_basic_consents)`를 *작성 경로*(POST/PATCH/DELETE)에만 적용 + *조회 경로*(GET)는 인증만(`deps.py:140-151` PIPA Art.35 정합), (d) `Idempotency-Key` 헤더는 CORS에 이미 허용되어 있으나 *처리는 Story 2.5*에서 — 본 스토리는 헤더 수신만 허용. (e) `[meal_id].tsx` 채팅 SSE 라우트는 Story 3.7 책임 — 본 스토리에서 도입 X. 본 스토리 종료 시점에 Epic 2 첫 스토리(2.1) 완료 → 후속 5개 스토리(2.2 사진/2.3 OCR/2.4 일별 기록/2.5 오프라인 큐잉)에 baseline 데이터 모델·API·화면이 제공된다.

## Acceptance Criteria

> **BDD 형식 — 각 AC는 독립적 검증 가능. 모든 AC 통과 후 `Status: review`로 전환하고 code-review 워크플로우로 진입.**

1. **AC1 — `meals` 테이블 + Alembic 0006 마이그레이션**
   **Given** Story 2.1, **When** `alembic upgrade head` 실행, **Then** `meals` 테이블이 다음 7컬럼으로 생성된다:
     - `id` UUID PRIMARY KEY DEFAULT `gen_random_uuid()` (Story 1.2 baseline 패턴 정합)
     - `user_id` UUID NOT NULL REFERENCES `users(id)` ON DELETE CASCADE
     - `raw_text` TEXT NOT NULL (텍스트 식단 본문 — *Story 2.2 사진 입력 도입 후에도 NOT NULL 유지* — 사진은 별도 `image_key` 컬럼으로 0007 마이그레이션에서 추가 + 텍스트 부재 시 placeholder 또는 OCR 결과 입력)
     - `ate_at` TIMESTAMPTZ NOT NULL DEFAULT `now()` (식사 시점 — 미명시 시 입력 시점으로 fallback. Story 2.4 시간순 정렬 입력)
     - `created_at` TIMESTAMPTZ NOT NULL DEFAULT `now()`
     - `updated_at` TIMESTAMPTZ NOT NULL DEFAULT `now()` ON UPDATE `now()` (SQLAlchemy `onupdate=text("now()")` 패턴 — `users` 모델 정합)
     - `deleted_at` TIMESTAMPTZ NULL (soft delete — `meals.deleted_at IS NOT NULL`이면 read query에서 제외)
   - **Constraints / Index 1건**:
     - `idx_meals_user_id_ate_at_active` partial index — `(user_id, ate_at DESC) WHERE deleted_at IS NULL` (architecture line 395 `idx_meals_user_id_ate_at` 패턴 + Story 2.4 daily list 쿼리 입력)
     - 추가 CHECK 제약 X — `raw_text` 길이/공백 검증은 Pydantic `Field(min_length=1, max_length=2000)` 1차 게이트로 충분(double-gate DB CHECK는 Story 8 hardening)
   - **Migration 파일**: `api/alembic/versions/0006_meals.py` — `down_revision = "0005_users_health_profile"`. `upgrade()`는 `op.create_table` + `op.create_index` 표준 alembic API 사용. `downgrade()`는 `op.drop_index` + `op.drop_table` (역순). `op.execute` raw SQL 회피 — 0005 패턴 정합.
   - **ORM 모델**: `api/app/db/models/meal.py` 신규 — `Meal(Base)` 클래스, `__tablename__ = "meals"`, 7 `mapped_column` 정의. 본 모델 `__init__.py`에 `from app.db.models.meal import Meal` import + `__all__`에 `"Meal"` 추가(declarative 등록 + autogenerate 인식).
   - **autogenerate diff**: `alembic revision --autogenerate` 실행 시 추가 diff 0건(0006이 이미 ORM과 sync된 상태).

2. **AC2 — `POST /v1/meals` 식단 생성 (require_basic_consents)**
   **Given** 4종 기본 동의 통과 사용자, **When** 인증 헤더 + `{"raw_text": "삼겹살 1인분, 김치찌개, 소주 2잔"}` body로 `POST /v1/meals` 호출, **Then**:
     - HTTP 201 + 응답 body `MealResponse` (7 필드: `id`, `user_id`, `raw_text`, `ate_at`, `created_at`, `updated_at`, `deleted_at`)
     - DB `meals` row 1건 INSERT — `raw_text` body 그대로, `user_id = current_user.id`, `ate_at` body 미지정 시 `now()` fallback, `deleted_at IS NULL`
     - `Idempotency-Key` 요청 헤더 — **수신은 허용**(CORS 이미 등록, `main.py:138`) **처리는 Story 2.5**(중복 차단 X — 같은 key 재발사 시 새 row 생성). 본 스토리에서 헤더 검증/저장 코드 도입 X.
     - **요청 body 스키마** (`MealCreateRequest` Pydantic 모델, `model_config=ConfigDict(extra="forbid")`):
       - `raw_text: str = Field(min_length=1, max_length=2000)` — 빈 문자열·whitespace-only 거부 (`@field_validator`로 `value.strip()` 후 길이 재검증), 2000자 상한(NFR baseline)
       - `ate_at: datetime | None = None` — 미지정 시 DB-side `now()` fallback. *미래 시점*(`ate_at > now() + 1 hour` 등) 거부는 도메인 룰 — 본 스토리는 *허용*(엔드유저가 *기록 catch-up* 시 입력 + 시계 skew 허용 5분 미만 — 명시 차단은 yagni). *과거 시점*은 자유 입력 허용(catch-up 시나리오).
     - **응답 body** (`MealResponse` Pydantic 모델):
       - `id: uuid.UUID`, `user_id: uuid.UUID`, `raw_text: str`, `ate_at: datetime`, `created_at: datetime`, `updated_at: datetime`, `deleted_at: datetime | None`
       - architecture line 481 룰 정합 — `deleted_at`이 NULL인 응답에서 키 *유지*(`null` JSON value, 키 누락 X — 스키마 안정성).
     - **인증·동의 가드**:
       - 401: 무인증 → `auth.access_token.invalid` (deps.py 패턴 정합)
       - 403: 동의 미통과 → `consent.basic.missing` (Story 1.5 W14 wire 정합)
     - **HTTP status 결정 — 201 채택**: REST 표준 + Story 1.5 `POST /me/profile` 200(*update*) 와 다른 의미(*create*). 모든 메소드가 동일 status 라는 anti-pattern(line 559) 회피. 응답 body는 새 리소스(line 481).
     - **로깅**: `log.info("meals.created", user_id=..., meal_id=..., raw_text_len=len(raw_text), ate_at_iso=...)` — `raw_text` *내용*은 로그에 raw 출력 X(architecture line 309 NFR-S5 마스킹 대상 명시 정합 — *식단 raw_text*).

3. **AC3 — `GET /v1/meals` 자기 식단 목록 조회 (인증만)**
   **Given** 인증 사용자, **When** `GET /v1/meals?from_date=2026-04-29&to_date=2026-04-29` 호출, **Then**:
     - HTTP 200 + 응답 body `MealListResponse = {meals: list[MealResponse], next_cursor: null}` 
     - 응답 list — `current_user.id`의 `meals` row 중 `deleted_at IS NULL` + 쿼리 필터 적용된 결과 — `ate_at DESC` 정렬(idx_meals_user_id_ate_at_active partial index hit)
     - **다른 사용자 식단 노출 X** — `WHERE user_id = current_user.id` 강제 (정합 회귀 차단 테스트 명시 작성)
     - **soft-deleted 제외** — `WHERE deleted_at IS NULL` 강제 (회귀 차단 테스트 명시)
     - **쿼리 파라미터** (`MealListQuery` Pydantic 모델 또는 FastAPI `Query()` 직접):
       - `from_date: date | None = None` — UTC date(YYYY-MM-DD). 미지정 시 lower bound 무제한
       - `to_date: date | None = None` — UTC date(YYYY-MM-DD). 미지정 시 upper bound 무제한. 적용 시 `ate_at < to_date + 1 day`(inclusive)
       - `limit: int = Field(default=50, ge=1, le=200)` — 페이지 크기. 기본 50.
       - `cursor: str | None = None` — *수신만* — 본 스토리에서 처리 X(Story 2.4가 cursor pagination 흡수). cursor 미지원 baseline 명시: `next_cursor`는 항상 `null` 응답.
     - 인증 가드: 401 only — *조회 경로는 동의 게이트 wire X* (`deps.py:140-151` 주석 정합 — PIPA Art.35 정보주체 권리 + 자기 데이터 조회는 동의 무관).
     - 빈 결과 → HTTP 200 + `{"meals": [], "next_cursor": null}` (404 미사용).
     - **응답 캐시**: 본 스토리는 cache 헤더 미설정(Story 8 polish — 1.3 W2 패턴 정합).

4. **AC4 — `PATCH /v1/meals/{meal_id}` 식단 수정 (require_basic_consents)**
   **Given** 4종 기본 동의 통과 사용자 + 자기 소유 식단, **When** `PATCH /v1/meals/{meal_id}` body `{"raw_text": "수정된 텍스트"}` 호출, **Then**:
     - HTTP 200 + 응답 body `MealResponse` (갱신 후 7 필드)
     - DB 업데이트: `raw_text` 갱신 + `updated_at = func.now()` 갱신 (단일 UPDATE statement, RETURNING 패턴 — Story 1.5 race-free 정합)
     - **요청 body 스키마** (`MealUpdateRequest` Pydantic, `extra="forbid"`):
       - `raw_text: str | None = Field(default=None, min_length=1, max_length=2000)` — 미지정 시 미변경. 빈 문자열 거부 동일.
       - `ate_at: datetime | None = None` — 미지정 시 미변경.
       - **빈 body / 모든 필드 None → 400** (`code=validation.error`, *최소 1 필드 필수* — `@model_validator` 또는 라우터 in-line 검증). update 대상 0이면 무의미한 DB call 회피.
     - **소유권 / 존재 검증 — 단일 SQL with RETURNING**:
       - `update(Meal).where(Meal.id == meal_id, Meal.user_id == user.id, Meal.deleted_at.is_(None)).values(...).returning(Meal)`
       - `result.scalar_one_or_none()` 결과가 None이면 → 404 + `code=meals.not_found` (소유권 미일치 / 존재 X / soft-deleted 모두 동일 응답 — *enumeration 차단*. 403/404 분기 X)
     - **에러 카탈로그 신규 1건**: `MealNotFoundError(BalanceNoteError)` — `status=404`, `code=meals.not_found`, `title="Meal not found"` — `app/core/exceptions.py`에 추가(Story 1.3·1.4 동의 예외 패턴 정합).
     - 동의 미통과 → 403 + `consent.basic.missing` 동일.
     - 인증 X → 401 동일.
     - 로깅: `log.info("meals.updated", user_id=..., meal_id=..., changed_fields=[...])` — *내용 raw 출력 X*.

5. **AC5 — `DELETE /v1/meals/{meal_id}` 식단 soft delete (require_basic_consents)**
   **Given** 4종 기본 동의 통과 사용자 + 자기 소유 식단, **When** `DELETE /v1/meals/{meal_id}` 호출, **Then**:
     - HTTP 204 No Content + 응답 body 없음
     - DB 업데이트: `deleted_at = func.now()` 단일 UPDATE statement
     - **소유권 / 존재 / *이미 deleted* 검증 — 단일 SQL with RETURNING**:
       - `update(Meal).where(Meal.id == meal_id, Meal.user_id == user.id, Meal.deleted_at.is_(None)).values(deleted_at=func.now()).returning(Meal.id)`
       - `result.scalar_one_or_none()`이 None → 404 + `meals.not_found` (이미 삭제된 식단도 404 — 멱등 *조회* 결과 일관성 + enumeration 차단)
     - **물리 삭제 X** — soft delete만. 30일 grace 후 물리 파기는 Story 5.2 책임(architecture line 297 정합 — *FR5 + C6 데이터 보존 정책*).
     - 동의 미통과 → 403 동일. 인증 X → 401 동일.
     - 로깅: `log.info("meals.deleted", user_id=..., meal_id=...)` — soft delete 흔적.

6. **AC6 — Mobile `(tabs)/_layout.tsx` 갱신 + meals 탭 + 기본 진입 redirect**
   **Given** Story 1.6의 4 가드 통과 사용자, **When** `(tabs)` 그룹 진입, **Then**:
     - `(tabs)/_layout.tsx`의 `<Tabs />`에 명시적 `<Tabs.Screen name="meals" options={{ title: '식단', ... }} />` + `<Tabs.Screen name="settings" options={{ title: '설정', ... }} />` 2개 등록(architecture line 803-808 정합). `<Tabs.Screen name="index" options={{ href: null }} />` 추가 — `(tabs)/index.tsx` 라우트는 *redirect 전용*이므로 탭 바에 노출 X (`href: null` Expo Router 표준 hide 패턴).
     - `(tabs)/index.tsx` 갱신 — 기존 placeholder 화면을 `<Redirect href="/(tabs)/meals" />`로 교체. typedRoutes cast(`as Parameters<typeof Redirect>[0]['href']`) Story 1.5/1.6 패턴 정합.
     - **결정 — `(tabs)/index.tsx` 삭제 vs redirect**:
       - 삭제: Expo Router는 `(tabs)/index.tsx` 부재 시 첫 child 라우트로 라우팅하나 alphabetical 순서가 OS·버전마다 미세 차이. deeplink `/(tabs)`가 *깨질* 위험.
       - **채택**: redirect로 유지 — deeplink 안전 + 탭 바 hide(`href: null`)로 UX 일관 + 향후 *welcome 화면*으로 확장 시 라우트 재사용 가능.
     - 4 가드(Story 1.6 정합) 그대로 유지 — *5번째 가드 추가 X*. 식단 입력 가드는 도메인 룰 미존재(첫 식단 입력은 사용자 자유).

7. **AC7 — Mobile `(tabs)/meals/index.tsx` 일별 기록 baseline 화면**
   **Given** Story 2.1, **When** 사용자가 meals 탭 진입, **Then**:
     - 화면 상단 *"오늘 식단"* 헤더 + *식단 입력* CTA 버튼(우상단 또는 헤더 우측 — `+` 아이콘) — 탭 시 `router.push('/(tabs)/meals/input')` (typedRoutes cast)
     - 카드 리스트 — `useMealsQuery({ from_date: today, to_date: today })` TanStack Query hook으로 fetch — `MealCard` 컴포넌트가 `raw_text` + `ate_at`(HH:mm 한국 시간 변환은 클라이언트 책임 — architecture line 478 정합) 표시
     - 카드 long-press → ActionSheet (`react-native` `ActionSheetIOS` iOS / `Alert.alert` Android fallback — *외부 라이브러리 X*) — 액션 *수정* / *삭제* / *취소*
       - *수정* → `router.push('/(tabs)/meals/input?meal_id=' + id)` (입력 화면이 PATCH 모드로 분기)
       - *삭제* → 확인 dialog(`Alert.alert`) → 사용자 OK 시 `useDeleteMealMutation` 호출 → 성공 후 list invalidate
     - **빈 결과 시** *"오늘 기록 없음 — 첫 식단을 입력하세요"* 표준 빈 화면 + CTA `식단 입력` 버튼 (Story 1.5 빈 화면 패턴 정합).
     - **로딩 시** `<ActivityIndicator />` (Story 1.5/1.6 정합).
     - **에러 시** *"오류 — 다시 시도"* 메시지 + 재시도 버튼(`refetch()` 호출). architecture line 521 표준 에러 화면 정합.
     - **본 스토리 baseline 한정 — *Story 2.4가 본 화면을 폴리싱*** — 매크로/fit_score/시간순 정렬·날짜 picker는 Story 2.4 책임. 본 스토리는 raw_text + ate_at + ActionSheet 흐름이 작동하는 최소 baseline.
     - 폰트 스케일 200%(NFR-A3) — `flexShrink: 1` + 카드 텍스트 wrap (Story 1.5/1.6 패턴).
     - `accessibilityRole`/`accessibilityLabel` — 카드 *"식단 카드: <raw_text 첫 30자>"* / 입력 버튼 *"식단 입력"* / 빈 화면 안내 텍스트.

8. **AC8 — Mobile `(tabs)/meals/input.tsx` 텍스트 입력/수정 폼 (POST + PATCH 통합)**
   **Given** Story 2.1, **When** 사용자가 *식단 입력* 또는 *식단 수정* 진입, **Then**:
     - `?meal_id=` 쿼리 파라미터로 분기:
       - 미존재 → POST 모드 (신규 작성). 헤더 *"식단 입력"*.
       - 존재 → PATCH 모드. 진입 시 `useMealQuery(meal_id)` 또는 `(tabs)/meals/index`의 캐시에서 prefill (`queryClient.getQueryData([...])` 패턴 — 추가 fetch 회피). 헤더 *"식단 수정"*.
       - **단일 GET endpoint `/v1/meals/{meal_id}` 필요 X** — 본 스토리는 list 캐시 prefill로 충분. *Story 3.7 채팅 화면이 단건 GET을 요구*하면 그 시점에 도입(yagni).
     - **폼 — `react-hook-form` + `zod`** (Story 1.5 패턴 정합):
       - `mobile/features/meals/mealSchema.ts` 신규 — `mealCreateSchema = z.object({ raw_text: z.string().trim().min(1, "식단 내용을 입력해주세요").max(2000, "2000자 이하 입력") })`. `ate_at`은 본 스토리 baseline에서 *입력 X*(서버 default `now()` 위임 — UI polish는 Story 2.4 시간 picker 도입 시점).
       - `MealInputForm.tsx` — `Controller` + `<TextInput multiline numberOfLines={6} />` + 제출 버튼. submit 중 `isSubmitting` 디스에이블.
     - **TanStack Query mutations** (`mobile/features/meals/api.ts` 신규):
       - `useCreateMealMutation` — `POST /v1/meals` (`authFetch` 사용). 성공 후 `queryClient.invalidateQueries({ queryKey: ['meals'] })` + `router.replace('/(tabs)/meals')`.
       - `useUpdateMealMutation` — `PATCH /v1/meals/{meal_id}`. 성공 후 동일 invalidate + replace.
       - `useDeleteMealMutation` — `DELETE /v1/meals/{meal_id}`. 성공 후 동일 invalidate + replace(`(tabs)/meals/index`로 회귀 — list에서 호출되었으므로 navigation pop으로 충분 시 `router.back()` 가능).
     - 에러 처리 — `extractSubmitErrorMessage` (Story 1.5 패턴 재사용 또는 인라인 — 401/403/400 분기):
       - 401: refresh 후 재시도 (authFetch 인터셉터)
       - 403 `consent.basic.missing` → `Alert.alert("동의가 필요합니다 — 온보딩으로 이동")` + `router.replace('/(auth)/onboarding/disclaimer')` (Story 1.5 W8 deferred 정합 — 본 스토리 inline 1회 처리)
       - 400 → 폼 필드 에러 표시 (`setError("raw_text", { message })`)
       - 5xx 또는 네트워크 → 표준 에러 메시지 토스트 또는 Alert
     - **인증·route guard**: `(tabs)` 그룹 가드 4단계가 이미 통과된 상태(이 화면 진입 자체가 가드 하위) — 별도 가드 X.
     - 폰트 스케일 200% / `accessibilityLabel` — 입력 필드 *"식단 텍스트 입력"*, 제출 버튼 *"저장"* / *"수정 저장"*.

9. **AC9 — 백엔드 라우터 wire + main.py 등록 + OpenAPI 자동 재생성**
   **Given** Story 2.1, **When** `app/main.py` 라우터 등록, **Then**:
     - `app.include_router(meals_router.router, prefix="/v1/meals", tags=["meals"])` 1줄 추가 (auth/users/consents/legal 4 라우터 다음). `from app.api.v1 import meals as meals_router` import 추가.
     - **OpenAPI 클라이언트 자동 재생성** — `IN_PROCESS=1 bash scripts/gen_openapi_clients.sh` 실행 → `mobile/lib/api-client.ts` + `web/src/lib/api-client.ts` 갱신 — `MealCreateRequest`/`MealUpdateRequest`/`MealResponse`/`MealListResponse` 타입 노출 + `/v1/meals` path 4 메소드 등록 확인(`grep "v1/meals"`). PR push 시 `openapi-diff` GitHub Actions 잡 통과(diff 0).
     - **Web에는 UI 변경 X** — 클라이언트 타입만 갱신(향후 admin 검색 Story 7.x 또는 데이터 export Story 5.3에서 활용).

10. **AC10 — 백엔드 테스트 (`tests/test_meals_router.py` 신규) + smoke 검증**
    - 백엔드 테스트 — pytest 신규 파일 `api/tests/test_meals_router.py`. 14+ 케이스 커버 (Story 1.5 21 케이스 패턴 정합, fixture 재활용 — `user_factory`, `consent_factory`, `auth_headers`):

      **POST /v1/meals (AC2):**
      - `test_post_meal_creates_returns_201` — 정상 입력 → 201 + `MealResponse` 7 필드 + DB row 검증
      - `test_post_meal_with_explicit_ate_at_returns_201` — `ate_at` 명시 입력 → 200 + 응답 `ate_at == 입력값`
      - `test_post_meal_blocks_user_without_basic_consents_returns_403` — 동의 미통과 → 403 + `code=consent.basic.missing`
      - `test_post_meal_unauthenticated_returns_401` — 헤더 없음 → 401 + `code=auth.access_token.invalid`
      - `test_post_meal_empty_raw_text_returns_400` — `raw_text=""` 또는 `"  "` (whitespace-only) → 400 + `code=validation.error`
      - `test_post_meal_too_long_raw_text_returns_400` — 2001자 → 400 (max_length 게이트)

      **GET /v1/meals (AC3):**
      - `test_get_meals_returns_user_only` — user A의 식단만 응답, user B 식단 노출 X (`user_factory()` 2명 + 각각 POST 후 user A로 GET)
      - `test_get_meals_excludes_soft_deleted` — DELETE 후 GET 결과에서 제외
      - `test_get_meals_filter_by_date_range` — `from_date`/`to_date` 필터 정상 분기
      - `test_get_meals_unauthenticated_returns_401` — 헤더 없음 → 401
      - `test_get_meals_no_consent_required` — 동의 미통과 사용자도 200(자기 데이터 조회는 동의 무관 — `deps.py:140-151` PIPA Art.35 정합 회귀 차단)
      - `test_get_meals_empty_returns_200_with_empty_list` — 식단 없는 사용자 → 200 + `meals=[]`

      **PATCH /v1/meals/{meal_id} (AC4):**
      - `test_patch_meal_updates_raw_text_returns_200` — 정상 수정 → 200 + 갱신값 반영 + `updated_at` 갱신
      - `test_patch_meal_other_user_returns_404` — user A의 meal_id를 user B가 PATCH → 404 + `code=meals.not_found` (403 X — enumeration 차단)
      - `test_patch_meal_soft_deleted_returns_404` — soft-deleted meal PATCH → 404
      - `test_patch_meal_nonexistent_id_returns_404` — 가짜 UUID → 404
      - `test_patch_meal_empty_body_returns_400` — `{}` → 400 + *최소 1 필드 필수* 메시지
      - `test_patch_meal_blocks_user_without_basic_consents_returns_403` — 동의 미통과 → 403

      **DELETE /v1/meals/{meal_id} (AC5):**
      - `test_delete_meal_soft_deletes_returns_204` — 정상 삭제 → 204 + `deleted_at IS NOT NULL` + 후속 GET에서 제외
      - `test_delete_meal_already_deleted_returns_404` — 이미 deleted_at set인 meal DELETE → 404
      - `test_delete_meal_other_user_returns_404` — user B가 user A meal DELETE → 404
      - `test_delete_meal_blocks_user_without_basic_consents_returns_403` — 동의 미통과 → 403
      
    - **모바일 TS 단위 테스트 OUT** — Story 1.4·1.5·1.6 정합. `pnpm tsc --noEmit` + `pnpm lint` clean 게이트.
    - **conftest 갱신**: 본 스토리는 `meal_factory` fixture 도입 X — 테스트 내에서 `client.post("/v1/meals", ...)` 호출 또는 `session_maker`로 직접 INSERT 어느 쪽이든 case-by-case. 1.5 패턴 정합(반복 헬퍼는 Story 2.4+ 도입 검토).
    - **TRUNCATE 갱신**: `tests/conftest.py:_truncate_user_tables` 의 TRUNCATE 문에 `meals` 추가 → `TRUNCATE meals, consents, refresh_tokens, users RESTART IDENTITY CASCADE`. order는 dependent 먼저(meals → consents → refresh_tokens → users).
    - smoke 통합 검증(local):
      1. 신규 사용자 — 온보딩 통과 → `/(tabs)/meals` 진입 → *식단 입력* 탭 → "삼겹살 1인분, 김치찌개" 입력 → 저장 → list에 즉시 표시
      2. 카드 long-press → 수정 ActionSheet → 수정 화면에서 텍스트 갱신 → 저장 → list 카드 갱신
      3. 카드 long-press → 삭제 ActionSheet → 확인 → list에서 카드 제거
      4. 동의 미통과 사용자 (Story 1.3·1.4 가드 우회한 직접 API 호출) → 403 응답
    - coverage gate: `--cov=app --cov-fail-under=70` 유지. 본 스토리 백엔드 신규 코드는 약 200줄(라우터 + 모델 + 마이그레이션 + 테스트) — 신규 라우터 22+ 케이스로 충분 cover.

11. **AC11 — `app/api/deps.py` 변경 X + 에러 카탈로그 1건 추가**
    - `app/api/deps.py` — **변경 X** — `current_user`, `require_basic_consents` 그대로 재사용. Story 1.5에서 wire된 `require_basic_consents`가 본 스토리 *작성 경로* 3종(POST/PATCH/DELETE)에서 두 번째 사용처가 됨. *조회 경로*(GET)는 `current_user`만 wire (PIPA Art.35 정합).
    - `app/core/exceptions.py` — `MealNotFoundError(BalanceNoteError)` 1건 추가:
      ```python
      class MealError(BalanceNoteError):
          status: ClassVar[int] = 500
          code: ClassVar[str] = "meals.error"
          title: ClassVar[str] = "Meal Error"

      class MealNotFoundError(MealError):
          status: ClassVar[int] = 404
          code: ClassVar[str] = "meals.not_found"
          title: ClassVar[str] = "Meal not found"
      ```
    - 도메인 예외 base(`MealError`) 도입 사유: Epic 2 후속 스토리(2.2 R2 업로드 실패, 2.3 OCR 장애, 2.5 큐잉 실패)에서 같은 base 하위로 코드 카탈로그 확장 가능 — Story 1.3·1.4 `ConsentError`/`AuthError` 패턴 정합.
    - 글로벌 핸들러 변경 X — `BalanceNoteError` 핸들러(`main.py:177`)가 `MealNotFoundError`를 자동으로 RFC 7807 404로 변환.

## Tasks / Subtasks

> 순서는 의존성 위주. 각 task는 AC 번호 매핑 명시. 본 스토리는 **단일 PR 권장** (Story 1.3·1.4·1.5·1.6 정합).

### Task 1 — DB 모델 + Alembic 마이그레이션 0006 (AC: #1)

- [x] 1.1 `api/app/db/models/meal.py` 신규 — `Meal(Base)` 클래스, 7 `mapped_column`(id/user_id/raw_text/ate_at/created_at/updated_at/deleted_at). `__table_args__`에 `Index("idx_meals_user_id_ate_at_active", "user_id", text("ate_at DESC"), postgresql_where=text("deleted_at IS NULL"))`. ON DELETE CASCADE는 `ForeignKey("users.id", ondelete="CASCADE")`.
- [x] 1.2 `api/app/db/models/__init__.py` — `from app.db.models.meal import Meal` import + `__all__`에 `"Meal"` 추가(declarative 등록).
- [x] 1.3 `api/alembic/versions/0006_meals.py` 신규 — `down_revision = "0005_users_health_profile"`, `branch_labels = None`, `depends_on = None`. `upgrade()`는 `op.create_table("meals", ...)` + `op.create_index(...)`. `downgrade()`는 `op.drop_index(...)` + `op.drop_table("meals")` (역순).
- [x] 1.4 마이그레이션 검증 — `cd api && uv run alembic upgrade head` 통과 + `uv run alembic revision --autogenerate -m "verify_meals_sync"` 실행 시 *추가 diff 0건* 확인(diff 발생 시 0006 패치 후 verify revision 삭제). 검증 후 임시 revision 파일 삭제.
- [x] 1.5 `ruff check . && ruff format --check . && mypy app` clean. 마이그레이션 파일은 `from __future__ import annotations` + `from collections.abc import Sequence` 패턴(0005 정합).

### Task 2 — 라우터 + Pydantic 스키마 + 도메인 예외 (AC: #2, #3, #4, #5, #11)

- [x] 2.1 `api/app/core/exceptions.py` — `MealError(BalanceNoteError)` + `MealNotFoundError(MealError)` 2 클래스 추가 (consents 계층 다음 위치). `status=404 / code=meals.not_found / title="Meal not found"`.
- [x] 2.2 `api/app/api/v1/meals.py` 신규 — `router = APIRouter()`. 4 endpoint:
  - `POST /` — `MealCreateRequest` body, `require_basic_consents` Depends, INSERT `meals` row, RETURNING으로 race-free 응답, status_code=201
  - `GET /` — `from_date`/`to_date`/`limit`/`cursor` Query, `current_user` Depends(동의 게이트 X), SELECT user 자기 + `deleted_at IS NULL` + 날짜 필터 + `ORDER BY ate_at DESC LIMIT N`
  - `PATCH /{meal_id}` — `MealUpdateRequest` body(model_validator: 최소 1 필드 필수), `require_basic_consents`, `update().where(id, user_id, deleted_at IS NULL).values(...).returning(Meal)` race-free. 결과 None → `raise MealNotFoundError(...)`. `updated_at = func.now()` 명시.
  - `DELETE /{meal_id}` — body 없음, `require_basic_consents`, `update().values(deleted_at=func.now()).where(id, user_id, deleted_at IS NULL).returning(Meal.id)`. 결과 None → 404. response status_code=204 + `Response(status_code=204)`.
- [x] 2.3 Pydantic 모델 정의 (`api/app/api/v1/meals.py` 상단):
  - `MealCreateRequest(BaseModel)` — `extra="forbid"`, `raw_text: str = Field(min_length=1, max_length=2000)`, `ate_at: datetime | None = None`. `@field_validator("raw_text") _validate_not_whitespace` — `value.strip() == ""` 시 ValueError.
  - `MealUpdateRequest(BaseModel)` — `extra="forbid"`, `raw_text: str | None = None`, `ate_at: datetime | None = None`. `@model_validator(mode="after") _at_least_one_field` — 모든 필드 None 시 ValueError("at least one of raw_text, ate_at required").
  - `MealResponse(BaseModel)` — 7 필드(id, user_id, raw_text, ate_at, created_at, updated_at, deleted_at).
  - `MealListResponse(BaseModel)` — `meals: list[MealResponse]`, `next_cursor: str | None = None`.
- [x] 2.4 `_meal_to_response(meal: Meal) -> MealResponse` helper — Story 1.5 `_build_profile_response` 패턴 정합. ORM 필드 → 응답 필드 매핑 단일 지점.
- [x] 2.5 라우터 로깅 — `structlog.get_logger(__name__)` + `meals.created/updated/deleted` 이벤트 (raw_text *내용* 로그 X — `raw_text_len`만).
- [x] 2.6 `api/app/main.py` — `from app.api.v1 import meals as meals_router` import + `app.include_router(meals_router.router, prefix="/v1/meals", tags=["meals"])` 1줄 추가(legal 라우터 다음).
- [x] 2.7 `ruff check . && ruff format --check . && mypy app` clean. SQLAlchemy `func.now()` / `func.coalesce` 타입 인식 정상.

### Task 3 — 백엔드 테스트 22+ 케이스 + conftest TRUNCATE 갱신 (AC: #10)

- [x] 3.1 `api/tests/conftest.py:_truncate_user_tables` — TRUNCATE 문에 `meals` 추가 (`TRUNCATE meals, consents, refresh_tokens, users RESTART IDENTITY CASCADE`).
- [x] 3.2 `api/tests/test_meals_router.py` 신규 — AC10 명시 22 케이스 작성. fixture: `client`, `user_factory`, `consent_factory`, `auth_headers`. helper: `_valid_meal_payload()` returning `{"raw_text": "삼겹살 1인분"}`.
- [x] 3.3 케이스 그룹화 — 4 endpoint × 평균 5-6 케이스 = 22 케이스. POST/PATCH/DELETE는 각각 동의 게이트 회귀 1 케이스 + 인증 1 케이스 + 엣지 케이스 3-4건.
- [x] 3.4 `uv run pytest --cov=app --cov-fail-under=70` 통과. 본 스토리 신규 케이스가 약 22 — 기존 case 수 대비 +20%.
- [x] 3.5 `ruff check . && ruff format --check . && mypy app` 모두 clean.

### Task 4 — Mobile (tabs) 라우팅 + meals 폴더 구조 (AC: #6)

- [x] 4.1 `mobile/app/(tabs)/_layout.tsx` 갱신 — `<Tabs>` 안에 명시적 `<Tabs.Screen name="index" options={{ href: null }} />` + `<Tabs.Screen name="meals" options={{ title: '식단', tabBarIcon: ({ color }) => <Ionicons name="restaurant" color={color} size={...} /> }} />` + `<Tabs.Screen name="settings" options={{ title: '설정', tabBarIcon: ... }} />`. 4 가드 로직(Story 1.6 정합)은 그대로 유지.
- [x] 4.2 `mobile/app/(tabs)/index.tsx` — 기존 placeholder 화면을 `<Redirect href={'/(tabs)/meals' as Parameters<typeof Redirect>[0]['href']} />`로 교체. typedRoutes cast Story 1.5/1.6 패턴.
- [x] 4.3 `mobile/app/(tabs)/meals/_layout.tsx` 신규 — `<Stack screenOptions={{ headerShown: true }} />` (Stack navigator). `headerShown: true`는 상단 *"식단"* 헤더 노출 — 카드 list/입력 화면이 같은 stack 내에서 push로 이동 시 자동 *back* 버튼.

### Task 5 — Mobile features/meals — TanStack Query api.ts + 컴포넌트 (AC: #7, #8)

- [x] 5.1 `mobile/features/meals/api.ts` 신규 — TanStack Query hooks:
  - `useMealsQuery(params)` — `GET /v1/meals?from_date=&to_date=&limit=` (`authFetch` 사용, JSON parse, `MealListResponse` 타입 forward).
  - `useCreateMealMutation` — `POST /v1/meals` body. 성공 후 `queryClient.invalidateQueries({ queryKey: ['meals'] })`.
  - `useUpdateMealMutation` — `PATCH /v1/meals/{meal_id}` body. 성공 후 동일 invalidate.
  - `useDeleteMealMutation` — `DELETE /v1/meals/{meal_id}`. 성공 후 동일 invalidate.
  - 타입: `mobile/lib/api-client.ts`에서 자동 생성된 타입 import (`MealResponse`, `MealCreateRequest`, `MealUpdateRequest`, `MealListResponse`) — Task 6 OpenAPI 재생성 후 사용.
- [x] 5.2 `mobile/features/meals/mealSchema.ts` 신규 — `mealCreateSchema` zod 검증(`raw_text: z.string().trim().min(1).max(2000)`). Story 1.5 `healthProfileSchema.ts` 패턴 정합.
- [x] 5.3 `mobile/features/meals/MealCard.tsx` 신규 — `{ meal: MealResponse; onActionPress: () => void }` props. raw_text + ate_at(HH:mm) 표시. long-press 시 `onActionPress()` 콜백.
- [x] 5.4 `mobile/features/meals/MealInputForm.tsx` 신규 — `react-hook-form` + `zodResolver(mealCreateSchema)`. PATCH 모드(`defaultValues` 입력 받음) + POST 모드 통합. `onSubmit` props로 외부 mutation 호출.
- [x] 5.5 `mobile/app/(tabs)/meals/index.tsx` 신규 — list 화면. `useMealsQuery({ from_date: today, to_date: today })` 호출. 카드 long-press → `Platform.OS === 'ios' ? ActionSheetIOS.showActionSheetWithOptions : Alert.alert` 분기 → 수정/삭제. 빈 화면 / 로딩 / 에러 표준 화면(AC7).
- [x] 5.6 `mobile/app/(tabs)/meals/input.tsx` 신규 — `useLocalSearchParams<{ meal_id?: string }>()`로 분기. PATCH 모드 prefill은 `queryClient.getQueryData(['meals', ...])`에서 직접 검색 또는 (간단화) 추가 GET 호출. 헤더 텍스트 분기 *"식단 입력"* / *"식단 수정"*. submit 시 `useCreateMealMutation` 또는 `useUpdateMealMutation` 호출 후 `router.replace('/(tabs)/meals')`.
- [x] 5.7 401/403/400 에러 처리 — `extractSubmitErrorMessage` (Story 1.5 패턴 — inline 또는 `mobile/lib/error.ts` 신규 헬퍼). 403 `consent.basic.missing` 시 `router.replace('/(auth)/onboarding/disclaimer')`.
- [x] 5.8 `pnpm tsc --noEmit` + `pnpm lint` 통과 (0 errors). typedRoutes — 신규 라우트(`/(tabs)/meals`, `/(tabs)/meals/input`)가 `mobile/.expo/types/router.d.ts`에 자동 등록되기 전 cast 우회 필요 시 Story 1.5 패턴 적용.

### Task 6 — OpenAPI 클라이언트 자동 재생성 + Web 타입 sync (AC: #9)

- [x] 6.1 `IN_PROCESS=1 bash scripts/gen_openapi_clients.sh` 실행 → `mobile/lib/api-client.ts` + `web/src/lib/api-client.ts` 갱신. `MealCreateRequest`/`MealUpdateRequest`/`MealResponse`/`MealListResponse` 4 타입 + `/v1/meals` 4 path operation 노출 확인(`grep "v1/meals"` + `grep "MealResponse"`).
- [x] 6.2 두 워크스페이스 `pnpm tsc --noEmit` 통과(타입 인식 정상).
- [x] 6.3 PR push 시 `openapi-diff` GitHub Actions 잡 통과 — schema dump 결과 commit으로 마무리(CI fresh 재생성과 비교 시 diff 0건).

### Task 7 — README + sprint-status 갱신 + smoke 검증 (AC: #10)

- [x] 7.1 `README.md` — 기존 *"온보딩 튜토리얼 SOP"* 단락 다음에 *"식단 CRUD SOP"* 1 단락 추가 (간결 — 6 줄 이하):
  - (a) `/v1/meals` REST 4 endpoint(POST/GET/PATCH/DELETE) 1줄 요약 + 동의 게이트 wire(작성만) + 조회는 인증만(PIPA Art.35) 1줄
  - (b) `meals` soft delete 정책(`deleted_at` set, 30일 grace + 물리 파기는 Story 5.2 책임) 1줄
  - (c) `Idempotency-Key` 헤더 — Story 2.5 책임(본 스토리 baseline은 수신만 허용) 1줄
  - (d) Epic 2(*식단 입력 + 일별 기록 + 권한 흐름*) 1번째 스토리(2.1) 완료 + 후속 5 스토리 안내 1줄
- [x] 7.2 smoke 검증 4 시나리오 — AC10 그대로(local docker compose up 환경에서 사용자가 별도 수행). 본 task는 *Dev Agent Record Completion Notes에 결과 기록* 만 — 백엔드 게이트(pytest/ruff/mypy clean) + 모바일 게이트(tsc/lint clean) 통과로 충분(Story 1.5/1.6 패턴 정합).
- [x] 7.3 Dev Agent Record + File List + Completion Notes 작성 후 `Status: review` 전환.
- [x] 7.4 `_bmad-output/implementation-artifacts/sprint-status.yaml` — `2-1-식단-텍스트-입력-crud` → `review` 갱신 + epic-2 → `in-progress` 자동 갱신(첫 스토리이므로 create-story가 이미 했어야 함 — review 시점에 중복 검증).

## Dev Notes

### Architecture decisions (반드시 따를 것)

[Source: architecture.md#Data Architecture (line 281-299), architecture.md#API Patterns (line 314-326), architecture.md#Cross-Cutting Concerns (line 870-908), epics.md#Story 2.1 (line 506-518), Story 1.5 Dev Notes 패턴]

**`meals` 테이블은 Epic 2 단일 출처 — `image_key` / 분석 결과는 후속 스토리/에픽 책임**

- 본 스토리 0006 마이그레이션은 **텍스트 전용 7컬럼**: id/user_id/raw_text/ate_at/created_at/updated_at/deleted_at. `image_key`는 **Story 2.2 0007 마이그레이션에서 추가**(텍스트 NULL + image_key NOT NULL 케이스를 분리 마이그레이션으로 박을 때 더 단순). 본 스토리에서 `image_key` nullable 컬럼 미리 추가하면 *2.1 baseline에서 사용처가 0이라 dead column* — yagni 회피.
- `meal_analyses` 테이블(architecture line 680/879)은 **Epic 3 책임** — 본 스토리에서 *"분석 결과는 invalidate 표시"* 라는 epic AC는 *클라이언트 UI 상의 표시*(Story 2.4가 polish — fit_score 카드에 *"수정됨"* badge 표시)이며 본 스토리 baseline은 `meal.updated_at > meal.created_at + 1초` 클라이언트 derive로 충분(Epic 3가 본격 invalidation 흐름 도입 시점에 해당 칼럼 도입).
- soft delete pattern은 *meals.deleted_at*만 — `users.deleted_at`(Story 1.2 baseline) 패턴 정합. 30일 grace + 물리 파기 cron은 *전사 정책*(architecture line 297) — Story 5.2가 `soft_delete_purge.py` worker로 일괄 도입. 본 스토리는 *컬럼 + read 필터*만.

**REST endpoint 4종 — POST/GET/PATCH/DELETE — wrapper 응답 X / 직접 응답 객체 (architecture line 459)**

- 응답 형식: `{"id": "...", "raw_text": "...", "ate_at": "...", ...}` 직접. `{data, error}` wrapper 도입 X(Anti-pattern 카탈로그 line 559).
- 에러: RFC 7807 Problem Details(`application/problem+json`) — 글로벌 핸들러(`main.py:177`)가 자동 변환. 본 스토리는 `MealNotFoundError` 1건 추가만 — 글로벌 핸들러 코드 수정 X.
- HTTP status: POST 201 Created, GET 200, PATCH 200, DELETE 204. 모든 메소드가 200으로 일원화하는 anti-pattern 회피(REST 표준 준수).
- URL 패턴: `/v1/meals` (kebab-plural noun, line 404), `/v1/meals/{meal_id}` path param FastAPI 표준(line 405).
- Query: snake_case (`from_date`, `to_date`, `limit`, `cursor`) line 406 정합.

**`require_basic_consents` 작성에만 wire / 조회는 인증만 — PIPA Art.35 정합 (deps.py:140-151 주석)**

- `POST /v1/meals` (생성), `PATCH /v1/meals/{meal_id}` (수정), `DELETE /v1/meals/{meal_id}` (삭제) 3 endpoint에 `Depends(require_basic_consents)` wire.
- `GET /v1/meals` (조회)는 `Depends(current_user)`만. 사유: PIPA 23조 정보주체 권리(열람·정정·삭제·처리정지)는 동의 철회와 독립. 사용자가 동의 철회 후에도 자기 데이터를 *볼 권리*가 있어야 함. + UX 모순(자기가 입력한 데이터를 볼 수 없음) 차단.
- Story 1.5 `POST /v1/users/me/profile` 정합 — *작성*만 동의 게이트, *조회*(`GET /v1/users/me/profile`)는 인증만. 본 스토리가 두 번째 적용 사례 — `require_basic_consents`가 점진적으로 모든 작성 라우터에 wire되는 패턴(Story 4.1 알림 설정, Story 5.1 프로필 수정 등 forward).

**소유권 / 존재 검증 — *단일 SQL with WHERE 통합 + RETURNING* — 404 일원화로 enumeration 차단**

- PATCH/DELETE에서 *소유권 미일치* / *존재 X* / *이미 soft-deleted* 모두 같은 응답(404 + `code=meals.not_found`).
- 사유: 403/404 분기 시 공격자가 status 차이로 *meal_id 존재 여부 enumeration* 가능. 보안 모범 사례(GitHub/Twitter 등 표준 패턴)에 따라 *비공개 리소스에 대한 접근* 모두 404 반환.
- 구현 — Python `if owner != user.id: raise 403; if not exists: raise 404` 분기 회피. 단일 SQL `update().where(id, user_id, deleted_at IS NULL).returning(...)` + `scalar_one_or_none() is None → MealNotFoundError`. race-free + 코드 단순.
- Story 1.5 race-free RETURNING 패턴 정합(`api/app/api/v1/users.py:177-194` `update().values().returning(User).execution_options(populate_existing=True)`).

**식단 raw_text는 NFR-S5 마스킹 대상 — 로그에 *내용* 출력 금지**

- architecture line 309: *"민감정보 마스킹 — Sentry before_send hook + structlog processor — 정규식으로 이메일/체중/식단 raw_text/알레르기 항목 마스킹"*.
- 본 스토리는 *전사 마스킹 processor 도입 X*(Story 8 cross-cutting). 단, **본 스토리 신규 라우터의 로그 이벤트는 `raw_text` 내용 raw 출력 X** — `meals.created` 이벤트는 `user_id`, `meal_id`, `raw_text_len`, `ate_at_iso`만 forward(*길이*만). 향후 마스킹 processor 도입 시 추가 정합 작업 0.
- Sentry 자동 capture는 본 스토리 baseline에서 `Exception` raise 시점에 발생 — 도메인 예외(`MealNotFoundError`)는 expected이므로 `BalanceNoteError` 핸들러가 catch + RFC 7807 변환(Sentry capture는 `INTERNAL`/unhandled에서만).

**Idempotency-Key 처리 — Story 2.5 책임 (본 스토리 baseline은 헤더 *수신*만)**

- architecture line 324: *"Idempotency — 결제 webhook + 식단 입력에 Idempotency-Key 헤더 권장"*. line 138 `main.py` CORS `allow_headers`에 `Idempotency-Key` 이미 등록.
- Story 2.5(*오프라인 텍스트 큐잉 + 온라인 자동 sync*)에서 *"같은 항목 sync 중복 방지 — Idempotency-Key(client-generated UUID) 헤더로 멱등 처리"* 명시(epic AC).
- **본 스토리는 헤더 도입 X** — POST `/v1/meals`가 같은 Idempotency-Key 헤더로 재발사 시 *새 row 생성*(중복) — 의도적 baseline. Story 2.5에서 `idempotency_keys` 또는 `meals.idempotency_key UNIQUE` 컬럼 추가 + 409/200 멱등 분기 흡수.
- 클라이언트(mobile)도 본 스토리에서 헤더 *송신 X* — 단순 POST. Story 2.5 offline-queue.ts가 헤더 송신 책임.

**`(tabs)/_layout.tsx` 명시적 `<Tabs.Screen>` 등록 — index 라우트 hide(`href: null`)**

- Expo Router는 `(tabs)/<route>.tsx` 또는 `(tabs)/<route>/` 폴더를 자동 탭으로 등록. 명시 `<Tabs.Screen name="..." />` 미사용 시 alphabetical 순서 + 모든 child 노출.
- 본 스토리는 `index.tsx`(redirect-only) + `meals/`(첫 탭) + `settings/`(두 번째 탭) 3 child가 존재 — index가 탭에 노출되면 UX 혼란.
- **채택**: 명시 `<Tabs.Screen name="index" options={{ href: null }} />` — `href: null`은 Expo Router 표준 hide 패턴(*탭 바에서 제외*). + `<Tabs.Screen name="meals" />` + `<Tabs.Screen name="settings" />` 명시 등록.
- `(tabs)/index.tsx`는 *유지* + Redirect 컴포넌트로 — deeplink `/(tabs)` 안전성.

**모바일 form/list 패턴 — react-hook-form + zod + TanStack Query (Story 1.5 정합)**

- 폼: `react-hook-form` + `zodResolver` (Story 1.5 `useHealthProfile.ts` 패턴 정합). `mealCreateSchema`는 zod 단일 schema에서 trim/min/max 검증.
- mutation: TanStack Query `useMutation` + `onSuccess` 시 `queryClient.invalidateQueries({ queryKey: ['meals'] })`. optimistic update 회피(yagni — 실패 시 rollback 복잡, baseline은 단순).
- 데이터 fetch: `useQuery` + `queryKey: ['meals', { from_date, to_date }]` (직렬화 가능한 plain object — TanStack Query 표준).
- ActionSheet 분기 — `Platform.OS === 'ios' ? ActionSheetIOS.showActionSheetWithOptions : Alert.alert` (외부 라이브러리 X — Story 1.6 `react-native-swiper` 회피 패턴 정합). Bottom sheet 라이브러리(`@gorhom/bottom-sheet` 등) 도입 X — yagni.

**Web 측 변경 X — OpenAPI 클라이언트 타입만 갱신**

- Architecture: 식단 입력은 *모바일 전용*(line 805 `mobile/(tabs)/meals/input.tsx` — Web 등가 라우트 부재). Web은 *주간 리포트·관리자* 책임(Epic 4·7).
- 본 스토리는 `web/src/lib/api-client.ts` 자동 재생성만 — UI 코드 변경 0건. 향후 Story 5.3(데이터 내보내기) / 7.2(관리자 사용자 검색)에서 web 측 활용.

### Library / Framework 요구사항

[Source: architecture.md#Frontend Architecture (line 327-339), architecture.md#Data Architecture (line 281-299), Story 1.5 Dev Notes 패턴]

| 영역 | 라이브러리 | 정확한 사유 |
|------|-----------|-----------|
| 백엔드 ORM | SQLAlchemy 2.0 async + asyncpg + `Mapped[]` `mapped_column` | 기존 패턴(Story 1.2/1.5 정합). `from sqlalchemy.dialects.postgresql import UUID` + `from sqlalchemy.orm import Mapped, mapped_column`. |
| 백엔드 race-free 쓰기 | `update().where(...).values(...).returning(Meal).execution_options(populate_existing=True)` | Story 1.5 `users.py:177-194` 패턴 정합 — 동시 변경 시 race 차단 + commit 전 응답 build로 expired 객체 lazy-load 회피. |
| 백엔드 단일 시계 | `func.now()` (DB-side) | Python `datetime.now()` 회피 — Story 1.5 P10 patch 정합. clock skew 차단. |
| Pydantic 모델 | `ConfigDict(extra="forbid")` + `Field(min_length, max_length)` + `@field_validator` + `@model_validator(mode="after")` | Story 1.5 `HealthProfileSubmitRequest` 패턴 정합. `extra="forbid"`로 silent unknown field 차단. |
| Alembic 마이그레이션 | `op.create_table` + `op.create_index(postgresql_where=...)` | Story 1.5 0005 패턴 — `op.execute` raw SQL 회피(가독성·downgrade 명확성). partial index는 `postgresql_where=text("deleted_at IS NULL")`. |
| 모바일 server state | TanStack Query `@tanstack/react-query` (이미 설치) | Story 1.5 정합 — `useQuery`/`useMutation` + `queryClient.invalidateQueries`. 캐시·재시도·dedup 표준. |
| 모바일 form | `react-hook-form` + `zod` (이미 설치) | Story 1.5 `healthProfileSchema.ts` 패턴 정합. |
| 모바일 ActionSheet | RN 표준 `ActionSheetIOS` (iOS) + `Alert.alert` (Android fallback) | 외부 라이브러리(`@gorhom/bottom-sheet` 등) 도입 X — Story 1.6 `react-native-swiper` 회피 패턴 정합. yagni. |
| 모바일 redirect | `Redirect` from `expo-router` (Story 1.3·1.4·1.5·1.6 패턴) | 라우터 state 보존 + cast 우회 패턴 정합. |

### Naming 컨벤션

[Source: architecture.md#Naming Patterns (line 386-431), Story 1.5 Dev Notes 정합]

- DB 테이블: `meals` (snake_case 복수, line 392).
- DB 컬럼: `id`, `user_id`, `raw_text`, `ate_at`, `created_at`, `updated_at`, `deleted_at` (snake_case, line 393).
- DB FK: `user_id` (`<referenced_table_singular>_id`, line 394).
- DB 인덱스: `idx_meals_user_id_ate_at_active` (`idx_<table>_<columns>_<modifier>` — partial index는 modifier suffix로 의미 표시 — line 395 패턴 + active 의미 명시).
- API URL: `POST /v1/meals`, `GET /v1/meals`, `PATCH /v1/meals/{meal_id}`, `DELETE /v1/meals/{meal_id}` (kebab-plural + path param `{meal_id}` line 404-406).
- API Query: `from_date`, `to_date`, `limit`, `cursor` (snake_case line 406).
- JSON wire: snake_case 양방향 (line 412 — `raw_text`, `ate_at`, `user_id` 등).
- Python 파일: `api/app/db/models/meal.py`, `api/app/api/v1/meals.py`, `api/alembic/versions/0006_meals.py`, `api/tests/test_meals_router.py` (snake_case.py — line 427).
- Python 클래스: `Meal`, `MealCreateRequest`, `MealUpdateRequest`, `MealResponse`, `MealListResponse`, `MealError`, `MealNotFoundError` (PascalCase — line 420).
- TS/Mobile 파일: `mobile/features/meals/MealCard.tsx`, `MealInputForm.tsx`(PascalCase 컴포넌트), `mealSchema.ts`(camelCase 모듈), `api.ts`(kebab/camel — Story 1.5 정합으로 camelCase 유지). `mobile/app/(tabs)/meals/index.tsx`, `input.tsx` (kebab-case + Expo Router 표준 — line 431).
- 에러 코드 카탈로그: `meals.not_found`, `meals.error`(base) (`<domain>.<sub>.<reason>` 패턴 — Story 1.3 `consent.basic.missing` / Story 1.2 `auth.access_token.invalid` 정합).
- 로깅 이벤트: `meals.created`, `meals.updated`, `meals.deleted` (`<domain>.<verb>` past tense — Story 1.5 `users.profile.updated` 정합).

### 폴더 구조 (Story 2.1 종료 시점에 *반드시* 존재해야 하는 신규/수정 항목)

[Source: architecture.md#Complete Project Directory Structure (line 661-728, 800-833), Story 1.6 종료 시점 골격]

```
api/
├── alembic/versions/
│   └── 0006_meals.py                                      # 신규 — meals 테이블 + partial index
├── app/
│   ├── api/v1/
│   │   └── meals.py                                       # 신규 — POST/GET/PATCH/DELETE 4 endpoint
│   ├── core/
│   │   └── exceptions.py                                  # 갱신 — MealError + MealNotFoundError 2 클래스 추가
│   ├── db/models/
│   │   ├── __init__.py                                    # 갱신 — Meal import + __all__ 추가
│   │   └── meal.py                                        # 신규 — Meal ORM 모델
│   └── main.py                                            # 갱신 — meals_router include 1줄
└── tests/
    ├── conftest.py                                        # 갱신 — TRUNCATE 문에 meals 추가
    └── test_meals_router.py                               # 신규 — 22+ 케이스

mobile/
├── app/
│   └── (tabs)/
│       ├── _layout.tsx                                    # 갱신 — <Tabs.Screen> 명시 등록 (index hide / meals / settings)
│       ├── index.tsx                                      # 갱신 — placeholder → <Redirect to="/(tabs)/meals" />
│       └── meals/
│           ├── _layout.tsx                                # 신규 — Stack navigator
│           ├── index.tsx                                  # 신규 — list 화면 (long-press ActionSheet)
│           └── input.tsx                                  # 신규 — POST + PATCH 통합 폼 (?meal_id= 분기)
├── features/
│   └── meals/
│       ├── api.ts                                         # 신규 — TanStack Query hooks (useMealsQuery + 3 mutation)
│       ├── mealSchema.ts                                  # 신규 — zod schema (mealCreateSchema)
│       ├── MealCard.tsx                                   # 신규 — 카드 컴포넌트 (long-press)
│       └── MealInputForm.tsx                              # 신규 — react-hook-form 폼
└── lib/
    └── api-client.ts                                      # 갱신 (자동 — pnpm gen:api)

web/
└── src/lib/
    └── api-client.ts                                      # 갱신 (자동 — pnpm gen:api)

README.md                                                  # 갱신 — 식단 CRUD SOP 1 단락 추가
_bmad-output/implementation-artifacts/sprint-status.yaml   # 갱신 — 2-1 → review (epic-2 → in-progress 자동)
```

**중요**: 위에 명시되지 않은 항목(`api/app/services/meal_service.py`, `api/app/db/models/meal_analysis.py`, `api/alembic/versions/0007_meals_image_key.py`, `mobile/features/meals/ChatStreaming.tsx`, `mobile/features/meals/DailyMealList.tsx`, `mobile/lib/offline-queue.ts`, `mobile/app/(tabs)/meals/[meal_id].tsx`, `web/src/app/(user)/meals/*`)은 본 스토리에서 생성하지 않는다. premature scaffolding 회피(Story 1.4·1.5·1.6 정합):

- `meal_service.py`: 본 스토리는 라우터 inline 로직으로 충분(약 50줄). service 분리는 Epic 3 분석 흐름 결합 시점에 의미 — yagni. architecture line 878 `meal_service.py` 명시는 *최종 구조* 표기이며 Story 단계별 도입 가능.
- `meal_analysis.py` ORM: Epic 3 Story 3.x 책임.
- `0007_meals_image_key.py`: Story 2.2 책임.
- `[meal_id].tsx`: Story 3.7(채팅 SSE) 책임.
- `DailyMealList.tsx` (별도 컴포넌트): 본 스토리는 `(tabs)/meals/index.tsx`에 list 로직 inline. 컴포넌트 분리는 Story 2.4 시점(매크로/fit_score 추가로 복잡도 증가 시).

### 보안·민감정보 마스킹 (NFR-S5)

[Source: prd.md#NFR-S5, architecture.md#Authentication & Security (line 309), Story 1.5 Dev Notes]

- **`raw_text`는 NFR-S5 마스킹 대상**(architecture line 309 명시 *"식단 raw_text"*). 본 스토리 라우터의 모든 로그는 *raw_text 내용 raw 출력 X* — `raw_text_len`(길이)만 forward.
- 전사 structlog processor / Sentry before_send hook 도입은 Story 8 cross-cutting cleanup 책임. 본 스토리는 *해당 processor 도입 후* `raw_text`가 LLM/Sentry로 leak되지 않도록 **로그에 raw_text 출력 안 함** 패턴만 박는다.
- 응답 body의 `raw_text`는 *사용자 자기 데이터*이므로 마스킹 X (자기 데이터 조회·수정·삭제는 PIPA Art.35 정보주체 권리). 마스킹은 *log/observability 출력*에만 적용.
- ate_at(timestamp) / id / user_id (UUID) — 민감정보 X. 마스킹 의무 X.
- `deleted_at`는 soft delete 흔적 — *삭제 사실*은 사용자 본인 작업 결과이므로 응답 노출 OK. 다른 사용자에게는 enumeration 차단(404 일원화).

### Anti-pattern 카탈로그 (본 스토리 영역)

[Source: Story 1.4·1.5·1.6 Anti-pattern 카탈로그, architecture.md#Anti-pattern (line 557-565)]

- ❌ Backend `meals.image_key` 컬럼 nullable로 0006에 미리 추가 — Story 2.2까지 사용처 0건이라 dead column. yagni 회피. Story 2.2 0007 마이그레이션에서 도입.
- ❌ Backend `meal_analyses` 테이블 0006에 미리 생성 — Epic 3 Story 3.3 책임. yagni.
- ❌ Backend `meals.idempotency_key` UNIQUE 컬럼 0006에 미리 추가 — Story 2.5 책임 (offline-queue 흐름과 함께 도입 시 멱등 의미 명확). yagni.
- ❌ Backend wrapper 응답 `{data: {...}, error: null}` 도입 — architecture line 559 anti-pattern. 직접 응답 객체.
- ❌ Backend PATCH/DELETE에서 *소유권 미일치 → 403* / *존재 X → 404* 분기 — enumeration 가능. **채택**: 모든 비공개/미존재 응답 404 일원화.
- ❌ Backend 식단 hard delete (`DELETE FROM meals WHERE id=...`) — 30일 grace 보존 정책(Story 5.2) 위반. **채택**: soft delete (`UPDATE meals SET deleted_at=now()`).
- ❌ Backend `MealNotFoundError` 미도입하고 `HTTPException(404)` 사용 — 도메인 예외 계층(line 562 anti-pattern *"도메인 예외 없이 generic HTTPException 남발"*). **채택**: `BalanceNoteError` 하위 `MealError` → `MealNotFoundError`.
- ❌ Backend `raw_text` 로그 raw 출력 — NFR-S5 위반. 길이/메타데이터만.
- ❌ Backend GET `/v1/meals`에 `Depends(require_basic_consents)` wire — 자기 데이터 조회를 동의 게이트로 차단 시 PIPA Art.35 권리 봉쇄(`deps.py:140-151` 명시). **채택**: 조회 경로는 `current_user`만.
- ❌ Backend offset pagination (`skip=N&limit=N`) 도입 — architecture line 482/564 anti-pattern. **채택**: cursor-based(`?cursor=...&limit=20`) — 본 스토리 baseline은 cursor 미구현(Story 2.4 도입 시점)이며, *offset은 절대 도입 X*. 본 스토리 응답에서 `next_cursor: null` 명시(forward-compat).
- ❌ Backend `meals` 테이블 stored procedure 도입 — 1인 8주 over-engineering. SQL 직접 + ORM 표준.
- ❌ Mobile `(tabs)/index.tsx` 삭제 — deeplink `/(tabs)` 깨짐 위험. **채택**: redirect 컴포넌트로 유지 + `href: null`로 탭 바 hide.
- ❌ Mobile `[meal_id].tsx` 라우트 본 스토리에서 도입 — Story 3.7(채팅 SSE) 책임. 본 스토리 baseline은 list ActionSheet → input.tsx PATCH 모드로 충분.
- ❌ Mobile 외부 BottomSheet 라이브러리(`@gorhom/bottom-sheet`, `react-native-actions-sheet`) 도입 — RN 표준 `ActionSheetIOS` + `Alert.alert` fallback으로 충분. 신규 의존성 + bundle 크기 증가 회피(Story 1.6 `react-native-swiper` 회피 패턴 정합).
- ❌ Mobile cache invalidation을 수동 timestamp 비교로 — TanStack Query `invalidateQueries({ queryKey: ['meals'] })` 표준 활용(architecture line 522 anti-pattern *"로딩 boolean 자체 관리"* 정합).
- ❌ Mobile `useMealQuery(meal_id)` 단건 GET 추가 도입 — list 캐시 prefill로 충분. 추가 endpoint(`GET /v1/meals/{meal_id}`) 미요구. yagni.
- ❌ Mobile `Idempotency-Key` 헤더 client-side 송신 — Story 2.5 offline-queue 책임. 본 스토리 baseline 도입 X.
- ❌ Mobile optimistic update 도입 (`onMutate` rollback 패턴) — 실패 시 rollback 복잡 + Story 2.5 offline 큐잉이 본격 책임. baseline 단순.
- ❌ Web 측 식단 입력 화면 도입 — architecture mobile-only 정합. yagni.

### Previous Story Intelligence (Story 1.4·1.5·1.6 학습)

[Source: `_bmad-output/implementation-artifacts/1-4-자동화-의사결정-동의.md` + `1-5-건강-프로필-입력.md` + `1-6-온보딩-튜토리얼.md` Dev Agent Record + Review Findings + `deferred-work.md`]

**적용 패턴(반드시 재사용):**

- **race-free RETURNING 단일 statement**: Story 1.5 `update().returning(User).execution_options(populate_existing=True)` — 본 스토리 PATCH/DELETE는 같은 패턴 + `where(meal.id, user_id, deleted_at IS NULL)` 통합으로 race + 소유권 + soft-delete 검증 1 SQL 처리.
- **DB-side `func.now()` 단일 시계**: Story 1.5 P10 patch — `meals.updated_at`/`deleted_at`/`ate_at` 모두 `func.now()` 또는 server_default `now()`. Python `datetime.now()` X.
- **OpenAPI 자동 재생성**: Story 1.4 P20 / Story 1.5 Task 8.1 / Story 1.6 Task 6 패턴 — 신규 라우터 추가 시 `pnpm gen:api` 후 클라이언트 재생성 + commit. CI `openapi-diff` 게이트 통과 보장. 본 스토리는 *4 endpoint + 5 Pydantic 모델* 신규 추가로 클라이언트 sync 필수.
- **typedRoutes cast 우회**: Story 1.5/1.6 typed routes 패턴(`as Parameters<typeof Redirect>[0]['href']` / `as Parameters<typeof router.push>[0]`) — 신규 라우트(`/(tabs)/meals`, `/(tabs)/meals/input`)에 그대로 적용.
- **bootstrap loading state**: Story 1.5/1.6 — `useQuery`의 `isPending` 또는 명시 `consentStatus === null` 체크 — 본 스토리는 `useMealsQuery`의 `isPending` 시 `<ActivityIndicator />` 표시 (TanStack Query 표준).
- **`accessibilityRole`/`accessibilityLabel` 명시**: Story 1.3·1.4·1.5·1.6 정합 — 카드 long-press / 버튼 / 입력 필드 모두 적용.
- **`extractSubmitErrorMessage` 패턴**: Story 1.5 inline 헬퍼 — 본 스토리 `mobile/features/meals/MealInputForm.tsx`에서 인라인 또는 `mobile/lib/error.ts` 신규 헬퍼 추출. 401/403/400 분기 + 5xx fallback.
- **conftest TRUNCATE 갱신**: Story 1.5 `consents`/`refresh_tokens`/`users` TRUNCATE 패턴 — 본 스토리는 `meals` 추가 (CASCADE로 자동 처리되나 명시 prepend로 가독성 — Story 1.5 conftest 주석 정합).

**Story 1.6 deferred-work.md 항목 — 본 스토리 처리:**

- 🔄 **W7/W33 (Story 1.3/1.6) — Mobile onboarding `?next=` 미독해** — onboarding 모든 화면이 forward만, 처리 X. 본 스토리는 (tabs) 그룹 진입이 자동으로 `/(tabs)/meals`로 라우팅되므로 *Story 1.6과 동일하게 forward만 수행* — `?next=` 처리는 **재 deferred**(Story 5.1 또는 Story 8 polish 시점).
- ⏭ **W8/W17 (Story 1.3/1.5) — Web cookie auth CSRF 보호** — 본 스토리 영향 X (Web UI 변경 X).
- ⏭ **W14 (Story 1.3) — `require_basic_consents` 라우터 wire 미적용** — Story 1.5에서 첫 wire (POST /v1/users/me/profile). **본 스토리가 두 번째 wire** — POST/PATCH/DELETE `/v1/meals/*` 3 endpoint. 회귀 테스트로 검증.
- ⏭ **W19 (Story 1.5) — Migration 0005 downgrade가 사용자 health 데이터 silent drop** — Story 8 운영 rollback runbook. 본 스토리 0006 마이그레이션 downgrade는 *meals 데이터 전체 drop* 동일 — Story 8에서 일괄 운영 SOP에 명시.
- ⏭ **W25 (Story 1.5) — `extractSubmitErrorMessage` 429/413 분기 부재** — rate limit(W16) 도입 후 polish. 본 스토리 신규 mutation 4건은 인라인 패턴 — 429/413은 Story 8 시점.
- ⏭ **W27 (Story 1.5) — Mobile `pathname` open-redirect 잠재성** — 본 스토리는 `(tabs)/_layout.tsx` 가드 4단계 그대로 (Story 1.6 정합).
- ⏭ **W34 (Story 1.6) — 단일 디바이스 다중 사용자 tutorial-seen 격리** — 본 스토리 영향 X.
- ⏭ **W36 (Story 1.6) — `asyncio.sleep(0.05)` flaky test smell** — 본 스토리 테스트는 *순차 호출 후 즉시 검증*(`updated_at > created_at` 비교 X) — 같은 race 위험 부재. PATCH 케이스에서 `created_at < updated_at` 검증 필요 시 동일 sleep 패턴 또는 *PATCH 응답의 updated_at가 created_at 이상* 정도로 약화 검증.

**신규 deferred 후보 (본 스토리 종료 시 `deferred-work.md` 추가):**

- *Cursor pagination 미구현* — `next_cursor: null` baseline. Story 2.4 일별 기록 화면이 7일/30일 history 표시 시점 또는 사용자 식단 1000건+ 시점에 도입.
- *`/v1/meals` 단건 GET endpoint 부재* — list 캐시 prefill로 충분하나 deeplink 진입 시(`/(tabs)/meals/input?meal_id=X` direct URL) prefill cache miss 가능. Story 3.7 채팅 SSE가 단건 GET 도입 시점에 흡수 또는 본 스토리 polish.
- *`meals` rate limit 미설정* — slowapi 운영 polish, Story 8 hardening (Story 1.5 W16 정합).
- *raw_text 마스킹 processor 미도입* — Story 8 cross-cutting (Story 1.3 W5 / 1.5 W17 정합 — *"민감정보 마스킹 processor 통합"*).
- *Mobile 기본 빈 화면 / 에러 화면 디자인 시스템 미통일* — Story 8 design polish (Story 1.5 W29/W30 정합).
- *Mobile `/(tabs)/meals/input?meal_id=` 진입 시 cache miss 시 fallback 처리* — list가 비어있는 상태에서 deeplink로 input?meal_id= 진입 시 `useQuery` 결과 없이 PATCH 시도 → undefined defaultValues로 빈 폼. Story 3.7 단건 GET 도입 시점에 cache miss fallback 자동 해결.
- *Backend `meals.idempotency_key` 부재 — POST 재발사 시 중복 row* — Story 2.5 offline-queue.ts + UNIQUE 컬럼 + 409 분기 일괄 도입.
- *Mobile optimistic update 부재 — POST 직후 list 새로고침 시 깜빡임 가능* — TanStack Query `setQueryData` 패턴은 Story 8 polish 또는 사용자 피드백 발생 시.
- *List 화면 날짜 picker 미구현* — `from_date=today` 고정. Story 2.4 일별 기록 화면이 7일 history + 날짜 picker 도입.

**Detected Conflict 처리:**

- Story 1.3·1.4·1.5·1.6에서 이미 처리됨. 본 스토리는 그 결정(`/v1/users/me/*` 라우터 prefix, snake_case 양방향, RFC 7807 응답, `require_basic_consents` 작성 게이트, race-free RETURNING) 그대로 활용.
- 새로운 충돌: **없음** — 본 스토리는 epic AC + architecture 명시 정합 패턴 그대로 구현.

### Git Intelligence (최근 커밋 패턴)

```
f2c738b docs(story-1.6): spec AC9 140행 모순 fix (Gemini PR #9 review)
ed1e1d9 fix(story-1.6): CR 13 patches (견고성·내비·회전·접근성·테스트) + Epic 1 종료
8ee64e8 chore(story-1.6): regenerate openapi clients (UserPublic.onboarded_at 노출)
5fb5877 feat(story-1.6): 온보딩 튜토리얼 (3 슬라이드 + skip/start) + onboarded_at 멱등 set + Epic 1 종료
8bded41 chore: ignore bmad-code-review local artifacts (.review-*) (#8)
```

**최근 커밋 패턴에서 학습:**

- 커밋 메시지: `feat(story-X.Y): <한국어 요약> + <부수 작업>` 형식 — 본 스토리도 `feat(story-2-1): 식단 텍스트 입력 CRUD baseline + meals 테이블 + Epic 2 시작` 패턴.
- *spec 모순 fix 커밋*: review 후 spec 자체 모순 발견 시 `docs(story-X.Y): spec ACN <줄번호> 모순 fix` 패턴 — 본 스토리도 review 시 동일 패턴 적용.
- OpenAPI 재생성 커밋 분리: 5fb5877(feat) → 8ee64e8(chore: regenerate openapi clients) — 본 스토리도 *코드 추가 커밋 + OpenAPI 재생성 커밋 분리* 권장(diff 명확성).
- CR patches 커밋 분리: 5fb5877 → ed1e1d9(fix: CR 13 patches) — 코드 리뷰 후 패치는 별 커밋. 본 스토리도 동일.

### References

- [Source: epics.md:506-518] — Story 2.1 epic AC 5건 (POST/카드 탭 수정/삭제 확인/빈 화면/에러 화면)
- [Source: prd.md:957-963] — FR12-FR16 Meal Logging
- [Source: architecture.md:281-299] — Data Architecture (`meals` ER 골격, soft delete 정책)
- [Source: architecture.md:303-312] — Authentication & Security (`require_basic_consents` 게이트)
- [Source: architecture.md:314-326] — API & Communication Patterns (REST + RFC 7807 + Idempotency-Key)
- [Source: architecture.md:386-431] — Naming Patterns (DB / API URL / JSON / 파일)
- [Source: architecture.md:455-482] — Format Patterns (RFC 7807 + 직접 응답 + ISO 8601 UTC + cursor pagination)
- [Source: architecture.md:557-565] — Anti-pattern 카탈로그
- [Source: architecture.md:803-833] — Mobile 폴더 구조 (`(tabs)/meals/{index,input,[meal_id]}.tsx`, `features/meals/*`)
- [Source: architecture.md:874-879] — Requirements to Structure Mapping (FR12-16 → meals.py + meal_service.py + r2.py + offline-queue.ts)
- [Source: 1-5-건강-프로필-입력.md] — race-free RETURNING / extractSubmitErrorMessage / Pydantic extra=forbid 패턴
- [Source: 1-6-온보딩-튜토리얼.md] — typedRoutes cast / `<Redirect href=...>` / 외부 라이브러리 회피 / typed routes 캐시 재생성
- [Source: deferred-work.md] — W7/W14/W17/W19/W25/W27/W33/W34/W36 forward-hooks 흡수 정책
- [Source: api/app/api/deps.py:140-151] — PIPA Art.35 정합 — 조회는 동의 무관 / 작성만 동의 게이트
- [Source: api/app/api/v1/users.py:177-194] — race-free `update().returning(User).execution_options(populate_existing=True)` 패턴
- [Source: api/alembic/versions/0005_users_health_profile.py] — alembic 0005 패턴 (op.create_table / op.create_index / `op.execute` 회피)
- [Source: api/app/core/exceptions.py:55-78] — `BalanceNoteError` 도메인 예외 base + ClassVar 패턴

## Dev Agent Record

### Agent Model Used

`claude-opus-4-7[1m]` — Amelia (bmad-agent-dev) → bmad-dev-story 워크플로우 실행
(2026-04-29).

### Debug Log References

- **mypy 오류 1건** (`api/app/api/v1/meals.py:139` 초안) — `Meal.__table__.insert()`
  방식이 SQLAlchemy 2.0 type stub에서 `FromClause`로 잡혀 `attr-defined` 에러.
  `from sqlalchemy import insert` + `insert(Meal).values(...).returning(Meal)`
  ORM 표준 패턴으로 교체 → 통과.
- **autogenerate diff 검증** — `0006_meals` 적용 후 `verify_meals_sync` revision
  생성 시 *meals 관련 diff 0건* 확인 (ORM↔migration sync). 표시된 `refresh_tokens`
  관련 drift는 본 스토리 범위 밖 (Story 1.2/1.4 모델 사전 drift) — 임시 verify
  revision 파일 삭제, 별도 후속 스토리 처리.
- **coverage 단일 파일 실행 시 68%** — `pytest tests/test_meals_router.py` 실행 시
  다른 라우터 미커버. 전체 `pytest` 실행 시 *80.29%* 통과.

### Completion Notes List

- **AC1 — `meals` 테이블 + Alembic 0006**: ORM 모델 `Meal` (7컬럼 + partial index
  `idx_meals_user_id_ate_at_active`), `0006_meals.py` 마이그레이션 (`upgrade`/
  `downgrade` 표준 alembic API). `alembic upgrade head` 통과 + autogenerate diff
  0건. ✅
- **AC2 — `POST /v1/meals` (require_basic_consents)**: `MealCreateRequest`
  (`extra="forbid"`, `min_length=1`/`max_length=2000`, `_validate_not_whitespace`
  field_validator). `insert(Meal).values(...).returning(Meal)` race-free 응답.
  201 + 7 필드 응답. `Idempotency-Key` 헤더 *수신만* 허용 (CORS 등록), 처리는
  Story 2.5. ✅
- **AC3 — `GET /v1/meals` (인증만 — PIPA Art.35)**: `current_user` Depends만 wire,
  `require_basic_consents` X. `from_date`/`to_date`/`limit`/`cursor` Query, soft-
  deleted/타 user 제외, `ORDER BY ate_at DESC` (partial index hit). 빈 결과 200 +
  `{"meals": [], "next_cursor": null}`. `cursor`는 *수신만*, `next_cursor`는 항상
  null. ✅
- **AC4 — `PATCH /v1/meals/{meal_id}` (require_basic_consents)**: `MealUpdateRequest`
  (`@model_validator` 최소 1 필드 필수). `update().where(id, user_id, deleted_at
  IS NULL).values(...).returning(Meal)` 단일 SQL — 소유권/존재/soft-delete 통합
  검증 + 404 일원화 (enumeration 차단). `updated_at = func.now()` 명시. ✅
- **AC5 — `DELETE /v1/meals/{meal_id}` (require_basic_consents)**: 단일 UPDATE
  `deleted_at = func.now()` + `RETURNING id`. 결과 None → 404 + `meals.not_found`.
  204 No Content + body 없음. 물리 삭제 X — Story 5.2 책임. ✅
- **AC6 — Mobile `(tabs)/_layout.tsx` 갱신 + meals 탭**: `<Tabs.Screen name="index"
  options={{ href: null }}>` (탭 바 hide) + `meals`/`settings` 명시 등록. 4 가드
  (Story 1.6 정합) 그대로 유지. ✅
- **AC6 (cont.) — `(tabs)/index.tsx` redirect 전환**: 기존 placeholder → `<Redirect
  href="/(tabs)/meals" />` (typedRoutes cast). deeplink `/(tabs)` 안전성 보존. ✅
- **AC7 — Mobile `(tabs)/meals/index.tsx` baseline 화면**: `useMealsQuery({
  from_date: today, to_date: today })`. `MealCard` long-press → ActionSheet
  (Platform 분기: iOS `ActionSheetIOS`, Android `Alert.alert`). 빈 화면 / 로딩
  `<ActivityIndicator />` / 에러 *"오류 — 다시 시도"* + `refetch()` 표준 화면.
  헤더 우상단 *＋* 버튼 → `/(tabs)/meals/input` push. accessibilityLabel 명시. ✅
- **AC8 — Mobile `(tabs)/meals/input.tsx` POST/PATCH 통합 폼**: `?meal_id=` query
  param 분기 — 미존재면 POST(헤더 *식단 입력*), 존재면 list 캐시(`['meals', ...]`)
  prefill + PATCH(헤더 *식단 수정*). 401 인터셉터 자동 처리, 403
  `consent.basic.missing` → onboarding/disclaimer redirect, 400/422 → 폼 필드
  에러, 5xx/네트워크 → Alert. zod schema (`mealCreateSchema`) `trim().min(1).max(
  2000)`. ✅
- **AC9 — 백엔드 라우터 wire + OpenAPI 자동 재생성**: `main.py`에
  `app.include_router(meals_router.router, prefix="/v1/meals", tags=["meals"])`
  추가. `IN_PROCESS=1 bash scripts/gen_openapi_clients.sh` 실행 → mobile/web
  `api-client.ts` 양쪽 갱신, `MealResponse`/`MealCreateRequest`/`MealUpdateRequest`
  /`MealListResponse` + `/v1/meals` 4 path 노출 확인 (각 18 hit). ✅
- **AC10 — 백엔드 테스트 22 케이스 + smoke**: `tests/test_meals_router.py` 22
  케이스 (POST 6 / GET 6 / PATCH 6 / DELETE 4). conftest `_truncate_user_tables`
  TRUNCATE 문에 `meals` prepend. 전체 `pytest` 161 passed, coverage 80.29%
  (`--cov-fail-under=70` 통과). smoke 4 시나리오는 사용자 별도 수행 (백엔드 게이트
  + 모바일 게이트 통과로 충분 — Story 1.5/1.6 패턴 정합). ✅
- **AC11 — `deps.py` 변경 X + `MealError`/`MealNotFoundError` 1건씩**:
  `app/core/exceptions.py`에 `MealError(BalanceNoteError)` base + `MealNotFoundError
  (MealError)` (404 / `meals.not_found` / "Meal not found") 추가. 글로벌
  `BalanceNoteError` 핸들러(`main.py:177`)가 자동 RFC 7807 변환. `deps.py` 0 변경.
  ✅

**전사 게이트**:
- API: `ruff check .` ✅ / `ruff format --check .` ✅ / `mypy app` ✅ (31 source
  files clean) / `pytest` 161 passed / coverage 80.29%.
- Mobile: `pnpm tsc --noEmit` ✅ / `pnpm lint` ✅.
- Web: `pnpm tsc --noEmit` ✅ (api-client.ts 자동 재생성 후).

**smoke 시나리오 (사용자 수행 권장)**:
1. 신규 사용자 — 온보딩 통과 → `/(tabs)/meals` 진입 → `+` 탭 → "삼겹살 1인분"
   입력 → 저장 → list에 즉시 표시.
2. 카드 long-press → 수정 ActionSheet → 수정 저장 → list 카드 갱신.
3. 카드 long-press → 삭제 ActionSheet → 확인 → list에서 카드 제거.
4. 동의 미통과 사용자 직접 API 호출 → 403 응답 (`code=consent.basic.missing`).

### File List

**API (신규 5 / 갱신 3)**:
- `api/app/db/models/meal.py` — 신규 (Meal ORM 모델 + partial index)
- `api/app/db/models/__init__.py` — 갱신 (Meal import + __all__)
- `api/alembic/versions/0006_meals.py` — 신규 (meals 테이블 마이그레이션)
- `api/app/api/v1/meals.py` — 신규 (POST/GET/PATCH/DELETE 4 endpoint + Pydantic 5)
- `api/app/core/exceptions.py` — 갱신 (MealError + MealNotFoundError 추가)
- `api/app/main.py` — 갱신 (meals_router include 1줄)
- `api/tests/conftest.py` — 갱신 (TRUNCATE meals 추가)
- `api/tests/test_meals_router.py` — 신규 (22 케이스)

**Mobile (신규 7 / 갱신 3 — 자동생성 1 포함)**:
- `mobile/app/(tabs)/_layout.tsx` — 갱신 (`<Tabs.Screen>` 명시 등록)
- `mobile/app/(tabs)/index.tsx` — 갱신 (placeholder → `<Redirect>`)
- `mobile/app/(tabs)/meals/_layout.tsx` — 신규 (Stack navigator)
- `mobile/app/(tabs)/meals/index.tsx` — 신규 (list 화면 + ActionSheet)
- `mobile/app/(tabs)/meals/input.tsx` — 신규 (POST/PATCH 통합 폼)
- `mobile/features/meals/api.ts` — 신규 (TanStack Query 4 hooks + MealSubmitError)
- `mobile/features/meals/mealSchema.ts` — 신규 (zod schema + wire 타입)
- `mobile/features/meals/MealCard.tsx` — 신규 (카드 컴포넌트)
- `mobile/features/meals/MealInputForm.tsx` — 신규 (RHF + zodResolver 폼)
- `mobile/lib/api-client.ts` — 자동 재생성 (Meal 타입 18 hit 추가)

**Web (자동생성 1)**:
- `web/src/lib/api-client.ts` — 자동 재생성 (Meal 타입 18 hit 추가, UI 변경 X)

**Docs / Status**:
- `README.md` — 갱신 (식단 CRUD SOP 1 단락 추가)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — 갱신
  (`2-1-식단-텍스트-입력-crud`: ready-for-dev → in-progress → review)
- `_bmad-output/implementation-artifacts/2-1-식단-텍스트-입력-crud.md` — 본 스토리
  파일 (Tasks 체크박스 + Dev Agent Record + File List + Status: review)

### Change Log

| Date | Author | Note |
|------|--------|------|
| 2026-04-29 | Amelia (claude-opus-4-7[1m]) | Story 2.1 baseline 구현 — meals 테이블 + REST CRUD 4종 + 모바일 list/input 화면 + OpenAPI 재생성. Status: ready-for-dev → review. |
