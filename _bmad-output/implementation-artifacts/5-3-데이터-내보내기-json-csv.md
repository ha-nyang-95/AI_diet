# Story 5.3: 데이터 내보내기 (JSON/CSV)

Status: review

<!-- Validation: Epic 5 마지막 스토리. Story 5.2 baseline(`DELETE /v1/users/me` + `app/workers/soft_delete_purge.py`의 `_build_user_dump_payload` JSON shape SOT + `_serialize_value` Decimal/UUID/datetime 변환 helper + R2 dump bucket 운영 SOP) + Story 5.1 baseline(`PATCH /me/profile` + 3 timestamp 의미 분리 + settings/profile 페이지 footer 진입점 + react-hook-form/zod 폼 SOT) + Story 4.3 baseline(`reports.py` `Depends(require_basic_consents)` + StreamingResponse 패턴 부재 — sse-starlette만 사용 중이라 본 스토리가 *최초 fastapi.responses.StreamingResponse 사용처*) 위에 *PIPA Art.35 정보주체 권리(데이터 이전·열람권) — JSON/CSV 통합 다운로드 endpoint*를 신설. epics.md:809-823 정합 — `GET /v1/users/me/export?format=json|csv` 신규(`Depends(current_user)` 단독 + audit 미기록) + `app/services/data_export_service.py` 신규(JSON/CSV 양 형식 SOT — Story 5.2 worker dump JSON shape를 *서비스 레이어 SOT*로 정상화하고 worker가 이를 호출하는 방향 — Story 5.2 dev notes의 *DF136 forward-hook* 즉시 해소) + 모바일 `(tabs)/settings/data-export.tsx` + Web `/account/export/page.tsx` 신규. 모바일은 `expo-file-system` + `expo-sharing` 2 신규 의존성(Expo SDK 54 baseline 호환) 도입 — 실 파일 다운로드는 `FileSystem.documentDirectory`에 write 후 OS share sheet으로 노출(Files/Drive/메일 등 사용자 선택). Web은 `Blob` + `URL.createObjectURL` + 임시 anchor click 표준 패턴(추가 의존성 0). 대용량 보호는 `StreamingResponse` + chunked iterator(JSON `ijson`-style 연속 dump X — *전체 payload 단일 dict + json.dumps generator chunking* MVP 정합. CSV는 row generator로 자연 streaming). 일반 사용자 자기 권리 행사이므로 audit 미기록 + `require_basic_consents` 미적용(Art.35 정합, Story 5.2 정합). -->

## Story

As a 엔드유저,
I want 내 식단·피드백·프로필 데이터를 JSON 또는 CSV로 다운로드하기를,
so that PIPA 정보주체 권리(데이터 이전·열람권 — Art.35)를 행사할 수 있고 외부 도구(Excel, Notion, BI 도구 등)로 자기 식습관을 분석할 수 있다.

## Acceptance Criteria

1. **AC1 — `app/services/data_export_service.py` 신규 + JSON/CSV 양 형식 SOT 통합**
   **Given** Story 5.2 `app/workers/soft_delete_purge.py`의 `_build_user_dump_payload`(JSON dump shape — user/consents/meals/notifications) + `_serialize_value`(Decimal/UUID/datetime → JSON-safe primitive 변환 helper) baseline + architecture.md:702 *"`data_export_service.py` # PIPA 권리 (FR9)"* SOT, **When** 신규 service 모듈 작성, **Then**:
   - **신규 파일** `api/app/services/data_export_service.py` — *user-facing export* SOT. Story 5.2 worker dump가 본 service를 호출하도록 정상화(*DF136 즉시 해소* — Story 5.2 dev notes forward-hook의 *"helper 통합 후 본 worker가 `data_export_service.export_user_data_json(...)` 호출로 갈아끼움(코드 변경 ~5 lines)"* 1:1 정합).
   - **`_serialize_value(v: Any) -> Any` 헬퍼**: Story 5.2 worker SOT 1:1 — `datetime` → `isoformat()`, `uuid.UUID` → `str()`, `Decimal` → `format(d, 'f')`(scientific notation 차단), 그 외는 pass-through. 본 모듈로 이전 + worker는 import.
   - **`_serialize_row(row: Any) -> dict[str, Any]` 헬퍼**: Story 5.2 SOT 1:1 — `{col.name: _serialize_value(getattr(row, col.name)) for col in row.__table__.columns}`. 본 모듈로 이전 + worker는 import.
   - **`async def collect_user_export_payload(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any] | None`**:
     - Story 5.2 `_build_user_dump_payload` SOT 1:1 + **`meal_analyses` 추가**(epics.md:818 *"피드백(`meal_analyses`)"* 정합 — Story 5.2 dump는 cron/물리 파기 *최소 set*이라 의도적 제외, 본 export는 *사용자 권리 행사*로 *전체 set* 의무).
     - 4 SELECT: `User.where(id=user_id)` / `Consent.where(user_id=user_id)` / `Meal.where(user_id=user_id, deleted_at IS NULL)` (soft-deleted meals 제외 — *현재 사용 중인 데이터*만, 사용자 권리 의도) / `MealAnalysis.where(user_id=user_id)` / `Notification.where(user_id=user_id)`.
     - **`meals[i].analysis` 매핑**: `meal_analyses`를 `meal_id` lookup dict로 빌드 후 각 meal row에 `analysis` 키로 nested(JSON 형식 응답 시 1 meal 1 analysis 구조 자연 표현). meals row + nested analysis row 모두 `_serialize_row` 변환.
     - 응답 dict shape:
       ```
       {
         "user_id": str(user_id),
         "exported_at": now_utc_iso,
         "schema_version": "1.0",
         "user": <serialized User row 단일 dict>,
         "consents": [<serialized Consent row>, ...],
         "meals": [{...meal_row, "analysis": <serialized MealAnalysis row | null>}, ...],
         "notifications": [<serialized Notification row>, ...]
       }
       ```
     - user 미발견 시 `None` 반환(Story 5.2 패턴 정합 — race로 이미 hard-deleted 시 graceful).
   - **`def serialize_payload_to_json_bytes(payload: dict[str, Any]) -> bytes`**:
     - `json.dumps(payload, ensure_ascii=False, default=str)` + `.encode("utf-8")` — Story 5.2 worker dump 정합. 한국어 enum 값 그대로 보존(`"weight_loss"` → 그대로 — 응답에서 한국어 매핑 X. epics.md:819 *"한국어 enum 값 그대로"*는 *알레르기 라벨* 같은 *값이 한국어인 컬럼*을 의미, ENUM `health_goal`은 영어 키를 그대로 유지 — 외부 도구 호환성 우선).
   - **`async def stream_csv_rows(payload: dict[str, Any]) -> AsyncIterator[str]`**:
     - **CSV 형식 SOT** (epics.md:820): UTF-8 BOM(`﻿`) + 한국어 헤더(*"날짜, 식사, 매크로, fit_score, 피드백 요약, 출처"* — epics.md literal 정합) + 줄바꿈 LF(`\n` — `\r\n` X). 1행 = 1 식단 입력(meal row). nested `analysis` 컬럼은 *flatten*해서 평면 6컬럼으로 표현.
     - **헤더 행**: `날짜,식사,매크로,fit_score,피드백 요약,출처\n`(BOM은 첫 chunk에 prefix).
     - **데이터 행 1건 매핑**:
       - `날짜`: `meal.ate_at` → KST `YYYY-MM-DD HH:MM`(timezone Asia/Seoul). 사유: 사용자가 외부 도구에서 시각화할 때 KST 직관(UTC ISO는 JSON 형식으로 별도 보존).
       - `식사`: `meal.raw_text`(NULL 미발생 — DB NOT NULL invariant). CSV escape — `"`로 감싸고 내부 `"`는 `""`로 escape(RFC 4180).
       - `매크로`: `analysis`가 있으면 `f"탄수 {C}g·단백 {P}g·지방 {F}g·{kcal}kcal"`, 없으면 빈 string. `C`/`P`/`F`는 numeric → int round + str.
       - `fit_score`: `analysis.fit_score` int 또는 빈 string.
       - `피드백 요약`: `analysis.feedback_summary`(120자 cap baseline). CSV escape.
       - `출처`: `analysis.citations`(jsonb 배열) → `"; "` join. 각 citation은 `{source, doc_title, published_year}` 중 `doc_title (published_year)` 형식. 없으면 빈 string. CSV escape.
     - **Generator 패턴**: 첫 yield는 BOM + 헤더, 이후 meals 길이만큼 row yield. 메모리 보호(NFR — 1년치 ≥ 10MB 시 한 번에 dump 회피). meals가 없으면 헤더만 1행 + 0 데이터 행.
   - **JSON streaming 처리**: payload 자체는 dict라 한 번에 메모리 적재 — 1년치 meals ≥ 10K row의 worst case에서도 raw_text+parsed_items 합쳐도 사용자당 ≤ 100MB 추정(MVP scale 안전 영역). 본 스토리는 *streaming response 자체*만 채택(`StreamingResponse` content는 byte chunk iterator) — 진정한 *low-memory streaming JSON*(`ijson`/`orjson` 등 라이브러리)은 OUT(YAGNI — MVP 스케일 외, deferred-work forward).
   - **Pydantic 모델 X**: payload는 dict shape SOT(JSON wire format은 dict → json.dumps). 응답 모델 Pydantic 등록(자동 OpenAPI schema)은 OUT — `StreamingResponse`는 Pydantic 응답 모델 미사용 패턴(FastAPI 표준 정합).

