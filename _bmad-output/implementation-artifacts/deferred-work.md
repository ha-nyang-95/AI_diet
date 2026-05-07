# Deferred Work

리뷰·구현 과정에서 식별되었으나 다음 스토리·시점으로 미룬 항목 모음.

## Deferred from: code review of 5-1-건강-프로필-수정 (2026-05-07)

- **D1 — `api-client.ts` mobile/web 중복 재발 (DF130)**: `mobile/lib/api-client.ts` + `web/src/lib/api-client.ts` 두 파일이 byte-identical hunk로 PATCH endpoint type을 동시 추가. 본 diff가 중복 면적을 ~200 lines × 2로 확대. 공통 SDK 모듈로 통합 후보. Story 8.4 polish forward — DF130 *active* 잔여로 묶어 일괄 처리.
- **D2 — `PATCH /me/profile` OpenAPI `responses={400, 403}` 미선언**: 자동 생성된 web/mobile api-client 타입이 실제 RFC 7807 에러 shape(`validation.error` 400 / `consent.basic.missing` 403) 누락. Story 1.5 POST + Story 4.4 PATCH `macro_goal` 등 `users.py` 전반 동일 패턴 — 프로젝트 단위 hygiene. Story 8.4 polish forward에서 `responses={400: dict, 403: dict}` 일괄 선언 + OpenAPI regen.

## Deferred from: code review of 4-2-apscheduler-nudge-미기록-푸시 (2026-05-06)

- **D1 — push-then-INSERT race window + multi-worker 동시 sweep + shutdown wait=False**: `expo_push.send_nudge` 성공 후 `_record_notification` INSERT *전*에 컨테이너 종료/Postgres connection drop 시 push는 발사됐지만 멱등 row 없음 → 다음 cycle 30분 후 동일 사용자 재발사(중복 알림). multi-worker(uvicorn workers > 1 또는 Railway preview + prod 동시) 시 두 sweep 인스턴스가 동일 사용자를 fetch → push 양쪽 발사 → 한쪽 INSERT만 성공. 1인 8주 단일 노드 정합 — Story 8.5 hardening forward(reservation 패턴: INSERT before send + `INSERT ... ON CONFLICT DO NOTHING RETURNING id` + `apscheduler-postgres` JobStore 또는 cron 외부화).
- **D2 — `expo_push.fetch_receipts` 시그니처가 spec(`get_receipts(ticket_ids: list[str])`)과 SDK reality(`check_receipts(tickets: list[PushTicket])`) 차이 + 본 스토리에서 미호출(forward use)**: spec wording이 SDK 미정합 vs 구현이 SDK 정합. `_check_receipts_with_retry`가 list로 받아 `{receipt.id: receipt}` dict 빌드하지만 실 SDK는 dict 반환 가능성. Story 4.4 receipts polling wire-up 시점에 SDK 실 동작 검증 + spec wording / docstring 정합 갱신.
- **D3 — Mobile jest 인프라 부재로 `setupGlobalPushHandler` / `resolveDeepLinkTarget` / `useLastNotificationResponse` cold-start hook 단위 테스트 0건**: deep link injection 차단(`balancenote://` prefix), `_globalHandlerInstalled` 멱등 가드, listener cleanup, cold-start 분기 등 보안/멱등 흐름이 tsc + lint만으로 prod 진입. Story 4.1 W1 deferred(Story 8.4 jest + RNTL 인프라 도입 AC) 정합 — Story 8.4에서 흡수.
- **D4 — `users` 테이블 sweep query expression partial index 부재**: WHERE 절 `notifications_enabled = true AND expo_push_token IS NOT NULL AND deleted_at IS NULL AND (notification_time + INTERVAL '30 minutes')::time BETWEEN ...`. 1k+ 사용자 규모에서 sequential scan + 사용자별 NOT EXISTS 두 개. Story 8.5 performance hardening — `idx_users_eligible_for_nudge` partial expression index.
- **D5 — `mobile/lib/push.ts:resolveDeepLinkTarget`가 `data.kind` 무시 + 모든 `balancenote://` URL을 `/(tabs)/meals/input`로 라우팅**: 미래 `weekly_report_ready` (Story 4.4) push 도입 시 misroute. 현재는 단일 kind라 영향 0. Story 4.4 path 매핑 SOT(`{kind: route}`) 도입 시점에 정리.
- **D6 — receipts polling 미구현 → ticket OK 후 receipt 단계 DeviceNotRegistered 영구 미감지**: ticket.status="ok"만 검사 → Expo가 ticket을 *queued*로 받았지만 push 발사 시점에 device 토큰 만료 감지(receipt 단계)는 영원히 미감지 → 다음 날 sweep에서 동일 사용자 재시도. Story 4.4 receipt polling wire-up — 별도 cron 5-15분 후 + `notifications.expo_receipt_status`/`expo_receipt_error` 컬럼 wire(0014에서 미리 박음).
- **D7 — `today_kst` 자정 cross UX semantic**: notification_time=23:30 사용자가 day N에 식단 정상 기록(예: 23:00 day N)했어도 day N+1 첫 cron tick(00:00 KST)에서 *"오늘 저녁 미기록"* 알림 수신 → 사용자 입장에서 *왜 알림이 와?*. 원인: `today_kst = now_kst.date()`이 발사 cycle(day N+1) 기준이라 meals NOT EXISTS query가 day N+1 meals(0건 — 새 날 시작)만 검사. 수정 시 sweep window(BETWEEN inclusive vs half-open) + target_kst 매핑 + 멱등 NOT EXISTS predicate(kst_date IN (day N, day N+1) 범위 매칭) + 회귀 테스트 3건 갱신(happy-path / 자정 cross / `notification_time=00:00` boundary) 일괄 필요. spec 자체 모호(*"발사 cycle 기준이라 정합"* vs 인접 parenthetical *"today_kst.meals가 1건이라 skip"* — 동일 case에서 두 해석 가능). Story 8.4 polish forward — UX 의사결정(sales 데모 시나리오 합의) + boundary 테스트 정합.

## Deferred from: code review of 4-1-알림-설정-푸시-권한 (2026-05-06)

- **W1 — AC15 mobile ~12건 jest 단위 테스트**: spec(`push.test.ts` ~4 + `permissions.test.ts` ~4 + `PermissionDeniedView.test.tsx` ~2 + `api.ts` schema ~2)이 명시했으나 mobile baseline에 jest 인프라 부재. **결정 (2026-05-06, hwan)**: 옵션 (a) 채택 — Story 8.4 ACs에 *모바일 jest + RNTL 인프라 도입* AC를 명시 추가(epics.md §Story 8.4 amendment 적용). 본 defer는 Story 8.4가 정식 home — 12건 흡수 + Story 2.2 `useCameraPermission`/`useMediaLibraryPermission` 등 추가 hygiene scope 5건도 동시 도입해 회귀 baseline 확립. Story 8.4 시점에 본 W1은 closed.
- **W2 — `register_push_token` TOCTOU race**: 두 UPDATE(`other-user.token=NULL` + `self.token=token`) 분리. 동시 등록 race 시 partial UNIQUE `ux_users_expo_push_token_active` 위반 → IntegrityError(데이터 손상 X — 안전망 작동, 사용자에 500 노출). Story 8.4 polish에서 SELECT FOR UPDATE row-lock 또는 IntegrityError catch + retry로 hardening. MVP <100 user 규모에서 발생 확률 극희박.
- **W3 — `signOut` 중 `unregisterPushTokenAsync` race + 무한 대기**: 401 refresh 인터셉터와 logout flow 충돌, 슬로우 네트워크 시 로그아웃 무한 대기 가능. `Promise.race(timeout 3s)` 도입 권장.
- **W4 — `(tabs)/_layout.tsx` 첫 prompt useEffect re-fire**: deps `[isReady, isAuthed, user?.profile_completed_at]` 갱신 시 effect 재실행. AsyncStorage flag가 1차 가드지만 getItem 실패 시 silent. 명시적 once-flag pattern로 hardening.
- **W5 — `NotificationApiError._parseProblem` 단일-사용 Response.json()**: 204 DELETE 응답에서 throw 후 `{}` swallow. response.ok 체크 후에만 json() 호출하는 명시적 status 분기로 정정.
- **W6 — `useNotificationPermission` AppState 미구독**: 사용자가 OS 설정 앱에서 권한 허용 후 복귀 시 notifications.tsx 권한 OFF 배너가 stale. Story 2.2 `useCameraPermission`도 동일 패턴 — 프로젝트 전반 hardening(AppState change → permission re-fetch).
- **W7 — TimePicker UX**: 시 단독 탭 시 즉시 `handleTimeSelect` + modal close. 시·분 동시 선택 후 "확인" 패턴이 표준. mutation 실패 시 modal 그대로 남고 에러 표시 X — 사용자 무한 재탭 가능. spec에 명시는 없으나 UX hygiene.
- ~~**W8 — `getLastNotificationResponse` deprecated**: expo-notifications 55+에서 `useLastNotificationResponse` hook 권장(React 스케줄링 통합). 현재 함수는 stale snapshot 반환 가능. Story 4.2 cold-start deep link wire 시점에 마이그레이션.~~ **CLOSED — Story 4.2 (2026-05-06)**: `mobile/app/_layout.tsx`에서 `useLastNotificationResponse` hook으로 cold-start 1회 처리(``identifier`` deps로 중복 차단). `getLastNotificationResponse` 함수는 deprecated 메모만 남기고 유지 — 외부 호출자 0건 시 Story 8.4 polish에서 제거 forward.
- **W9 — Tasks 7.5/8.4/9.3/11.6 dev device 통합 검증**: DS 스코프는 자동 게이트(tsc/lint/pytest)만, 실 디바이스 push token 발급/permission OEM Android Alert fallback 등은 QA 단계 책임. Story 8.4/QA 통합 시점에 EAS dev build로 검증.
- **W10 — `push.ts:registerForPushNotificationsAsync`의 iOS `provisional` 분기 미명시**: `permissions.ts:_normalizeStatus`는 `provisional → granted` 매핑하나 `push.ts`는 raw `Notifications.PermissionStatus` 비교. provisional 사용자가 token 발급 단계 진입하지 못할 가능성. 통합 매핑.
- **W11 — `_resolveProjectId` 빈 문자열 fallback**: `Constants.expoConfig?.extra?.eas?.projectId = ''` 시 `??` 사용으로 빈 문자열 통과 → `getExpoPushTokenAsync({projectId: ''})` warning. truthy 검증으로 정정.
- **W12 — `getExpoPushTokenAsync` 빈 문자열 token edge**: SDK 극단 케이스(인증 회복 중 등)에서 빈 문자열 token 반환 가능. 백엔드 regex 거부 → 400. mobile에서 사전 가드.
- **W13 — `registerForPushNotificationsAsync` granted+token=null 시 prompt flag set**: Expo Go / projectId 누락 사용자가 영구히 `has_push_token=false`로 묶임 → 향후 Story 4.2 cron skip. flag set 조건을 token 발급 성공으로 강화 + EAS dev build 사용자 retry path.
- **W14 — `notifications.tsx` Switch toggle granted+token=null silent gap**: 사용자는 알림 ON으로 인지하나 backend token 미등록 → 푸시 영구 미수신. Alert 또는 `has_push_token` 기반 inline 안내.
- **W15 — `updateMutation`/`registerMutation` rejection 표시**: Switch/TimePicker 실패 시 UI silent. `Alert.alert` 또는 toast로 에러 노티.
- **W16 — `push.ts:_ensureAndroidChannel` 첫 실패 시 `_channelInitialized=true` 영구 set**: retry 영구 차단. 성공 시에만 set으로 정정.

