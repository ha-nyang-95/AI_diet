# Story 3.4: 음식명 정규화 매칭 + 임베딩 fallback + Self-RAG 재질문

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **시스템 엔지니어**,
I want **`retrieve_nutrition` 노드가 `food_aliases` 정규화 1차 lookup → `food_nutrition` exact 매칭 → `food_nutrition.embedding` HNSW top-3 임베딩 fallback 3단 검색을 수행하고, 신뢰도 미달 시 `rewrite_query`(실 LLM)로 재검색하며, 재검색 후에도 미달이면 `needs_clarification = True` + `clarification_options`를 set해 그래프를 일시 정지(`END` 도달)하고, 사용자 응답 수신 시 `analysis_service.aresume`이 `parse_meal`을 갱신해 재개하기를**,
so that **"짜장면" / "자장면" / "포케볼" 같은 한국식 변형 + 모호 항목에 대한 환각률을 낮추고(T3 ≥ 90%) Self-RAG 재질문 카드의 백엔드 신호를 박아 책임 추적성을 높인다(FR18, FR19, FR20)**.

본 스토리는 Epic 3(AI 영양 분석 — Self-RAG + 인용 피드백)의 *retrieve 실 비즈니스 로직 + Self-RAG 재질문 흐름의 백엔드 SOT*를 박는다 — **(a) `app/adapters/openai_adapter.py` 확장 — `parse_meal_text(text)` 함수(structured output `ParsedMeal` 재사용 — Story 2.3 Vision 패턴 정합, OCR Vision 미경유 텍스트 입력 전용 LLM parse) + `rewrite_food_query(query)` 함수(structured output `RewriteVariants` 신규 — `["연어 포케", "참치 포케", "베지 포케"]` 형태 2-3건 변형 생성, T2 KPI 5건 회귀 가드 정합)**, **(b) `app/rag/food/normalize.py` 신규 — `lookup_canonical(session, alias)` async 함수 — `food_aliases.alias = :alias` exact lookup → `canonical_name` 반환 또는 None(unmatched). 1 round-trip(architecture line 977 정합 — FR19 SOT)**, **(c) `app/rag/food/search.py` 신규 — `search_by_name(session, canonical_name) -> RetrievedFood | None` exact name 매칭(`food_nutrition WHERE name = :n LIMIT 1` — score=1.0) + `search_by_embedding(session, query) -> list[RetrievedFood]` HNSW top-3(`ORDER BY embedding <=> :q LIMIT 3` + `WHERE embedding IS NOT NULL` 자동 제외) + `compute_retrieval_confidence(matches: list[RetrievedFood]) -> float` aggregator(top-1 score 또는 단일 항목 score — multi-item 시 *최소값* 채택으로 한 항목이라도 신뢰도 낮으면 Self-RAG 재검색 분기 — *보수적*)**, **(d) `app/graph/nodes/parse_meal.py` 갱신 — *실 비즈니스 로직*: 단계 (i) `meals.parsed_items` JSONB 우선 읽기(Story 2.3 OCR 결과 영속화 정합 — 이미 parse된 사진 입력은 LLM 재호출 X — cost 0), (ii) `parsed_items IS NULL` 시(텍스트-only 식단) `openai_adapter.parse_meal_text(state["raw_text"])` 호출 → `ParsedMealItem` → `FoodItem` 매핑, (iii) 빈 텍스트 시 빈 리스트 반환(downstream 노드는 빈 retrieval로 진행)**, **(e) `app/graph/nodes/retrieve_nutrition.py` 갱신 — *실 비즈니스 로직*: 단계 (i) `parsed_items` 빈 리스트 시 `RetrievalResult(retrieved_foods=[], retrieval_confidence=0.0)` 즉시 반환, (ii) 각 item에 대해 `lookup_canonical(session, item.name)` 호출 → matched 시 `search_by_name(session, canonical_name)` exact 매칭, (iii) alias 미스 또는 exact 매칭 미스 시 `search_by_embedding(session, item.name)` HNSW top-3, (iv) per-item `RetrievedFood` 수집 + `compute_retrieval_confidence(matches)`로 `retrieval_confidence` 산출, (v) `_LOW_CONFIDENCE_SENTINEL`/`"low_confidence"` keyword 분기 보존(test 환경 hook — Story 3.3 회귀 가드)**, **(f) `app/graph/nodes/rewrite_query.py` 갱신 — *실 비즈니스 로직*: 단계 (i) `parsed_items[0].name`을 `rewrite_food_query(name)` 호출 → 2-3 변형 생성(예: `"포케볼"` → `["연어 포케", "참치 포케", "베지 포케"]`), (ii) `rewritten_query`는 변형들의 `" / "` join(retrieve_nutrition가 *각 변형 임베딩*을 동시 검색하는 미래 확장은 Story 8.4 polish — 본 스토리는 *합쳐진 자유 텍스트*로 단일 임베딩 호출), (iii) `rewrite_attempts: state.get("rewrite_attempts", 0) + 1` 동시 갱신**, **(g) `app/graph/state.py` 확장 — `ClarificationOption` Pydantic BaseModel(`label: str` + `value: str`) + `MealAnalysisState`에 `clarification_options: list[ClarificationOption]` 필드 추가(디폴트 `[]` — `needs_clarification=True` 시 1+개 채워짐)**, **(h) `app/graph/edges.py` 갱신 — `route_after_evaluate(state)` 라우터에 *3-way 분기* 추가: `route="rewrite"` → `rewrite_query`, `route="clarify"` → `request_clarification`(신규 노드), `route="continue"` → `fetch_user_profile`. **`evaluate_retrieval_quality`의 결정 로직 보강**: `confidence < threshold AND attempts >= 1` 시 `route="clarify"` 반환(재검색 후에도 미달 — 재질문 분기). `attempts < 1` 시 기존 `"rewrite"` 분기 유지**, **(i) `app/graph/nodes/request_clarification.py` 신규 — `needs_clarification=True` + `clarification_options` 생성 노드. `parsed_items[0].name`을 입력으로 OpenAI structured output `ClarificationOptions(options: list[ClarificationOption])` 호출 → 2-4 옵션 생성(예: `"포케볼"` → `[{label="연어 포케", value="연어 포케"}, {label="참치 포케", value="참치 포케"}, {label="채소 포케", value="베지 포케"}]`). `request_clarification` 다음 edge는 `END`(분석 일시 정지 — graph는 checkpoint state로 idle, 라우터가 `aget_state` 조회 후 사용자 응답 대기)**, **(j) `app/services/analysis_service.py` `aresume` 강화 — *Command(update=..., goto=...) 패턴 도입*: `aresume(thread_id, user_input)` 진입 시 (i) `user_input["raw_text_clarified"]` 추출, (ii) `Command(update={"raw_text": clarified, "parsed_items": None, "retrieval": None, "rewrite_attempts": 0, "node_errors": [], "needs_clarification": False, "clarification_options": [], "evaluation_decision": None}, goto="parse_meal")` invoke → graph가 `parse_meal`부터 재개(이번엔 사용자 정제 텍스트로 LLM parse + 정규화 1차 hit 가능성 ↑)**, **(k) `app/core/config.py` 확장 — `food_retrieval_top_k: int = 3`(HNSW top-K) + `clarification_max_options: int = 4`(재질문 옵션 상한) — 두 값 모두 환경 변수 override 가능(NFR-O3 식약처 데이터 지속 갱신 정합)**, **(l) `api/tests/data/korean_foods_100.json` 신규 — *한식 100건 ground-truth 데이터셋* (T3 KPI SOT — 짜장면/자장면/김치찌개/김치 찌개/떡볶이/떡뽁이/포케볼/...). 각 행: `{"input": "자장면", "expected_canonical": "짜장면", "expected_path": "alias", "category": "면류"}` (`expected_path`는 `alias`/`exact`/`embedding`/`clarification` 4 분류 — 실 흐름 분포 가시화). 본 데이터셋은 **Story 3.8이 `scripts/upload_eval_dataset.py`로 LangSmith Dataset(`balancenote-korean-foods-v1`)으로 업로드**(epic line 705 정합 — 본 스토리에서 *데이터 SOT만 박음*, 업로드 자동화는 3.8 책임)**, **(m) 테스트 인프라 — `api/tests/rag/test_food_normalize.py`(신규 — `lookup_canonical` alias hit/miss + 빈 입력 가드) + `api/tests/rag/test_food_search.py`(신규 — `search_by_name` exact + `search_by_embedding` HNSW + `compute_retrieval_confidence` min/single 분기) + `api/tests/graph/nodes/test_parse_meal.py`(갱신 — `meals.parsed_items` 우선 + LLM fallback + 빈 텍스트 + Pydantic 검증 fail-fast) + `api/tests/graph/nodes/test_retrieve_nutrition.py`(갱신 — 3단 검색 + sentinel 분기 보존 + low-confidence 분기) + `api/tests/graph/nodes/test_rewrite_query.py`(갱신 — LLM mock + 변형 생성 + rewrite_attempts increment) + `api/tests/graph/nodes/test_request_clarification.py`(신규 — `clarification_options` 생성 + `needs_clarification=True`) + `api/tests/graph/test_self_rag.py`(갱신 — `clarify` 분기 추가 — 재검색 후에도 미달 시 `END` 도달 + `clarification_options ≥ 1`) + `api/tests/services/test_analysis_service.py`(갱신 — `aresume`이 `parse_meal`부터 재개 + state 정상 갱신) + `api/tests/test_korean_foods_eval.py`(신규 — T3 KPI ≥ 90% 회귀 가드 — `@pytest.mark.eval` skip 디폴트, `RUN_EVAL_TESTS=1` 게이트)** 의 데이터·인프라 baseline을 박는다.