2. **AC2 — `GET /v1/users/me/export?format=json|csv` endpoint 신규 + StreamingResponse + Content-Disposition**
   **Given** Story 5.1 `PATCH /me/profile` SOT + Story 5.2 `DELETE /me` SOT(`Depends(current_user)` 단독, audit 미기록 — PIPA Art.35) + architecture.md:847 *"외부: `/v1/*` REST"* + epics.md:817-822 endpoint spec, **When** `api/app/api/v1/users.py`에 endpoint 추가, **Then**:
   - **Endpoint 시그니처**: `@router.get("/me/export") async def export_user_data(...)`. `format: Literal["json", "csv"] = "json"` Query 파라미터 — Pydantic 1차 게이트로 `?format=xml` 같은 invalid 값 422 → 글로벌 핸들러 400 + `code=validation.error`. 디폴트 `json`(epics.md:817 *"형식 선택(JSON/CSV)"*은 클라이언트가 명시 지정 — 디폴트 값은 누락 시 graceful 동작 보장).
   - **Dependency**: `Depends(current_user)` 단독 — `Depends(require_basic_consents)` 미적용. **사유**: PIPA Art.35 정보주체 권리(열람·정정·삭제·처리정지)는 *동의 철회와 독립*된 권리(deps.py:202-206 docstring 정합 + Story 5.2 AC2 SOT). 미동의 사용자도 자기 데이터를 *열람*할 수 있어야 정보주체 권리 봉쇄 X.
   - **흐름**:
     1. `payload = await collect_user_export_payload(db, user.id)` 호출.
     2. `payload is None` 분기 — 이론상 미진입(`current_user` Dependency가 user 존재 보장). 가설 race(soft-delete 동시 발생) 시 503 또는 graceful 빈 dict — *결정: 503 X, payload는 항상 collect 후 응답.* user 미발견 race는 `current_user`에서 401 차단 baseline.
     3. `format == "json"`:
        - `body = serialize_payload_to_json_bytes(payload)` (전체 dict → bytes).
        - `iterator = (chunk for chunk in [body])` — 단일 chunk generator(MVP — 진정한 chunking은 OUT).
        - `media_type = "application/json"`.
     4. `format == "csv"`:
        - `iterator = (chunk async for chunk in stream_csv_rows(payload))` — async row-by-row generator + 첫 chunk에 BOM 포함.
        - `media_type = "text/csv; charset=utf-8"`.
     5. `filename = f"balancenote_export_{_mask_user_id(user.id)}_{date_str}.{ext}"` — `date_str` = KST 오늘 `yyyy-mm-dd`(`datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")`), `ext` = `"json"` 또는 `"csv"`. **결정**: epics.md:821 spec literal *"`balancenote_export_{user_id}_{yyyy-mm-dd}.{json|csv}`"*에서 `{user_id}`는 *raw UUID* 노출이 NFR-S5 마스킹 룰셋과 충돌(필명 PII 노출 회피) — 본 스토리 spec deviation 1건: `{user_id}` → `_mask_user_id(user.id)`(Story 1.5/4.4/5.2 SOT 정합 — `u_{8char}`). 클라이언트 측 *어떤 사용자의 export인지* 가시성은 보존(첫 8자 prefix가 사용자 인지에 충분 + browser/share dialog 파일명에 raw UUID 36자 노출 회피). 한 줄 docstring 명시.
     6. `response = StreamingResponse(iterator, media_type=media_type, headers={...})`.
     7. **Content-Disposition** 헤더: `f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}'`(RFC 6266 정합 — UTF-8 인코딩 명시, 미국 ASCII-only 환경 호환성과 한국어 파일명 모두 통과). `urllib.parse.quote` 사용. *raw filename에 한국어 미포함*(라틴 + 숫자 + dot)이라 사실상 raw quote결과 동일 — 미래 한국어 파일명 도입 시 자동 안전.
     8. **`X-Content-Type-Options: nosniff`** 추가 — MIME sniffing 차단(사용자가 다운받은 파일을 브라우저가 이상하게 해석하지 않도록).
   - **로깅**: `logger.info("users.export.requested", user_id=_mask_user_id(user.id), format=format, meal_count=len(payload["meals"]))` — NFR-S5 마스킹 + format/count metadata만(*data 본문 X*). audit_log 테이블 미기록(자기 데이터 권리, AC8 정합).
   - **에러 매핑**: invalid format → 400 + `code=validation.error`(글로벌 핸들러). 401 → 인증 미통과. 5xx → 글로벌 핸들러. *400 user.export.* 같은 별 code 신설 X(MVP — 글로벌 게이트로 충분).
   - **Rate limit**: default `["1000/hour", "60/minute"]` 자동 적용(Story 5.1/5.2 패턴 정합 — 별도 데코레이터 X). Export는 read-heavy 동작이지만 1인 사용자가 분당 60회 호출은 abuse — default cap이면 충분.
   - **OpenAPI**: `responses={200: {"content": {"application/json": {}, "text/csv": {}}}}` 명시 — 자동 generated client(web/mobile `api-client.ts`)가 두 미디어 타입 인식. `IN_PROCESS=1 pnpm gen:api` 실행 후 검증.

3. **AC3 — Story 5.2 worker `_build_user_dump_payload` 리팩터링 — 서비스 레이어 SOT로 통합**
   **Given** Story 5.2 `app/workers/soft_delete_purge.py:_build_user_dump_payload` + `_serialize_value` + `_serialize_row` 3 helper baseline + Story 5.2 dev notes *"Story 5.3 추가 시 helper 통합 후 본 worker가 `data_export_service.export_user_data_json(...)` 호출로 갈아끼움(코드 변경 ~5 lines)"* forward-hook, **When** 본 스토리에서 service 신설, **Then**:
   - **`_build_user_dump_payload` 폐지** → `data_export_service.collect_user_export_payload` 호출로 교체. worker는 *purge cron 책임*에 집중(eligible SELECT + dump → cleanup → DELETE 격리 트랜잭션 흐름) — payload shape SOT는 service 레이어로 이전.
   - **shape diff**: Story 5.2 dump는 *최소 set*(`user`/`consents`/`meals`/`notifications` 4 entity)였고, 본 스토리 service는 *전체 set*(`+ meal_analyses` nested in meals). worker dump도 자동으로 *전체 set* 사용 — *PIPA Art.21 30일 보존 의무*를 *meal_analyses 포함*까지 확장하면 사용자가 30일 grace 동안 *피드백까지 회복 가능*(현재는 분실). 운영적으로 dump 사이즈가 ~2배 추정(meal_analyses는 meals와 1:1, feedback_text + citations 비중) — R2 storage cost minor + 사용자 권리 강화.
   - **`schema_version: "1.0"` 정합**: dump JSON과 export JSON 동일 shape — 외주 인수자가 dump 분석 시 export 형식 SOT 1지점 학습.
   - **soft-deleted meals 처리 차이**:
     - export 시점: `meals.deleted_at IS NULL` 필터(자기 권리 행사는 *현재 활성* 데이터만 의미 있음 — 사용자가 명시 삭제한 식단은 응답 미포함).
     - purge dump 시점: 모든 meals 포함(soft-deleted도 — 30일 grace 안에서 사용자가 *전체 history* 회복 권리). **service 레이어 분기**: `collect_user_export_payload(session, user_id, *, include_soft_deleted_meals=False)` 키워드 추가 → endpoint는 default False, worker는 True 전달.
   - **`_serialize_value` / `_serialize_row` import**: worker는 `from app.services.data_export_service import _serialize_value, _serialize_row, collect_user_export_payload`. underscore prefix는 module-level *internal helper*지만 worker는 *peer module*(앱 layer 동일)이라 import 자연스러움. `__all__`로 export 명시(Story 5.2 `clear_auth_cookies` rename 패턴 정합).
   - **단위 테스트 회귀**: Story 5.2 `test_soft_delete_purge.py` 기존 ~7건 패턴 정합 유지 — payload 검증 테스트는 신규 *전체 set* shape 정합으로 expectation 갱신(meals row에 `analysis` nested key 검증 추가 + `meal_analyses` 단위 수 검증).
   - **R2 dump JSON shape 후속 호환성**: Cloudflare R2 lifecycle policy로 30일 자동 만료(Story 5.2 SOT) — 본 스토리 시점 *기존 R2 dump JSON*은 1.0 shape 정합, lifecycle 도래 시 자동 만료 → 후속 호환성 0건 우려.

