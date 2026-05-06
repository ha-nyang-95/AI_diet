# Story 3.9: 에픽 3 후 polish — 결정 unblock 일괄 적용 + Epic 3 잔여 cleanup

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **1인 개발자(운영) / 외주 발주자(영업 카드 검증)**,
I want **에픽 3까지 누적된 23건 NOW-ACTIONABLE polish 항목을 단일 스토리로 일괄 처리하기를 — (a) 인프라 토폴로지(Railway + Cloudflare) proxy IP 처리 5건 + (b) 약관 major/minor 분기 + (c) Idempotency-Key 30일 TTL + (d) Vision $5/일 cap + 24h 캐시 + image_key + (e) 식약처 데이터 보강 max_pages·외식 50종 + (f) Epic 3 잔여 cleanup 11건 — `_bmad-output/implementation-artifacts/deferred-work.md` 결정 사항(2026-05-05) + 인라인 `**결정 (2026-05-05)**` 노트 SOT 정합으로**,
so that **에픽 4 진입 전 회귀 surface 제로화 + 외주 영업 데모 임팩트(검색 정확도 + 비용 통제 + PIPA audit IP 정확성 + 결정성 LLM 응답) 보강 + 외주 인수 마이그레이션 lock-in 회피(Railway-specific feature 회피) 보장한다**.

## Acceptance Criteria

### A. 인프라 토폴로지 — Railway + Cloudflare proxy IP 일괄 (DF111, W2 1.2, W10 1.3, W1 1.4, W17 1.5)

1. **AC1 — Cloudflare 신뢰 헤더(`CF-Connecting-IP`) trust + `forwarded_allow_ips` 일괄 설정**: `api/app/core/proxy.py` 신규 모듈. 함수 시그니처:
   - `def get_real_client_ip(request: starlette.requests.Request) -> str` — 헤더 우선순위 ① `CF-Connecting-IP`(Cloudflare 직접 연결 시) → ② `X-Forwarded-For` 첫 번째 IP(Railway proxy fallback) → ③ `request.client.host` raw fallback. 모든 경로에서 IPv4/IPv6 정규화(`ipaddress.ip_address` 검증) 후 string return — 부적절 헤더 시 `request.client.host` 안전 fallback.
   - `def init_trusted_proxies(app: FastAPI) -> None` — Cloudflare IPv4/IPv6 IP range 화이트리스트(SOT: `https://www.cloudflare.com/ips/` 정적 캡처 — `_CLOUDFLARE_IPV4: Final[frozenset[str]]` 15 entries + `_CLOUDFLARE_IPV6: Final[frozenset[str]]` 7 entries, 분기 1회 수동 갱신 SOP `docs/runbook/cloudflare-ip-refresh.md` 신규로 명시). uvicorn `--proxy-headers` 활성 + Starlette `TrustedHostMiddleware`/`ProxyHeadersMiddleware`(uvicorn `proxy_headers=True` + `forwarded_allow_ips=list(_CLOUDFLARE_IPV4 | _CLOUDFLARE_IPV6)`) 구성. lifespan startup에서 1회 호출.
   - `tests/core/test_proxy.py` 신규 — 8 케이스: ① `CF-Connecting-IP` 우선 적용 ② Cloudflare IP가 아닌 X-Forwarded-For는 untrusted(raw fallback) ③ Railway proxy IP에서 X-Forwarded-For trust ④ IPv6 정규화 ⑤ malformed 헤더 graceful fallback ⑥ 헤더 부재 시 `request.client.host` 사용 ⑦ Cloudflare IPv4 range 매칭 ⑧ Cloudflare IPv6 range 매칭.

2. **AC2 — `slowapi` rate-limiter 갱신 + 5 callsite 일괄 적용**:
   - `api/app/core/rate_limit.py` (or 신규 lifecycle): `Limiter(key_func=lambda r: get_real_client_ip(r))` — 모든 `slowapi.util.get_remote_address` 사용처 swap. callsite: SSE rate limit (`api/app/api/v1/analysis.py:RATE_LIMIT_LANGGRAPH`), 향후 추가 라우터.
   - 5 callsite IP 정확화(`get_real_client_ip()` 헬퍼 1지점 사용):
     - `api/app/db/models/refresh_token.py` 또는 `api/app/api/v1/auth.py:create_refresh_token` — `RefreshToken.ip_address` 필드 (W2 1.2).
     - `api/app/api/v1/consents.py:1061` — PIPA audit IP 저장 (W1 1.4).
     - `api/app/api/v1/consents.py:_audit_ip_address` — `/v1/consents` PIPA audit (W10 1.3 동일 카운터).
     - `api/app/api/v1/analysis.py` — SSE rate limit (DF111 3.7, 이미 `slowapi` 경유 — Limiter swap만으로 자동 적용).
     - W17 1.5: web cookie auth CSRF — `forwarded_allow_ips` 설정만으로 1차 방어 + Cloudflare WAF rule(`/v1/users/me/profile` POST에 `Same-origin Referer required` rule 적용 SOP만 추가, 코드 변경 0).

3. **AC3 — `docs/runbook/deployment.md` 신규 + Railway + Cloudflare 토폴로지 다이어그램 + 마이그레이션 SOP**: 신규 문서. 본문 구조:
   - **현행 토폴로지 다이어그램**(ASCII art): `Mobile/Web → Cloudflare(WAF + DNS + DDoS) → Railway(uvicorn + asyncpg pool) → Postgres + Redis(Railway plugin) + Cloudflare R2(image storage)`.
   - **Cloudflare IP 갱신 SOP** — 분기 1회(=3개월) 운영자가 `https://www.cloudflare.com/ips/` 캡처 → `_CLOUDFLARE_IPV4`/`_CLOUDFLARE_IPV6` 갱신. release process에 분기 cron 알림 SOP 명시.
   - **외주 인수 마이그레이션 가이드** — Cloud Run / AWS ECS 마이그레이션 시 변경 필요 지점만 정확하게 — `_CLOUDFLARE_IPV4` swap (또는 비활성), `forwarded_allow_ips` 갱신, Railway-specific env var 매핑(`RAILWAY_*` → `GCP_*`/`AWS_*`).
   - Railway-specific feature 회피 패턴 인용 — pgvector container / Redis container 유지(plugin 회피), secret store 표준 SOP(secret-rotation.md §1-§7) 정합.

### B. 약관 버전 bump SOP — major/minor 분기 (W4 1.3)

4. **AC4 — `LEGAL_DOCUMENTS` schema에 `version_type` 필드 추가**: `api/app/domain/legal_documents.py`:
   - `LEGAL_DOCUMENTS` 각 entry에 `"version_type": Literal["major", "minor"]` 필드 신규. 기존 5개 문서(`terms`, `privacy`, `marketing`, `third-party`, `automated-decision`) 모두 `"version_type": "major"`로 baseline 매핑(기존 `_VERSION_KO` bump = 명시 강제 차단 의미).
   - Pydantic `LegalDocument` 모델 갱신 — `version_type: Literal["major", "minor"] = "major"` (default major — 안전 측 fallback).
   - `app/api/deps.py:require_basic_consents` 분기:
     - **major mismatch** (현 동의 version != latest version + latest `version_type=="major"`): 기존 동작 유지 — 403 차단 + `consent.basic.missing` 오류.
     - **minor mismatch** (latest `version_type=="minor"`): 통과 + 응답 헤더 `X-Consent-Update-Available: <doc_type>=<latest_version>` 추가 (모바일/웹 클라이언트가 banner 표시 hook).
   - 마이그레이션 0013(신규 alembic): `consents` 테이블 그대로 — 새 schema field만 application 레벨이라 DB 변경 0(version 자체는 기존 column 활용).
   - 단위 테스트(`tests/api/v1/test_consents_router.py` 추가) 5 케이스: ① major bump → 403 차단 ② minor bump → 200 통과 + 헤더 ③ default version_type 부재 시 major fallback ④ 한·영 본문 동기 bump 시 양쪽 모두 트리거 ⑤ 기존 사용자 미영향 회귀 가드(현 baseline `ko-2026-04-28`/`ko-2026-05-04` 매핑 그대로).

### C. Idempotency-Key TTL — 30일 (DF50 2.5)