부수적으로 (a) **모바일 SSE 채팅 UI에서 `clarification_options` 카드 렌더링은 OUT** — Story 3.7 책임 (`(tabs)/meals/[meal_id].tsx`의 `ChatStreaming.tsx`가 `event: clarification` SSE 이벤트로 옵션 노출 + 사용자 선택 시 `POST /v1/analysis/clarify` 호출). 본 스토리는 *백엔드 신호*(`needs_clarification` + `clarification_options`)만 박음, (b) **`POST /v1/analysis/stream` SSE 라우터 + `POST /v1/analysis/{thread_id}/clarify` 라우터는 OUT** — Story 3.7 책임. 본 스토리의 `analysis_service.aresume`은 *내부 호출 가능 인터페이스*만 — 단위 테스트가 1차 호출자, (c) **`fit_score` 알고리즘은 OUT** — `evaluate_fit`은 Story 3.3 stub(`fit_score=50`) 유지, Story 3.5 책임, (d) **인용형 피드백 + 광고 표현 가드는 OUT** — `generate_feedback`은 Story 3.3 stub(`text="(분석 준비 중)"`) 유지, Story 3.6 책임, (e) **듀얼-LLM router는 OUT** — `parse_meal_text`/`rewrite_food_query`/`request_clarification` 모두 OpenAI 단일 LLM(`gpt-4o-mini`) 호출. tenacity transient retry 1회는 본 스토리에서 박지만 *Anthropic Claude fallback*은 Story 3.6 `adapters/llm_router.py`가 통합 시점, (f) **LangSmith 외부 옵저버빌리티는 OUT** — Story 3.8 책임. 본 스토리는 `LANGCHAIN_TRACING_V2=true` env 활성화 시 native 자동 트레이스가 동작하지만(LangGraph 표준), `mask_run` hook 부착은 3.8, (g) **Redis LLM 캐시(`cache:llm:{sha256(...)}`)는 OUT** — Story 3.6 정합. 본 스토리 LLM 호출은 *miss 100%* 가정 + cost 1배 budget, (h) **PIPA 동의 게이트 dependency는 OUT** — `Depends(require_automated_decision_consent)` 적용은 *분석 라우터*(Story 3.7)에서. 본 스토리는 라우터 노출 X → 게이트 적용 X(architecture line 311 정합), (i) **Rate limit 적용은 OUT** — Story 3.7/8.4 책임, (j) **분석 결과 영속화(`meal_analyses` 테이블)는 OUT** — Story 3.6 generate_feedback 후처리 단계, (k) **외주 인수 클라이언트 alias 추가 admin UI는 OUT** — Story 7.x 책임. 본 스토리 alias 데이터는 Story 3.1 시드 50+건 그대로(추가 시드 X), (l) **LangSmith Dataset 자동 업로드(`scripts/upload_eval_dataset.py`)는 OUT** — Story 3.8 책임. 본 스토리는 *데이터 SOT 파일*(`korean_foods_100.json`)만 박고, T3 KPI는 *로컬 pytest*에서 검증.

## Acceptance Criteria

> **BDD 형식 — 각 AC는 독립적 검증 가능. 모든 AC 통과 후 `Status: review`로 전환하고 code-review 워크플로우로 진입.**

1. **AC1 — `app/graph/state.py` 확장 — `ClarificationOption` 모델 + `MealAnalysisState.clarification_options` 필드**
   **Given** Story 3.3 baseline `MealAnalysisState`(13 필드 + Pydantic IO 6세트), **When** `from app.graph.state import ClarificationOption, MealAnalysisState` import, **Then**:
   - **`ClarificationOption` (Pydantic BaseModel, `extra="forbid"`)** — `label: str = Field(min_length=1, max_length=50)`(UI 노출 라벨, 한국어 — 예: `"연어 포케"`) + `value: str = Field(min_length=1, max_length=80)`(`aresume` 시 `raw_text_clarified`에 주입될 정제 텍스트 — 라벨과 동일하거나 quantity 포함 — 예: `"연어 포케 1인분"`).
   - **`MealAnalysisState`에 `clarification_options: list[ClarificationOption]` 필드 추가** (`total=False` — 디폴트 부재로 인식). `request_clarification` 노드가 1+개 채움. `aresume` 시 빈 리스트로 reset.
   - **테스트** — `api/tests/graph/test_state.py` 갱신 — `ClarificationOption` Pydantic 검증(빈 label/value → `ValidationError`, max_length 초과 → `ValidationError`, extra field 거부) + `MealAnalysisState` partial dict에 `clarification_options=[]` 정합.

2. **AC2 — `app/adapters/openai_adapter.py` 확장 — `parse_meal_text` + `rewrite_food_query` + `generate_clarification_options`**
   **Given** Story 2.3 baseline `_call_vision`/`_call_embedding` 패턴(structured output + tenacity 1회 retry + lazy singleton), **When** `from app.adapters.openai_adapter import parse_meal_text, rewrite_food_query, generate_clarification_options` import, **Then**:
   - **`parse_meal_text(text: str) -> ParsedMeal`** — async — `client.beta.chat.completions.parse(model=PARSE_MODEL, messages=[system_prompt, user_text], response_format=ParsedMeal, temperature=0.0)` 호출. `PARSE_MODEL = "gpt-4o-mini"`(architecture line 509 정합 — 메인 LLM). system 프롬프트: *"한국어 식단 텍스트에서 음식 항목을 추출. 각 항목 name(한국어 표준)/quantity(자유 텍스트, "1인분"/"200g"/None)/confidence(0~1) 반환. 음식 아닌 텍스트는 빈 items 배열 반환."* tenacity 1회 retry(transient만 — `_TRANSIENT_RETRY_TYPES` 재사용). 빈 입력(`text.strip() == ""`) 즉시 `ParsedMeal(items=[])` 반환(API 호출 X / cost 0). 오류 매핑: transient 후 `MealOCRUnavailableError(503)`, schema 위반 `MealOCRPayloadInvalidError(502)` (Vision 패턴 정합 — 신규 예외 클래스 추가 X).
   - **`rewrite_food_query(query: str) -> RewriteVariants`** — async — structured output `RewriteVariants(variants: list[str] = Field(min_length=1, max_length=4))` 신규 정의(파일 상단). system 프롬프트: *"한국어 음식명 모호 시 가능한 변형 2-4건 생성. 예: 포케볼 → [연어 포케, 참치 포케, 베지 포케]. 단순 동의어가 아닌 *세부 항목 분기*."* tenacity 1회 retry. 빈 입력 즉시 `RewriteVariants(variants=[query or "unknown"])` 반환(graceful — 호출자가 fallback 처리).
   - **`generate_clarification_options(query: str) -> ClarificationVariants`** — async — structured output `ClarificationVariants(options: list[ClarificationOption])` (state.py의 `ClarificationOption` 재사용 — `from app.graph.state import ClarificationOption` import). system 프롬프트: *"사용자에게 *어떤 ◯◯인가요?* 형태로 물을 옵션 2-4건 생성. label은 짧은 한국어(≤50자), value는 라벨 + 양 추정(예: '연어 포케 1인분'). max 4."* `settings.clarification_max_options` 상한(디폴트 4) — Pydantic `max_length` 동적 적용 X(상수 4)이지만 호출자가 truncate. 빈 입력 시 `ClarificationVariants(options=[ClarificationOption(label="알 수 없음", value=query or "")])` graceful.
   - **NFR-S5 마스킹** — `text`/`query` raw 값 로그 X (잠재 raw_text 포함 — Story 3.1 `food_seed.no_data_graceful` 패턴 정합). items_count + latency_ms + model만.
   - **테스트** — `api/tests/test_openai_adapter.py` 갱신 또는 신규 모듈 — (i) `parse_meal_text("짜장면 1인분, 군만두 4개")` mock으로 `ParsedMeal(items=[{name:"짜장면", quantity:"1인분"}, ...])` 반환 + 빈 입력 → API 호출 X, (ii) `rewrite_food_query("포케볼")` mock → 2-4 변형 + 빈 입력 graceful, (iii) `generate_clarification_options("포케볼")` mock → 2-4 옵션 + max_options 상한, (iv) transient `httpx.TimeoutException` 첫 호출 + 두 번째 정상 → tenacity retry 발동 + 정상 종료, (v) 영구 오류(`AuthenticationError`) → 즉시 `MealOCRUnavailableError`(retry X — cost 낭비 차단).