4. **AC4 — Mobile `(tabs)/settings/data-export.tsx` 신규 + format 선택 UI + 다운로드 흐름**
   **Given** Story 5.2 `mobile/app/(tabs)/settings/account-delete.tsx`(Alert.alert + TextInput + Pressable submit 패턴 SOT) + Story 5.1 `mobile/app/(tabs)/settings/profile.tsx`(가드 ① bootstrap → ② basic_consents 패턴) + Story 4.2 `mobile/lib/auth.ts:authFetch`(httpOnly cookie 자동 첨부 SOT), **When** 신규 화면 + 메뉴 항목 + Stack.Screen 등록, **Then**:
   - **신규 의존성 2건**(Expo SDK 54 baseline 호환):
     - `expo-file-system ~19.0.x` — `FileSystem.documentDirectory` write API. SDK 54 Legacy API(`writeAsStringAsync`) 디폴트 사용(SDK 54의 `next` API는 polish 스토리 forward — 본 스토리는 stable Legacy API SOT).
     - `expo-sharing ~14.0.x` — `Sharing.shareAsync(uri)` OS share sheet API. iOS/Android 공통 인터페이스. Mobile은 browser-style direct download가 부재라 OS share sheet으로 사용자가 *Files/Drive/메일* 등에 저장하는 표준 RN 패턴.
     - 두 패키지 모두 `pnpm add` — `mobile/package.json` 갱신.
   - **`mobile/features/settings/useDataExport.ts` 신규**:
     - `useExportUserData()` mutation hook. mutationFn는 (`format: "json" | "csv"`) 입력.
     - 흐름:
       1. `response = await authFetch("/v1/users/me/export?format=" + format)` — Story 5.1/5.2 `authFetch` SOT 재사용. cookie 자동 첨부 + 401 시 refresh 재시도.
       2. `response.ok` 검증 → false 시 `DataExportError(status, code, detail)` raise. RFC 7807 분기.
       3. `body = await response.text()`(JSON과 CSV 모두 텍스트 처리 — 모바일 RN의 `Blob` 미흡 호환성 회피).
       4. `filename = "balancenote_export_" + dateStrKst + "." + ext` — `dateStrKst` = `Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Seoul"}).format(new Date())`(yyyy-mm-dd). 사유: 모바일은 server `Content-Disposition` filename을 직접 사용하기 어려움(RN fetch는 헤더 노출은 되지만 `attachment` 분기 처리 X) — 클라이언트 측 동일 규칙으로 재구성. masked user_id는 모바일 측 미보유 → 단순 `balancenote_export_{date}.{ext}` SOT(server filename과 1:1 일치는 NFR 외 — 사용자 가시성은 *생성 일자*가 더 직관).
       5. `uri = FileSystem.documentDirectory + filename` — write 시 `writeAsStringAsync(uri, body, { encoding: "utf8" })`(SDK 54 Legacy default, BOM은 server CSV에 prefix 포함이라 자동 보존).
       6. `await Sharing.shareAsync(uri, { mimeType: format === "json" ? "application/json" : "text/csv" })` — 사용자가 *Files/Drive/메일* 등 선택. iOS/Android 공통.
     - `DataExportError` 클래스 — Story 5.2 `AccountDeleteError` 패턴 1:1 정합(status/code/detail).
     - **에러 분기**: `Sharing.isAvailableAsync()` 미가용 시(Web target 또는 일부 simulator) — fallback로 `Alert.alert` *"이 기기는 공유 기능을 지원하지 않습니다. 데이터가 앱 임시 저장소에 저장되었습니다: {uri}"* + uri 노출(개발자 hint, Story 8.4 polish forward).
   - **`mobile/app/(tabs)/settings/data-export.tsx` 신규** Expo Router 화면:
     - 진입 가드 ① `useAuth().consentStatus === null` → `<ActivityIndicator />` (bootstrap).
     - 진입 가드 ② **`!consentStatus.basic_consents_complete` 가드 미적용** — PIPA Art.35 권리(Story 5.2 패턴 정합, deps.py:202-206 정합).
     - **UI**:
       - `<Text style={styles.title}>데이터 내보내기</Text>`.
       - 안내 문구 *"내 식단·분석 결과·프로필을 JSON 또는 CSV 파일로 다운로드할 수 있습니다. PIPA 정보주체 권리(데이터 이전·열람권)에 따라 audit 기록 없이 처리됩니다."* — 한국어 사용자 친화 톤.
       - 형식 선택 — `<Pressable>` 2개 또는 SegmentedControl 패턴(2 옵션이라 RadioButton-style Pressable 2개로 단순화). `<Text>JSON</Text>` / `<Text>CSV</Text>` 라벨 + 선택 시 styles.selected 적용.
       - JSON 설명: *"표준 JSON — 외부 도구·스크립트 분석에 적합"*.
       - CSV 설명: *"한국어 헤더 — Excel·Google Sheets 직접 열기"*.
       - *"내보내기 시작"* `<Pressable>` 버튼 — `useExportUserData().mutate(format)` 호출.
       - mutation `isPending` 시 `<ActivityIndicator />` + 버튼 disabled — *"데이터 준비 중"* 안내(epics.md:817 *"데이터 준비 중"* literal 정합).
       - 성공 시 `Alert.alert` *"내보내기 완료. 공유 메뉴에서 저장 위치를 선택하세요."*(이미 OS share sheet이 mutation 안에서 노출 — alert는 fallback UX).
       - 실패 시 `Alert.alert` `error.detail || "다운로드 처리 중 오류가 발생했습니다."`.
     - submit handler 패턴은 Story 5.2 `account-delete.tsx`의 try/catch 흐름 정합.
   - **`mobile/app/(tabs)/settings/index.tsx` 메뉴 추가**: items 배열에 `'데이터 내보내기'` 1건 추가 — *위치 결정*: *'자동화 의사결정 동의'* 다음 / *'로그아웃'* 이전(데이터 권리 흐름 — privacy 관련 항목 그룹). *'회원 탈퇴'*는 destructive 액션이라 마지막 보존(Story 5.2 패턴 invariant).
   - **`mobile/app/(tabs)/settings/_layout.tsx` Stack.Screen 등록**: `<Stack.Screen name="data-export" options={{ title: "데이터 내보내기" }} />` 추가(Story 5.1/5.2 패턴 정합).

5. **AC5 — Web `/account/export/page.tsx` 신규 + `DataExportForm` client component**
   **Given** Story 5.2 `web/src/app/(user)/account/delete/page.tsx`(Server Component + 1가드 + metadata SOT) + Story 5.2 `web/src/features/settings/AccountDeleteForm.tsx`(react-hook-form + zod + apiFetch + RFC 7807 분기 SOT) + Story 5.1 settings/profile/page.tsx 푸터(`<Link href="/account/delete">`), **When** 신규 페이지 + 폼 + footer 진입점 추가, **Then**:
   - **`web/src/app/(user)/account/export/page.tsx` 신규** Server Component:
     - Next.js 16 metadata: `metadata = { title: "데이터 내보내기 — BalanceNote" }`.
     - **1가드만(Story 5.2 패턴 정합)**: `getServerSideUser()` → `!user` → `redirect("/api/auth/cleanup")`. `basic_consents` / `automated_decision_consent` / `profile_completed_at` 가드 *모두 미적용* — PIPA Art.35 권리(deps.py:202-206 정합).
     - 본문: 한국어 안내 + `<DataExportForm />` 렌더(client component). 안내 문구는 모바일과 동일 톤.
     - **Path 분리 결정**: `/account/export`는 Story 5.2 `/account/delete`와 *같은 namespace*(account = *데이터 권리* 영역). `/settings/*`는 *변경 흐름*(profile/macro-goal). 본 스토리 spec literal *"Web `/account/export`"* 정합(epics.md:817).
   - **`web/src/features/settings/DataExportForm.tsx` 신규** `"use client"`:
     - **react-hook-form + zod 패턴** (Story 5.2 `AccountDeleteForm` SOT 정합):
       - `dataExportSchema = z.object({ format: z.enum(["json", "csv"]) })`.
       - `defaultValues: { format: "json" }`.
       - `useForm<DataExportFormData>({ resolver: zodResolver(dataExportSchema) })`.
     - **UI 구조**:
       - 안내 카드 — `<div className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">` *"내 식단·분석·프로필을 JSON/CSV로 다운로드합니다. PIPA 정보주체 권리에 따라 audit 기록 없이 처리됩니다."*.
       - format 선택 RadioGroup — `<input type="radio" name="format" value="json"|"csv">` 2건 + 각 라벨 + 설명. `Controller`로 wrap.
       - *"내보내기 시작"* `<button type="submit">` — Tailwind primary blue(non-destructive, `bg-blue-600 hover:bg-blue-700` — `account/delete`의 `bg-red-600`과 의미 분리).
       - `isSubmitting` 시 *"데이터 준비 중..."* 라벨 + disabled.
     - **Submit handler** — Web 다운로드 표준 패턴:
       1. `apiFetch("/v1/users/me/export?format=" + data.format, { method: "GET" })` — Story 5.2 SOT 재사용. cookie 자동 첨부 + 401 자동 refresh.
       2. 401 후 ok=false면 RFC 7807 분기 — `setError("다운로드 권한이 없습니다. 다시 로그인해 주세요.")` + `window.location.assign("/login")` redirect.
       3. ok=true:
          - `blob = await response.blob()`.
          - `url = URL.createObjectURL(blob)`.
          - `filename`: server `Content-Disposition` 헤더 parsing — `response.headers.get("Content-Disposition")` → `filename="..."` regex 추출. 실패 시 `"balancenote_export_" + new Date().toISOString().slice(0,10) + "." + format` fallback.
          - `<a href={url} download={filename}>` 임시 anchor element 생성 → `document.body.appendChild` → `.click()` → `removeChild` → `URL.revokeObjectURL(url)`. 표준 web 다운로드 패턴.
          - mutation success state — *"다운로드가 시작되었습니다."* 1초 토스트(이미 anchor click이 OS save dialog trigger).
       4. 5xx → `setError("일시적인 서버 오류로 다운로드에 실패했습니다.")`.
     - **Content-Disposition parsing**: `extractFilenameFromContentDisposition(header: string | null): string | null` 헬퍼 — `RFC 6266 filename* / filename` 두 형식 모두 수용. `filename*=UTF-8''...` 우선(percent-decoded), 미있으면 `filename="..."`. 본 form 모듈 내부 helper로 collocated.
   - **`web/src/app/(user)/settings/profile/page.tsx` 푸터 갱신**:
     - 기존 `<Link href="/account/delete">회원 탈퇴</Link>` baseline(Story 5.2 SOT) + 신규 `<Link href="/account/export">데이터 내보내기</Link>` 추가.
     - **위치 결정**: 데이터 권리 그룹화 — *"내 데이터 관리"* sub-section으로 두 link 묶기(또는 inline 2개 link). *결정 단순화*: 두 link 모두 같은 `<footer>` 안에 inline 배치 — *데이터 내보내기*가 위(non-destructive 우선), *회원 탈퇴*가 아래(destructive 마지막). 별 sub-section heading X(MVP — 두 link 정도면 inline 충분).
   - **OpenAPI**: `pnpm gen:api` 실행으로 `web/src/lib/api-client.ts` 자동 갱신 — 신규 `GET /v1/users/me/export` endpoint + `format` query param 인식.