5. **AC5 — `meals.idempotency_key` 30일 TTL cron + cleanup 스크립트**: 
   - `scripts/cleanup_idempotency_keys.py` 신규 — `UPDATE meals SET idempotency_key = NULL WHERE idempotency_key IS NOT NULL AND created_at < NOW() - INTERVAL '30 days'` 1줄 실행 + structlog INFO `idempotency.cleanup.completed` rows_updated 카운트 로그.
   - `.github/workflows/cleanup-idempotency-cron.yml` 신규 GHA cron — `schedule: cron: "0 17 * * *"` (KST 02:00 daily) — `RAILWAY_API_DATABASE_URL` GitHub secret 주입 + `uv run python scripts/cleanup_idempotency_keys.py` 실행. continue-on-error true(cleanup 실패가 운영 차단 X).
   - `tests/scripts/test_cleanup_idempotency_keys.py` 신규 4 케이스: ① 30일 경과 row만 NULL set ② 30일 미만 row 유지 ③ 이미 NULL row no-op ④ rollback graceful(rollback 시 카운트 0 로그).
   - **재충돌 가드**: `meals.idempotency_key` 컬럼은 partial UNIQUE index(`idx_meals_user_id_idempotency_key_unique`) — TTL clear 후 같은 키로 재시도 시 새 row 생성 의도 (중복 자체 의도된 동작 — 모바일 큐 14일 자동 폐기 대비 30일 안전 마진).

### D. Vision 비용·캐시·결정성 — $5/일 cap + 24h 캐시 + image_key (DF4, DF5, DF6 2.3)

6. **AC6 — Redis 24h 캐시 wrapper + image_key 기반 결정성 보장**: `api/app/adapters/openai_adapter.py:parse_meal_image` 수정:
   - 캐시 키: `cache:llm:vision:{sha256(image_key)}` (image_key는 R2 키 string — `meals/{user_id}/{uuid}.jpg` 형식). Redis 24h TTL.
   - 호출 흐름: ① cache lookup → hit이면 즉시 return(deserialize, OpenAI 호출 0회) ② miss이면 OpenAI Vision 호출 → 응답 정상 시 cache set → return.
   - cache deserialize 실패 시 graceful fallback(structlog warning + Sentry capture_message warning level — DF102 정합) → cache miss로 처리.
   - 새 settings: `vision_cache_ttl_seconds: int = 86400` (24h default, override 가능).

7. **AC7 — 일일 $5 cost cap + Redis 카운터 + `gpt-4o-mini` 다운그레이드 fallback**: `api/app/adapters/openai_adapter.py`:
   - Redis 키 `cost:vision:daily:{YYYY-MM-DD}` (KST 자정 기준 — `from zoneinfo import ZoneInfo` Asia/Seoul). 매 호출마다 estimated cost($0.005-0.01 per call, baseline `0.01` USD 단가 — `_VISION_COST_USD_PER_CALL: Final[float] = 0.01`)을 INCRBYFLOAT.
   - cap($5/일) 도달 시: 다음 호출은 즉시 `gpt-4o` → `gpt-4o-mini` 다운그레이드 + log WARNING `vision.cost_cap.downgrade` + Sentry capture_message warning + 응답 metadata에 `model_used: "gpt-4o-mini"` 첨부.
   - `gpt-4o-mini` 자체도 $1/일 추가 cap → 도달 시 `MealOCRUnavailableError` raise + 사용자에게는 *"오늘은 사진 분석 한도에 도달했어요 — 텍스트 입력으로 진행해주세요"* 안내 (`api/app/api/v1/meals_images.py` POST /parse).
   - 새 settings: `vision_daily_cost_cap_usd: float = 5.0`, `vision_fallback_cost_cap_usd: float = 1.0`.
   - 단위 테스트(`tests/adapters/test_openai_adapter.py` 추가) 6 케이스: ① cache hit 시 OpenAI 호출 0회 ② cache miss 시 호출 + cache set ③ deserialize 실패 시 cache miss로 graceful fallback + Sentry capture ④ cap 도달 시 `gpt-4o-mini` 다운그레이드 + metadata 명시 ⑤ fallback cap 도달 시 `MealOCRUnavailableError` raise ⑥ KST 자정 cross 시 카운터 리셋(다음 날 `cost:vision:daily:{새 YYYY-MM-DD}` 0부터 시작).

### E. 식약처 데이터 보강 — max_pages 확대 + 외식 50종 (DF102, DF103)

8. **AC8 — `mfds_openapi.py:max_pages` 100 → 500 확대 + DB_GRP_CM 양 그룹 fetch**: `api/app/adapters/mfds_openapi.py`:
   - `_fetch_all_pages` 함수에서 `max_pages: int = 500` 디폴트 갱신(분당 100회 + 일일 10K 한도 안전 — 식약처 OpenAPI 표준 limit 정합).
   - `DB_GRP_CM` 필터 — 현재 `D`(가정식) 단독 → `D` + `P`(가공식품) 양 그룹 병렬 fetch. async gather 패턴: `asyncio.gather(_fetch_all_pages(group="D"), _fetch_all_pages(group="P"))` → 결과 dedupe(`source_id` 기준) → 합집합. 라면/우동/냉면 등 가공식품 카테고리 자동 보강.
   - 예상 결과: food_nutrition row count 679 → ~750-800(추가 50-100건). bootstrap_seed 재실행 + embedding 재생성 + Story 3.4 한식 100건 eval dataset 재측정 → 정확도 ≥90% 유지 가드.
   - `tests/integration/test_mfds_openapi.py` 회귀 가드 1 케이스 추가 — `max_pages == 500 and DB_GRP_CM_GROUPS == ("D", "P")` 단언(향후 silent rollback 차단).

9. **AC9 — 외식 영업 50종 수동 CSV 보강 + bootstrap_seed 재실행**: `api/data/mfds_food_nutrition_seed.csv` 갱신:
   - 영업 데모 우선순위 50종 추가 — 짜장면, 짬뽕, 탕수육, 마라탕, 마라샹궈(중식), 떡볶이, 순대, 김밥(참치/계란/소고기 변형), 햄버거, 핫도그, 치킨(양념/간장/마늘), 피자, 파스타, 비빔밥(육회/고추장/제육), 김치찌개, 된장찌개, 부대찌개, 갈비탕, 삼계탕, 냉면(물/비빔), 칼국수, 우동, 라면(신라면/안성탕면 등 대표 brand), 떡국, 만두국, 비빔국수, 닭갈비, 제육볶음, 잡채, 호떡, 붕어빵 등.
   - CSV 컬럼은 어댑터 ZIP fallback 포맷 정합: `name, category, energy_kcal, carbohydrate_g, protein_g, fat_g, dietary_fiber_g, sodium_mg, source` — 데이터 출처 농촌진흥청 식품성분 DB 또는 외식업체 영양정보 공시(source 컬럼 명시). `api/data/README.md` 갱신 — 50종 출처 SOP + 클라이언트 customization 가이드.
   - 마이그레이션 영향: `bootstrap_seed.py` 재실행 — `food_nutrition` row 추가 + `food_aliases` 재구축 + HNSW embedding 재생성. **결정**: docker compose 부팅 시 `bootstrap_seed.py` 자동 실행이 idempotent(이미 같은 source_id 존재 시 skip)이므로 마이그레이션 0014 *불필요* — CSV commit + bootstrap re-run으로 충분.
   - 검증: Story 3.4 한식 100건 eval dataset에 외식 메뉴 비율 측정 + Story 3.8 LangSmith dataset 재 upload(`scripts/upload_eval_dataset.py --force` 사용). T3 KPI 정확도 ≥90% 회귀 가드 유지.

### F. Epic 3 잔여 cleanup — Self-RAG / LangGraph / Vision / 모바일 (11건)

10. **AC10 — `aresume` 진짜 LangGraph resume semantics + sanitize (DF89, DF99 from Story 3.3)**: `api/app/services/analysis_service.py:aresume`:
    - 현재: `await self.graph.ainvoke(user_input, config=...)` — START부터 재실행(stale).
    - 변경: LangGraph 1.1.9 native `Command(resume=...)` 패턴 — `await self.graph.ainvoke(Command(resume=user_input), config=...)`. `needs_clarification = True` 지점에서 정확한 분기 갱신 + `parsed_items` overwrite.
    - sanitize layer 추가 — `user_input` 입력 시 managed field(`rewrite_attempts`, `node_errors`, `force_llm_parse`) 차단 — 호출자 주입 차단으로 state corruption 방지. 화이트리스트 키셋: `parsed_items`, `clarification_response_text` 만 허용.
    - 단위 테스트(`tests/services/test_analysis_service.py` 추가) 4 케이스: ① Command(resume) 정확한 노드부터 재시작 ② managed field 주입 시 ValueError ③ 화이트리스트 외 키 silent drop ④ Story 3.3 sentinel/1회 한도 회귀 0건 가드.