## CLOSED (2026-05-05) — Story 3.9 에픽 3 후 polish 일괄 처리

Story 3.9 (`_bmad-output/implementation-artifacts/3-9-에픽-3-후-polish.md`)에서 23건
NOW-ACTIONABLE 일괄 CLOSED. 20 AC + 10 Task로 그룹화 처리.

**A. 인프라 토폴로지 — Cloudflare proxy IP (DF111, W2 1.2, W10 1.3, W1 1.4, W17 1.5)**: `api/app/core/proxy.py` 신규 + `_CLOUDFLARE_IPV4`/`_CLOUDFLARE_IPV6` 22 CIDR + `get_real_client_ip()` SOT + 5 callsite swap(refresh_token / consents PIPA audit / SSE rate limit / Limiter key_func / lifespan init). `docs/runbook/deployment.md` + `cloudflare-ip-refresh.md` 신규(분기 1회 갱신 SOP).

**B. 약관 major/minor 분기 (W4 1.3)**: `LegalDocument.version_type: Literal["major","minor"]` 추가 + `CURRENT_VERSION_TYPES` SOT + `require_basic_consents` 분기(major mismatch 차단 / minor `X-Consent-Update-Available` 헤더). privacy/sensitive_personal_info 만 minor 분류, 나머지 4개 baseline major 유지.

**C. Idempotency-Key 30일 TTL (DF50)**: `scripts/cleanup_idempotency_keys.py` 신규 + `.github/workflows/cleanup-idempotency-cron.yml` (KST 02:00 daily) + 4 단위 테스트.

**D. Vision 비용·캐시·결정성 (DF4, DF5, DF6)**: `cache:llm:vision:{sha256(image_key)}` Redis 24h TTL + `cost:vision:daily:{YYYY-MM-DD}` 일일 카운터(KST 자정 cross 자연 리셋) + `gpt-4o → gpt-4o-mini` 다운그레이드 fallback + `MealOCRUnavailableError` (한도 도달) + `ParsedMeal.model_used` metadata. 6 단위 테스트.

**E. 식약처 데이터 보강 (DF102, DF103)**: `MFDS_MAX_PAGES` 100→500 + `DB_GRP_CM_GROUPS=("D","P")` SOT 회귀 가드 + `mfds_food_nutrition_seed.csv` 외식·가공식품 50종 수동 보강(짜장면/짬뽕/탕수육/마라탕/마라샹궈/떡볶이/순대/김밥 변형/햄버거/핫도그/치킨 변형/피자/파스타/비빔밥 변형/김치찌개/된장찌개/부대찌개/갈비탕/삼계탕/냉면/칼국수/우동/라면 변형/떡국/만두국/비빔국수/닭갈비/제육볶음/잡채/호떡/붕어빵/스낵 등). bootstrap_seed idempotent 회귀 가드 갱신.

**F. Self-RAG / LangGraph (DF89, DF99, DF91)**: `aresume` sanitize layer (managed field 차단 — `rewrite_attempts`/`node_errors`/`force_llm_parse` 주입 시 ValueError + 화이트리스트 외 키 silent drop). `_node_wrapper(deterministic=True)` 옵션 추가 — `evaluate_retrieval_quality` / `fetch_user_profile` 결정적 노드 retry 0회. 4+2 단위 테스트.

**G. SSE / LLM telemetry / Citation (DF115, DF100, DF104)**: `tests/perf/test_sse_t5_kpi.py` perf marker(opt-in `RUN_PERF_TESTS=1`). `_USED_LLM_OPENAI` Literal 확장 + `_resolve_used_llm` 헬퍼 — env override 정확 attribution(`gpt-4o-mini` / `gpt-4o` / `claude-haiku-4-5` / `claude` / `stub`). `_CITATION_PATTERN` regex `\(\s*출처\s*[:：]` 변형 수용(fullwidth colon / leading whitespace / 전각공백). 5+3 단위 테스트.

**H. Test infra (DF101)**: `tests/conftest.py:make_llm_adapter_mocks()` SOT 추출 — 4 모듈(`test_pipeline` / `test_self_rag` / `test_analysis_service` / `test_main_lifespan`)이 1지점 위임. 회귀 0건.

**I. 모바일/백엔드 회귀 가드 + 단건 endpoint (DF28, DF38, DF21, DF18, DF26, DF9)**: `MealMacros.le=10000` 환각 데이터 cap + 정상 범위 회귀 가드. `MealCard.time.flexShrink: 0` 명시(NFR-A3 200% scale + allergen 라벨 동시 표시 시 시간 잘림 차단). `mobile/lib/query-persistence.ts` `buster` bump SOP 도입(persist schema 변경 시 v1→v2 룰 명시). `GET /v1/meals/{meal_id}` 신규 endpoint + 모바일 `useMealQuery(meal_id)` hook + 4+1 단위 테스트(자기 200 / 다른 사용자 404 / soft-deleted 404 / 미존재 404). Vision 환각률 perf marker 골격 (`tests/perf/test_vision_hallucination_rate.py`).

**검증 결과**: pytest 824 passed / 11 skipped / 0 failed + coverage 84.92% + ruff/format/mypy 0 errors + mobile tsc 0 errors. Story 3.3-3.8 회귀 0건.

---

## 결정 사항 (2026-05-05) — 결정-블록 DEFER unblock

이전 *시점*이 아닌 *결정*에 묶여 있던 DEFER 항목들을 실 결정으로 unblock. 영향받는 bullet에는 `**결정 (2026-05-05)**:` 노트가 추가됐고, 모두 NOW-ACTIONABLE로 승격.

- **인프라 토폴로지** — **Railway + Cloudflare 앞단** 채택. proxy chain: `Cloudflare → Railway → app`. PIPA audit IP는 `CF-Connecting-IP` trust. 외주 인수 마이그레이션 lock-in 회피를 위해 Railway-specific feature 회피(pgvector/redis 컨테이너 유지, secret store 표준 SOP). 영향: **DF111(3.7), W2(1.2), W10(1.3), W1(1.4), W17(1.5)**.
- **약관 버전 bump SOP** — **major/minor 분기** 채택. `LEGAL_DOCUMENTS`에 `version_type: "major" | "minor"` 추가, major mismatch만 `require_basic_consents` 차단, minor는 `X-Consent-Update-Available` 헤더 안내. 영향: **W4(1.3)**.
- **Idempotency-Key TTL** — **30일** 채택. cron 1줄로 `meals.idempotency_key` clear (모바일 큐 자동 폐기 14일 대비 안전 마진). 영향: **DF50(2.5)**.
- **Vision 비용·캐시·결정성** — **일일 $5 cap + 24h 캐시 + image_key 기반** 채택. 캐시 키 `cache:llm:vision:{sha256(image_key)}`, cap 도달 시 `gpt-4o-mini` 다운그레이드 fallback. 영향: **DF4, DF5, DF6 (Story 2.3)**.
- **식약처 데이터 보강** — **max_pages 100→500 확대 + DB_GRP_CM 가공식품 그룹 fetch + 외식 영업 50종 수동 CSV** 채택 (짜장면/짬뽕/탕수육/마라탕/떡볶이/순대/김밥 변형 등). 클라이언트 도메인 customization은 인수 후 따로. 영향: **DF102, DF103**.
- **True LLM-token streaming** — **채택 안 함**(pseudo-streaming 유지). 데모 임팩트 미미 + 후처리 회귀 risk 높음. → **DF110(3-7 섹션) DISMISS 처리, 본 문서에서 제거됨**.

## Deferred from: code review of 3-7-모바일-sse-스트리밍-채팅-ui (2026-05-04)

- **DF111 — Rate limit X-Forwarded-For trusted proxy 인식** — `slowapi.util.get_remote_address`가 raw `request.client.host` 폴백, 프록시 뒤에선 단일 IP로 전체 트래픽 1 bucket 공유. **결정 (2026-05-05)**: Railway + Cloudflare topology 채택 — Cloudflare → Railway → app proxy chain. `CF-Connecting-IP` trust + `forwarded_allow_ips`에 Cloudflare IP range 설정. **재검토 시점**: 결정-블록 해소, NOW-ACTIONABLE 승격 (W2 1.2 / W10 1.3 / W1 1.4 / W17 1.5와 일괄 작업).
- **DF115 — T5 KPI 자동화(끊김 ≤ 1/50회) — perf marker `@pytest.mark.perf`** — Task 9.1 명시 케이스이나 본 스토리 perf marker 골격 부재. 사유: spec AC5 본문에 *"T5 KPI 측정은 Story 3.8 LangSmith eval 흐름에서 자동화"* 명시 — Story 3.8 LangSmith dataset 인프라 종속. **재검토 시점**: Story 3.8 — opt-in `RUN_PERF_TESTS=1` + `EventSource.onerror` 카운터 + dataset 통계.

## Deferred from: code review of 3-6-인용형-피드백-광고-가드-듀얼-llm (2026-05-04)