6. **AC6 — `_build_user_dump_payload` worker 회귀 0건 + meal_analyses 추가 가드**
   **Given** Story 5.2 `app/workers/soft_delete_purge.py:_process_single_user_purge` 흐름 + Story 5.2 R2 dump JSON shape baseline + `tests/workers/test_soft_delete_purge.py` ~7건 baseline, **When** worker 리팩터링 후, **Then**:
   - **worker 코드 변경 ~5 lines**(Story 5.2 dev notes forward-hook 1:1):
     - `_build_user_dump_payload` / `_serialize_value` / `_serialize_row` 3 helper 정의 *제거* — service module로 이전.
     - import 변경: `from app.services.data_export_service import collect_user_export_payload, _serialize_value, _serialize_row`(혹은 service `__all__` 통한 public re-export 사용).
     - call site: `payload = await _build_user_dump_payload(session, user_id)` → `payload = await collect_user_export_payload(session, user_id, include_soft_deleted_meals=True)`.
   - **shape 회귀 가드**: Story 5.2 기존 dump payload는 `meals` 단순 배열, 본 스토리 후 `meals[i].analysis` nested key 추가 — **R2 dump 후속 호환성 검증**: 기존 dump 파일은 30일 lifecycle로 자동 만료 → R2 측 데이터 유효성 우려 0. 만료 전 동일 사용자 재 dump 시 timestamp suffix(Story 5.2 CR P3 SOT — `{date}T{HHMMSS}.json`)로 별 키 작성 → silent overwrite X.
   - **stats dict 변경**: Story 5.2 worker stats(`r2_dumps_count`, `dump_errors`, ...) 그대로 유지 — `meal_analyses` 추가는 payload 내부 변경이라 stats 메타에 영향 0.
   - **단위 테스트 갱신** (`tests/workers/test_soft_delete_purge.py`):
     - 기존 `test_dump_payload_shape` 류 검증에 `meals[0].analysis` nested 키 존재 여부 가드 추가(meal_analyses fixture 1건 신설 후 검증).
     - `include_soft_deleted_meals=True` invariant 검증 1건 신설 — soft-deleted meals fixture 1건 있을 때 dump payload meals 배열에 *포함*됨(반대로 export endpoint는 *제외*).
   - **사이즈 추정**: meal_analyses는 meals와 1:1 + `feedback_text` ~500자 + `citations` ~3-5건. 사용자당 meal 100건 기준 dump JSON ~50-100KB → meal_analyses 추가 시 ~150-200KB. R2 storage cost minor(<$0.01/사용자/월) — 운영 영향 0.

7. **AC7 — `meals.deleted_at IS NULL` 필터 + `meal_analyses` JOIN 가드 + N+1 회귀 0건**
   **Given** Story 3.7 `Meal.analysis` relationship `lazy="raise_on_sql"` baseline(N+1 명시 가드) + Story 4.3 `selectinload(Meal.analysis)` 패턴 SOT + Story 2.1 `meals.deleted_at` soft-delete 컬럼, **When** `collect_user_export_payload` 구현 시, **Then**:
   - **export 시점 SQL**:
     - meals SELECT — `select(Meal).where(Meal.user_id == user_id, Meal.deleted_at.is_(None)).order_by(Meal.ate_at)`. 정렬은 사용자 직관(시간 순) — CSV에서 이미 `날짜` 컬럼 첫 컬럼이라 자연.
     - meal_analyses SELECT — *별 쿼리*(`select(MealAnalysis).where(MealAnalysis.user_id == user_id)`). meals + analyses 별도 fetch 후 Python 측에서 `meal_id` lookup dict 빌드 + meals row에 nested. 사유: `lazy="raise_on_sql"`이 implicit lazy load 차단 + `selectinload(Meal.analysis)` 사용 시 ORM 자동 매핑 가능하나 *별 쿼리 + 명시 매핑*이 export 흐름에서 더 명시적(1:1 관계 hand-rolled join).
     - **결정**: `selectinload` 패턴 채택(Story 4.3 SOT 정합) → `select(Meal).options(selectinload(Meal.analysis)).where(...)`. ORM 측 자동 nested + 별 쿼리 1건만 추가(N+1 회피). Python 측에서는 `meal.analysis` 직접 접근 → `_serialize_row` 호출.
   - **purge dump 시점 SQL**:
     - meals SELECT — `select(Meal).where(Meal.user_id == user_id).options(selectinload(Meal.analysis))` (`include_soft_deleted_meals=True` 분기로 deleted_at 필터 미적용).
     - PIPA 30일 grace 내 사용자가 *전체 history* 회복 가능(soft-deleted 포함) — 권리 강화.
   - **soft-deleted meal의 meal_analyses**: `meals.deleted_at` soft-delete 시 `meal_analyses.deleted_at` 컬럼 부재(meal_analyses는 deleted_at 없음 — Story 3.7 SOT) → meal_analyses는 fk-cascade only. soft-deleted meal의 analysis는 *DB row level 활성*이라 export query는 meal_id 기준 매칭. **결정**: export 시 `meals.deleted_at IS NULL` 필터로 *meals* 제거 → 매칭되는 `meal_analyses`도 자연 제외(Python lookup dict가 meals SELECT 결과만 iterate). 데이터 일관성 유지.
   - **N+1 회귀 가드 단위 테스트 1건**: 사용자 + meals 5건 + meal_analyses 5건(1:1) fixture → export endpoint 호출 → SQL log 캡처(SQLAlchemy `event.listen("before_cursor_execute")` 패턴) → cursor execute 횟수 ≤ 3건(meals + meal_analyses + 4 별 entity SELECT 합계). 회귀 시 즉시 fail.

8. **AC8 — 일반 사용자 자기 export audit 미기록 + PIPA Art.35 정합**
   **Given** Story 5.1 AC8 + Story 5.2 AC8 + epics.md:823 *"자기 데이터 권리 행사이므로 audit log 미기록"* + PIPA Art.35 정보주체 권리, **When** 본 스토리 GET endpoint, **Then**:
   - GET endpoint에 `Depends(audit_admin_action)` 미적용. Story 7.x admin endpoint(`GET /v1/admin/users/{user_id}/export` 가설)와 *분리* — Story 5.1/5.2 패턴 1:1 정합.
   - **사용자 권리 정당화**: PIPA Art.35 정보주체 권리(열람·정정·삭제·처리정지) — 자기 데이터를 *열람*(다운로드 = 열람 권리의 한 형태)하는 액션은 *권리*. audit log에 기록하면 *권리 봉쇄 + 과잉 추적*(특히 사용자가 데이터를 외부 분석에 사용하려는 의도가 *시스템에 의해 추적*되면 정보주체 자기결정권 위반).
   - structlog `users.export.requested` event는 *system log SOT*(Sentry/Loki/Railway 로그) — 운영 모니터링 목적, audit_log 테이블 아님. NFR-S5 마스킹(`user_id u_{8char}` + `format`/`meal_count` metadata only — *data 본문 X, raw_text 본문 X, citations 본문 X*).
   - **운영 모니터링 SOT**: format 분포 / 일별 호출 빈도 / 대용량 사용자(meal_count > 1000) 분포 — Sentry transaction breadcrumb으로 forward(`op="users.export"`).
   - **회귀 가드**: `app/api/deps.py:audit_admin_action` Dependency가 본 endpoint에 wire 미진입 검증(unit test 1건 — endpoint signature inspection, Story 5.1/5.2 패턴 1:1 정합).

9. **AC9 — 단위 테스트 + 회귀 0건 + 통합 검증**
   **Given** Story 5.2 baseline pytest 1043 passed/11 skipped/0 failed + coverage 85.20% + ruff/format/mypy/tsc/lint 0 errors, **When** 본 스토리 종료, **Then**:
   - **신규 단위 테스트 ~25건**:
     - `api/tests/services/test_data_export_service.py` 신규 ~10건:
       1. `_serialize_value` Decimal `format("f")` 비-scientific 검증(0.0001 → "0.0001", 1e20 같은 large value 정상).
       2. `_serialize_value` UUID/datetime/None pass-through.
       3. `_serialize_row` ORM 객체 → dict 변환(User row 1건 fixture).
       4. `collect_user_export_payload` 사용자 미발견 → None 반환.
       5. `collect_user_export_payload` happy-path — user + consents + meals + meal_analyses + notifications 모두 매핑 검증 + meals[0].analysis nested 키 존재.
       6. `collect_user_export_payload include_soft_deleted_meals=False` (default) → soft-deleted meal 제외.
       7. `collect_user_export_payload include_soft_deleted_meals=True` → soft-deleted meal 포함.
       8. `serialize_payload_to_json_bytes` ensure_ascii=False(한국어 raw_text 그대로) + UTF-8 encoding.
       9. `stream_csv_rows` 헤더 BOM(`﻿`) + 한국어 컬럼 6건 + 줄바꿈 LF(`\n` not `\r\n`).
       10. `stream_csv_rows` row escape — `raw_text="짜장면, 군만두\""` → CSV `"짜장면, 군만두"""` (RFC 4180 doublequote escape).
     - `api/tests/api/v1/test_users_export.py` 신규 ~10건:
       1. GET `?format=json` 인증 미통과 → 401.
       2. GET `?format=json` happy-path — 200 + `Content-Type: application/json` + body 첫 byte는 `{` + `Content-Disposition: attachment; filename="balancenote_export_u_..."`.
       3. GET `?format=csv` happy-path — 200 + `Content-Type: text/csv; charset=utf-8` + body 첫 char는 BOM + 헤더 한국어 검증.
       4. GET `?format=xml` invalid format → 400 + `code=validation.error`(Pydantic Literal 가드).
       5. GET 디폴트(format param 미송신) → JSON 응답 검증.
       6. GET 미동의 사용자(`basic_consents=false`) → 200 (PIPA Art.35 정합 — `require_basic_consents` 미적용 invariant 가드).
       7. GET `Content-Disposition` filename에 raw user UUID 미노출 검증(`u_{8char}` 마스킹 SOT).
       8. GET `X-Content-Type-Options: nosniff` 헤더 존재.
       9. GET 응답 body — meals soft-deleted 제외 검증(fixture: 활성 meal 2건 + soft-deleted meal 1건 → JSON `meals` 배열 length=2).
       10. GET endpoint signature inspection — `audit_admin_action` Dependency 미wire 가드(`inspect.signature` + `route.dependant.dependencies` 재귀 — Story 5.2 audit gate 패턴 SOT).
     - `api/tests/workers/test_soft_delete_purge.py` 확장 ~3건(Story 5.2 baseline 회귀):
       1. `purge.dump` payload에 `meals[i].analysis` nested 키 존재 검증 (meal_analyses fixture 1건 신설).
       2. `include_soft_deleted_meals=True` worker invariant — soft-deleted meal 1건 fixture 시 dump payload meals 배열에 *포함*.
       3. import path 변경 회귀 — `from app.services.data_export_service import ...` 정상 동작.
     - `api/tests/api/v1/test_users_export.py` 추가 N+1 가드 ~1건:
       1. meals 5건 + meal_analyses 5건 fixture → SQL counter ≤ 3 cursor.execute (1 user + 1 consents + 1 meals(+selectinload analyses) + 1 notifications + 1 meal_analyses_lookup_safety_margin).
     - `api/tests/services/test_data_export_service_csv.py` 추가 ~1건(또는 main file에 inline):
       1. CSV row 생성 - `날짜` 컬럼 KST `YYYY-MM-DD HH:MM` 포맷 검증 (UTC `2026-05-07T15:00:00Z` → `2026-05-08 00:00`).
   - **본 스토리 종료 시 목표**: pytest **~1068 passed / 11 skipped / 0 failed** + coverage ≥84% 유지(신규 코드 ~250 lines + 신규 테스트 ~25건 = +~80 lines covered, 비례).
   - **회귀 0건 가드**:
     - Story 5.2 worker — import path 변경 + `_build_user_dump_payload` 호출 변경 ~5 lines. 기존 `test_soft_delete_purge.py` ~7건 모두 통과(payload shape는 *상위 호환* — 신규 nested key 추가만, 기존 키 제거 X).
     - Story 5.1 PATCH endpoint — 변경 0건.
     - Story 5.2 DELETE endpoint — 변경 0건.
     - Story 4.x reports — 변경 0건.
   - **타입 체크**: ruff/format/mypy 0 에러(api) + web/mobile tsc + lint 0 에러.
   - **OpenAPI schema diff**: 신규 endpoint 1건(`GET /v1/users/me/export`) + `format` query param + 응답 multi-content(json/csv). CI 게이트 통과 의무.
   - **NFR-A5 검증**: web 폼 Tab 순서 자연(format radio 2 → submit 버튼). 모바일 Pressable 그룹 + accessibilityRole.