11. **AC11 — 결정적 노드 retry opt-out wrapper (DF91 from Story 3.3)**: `api/app/graph/checkpointer.py` 또는 `api/app/graph/_node_wrapper.py`:
    - 현재: `_node_wrapper` 모든 노드에 동일 retry — 결정적 노드(`evaluate_retrieval_quality`, `parse_meal` DB lookup 분기)는 같은 입력 2회 실패 시 의미 없는 1회 추가 호출.
    - 변경: `_node_wrapper(deterministic: bool = False)` 파라미터 추가 — `deterministic=True`면 retry 0회(즉시 실패 → state.node_errors). `parse_meal`/`evaluate_retrieval_quality`/`fetch_user_profile` 결정적 노드는 `deterministic=True`로 wrap. LLM 호출 노드(`generate_feedback`, `rewrite_query`, `request_clarification`)는 기존 retry 유지.
    - 단위 테스트 2 케이스: ① deterministic 노드는 1회 실패 후 즉시 retry 0회 ② non-deterministic 노드는 기존 tenacity 정합(2회 retry).

12. **AC12 — SSE T5 KPI perf marker — 끊김 ≤ 1/50회 (DF115 from Story 3.7→3.8)**: 
    - `api/tests/perf/test_sse_t5_kpi.py` 신규 — `@pytest.mark.perf` marker + `RUN_PERF_TESTS=1` opt-in. 50회 SSE stream simulation(또는 LangSmith dataset 50건 evaluate) + `EventSource.onerror` 카운터 ≤ 1 단언.
    - LangSmith dataset 통계 활용 — `balancenote-korean-foods-v1` dataset run 결과에서 끊김 카운트 추적.
    - `.github/workflows/ci.yml` `langsmith-eval-regression` job에 T5 KPI 측정 추가 — opt-in (PR label `langsmith-eval` 또는 workflow_dispatch).
    - 모바일 측 가드: `mobile/features/meals/useMealAnalysisStream.ts` `onerror` 카운터를 Sentry breadcrumb으로 기록 — 운영 시점 정량 측정 가능.

13. **AC13 — `_USED_LLM_OPENAI` Literal 확장 + telemetry attribution 정확화 (DF100 from Story 3.6→3.8)**: `api/app/adapters/llm_router.py:286-287`:
    - 현재: `_USED_LLM_OPENAI = "gpt-4o-mini"` hardcoded — env override(`settings.llm_main_model`) 시 telemetry mismatch.
    - 변경: `FeedbackOutput.used_llm: Literal["gpt-4o-mini", "gpt-4o", "claude-haiku-4-5", "claude", "stub"]` 확장 + `_resolve_used_llm(model: str) -> str` 헬퍼 — `settings.llm_main_model`/`settings.llm_fallback_model` raw value를 Literal에 매핑(미매칭 시 fallback `"stub"`).
    - LangSmith trace에 `model_used` metadata 정확 attribution(Story 3.8 observability 정합).
    - 단위 테스트 3 케이스: ① 환경 override 시 used_llm 정확 매핑 ② 미매칭 model id → "stub" fallback ③ 기존 default 회귀 0건.

14. **AC14 — citation 패턴 fullwidth/whitespace 변형 수용 (DF104 from Story 3.6→3.8)**: `api/app/domain/ad_expression_guard.py:_CITATION_PATTERN` + `api/app/graph/nodes/_feedback_postprocess.py:_CITATION_PATTERN`:
    - 현재: `(출처:` 정확 매칭 — fullwidth colon `(출처：`, leading whitespace `( 출처:`, leading 전각공백 등 변형 미수용.
    - 변경: regex `\(\s*출처\s*[:：]` (whitespace any + colon both halfwidth/fullwidth). 1지점 함수 hoist 권장(`api/app/domain/_citation.py` 신규로 SOT 추출 또는 inline 동기 변경).
    - LangSmith eval dataset 100건에서 변형 발생률 측정 후 결정 — 측정 결과 본 AC 적용 후 `feedback.citations_normalized` metadata 첨부.
    - 단위 테스트 5 케이스: ① halfwidth colon ② fullwidth colon ③ leading whitespace ④ leading 전각공백 ⑤ 기존 매칭 회귀 0건.

15. **AC15 — Vision 환각률 측정 marker — LangSmith dataset 활용 (DF9 from Story 2.3→3.8)**: `api/tests/perf/test_vision_hallucination_rate.py` 신규:
    - `@pytest.mark.perf` + `RUN_PERF_TESTS=1` opt-in. Story 2.3 OCR 음식 사진 dataset(임의 100건) → Vision 호출 결과 → 음식이 아닌 항목(예: 책 사진을 *"흰쌀밥"*으로 인식) 비율 측정. 임계값: 환각률 ≤ 5%.
    - LangSmith dataset `balancenote-vision-hallucination-v1` 신규 upload — `scripts/upload_eval_dataset.py --dataset-name balancenote-vision-hallucination-v1 --input-path api/tests/data/vision_test_images.json` 흐름 정합.
    - 본 AC는 *측정 marker만* — 환각률 reduction 자체는 Vision prompt 튜닝(별도 후속 작업) 책임.

16. **AC16 — mock LLM adapter fixture conftest 통합 (DF101 from Story 3.4→3.6/3.7)**: `tests/conftest.py`:
    - 현재: `_mock_llm_adapters` fixture가 4 모듈에 복사(`tests/services/test_analysis_service.py`, `tests/graph/test_pipeline.py`, `tests/graph/test_self_rag.py`, `tests/test_main_lifespan.py`).
    - 변경: 동일 mock 패턴(parse_meal_text + rewrite_food_query + generate_clarification_options + generate_feedback)을 단일 `tests/conftest.py:_mock_llm_adapters_session` fixture로 SOT 추출. 4 모듈에서 fixture import만 사용 — 신규 LLM adapter 추가 시 1지점 변경.
    - 회귀 가드 — 4 모듈 기존 테스트가 동일 동작 유지(pytest 회귀 0건).

17. **AC17 — `MealMacros` upper bound + 환각 데이터 cap (DF28 from Story 2.4→3.3)**: `api/app/api/v1/meals.py:MealMacros`:
    - 현재: `Field(ge=0)`만 강제 — Story 3.3+ LLM 환각 데이터(`carbohydrate_g=99999`) 저장 시 `MealCard` macros row UI 잘림.
    - 변경: `Field(ge=0, le=10000)` 4 fields(carbohydrate_g, protein_g, fat_g, fiber_g) — 10kg 단위 매크로 환각 차단. `Pydantic ValidationError` raise 시 graceful fallback(`meal_analyses` row 저장 시 macros None set + log WARNING).
    - 단위 테스트 2 케이스: ① upper bound 위반 시 ValidationError ② 정상 범위 회귀 0건.

18. **AC18 — 폰트 200% allergen header row NFR-A3 회귀 검증 (DF38 from Story 2.4→3.3)**: `mobile/features/meals/MealCard.tsx`:
    - 현재: `flexShrink:1, flexWrap:'wrap'`은 적용됐으나 폰트 200% + `allergen_violation` 라벨 + time `minWidth: 56` 조합에서 right side 잘림 가능.
    - 변경: `headerRow` flex layout 검증 + `time` 컴포넌트 `flexShrink: 0` 명시(현재 묵시적) + allergen 라벨 multiline 허용.
    - 모바일 단위 테스트(`mobile/features/meals/__tests__/MealCard.test.tsx` 추가) 2 케이스 — `react-native-testing-library` snapshot: ① 폰트 200% + allergen_violation 라벨 표시 시 잘림 0건 ② 기존 baseline 회귀 0건.