- **DF100 — `_USED_LLM_OPENAI = "gpt-4o-mini"` hardcoded(`settings.llm_main_model`과 분리)** — `api/app/adapters/llm_router.py:286-287`. env override로 model 변경 시 telemetry attribution이 실제 호출 모델과 mismatch. 사유: `FeedbackOutput.used_llm: Literal["gpt-4o-mini","claude","stub"]` 강제 — 단순 settings 파생은 Literal 위반. **재검토 시점**: Story 3.8 LangSmith — Literal 확장(model id별) 또는 별도 attribution 채널 분리.
- **DF101 — `LLMRouterPayloadInvalidError`가 content-policy refusal과 schema-invalid 미구분** — `api/app/adapters/llm_router.py:169-186`. 사용자 입력이 정책상 refuse면 OpenAI + Anthropic 양쪽 quota burn. 사유: 본 스토리 cost monitor 미도입 + content-policy 빈도 측정 부재. **재검토 시점**: Story 8.4 polish — `LLMRouterContentRefusedError` 서브클래스 분리, fallback 차단.
- **DF102 — cache deserialize 실패가 Sentry 미캡처(structlog warning만)** — `api/app/adapters/llm_router.py:81-94`. cache poisoning 같은 silent 회귀 알림 부재. 사유: 본 스토리는 anchor 1지점만 — observability 정교화는 후속. **재검토 시점**: Story 8.4 polish — `sentry_sdk.capture_message(..., level="warning")` 추가.
- **DF103 — `temperature=0.3` / `max_tokens=1024` magic dup (openai/anthropic adapters)** — `api/app/adapters/openai_adapter.py`, `api/app/adapters/anthropic_adapter.py`. 두 adapter에 독립 const, 향후 튜닝 시 drift 위험. 사유: settings에 hoist 시 LLM별 별도 필드 필요(스펙 미명시). **재검토 시점**: Story 8.4 polish — `settings.llm_temperature`/`settings.llm_max_tokens` 도입.
- **DF104 — 인용 패턴 fullwidth colon `(출처：` / leading whitespace `( 출처:` 등 변형 미수용** — `api/app/domain/ad_expression_guard.py:_CITATION_PATTERN`, `api/app/graph/nodes/_feedback_postprocess.py:_CITATION_PATTERN`. 한국어 LLM 출력에서 빈도 낮음으로 판단. 사유: 실측 부재 — Story 3.8 eval에서 발생률 측정 후 결정. **재검토 시점**: Story 3.8 LangSmith eval.
- **DF105 — 광고 가드 false-positive 차단 테스트(`예방접종`/`처방전`/`완화병동`/`진단서`) — B1 decision 후 일괄 추가** — `api/tests/domain/test_ad_expression_guard.py`. 사유: regex 처리 방향(decision_needed B1) 확정 전 테스트 작성은 wasted work. **재검토 시점**: B1 decision 직후 동일 PR에 추가.

## Deferred from: code review of 3-5-fit-score-알고리즘-알레르기-단락 (2026-05-03)

- **df-1 hardcoded `sex="female"` for all users** — `api/app/domain/fit_score.py:compute_fit_score` BMR 호출이 `sex="female"`로 고정. 남성 사용자 BMR 166 kcal 과소산정 → meal target ~76-105 kcal 과소 → calorie_score systematic 편향. **재검토 시점**: Story 8.4 polish — `UserProfileSnapshot.sex` 필드 추가 + Story 1.5 alembic 마이그레이션 + fetch_user_profile 갱신 (스펙 line 26 명시 OUT).
- **df-2 negation phrasing(`땅콩없음`/`우유 미함유`) substring false-positive** — `api/app/domain/fit_score.py:detect_allergen_violations`. `"땅콩 미함유"` 라벨도 `"땅콩"` substring으로 fire. 스펙 posture는 "보수적 false-positive 우선 — 안전 측면". 실 메뉴는 negation을 name 필드보다 ingredient list에 명시. **재검토 시점**: Story 4.x ingredient list 처리 도입 시 또는 Story 8.4 polish.
- **df-3 `포크` alias가 비식품 단어(포크송/포크댄스/포크리프트)에 fire 가능** — `api/app/domain/fit_score.py:ALLERGEN_ALIAS_MAP`. LLM/OCR 파이프라인이 비식품 단어를 음식명으로 emit 가능성 낮음. **재검토 시점**: Story 8.4 alias map 50+ 확장 + 외주 클라이언트 자사 메뉴 보강 SOP.
- **df-4 tautological 22-allergen 테스트 (`아황산류`/`잔류 우유 단백`)** — `api/tests/domain/test_fit_score_allergen_22.py`. food name이 라벨 string 자체를 verbatim 포함 → 단순 `label in text` 매칭. 실 한국 메뉴는 `"드라이와인"`/`"카제인 함유 단백질바"` 처럼 alias 필요. **재검토 시점**: Story 8.4 alias map 50+ 확장 시 와인/카제인 매핑 추가.
- **df-5 detect_allergen_violations가 quantity 무시 (trace amount == primary ingredient)** — `api/app/domain/fit_score.py:detect_allergen_violations`. `"우유 1방울"` 같은 trace도 fit_score=0 단락. 안전 baseline 의식적 선택. **재검토 시점**: Story 8.4 dose threshold(예: `>= 5g` 또는 ingredient ratio).
- **df-6 BMR 검증이 ratio sanity 미체크 (age=150 + weight=1 → 음수 BMR)** — `api/app/domain/bmr.py:compute_bmr_mifflin`. DB CHECK가 SOT — 실 시나리오에서 도달 불가. 음수 출력 가드는 m-6 패치로 처리. **재검토 시점**: Story 8.4 polish — input ratio sanity validator (예: `weight_kg/height_cm > 0.05`).

## Deferred from: code review of 3-3-langgraph-6노드-self-rag-saver (2026-05-02)