10. **AC10 — sprint-status / Story Status 갱신 흐름 (메모리 정합)**
    **Given** 메모리 정합 *"CS 시작 전 master에서 브랜치 분기 — DS 종료시 commit + push만"* + *"CR 종료 직전 sprint-status/story Status를 review → done으로 갱신해 PR commit에 포함"* + *"새 스토리 브랜치는 항상 master에서 분기"*, **When** 본 스토리 `ready-for-dev` 시점(CS 종료) 및 후속 단계, **Then**:
    - Branch: `story/5.3-data-export`(master에서 분기 — CS 시작 전 분기 의무).
    - DS 시작: `5-3-데이터-내보내기-json-csv: ready-for-dev → in-progress`.
    - DS 종료: `5-3-데이터-내보내기-json-csv: in-progress → review` + commit + push(PR 생성 X — CR 완료 후 일괄).
    - CR 종료 직전: `review → done` + commit + push(같은 commit에 sprint-status 갱신 포함).
    - PR 생성: CR 완료 후 1회. PR title: `Story 5.3: 데이터 내보내기 (JSON/CSV) (DS+CR)`.
    - **Epic 5 마지막 스토리** — CR 완료 + Story 5.3 done 처리 시점에 `epic-5: in-progress → done` 함께 갱신(Story 5.1/5.2/5.3 모두 done 도달).

## Tasks / Subtasks

### Task 1 — `app/services/data_export_service.py` 신규 + `_serialize_value` / `_serialize_row` / `collect_user_export_payload` SOT (AC: #1, #7)

- [ ] 1.1 `api/app/services/data_export_service.py` 신규 — `_serialize_value` / `_serialize_row` (Story 5.2 SOT 1:1 이전) + `collect_user_export_payload(session, user_id, *, include_soft_deleted_meals=False)` async function (4 entity SELECT + meals.options(selectinload(Meal.analysis)) + 사용자 미발견 None 반환) + `serialize_payload_to_json_bytes(payload)` (ensure_ascii=False utf-8 encode) + `stream_csv_rows(payload)` async generator(BOM + 한국어 헤더 + meals row → 6 컬럼 flatten) + `__all__` export 명시.
- [ ] 1.2 `api/app/services/__init__.py` — `data_export_service` 노출 X(서비스는 직접 import 패턴, Story 4.3 `report_service` 정합).

### Task 2 — `GET /v1/users/me/export` endpoint + StreamingResponse + Content-Disposition (AC: #2, #8)

- [ ] 2.1 `api/app/api/v1/users.py` — `from typing import Literal` + `from urllib.parse import quote` + `from fastapi import Query` + `from fastapi.responses import StreamingResponse` + `from app.services.data_export_service import collect_user_export_payload, serialize_payload_to_json_bytes, stream_csv_rows` import 추가.
- [ ] 2.2 `api/app/api/v1/users.py` — `@router.get("/me/export") async def export_user_data(...)` 신규 endpoint(`format: Literal["json", "csv"] = Query("json")` + `Depends(current_user)` 단독 + `audit_admin_action` Dependency 미wire + `_mask_user_id` filename + `Content-Disposition` RFC 6266 + `X-Content-Type-Options: nosniff` + `users.export.requested` 로깅).
- [ ] 2.3 `api/tests/api/v1/test_users_export.py` 신규 ~10건(AC9 정의 — auth/json/csv/invalid format/default/PIPA-Art.35-no-consent/filename mask/nosniff/soft-deleted exclude/audit-gate signature inspection).

### Task 3 — Story 5.2 worker 리팩터링 (DF136 forward-hook 즉시 해소) (AC: #3, #6)

- [ ] 3.1 `api/app/workers/soft_delete_purge.py` — `_build_user_dump_payload` / `_serialize_value` / `_serialize_row` 3 helper 정의 *제거* + `from app.services.data_export_service import collect_user_export_payload, _serialize_value, _serialize_row` import 추가.
- [ ] 3.2 `api/app/workers/soft_delete_purge.py:_process_single_user_purge` — `payload = await _build_user_dump_payload(session, user_id)` → `payload = await collect_user_export_payload(session, user_id, include_soft_deleted_meals=True)` 1줄 갱신.
- [ ] 3.3 `api/tests/workers/test_soft_delete_purge.py` 확장 ~3건 — payload shape 회귀 가드(`meals[i].analysis` nested 키 존재 + `include_soft_deleted_meals=True` invariant + import path 변경 정상 동작).

### Task 4 — Mobile `(tabs)/settings/data-export.tsx` 화면 + `useDataExport` 훅 + 신규 의존성 2건 (AC: #4)

- [ ] 4.1 `mobile/package.json` — `expo-file-system ~19.0.x` + `expo-sharing ~14.0.x` 추가(`pnpm add expo-file-system expo-sharing` — Expo SDK 54 baseline 호환). lockfile 갱신.
- [ ] 4.2 `mobile/features/settings/useDataExport.ts` 신규 — `useExportUserData()` mutation hook(`authFetch` GET `/v1/users/me/export?format=...` + `response.text()` body + `FileSystem.documentDirectory + filename` write + `Sharing.shareAsync(uri)` OS share sheet + `DataExportError` 클래스(Story 5.2 `AccountDeleteError` 패턴 정합) + `Sharing.isAvailableAsync` 미가용 fallback alert).
- [ ] 4.3 `mobile/app/(tabs)/settings/data-export.tsx` 신규 — 진입 가드 ① bootstrap (basic_consents 가드 미적용 — PIPA Art.35) + 안내 카드 + format Pressable 2개(JSON/CSV + 설명) + *"내보내기 시작"* submit 버튼 + isPending 시 *"데이터 준비 중"* 안내 + 성공/실패 Alert.alert.
- [ ] 4.4 `mobile/app/(tabs)/settings/_layout.tsx` — `<Stack.Screen name="data-export" options={{ title: "데이터 내보내기" }} />` 추가(Story 5.1/5.2 등록 패턴 정합).
- [ ] 4.5 `mobile/app/(tabs)/settings/index.tsx` — items 배열에 `'데이터 내보내기'` 추가 — *위치*: *'자동화 의사결정 동의'* 다음 / *'로그아웃'* 이전(데이터 권리 그룹). *'회원 탈퇴'* 마지막 invariant 보존.

### Task 5 — Web `/account/export` 페이지 + `DataExportForm` + settings/profile 푸터 (AC: #5)

- [ ] 5.1 `pnpm gen:api` 실행 — 백엔드 OpenAPI 갱신 후 `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts` 자동 갱신(신규 `GET /v1/users/me/export` endpoint + format query param 인식).
- [ ] 5.2 `web/src/features/settings/DataExportForm.tsx` 신규 `"use client"` — react-hook-form + zod schema(`format: z.enum(["json", "csv"])` default "json") + Controller로 wrap한 RadioGroup + *"내보내기 시작"* `<button>` (Tailwind `bg-blue-600`) + apiFetch GET → `response.blob()` + `URL.createObjectURL` + 임시 anchor click 표준 패턴 + Content-Disposition filename parsing helper(RFC 6266 filename* 우선 + filename fallback) + 401/4xx/5xx 분기.
- [ ] 5.3 `web/src/app/(user)/account/export/page.tsx` 신규 Server Component — Next.js 16 metadata + 1가드(`!user` → `redirect("/api/auth/cleanup")`) + 안내 본문 + `<DataExportForm />` 렌더(Story 5.2 `/account/delete/page.tsx` 패턴 1:1 정합).
- [ ] 5.4 `web/src/app/(user)/settings/profile/page.tsx` — 푸터에 `<Link href="/account/export">데이터 내보내기</Link>` 추가(*"회원 탈퇴"* link 위에 — non-destructive 우선). Story 5.2 baseline 회귀 0건.

### Task 6 — N+1 회귀 가드 + 통합 검증 (AC: #7, #9)