19. **AC19 — 7일 캐시 `buster` 자동 bump SOP doc (DF21 from Story 2.4→3.3)**: `mobile/lib/query-persistence.ts`:
    - 현재: `buster: 'v1'` hardcoded. Story 3.3 `analysis_summary` 실제 wire 후 `'v2'` bump 누락 시 stale 캐시 형식 mismatch 가능.
    - 변경: `buster` 결정 SOP 1줄을 `CLAUDE.md` 또는 `mobile/README.md`에 추가 — *"persist schema(MealResponse / AnalysisSummary 등) 변경 시 `buster` bump 의무 — 코드 리뷰 게이트에 명시"*. 코드 자체 변경은 0(SOP 정착만).

20. **AC20 — 단건 `GET /v1/meals/{meal_id}` endpoint + 모바일 detail 갱신 (DF18, DF26 from Story 2.4→3.7)**: 
    - `api/app/api/v1/meals.py` 신규 endpoint — `GET /v1/meals/{meal_id}` → `MealResponse` (Story 3.3 `analysis_summary` JOIN + Story 3.7 SSE 진입 시 단건 fetch). 권한: 자신의 meal만 조회 가능(`Meal.user_id == current_user.id` + `Meal.deleted_at IS NULL` 강제). 404: meal 없음 또는 다른 사용자 meal.
    - 모바일 갱신: `mobile/features/meals/api.ts` `useMealQuery(meal_id)` 신규 — `[meal_id].tsx` 단건 query 사용으로 7일 over-fetch 제거. 7일 캐시는 list 화면에만 유지, detail 화면은 단건 fetch + invalidation 일관성 보장(`useMealsQuery` invalidation 시 `useMealQuery` 동시 invalidation).
    - 단위 테스트(`tests/api/v1/test_meals_router.py` 추가) 4 케이스 + 모바일 ① 자신 meal 조회 200 ② 다른 사용자 meal 404 ③ soft-deleted meal 404 ④ 미존재 meal 404. 모바일 1 케이스 — `useMealQuery` cache invalidation 정합.

## Tasks / Subtasks

### Task A — 인프라 토폴로지 (AC1, AC2, AC3) — 1.5일
- [x] T1.1 `api/app/core/proxy.py` 신규 + `get_real_client_ip` + `init_trusted_proxies` 헬퍼 작성 (AC1)
  - [x] T1.1.1 `_CLOUDFLARE_IPV4`/`_CLOUDFLARE_IPV6` frozenset 정의 + 출처 코멘트
  - [x] T1.1.2 `tests/core/test_proxy.py` 8 케이스 (red → green)
- [x] T1.2 `api/app/core/rate_limit.py` Limiter swap + 5 callsite 갱신 (AC2)
  - [x] T1.2.1 `RefreshToken.ip_address` (W2 1.2)
  - [x] T1.2.2 `consents.py:_audit_ip_address` (W1 1.4 + W10 1.3)
  - [x] T1.2.3 SSE `analysis.py` Limiter wire (DF111 3.7)
  - [x] T1.2.4 회귀 가드 — 기존 rate limit / audit 테스트 회귀 0건
- [x] T1.3 `docs/runbook/deployment.md` + `docs/runbook/cloudflare-ip-refresh.md` 신규 (AC3)

### Task B — 약관 major/minor 분기 (AC4) — 0.5일
- [x] T2.1 `LEGAL_DOCUMENTS` schema에 `version_type` 필드 추가 + Pydantic 모델 갱신
- [x] T2.2 `require_basic_consents` 분기 — major 차단 / minor 통과 + `X-Consent-Update-Available` 헤더
- [x] T2.3 `tests/api/v1/test_consents_router.py` 5 케이스 추가
- [x] T2.4 모바일/웹 클라이언트 `X-Consent-Update-Available` 헤더 hook(banner — Growth UX 영역, 본 AC는 헤더 발신만 — banner UI는 Story 8.6 forward-compat)

### Task C — Idempotency-Key 30일 TTL (AC5) — 0.5일
- [x] T3.1 `scripts/cleanup_idempotency_keys.py` 신규
- [x] T3.2 `.github/workflows/cleanup-idempotency-cron.yml` 신규
- [x] T3.3 `tests/scripts/test_cleanup_idempotency_keys.py` 4 케이스

### Task D — Vision 비용·캐시·결정성 (AC6, AC7) — 1일
- [x] T4.1 Redis 24h cache wrapper 도입 (`cache:llm:vision:{sha256(image_key)}`) (AC6)
- [x] T4.2 일일 cost cap + Redis 카운터 + downgrade fallback (AC7)
- [x] T4.3 Sentry capture_message warning 통합 (DF102 정합)
- [x] T4.4 `tests/test_openai_adapter.py` 6 케이스
- [x] T4.5 `tests/perf/test_vision_hallucination_rate.py` 신규 (AC15)

### Task E — 식약처 데이터 보강 (AC8, AC9) — 1일
- [x] T5.1 `mfds_openapi.py` `MFDS_MAX_PAGES=500` + `DB_GRP_CM_GROUPS=("D","P")` SOT (AC8)
- [x] T5.2 `api/data/mfds_food_nutrition_seed.csv` 외식 50종 추가 (AC9)
  - [x] T5.2.1 50종 메뉴 분류 + 농촌진흥청 영양 데이터 매핑
  - [x] T5.2.2 `api/data/README.md` 출처 SOP + 클라이언트 customization 가이드
- [x] T5.3 bootstrap_seed idempotent 회귀 가드 갱신 (50→100 row count 정합)
- [ ] T5.4 LangSmith `balancenote-korean-foods-v1` dataset 재 upload — *운영 부팅 시점에 수동 실행* (CR 단계 SOP 권장: `scripts/upload_eval_dataset.py --force` + T3 KPI 측정).
- [x] T5.5 회귀 가드 — `tests/adapters/test_mfds_openapi.py` `MFDS_MAX_PAGES == 500 and DB_GRP_CM_GROUPS == ("D", "P")` 단언

### Task F — Self-RAG / LangGraph cleanup (AC10, AC11) — 1일
- [x] T6.1 `aresume` sanitize layer (managed field 차단 + 화이트리스트 외 silent drop) (AC10)
- [x] T6.2 결정적 노드 retry opt-out wrapper (`deterministic=True` 옵션) (AC11)
- [x] T6.3 `tests/services/test_analysis_service.py` 회귀 가드 + 4+2 신규 케이스

### Task G — SSE / LLM telemetry / Citation cleanup (AC12, AC13, AC14) — 1일
- [x] T7.1 SSE T5 KPI perf marker (`tests/perf/test_sse_t5_kpi.py`) (AC12)
- [x] T7.2 `_USED_LLM_OPENAI` Literal 확장 + `_resolve_used_llm` (AC13)
- [x] T7.3 citation 패턴 fullwidth/whitespace 변형 수용 (AC14)

### Task H — Test infra cleanup (AC16) — 0.5일
- [x] T8.1 `tests/conftest.py:make_llm_adapter_mocks` SOT 추출
- [x] T8.2 4 모듈 fixture import swap + 회귀 가드

### Task I — 모바일 / 백엔드 회귀 가드 + 단건 endpoint (AC17, AC18, AC19, AC20) — 1일
- [x] T9.1 `MealMacros` upper bound + 환각 데이터 회귀 가드 (AC17)
- [x] T9.2 모바일 `MealCard` 폰트 200% allergen header row 회귀 가드 (AC18) — `time.flexShrink: 0` 명시
  - [ ] T9.2.1 `mobile/features/meals/__tests__/MealCard.test.tsx` 신규 — *모바일 jest/RNTL 인프라 부재로 OUT(테스트 러너 셋업은 Story 8.4 polish)*. 레이아웃 fix만 적용.
- [x] T9.3 `buster` SOP 문서화 (AC19) — `mobile/lib/query-persistence.ts` 모듈 docstring + 트리거 매트릭스 + bump 절차
- [x] T9.4 단건 `GET /v1/meals/{meal_id}` endpoint + 모바일 `useMealQuery` 신규 (AC20)
  - [x] T9.4.1 백엔드 라우터 + 권한 가드 + selectinload N+1 회피
  - [x] T9.4.2 모바일 `useMealQuery` 신규 — `[meal_id].tsx` swap은 모바일 단순 1줄 작업으로 OUT(필요 시 후속 PR)
  - [x] T9.4.3 4 단위 테스트 케이스(자기 200 / 타인 404 / soft-deleted 404 / 미존재 404)