3. **AC3 — `app/rag/food/normalize.py` 신규 — `lookup_canonical(session, alias)` async**
   **Given** Story 3.1 baseline `food_aliases` 50+건 시드 + `UNIQUE(alias)` 제약, **When** `from app.rag.food.normalize import lookup_canonical` import, **Then**:
   - **`lookup_canonical(session: AsyncSession, alias: str) -> str | None`** — async — `SELECT canonical_name FROM food_aliases WHERE alias = :alias LIMIT 1` 1 round-trip(text() 또는 ORM `select(FoodAlias.canonical_name).where(FoodAlias.alias == alias)`). 매치 시 `canonical_name` 반환, 미스 시 `None`. 빈 입력(`alias.strip() == ""`) 즉시 `None`(DB 호출 X).
   - **소문자 정규화 X** — `food_aliases.alias`는 *exact 한국어 매칭*(영문 case insensitive 회피 — "BBQ"/"bbq" 동치는 별 고려 — 본 스토리 baseline은 한국어만). 외주 인수 시 영문 alias 추가 가능 SOP는 `data/README.md`(Story 3.1).
   - **NFR-S5 마스킹** — `alias` raw 값 로그 X(잠재 음식명 — 식습관 추론 — Story 3.1 `food_seed` 패턴 정합). hit/miss 통계만.
   - **테스트** — `api/tests/rag/test_food_normalize.py` 신규 — (i) seeded `"자장면"` → `"짜장면"`, (ii) 미스 `"임의의_음식_xyz"` → `None`, (iii) 빈 입력 `""` → `None` (DB 호출 X — mock으로 `session.execute` 호출 횟수 검증), (iv) 공백 trim 검증(`"  자장면  "` → `None` *not* `"짜장면"` — 사전적 정확 매칭 강제 — 사용자 입력 trim은 호출자 책임).

4. **AC4 — `app/rag/food/search.py` 신규 — exact + HNSW top-3 + confidence aggregator**
   **Given** Story 3.1 baseline `food_nutrition`(1500+건 시드 + HNSW `vector_cosine_ops` 인덱스 + `embedding NULL` 허용), **When** `from app.rag.food.search import search_by_name, search_by_embedding, compute_retrieval_confidence` import, **Then**:
   - **`search_by_name(session: AsyncSession, name: str) -> RetrievedFood | None`** — async — `SELECT id, name, nutrition FROM food_nutrition WHERE name = :n LIMIT 1`. 매치 시 `RetrievedFood(name=name, food_id=id, score=1.0, nutrition=nutrition)` 반환(score 고정 1.0 — exact 매칭 신뢰도 최고). 미스 시 `None`. 빈 입력 즉시 `None`.
   - **`search_by_embedding(session: AsyncSession, query: str, *, top_k: int | None = None) -> list[RetrievedFood]`** — async — 단계 (i) `embeddings = await openai_adapter.embed_texts([query])` → 1536-dim 벡터 1건, (ii) `SELECT id, name, nutrition, embedding <=> :q AS distance FROM food_nutrition WHERE embedding IS NOT NULL ORDER BY embedding <=> :q LIMIT :k` (`top_k or settings.food_retrieval_top_k`, 디폴트 3). pgvector cosine 거리 `<=>` 0~2 범위 — `score = 1 - (distance / 2)` 0~1 정규화(상한 1.0, 하한 0.0 clip). `nutrition`은 jsonb dict. 빈 결과(인덱스 비어있음 — dev/test graceful) 시 빈 리스트.
   - **`compute_retrieval_confidence(matches: list[RetrievedFood], *, single_item: bool = True) -> float`** — pure function. `matches`가 빈 리스트 시 0.0. `single_item=True`(단일 음식 케이스) → top-1 score 그대로. `single_item=False`(multi-food meal — 2+ items) → *최소값* 채택(보수적 — 한 항목이라도 신뢰도 낮으면 Self-RAG 재검색 분기). 호출자(`retrieve_nutrition` 노드)가 `len(parsed_items) == 1` 분기.
   - **HNSW perf** — Story 3.1 NFR-P6 baseline ≤ 200ms 정합. 본 스토리는 *임베딩 호출(OpenAI)* 추가로 p95 ≤ 800ms 목표(임베딩 round-trip 500ms + DB 200ms 마진). NFR-P4 ≤ 3s 분석 budget 안에서 안전.
   - **NFR-S5 마스킹** — `query` raw 노출 X. items_count/source/latency_ms만.
   - **테스트** — `api/tests/rag/test_food_search.py` 신규 — (i) `search_by_name` exact hit + 미스 + 빈 입력, (ii) `search_by_embedding` HNSW top-3 ordering(`distance ASC` 정합) + score 정규화 0~1 범위 + 빈 인덱스 graceful, (iii) `compute_retrieval_confidence` single-item top-1 / multi-item min / 빈 리스트 → 0.0, (iv) `OPENAI_API_KEY` 미설정 시 `embed_texts`가 `MealOCRUnavailableError` raise → 호출자 노드 wrapper가 NodeError로 변환(상위 레이어 책임 — search 자체는 propagate).

5. **AC5 — `app/graph/nodes/parse_meal.py` 갱신 — `meals.parsed_items` 우선 + LLM fallback**
   **Given** Story 3.3 결정성 stub(`raw_text[:50]` placeholder) → 본 스토리 *실 비즈니스 로직*, **When** `parse_meal(state, deps)` 노드 호출, **Then** 단계:
   - **(i) `meals.parsed_items` 우선 읽기** — `state["meal_id"]`로 `SELECT parsed_items FROM meals WHERE id = :meal_id` 1 round-trip. `parsed_items IS NOT NULL` 시 jsonb를 `[FoodItem(name=..., quantity=..., confidence=...)]` 매핑 후 dict 반환(LLM 호출 X — Story 2.3 OCR 결과 재사용 — cost 0). `meal_id` 부재 또는 row 부재 시 (ii) 진행.
   - **(ii) LLM fallback** — `state["raw_text"]`이 비어있지 않으면 `await openai_adapter.parse_meal_text(raw_text)` 호출 → `ParsedMeal.items` → `FoodItem` 매핑 후 dict 반환. `parse_meal_text`가 transient 후 raise하면 `_node_wrapper`가 1회 retry → 2회 실패 시 NodeError append + 빈 `parsed_items` 반환(downstream graceful).
   - **(iii) 빈 텍스트** — `raw_text.strip() == ""` 시 `ParseMealOutput(parsed_items=[])` 반환(downstream 빈 retrieval로 진행 → fit_score=0 stub).
   - **결정성 stub 호환** — 본 스토리는 *실 로직*이지만, 테스트에서 `parse_meal_text`/DB는 mock으로 격리. Story 3.3 stub `raw_text[:50]` 방식은 폐지.
   - **NFR-S5 마스킹** — `raw_text` 로그 X. items_count + source(`"db"`/`"llm"`/`"empty"`)만 1줄.
   - **테스트** — `api/tests/graph/nodes/test_parse_meal.py` 갱신 — (i) `meals.parsed_items` 시드된 케이스 → DB 우선 + `parse_meal_text` 호출 X(mock으로 호출 횟수 0 검증), (ii) `parsed_items IS NULL` + `raw_text="짜장면 1인분"` → `parse_meal_text` 호출 + items 매핑, (iii) 빈 `raw_text` → 빈 리스트 + LLM 호출 X, (iv) `parse_meal_text`가 `MealOCRUnavailableError` raise → wrapper retry 1회 → fallback NodeError + 빈 `parsed_items`(downstream graceful), (v) 잘못된 jsonb 형태(`parsed_items`가 list 아닌 string) → ValidationError → wrapper retry → fallback.