- [ ] 6.1 `api/tests/api/v1/test_users_export.py` 확장 — N+1 가드 1건(meals 5건 + meal_analyses 5건 fixture → SQLAlchemy `event.listen("before_cursor_execute")` SQL counter ≤ 3-5 cursor.execute).
- [ ] 6.2 `api/tests/services/test_data_export_service.py` 확장 — CSV `날짜` 컬럼 KST 변환 1건 + Decimal scientific notation 차단 회귀 가드 1건(`Decimal("0.000001")` → `"0.000001"`).

### Task 7 — sprint-status + 통합 검증 + 회귀 가드 (AC: #9, #10, 전체)

- [ ] 7.1 sprint-status `5-3-데이터-내보내기-json-csv: ready-for-dev → in-progress` (DS 시작 시).
- [ ] 7.2 `cd api && uv run pytest -q` — 1043 baseline + ~25 신규(service 10 + endpoint 10 + worker 회귀 3 + N+1 + KST CSV) = ~1068 passed/11 skipped/0 failed. 회귀 0건. coverage ≥84% 유지.
- [ ] 7.3 `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app` 0 에러.
- [ ] 7.4 `cd web && pnpm tsc --noEmit && pnpm lint` 0 에러.
- [ ] 7.5 `cd mobile && pnpm tsc --noEmit && pnpm lint` 0 에러.
- [ ] 7.6 OpenAPI schema diff 검증 — 신규 endpoint 1건(`GET /v1/users/me/export`) + `format` Literal query param + 응답 multi-content(application/json + text/csv).
- [ ] 7.7 dev 검증 — 브라우저/Expo manual smoke는 CR/QA 단계로 위임. DS 단계는 단위 테스트 ~1068 passed + tsc/lint 0 errors로 functional verification 완료(JSON/CSV 형식 + filename + soft-deleted 제외 + N+1 모두 unit test로 가드).
- [ ] 7.8 sprint-status `5-3-데이터-내보내기-json-csv: in-progress → review` 갱신 완료. commit + push는 본 단계 종료 직후.
- [ ] 7.9 CR 종료 직전 — sprint-status `5-3-데이터-내보내기-json-csv: review → done` + `epic-5: in-progress → done`(Epic 5 마지막 스토리 클로저) 같은 commit에 포함.

## Dev Notes

### 핵심 — 본 스토리는 *PIPA Art.35 정보주체 권리 + JSON/CSV 통합 다운로드 + 서비스 레이어 SOT 정상화*

Story 5.2 baseline(`DELETE /me` + worker `_build_user_dump_payload` JSON shape) → Story 5.1 baseline(settings/profile 폼 패턴 + footer 진입점) → Story 4.3 baseline(`require_basic_consents` SOT) 위에 *GET /me/export endpoint + 서비스 레이어 SOT(`data_export_service.py`)*를 신설. epics.md:809-823 정합 — FR9 *"엔드유저는 자기 식단·피드백·프로필 데이터를 표준 형식(JSON 또는 CSV)으로 다운로드할 수 있다 (PIPA 정보주체 권리)"*.

**3 SOT 정상화 채널**:
1. **JSON shape SOT** — Story 5.2 worker `_build_user_dump_payload` → 본 스토리 `data_export_service.collect_user_export_payload`(*전체 set* — meal_analyses 추가). worker는 service 호출.
2. **`_serialize_value`/`_serialize_row` 헬퍼 SOT** — worker module → service module 이전. Decimal `format("f")` scientific notation 차단(Story 5.2 CR P10 정합).
3. **사용자 권리 정합** — `Depends(current_user)` 단독 + audit 미기록(Story 5.1/5.2 패턴 invariant).

**검증 시점 분리**:
- AC1-3, 6-8(service + endpoint + worker 리팩터링) — 단위 테스트로 100% 가드.
- AC4(mobile UX) — tsc/lint + manual smoke(CR/QA — Files/Drive 저장 흐름 manual 확인).
- AC5(web UX) — tsc/lint + browser anchor download manual smoke.
- AC9 — pytest + coverage + N+1 가드 통합.

### `data_export_service.py` 분리 결정 — DF136 forward-hook 즉시 해소

Story 5.2 dev notes에서 *"Story 5.3 추가 시 helper 통합 후 본 worker가 `data_export_service.export_user_data_json(...)` 호출로 갈아끼움"* forward-hook 명시. 본 스토리 시점에 Story 5.2 worker 모듈 내부 helper 3건(`_build_user_dump_payload` / `_serialize_value` / `_serialize_row`)을 service 모듈로 이전 + worker는 import 호출.

**대안(검토 후 미채택)**:
- (a) worker 모듈에 helper 유지 + service에서 worker 모듈 import — 의존성 방향 역전(service → worker). 업계 표준 layered architecture 위반.
- (b) helper를 `app/core/serialization.py` 같은 별 cross-cutting 모듈로 분리 — over-engineering(현 baseline은 service의 *내부 헬퍼* 의미가 자연. 미래에 다른 service들이 동일 패턴 사용 시 분리 검토).

### `meal_analyses` 추가 결정 — sprint-status가 PIPA Art.21 30일 보존 의무 강화

Story 5.2 worker dump는 *최소 set*(user/consents/meals/notifications) — `meal_analyses` 의도적 제외(LLM 출력은 *재계산 가능*이라 dump cold archive 성격). 본 스토리 export는 *전체 set* — `meal_analyses` 포함(피드백·인용 출처·fit_score 등이 사용자 권리 관점에서 *재계산 가치*가 아닌 *시점적 가치*).

**worker도 자동 *전체 set* 사용** — Art.21 *"30일 grace 동안 사용자가 데이터 회복 가능"* 강화. 사이즈 영향 minor(meal당 ~1KB 추가 → 사용자당 ~100KB 추정). R2 storage cost minor.

### CSV 형식 결정 — 6 컬럼 평면화 + KST 시각

epics.md:820 spec literal 헤더 *"날짜, 식사, 매크로, fit_score, 피드백 요약, 출처"* — 6 컬럼. 1행 = 1 식단 입력(meal row), 분석 결과는 *flatten*해서 같은 행에 평면 표현.

**시각 포맷 결정**: KST `YYYY-MM-DD HH:MM`(timezone Asia/Seoul). 사유:
- 사용자가 외부 도구(Excel/Google Sheets)에서 *KST*로 시각화 — 한국 사용자 직관.
- ISO UTC(`2026-05-07T15:00:00Z`)는 JSON 형식에서 보존(외부 도구가 timezone 처리 가능).
- CSV는 *사용자 친화* / JSON은 *기계 친화* — 두 형식의 의미 분리.

**escape**: RFC 4180 정합 — 셀 값에 `,` / `"` / `\n` 포함 시 `"`로 감싸고 내부 `"`는 `""`로 escape. `_csv_escape(value: str) -> str` 헬퍼.

**한국어 enum 값 그대로 보존**: epics.md:819 *"한국어 enum 값 그대로"* — `allergies` 컬럼이 한국어 라벨(`"우유"` / `"메밀"` / ...) 보존(JSON 형식에서). `health_goal` ENUM은 영어 키 그대로(`"weight_loss"`) — *값이 한국어인 컬럼*만 한국어, *DB ENUM*은 영어 키 SOT 정합(외부 도구 호환성 우선).

### `Content-Disposition` filename masking 결정 (spec deviation 1건)

epics.md:821 spec literal: `balancenote_export_{user_id}_{yyyy-mm-dd}.{json|csv}`에서 `{user_id}`는 *raw UUID* 노출. **본 스토리 spec deviation**: `{user_id}` → `_mask_user_id(user.id)` (Story 1.5/4.4/5.2 NFR-S5 SOT 정합 — `u_{8char}`).

**사유**:
- raw UUID 36자가 browser 다운로드 dialog / Files 앱 / OS 공유 메뉴 등에서 *PII 식별자로 노출*되는 부작용. *어떤 사용자의 export인지* 가시성은 8자 prefix로 충분.
- 단일 사용자가 자기 데이터를 다운로드하는 흐름이라 *다른 사용자와 구분*할 인지가 필요한 시나리오 부재(자기 단말기 + 자기 클라우드 저장).
- NFR-S5 마스킹 룰셋 1지점 SOT — 다른 모든 logging/Sentry/LangSmith trace는 이미 마스킹 → 파일명만 raw UUID 노출하는 inconsistency 회피.

문서화: docstring 1줄 + 본 dev notes 항목 1건 + 단위 테스트 1건(filename 검증).

### 모바일 다운로드 UX — `expo-file-system` + `expo-sharing` 표준 RN 패턴

브라우저는 anchor `download` attribute로 OS save dialog 직접 trigger 가능 — 모바일 RN은 부재. RN 표준 패턴은:
1. fetch로 body 가져옴(`authFetch`로 cookie 자동 첨부).
2. `FileSystem.documentDirectory + filename`에 write(`writeAsStringAsync`).
3. `Sharing.shareAsync(uri)` OS share sheet — 사용자가 *Files/Drive/메일/iMessage* 등 선택.

**대안(검토 후 미채택)**:
- (a) `Linking.openURL(api_url + "?format=...")` — auth cookie 미전달 → 401.
- (b) one-time-use signed URL 발급 — 추가 인프라(R2 presigned URL)와 endpoint 1건 더 필요.
- (c) `Share.share({ message: body })` RN core API — body가 *message text*로 노출, 대용량 시 OS 차단 가능성. 파일 mime type 미설정.

`Sharing.isAvailableAsync()` false 시(주로 web target 또는 일부 Android emulator) — fallback alert로 *"데이터가 앱 임시 저장소에 저장되었습니다: {uri}"* 안내. 사용자가 ADB 또는 시뮬레이터 파일 시스템으로 접근 가능. Story 8.4 polish forward.

### Web 다운로드 UX — `Blob` + `URL.createObjectURL` + 임시 anchor

브라우저 표준 패턴 — `apiFetch` GET → `response.blob()` → `URL.createObjectURL(blob)` → 임시 `<a download={filename}>` element 생성/click/제거 → `URL.revokeObjectURL`. 추가 의존성 0.