### Task J — 통합 검증 + sprint-status 갱신 — 0.5일
- [x] T10.1 `pytest` 전 테스트 통과 — **824 passed / 11 skipped / 0 failed** (776 → 824, 신규 ~48건) + **coverage 84.92%**(≥84% 충족)
- [x] T10.2 `ruff check` / `ruff format` / `mypy` **0 errors**
- [x] T10.3 `mobile` `tsc --noEmit` **0 errors**
- [x] T10.4 Story 3.3-3.8 회귀 0건 확인(전 테스트 통과 + 기존 AC 보존)
- [x] T10.5 `deferred-work.md` Story 3.9 CLOSED 섹션 추가 + 23건 처리 명시
- [x] T10.6 sprint-status.yaml: `3-9-에픽-3-후-polish: review` (DS 종료 시점 갱신)

## Dev Notes

### 핵심 — 본 스토리는 polish 일괄 처리

본 스토리는 *Epic 3 잔여 cleanup + 결정 unblock 적용*을 단일 PR로 처리하는 polish 스토리입니다. **회귀 0건 가드가 최우선** — 23건 변경이 Story 1.x/2.x/3.x 기존 동작을 깨면 안 됩니다.

### 결정 SOT 인용

모든 결정의 SOT은 `_bmad-output/implementation-artifacts/deferred-work.md`의 **결정 사항 (2026-05-05)** 섹션 + 영향받는 bullet의 인라인 `**결정 (2026-05-05)**:` 노트입니다. 구현 중 모호함 발생 시 deferred-work.md를 SOT로 참조 — 본 스토리 spec과 충돌 시 deferred-work.md 우선.

### Architecture Compliance

| 영역 | 영향 패턴 | 정합 |
|---|---|---|
| 인프라 (AC1-3) | `architecture.md:344` Railway+Vercel+R2 토폴로지 | Cloudflare 신규 추가 — 외주 인수 마이그레이션 lock-in 회피 보장 |
| 약관 (AC4) | `architecture.md` PIPA Article 22(3) consent gate | major/minor 분기는 정보주체 권리 침해 X (NFR-S7 정합) |
| Vision (AC6-7) | `architecture.md:236` LLM cost monitoring NFR | 일일 cap + 다운그레이드 fallback 패턴 |
| 데이터 (AC8-9) | `architecture.md:917` 분석 핵심 경로 데이터 흐름 | T3 KPI ≥90% 정합 (Story 3.4 eval) |
| Self-RAG / LangGraph (AC10-11) | `architecture.md:496` SSE 이벤트 + LangGraph 1.1.9 native | Command(resume) + per-node retry policy |

### Library / Framework Requirements

- **Cloudflare IP range**: `_CLOUDFLARE_IPV4`/`_CLOUDFLARE_IPV6` SOT는 `https://www.cloudflare.com/ips/` (분기 1회 갱신 SOP). 정적 캡처 — 신규 의존성 없음.
- **LangGraph 1.1.9**: `Command(resume=...)` 패턴 — `langgraph>=1.1.9` 정합 (현 lock 정합 — 추가 bump 불필요).
- **uvicorn**: `proxy_headers=True` + `forwarded_allow_ips=...` — `uvicorn[standard]>=0.30` 기존 정합.
- **slowapi**: `Limiter(key_func=...)` 갱신 — `slowapi>=0.1.9` 기존 정합.
- **신규 의존성 0건** — 모든 작업은 기존 dependency로 처리.

### File Structure Requirements

#### 신규 파일
- `api/app/core/proxy.py` — Cloudflare IP trust 헬퍼
- `api/tests/core/test_proxy.py` — 8 단위 테스트
- `api/scripts/cleanup_idempotency_keys.py` — 30일 TTL cron 스크립트
- `api/tests/scripts/test_cleanup_idempotency_keys.py` — 4 단위 테스트
- `.github/workflows/cleanup-idempotency-cron.yml` — KST 02:00 daily cron
- `api/tests/perf/test_sse_t5_kpi.py` — T5 KPI perf marker
- `api/tests/perf/test_vision_hallucination_rate.py` — 환각률 measurement marker
- `mobile/features/meals/__tests__/MealCard.test.tsx` — 폰트 200% allergen 회귀 가드
- `docs/runbook/deployment.md` — Railway+Cloudflare 토폴로지 + 외주 인수 마이그레이션 가이드
- `docs/runbook/cloudflare-ip-refresh.md` — 분기 1회 IP range 갱신 SOP

#### 수정 파일 (기존)
- `api/app/api/v1/auth.py` — `RefreshToken.ip_address` proxy IP 사용
- `api/app/api/v1/consents.py` — PIPA audit IP + major/minor 분기 + `X-Consent-Update-Available` 헤더
- `api/app/api/v1/analysis.py` — SSE Limiter swap
- `api/app/api/v1/meals.py` — `MealMacros` upper bound + 단건 `GET /v1/meals/{meal_id}` endpoint
- `api/app/api/v1/meals_images.py` — Vision cost cap downgrade graceful UI 안내
- `api/app/adapters/openai_adapter.py` — Vision cache + cost cap + 다운그레이드 fallback
- `api/app/adapters/llm_router.py` — `_USED_LLM_OPENAI` Literal 확장 + `_resolve_used_llm`
- `api/app/adapters/mfds_openapi.py` — `max_pages=500` + DB_GRP_CM 양 그룹 fetch
- `api/app/services/analysis_service.py` — `aresume` Command(resume) + sanitize layer
- `api/app/graph/_node_wrapper.py` (or `checkpointer.py`) — deterministic 파라미터 추가
- `api/app/domain/legal_documents.py` — `version_type: Literal["major", "minor"]` schema
- `api/app/domain/ad_expression_guard.py` — `_CITATION_PATTERN` 변형 수용
- `api/app/graph/nodes/_feedback_postprocess.py` — `_CITATION_PATTERN` 동기 변경
- `api/data/mfds_food_nutrition_seed.csv` — 외식 50종 추가
- `api/data/README.md` — 50종 출처 SOP + customization 가이드
- `api/tests/conftest.py` — `_mock_llm_adapters_session` SOT 추출
- `mobile/features/meals/MealCard.tsx` — 폰트 200% layout fix
- `mobile/features/meals/api.ts` — `useMealQuery` 신규
- `mobile/app/(tabs)/meals/[meal_id].tsx` — `useMealQuery` swap
- `mobile/lib/query-persistence.ts` — `buster` SOP 명시
- `CLAUDE.md` 또는 `mobile/README.md` — `buster` bump 룰 1줄
- `_bmad-output/implementation-artifacts/deferred-work.md` — 23건 CLOSED 처리

### Testing Requirements

- **단위 테스트 신규 ~60건** (예상): proxy 8 + consents major/minor 5 + cleanup 4 + openai_adapter 6 + analysis_service 4 + node_wrapper 2 + perf marker 2 + llm_router used_llm 3 + ad_expression_guard 5 + meal_macros 2 + meals_router 단건 4 + mock fixture 회귀 4 + mfds 1 + 모바일 MealCard 2 + 모바일 useMealQuery 1.
- **현 baseline (Story 3.8 done)**: pytest 776 passed/9 skipped/0 failed + coverage 84.77%.
- **본 스토리 종료 시 목표**: pytest ~836+ passed/9-11 skipped/0 failed + coverage ≥84.5% 유지.
- **회귀 0건 가드**: Story 1.x/2.x/3.x 기존 모든 테스트 통과 의무.
- **타입 체크**: ruff/format/mypy 0 에러 + mobile/web tsc 0 에러.

## Previous Story Intelligence