- **DF89 — `aresume`의 진짜 LangGraph resume semantics 미구현** — `api/app/services/analysis_service.py:aresume`. 현 구현은 `await self.graph.ainvoke(user_input, config=...)`로 START부터 재실행. 진짜 resume은 `Command(resume=...)` 또는 `ainvoke(None, config=...)` 패턴. 사유: spec line 125-126이 *인터페이스 박기만* 명시 — Story 3.4 needs_clarification 흐름에서 실 분기 갱신 로직과 함께 도입. **재검토 시점**: Story 3.4 — `needs_clarification = True` 후 사용자 응답 받아 parsed_items 갱신 후 재개 흐름 확정 시.
- **DF90 — `parse_meal` `raw[:50]` 그래프임 클러스터/이모지 mid-codepoint cut** — `api/app/graph/nodes/parse_meal.py:25-27`. 현 stub은 단순 `[:50]` 슬라이스로 multi-codepoint emoji/ZWJ 시퀀스 중간 절단 가능. 사유: Story 3.4가 실 LLM parse로 stub 대체 시 이 슬라이스 자체가 사라짐. **재검토 시점**: Story 3.4.
- **DF91 — `evaluate_retrieval_quality` 결정성 노드 retry 의미 0** — `_node_wrapper`가 모든 노드에 동일 retry 적용. 결정적 노드는 같은 입력으로 2회 실패 → 의미 없는 1회 추가 호출. 사유: 본 스토리는 stub만 — Story 3.6 실 LLM router 진입 시점에 retry 정책 분기(per-node opt-out 또는 deterministic 노드 wrapper override). **재검토 시점**: Story 3.6.
- **DF92 — `fetch_user_profile.health_goal` Literal 강제 변환 누락** — `api/app/graph/nodes/fetch_user_profile.py`. SQLAlchemy PG_ENUM이 raw string 반환 → DB enum drift 시 PydanticValidationError → wrapper retry 의미 없는 fallback. 사유: 현 단계 enum 안정. **재검토 시점**: Story 5.x 회원 프로필 수정 시 enum 마이그레이션과 함께.
- **DF93 — `AsyncConnectionPool max_size=4` 하드코딩** — `api/app/graph/checkpointer.py:74-75`. 동시 분석 호출 5+ 개 시 풀 starvation 가능. `RATE_LIMIT_LANGGRAPH = "10/minute"`와 정합 X. 사유: 실 부하 측정 전 premature optimization. **재검토 시점**: Story 8 운영 hardening + perf 측정.
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
- **W2 `request.client.host` proxy 헤더 처리** — `RefreshToken.ip_address`에 raw `request.client.host` 저장. reverse proxy 뒤에서는 LB IP로 통일. **결정 (2026-05-05)**: Railway + Cloudflare topology — `CF-Connecting-IP` trust. **재검토 시점**: 결정-블록 해소, NOW-ACTIONABLE (DF111 / W10 / W1(1.4) / W17 일괄 작업).
- **W3 httpx retry/backoff 미적용** — `google_oauth.exchange_code` 5초 timeout만, transient 5xx/네트워크 예외가 그대로 `InvalidIdTokenError`로 전파. 사유: Epic 8(운영 hardening)의 resilience 패턴(tenacity·circuit breaker)과 함께 일괄 적용.
- **W6 `ProblemDetail.type=about:blank` 일관 사용** — RFC 7807 허용 범위. 사유: code 카탈로그 + i18n URI는 운영 안정화 후 Story 8 일괄.
- **W10 ValidationError `msg`/`loc` raw 노출** — pydantic 메시지가 입력값 echo. 사유: 별도 NFR(입력 echo 정책) 정의 후 모든 validation 에러 일괄 sanitize.

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
- **W4 — 버전 bump 시 자동 재동의 트리거 부재** — 운영자가 `_VERSION_KO`만 바꾸면 모든 활성 사용자가 즉시 `basic_consents_complete=false`로 차단됨(운영 폭탄). **결정 (2026-05-05)**: major/minor 분기 채택 — `LEGAL_DOCUMENTS`에 `version_type: "major" | "minor"` 추가, major mismatch만 차단, minor는 `X-Consent-Update-Available` 헤더 안내. **재검토 시점**: 결정-블록 해소, NOW-ACTIONABLE.
- **W5 — `require_basic_consents` DB error → typed 5xx 매핑 미적용** — `db.execute` 실패 시 raw exception으로 500. 사유: cross-cutting, Story 8 운영 hardening.
- **W6 — soft-deleted user 복원 시 stale consents row 사용 가능** — `users.deleted_at` 마킹만 하고 `consents` row 보존 → 복원 시 fresh PIPA assent 누락. 사유: Story 5.x(회원 탈퇴 + 30일 grace) 책임 영역.
- **W7 — Mobile onboarding이 `?next=` 미독해** — `(tabs)/_layout.tsx`가 next 쿼리는 보존하지만 onboarding 화면들이 읽지 않음. 사유: spec AC2 line 31에 *Story 1.6 온보딩 완료 후 복귀에서 활용* 명시.
- **W8 — `consent.basic.missing` 클라이언트 인터셉터 부재** — `require_basic_consents`가 wire되면 사용자가 raw 403만 보고 onboarding 진입 경로 못 찾음. 사유: Story 1.5+ 라우터 wire 시점에 인터셉터 추가.
- **W9 — typed-route cast workaround (`as Parameters<typeof router.push>[0]`)** — Expo Router typed-routes 캐시 재생성 트리거를 위한 임시 우회. 사유: PR 머지·캐시 정상화 후 정리. 잔존 시 settings 경로 변경 시 컴파일러 검출 안 됨.
- **W10 — `request.client.host` proxy 헤더 처리 미적용** — Gemini Code Assist medium 코멘트(PR #5 #discussion_r3153082820). PIPA audit IP가 reverse-proxy 사설 IP로 통일됨. **결정 (2026-05-05)**: Railway + Cloudflare topology — `CF-Connecting-IP` trust (W2 1.2 / DF111 / W1 1.4 / W17 일괄). **재검토 시점**: 결정-블록 해소, NOW-ACTIONABLE.
- **W12 — middleware JWT 시그니처 검증 불가** — `hasValidLookingCookie`는 길이만 체크. 위조 쿠키로 onboarding GET 한 번 통과 가능(RSC가 bounce). 사유: Edge runtime crypto 제약 + Story 1.2 정합 패턴 — RSC 책임으로 분리.
- **W13 — `ConsentVersionMismatchError` 409에 `X-Consent-Latest-Version` 헤더 미포함** — 클라이언트는 status만 보고 latest version 추론 불가, 추가 round trip 필요. 사유: UX nice-to-have, Story 1.4가 같은 패턴으로 추가 시 일괄 도입.
- **W14 — `require_basic_consents` 라우터 wire 미적용** — `app/api/deps.py`에 정의되어 있으나 어떤 라우터에도 Depends 등록 안 됨. 사유: spec AC11 명시 — 본 스토리는 *함수 정의 + 단위 테스트*만, Story 1.5(`POST /v1/users/me/profile`) / Story 2.1+(`/v1/meals/*`)이 명시 적용.
- **W15 — CSRF 방어 명시 검증 미수행** — Web POST `/v1/users/me/consents`가 cookie 인증 + body POST. 사유: Story 1.2 `Spec deviation: SameSite=Lax` 정합 — Lax 쿠키가 cross-site form POST 차단. 외부 보안 audit 시 재검토.

## Deferred from: code review of 1-4-자동화-의사결정-동의 (2026-04-28)

- **W0 (D1 결정) — 백엔드 `POST /automated-decision`에 `require_basic_consents` 게이트 미적용** [`api/app/api/v1/consents.py:285-321`] — 스펙 AC3 가 INSERT 분기 basic 4 컬럼 NULL 허용을 *명시*("이론상 불가 — 본 화면 진입 가드가 basic 4종 통과 강제"), 직접 API 호출 시 `basic_consents_complete=false` + AD granted 인 일관성 깨진 row 생성 가능 + Anti-pattern catalog (line 535) 모순. 사유: 본 스토리는 데모 sales tool 범위, 프론트엔드 가드로 충분; 직접 API 호출 보호는 운영 hardening 영역 — Story 8(운영 hardening) 또는 외부 보안 audit 시 재검토. 도입 시 새 에러 클래스 `BasicConsentsMissingError(409)` + AC3 수정 + Mobile `extractSubmitErrorMessage` 처리 (P8 와 함께) 일괄.
- **W1 — `request.client.host` 원시 IP** [`api/app/api/v1/consents.py:1061`] — proxy/LB 뒤에서 PIPA audit 가 LB IP 로 통일됨. **결정 (2026-05-05)**: Railway + Cloudflare topology — `CF-Connecting-IP` trust (W2 1.2 / W10 1.3 / DF111 / W17 일괄). **재검토 시점**: 결정-블록 해소, NOW-ACTIONABLE.
- **W3 — `datetime.now(UTC)` (Python) vs `func.now()` (Postgres) 타임스탬프 drift** [`api/app/api/v1/consents.py:1056-1083, 1109-1113`] — 같은 row 내 `automated_decision_consent_at` (Python) 과 `updated_at` (DB) 에 ms 수준 시계 차이 발생 가능. 사유: Story 1.3 carry-over 패턴 — DB-only(`func.now()`) 또는 Python-only(`datetime.now(UTC)`) 통일은 Story 8 일괄 정리.

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
- **W17 — Web cookie auth CSRF 보호 미명시** — `bn_access` SameSite=Lax 채택 + 명시 CSRF 미들웨어 없음. **결정 (2026-05-05)**: Railway + Cloudflare topology — Cloudflare WAF rule + `forwarded_allow_ips` 일괄 설정 (proxy IP 처리와 동일 PR). **재검토 시점**: 결정-블록 해소, NOW-ACTIONABLE.
- **W18 — Migration이 `app.domain.*` import (replay safety vs SOT-sync)** — spec 결정으로 SOT 우선 채택. 향후 22종 변경 cron(Story 8 R8 SOP)과 함께 재검토.
- **W19 — Migration 0005 downgrade가 사용자 health 데이터 silent drop** [alembic 0005 downgrade] — 운영 rollback runbook (Story 8). 실제 운영 전 backup 절차 명시 필요.
- **W20 — Web `HealthProfileForm` AbortController 미적용** — Task 7.5 명시 deviation (`isSubmitting`로 차단 충분). Story 8 polish 또는 메모리 누수 이슈 발견 시 도입.
- **W21 — Mobile `inflightRef` unmount cleanup + AbortController** — react-hook-form `isSubmitting` 우선, Story 8 polish.
- **W22 — `extra="forbid"` 클라이언트 진화 우려** — 각 endpoint 명시 contract 결정 유지. 7번째 입력 필드 추가 시 OpenAPI 재생성 + 양 클라이언트 deploy chain 검토.
- **W24 — BMR/TDEE float precision drift** [api/app/api/v1/users.py:100, weight_kg float 변환] — Story 3.x BMR 도입 시점 결정 (Decimal 직접 사용 vs float wire format).
- **W25 — `extractSubmitErrorMessage` 429/413 분기 부재** [mobile profile.tsx + web HealthProfileForm.tsx] — rate limit (W16) 도입 후 polish.
- **W27 — Mobile `pathname` open-redirect 잠재성** [mobile/app/(tabs)/_layout.tsx:57] — Expo Router pathname 안전 가정. Story 1.6 `?next=` 처리(W7) 시 일괄 whitelist.
- **W29 — Activity color spectrum 녹색 일색** [mobile healthProfileSchema.ts:75-81] — NFR-A4는 텍스트 라벨로 충족, design polish.
- **W32 — `Numeric(5,1)` 상한과 CHECK 500.0 mismatch (defense-in-depth)** [alembic 0005] — Numeric(5,1)은 max 9999.9, CHECK는 500.0. 현 동작 무영향, 정밀도 명세 명시 시점에 일괄 정리.

## Deferred from: code review of 1-6-온보딩-튜토리얼 (2026-04-29)

- **W33 — `?next=` 쿼리 forward + 처리** [mobile/app/(auth)/onboarding/tutorial.tsx Redirect, mobile/app/(tabs)/_layout.tsx:58-62] — onboarding 모든 화면이 forward만 수행, 처리 X. tutorial.tsx도 `<Redirect href={PROFILE_ROUTE} />`로 next 미전파, `setTutorialSeen` 후 `router.replace(PROFILE_ROUTE)`도 동일. Story 1.3 W7 재deferred(spec deferred-work 명시) — Story 5.1 또는 Story 8 polish 시점에 일괄 whitelist + 처리.
- **W35 — Color contrast WCAG AA 검증** [mobile/app/(auth)/onboarding/tutorial.tsx 색상값 #666·#1a73e8] — Skip 텍스트 #666 on #fff ~5.7:1, primary 버튼 #fff on #1a73e8 ~4.7:1로 WCAG AA borderline. Design system 도입(Story 8) 시점에 일괄 정리.
- **W38 — 로그 이벤트명 `users.profile.updated` 첫 onboard vs profile edit 미구분** [api/app/api/v1/users.py:194] — 다운스트림 로그 분석이 boolean field 파싱 의존. 별도 `users.onboarded` 이벤트 분리는 Story 7 audit 정제 시점.

## Deferred from: code review of 2-1-식단-텍스트-입력-crud (2026-04-29)

- **W45 — 부분 인덱스 (`idx_meals_user_id_ate_at_active`) 사용 EXPLAIN 검증 부재** [api/tests/test_meals_router.py] — 본 스토리 baseline은 정합성/회귀 테스트 22건. 향후 마이그레이션이 인덱스 조건/컬럼 변경 시 silent 성능 회귀 가능. `EXPLAIN (FORMAT JSON)` 기반 perf smoke 1건 추가. 사유: Story 8 perf hardening 또는 사용자 식단 1k+ 누적 후 성능 이슈 surface 시.
- ~~**W46 — 앱 백그라운드/킬 mid-mutation 시 중복 POST**~~ [mobile/features/meals/api.ts `useCreateMealMutation`] — ~~사용자가 "저장" 탭 후 OS가 앱을 background → 메모리 회수로 kill, 사용자 재개 후 재시도 시 같은 식단 2 row 생성 (서버는 `Idempotency-Key` 헤더 *수신*만 허용, 처리 X — AC2 정합). 사유: Story 2.5(오프라인 텍스트 큐잉) offline-queue.ts + `meals.idempotency_key UNIQUE` 컬럼 + 409 분기 일괄 도입 시 흡수.~~ **CLOSED — Story 2.5 (2026-04-30)**: `meals.idempotency_key TEXT NULL` 컬럼 + `idx_meals_user_id_idempotency_key_unique` partial UNIQUE index 추가, `POST /v1/meals`에서 `Idempotency-Key` 헤더 처리 + race-free SELECT-INSERT-CATCH-SELECT + 200 idempotent replay (RFC 9110), 모바일 `useCreateMealMutation`이 매 호출마다 `expo-crypto` `randomUUID()`로 헤더 자동 첨부. 회귀 차단: `test_post_meal_with_idempotency_key_duplicate_returns_200_same_row` + `test_post_meal_with_idempotency_key_race_simulated_two_inserts_same_key`.
- **W47 — `setError("raw_text", ...)` 미사용 (스펙 wording deviation)** [mobile/app/(tabs)/meals/input.tsx, MealInputForm.tsx] — 스펙 AC8 line 135은 400 응답 시 `setError("raw_text", { message })`로 RHF 필드-에러 API 사용 명시. 현 구현은 `setServerError(state)` + 별도 텍스트 렌더링 — 기능 동등이나 RHF `formState.errors` 통합 미활용(다음 입력 시 자동 클리어 등). 사유: P14(serverError 자동 클리어) 적용 후 추가 polish 가치 낮음, design polish 또는 RHF 통일 시점에 일괄.
- ~~**W49 — `MealCard.formatHHmm` 디바이스 로컬 TZ 사용 (D1 결정에 종속)**~~ [mobile/features/meals/MealCard.tsx:14-21] — ~~`new Date(isoString).getHours()/getMinutes()`는 디바이스 TZ 기반 — 한국 사용자가 LA 출장 시 PST로 표시. 본 스토리 baseline에서 *정확한 KST pin* 의무 미명시. 사유: D1(date filter wire 시맨틱) 결정 시 wire TZ 정책에 정합 — KST 강제 시 `Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', ... })` 일괄 적용.~~ **CLOSED — Story 2.4 (2026-04-30)**: `formatHHmm` `Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul' })` 강제 적용. `[meal_id].tsx`도 동일 패턴 사용. W49 해소.
- ~~**W50 (D1 결정) — `from_date`/`to_date` wire 시맨틱 KST/UTC 드리프트**~~ [api/app/api/v1/meals.py GET /v1/meals + mobile/app/(tabs)/meals/index.tsx] — ~~모바일은 디바이스-로컬(`Date.getDate()`)로 "today"를 KST 형식 문자열 송신, 서버는 `date` 타입을 Postgres 세션 TZ(=UTC)로 캐스팅 → KST 0–9시 식사 *제외*.~~ **CLOSED — Story 2.4 (2026-04-30, D1 option B 결정)**: 백엔드 `_KST = ZoneInfo("Asia/Seoul")` + `datetime.combine(date, time.min, tzinfo=_KST)` 변환으로 `Asia/Seoul` TZ 자정 boundary 강제 — KST 0-9시 식단 누락 차단. ORDER BY 분기(D2): 날짜 필터 활성 시 ASC, 미적용 시 DESC. W50 해소.
- **W51 (Gemini PR #10 review) — `users.py` `suppress(Exception)` 광범위 제거 (P16 cross-cutting)** [api/app/api/v1/users.py 일대] — Story 2.1 CR P16에서 `meals.py`의 `with contextlib.suppress(Exception):` 로거 가드를 *관측성 silent 차단 방지* 사유로 제거. Gemini 봇은 같은 패턴이 `users.py`(Story 1.5/1.6 코드)에도 잔존함을 지적, 일관성 확보 권장. 사유: 본 PR은 Story 2.1 범위 한정, cross-cutting 패턴 정합은 별도 polish PR (Story 8 hardening 또는 follow-up issue)에서 일괄. 검증 필요 — `git grep -n "suppress(Exception)" api/app` 으로 잔존 위치 식별 후 각각 None guard 또는 specific exception type으로 좁히기.

## Deferred from: Story 2.3 implementation (2026-04-30, OCR Vision + 확인 카드)

- **DF4 — Vision 모델 cost cap 부재** [api/app/adapters/openai_adapter.py] — `gpt-4o` 호출당 ~$0.005-0.01 + 일일 100건 cap 미적용. **결정 (2026-05-05)**: 일일 $5 cap + cap 도달 시 `gpt-4o-mini` 다운그레이드 fallback + Redis 일일 카운터 + Sentry alert. **재검토 시점**: 결정-블록 해소, NOW-ACTIONABLE (DF5/DF6과 일괄).
- **DF5 — Vision 응답 결정성 부족** [api/app/adapters/openai_adapter.py:VISION_MODEL] — `temperature=0.0` 강제이나 *같은 사진 재호출 시 다른 응답* 가능 (모델 내부 비결정성). **결정 (2026-05-05)**: image_key 기반 24h 캐시(DF6과 동일 키)로 결정성 보장 — 같은 사진 재호출 시 캐시 hit. **재검토 시점**: 결정-블록 해소, NOW-ACTIONABLE.
- **DF6 — Vision 응답 캐시 부재** [api/app/api/v1/meals_images.py POST /parse] — 같은 image_key 재 parse 호출 시 매번 OpenAI 호출 + 비용 + 지연. **결정 (2026-05-05)**: Redis `cache:llm:vision:{sha256(image_key)}` 24h TTL 도입 (DF4 cost cap + DF5 결정성과 동일 PR). **재검토 시점**: 결정-블록 해소, NOW-ACTIONABLE.
- **DF7 — `parsed_items` 음식명 정규화 미적용** [meals.parsed_items jsonb] — Vision이 *"자장면"* / *"짜장면"* / *"jajangmyeon"* 변형 출력 가능. 본 스토리는 *raw 출력 그대로 영속화*만. **재검토 시점**: Story 3.4 — 음식명 정규화 + `food_aliases` 매칭으로 일괄 처리.
- **DF8 — `parsed_items` 알레르기 자동 검출 미적용** — Vision이 *"새우"* 추출 시 알레르기 사용자 자동 경고 부재. **재검토 시점**: Story 3.5(fit_score + 알레르기 단락) 책임.
- **DF9 — Vision 환각 사례 모니터링 부재** — *"사용자 얼굴: 30대 남성"* 등 PII 출력 시도는 structured outputs로 차단되나 *"음식이 아닌 사물"*(예: 책 사진을 *"흰쌀밥"*으로 인식)은 차단 X. confidence 임계값 0.6 + 사용자 확인 카드로 1차 방어. **재검토 시점**: Story 3.8 LangSmith 평가 데이터셋 도입 시 환각률 측정.
- **DF10 — `OCRConfirmCard` 모달 vs inline 결정 미명시** [mobile/features/meals/OCRConfirmCard.tsx] — 본 스토리는 *inline*(form 대체) 채택. 모달 UX(반투명 backdrop + 외부 탭 dismiss)는 baseline OUT. **재검토 시점**: Story 8 polish 또는 사용자 피드백.
- **DF11 — `OCRConfirmCard` lowConfidence forced confirmation UX 검증 미실시** — 사용자가 *"이대로 진행"* 버튼 누르고 환각 항목 그대로 저장하는 *opt-out 시나리오* 측정 부재. **재검토 시점**: W8 데모 또는 Growth 단계 정량 평가.
- **DF13 — `parsed_items` jsonb GIN 인덱스 부재** [meals.parsed_items 컬럼] — Story 2.4 일별 기록 검색 시 `parsed_items.name` LIKE 검색 도입 가능성 — 현재는 인덱스 부재로 sequential scan. **재검토 시점**: 검색 기능 도입 시 Story 8 perf hardening.
- **DF14 — `OCRConfirmCard` `confidence` 사용자 편집 시 1.0 강제 vs 명시 변경 UX** [mobile/features/meals/OCRConfirmCard.tsx] — *"+ 항목 추가"*는 confidence 1.0 강제이나 *기존 항목 name/quantity 편집* 시 confidence 그대로 — 사용자가 환각 항목을 정확하게 고친 경우에도 낮은 confidence 잔존. behavior tradeoff(편집된 항목은 사용자 확신 vs 원본 confidence 보존)는 baseline에서는 *원본 보존* 선택. **재검토 시점**: Story 3.5 fit_score 도입 시 confidence 활용 패턴 결정 후 일괄.
- ~~**DF15 — `MealCard.tsx` `parsed_items` 표시 forward 미적용**~~ [mobile/features/meals/MealCard.tsx] — ~~Story 2.3 baseline은 *MealCard 변경 X* (Story 2.4가 일별 기록 화면 polish 시 *"인식: 짜장면 1인분, 군만두 4개"* 부제 추가). 본 스토리는 `MealResponse.parsed_items` 인터페이스 노출까지만.~~ **CLOSED — Story 2.4 (2026-04-30)**: `formatParsedItemsToInlineLabel` 헬퍼 + `MealCard.tsx` parsed_items 부제 wire(60자 ellipsis). DF15 해소.

## Deferred from: code review of story-2.3 (2026-04-30)

- **W1 — Vision 호출 client-side timeout/cancel 부재** [mobile/app/(tabs)/meals/input.tsx parseMealImage chain] — 백엔드 30s + tenacity 1회 retry로 60s까지 spinner 지속 — 사용자 escape 부재. AbortController + 35s 클라이언트 timeout + retry UI는 UX polish 영역. **재검토 시점**: Story 8 UX polish 또는 사용자 피드백 정량.
- **W3 — 같은 image_key parse 반복 호출 dedup/rate-limit 부재** [api/app/api/v1/meals_images.py POST /parse] — 호출당 새 Vision 호출 + cost 누적. 이미 DF6(Vision 응답 캐시 `cache:llm:{sha256(image_key)}` 24h TTL)와 통합 처리. **재검토 시점**: DF6과 동일 — Story 8 perf hardening.

## Deferred from: Story 2.4 implementation (2026-04-30, 일별 식단 기록 화면 + 7일 캐시 + KST 필터)

- **DF17 — `MealAnalysisSummary` cursor pagination 도입** [api/app/api/v1/meals.py list_meals] — Story 3.x `meal_analyses` JOIN 도입 시 *list 응답이 무거워짐*(macros 4 fields + feedback 120자) — cursor pagination 도입 검토. 본 스토리는 *날짜 필터 + limit=50*만. **재검토 시점**: Story 8 perf hardening 또는 사용자 식단 1k+ 누적 시 surface.
- **DF18 — `[meal_id].tsx` 단건 endpoint(`GET /v1/meals/{meal_id}`) 도입** [mobile/app/(tabs)/meals/[meal_id].tsx] — 7일 캐시 miss 시 *전체 fetch* 회피 + Story 3.7 SSE 채팅 진입 시점 단건 fetch 가능. 본 스토리는 *7일 client-side filter*만. **재검토 시점**: Story 8 hardening 또는 Story 3.7 SSE 통합 시.
- **DF19 — fit_score color/label 매핑 5단계 임계값 fine-tune** [mobile/features/meals/MealCard.tsx FIT_SCORE_COLORS/LABELS_KO] — baseline은 `low<40<moderate<60<good<80<excellent`. Story 3.5 알고리즘 도입 시 KDRIs AMDR 매크로 룰 기반 fine-tune. **재검토 시점**: Story 3.5 fit_score 알고리즘 도입.
- **DF20 — fit_score 헬퍼(`fit_score_color`/`fit_score_label_ko`) 모듈 분리** [mobile/features/meals/MealCard.tsx + [meal_id].tsx — 같은 매핑 inline duplicate] — Story 2.4 baseline은 `MealCard.tsx` + `[meal_id].tsx` 각각 inline 정의. Story 3.5 `fitScore.ts` 분리 시점에 통합. **재검토 시점**: Story 3.5 도입 시.
- **DF21 — 7일 캐시 `buster` 자동 bump SOP** [mobile/lib/query-persistence.ts] — baseline은 `buster: 'v1'` hardcode. Story 3.x `analysis_summary` 실제 wire 시 `'v2'` bump 누락 시 stale 캐시 형식 mismatch — *코드 리뷰 게이트*에 *persist schema 변경 시 buster bump* 명시 필요. README + CLAUDE.md SOP 1줄 추가 검토. **재검토 시점**: Story 3.3 시점에 SOP 정착.
- **DF23 — `[meal_id].tsx` accessibility — `AccessibilityInfo.announceForAccessibility`** [mobile/app/(tabs)/meals/[meal_id].tsx] — 화면 진입 시 시각 장애 사용자 자동 안내(*"19시 30분 식단 상세"*). baseline은 미수행. **재검토 시점**: Story 8 polish 또는 Growth NFR-A6.
- **DF26 — `useMealsQuery`의 `[meal_id].tsx` 호출 — 7일 윈도우 over-fetch** [mobile/app/(tabs)/meals/[meal_id].tsx useMealsQuery] — 단건 endpoint 부재로 *7일 전체 fetch* + client-side filter. 30일 누적 사용자에게 list 무거워짐. DF18과 통합 처리 — 단건 endpoint 도입 시 client-side filter 제거. **재검토 시점**: Story 8 또는 Story 3.7 — DF18과 동일.

## Deferred from: code review of 2-4-일별-식단-기록-화면 (2026-04-30)

- **DF27 — `from_date` 단독 사용 시 미래 식단 무한 노출** [api/app/api/v1/meals.py:506-508 list_meals] — `from_date`만 주고 `to_date` 미지정 시 `Meal.ate_at >= from_dt` upper bound 부재로 미래 catch-up 식단까지 모두 반환. 현 모바일은 `from_date == to_date` 동시 송신이라 노출 표면 없음. limit=200 cap 있음. **재검토 시점**: Story 8 운영 hardening — `to_date` 미지정 시 자동 boundary(예: today + 1d) 강제 또는 `from_date 단독` 거부.
- **DF28 — `MealMacros` upper bound 미정의** [api/app/api/v1/meals.py:260-273 MealMacros] — `Field(ge=0)`만 강제, `le=` 미지정. Story 3.x LLM 환각 데이터(`carbohydrate_g=99999`) 저장 시 `MealCard` macros row UI 잘림. 본 스토리는 슬롯 정의만, 채우는 건 Story 3.3/3.5 책임. **재검토 시점**: Story 3.3 `meal_analyses` JOIN 도입 시 — `Field(ge=0, le=10000)` 등 upper bound 추가.
- **DF30 — `web/src/lib/api-client.ts` 사용처 타입 마이그레이션** [web/src/lib/api-client.ts] — `MealResponse.analysis_summary` 신규 non-optional 필드 추가로 웹 사용처가 객체 리터럴 mock 시 strict TS 컴파일 영향 가능. 본 스토리는 OpenAPI 자동 재생성만 — 웹 사용처 영향은 별건 PR. **재검토 시점**: Story 4.3 web 주간 리포트 또는 web 식단 화면 도입 시.
- **DF37 — 만료 presigned URL fallback** [mobile/features/meals/MealCard.tsx + [meal_id].tsx — `expo-image`] — R2 image_url presign 만료 시 `expo-image` `onError` 핸들러 부재로 회색 background 잔상. 현 image_url은 public URL 가정. **재검토 시점**: Story 2.2 R2 wire 또는 Story 8 polish — presign 만료 핸들링 + retry.
- **DF38 — 폰트 200% + `allergen_violation` 라벨 헤더 row 깨짐** [mobile/features/meals/MealCard.tsx:174-187 headerRow] — `flexShrink:1, flexWrap:'wrap'` 있으나 `headerRow justifyContent:'space-between'` + time `minWidth: 56`으로 right side가 잘릴 수 있음. baseline 항상 null 미노출 — Epic 3 wire 시점 회귀 위험. **재검토 시점**: Story 3.3 `analysis_summary` JOIN 도입 시 NFR-A3 회귀 검증.
- **DF39 — `parsed_items` 1000+ 렌더 비용** [mobile/features/meals/parsedItemsFormat.ts formatParsedItemsToInlineLabel] — 60자 cap 적용은 `formatParsedItemsToRawText` 전체 join 후 slice. 악의적 OCR 응답 또는 백엔드 회귀로 1000+ items 시 카드당 ms 단위 비용. Story 2.3 OCR 응답 cap으로 차단되나 방어 layer 부재. **재검토 시점**: Story 8 hardening.
- ~~**DF42 — `[meal_id].tsx` `index.tsx`의 7일 캐시 토폴로지 정합**~~ — ~~`index.tsx`는 일자별 queryKey, `[meal_id].tsx`는 7일 윈도우 queryKey~~ **CLOSED — Story 2.4 CR (2026-04-30, 옵션 b 채택)**: `index.tsx`도 7일 윈도우 fetch + client-side filter로 변경. queryKey 통일(detail과 캐시 공유) + NFR-R4 일자 무관 7일 보장 + 백엔드 ASC + client filter로 AC4 시간순 정합.


## Deferred from: Story 2.5 implementation (2026-04-30, 오프라인 텍스트 큐잉 + Idempotency-Key)

- **DF43 — PATCH/DELETE 오프라인 큐잉** [mobile/lib/offline-queue.ts + (tabs)/meals/input.tsx] — 본 스토리 baseline은 PATCH/DELETE 오프라인 차단(Alert + back). 사용자가 오프라인에서 수정하려는 케이스(예: 제품 데모 중 회식 후 식단 수정)는 *Story 8 polish* — 큐잉 + 자동 flush 도입 검토. **재검토 시점**: Story 8 polish 또는 사용자 피드백.
- **DF44 — 사진 큐잉 (online deferred sync)** [mobile/lib/offline-queue.ts + (tabs)/meals/input.tsx] — 본 스토리 baseline은 사진 입력 오프라인 차단. *온라인 시 사진 첨부 + 텍스트는 큐잉(Vision 호출은 차후)* 부분 큐잉은 *Growth* — Vision 호출 비용 + UX 복잡도. **재검토 시점**: Growth UX polish.
- **DF45 — `OfflineQueueItem` schema buster 패턴** [mobile/lib/offline-queue.ts] — 본 스토리 baseline은 deserialize 실패 시 silent reset. *명시 buster 패턴*(`v1` → `v2` bump on schema change)은 Story 8 polish (Story 2.4 query-persistence DF21 정합). **재검토 시점**: Story 8 polish 또는 schema migration 발생 시점.
- ~~**DF46 — manual retry granular `attempts` reset 정책**~~ — ~~본 스토리 baseline은 manual retry 시 attempts reset 미적용(누적 유지). *attempts cap 도달 후 manual retry granular reset*은 Story 8 polish~~ **CLOSED — Story 2.5 CR (2026-04-30, DN2 결정 P16 승격)**: D4 baseline literal 충족 — `resetAttempts(userId, client_id)` 헬퍼 신규 + `triggerFlush`가 `flushQueue` 호출 전 attempts=0 reset.
- **DF48 — Sentry/PII 마스킹 큐 데이터** [mobile/lib/offline-queue.ts + 4xx Alert] — 본 스토리 baseline은 raw_text 그대로 큐 보관 + 4xx 시 Alert에 server detail 노출. *Sentry capture 시점에 raw_text 마스킹*은 Story 8 polish (NFR-S5). **재검토 시점**: Story 8 polish — Sentry wire 시점.
- **DF49 — `Idempotency-Key` cross-cutting 도메인 격리** [api/app/core/exceptions.py — `MealIdempotencyKeyInvalidError(MealError)`] — 본 스토리 baseline은 `MealError` 식단 도메인 하위. *Story 6.x 결제 webhook idempotency 도입* 시점에 *`IdempotencyError` cross-cutting base*로 분리 검토. **재검토 시점**: Story 6.x 결제 웨훅 도입.
- **DF50 — Idempotency-Key TTL** [api/app/db/models/meal.py idempotency_key] — 본 스토리 baseline은 `meals.idempotency_key`가 *영구 보존* (soft delete 후에도 unique 충돌 가능 — 409 분기). **결정 (2026-05-05)**: 30일 TTL 채택 — 모바일 큐 자동 폐기 14일 대비 안전 마진. cron 1줄: `UPDATE meals SET idempotency_key = NULL WHERE idempotency_key IS NOT NULL AND created_at < NOW() - INTERVAL '30 days'`. **재검토 시점**: 결정-블록 해소, NOW-ACTIONABLE (cron 인프라 도입 PR과 동시 또는 별도 작업).
- **DF51 — flush 중 transient 에러 시 다음 항목 진행 (batch parallel)** [mobile/lib/offline-queue.ts flushQueue] — 본 스토리 baseline은 transient 에러 시 flush 중단(첫 항목 backoff 의미 보존). *batch parallel sync*는 Story 8 polish — race + UX 트레이드오프 평가. **재검토 시점**: Story 8 polish.

## Deferred from: code review of 2-5-오프라인-텍스트-큐잉-sync (2026-04-30)

- **DF57 — 큐 배지 `accessibilityLiveRegion="polite"` 재공지 노이즈** [mobile/app/(tabs)/meals/index.tsx 배지 영역] — 매 `queueSize` 변경마다 VoiceOver 재공지 — flush 진행 중 N→0 단계별 announce. offline→online 전이 시 1회만 공지로 정련. **재검토 시점**: Story 8 a11y polish.
- **DF60 — `isInternetReachable` vs `isOnline` 분기 강화** [mobile/lib/use-online-status.ts + (tabs)/meals/index.tsx 자동 flush 트리거] — 현 Story 2.4 baseline `isConnected !== false`만 사용. `isInternetReachable === false` 케이스에서 useless 시도 누적. 조건 분기 강화. **재검토 시점**: Story 8 polish.
- **DF64 — `_create_meal_idempotent_or_replay` `values: dict` 타입 강화** [api/app/api/v1/meals.py:_create_meal_idempotent_or_replay] — 현 `dict[str, object]` — runtime mismatch 미감지. `MealInsertValues` TypedDict 또는 named args. **재검토 시점**: Story 8 type discipline.
- **DF70 — 식약처 OpenAPI endpoint URL + 응답 키 매핑 운영 검증** [api/app/adapters/mfds_openapi.py:MFDS_API_BASE_URL + MFDS_RAW_KEY_MAP + MFDS_KOREAN_FOOD_CATEGORIES] — Story 3.1 baseline은 *추정값*(공공데이터포털 데이터셋 15127578 신/구 표준 혼재 + 데이터셋별 endpoint 변동 위험). 운영 부팅 시 실제 OpenAPI 문서 + 샘플 응답으로 *최종 endpoint URL + 키 매핑 + 카테고리 명* 확정 필요. 현 추정 endpoint로 401/404 시드 fail 가능. **재검토 시점**: 외주 운영 첫 부팅 직전 또는 Story 8 hardening.
- **DF71 — `embedding NULL` row 백필 — wakeful repair 호출** [api/app/rag/food/seed.py:_embed_batch graceful fallback] — D4 graceful로 batch 임베딩 실패 시 `embedding NULL` INSERT 허용. 검색 시점에 자동 제외되지만, 누적된 NULL row를 *백필 재호출*하는 운영 SOP 부재. cron-driven repair 또는 Story 3.4 시점에 unmatched 시 임베딩 재계산 분기. **재검토 시점**: Story 3.4 또는 Story 8 polish.
- **DF72 — `food_aliases.canonical_name` ↔ `food_nutrition.name` orphan 검증 SOP** [api/app/rag/food/aliases_seed.py + Story 3.4 normalize.py] — 본 스토리 baseline은 두 시드 *독립*(canonical_name이 food_nutrition.name과 1:1 매칭되지 않아도 시드 통과). Story 3.4 normalize.py가 unmatched 시 임베딩 fallback로 자연 처리. 운영 시점에 orphan 비율 모니터링 + 데이터 품질 KPI 도입. **재검토 시점**: Story 3.4 또는 Story 8 polish.
- **DF73 — `MFDS_RAW_KEY_MAP` const 미사용(deprecated 표기 가드)** [api/app/adapters/mfds_openapi.py:MFDS_RAW_KEY_MAP + _raw_to_standard] — 현 `_raw_to_standard`는 inline 매핑(`item.get("FOOD_NM_KR") or item.get("name")`) 사용. `MFDS_RAW_KEY_MAP` const는 *문서 + DS 검증용*만 — 실제 매핑 로직은 함수 내 inline. 운영 부팅 시 실제 키가 const와 정합 검증 후 함수 본문도 const-driven으로 리팩터(키 변경 시 한 곳만 수정). **재검토 시점**: Story 8 refactor.
- **DF74 — `data/mfds_food_nutrition_seed.csv` placeholder → 실데이터 commit SOP 자동화** [api/data/mfds_food_nutrition_seed.csv + scripts/refresh_food_data.py 신규] — 본 스토리 baseline은 헤더만 commit. 운영자가 data.go.kr 통합 자료집 ZIP 다운로드 → 컬럼 변환 → CSV commit 수동 SOP. 분기 1회 갱신 자동화 스크립트(다운로드 + 변환 + diff 검증) 도입 검토. **재검토 시점**: Story 8.5 운영 SOP.

## Deferred from: code review of 3-1-음식-영양-rag-시드-pgvector (2026-05-01)

- **DF75 — `food_nutrition.updated_at` ON UPDATE DB-level 트리거** [api/alembic/versions/0010_food_nutrition_and_aliases.py L731-736, L772-777] — ORM `onupdate=text("now()")`만 적용 — psql 직접 UPDATE(외주 인수 클라이언트 SOP 경로 B)는 `updated_at` 자동 갱신 X. trigger 또는 generated column으로 DB-level enforcement. **재검토 시점**: Story 8 polish 또는 외주 인수 클라이언트 첫 부팅 SOP 정합 시.
- **DF76 — `_SEED_CSV_PATH = __file__.parents[3]` 경로 fragile** [api/app/rag/food/seed.py L1755-1759] — wheel/installed layout 또는 모듈 이동 시 silent miss(다른 경로 찾기). `settings.seed_data_dir` 도입 + startup 검증 로그. **재검토 시점**: Story 8 hardening.
- **DF78 — HNSW partial index `WHERE embedding IS NOT NULL`** [api/alembic/versions/0010_food_nutrition_and_aliases.py L745-752] — D4 graceful로 NULL embedding 행 발생 시 인덱스 bloat. `postgresql_where=sa.text("embedding IS NOT NULL")` 추가 검토. **재검토 시점**: Story 3.3 retrieve_nutrition perf 측정 후.
- **DF79 — `_get_client` MFDS API key 회전 캐시 무효화** [api/app/adapters/mfds_openapi.py:_get_client L955-975] — rolling deploy 시 MFDS_OPENAPI_KEY 회전 후 stale auth로 retry 실패 가능(현 `_fetch_page`는 매 호출 read이므로 부분 mitigation). prod 모드에서만 강한 invalidation 필요 시. **재검토 시점**: Story 8 prod hardening.
- **DF80 — Migration 부분 실패 복구 — `DROP INDEX IF EXISTS`** [api/alembic/versions/0010_food_nutrition_and_aliases.py upgrade/downgrade] — `op.create_index` 실패로 부분 commit된 상태에서 downgrade 재시도 시 IF EXISTS 누락으로 fail. defensive `op.execute("DROP INDEX IF EXISTS ...")`. **재검토 시점**: Story 8 hardening.
- **DF81 — `_read_zip_fallback` CSV header schema 검증** [api/app/rag/food/seed.py:_read_zip_fallback] — header typo 시 모든 row의 `source_id`가 synthetic fallback로 빠짐 — silent corruption 위험. 첫 행 키 set이 expected schema와 정합 검증 + 비-graceful 환경에서는 raise. **재검토 시점**: Story 8 polish.

## Deferred from: code review of 3-2-가이드라인-rag-시드-chunking (2026-05-01)

- **DF84 — `pypdf` 6.10.2 vs spec/dev-notes `>=5.1` 가이드 drift** [api/uv.lock:1630 + api/pyproject.toml:41] — `>=5.1` 제약은 6.x 허용으로 lock 자체는 합법. spec/dev-notes는 5.1 동작 기준이지만 6.x로 한국어 PDF 추출 parity 미검증. PDF chunker는 MVP 시드 경로 호출 X(D1)이므로 prod 영향 0. pyproject `pypdf>=5,<7` 정합 또는 spec 갱신. **재검토 시점**: Story 8 polish 또는 외주 인수 PDF 자동 시드 활성화 시점.
- **DF85 — `verify_allergy_22.py` 하드코딩 MFDS CMS IDs 부패 방어** [scripts/verify_allergy_22.py:36-49] — `flSeq=42533884` / `bbs_no=bbs001` / `seq=31242` ephemeral CMS ID. 식약처 사이트 재구성 시 dead URL. 분기 SOP에서 운영자가 수동 검색하지만, `last_verified_at` 메타 + 식약처 별표 PDF 자동 다운으로 흡수. **재검토 시점**: Story 8.4 운영 SOP polish.
- **DF88 — `chunk_pdf` `for page in reader.pages` 루프가 try-block 외부 (lazy load 시점 leak)** [api/app/rag/chunking/pdf.py:48] — `PdfReader(...)` 생성자 try block 내부지만 `reader.pages` iteration은 외부. pypdf 6.x는 lazy load이므로 page 접근 시 `PdfReadError` 가능 → 외부로 leak하여 `GuidelineSeedAdapterError` 미래핑. PDF chunker는 MVP 시드 경로 호출 X(D1)로 운영 영향 0. **재검토 시점**: 외주 인수 PDF 자동 시드 활성화 시점.

## Deferred from: code review of 3-4-음식명-정규화-매칭-fallback (2026-05-03)

- **DF100 — `parse_meal._load_parsed_items_from_db` per-call session — retrieve_nutrition 세션과 batching 미실현 (per-analysis 2x connection churn)** [api/app/graph/nodes/parse_meal.py:32-49] — 한 분석 파이프라인 안에서 parse_meal과 retrieve_nutrition 노드가 각각 별도 `async with deps.session_maker()` 컨텍스트 → connection 2개 순차 점유. NFR-P4 ≤ 3s 게이트는 통과(현 측정 안전권)하지만 부하 시 pool 압박 가능. NodeDeps에 session 선택적 주입 패턴 또는 노드 간 단일 트랜잭션 공유 도입. **재검토 시점**: Story 8.4 운영 polish — Sentry latency p95 측정 후 + connection pool exhaustion alert 발동 시.
- **DF101 — `_mock_llm_adapters` fixture 4 모듈 중복 — DRY 위반, LLM 어댑터 추가 시 다중 touch point** [tests/services/test_analysis_service.py:28-50 + tests/graph/test_pipeline.py + tests/graph/test_self_rag.py + tests/test_main_lifespan.py] — 동일 mock 패턴(parse_meal_text + rewrite_food_query + generate_clarification_options)이 4 테스트 모듈에 복사. `tests/conftest.py`로 단일 SOT 추출 시 중복 제거 + 신규 LLM adapter 추가 시 단일 touch point. 본 스토리 회귀 0건 + 정상 동작. **재검토 시점**: Story 3.6(generate_feedback 실 LLM) 또는 Story 3.7(dual-LLM router) 도입 시점에 동시 conftest 통합.

## Deferred from: MFDS adapter integration verification (2026-05-03)

- **DF102 — 식약처 한식 면류 카테고리 보강 — `max_pages` 확대 + 가공식품 그룹 추가 fetch** [api/app/adapters/mfds_openapi.py] — 어댑터 재정확화(PR #22) 후 시드 결과 food_nutrition 679건 수집됐으나 한식 *면류* 카테고리 0건. 원인: (a) `max_pages=100`(=10K 행) 한도, (b) 한식 가정식 그룹(`DB_GRP_CM=D`)만 fetch — 라면 등은 가공식품 그룹(`DB_GRP_CM=P`)에 위치. **결정 (2026-05-05)**: 채택 — `max_pages` 100→500 확대 + `DB_GRP_CM=D`/`P` 양 그룹 병렬 fetch. 예상 추가 row ~50-100건(라면/우동/냉면 등 변형). **재검토 시점**: 결정-블록 해소, NOW-ACTIONABLE (DF103과 일괄, bootstrap_seed 재실행 + embedding 재생성 + eval dataset 재측정).
- **DF103 — 외식/배달 메뉴 핵심 50종 수동 CSV 보강 — 식약처 미지원 영역 SOT** [api/data/mfds_food_nutrition_seed.csv + api/data/README.md] — 짜장면/짬뽕/탕수육(중식) + 떡볶이/순대(분식) + 김밥 변형 다양화 등 *영업 데모 자주 등장하는 외식 메뉴*는 식약처 영양분석 대상이 아님(API 검색 totalCount=0). **결정 (2026-05-05)**: 영업 데모 임팩트 우선 50종 채택 — 짜장면/짬뽕/탕수육/마라탕/떡볶이/순대/김밥 변형 등. CSV 포맷은 어댑터 ZIP fallback 정합(name/category/energy_kcal/...). 데이터 출처: 농촌진흥청 식품성분 DB 또는 외식업체 영양정보 공시. 클라이언트 도메인 customization(예: 병원 환자식)은 인수 후 별도 SOP. **재검토 시점**: 결정-블록 해소, NOW-ACTIONABLE (DF102와 일괄).

## Deferred from: code review of 3-8-langsmith-옵저버빌리티-평가-데이터셋 (2026-05-04)

- **DF110 — `/tmp/eval.log` Linux-only 경로** [.github/workflows/ci.yml:307] — `langsmith-eval-regression` job이 `/tmp/eval.log`를 하드코딩. `runs-on: ubuntu-latest` 고정이라 즉시 위험 없으나 self-hosted runner 또는 Windows 마이그레이션 시 silent break. GitHub Actions 표준은 `$RUNNER_TEMP/eval.log`. **재검토 시점**: Story 8.4 운영 polish — CI runner 다양화 또는 Windows 도입 검토 시점.
- **DF111 — `docs/runbook/secret-rotation.md` §1,§2,§4-§7 placeholder** [docs/runbook/secret-rotation.md:2076-2086, 2141-2150] — Story 1.1에 부재였던 secret-rotation 문서를 본 스토리에서 최초 박았으나 LangSmith §3 외 5개 섹션(§1 OAuth, §2 OpenAI, §4 Anthropic, §5 PostgreSQL, §6 Redis, §7 Sentry)은 placeholder 상태. 운영자가 OpenAI 회전 절차 찾아도 빈 섹션. **재검토 시점**: Story 8.5 클라우드 배포 hardening — runbook 종합 정리 슬롯.

## Deferred from: code review of 4-3-web-주간-리포트-차트 (2026-05-06)

- **DF116 — 알레르기 substring 매칭 short labels (게/잣) false-positive 가드 누락** [api/app/domain/allergens.py:_LABEL_SUBSTRING_EXCLUSIONS] — 단일 문자 `잣` 또는 `게`(한국어 매우 흔한 음절 — `먹게`/`있게`/`사게`)가 22 알레르기 substring 매칭에서 광범위 false-positive 트리거. Story 3.5 SOT 확장 영역(본 스토리에서 단지 surfaced — 알레르기 노출이 차트로 사용자 가시화). **재검토 시점**: Story 8.4 polish 또는 Story 5.1 health profile 수정 시점에 word boundary 룰 추가.
- **DF117 — `weight_kg < 20` 또는 > 300 sanity clamp** [api/app/services/report_service.py:1228-1230 + api/app/db/models/user.py] — `weight_kg=0.0001`(rounding bug) 또는 9999.9(corrupt entry) 시 `protein_g_per_kg` blow up 또는 0.002 — ProteinChart 비현실 표시. User 모델 CHECK 제약 추가 영역. **재검토 시점**: Story 5.1 (건강 프로필 수정) 또는 Story 8.4 polish.
- **DF118 — Per-meal text length cap (DoS 방지)** [api/app/services/report_service.py:1244-1263] — 50,000자 raw_text 인입 시 22 알레르기 × NFC normalize 부하. 1인 8주 단일 노드는 acknowledged. **재검토 시점**: Story 8.5 클라우드 hardening.
- **DF119 — NFC normalize per-meal-once vs per-allergen 캐싱** [api/app/domain/allergens.py:contains_allergen] — 같은 텍스트에 22 알레르기 매칭 시 NFC normalize 22회 반복 — perf micro-opt. **재검토 시점**: Sentry latency p95 측정 후 NFR-P8 회귀 시.
- **DF120 — `기타` 알레르기 자연어 매칭 미스** [api/app/domain/allergens.py + service] — `_SKIP_SUBSTRING_LABELS = {"기타"}` 가드로 `"기타 알레르기 성분이 들어 있을 수 있습니다"` 자연어 텍스트가 `기타` 알레르기 사용자에게 노출 카운트 0. alias 룩업 SOT 확장 영역. **재검토 시점**: Story 3.5 SOT 보강 또는 Story 8.4.
- **DF121 — `monitored_allergies` 응답 필드 (legacy invalid 알레르기 클라이언트 표시 정합)** [api/app/services/report_service.py:WeeklyReportResponse + web/src/features/reports/AllergyExposureChart.tsx] — 사용자 `users.allergies`에 22-out-of-bounds 항목 있으면 백엔드 silently filter, 클라이언트는 raw 카운트 표시 — UI/server 표기 불일치. **재검토 시점**: Story 5.1 (allergies CHECK 제약 강화 정합).
- **DF122 — WeeklyReport 빈 응답 시 dashboard 복귀 링크** [web/src/features/reports/WeeklyReport.tsx + web/src/app/(user)/dashboard/weekly/page.tsx] — `report=null` fallback에 "대시보드로 돌아가기" 미제공 → dead-end UX. **재검토 시점**: Story 4.4 인사이트 카드 + 매크로 목표 조정 UX 통합 시.
- **DF123 — `from_date == to_date` 단일일 지원 명시화** [api/app/services/report_service.py + spec] — service는 0-30일 범위 일반화, AC10 spec은 7일 default 가정. Story 4.4 14일 트레일링 윈도우 활용 시 `daily_summaries.length` 비-7 케이스 클라이언트 가드 필요. **재검토 시점**: Story 4.4 인사이트 카드 시점.
- **DF124 — `parsed_items` non-dict shape structlog 경고** [api/app/services/report_service.py:1247-1251] — 레거시/스키마 드리프트로 `parsed_items` 항목이 dict가 아닐 때 silent partial info loss(매칭 텍스트에서 누락). **재검토 시점**: Story 8.4 polish.
- **DF125 — `protein_g_per_kg=0` 표시 명시 ("단백질 기록 없음")** [web/src/features/reports/ProteinChart.tsx] — meal_count > 0이지만 protein 0g 케이스 UX 모호 — 차트 + 표 모두 0.00 표시. **재검토 시점**: Story 4.4 인사이트 카드 차트 polish 시.
- **DF126 — 차트 Tooltip formatter 표준화** [web/src/features/reports/{Macro,Calorie,Protein}Chart.tsx] — recharts `<Tooltip />` 기본값으로 `399.99999` 등 raw 노출 가능. `formatter={(v) => v.toFixed(0)}` 표준화. **재검토 시점**: Story 8.4 UI polish.
- **DF127 — chartData `formatMmDd` 연도 경계** [MacroChart/CalorieChart/ProteinChart] — 7일 윈도우가 12-29 ~ 01-04 걸칠 때 라벨 정렬 비sortable + 연도 정보 누락. **재검토 시점**: 연말 윈도우 첫 실배포 시점 직전.
- **DF128 — `docs/runbook/web-perf-check.md` Lighthouse 실측** [docs/runbook/web-perf-check.md] — DS는 SOP만 명시. NFR-P8 1.5초 실측은 CR/QA 단계 책임 — 본 CR에서 environment 부재로 미수행. **재검토 시점**: Story 8.4 클라우드 배포 hardening 또는 영업 데모 직전.

## Deferred from: code review of 4-4-인사이트-카드-매크로-목표-조정 (2026-05-07)

- **DF129 — JSONB merge race: 동일 사용자 동시 PATCH 충돌** [api/app/api/v1/users.py:309-322] — `COALESCE(macro_goal, '{}'::jsonb) || :patch` merge는 optimistic concurrency 미적용. 두 PATCH가 동시에 다른 키를 갱신해도 `RETURNING`은 최후 commit 결과를 반환 → 일부 클라이언트 응답이 stale. 단일 사용자 환경에서 빈도 매우 낮아 본 스토리 미수정. **재검토 시점**: 동시 편집 UX(Story 7.x — 가족 공유 기능 또는 admin 패널) 도입 시.
- **DF130 — Mobile/web `lib/api-client.ts` SOT 중복** [mobile/lib/api-client.ts + web/src/lib/api-client.ts] — 두 파일 모두 `pnpm gen:api` 출력으로 byte-identical하나 별도 위치. 향후 백엔드 OpenAPI 변경 시 양쪽 동시 regen 책임이 휴먼 프로세스에 의존. **재검토 시점**: monorepo codegen 통합(Epic 5 또는 Epic 6 인프라 hardening).
- **DF131 — `fetch_user_profile`이 ValidationError만 catch (TypeError 경로 무방어)** [api/app/graph/nodes/fetch_user_profile.py:54-58] — `MacroGoal.model_validate(row.macro_goal)`이 dict가 아닌 입력에 대해 TypeError/AttributeError를 raise할 가능성. 0015 CHECK 제약이 `jsonb_typeof = 'object'` 강제로 진입 차단하므로 현재 위험 0. **재검토 시점**: legacy 마이그레이션(Pre-0015 row 존재 가능성) 또는 schema drift 점검 스토리.