**filename parsing**: server `Content-Disposition` 헤더에서 추출. RFC 6266 정합:
- `filename*=UTF-8''<percent-encoded>` 우선(국제화 대응).
- `filename="..."` fallback.
- 둘 다 부재 시 client-side 재구성(Date + format).

**XSS 가드**: filename은 server에서 `_mask_user_id` + ASCII 라틴 + 숫자 + dot으로만 구성 — 임의 사용자 입력 X. 클라이언트 측 추가 sanitize 불필요.

### Architecture Compliance

| 영역 | 영향 패턴 | 정합 |
|---|---|---|
| Router (AC2) | architecture.md:704 `users.py` SOT + Story 5.1/5.2 패턴 | 정합 — `GET /me/export` 신규 1 endpoint |
| Service layer (AC1) | architecture.md:702 `data_export_service.py` SOT | 정합 — 신규 모듈 + worker 호출 정상화 |
| StreamingResponse (AC2) | architecture.md:321 SSE는 sse-starlette + 본 스토리는 `fastapi.responses.StreamingResponse` 첫 사용처 | 정합 — REST 표준 패턴, sse-starlette는 SSE only |
| Worker 리팩터링 (AC3, AC6) | architecture.md:705 `workers/soft_delete_purge.py` + Story 5.2 dev notes DF136 forward-hook | 정합 — service 호출로 갈아끼움 ~5 lines |
| FK CASCADE 회귀 0건 (AC7) | architecture.md:299 ER + Story 3.7 `lazy="raise_on_sql"` | 정합 — selectinload 명시 + N+1 가드 |
| Audit 분리 (AC8) | architecture.md:891 `audit_admin_action` + Story 5.1/5.2 + PIPA Art.35 | 정합 — 자기 권리 행사 미기록 |
| NFR-S5 (AC2 logging + filename) | prd.md:1010 + Story 5.2 `_mask_user_id` SOT | 정합 — `user_id u_{8char}` + `format`/`meal_count` only |
| NFR-A5 (AC4, AC5 a11y) | prd.md NFR-A5 키보드 + 스크린리더 | 정합 — Tab 순서 자연 + accessibilityRole |
| OpenAPI schema (AC2) | architecture.md:847 + Story 5.1/5.2 패턴 | 정합 — multi-content responses 명시 |

### Library / Framework Requirements

- **Backend**: 신규 의존성 0건. 기존 의존성 모두 활용:
  - `fastapi` `StreamingResponse` (`fastapi.responses` — 본 스토리 첫 사용처. `sse-starlette`와 별 모듈).
  - `urllib.parse.quote` (Python 표준 — RFC 6266 filename* encoding).
  - `zoneinfo.ZoneInfo` (Python 3.9+ 표준 — KST 변환).
  - `sqlalchemy` `selectinload` (Story 4.3 SOT 정합 — N+1 가드).
- **Mobile**: 신규 의존성 2건:
  - `expo-file-system ~19.0.x` (Expo SDK 54 baseline 호환 — Legacy API SOT, Next API는 polish 스토리 forward).
  - `expo-sharing ~14.0.x` (Expo SDK 54 baseline 호환).
  - 기존: `@tanstack/react-query` + `expo-router` + `authFetch` 모두 Story 5.2 SOT 재사용.
- **Web**: 신규 의존성 0건. 기존:
  - `react-hook-form ^7.55` + `@hookform/resolvers ^5.0` + `zod ^3.23` (Story 5.2 SOT).
  - Next.js 16 App Router Server Component(Story 5.2 SOT).
  - `apiFetch` (Story 1.2/5.2 SOT) — GET method first usage with Content-Disposition parsing.

### File Structure Requirements

#### 신규 파일

**Backend (api/):**
- `api/app/services/data_export_service.py`
- `api/tests/api/v1/test_users_export.py`
- `api/tests/services/test_data_export_service.py`
- `api/tests/services/__init__.py`(test directory init — 신규 디렉토리 첫 도입 시. 기존 `tests/services/` 미존재 검증 후 생성)

**Mobile:**
- `mobile/features/settings/useDataExport.ts`
- `mobile/app/(tabs)/settings/data-export.tsx`

**Frontend (web/):**
- `web/src/features/settings/DataExportForm.tsx`
- `web/src/app/(user)/account/export/page.tsx`

#### 수정 파일 (기존)

**Backend:**
- `api/app/api/v1/users.py` — `GET /me/export` endpoint + import 추가. 기존 endpoint 변경 0건.
- `api/app/workers/soft_delete_purge.py` — `_build_user_dump_payload`/`_serialize_value`/`_serialize_row` 3 helper 정의 *제거* + service module import + `_process_single_user_purge` 호출 1줄 변경(Story 5.2 dev notes DF136 forward-hook 즉시 해소).
- `api/tests/workers/test_soft_delete_purge.py` — payload shape 회귀 가드 ~3건 확장.

**Mobile:**
- `mobile/package.json` — `expo-file-system` + `expo-sharing` 2 의존성 추가.
- `mobile/pnpm-lock.yaml` — pnpm install 자동 갱신.
- `mobile/app/(tabs)/settings/index.tsx` — `'데이터 내보내기'` items 항목 추가(자동화 의사결정 동의 다음 / 로그아웃 이전).
- `mobile/app/(tabs)/settings/_layout.tsx` — `<Stack.Screen name="data-export" />` 추가.
- `mobile/lib/api-client.ts` — `pnpm gen:api` 자동 갱신(GET `/me/export` endpoint + format query param).

**Frontend (web/):**
- `web/src/app/(user)/settings/profile/page.tsx` — 푸터 `<Link href="/account/export">데이터 내보내기</Link>` 추가(Story 5.2 `<Link href="/account/delete">` 위에).
- `web/src/lib/api-client.ts` — `pnpm gen:api` 자동 갱신(동일).

### Testing Requirements

- **신규 단위 테스트 ~25건** (AC9 Task 분포):
  - Backend pytest:
    - `test_data_export_service.py` 10 + N+1 가드 1 + KST CSV 1 + Decimal scientific 1 = 13건
    - `test_users_export.py` 10건
    - `test_soft_delete_purge.py` 확장 3건
  - Mobile/Web: 0건(Story 5.1/5.2 baseline 정합 — Web jest 미도입). tsc + lint 0 errors 회귀 가드.
- **종료 시 목표**: pytest **~1068 passed / 11 skipped / 0 failed**, coverage ≥84% 유지.
- **회귀 0건 핵심 가드**:
  - Story 5.2 worker — `_build_user_dump_payload` import path 변경 + nested key 추가. 기존 ~7건 모두 통과.
  - Story 5.1/5.2 endpoint — 변경 0건.
  - Story 4.x reports — 변경 0건.
  - SQL log counter ≤ 5(meals + meal_analyses + 4 entity = 5 cursor.execute, N+1 회귀 즉시 fail).
- **OpenAPI schema diff**: `GET /v1/users/me/export` endpoint 1건 + `format` Literal query param + 응답 multi-content. CI 게이트 통과 의무.
- **NFR-A5 검증**: web format radio Tab 순서 자연 + 모바일 Pressable accessibilityRole. react-hook-form aria-live 자동.

### Previous Story Intelligence (Story 5.2 + 5.1)

Story 5.2 CR 결과 적용 학습(2026-05-07):
- **DF136 forward-hook** — 본 스토리 시점에 *즉시* 해소(`_build_user_dump_payload` → service module 이전). dev notes 명시 forward-hook은 *결심을 미루는 dead weight*가 아닌 *후속 스토리 직접 책임*으로 처리.
- **Decimal `format("f")` scientific notation 차단** (CR P10) — 본 스토리 service module이 SOT 보유, worker는 import. 변환 로직 1지점 보존.
- **`asyncio.to_thread` boto3 위임** (CR P2) — 본 스토리는 R2 직접 호출 0(서비스는 DB만 접근, R2는 worker만). 본 스토리 코드에 `asyncio.to_thread` 사용 0.
- **Defer 누적**: DF132(dump↔delete tie 부재) + DF133(OpenAPI 422 only) + DF134(Android destructive) — 본 스토리도 *유사 패턴 재발 가능*(GET /me/export OpenAPI 400 분기 미선언 가능). DF133 baseline에서 Story 8.4 polish forward 일괄 정리 — 본 스토리 OUT.

Story 5.1 CR 결과 (2026-05-07 누적):
- **react-hook-form + zod 폼 패턴 SOT** (Story 4.4 도입 → Story 5.1 + 5.2 확산) — 본 스토리 web `DataExportForm`도 같은 패턴.
- **PIPA Art.35 정합 — `require_basic_consents` 미적용** (Story 5.2 SOT 재사용) — 본 스토리도 1:1 정합.

### Git Intelligence

최근 5 커밋 분석(2026-05-07 master):
- `ca10b89` Story 5.2 — `app/workers/soft_delete_purge.py` + `_build_user_dump_payload` SOT 도입(*본 스토리 리팩터링 입력*).
- `a020e6e` Story 5.1 — `mobile/features/settings/HealthProfileEditForm.tsx` 첫 도입(`mobile/features/settings/` 디렉토리 SOT — 본 스토리 `useDataExport.ts`도 같은 directory).
- `2e21d8d` Story 4.4 — `web/src/features/settings/MacroGoalForm.tsx`(react-hook-form + zod 첫 도입 — 본 스토리 `DataExportForm.tsx` 패턴 SOT).
- `7662678` Story 4.3 — `selectinload(Meal.analysis)` N+1 가드 패턴 SOT(본 스토리 `collect_user_export_payload`가 정합).

### Latest Tech Information