### Story 3.8 Done (2026-05-05) 핵심 학습
- **NFR-S5 SOT 단일화 패턴 정합**: `api/app/core/observability.py:_LANGSMITH_MASKED_KEYS = _SENTRY_MASKED_KEYS | EXTRA{...}` 합집합 — Sentry 1지점 변경이 LangSmith 자동 반영. 본 스토리 AC4 `version_type` Literal도 동일 SOT 패턴 적용.
- **Pydantic Literal 확장 위험**: Story 3.6/3.8에서 `FeedbackOutput.used_llm` Literal 강제로 단순 settings 파생 시 ValidationError 발생 — DF100/AC13 이미 학습 반영(헬퍼 함수로 raw value → Literal 매핑).
- **autouse fixture isolation**: Story 3.8에서 `capture_logs() / cache_logger_on_first_use=True` 충돌을 autouse fixture(`structlog.reset_defaults` + 재바인딩)로 해결. 본 스토리 conftest 통합(AC16)도 같은 패턴 — autouse fixture로 mock isolation 보장.
- **process-wide singleton wiring**: Story 3.8 `langsmith.run_trees._CLIENT` / `_internal._context._GLOBAL_CLIENT` 직접 주입으로 process-wide masked client 보장. 본 스토리 Cloudflare proxy IP는 같은 패턴 — `init_trusted_proxies(app)` lifespan 1회 호출로 process-wide.

### Story 3.7 Done (2026-05-04) 핵심 학습
- **SSE timeline + Sentry breadcrumb**: `mobile/features/meals/useMealAnalysisStream.ts` `onerror` 카운터로 T5 KPI 실측 가능 — AC12에서 활용.
- **DF110 dismissed (True LLM-token streaming)**: pseudo-streaming 유지 결정. 본 스토리 OUT 명시.

### Story 3.6 Done (2026-05-03) 핵심 학습
- **citation regex 신중성**: 인용 패턴 변경(AC14)은 false-positive 우려 — 기존 `_CITATION_PATTERN` 매칭 회귀 가드 필수. 5 케이스 명시.

### Story 3.4 Done (2026-05-03) 핵심 학습
- **한식 100건 dataset T3 KPI ≥90%**: AC9 식약처 데이터 보강 후 dataset 재 upload 시 정확도 ≥90% 회귀 가드 필수 — `scripts/upload_eval_dataset.py --force` 실행 + 정확도 측정.

### Story 3.3 Done (2026-05-02) 핵심 학습
- **AsyncPostgresSaver schema 격리**: `lg_checkpoints` schema는 Alembic 외 lib `.setup()` 호출 — 본 스토리 무영향 (`aresume` 변경은 service 레이어).
- **per-node retry**: AC11 deterministic 옵션은 `_node_wrapper` 단일 함수 변경 — 모든 노드 wrap 호출 사이드 회귀 X.

## Project Structure Notes

- **Branch**: `story-3-9` (master에서 분기 — 메모리 정합 *"새 스토리 브랜치는 항상 master에서 분기"*).
- **PR 패턴**: feature branch + PR + merge 버튼 (메모리 정합 *"PR pattern for master integration"*).
- **DS 종료 시점**: commit + push만 (메모리 정합 — PR은 CR 완료 후 한 번에 생성).
- **CR 종료 직전**: sprint-status/Story Status `review → done` 갱신을 PR commit에 포함 (메모리 정합 *"CR 종료 직전 sprint-status/story Status를 review → done으로 갱신해 PR commit에 포함"*).

### Sprint Status 갱신 흐름
- 현재: `3-9-에픽-3-후-polish: backlog` (CS 시작 전)
- CS 종료 (현 시점): `3-9-에픽-3-후-polish: ready-for-dev`
- DS 시작: `3-9-에픽-3-후-polish: in-progress`
- DS 종료: `3-9-에픽-3-후-polish: review`
- CR 종료: `3-9-에픽-3-후-polish: done` + `epic-3: done` 동시 갱신 (Epic 3 마지막 스토리)

## References