6. **AC6 — `app/graph/nodes/retrieve_nutrition.py` 갱신 — alias → exact → HNSW 3단**
   **Given** AC3 `lookup_canonical` + AC4 `search_by_name`/`search_by_embedding`/`compute_retrieval_confidence`, **When** `retrieve_nutrition(state, deps)` 호출, **Then** 단계:
   - **(i) 빈 `parsed_items`** — 즉시 `RetrievalResult(retrieved_foods=[], retrieval_confidence=0.0)` 반환.
   - **(ii) 각 item에 대해 (단일 item 가정 — multi-item은 단계 (vi))**:
     - **(a) alias lookup** — `canonical = await lookup_canonical(session, item.name)`. matched 시 `name = canonical`, 아니면 `name = item.name`(원문 그대로 다음 단계).
     - **(b) exact name 매칭** — `match = await search_by_name(session, name)`. matched 시 `[match]` + score=1.0 → confidence 1.0 → 다음 단계 skip.
     - **(c) HNSW 임베딩 fallback** — exact 미스 시 `matches = await search_by_embedding(session, item.name)` top-3. confidence는 top-1 score(`compute_retrieval_confidence(matches, single_item=True)`).
   - **(iii) `rewrite_attempts > 0` 분기** — Self-RAG 1회 재검색 후라면 `state["rewritten_query"]`(존재 시)을 `search_by_embedding` 입력으로 사용(원본 `item.name` 대신 변형 쿼리로 재검색). alias/exact 단계 skip(이미 재작성된 쿼리는 alias 사전 미포함 — 임베딩 fallback 직진).
   - **(iv) sentinel 분기 보존(test 환경)** — `_LOW_CONFIDENCE_SENTINEL = "__test_low_confidence__"` 또는 `deps.settings.environment in {dev,test,ci}` AND `name` 포함 `"low_confidence"` AND `rewrite_attempts == 0` 시 `RetrievalResult(retrieved_foods=[], retrieval_confidence=0.3)` 즉시 반환(Story 3.3 회귀 가드 — Self-RAG 분기 트리거 결정성 fixture 보존). prod에서는 sentinel만 매칭(NFR-S5 정합).
   - **(v) `rewrite_attempts > 0` 신뢰도 boost** — 결정성 sentinel 입력 시 `retrieval_confidence=0.85` (Story 3.3 회귀 가드 — 1회 재검색 후 신뢰도 회복 시뮬레이션). 실 alias/exact/HNSW 흐름은 actual score 사용.
   - **(vi) multi-item 케이스** — 2+ items 시 각 item을 (a)(b)(c) 순차 처리(병렬 X — DB connection pool 보호) + 모든 `RetrievedFood`를 `retrieved_foods` 리스트에 append + `compute_retrieval_confidence(retrieved_foods, single_item=False)`로 *최소값* 채택. 한 item이라도 신뢰도 낮으면 Self-RAG 재검색 분기 — 보수적.
   - **DB 자원** — `async with deps.session_maker() as session:` 1 컨텍스트 내부에서 모든 alias/exact/HNSW 호출(connection 1개 점유). HNSW 호출은 `session.execute(text(...))` raw SQL — pgvector `<=>` 연산자 ORM 미지원 회피.
   - **NFR-P6 + perf** — 단일 item p95 ≤ 800ms (alias 1ms + exact 5ms + 임베딩 500ms + HNSW 200ms 마진). NFR-P4 ≤ 3s 분석 budget 안전.
   - **NFR-S5 마스킹** — `item.name`/`canonical_name` 로그 X. items_count/path 분류(`"alias"`/`"exact"`/`"embedding"`/`"sentinel"`)/confidence/latency_ms만.
   - **테스트** — `api/tests/graph/nodes/test_retrieve_nutrition.py` 갱신 — (i) seeded `"자장면"` → alias hit → exact hit `"짜장면"` → confidence 1.0, (ii) seeded `"짜장면"`(alias 미스 + exact hit) → exact 1.0, (iii) `"임의의_음식_xyz"`(alias 미스 + exact 미스) → HNSW top-3 + 정규화 score, (iv) 빈 `parsed_items` → 빈 리스트 + 0.0, (v) sentinel `"__test_low_confidence__"` + `rewrite_attempts=0` → confidence 0.3(Story 3.3 회귀), (vi) `rewrite_attempts > 0` + 동일 sentinel → 0.85 boost(Story 3.3 회귀), (vii) multi-item(`["짜장면", "임의의_음식"]`) → 각각 처리 + `compute_retrieval_confidence(min)` 검증, (viii) `rewrite_attempts > 0` + `rewritten_query` 존재 시 임베딩 fallback 직진(alias/exact skip — mock으로 호출 횟수 0 검증).

7. **AC7 — `app/graph/nodes/rewrite_query.py` 갱신 — 실 LLM rewrite + rewrite_attempts increment**
   **Given** AC2 `rewrite_food_query` 어댑터, **When** `rewrite_query(state, deps)` 호출, **Then** 단계:
   - **(i) 빈 `parsed_items`** — `rewritten_query="unknown_food"` + `rewrite_attempts: state.get("rewrite_attempts", 0) + 1` 반환(LLM 호출 X — graceful).
   - **(ii) 정상 케이스** — `name = parsed_items[0].name`. `variants = await openai_adapter.rewrite_food_query(name)`. `rewritten_query = " / ".join(variants.variants)` (예: `"연어 포케 / 참치 포케 / 베지 포케"`). `rewrite_attempts` increment.
   - **(iii) Self-RAG 1회 한도** — `evaluate_retrieval_quality`가 `rewrite_attempts < 1` 가드로 강제(Story 3.3 SOT — 본 노드는 *카운터 increment*만 — 한도 결정은 wrapper 외부).
   - **(iv) 무한 루프 가드 회귀** — `rewrite_food_query`가 transient로 매번 실패해 wrapper fallback 진입 시 `rewrite_attempts` increment 누락 가능 — `evaluate_retrieval_quality`가 `node_errors` 내 `rewrite_query` 실패 카운트 합산(Story 3.3 보강 정합 — 본 스토리는 변경 X — 회귀 가드 존속).
   - **NFR-S5 마스킹** — `name`/`variants` 로그 X. variants_count + latency_ms만.
   - **테스트** — `api/tests/graph/nodes/test_rewrite_query.py` 갱신 — (i) `["짜장면"]` → mock `["짜장면 곱빼기", "짜파게티"]` → `rewritten_query="짜장면 곱빼기 / 짜파게티"` + `rewrite_attempts` increment, (ii) 빈 `parsed_items` → `"unknown_food"` + LLM 호출 X(mock 호출 횟수 0), (iii) `rewrite_food_query` transient 실패 → wrapper retry 1회 → fallback NodeError + `rewrite_attempts` 누락 + 무한 루프 가드 별 검증(test_self_rag.py).

8. **AC8 — `app/graph/edges.py` + `evaluate_retrieval_quality` 갱신 — `clarify` 분기 추가 (3-way)**
   **Given** Story 3.3 `route_after_evaluate` 2-way(rewrite/continue), **When** Self-RAG 재검색 후에도 confidence 미달 시 *재질문 분기* 진입, **Then**:
   - **`evaluate_retrieval_quality(state, deps)` 결정 로직 보강** — 단계:
     - `confidence = state["retrieval"].retrieval_confidence` (Story 3.3 정합),
     - `attempts = rewrite_attempts + node_errors[rewrite_query failure 수]` (Story 3.3 무한 루프 가드 정합),
     - **신규 분기**: `confidence < threshold` 시:
       - `attempts < 1` → `route="rewrite"` (Story 3.3 정합 — 1회 재검색 시도),
       - `attempts >= 1` → `route="clarify"` (**신규** — 재검색 후에도 미달 → 재질문),
     - `confidence >= threshold` → `route="continue"` (Story 3.3 정합).
     - `EvaluationDecision`의 `route: Literal["rewrite", "continue", "clarify"]`로 *3-way Literal* 확장.
   - **`route_after_evaluate(state) -> Literal["rewrite_query", "fetch_user_profile", "request_clarification"]`** — 라우터 분기 확장. `route="rewrite"` → `"rewrite_query"`, `route="clarify"` → `"request_clarification"`(신규 노드 — AC9), `route="continue"` → `"fetch_user_profile"`. 알 수 없는 값은 `"continue"` fail-soft + warn 로그(Story 3.3 정합).
   - **테스트** — `api/tests/graph/test_edges.py` 갱신 — (i) `EvaluationDecision(route="clarify")` → `"request_clarification"` 라우팅, (ii) `route="rewrite"`/`"continue"` 기존 분기 회귀 0건, (iii) 알 수 없는 route → `"fetch_user_profile"` fail-soft. `api/tests/graph/nodes/test_evaluate_retrieval_quality.py` 갱신 — (i) `confidence=0.3 + attempts=0` → `"rewrite"`, (ii) `confidence=0.3 + attempts=1` → `"clarify"`(신규), (iii) `confidence=0.7 + attempts=0` → `"continue"` (Story 3.3 회귀 가드).