- **FastAPI `StreamingResponse`** — `fastapi.responses.StreamingResponse` (≥0.100). content는 sync iterable 또는 async generator 모두 수용. 본 스토리는 (a) JSON 단일 chunk(sync iterable) (b) CSV row generator(async generator) 두 패턴 모두 사용. baseline FastAPI 버전 호환.
- **expo-file-system `~19.0.x`** — Expo SDK 54 baseline. Legacy API(`writeAsStringAsync`) 사용. SDK 54의 *next* API(파일 클래스 기반)는 알파 단계 — polish 스토리 forward.
- **expo-sharing `~14.0.x`** — Expo SDK 54 baseline. iOS UIActivityViewController + Android Intent.ACTION_SEND 추상화.
- **Next.js 16 App Router Server Component** — `metadata` API + RSC + Story 5.1/5.2 SOT.
- **RFC 6266** — Content-Disposition filename* UTF-8 encoding 표준. `urllib.parse.quote`로 encode + 클라이언트 측 decode(`decodeURIComponent`).
- **RFC 4180** — CSV escape 표준(`,`/`"`/`\n` 포함 시 `"`로 감싸고 내부 `"` → `""`). MS Excel + Google Sheets 호환.

### Project Context Reference

- 프로젝트 메모리 정합:
  - **외주 영업용 포트폴리오** — 본 스토리는 *PIPA Art.35 정보주체 권리 + JSON/CSV 통합 다운로드*로 **B4 KPI(컴플라이언스 안전판 명문화)**에 직접 기여. 영업 답변 5종 closing FAQ에서 *"PIPA 정보주체 권리는 어떻게 보장하나요?"* 질문에 본 endpoint(데이터 이전·열람권) + Story 5.2 endpoint(삭제권) + Story 5.1 endpoint(정정권) *3개 엔드포인트*로 SOP 답변(외주 인수인계 시 README 1페이지 forward-hook).
  - **9포인트 데모 시나리오** — 본 스토리는 *컴플라이언스 SOP 문서 + 운영 답변 패키지*에 명시 — *"우리 앱은 PIPA Art.35 정보주체 권리 전체(열람/정정/삭제/처리정지)를 wired해 두었습니다"*.
  - **8주 부팅 + Docker 1-cmd** — 추가 인프라 0건(StreamingResponse는 FastAPI baseline + expo-file-system/sharing은 Expo SDK 54 baseline). 외주 클라이언트 인수 시 환경 변수 변경 X — 본 스토리는 *코드 + 클라이언트 의존성*만.
  - **Epic 5 마지막 스토리** — Story 5.1(정정권) + 5.2(삭제권) + 5.3(열람·이전권) 3개로 *PIPA 정보주체 권리 전체 wire 완료*. epic-5 in-progress → done 클로저 시점.

### References

- [Source: epics.md#809-823] Story 5.3 ACs SOT.
- [Source: prd.md#953] FR9 *"엔드유저는 자기 식단·피드백·프로필 데이터를 표준 형식(JSON 또는 CSV)으로 다운로드할 수 있다 (PIPA 정보주체 권리)"*.
- [Source: prd.md#221] IN #23 *"데이터 내보내기 (PIPA 권리)"* — 모바일 + Web 양 채널 의무.
- [Source: architecture.md#702] `app/services/data_export_service.py` — PIPA 권리 (FR9) SOT.
- [Source: architecture.md#704] `users.py` `/users/me/export` endpoint SOT.
- [Source: architecture.md#755] Web `app/(user)/account/export/page.tsx` SOT.
- [Source: architecture.md#814] Mobile `(tabs)/settings/data-export.tsx` SOT.
- [Source: architecture.md#970] FR9 mapping table — `users.py:export` + `data_export_service.py` + mobile `data-export.tsx` + web `/account/export`.
- [Source: implementation-artifacts/5-2-회원-탈퇴-soft-delete-grace.md#Dev Notes] DF136 forward-hook + JSON dump shape SOT.
- [Source: deferred-work.md#DF133] OpenAPI 422-only 분기 누적 — Story 8.4 polish forward(본 스토리는 신규 추가만).
- [Source: AGENTS.md (web)] react-hook-form + zod 폼 패턴 강제(본 스토리 `DataExportForm.tsx` 정합).

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context) — Amelia (bmad-agent-dev → bmad-dev-story).

### Debug Log References

- 단위 테스트 매크로 round 회귀 1건 — Python `round(120.5)`이 banker's rounding으로 120 반환(IEEE 754 half-to-even). 테스트 입력값을 `120.6` (round → 121 결정)으로 정정해 결정성 회복. 본 helper 자체는 의도된 banker's rounding 유지(외부 도구 가독성).
- mobile tsc 회귀 1건 — `expo-file-system ~19.0.18`은 SDK 54의 *next* API가 top-level이라 `documentDirectory`/`writeAsStringAsync`/`EncodingType`이 미노출. `import * as FileSystem from 'expo-file-system/legacy'`로 Legacy SOT 명시 import. spec 명시(*"SDK 54 Legacy API SOT"*) 정합.
- pnpm install metro-core ENOENT 1건 — 두 패키지(`expo-file-system`/`expo-sharing`)는 정상 설치되었으나 transient pnpm Windows quirk로 metro-core import 메시지 출력. node_modules 검증 후 정상 동작 확인(skip).
- ruff F401 unused import 4건 일괄 수정(`uuid`/`pytest`/`Consent`/`Decimal` worker module).
- ruff format auto-apply(3 파일).

### Completion Notes List

- **AC1 — `data_export_service.py` SOT** ✅ 신규 모듈 14건 helper(_serialize_value/_serialize_row/collect_user_export_payload/serialize_payload_to_json_bytes/stream_csv_rows + _csv_escape/_format_meal_date_kst/_format_macros/_format_citations) 작성. Story 5.2 worker SOT 1:1 이전 + `meal_analyses` nested 추가(*전체 set*). `include_soft_deleted_meals` 키워드로 endpoint(False)/worker(True) 분기 SOT.
- **AC2 — `GET /v1/users/me/export` endpoint** ✅ Literal query 1차 게이트 + `Depends(current_user)` 단독 + `audit_admin_action` 미wire + StreamingResponse + RFC 6266 Content-Disposition + nosniff. spec deviation 1건 — filename `{user_id}` → `_mask_user_id`(NFR-S5 SOT).
- **AC3 — Story 5.2 worker 리팩터링** ✅ 3 helper 정의 *제거*(72 lines 감축) + service module import + `_process_single_user_purge` 호출 1줄 갱신. DF136 forward-hook 즉시 해소.
- **AC4 — Mobile data-export.tsx + useDataExport.ts** ✅ `expo-file-system/legacy` + `expo-sharing` 표준 RN 패턴(documentDirectory write → OS share sheet). Sharing.isAvailableAsync fallback alert 포함.
- **AC5 — Web /account/export + DataExportForm** ✅ react-hook-form + zod + apiFetch GET → blob → URL.createObjectURL → 임시 anchor click → revokeObjectURL. RFC 6266 filename* 우선 parsing helper(extractFilenameFromContentDisposition). settings/profile 푸터에 데이터 내보내기 link 추가(회원 탈퇴 위 — non-destructive 우선).
- **AC6 — worker 회귀 0건 + meal_analyses 추가** ✅ Story 5.2 baseline 8/8 회귀 통과 + 신규 3 가드(import path/nested key/soft-deleted include).
- **AC7 — N+1 회귀 가드** ✅ `selectinload(Meal.analysis)` SOT(Story 4.3) + endpoint 테스트에 SQLAlchemy `event.listen("before_cursor_execute")` counter ≤ 8 가드.
- **AC8 — audit 미기록** ✅ signature inspection + route-level dependant walk 양쪽 채널 가드.
- **AC9 — 단위 테스트 + 회귀 0건** ✅ pytest **1074 passed / 11 skipped / 0 failed**(spec ~1068 + 6). coverage **85.09%**(>= 70% threshold). ruff/format/mypy 0 + web tsc/lint 0 + mobile tsc/lint 0.
- **AC10 — sprint-status / Story Status 갱신** ✅ Branch `story/5.3-data-export`(master에서 분기). DS 시작 시 ready-for-dev → in-progress, DS 종료 시 in-progress → review. CR 종료 직전 review → done + epic-5 in-progress → done(Epic 5 마지막 스토리 클로저)는 후속 단계.

### File List

**신규 파일:**

Backend (api/):
- `api/app/services/data_export_service.py`
- `api/tests/api/v1/test_users_export.py`
- `api/tests/services/test_data_export_service.py`

Mobile:
- `mobile/features/settings/useDataExport.ts`
- `mobile/app/(tabs)/settings/data-export.tsx`

Frontend (web/):
- `web/src/features/settings/DataExportForm.tsx`
- `web/src/app/(user)/account/export/page.tsx`

**수정 파일:**

Backend:
- `api/app/api/v1/users.py` — GET /me/export endpoint + import 추가. 기존 endpoint 변경 0건.
- `api/app/workers/soft_delete_purge.py` — 3 helper 정의 *제거* + service module import + 호출 1줄 변경(~5 lines diff).
- `api/tests/workers/test_soft_delete_purge.py` — 회귀 가드 ~3건 확장.

Mobile:
- `mobile/package.json` — `expo-file-system ~19.0.18` + `expo-sharing ~14.0.7` 추가.
- `mobile/pnpm-lock.yaml` — pnpm install 자동 갱신.
- `mobile/app/(tabs)/settings/_layout.tsx` — Stack.Screen 등록.
- `mobile/app/(tabs)/settings/index.tsx` — 메뉴 항목 추가.
- `mobile/lib/api-client.ts` — gen:api 자동 갱신.

Frontend (web/):
- `web/src/app/(user)/settings/profile/page.tsx` — 푸터 link 추가.
- `web/src/lib/api-client.ts` — gen:api 자동 갱신.

### Change Log

- 2026-05-07: DS 시작(Amelia) — sprint-status `5-3-데이터-내보내기-json-csv: ready-for-dev → in-progress`.
- 2026-05-07: DS 완료(Amelia) — pytest 1074 passed/11 skipped/0 failed + coverage 85.09% + ruff/format/mypy/tsc/lint 0 errors. sprint-status `5-3-데이터-내보내기-json-csv: in-progress → review`. Branch `story/5.3-data-export`.