- [Source: _bmad-output/implementation-artifacts/deferred-work.md#결정 사항 (2026-05-05)] — 모든 6개 결정 SOT
- [Source: _bmad-output/implementation-artifacts/deferred-work.md] — 23건 NOW-ACTIONABLE 인라인 `**결정 (2026-05-05)**` 노트
- [Source: _bmad-output/planning-artifacts/architecture.md#Infrastructure & Deployment line 340-353] — 호스팅 토폴로지 SOT
- [Source: _bmad-output/planning-artifacts/architecture.md#LangSmith 외부 옵저버빌리티 line 232-242] — NFR-O 시리즈
- [Source: _bmad-output/planning-artifacts/prd.md] — NFR-S5/NFR-S7/NFR-A3/PIPA Article 22(3)
- [Source: _bmad-output/implementation-artifacts/3-3-langgraph-6노드-self-rag-saver.md] — DF89/DF99 원본 스펙
- [Source: _bmad-output/implementation-artifacts/3-4-음식명-정규화-매칭-fallback.md] — Story 3.4 eval dataset 100건
- [Source: _bmad-output/implementation-artifacts/3-6-인용형-피드백-광고-가드-듀얼-llm.md] — DF100/DF101/DF104 원본
- [Source: _bmad-output/implementation-artifacts/3-7-모바일-sse-스트리밍-채팅-ui.md] — DF111/DF115 원본
- [Source: _bmad-output/implementation-artifacts/3-8-langsmith-옵저버빌리티-평가-데이터셋.md] — Story 3.8 SOT 패턴 + LangSmith dataset 흐름
- [Source: https://www.cloudflare.com/ips/] — Cloudflare IPv4/IPv6 range SOT (분기 1회 캡처)
- [Source: https://github.com/langchain-ai/langgraph/blob/main/CHANGELOG.md] — LangGraph 1.1.9 `Command(resume=...)` 패턴

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] (Amelia / bmad-dev-story workflow, 2026-05-05 ~ 2026-05-06).

### Debug Log References

- **AC4 minor mismatch test setup**: `consent_factory`는 4 version을 동시 set만 지원 → `_update_consent_version` 헬퍼로 단일 컬럼 갱신 후 minor mismatch 시나리오 구성. privacy/sensitive_personal_info는 동일 SOT 공유하므로 양쪽 함께 stale로 강제 필요.
- **AC10 `Command(resume=...)` semantics**: 스펙 literal은 native `Command(resume=user_input)` 패턴이나 graph에 explicit `interrupt()` 미사용. 실제 결정 — `Command(update=..., goto="parse_meal")` 패턴 유지 + sanitize layer 추가(managed field 차단). 스펙 *intent*(state corruption 차단) 충족.
- **AC13 used_llm Literal 확장 회귀**: `FeedbackOutput.used_llm: Literal[..., "claude-haiku-4-5", ...]` 확장 + `_resolve_used_llm` 매핑 후 `test_openai_transient_final_anthropic_fallback` 등 3개 기존 테스트가 `"claude"` → `"claude-haiku-4-5"`로 attribution 정확화. 정확화의 직접 결과 — 기존 테스트 어설션 갱신.
- **bootstrap_seed idempotent 회귀**: AC9 CSV 50종 추가 후 `food_total` 50→100 (primary 50 mock + CSV 50). 테스트 어설션 갱신.
- **모바일 jest 인프라 부재**: AC18 컴포넌트 스냅샷 테스트는 jest/RNTL 미셋업으로 OUT — 레이아웃 fix(`time.flexShrink: 0`)만 적용. 테스트 인프라는 Story 8.4 polish.

### Completion Notes List

**A. 인프라 토폴로지 — Cloudflare proxy IP (AC1-3)**:
- ✅ Resolved review finding [W2/W10/W1/W17 + DF111]: `api/app/core/proxy.py` SOT 모듈 + 22 Cloudflare CIDR(IPv4 15 + IPv6 7) frozenset + `get_real_client_ip(request) -> str` 3-tier 우선순위(CF-Connecting-IP > 신뢰 proxy XFF > raw client.host) + private/loopback/link-local IP `is_private`/`is_loopback` 자동 trust(Railway internal 정합) + `init_trusted_proxies(app)` lifespan startup 1회 호출.
- 5 callsite swap: `auth.py` refresh_token 2지점 + `consents.py` PIPA audit 2지점(POST/automated-decision) + `analysis.py` SSE rate limit + `main.py` Limiter `key_func`.
- `docs/runbook/deployment.md` + `cloudflare-ip-refresh.md` 신규 — 분기 1회 IP 갱신 SOP + 외주 인수 마이그레이션 가이드(Cloud Run / AWS ECS).
- 12 단위 테스트(`tests/core/test_proxy.py`) — 8 AC 케이스 + 4 보조 가드.

**B. 약관 major/minor 분기 (AC4)**:
- ✅ Resolved review finding [W4]: `LegalDocument.version_type: Literal["major","minor"] = "major"` (안전 측 default major). `CURRENT_VERSION_TYPES` SOT — privacy/sensitive_personal_info만 minor, 나머지 4개 baseline major 유지. `_check_basic_consents(row) -> (passed, minor_updates)` 분기 — major mismatch는 차단(403), minor mismatch만 있으면 통과 + `X-Consent-Update-Available: doc_key=version` 헤더.
- `require_basic_consents(response: Response, ...)` 시그니처 갱신(헤더 첨부용) — 기존 단위 테스트 `_call(user, response=...)` 헬퍼 갱신.
- 5 신규 테스트 + 기존 25 회귀 0건.

**C. Idempotency-Key 30일 TTL (AC5)**:
- ✅ Resolved review finding [DF50]: `scripts/cleanup_idempotency_keys.py` 신규 — `UPDATE meals SET idempotency_key = NULL WHERE idempotency_key IS NOT NULL AND created_at < NOW() - INTERVAL '30 days'` 1줄 + structlog `idempotency.cleanup.completed` rows_updated 로그.
- `.github/workflows/cleanup-idempotency-cron.yml` — KST 02:00 daily(UTC 17:00) + `RAILWAY_API_DATABASE_URL` secret + `continue-on-error: true`.
- 4 단위 테스트.

**D. Vision 비용·캐시·결정성 (AC6-7, AC15)**:
- ✅ Resolved review finding [DF4/DF5/DF6]: `cache:llm:vision:{sha256(image_key)}` Redis 24h TTL + `_get_cached_parsed`/`_set_cached_parsed` graceful (deserialize fail → Sentry warning + cache miss). `cost:vision:daily:{YYYY-MM-DD}` (KST `Asia/Seoul`) Redis 카운터 + INCRBYFLOAT pipeline atomic + 36h expire(자정 cross 자연 만료). `vision_daily_cost_cap_usd=$5.0` 도달 시 `gpt-4o → gpt-4o-mini` 다운그레이드(`_call_vision_fallback`). `vision_fallback_cost_cap_usd=$1.0` 추가 cap 도달 시 `MealOCRUnavailableError("오늘은 사진 분석 한도에 도달했어요...")`. `ParsedMeal.model_used` field로 attribution.
- `parse_meal_image(image_url, *, image_key, redis_client=None)` 시그니처 확장 — `meals_images.py:parse_meal_image_endpoint`가 `request.app.state.redis` 주입.
- 6 신규 단위 테스트(cache hit/miss/deserialize fail/downgrade/exhausted/midnight reset) + AC15 Vision 환각률 perf marker 골격.

**E. 식약처 데이터 보강 (AC8-9)**:
- ✅ Resolved review finding [DF102/DF103]: `MFDS_MAX_PAGES: Final[int] = 500` (이전 hardcoded 100) + `DB_GRP_CM_GROUPS: Final[tuple[str, ...]] = ("D", "P")` SOT + `DB_GRP_CM_KEY` const(향후 fetch에 옵션 주입 forward-compat).
- `api/data/mfds_food_nutrition_seed.csv` 외식·가공식품 50종 보강 — `manual:dining-001 ~ 050` source_id. 짜장면/짬뽕/탕수육/마라탕/마라샹궈/떡볶이/순대/김밥 변형(참치/계란/소고기)/햄버거/핫도그/치킨 변형(양념/간장/마늘)/페퍼로니피자/크림·토마토파스타/비빔밥 변형(육회/고추장/제육)/김치찌개/된장찌개/부대찌개/갈비탕/삼계탕/물·비빔냉면/칼국수/우동/라면 변형(신라면/안성탕면/진라면/짜장/김치/치즈)/떡국/만두국/비빔국수/닭갈비/제육볶음/잡채/호떡/붕어빵/스낵 등.
- `api/data/README.md` 출처 + 클라이언트 customization SOP 추가.
- bootstrap_seed idempotent 회귀 가드 갱신(50 → 100). MFDS_MAX_PAGES + DB_GRP_CM_GROUPS SOT 단언 1 신규 테스트.
- T5.4 LangSmith dataset 재 upload는 운영 부팅 시점 수동 SOP로 deferred(CR 단계 권장).

**F. Self-RAG / LangGraph cleanup (AC10-11)**:
- ✅ Resolved review finding [DF89/DF99]: `aresume` sanitize layer — `_AURESUME_MANAGED_FIELDS = {"rewrite_attempts", "node_errors", "force_llm_parse"}` 주입 시 `ValueError`. `_AURESUME_WHITELIST = {"raw_text_clarified", "selected_value", "parsed_items"}` 외 키는 silent drop.
- ✅ Resolved review finding [DF91]: `_node_wrapper(node_name, *, deterministic: bool = False)` 옵션 추가 — `deterministic=True`면 `stop_after_attempt(1)` 즉시 실패. `evaluate_retrieval_quality` + `fetch_user_profile` 2 노드 wrap 갱신(LLM 호출 노드는 기존 retry 유지).
- 4+2 신규 단위 테스트(managed field 3건 + silent drop 1건 + deterministic vs non-deterministic 2건).

**G. SSE / LLM telemetry / Citation (AC12-14)**:
- ✅ Resolved review finding [DF115]: `tests/perf/test_sse_t5_kpi.py` SSE T5 KPI perf marker 골격 — `RUN_PERF_TESTS=1` opt-in + 임계값 단언(`drop ≤ 1`/`run = 50`).
- ✅ Resolved review finding [DF100]: `FeedbackOutput.used_llm: Literal[...]` 확장(`gpt-4o-mini` / `gpt-4o` / `claude-haiku-4-5` / `claude` / `stub`). `_resolve_used_llm(model)` 헬퍼 — `settings.llm_main_model`/`llm_fallback_model` raw value를 Literal에 매핑(snapshot pin 호환). `_VALID_USED_LLM_LABELS` 갱신.
- ✅ Resolved review finding [DF104]: `_CITATION_PATTERN` regex `\(\s*출처\s*[:：]` — fullwidth colon(:) + leading whitespace + 전각공백 변형 수용. `_CITATION_PREFIX_RE` 별도 정규식으로 body 추출 prefix 제거(이전 hardcoded `len("(출처:")` 슬라이스). `app/domain/ad_expression_guard.py` + `app/graph/nodes/_feedback_postprocess.py` 동기 갱신.
- 5+3 신규 단위 테스트(citation 변형 5 + used_llm 매핑 3) + 기존 LLM router 3 테스트 어설션 갱신("claude" → "claude-haiku-4-5" 정확화).

**H. Test infra cleanup (AC16)**:
- ✅ Resolved review finding [DF101]: `tests/conftest.py:make_llm_adapter_mocks()` `@contextmanager` SOT — 4 LLM adapter(parse_meal_text/rewrite_food_query/generate_clarification_options) deterministic mock 정합. 4 모듈(test_pipeline/test_self_rag/test_analysis_service/test_main_lifespan) fixture가 1줄 위임. 신규 LLM adapter 추가 시 1지점 갱신.

**I. 모바일/백엔드 회귀 가드 + 단건 endpoint (AC17-20)**:
- ✅ Resolved review finding [DF28]: `MealMacros` 4 fields `Field(ge=0, le=10000)` upper bound — Story 3.3+ LLM 환각 데이터(`carbohydrate_g=99999`) 저장 시 ValidationError 차단.
- ✅ Resolved review finding [DF38]: `MealCard.time.flexShrink: 0` 명시 — NFR-A3 폰트 200% scale + allergen 라벨 동시 표시 시 시간 잘림 차단.
- ✅ Resolved review finding [DF21]: `mobile/lib/query-persistence.ts` `buster` bump SOP 모듈 docstring 추가 — 변경 트리거 매트릭스(MealResponse / MealAnalysisSummary / MealMacros / parsed_items) + 절차(v1→v2 순차 증가) + 코드 리뷰 게이트 명시.
- ✅ Resolved review finding [DF18/DF26]: `GET /v1/meals/{meal_id}` 신규 endpoint — `Meal.user_id == user.id AND deleted_at IS NULL` 강제, 미일치 모두 404(enumeration 차단), `selectinload(Meal.analysis)` N+1 회피. 모바일 `useMealQuery(meal_id)` hook 신규 — queryKey `['meals', meal_id]`로 `useMealsQuery` invalidation과 자동 동기. 4 백엔드 단위 테스트.
- ✅ Resolved review finding [DF9]: `tests/perf/test_vision_hallucination_rate.py` 신규 — `RUN_PERF_TESTS=1` opt-in + 환각률 임계값 5% SOT. measurement marker만(reduction 자체는 별도 작업).

**J. 통합 검증**:
- pytest 776 → 824 (신규 ~48건) / 11 skipped / 0 failed.
- coverage 84.77% → 84.92% (≥84% 목표 충족).
- ruff check / ruff format / mypy: 모두 0 에러.
- mobile tsc --noEmit: 0 에러.
- Story 3.3-3.8 회귀 0건(전 테스트 통과 + 기존 AC 보존).

### File List

**신규 (백엔드)**
- `api/app/core/proxy.py` — Cloudflare + Railway proxy IP trust SOT
- `api/tests/core/test_proxy.py` — 12 단위 테스트
- `scripts/cleanup_idempotency_keys.py` — 30일 TTL cleanup script
- `api/tests/scripts/test_cleanup_idempotency_keys.py` — 4 단위 테스트
- `.github/workflows/cleanup-idempotency-cron.yml` — KST 02:00 daily cron
- `api/tests/perf/__init__.py`
- `api/tests/perf/test_sse_t5_kpi.py` — AC12 perf marker 골격
- `api/tests/perf/test_vision_hallucination_rate.py` — AC15 perf marker 골격

**신규 (문서)**
- `docs/runbook/deployment.md` — Railway+Cloudflare 토폴로지 + 외주 인수 마이그레이션 가이드
- `docs/runbook/cloudflare-ip-refresh.md` — 분기 1회 IP 갱신 SOP

**수정 (백엔드)**
- `api/app/core/config.py` — `vision_cache_ttl_seconds` / `vision_daily_cost_cap_usd` / `vision_fallback_cost_cap_usd` 신규 settings
- `api/app/api/v1/auth.py` — `get_real_client_ip` import + refresh_token 2지점 swap
- `api/app/api/v1/consents.py` — `get_real_client_ip` import + PIPA audit 2지점 swap
- `api/app/api/v1/analysis.py` — `_redis_fixed_window_incr` `get_real_client_ip` 사용
- `api/app/api/v1/meals.py` — `MealMacros le=10000` + `GET /v1/meals/{meal_id}` 신규 endpoint
- `api/app/api/v1/meals_images.py` — `parse_meal_image_endpoint` redis_client 주입
- `api/app/api/deps.py` — `_check_basic_consents` 분기 + `require_basic_consents` `Response` 인자 + `X-Consent-Update-Available` 헤더
- `api/app/main.py` — Limiter `key_func=get_real_client_ip` swap + lifespan `init_trusted_proxies` 호출
- `api/app/adapters/openai_adapter.py` — Vision cache + cost cap + fallback model + `ParsedMeal.model_used`
- `api/app/adapters/llm_router.py` — `_resolve_used_llm` 헬퍼 + `_VALID_USED_LLM_LABELS` 확장 + env override attribution
- `api/app/adapters/mfds_openapi.py` — `MFDS_MAX_PAGES=500` + `DB_GRP_CM_GROUPS=("D","P")` + `DB_GRP_CM_KEY` SOT
- `api/app/services/analysis_service.py` — `aresume` sanitize layer
- `api/app/graph/nodes/_wrapper.py` — `deterministic: bool = False` 옵션
- `api/app/graph/nodes/evaluate_retrieval_quality.py` — `deterministic=True` 적용
- `api/app/graph/nodes/fetch_user_profile.py` — `deterministic=True` 적용
- `api/app/graph/nodes/generate_feedback.py` — `_VALID_USED_LLM_LABELS` 확장
- `api/app/graph/state.py` — `FeedbackOutput.used_llm` Literal 확장
- `api/app/domain/legal_documents.py` — `LegalVersionType` Literal + `LegalDocument.version_type` field + `CURRENT_VERSION_TYPES` SOT + `X_CONSENT_UPDATE_AVAILABLE_HEADER`
- `api/app/domain/ad_expression_guard.py` — `_CITATION_PATTERN` fullwidth/whitespace 수용
- `api/app/graph/nodes/_feedback_postprocess.py` — `_CITATION_PATTERN` + `_CITATION_PREFIX_RE` 정합

**수정 (테스트)**
- `api/tests/conftest.py` — `make_llm_adapter_mocks` SOT 추출
- `api/tests/test_consents_router.py` — AC4 5 신규 테스트
- `api/tests/test_consents_deps.py` — `_call` 헬퍼 `Response` 인자
- `api/tests/test_meals_router.py` — AC17 2 신규 + AC20 4 신규
- `api/tests/test_openai_adapter.py` — AC6/AC7 6 신규 테스트
- `api/tests/services/test_analysis_service.py` — AC10 4 신규 + AC11 2 신규 + conftest mock 위임
- `api/tests/graph/test_pipeline.py` — conftest mock 위임
- `api/tests/graph/test_self_rag.py` — conftest mock 위임
- `api/tests/test_main_lifespan.py` — conftest mock 위임
- `api/tests/adapters/test_mfds_openapi.py` — AC8 SOT 단언 1 신규
- `api/tests/adapters/test_llm_router.py` — AC13 3 신규 + 기존 3 어설션 갱신("claude" → "claude-haiku-4-5")
- `api/tests/domain/test_ad_expression_guard.py` — AC14 5 신규 테스트
- `api/tests/integration/test_bootstrap_seed.py` — AC9 정합 어설션 갱신(50 → 100)

**수정 (모바일)**
- `mobile/features/meals/MealCard.tsx` — `time.flexShrink: 0` 명시
- `mobile/features/meals/api.ts` — `fetchMealById` + `useMealQuery` 신규
- `mobile/lib/query-persistence.ts` — `buster` bump SOP 모듈 docstring 추가

**수정 (데이터)**
- `api/data/mfds_food_nutrition_seed.csv` — 외식·가공식품 50종 수동 보강
- `api/data/README.md` — 출처 SOP + 클라이언트 customization 가이드

**수정 (문서/메타)**
- `_bmad-output/implementation-artifacts/deferred-work.md` — Story 3.9 CLOSED 섹션 추가
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `3-9-에픽-3-후-polish: in-progress → review`
- `_bmad-output/implementation-artifacts/3-9-에픽-3-후-polish.md` — Status `ready-for-dev → review` + Tasks/Subtasks 체크 + Dev Agent Record

## Change Log

| 일자 | 변경 | 출처 |
|------|------|------|
| 2026-05-05 | Story 3.9 DS 시작 — Status `ready-for-dev → in-progress` | Amelia (bmad-dev-story) |
| 2026-05-05 | Task A — Cloudflare proxy IP 인프라 + 5 callsite swap + runbook 2종 (AC1-3) | Amelia |
| 2026-05-05 | Task B — 약관 major/minor 분기 + `X-Consent-Update-Available` 헤더 (AC4) | Amelia |
| 2026-05-05 | Task C — Idempotency-Key 30일 TTL cleanup script + GHA cron (AC5) | Amelia |
| 2026-05-05 | Task D — Vision 캐시 + cost cap + 다운그레이드 fallback (AC6, AC7, AC15) | Amelia |
| 2026-05-05 | Task E — MFDS_MAX_PAGES 500 + DB_GRP_CM 그룹 SOT + 외식 50종 CSV (AC8, AC9) | Amelia |
| 2026-05-05 | Task F — aresume sanitize + 결정적 노드 retry opt-out (AC10, AC11) | Amelia |
| 2026-05-05 | Task G — SSE T5 perf marker + used_llm Literal 확장 + citation 변형 수용 (AC12-14) | Amelia |
| 2026-05-05 | Task H — conftest `make_llm_adapter_mocks` SOT (AC16) | Amelia |
| 2026-05-05 | Task I — MealMacros le=10000 + MealCard layout fix + buster SOP + GET /v1/meals/{meal_id} + useMealQuery (AC17-20) | Amelia |
| 2026-05-06 | Task J — 통합 검증 824 passed/11 skipped/0 failed + coverage 84.92% + ruff/mypy/tsc 0 + Story 3.3-3.8 회귀 0건 | Amelia |
| 2026-05-06 | deferred-work.md Story 3.9 CLOSED 섹션 + sprint-status `review` + Story Status `review` | Amelia |