9. **AC9 — `app/graph/nodes/request_clarification.py` 신규 + `pipeline.py` 등록**
   **Given** AC2 `generate_clarification_options` + AC8 라우터 `clarify` 분기, **When** `request_clarification(state, deps)` 노드 호출, **Then** 단계:
   - **(i) 입력** — `parsed_items[0].name` 또는 `state["raw_text"]`(parsed 빈 리스트 fallback).
   - **(ii) `await openai_adapter.generate_clarification_options(name)`** — `ClarificationVariants(options=[...])` 반환.
   - **(iii) `settings.clarification_max_options` 상한 truncate** — 디폴트 4. (1+ option 최소).
   - **(iv) 반환** — `{"needs_clarification": True, "clarification_options": [opt.model_dump() for opt in options]}` (LangGraph dict-merge 정합 — `model_dump()`로 dict 직렬화 — Story 3.3 `evaluation_decision` 패턴 정합).
   - **(v) graceful 빈 옵션** — `generate_clarification_options`가 빈 리스트 반환 시 fallback `[ClarificationOption(label="알 수 없음", value=name)]` 1건 강제(UI 깨짐 방지).
   - **`pipeline.py` 갱신** — `builder.add_node("request_clarification", partial(request_clarification, deps=deps))` + `builder.add_edge("request_clarification", END)` (분석 일시 정지 — `fit_score`/`feedback` 미진행). graph는 checkpoint state로 idle, `analysis_service.aget_state(thread_id)` 호출 시 `needs_clarification=True` + `clarification_options` 노출.
   - **`pipeline.py` Self-RAG 분기 갱신** — `add_conditional_edges("evaluate_retrieval_quality", route_after_evaluate, {"rewrite_query": "rewrite_query", "fetch_user_profile": "fetch_user_profile", "request_clarification": "request_clarification"})` 3-way 매핑.
   - **테스트** — `api/tests/graph/nodes/test_request_clarification.py` 신규 — (i) `parsed_items[0].name="포케볼"` mock → 3 옵션 생성 + `needs_clarification=True`, (ii) 빈 `parsed_items` + `raw_text="포케볼"` → `raw_text` fallback, (iii) `generate_clarification_options` 빈 리스트 → fallback 1건 강제, (iv) `clarification_max_options=2` 설정 → 4개 응답이라도 2개 truncate.

10. **AC10 — `app/services/analysis_service.py` `aresume` 강화 — Command(update=..., goto="parse_meal")**
    **Given** Story 3.3 `aresume` thin pass-through(`graph.ainvoke(user_input, config=...)`), **When** Story 3.7 라우터(`POST /v1/analysis/{thread_id}/clarify`)가 사용자 응답을 받아 호출(라우터 자체는 Story 3.7 OUT — *인터페이스 검증*만 본 스토리), **Then**:
    - **`aresume(self, *, thread_id: str, user_input: dict[str, Any]) -> MealAnalysisState`** — 단계:
      - (i) `clarified = user_input.get("raw_text_clarified")` 또는 `user_input.get("selected_value")` 추출(라우터가 전달 — `ClarificationOption.value`),
      - (ii) `clarified is None` 또는 빈 문자열 → `ValueError("aresume requires raw_text_clarified or selected_value")` raise(라우터가 422로 변환 — Story 3.7 책임),
      - (iii) `from langgraph.types import Command` import + `cmd = Command(update={"raw_text": clarified, "parsed_items": None, "retrieval": None, "rewrite_attempts": 0, "node_errors": [], "needs_clarification": False, "clarification_options": [], "evaluation_decision": None}, goto="parse_meal")`,
      - (iv) `final_state = await self.graph.ainvoke(cmd, config={"configurable": {"thread_id": thread_id}})` — graph가 `parse_meal`부터 재개. checkpointer는 thread_id별 격리이므로 상태 누적 정합(Story 3.3 정합),
      - (v) Sentry transaction(`op="analysis.pipeline"`, `name="meal_analysis_resume"`) — 재개도 1 transaction.
    - **테스트** — `api/tests/services/test_analysis_service.py` 갱신 — (i) clarification 발동 → `aget_state(thread_id)`에 `needs_clarification=True` 검증, (ii) `aresume(thread_id, {"selected_value": "참치 포케 1인분"})` → graph 재개 + 종단 state에 `feedback`(stub) 도달 + `needs_clarification=False` 리셋, (iii) `user_input` 빈 dict → `ValueError` raise, (iv) thread_id 미존재 → graph가 idle state 인식 + graceful(파이프라인 처음부터 재시작 — Story 3.3 `aget_state` snapshot None 정합).

11. **AC11 — `app/core/config.py` 확장 + `api/tests/data/korean_foods_100.json` 신규**
    **Given** Story 3.3 baseline `self_rag_confidence_threshold=0.6`, **When** `from app.core.config import settings` import, **Then**:
    - **`food_retrieval_top_k: int = 3`** — HNSW top-K 상한(NFR-P6 정합 + cost 보호). 환경 변수 `FOOD_RETRIEVAL_TOP_K` override 가능.
    - **`clarification_max_options: int = 4`** — 재질문 옵션 상한(UI 카드 4건 안 — NFR-A1 정합). 환경 변수 `CLARIFICATION_MAX_OPTIONS` override 가능.
    - **`korean_foods_100.json` 데이터셋** — `api/tests/data/korean_foods_100.json` 신규 — `[{"input": "자장면", "expected_canonical": "짜장면", "expected_path": "alias", "category": "면류"}, ...]` 100건. 분포: alias 30+ / exact 30+ / embedding 25+ / clarification 10+ (다양성 — T3 KPI 회귀 데이터셋). epic line 705 정합 — Story 3.8이 LangSmith Dataset(`balancenote-korean-foods-v1`)로 업로드.
    - **데이터 시드 베이스라인 조건** — 본 데이터셋의 `expected_canonical` 값들은 `food_nutrition` 시드(Story 3.1 1500-3000건)에 *반드시 존재*하는 한식만 선정 — orphan 회귀 차단. CI에서 dev/test 환경 시드 후 데이터셋의 `expected_canonical` 모두 `food_nutrition.name`에 존재 검증.
    - **테스트** — `api/tests/test_config.py` 갱신 또는 신규 — `food_retrieval_top_k` env override 검증 + `clarification_max_options` 검증. `api/tests/test_korean_foods_dataset.py` 신규 — (i) JSON schema 검증(100 행, 각 행 4 필드), (ii) `expected_path` 분류 분포 검증(alias ≥ 25, exact ≥ 25, embedding ≥ 20, clarification ≥ 5).

12. **AC12 — T3 KPI eval 테스트 — 한식 100건 정확도 ≥ 90% (`@pytest.mark.eval` skip 디폴트)**
    **Given** AC11 데이터셋 + AC3-AC9 통합 흐름, **When** `RUN_EVAL_TESTS=1 uv run pytest -m eval`, **Then**:
    - **`api/tests/test_korean_foods_eval.py`** 신규 — `@pytest.mark.eval` 디폴트 skip(`api/pyproject.toml [tool.pytest.ini_options].markers` 등재 — Story 3.3 `perf` 패턴 정합 — line 95-97). DB seed 후 100건을 `analysis_service.run` 또는 `retrieve_nutrition` 직접 호출(LLM은 mock 또는 실 호출 — env 분기) — *prediction* `path`(`alias`/`exact`/`embedding`/`clarification`) 산출.
    - **정확도 계산** — `correct = sum(1 for row in dataset if predicted_canonical == row["expected_canonical"])`. `accuracy = correct / 100 * 100`. **`accuracy ≥ 90%`** assert(T3 KPI 정합).
    - **expected_path 분류 정합** — `predicted_path` 정확도 별도 측정(분포 일치 검증) — 90% 미달 시 fail이 아닌 warn(분포 정확도는 KPI 외 — 시드 변화에 민감).
    - **dev/staging 분기** — dev에서는 mock LLM(결정성 응답) — accuracy 측정은 불완전(LLM 변형 ≠ 실 응답). staging/prod CI에서 *실 LLM* + 실 `food_nutrition` 시드로 1회 측정 — 결과는 LangSmith Dataset(Story 3.8) 업로드 시 baseline.
    - **본 스토리 통과 기준** — *eval skip default* + dataset 파일 검증(AC11) + 인프라 박힘. *실 90% 측정 통과*는 Story 3.8 W3 슬롯에서 LangSmith eval로 검증 — *본 스토리는 데이터 SOT + 측정 인프라*가 통과 기준.

13. **AC13 — perf budget 갱신 + 게이트 통과 + sprint-status + commit/push**
    **Given** AC1-AC12 통합 + Story 3.3 CR 패턴(86% coverage / 404 tests), **When** DS 완료 시점, **Then**:
    - **NFR-P6 perf 테스트 갱신** — `api/tests/rag/test_food_search_perf.py` 신규 (`@pytest.mark.perf`) — `search_by_embedding` 30회 측정 + p95 ≤ 800ms(임베딩 + HNSW). DB 빈 인덱스에서는 N/A skip.
    - **NFR-P4 perf 회귀** — `test_pipeline_perf.py`(Story 3.3) 갱신 — stub 기반 budget(≤100ms)에서 *실 LLM/DB 기반 budget* (≤3s) 갱신. `RUN_PERF_TESTS=1` 게이트 활성화 시 NFR-P4 ≤ 3s 평균 + NFR-P5 + 2초(Self-RAG 1회 재검색) 검증.
    - **ruff check + format** — `cd api && uv run ruff check . && uv run ruff format --check .` 0 에러.
    - **mypy strict** — `cd api && uv run mypy app` 신규 모듈(`rag/food/normalize.py` + `search.py` + `nodes/request_clarification.py`) 0 에러. Story 3.3 baseline 0 에러 회귀 가드.
    - **pytest + coverage** — `cd api && uv run pytest`(eval/perf skip) 모든 테스트 통과 + coverage `--cov-fail-under=70` 충족. 신규 모듈 coverage ≥ 80%(rag/food + 노드 갱신 — 분기 가드 명시).
    - **sprint-status 갱신** — `_bmad-output/implementation-artifacts/sprint-status.yaml`의 `3-4-음식명-정규화-매칭-fallback: ready-for-dev` → `in-progress` (DS 시작 시) → `review` (DS 완료 시 — CR 진입 직전). `last_updated` 갱신.
    - **branch + commit** — 이미 분기된 `feat/story-3.4`(CS 시작 전 master 분기 정합 — memory `feedback_branch_from_master_only.md` + `feedback_ds_complete_to_commit_push.md` 정합)에서 DS 종료 시점 단일 커밋 + push. 메시지 패턴 `feat(story-3.4): 음식명 정규화 + HNSW fallback + Self-RAG 재질문 + analysis_service.aresume 강화`.
    - **PR 생성 X (DS 시점)** — PR(draft 포함)은 CR 완료 후 한 번에 생성(memory `feedback_ds_complete_to_commit_push.md` 정합).

## Tasks / Subtasks

- [ ] **Task 1 — `app/graph/state.py` 확장 (AC: #1)**
  - [ ] 1.1 `ClarificationOption` Pydantic BaseModel 정의 (`label`/`value`).
  - [ ] 1.2 `MealAnalysisState`에 `clarification_options: list[ClarificationOption]` 필드 추가.
  - [ ] 1.3 `tests/graph/test_state.py` 갱신(label/value 검증 + extra forbid + max_length).

- [ ] **Task 2 — `app/adapters/openai_adapter.py` 확장 (AC: #2)**
  - [ ] 2.1 `RewriteVariants` + `ClarificationVariants` Pydantic 모델 정의.
  - [ ] 2.2 `parse_meal_text(text)` 함수 + system 프롬프트 + structured output.
  - [ ] 2.3 `rewrite_food_query(query)` 함수.
  - [ ] 2.4 `generate_clarification_options(query)` 함수.
  - [ ] 2.5 `tests/test_openai_adapter.py` 갱신/신규(mock 5 케이스 — happy/transient/permanent/empty/max_options).

- [ ] **Task 3 — `app/rag/food/normalize.py` 신규 (AC: #3)**
  - [ ] 3.1 `lookup_canonical(session, alias)` async 함수 + 빈 입력 가드.
  - [ ] 3.2 `tests/rag/test_food_normalize.py` 신규(hit/miss/empty/exact-match-only).

- [ ] **Task 4 — `app/rag/food/search.py` 신규 (AC: #4)**
  - [ ] 4.1 `search_by_name(session, name)` exact + score 1.0.
  - [ ] 4.2 `search_by_embedding(session, query, top_k)` HNSW + score 정규화.
  - [ ] 4.3 `compute_retrieval_confidence(matches, single_item)` aggregator.
  - [ ] 4.4 `tests/rag/test_food_search.py` 신규(exact + HNSW + min/single 분기 + empty index graceful).

- [ ] **Task 5 — `app/graph/nodes/parse_meal.py` 갱신 (AC: #5)**
  - [ ] 5.1 `meals.parsed_items` 우선 읽기 분기.
  - [ ] 5.2 `parse_meal_text` LLM fallback.
  - [ ] 5.3 빈 입력 graceful.
  - [ ] 5.4 `tests/graph/nodes/test_parse_meal.py` 갱신(DB 우선 + LLM fallback + 빈 입력 + transient retry + ValidationError).

- [ ] **Task 6 — `app/graph/nodes/retrieve_nutrition.py` 갱신 (AC: #6)**
  - [ ] 6.1 빈 `parsed_items` 분기.
  - [ ] 6.2 alias → exact → HNSW 3단 검색.
  - [ ] 6.3 `rewrite_attempts > 0` 분기(rewritten_query 사용).
  - [ ] 6.4 sentinel 분기 + boost(Story 3.3 회귀).
  - [ ] 6.5 multi-item compute_retrieval_confidence(min).
  - [ ] 6.6 `tests/graph/nodes/test_retrieve_nutrition.py` 갱신(8 케이스).

- [ ] **Task 7 — `app/graph/nodes/rewrite_query.py` 갱신 (AC: #7)**
  - [ ] 7.1 `rewrite_food_query` 호출 + 변형 join.
  - [ ] 7.2 빈 입력 graceful.
  - [ ] 7.3 `rewrite_attempts` increment.
  - [ ] 7.4 `tests/graph/nodes/test_rewrite_query.py` 갱신(LLM mock + transient + 무한 루프 회귀).

- [ ] **Task 8 — `app/graph/nodes/evaluate_retrieval_quality.py` + `edges.py` 갱신 (AC: #8)**
  - [ ] 8.1 `EvaluationDecision.route` Literal 3-way 확장 (`"rewrite"`/`"continue"`/`"clarify"`).
  - [ ] 8.2 `evaluate_retrieval_quality`에 `attempts >= 1 + low_confidence` → `"clarify"` 분기.
  - [ ] 8.3 `route_after_evaluate` 라우터 3-way 분기 + `"request_clarification"` 매핑.
  - [ ] 8.4 `tests/graph/nodes/test_evaluate_retrieval_quality.py` 갱신(3-way 분기 + Story 3.3 회귀).
  - [ ] 8.5 `tests/graph/test_edges.py` 갱신(clarify 분기 + fail-soft).

- [ ] **Task 9 — `app/graph/nodes/request_clarification.py` 신규 + `pipeline.py` 갱신 (AC: #9)**
  - [ ] 9.1 `request_clarification` 노드 함수 + graceful 빈 옵션.
  - [ ] 9.2 `nodes/__init__.py` export 갱신.
  - [ ] 9.3 `pipeline.py`에 `request_clarification` 노드 등록 + END edge.
  - [ ] 9.4 `add_conditional_edges` 매핑 3-way 갱신.
  - [ ] 9.5 `tests/graph/nodes/test_request_clarification.py` 신규(4 케이스).

- [ ] **Task 10 — `app/services/analysis_service.py` `aresume` 강화 (AC: #10)**
  - [ ] 10.1 `langgraph.types.Command` import + `update`/`goto` 패턴 적용.
  - [ ] 10.2 `user_input` 검증(`raw_text_clarified` 또는 `selected_value` 필수).
  - [ ] 10.3 Sentry transaction `meal_analysis_resume`.
  - [ ] 10.4 `tests/services/test_analysis_service.py` 갱신(clarification → aresume → 정상 종단 + 빈 input ValueError).

- [ ] **Task 11 — config + 데이터셋 (AC: #11)**
  - [ ] 11.1 `app/core/config.py`에 `food_retrieval_top_k` + `clarification_max_options` 추가.
  - [ ] 11.2 `api/tests/data/korean_foods_100.json` 신규 (100 행 + 분포 명시).
  - [ ] 11.3 `tests/test_config.py` 갱신(env override).
  - [ ] 11.4 `tests/test_korean_foods_dataset.py` 신규(schema + 분포 검증).
  - [ ] 11.5 `tests/test_korean_foods_dataset.py`에 *시드된 `food_nutrition.name`에 `expected_canonical` 모두 존재* 검증 추가(orphan 차단).

- [ ] **Task 12 — T3 KPI eval 테스트 (AC: #12)**
  - [ ] 12.1 `tests/test_korean_foods_eval.py` 신규 (`@pytest.mark.eval`).
  - [ ] 12.2 `api/pyproject.toml [tool.pytest.ini_options].markers`에 `eval` 추가(line 95-97 `perf` 패턴 정합).
  - [ ] 12.3 `RUN_EVAL_TESTS=1` 게이트 환경 변수 분기.
  - [ ] 12.4 dev mock LLM / staging 실 LLM 분기 문서화(테스트 docstring).

- [ ] **Task 13 — perf + 게이트 + commit/push (AC: #13)**
  - [ ] 13.1 `tests/rag/test_food_search_perf.py` 신규(`@pytest.mark.perf`).
  - [ ] 13.2 `tests/graph/test_pipeline_perf.py` budget 갱신(stub → 실 budget 3s/5s).
  - [ ] 13.3 `cd api && uv run ruff check . && uv run ruff format --check .` 통과.
  - [ ] 13.4 `cd api && uv run mypy app` 0 에러 회귀.
  - [ ] 13.5 `cd api && uv run pytest` 통과 + coverage ≥ 70%.
  - [ ] 13.6 sprint-status `3-4-* → in-progress`(DS 시작 시).
  - [ ] 13.7 sprint-status `3-4-* → review`(DS 종료 시 + last_updated 갱신).
  - [ ] 13.8 단일 commit + push (`feat(story-3.4): ...`).

## Dev Notes

### Architecture Patterns (Story 3.3 정합 + 본 스토리 추가)

- **노드 시그니처 SOT** — `async def <node_name>(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]` 패턴 유지. 본 스토리 신규 노드(`request_clarification`)도 동일.
- **`_node_wrapper` 자동 부착** — Story 3.3 `_wrapper.py`가 (a) tenacity 1회 retry, (b) Sentry span, (c) NodeError fallback 자동 부착. 본 스토리는 wrapper 코드 변경 X — 노드 함수만 수정 + 신규.
- **dict-merge 정합** — 모든 반환은 dict — `LangGraph`가 `MealAnalysisState`(`total=False`)에 부분 병합. `model_dump()` 호출로 Pydantic instance → dict 변환(checkpoint 직렬화 round-trip 안전 — Story 3.3 CR 보강 정합).
- **state field access** — `get_state_field` helper(Story 3.3 `state.py:131-143`)로 Pydantic instance / dict 양 형태 수용. 본 스토리 `route_after_evaluate` 갱신 시 동일 패턴.
- **closure deps 주입** — `pipeline.py`가 `partial(node, deps=deps)` 패턴(Story 3.3 SOT — 본 스토리는 `request_clarification`도 동일 등록).
- **NFR-S5 마스킹 SOT** — raw_text/raw alias name/canonical_name 모두 1줄 로그 X. items_count + path 분류 + latency_ms + score 통계만(Story 3.1/3.2/3.3 패턴 정합 — 회귀 0건).
- **Self-RAG 1회 한도 회귀 가드** — Story 3.3 `evaluate_retrieval_quality`의 `node_errors` 카운트 합산 로직(`evaluate_retrieval_quality.py:46-49`)은 본 스토리에서 변경 X — 무한 루프 차단 SOT 보존.

### LangGraph 3.x Command 패턴 (`aresume` 강화 — AC10)

- **`Command(update={...}, goto="parse_meal")`** — LangGraph 3.x의 noeud 진입 갱신 + 분기 점프 SOT. `from langgraph.types import Command` import.
- **재개 시 reset 필요 필드** — `parsed_items=None`, `retrieval=None`, `rewrite_attempts=0`, `node_errors=[]`, `needs_clarification=False`, `clarification_options=[]`, `evaluation_decision=None`. *재개의 본질*: 사용자 정제 텍스트로 새 흐름 시작 — 직전 시도의 상태는 *clean slate*.
- **thread_id 격리** — checkpointer가 thread_id별 격리이므로 `aresume` 호출자는 *동일 thread_id*를 전달 책임(Story 3.7 라우터 책임).
- **dev 환경 graceful** — `aresume`이 thread_id 미존재 시 `aget_state` snapshot None — graph가 `parse_meal`부터 새 흐름 진입(Story 3.3 정합).

### `meals.parsed_items` JSONB 우선 패턴 (AC5)

- **Story 2.3 OCR 결과 영속화 SOT** — `meals.parsed_items` JSONB는 OCR Vision의 `[{name, quantity, confidence}]` 영속화. 본 스토리 `parse_meal` 노드는 *DB 우선* — LLM 재호출 cost 0(이미 parse된 사진 입력은 영속화된 결과 재사용).
- **NULL 분기** — `parsed_items IS NULL`은 두 케이스: (a) 텍스트-only 식단(사진 입력 X) — LLM parse 필요, (b) 사진 + parse 미호출(Story 2.3 후처리 누락 — 운영상 발생 가능 — graceful fallback 진입).
- **jsonb → FoodItem 매핑** — `[{"name":..., "quantity":..., "confidence":...}]` 형태 가정. 잘못된 형태(예: dict 아닌 string 또는 missing keys) → Pydantic ValidationError → wrapper retry 1회 → fallback NodeError(downstream graceful).

### `food_aliases` + `food_nutrition` 검색 흐름 (AC3-AC4-AC6)

- **3단 검색 SOT** — alias → exact → HNSW. alias 50+건 시드(Story 3.1) + `food_nutrition` 1500-3000건 시드(Story 3.1). HNSW `vector_cosine_ops` 인덱스 + `embedding NULL` 자동 제외(Story 3.1 D4 정합).
- **score 정규화** — pgvector `<=>` cosine distance는 0(완전 일치)~2(반대) 범위. `score = 1 - (distance / 2)` 0~1 정규화 + clip [0, 1]. exact 매칭은 score=1.0 고정(임베딩 호출 X — 비용 절약).
- **multi-item min confidence** — 한 식사가 2+ 음식 시 *최소* 신뢰도가 전체 confidence(보수적). 한 항목이라도 모호하면 Self-RAG 재검색 분기.
- **NFR-P6 정합** — Story 3.1 NFR-P6(`food_nutrition` 검색 p95 ≤ 200ms)은 *DB 자체*만 — 본 스토리는 *임베딩 호출 + DB*로 p95 ≤ 800ms 목표. 분석 budget(NFR-P4 ≤ 3s) 안에서 안전.

### `clarification_options` UX 백엔드 신호 (AC1, AC9, AC10)

- **본 스토리 책임** — `needs_clarification: bool` + `clarification_options: list[ClarificationOption]` *백엔드 state 박기*. UI 카드 렌더링은 Story 3.7.
- **`ClarificationOption.label` vs `value`** — `label`은 UI 노출 라벨(짧은 한국어 ≤50자), `value`는 `aresume` 시 `parse_meal` 입력으로 갈 정제 텍스트(라벨 + 양 추정 — 예: `"연어 포케 1인분"` ≤80자).
- **graph 일시 정지** — `request_clarification` → `END` edge로 graph 종료(`fit_score`/`feedback` 미진행). checkpointer가 state 영속화 → `aget_state(thread_id)`로 조회 가능.
- **재개 — Story 3.7 라우터** — `POST /v1/analysis/{thread_id}/clarify` 엔드포인트(Story 3.7 OUT)가 `selected_value` 받아 `aresume` 호출. 본 스토리는 *내부 호출 가능 인터페이스*만.

### Project Structure Notes

- **신규 모듈** — `app/rag/food/normalize.py` + `app/rag/food/search.py` + `app/graph/nodes/request_clarification.py` + `api/tests/data/korean_foods_100.json` + `api/tests/rag/test_food_normalize.py` + `api/tests/rag/test_food_search.py` + `api/tests/rag/test_food_search_perf.py` + `api/tests/graph/nodes/test_request_clarification.py` + `api/tests/test_korean_foods_dataset.py` + `api/tests/test_korean_foods_eval.py`. architecture line 654-655 정합(`rag/food/normalize.py` + `rag/food/search.py` 명시).
- **갱신 모듈** — `app/adapters/openai_adapter.py`(parse_meal_text + rewrite_food_query + generate_clarification_options) + `app/graph/state.py`(ClarificationOption + clarification_options 필드) + `app/graph/nodes/parse_meal.py`(실 로직) + `app/graph/nodes/retrieve_nutrition.py`(실 로직) + `app/graph/nodes/rewrite_query.py`(실 로직) + `app/graph/nodes/evaluate_retrieval_quality.py`(clarify 분기) + `app/graph/edges.py`(3-way 라우터) + `app/graph/pipeline.py`(request_clarification 등록) + `app/graph/nodes/__init__.py`(export 갱신) + `app/services/analysis_service.py`(aresume Command 패턴) + `app/core/config.py`(food_retrieval_top_k + clarification_max_options) + 기존 테스트 6개 갱신.
- **데이터 인벤토리 — `api/data/`** — Story 3.1 baseline `mfds_food_nutrition_seed.csv`(ZIP fallback) + Story 3.2 baseline `guidelines/`(KDRIs PDF chunks). 본 스토리는 *추가 시드 X* — 데이터셋(`korean_foods_100.json`)은 `api/tests/data/`(테스트 자원).
- **`food_aliases` 추가 시드 X** — Story 3.1의 50+건이 본 스토리 baseline. 외주 클라이언트 alias 추가는 `data/README.md`(Story 3.1) 3 경로 SOP.
- **mypy strict** — 신규 모듈 type hint 완전성 + `pgvector.sqlalchemy.Vector` import는 Story 3.1 `food_nutrition.py` 패턴 정합. `psycopg.sql.Identifier` 같은 raw SQL composer 사용 시 `.cast(...)` annotation 필요(Story 3.3 checkpointer.py:68 정합).

### Testing Standards

- **pytest + pytest-asyncio + httpx AsyncClient** — Story 1.1 baseline 패턴 정합 (`asyncio_mode=auto`).
- **markers** — `@pytest.mark.eval`(신규 — 본 스토리) + `@pytest.mark.perf`(Story 3.3 baseline). `pytest.ini` markers 추가 + 디폴트 skip + 환경 변수(`RUN_EVAL_TESTS=1`/`RUN_PERF_TESTS=1`) 게이트 활성화 패턴.
- **mock LLM** — `monkeypatch` 또는 `unittest.mock.patch`로 `openai_adapter.parse_meal_text`/`rewrite_food_query`/`generate_clarification_options`/`embed_texts` mock(Story 3.1 `_call_embedding` mock 패턴 정합 — `tests/rag/test_food_seed.py` 참고).
- **DB integration** — `db_deps` fixture(Story 3.3 `tests/graph/conftest.py`) 재사용 — 실 PG + Story 3.1 시드 후 alias/exact/HNSW 검증.
- **coverage ≥ 70%** — 전체 baseline. 신규 모듈(`rag/food/normalize` + `search` + `nodes/request_clarification`)은 ≥ 80% 권장(분기 가드 명시).
- **회귀 가드** — Story 3.3의 404 passed / 5 skipped(perf) baseline에서 +30 ≈ 434+ passed 목표(eval skip default 5건 추가). 0 회귀.

### References

- [Source: epics.md:626-639] — Story 3.4 BDD ACs (alias 1차 lookup + 임베딩 fallback + 재검색 + 재질문 + aresume + 한식 100건 ≥ 90%).
- [Source: epics.md:583-595] — Story 3.1 `food_aliases` 50+건 시드 + `food_nutrition` 1500-3000건 + HNSW 인덱스(본 스토리 입력).
- [Source: epics.md:611-624] — Story 3.3 LangGraph 6노드 + Self-RAG + AsyncPostgresSaver(본 스토리 baseline).
- [Source: epics.md:705] — Story 3.8 `scripts/upload_eval_dataset.py` LangSmith Dataset 업로드(본 스토리는 데이터 SOT만, 자동화는 3.8).
- [Source: prd.md:93] — *2. Self-RAG 재검색 노드* + 음식명 정규화 사전 + 임베딩 fallback (한국식 음식 매칭 정확도).
- [Source: prd.md:131] — *"이게 짜장면이 맞나요? 양은 1인분인가요?"* 형태 재질문 UX.
- [Source: prd.md:157] — T2 KPI Self-RAG 재검색 동작(테스트 케이스 ≥ 5건 회귀 가드).
- [Source: prd.md:287-299] — Journey 2 모바일 Edge Case Self-RAG 재질문 종단 시나리오.
- [Source: prd.md:550-555] — IA1 Self-RAG의 한국 음식 도메인 적용 + T2/T3 KPI 검증 방법.
- [Source: prd.md:610-614] — Self-RAG 1회 한도 강제 + retrieval_confidence 임계값 0.6 + W2 spike 튜닝.
- [Source: prd.md:968-970] — FR18 (재검색) + FR19 (정규화 매칭) + FR20 (재질문 UX).
- [Source: prd.md:1033-1034] — NFR-P4 ≤ 3s + NFR-P5 +2s 분석 budget.
- [Source: architecture.md:289-292] — `food_aliases` 외주 인수 alias 추가 SOP + 본 스토리 normalize.py 1차 lookup 입력.
- [Source: architecture.md:654-655] — `app/rag/food/normalize.py` + `search.py` 모듈 명시.
- [Source: architecture.md:917-925] — 분석 핵심 경로 시퀀스 + 분기 노드 + needs_clarification 분기.
- [Source: architecture.md:976-978] — FR18-FR20 코드 위치 매핑(`evaluate_retrieval_quality` + `rewrite_query` + `normalize.py` + `food_aliases` + edges.py needs_clarification 분기).
- [Source: architecture.md:1042] — R1 음식명 매칭 mitigation = `rag/food/normalize.py` + `food_aliases` + 임베딩 fallback.
- [Source: api/app/graph/state.py:30-65] — `FoodItem`/`RetrievedFood`/`RetrievalResult` Pydantic 모델 (본 스토리 사용).
- [Source: api/app/graph/state.py:131-143] — `get_state_field` helper(Pydantic instance / dict 양 형태 수용 — 본 스토리 라우터 갱신 시 동일 패턴).
- [Source: api/app/graph/nodes/_wrapper.py:50-118] — `_node_wrapper` 데코레이터 SOT(retry + Sentry + NodeError fallback — 본 스토리 신규 노드도 동일 부착).
- [Source: api/app/graph/nodes/evaluate_retrieval_quality.py:42-60] — Self-RAG 1회 한도 + node_errors 카운트 합산(무한 루프 가드 — 본 스토리 변경 X).
- [Source: api/app/graph/nodes/retrieve_nutrition.py:26-34] — `_LOW_CONFIDENCE_SENTINEL` + `_TEST_ENVIRONMENTS` 분기(test 환경 hook — 본 스토리 보존 + 실 흐름 추가).
- [Source: api/app/graph/checkpointer.py:74-119] — AsyncPostgresSaver thread_id 격리(`aresume` 호출자 책임 — Story 3.7).
- [Source: api/app/services/analysis_service.py:38-101] — `run`/`aget_state`/`aresume` 진입점(본 스토리 `aresume` 강화).
- [Source: api/app/adapters/openai_adapter.py:97-258] — Vision OCR 패턴(structured output + tenacity 1회 retry + lazy singleton — 본 스토리 `parse_meal_text`/`rewrite_food_query`/`generate_clarification_options`이 동일 패턴 재사용).
- [Source: api/app/adapters/openai_adapter.py:285-302] — `embed_texts` (본 스토리 `search_by_embedding` 입력).
- [Source: api/app/db/models/food_alias.py] — `FoodAlias` ORM model + `UNIQUE(alias)` 제약(본 스토리 normalize 1차 lookup 대상).
- [Source: api/app/db/models/food_nutrition.py] — `FoodNutrition` ORM + `nutrition` jsonb + `embedding` Vector(1536) + HNSW(본 스토리 search 대상).
- [Source: api/app/db/models/meal.py:73] — `meals.parsed_items` JSONB(본 스토리 parse_meal DB 우선 입력).
- [Source: api/app/rag/food/aliases_data.py] — `FOOD_ALIASES` 50+건 const(본 스토리 baseline — 추가 X).
- [Source: api/app/rag/food/seed.py + aliases_seed.py] — Story 3.1 시드(본 스토리 입력).
- [Source: _bmad-output/implementation-artifacts/3-3-langgraph-6노드-self-rag-saver.md] — Story 3.3 본문(상위 baseline + 회귀 가드 정합 + CR 18 patches 정합).
- [Source: langgraph docs — Command type] — `Command(update=..., goto=...)` 패턴(`aresume` 강화 SOT — LangGraph 3.x).
- [Source: pgvector docs — vector_cosine_ops] — `<=>` cosine distance 연산자(0~2 범위) + HNSW `m=16, ef_construction=64`(Story 3.1 D5 정합).

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m]

### Debug Log References

### Completion Notes List

### File List
