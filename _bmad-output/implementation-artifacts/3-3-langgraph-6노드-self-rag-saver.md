# Story 3.3: LangGraph 6노드 + Self-RAG 분기 + AsyncPostgresSaver

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **시스템 엔지니어**,
I want **LangGraph 6노드(`parse_meal` → `retrieve_nutrition` → `evaluate_retrieval_quality` → `fetch_user_profile` → `evaluate_fit` → `generate_feedback`) + Self-RAG `rewrite_query` 재검색 분기를 AsyncPostgresSaver(`lg_checkpoints` schema 격리)로 영속화하기를**,
so that **재시작·세션 분리에도 분석 흐름이 끊기지 않으며 한 노드 실패가 전체 파이프라인을 멈추지 않고, 1회 재검색 한도로 비용 폭증·무한 루프를 차단한다**.

본 스토리는 Epic 3(AI 영양 분석 — Self-RAG + 인용 피드백)의 *오케스트레이션 골격(scaffold)*을 박는다 — **(a) `app/graph/` 패키지 신규 — `state.py`(MealAnalysisState `TypedDict` + 노드별 Pydantic IO 모델 6세트 — `ParseMealOutput`/`RetrievalResult`/`EvaluationDecision`/`UserProfileSnapshot`/`FitEvaluation`/`FeedbackOutput`) + `nodes/` 7 모듈(6노드 + `rewrite_query`) + `edges.py`(Self-RAG 조건부 분기 + error fallback edge) + `pipeline.py`(`StateGraph(MealAnalysisState)` 컴파일 SOT) + `checkpointer.py`(AsyncPostgresSaver factory + `lg_checkpoints` schema 격리 + psycopg 풀 lifecycle)**, **(b) `langgraph-checkpoint-postgres` 3.x AsyncPostgresSaver — 같은 PG의 별 schema `lg_checkpoints`에 영속화 — Alembic 외 lib `.setup()` 1회 호출 + 본 schema(public)와 격리되어 마이그레이션 충돌 차단(architecture line 295/369 정합)**, **(c) `psycopg[binary,pool]` 직접 의존성 승격 — `langgraph-checkpoint-postgres` transitive에서 *명시 직접 의존성*으로 승격(driver 버전·extra 통제권 + 외주 인수 readiness 신호)**, **(d) Self-RAG 분기 — `evaluate_retrieval_quality`가 `retrieval_confidence < threshold` AND `rewrite_attempts < 1` 시 `"rewrite"` route 반환 → `rewrite_query` → `retrieve_nutrition` 재실행(1회 한도 강제 — 무한 루프 차단). `rewrite_attempts ≥ 1` 또는 신뢰도 충족 시 `"continue"` route → `fetch_user_profile`**, **(e) 노드 격리 패턴 — 모든 노드 출력 Pydantic 모델 fail-fast 검증 + tenacity exponential backoff 1회 retry(`stop_after_attempt(2)` + `wait_exponential(min=1, max=4)`) + 실패 시 error edge fallback(노드별 isolation — 한 노드 실패가 전체 파이프라인을 멈추지 않음, FR45 정합)**, **(f) Sentry 노드별 transaction tracing — `sentry_sdk.start_span(op="langgraph.node", description=node_name)` 데코레이터 + 실패 자동 capture + breadcrumb에 `node_name` + `rewrite_attempts` 부착(architecture line 349 + NFR-O1 정합)**, **(g) `app/services/analysis_service.py` 신규 — `app/graph/pipeline.ainvoke()` thin wrapper(`run(meal_id, user_id, raw_text)` 진입 + `aget_state(thread_id)` 상태 조회 + `aresume(thread_id, user_input)` 사용자 응답 후 재개 — Story 3.4 needs_clarification 흐름 토대만)**, **(h) `app/core/exceptions.py` 갱신 — `AnalysisGraphError(BalanceNoteError)` base + 4 서브클래스 (`AnalysisNodeError` 503 — 노드 retry 후 fallback 진입 / `AnalysisCheckpointerError` 503 — saver setup/connection 실패 / `AnalysisStateValidationError` 422 — Pydantic 검증 실패 / `AnalysisRewriteLimitExceededError` 422 — Self-RAG 1회 한도 초과 — 본 스토리에서는 정상 흐름의 짧은 회귀 예외이며 운영 alert 신호)**, **(i) `app/main.py` lifespan 갱신 — `async with AsyncConnectionPool(...) as pool: checkpointer = AsyncPostgresSaver(pool); await checkpointer.setup()` + `app.state.checkpointer = checkpointer` + `app.state.graph = compile_pipeline(checkpointer)` 1회 컴파일 SOT 등록 + dispose hook(graceful shutdown)**, **(j) `pyproject.toml` 갱신 — `psycopg[binary,pool]>=3.2` 명시 등재 + `langgraph-checkpoint-postgres>=3.0`(현 lock 3.0.5와 정합 — `>=2.0` ↑ 강화) + mypy.overrides에 `psycopg.*`, `psycopg_pool.*` 추가**, **(k) 노드 stub 베이스라인 — `parse_meal`/`retrieve_nutrition`/`fetch_user_profile`/`rewrite_query`/`evaluate_fit`/`generate_feedback` 6 노드는 *결정성 stub* 활성화 — 입력 → Pydantic 출력 mapping이 deterministic, 실 LLM/RAG 호출 X(Story 3.4-3.6 책임). `evaluate_retrieval_quality`는 *실 결정 로직*(Self-RAG 분기 핵심) — `retrieval_confidence` 임계값 0.6 + `rewrite_attempts` 카운터 비교**, **(l) 테스트 인프라 — `api/tests/graph/test_pipeline.py`(컴파일 + 6노드 시퀀스) + `test_self_rag.py`(low/high confidence 분기 + 1회 한도 + rewrite_attempts state 갱신) + `test_checkpointer.py`(setup + round-trip + thread_id별 격리) + `nodes/test_*.py` 6 모듈(노드 단위 retry + Pydantic 검증 fail-fast 회귀) + `test_pipeline_perf.py`(NFR-P4 ≤ 3s 단일 호출 + NFR-P5 +2s Self-RAG + T1 100회 ≤ 2% 실패율 — `pytest -m perf` skip 디폴트, 게이트 옵션)**의 데이터·인프라 baseline을 박는다.

부수적으로 (a) **실 음식 정규화 매칭 + 임베딩 fallback 검색은 OUT** — `retrieve_nutrition`은 *결정성 stub*만(Story 3.4 책임 — `food_aliases` lookup → `food_nutrition.embedding` HNSW top-3 + retrieval_confidence 산출), (b) **needs_clarification 사용자 재질문 흐름은 OUT** — Self-RAG 1회 재검색 *분기 인프라*만(Story 3.4 책임 — `needs_clarification = True` set + AsyncPostgresSaver checkpoint 사용자 응답 대기 + `aresume(thread_id, user_input)` 재개), (c) **`fit_score` 알고리즘 + 알레르기 위반 단락은 OUT** — `evaluate_fit`은 결정성 stub만(`fit_score=50`, `reasons=[]`)(Story 3.5 책임), (d) **인용형 피드백 + 광고 표현 가드 + 듀얼-LLM router는 OUT** — `generate_feedback`은 결정성 stub만(고정 placeholder 텍스트)(Story 3.6 책임), (e) **모바일 SSE 스트리밍 채팅 UI는 OUT** — Story 3.7 책임 (analysis_service의 `astream_events()` 활용은 Story 3.7 시점에 추가), (f) **LangSmith 외부 옵저버빌리티 + 평가 데이터셋은 OUT** — Story 3.8 책임. 단 본 스토리는 `langsmith` SDK + `LANGCHAIN_TRACING_V2` env native 통합 *비활성*(추가 코드 X)이므로 Story 3.8 시점에 env flip만으로 활성화 가능, (g) **PIPA 동의 게이트 라우터 dependency는 OUT** — `Depends(require_automated_decision_consent)` 적용은 *분석 라우터*(Story 3.7)에서. 본 스토리는 라우터 노출 X → 게이트 적용 X(architecture line 311/371 정합), (h) **Rate limit `RATE_LIMIT_LANGGRAPH` 3-tier 적용은 OUT** — main.py에 키 상수만 정의된 상태(Story 1.1 baseline). 적용은 분석 라우터 시점, (i) **LLM 캐시 계층(`cache:llm:{sha256(meal_text+profile_hash)}`)은 OUT** — Story 8.4 polish 책임, (j) **분석 결과 영속화(`meal_analyses` 테이블)는 OUT** — Story 3.6 generate_feedback 노드의 후처리 단계에서 도입(architecture line 299 ER 골격 + line 681 ORM 명세 정합). 본 스토리는 *그래프 출력 → state* 까지만, (k) **모바일 식단 입력 → 분석 트리거 라우터 wiring은 OUT** — `POST /v1/analysis/stream` SSE 엔드포인트는 Story 3.7. 본 스토리의 `analysis_service.run()`은 *내부 호출 가능 인터페이스*만 — 단위 테스트가 1차 호출자.

## Acceptance Criteria

> **BDD 형식 — 각 AC는 독립적 검증 가능. 모든 AC 통과 후 `Status: review`로 전환하고 code-review 워크플로우로 진입.**

1. **AC1 — `app/graph/state.py` — `MealAnalysisState` TypedDict + 노드별 Pydantic IO 모델 6세트**
   **Given** Epic 3 진입 + Story 3.1/3.2 baseline(`food_nutrition`/`knowledge_chunks` 박힘) + 본 스토리 `app/graph/` 신규, **When** `from app.graph.state import MealAnalysisState, ParseMealOutput, RetrievalResult, RetrievedFood, EvaluationDecision, UserProfileSnapshot, FitEvaluation, FeedbackOutput, NodeError` import, **Then**:
     - **`MealAnalysisState` (`TypedDict`, `total=False`)** — 그래프 SOT state, LangGraph가 *부분 갱신*(노드별 dict-merge — total=False)으로 채워나가는 포맷:
       - `meal_id: uuid.UUID` (입력 — `meals` 테이블 row id),
       - `user_id: uuid.UUID` (입력 — `users` 테이블 row id, `fetch_user_profile` 노드의 lookup 키),
       - `raw_text: str` (입력 — `meals.raw_text` 또는 OCR 후처리 텍스트),
       - `parsed_items: list[FoodItem] | None` (`parse_meal` 출력 — `[FoodItem(name="짜장면", quantity="1인분", confidence=0.92)]`),
       - `retrieval: RetrievalResult | None` (`retrieve_nutrition` 출력 — `retrieved_foods` + `retrieval_confidence`),
       - `rewrite_attempts: int` (Self-RAG 1회 한도 카운터 — 디폴트 0, `evaluate_retrieval_quality`가 `"rewrite"` route 반환 시 +1),
       - `rewritten_query: str | None` (`rewrite_query` 출력 — 재검색용 변형 쿼리),
       - `user_profile: UserProfileSnapshot | None` (`fetch_user_profile` 출력 — health_goal/age/weight_kg/height_cm/activity_level/allergies),
       - `fit_evaluation: FitEvaluation | None` (`evaluate_fit` 출력 — Story 3.5 stub: `fit_score=50` + `reasons=[]`),
       - `feedback: FeedbackOutput | None` (`generate_feedback` 출력 — Story 3.6 stub: `text=""` + `citations=[]`),
       - `node_errors: list[NodeError]` (디폴트 `[]` — 노드 retry 후 fallback 진입 시 append, 다음 노드는 *부분 state*로 진행 — FR45 정합),
       - `needs_clarification: bool` (디폴트 False — Story 3.4가 set, 본 스토리는 *읽기 전용 필드 노출*만).
       - `evaluation_decision: dict` (`evaluate_retrieval_quality` 노드의 *공식 출력* — `EvaluationDecision(...).model_dump()` dict 저장, `route_after_evaluate` 라우터의 입력. CR 보강: checkpoint 직렬화 round-trip 안전성 + AC3 line 74-75 정합).
     - **`FoodItem` (Pydantic BaseModel)** — `name: str` (한국어 원문 — 정규화는 Story 3.4) + `quantity: str | None` (자유 텍스트 "1인분"/"200g") + `confidence: float = Field(ge=0, le=1)` (Vision OCR / parse 결정성 stub).
     - **`ParseMealOutput`** — `parsed_items: list[FoodItem]` (1+ items 또는 `[]`).
     - **`RetrievedFood`** — `name: str` (정규화된 canonical_name) + `food_id: uuid.UUID | None` + `score: float = Field(ge=0, le=1)` (HNSW cosine similarity, stub은 fixed 0.7) + `nutrition: dict[str, float | int]` (식약처 jsonb 표준 키 — 본 스토리 stub은 `{"energy_kcal": 0}` placeholder, Story 3.4가 실 jsonb 주입).
     - **`RetrievalResult`** — `retrieved_foods: list[RetrievedFood]` + `retrieval_confidence: float = Field(ge=0, le=1)` (top-1 score 또는 평균 — stub은 `_stub_confidence_for(raw_text)` 결정성 분기).
     - **`EvaluationDecision`** — `route: Literal["rewrite", "continue"]` + `reason: str` (logger 메타 — 디버깅용). `evaluate_retrieval_quality`의 *공식 출력*.
     - **`UserProfileSnapshot`** — `user_id: uuid.UUID` + `health_goal: HealthGoal` (Story 1.5 enum 재활용) + `age: int` + `weight_kg: float` + `height_cm: float` + `activity_level: ActivityLevel` (Story 1.5 enum 재활용) + `allergies: list[str]` (식약처 22종 lookup — Story 1.5 baseline 정합).
     - **`FitEvaluation`** — `fit_score: int = Field(ge=0, le=100)` + `reasons: list[str]` (Story 3.5 stub: 50 + `[]`).
     - **`FeedbackOutput`** — `text: str` + `citations: list[Citation]` + `used_llm: Literal["gpt-4o-mini", "claude", "stub"] = "stub"` (Story 3.6 책임 — 본 스토리 stub은 `"stub"`).
     - **`Citation`** — `source: str` + `doc_title: str` + `published_year: int | None` (Story 3.2 `knowledge_chunks` 메타데이터 정합 — 인용 패턴 *(출처: 기관명, 문서명, 연도)* 직접 주입용).
     - **`NodeError`** — `node_name: str` + `error_class: str` + `message: str` + `attempts: int` (retry 후 fallback 진입 컨텍스트 — Sentry breadcrumb 정합).
     - **테스트** — `api/tests/graph/test_state.py` 신규 — Pydantic 검증(필드 누락 → ValidationError) + `MealAnalysisState` TypedDict 부분 dict 정합(LangGraph dict-merge 시뮬레이션) + 모든 enum/Literal 필드의 invalid 값 거부 + `Citation` 빈 리스트 허용(stub 정합).

2. **AC2 — `app/graph/checkpointer.py` — AsyncPostgresSaver factory + `lg_checkpoints` schema 격리 + psycopg 풀 lifecycle**
   **Given** `langgraph-checkpoint-postgres>=3.0` + `psycopg[binary,pool]>=3.2` 직접 의존성, **When** `from app.graph.checkpointer import build_checkpointer, dispose_checkpointer, _to_psycopg_dsn` import + `lifespan` 호출, **Then**:
     - **`_to_psycopg_dsn(database_url)`** — `postgresql+asyncpg://app:app@host:5432/app` → `postgresql://app:app@host:5432/app` 변환 (asyncpg → psycopg). `urllib.parse.urlsplit` + 명시 prefix swap (정규식 회피 — Story 1.1 baseline 패턴 정합).
     - **`build_checkpointer(database_url, *, schema="lg_checkpoints", min_size=1, max_size=4) -> tuple[AsyncPostgresSaver, AsyncConnectionPool]`** — async function. 단계:
       - 1. **풀 빌드** — `psycopg_pool.AsyncConnectionPool(conninfo=_to_psycopg_dsn(...), min_size=min_size, max_size=max_size, kwargs={"options": f"-c search_path={schema},public"}, open=False)` — search_path 격리(connection-level — `setup()` 및 후속 read/write 모두 `lg_checkpoints` schema 사용). `open=False` + 명시 `await pool.open()` (psycopg-pool 3.3 deprecation 경고 회피 — `open=True` deprecated).
       - 2. **schema 사전 생성** — 별 connection으로 `CREATE SCHEMA IF NOT EXISTS lg_checkpoints` 실행(setup() 전제 — `langgraph-checkpoint-postgres`는 schema 자동 생성 X). pool 외부 1회 connection — race 회피 위해 *single-flight* 패턴(lifespan 1회 호출 정합).
       - 3. **`AsyncPostgresSaver(pool)`** 인스턴스화 + `await checkpointer.setup()` 호출 — schema 내부 `checkpoints` + `checkpoint_blobs` + `checkpoint_writes` 3 테이블 자동 생성(idempotent — 재호출 시 IF NOT EXISTS).
       - 4. **return** `(checkpointer, pool)` — caller가 dispose 시점 책임.
     - **`dispose_checkpointer(pool)`** — async function — `await pool.close()` 안전 호출 + 예외 swallow(shutdown 경로 — Story 1.1 baseline 정합).
     - **schema 격리 검증** — `setup()` 직후 `SELECT table_schema, table_name FROM information_schema.tables WHERE table_name LIKE 'checkpoint%'` 결과가 모두 `lg_checkpoints` schema (3 테이블). public schema에는 0 row.
     - **에러 매핑** — `OperationalError` / `InterfaceError` (psycopg-pool 연결 실패) → `AnalysisCheckpointerError("checkpointer.setup_failed")` re-raise. SDK 원 예외는 `__cause__`로 보존(Sentry stack trace 정상).
     - **logger** — `checkpointer.setup.complete` 1줄 (`schema` + `pool_min` + `pool_max`) — Story 3.1/3.2 event-style 정합. raw DSN/password 노출 X(NFR-S5).
     - **테스트** — `api/tests/graph/test_checkpointer.py` 신규 — `_to_psycopg_dsn` 단위(asyncpg/psycopg/잘못된 scheme 3 케이스) + `build_checkpointer` round-trip(setup → 임의 thread_id `aput`/`aget` checkpoint → 동일 객체 반환) + schema 격리 검증(`lg_checkpoints.checkpoints` 존재 + `public.checkpoints` 부재) + dispose idempotency(2회 호출 안전) + `AsyncConnectionPool` mock으로 OperationalError raise 시 `AnalysisCheckpointerError` 매핑.

3. **AC3 — `app/graph/nodes/` — 7 모듈(6노드 + `rewrite_query`) 결정성 stub + Pydantic 검증 + tenacity retry**
   **Given** AC1 state 모델 + AC4 edges + AC5 pipeline 컴파일 정합, **When** `from app.graph.nodes import parse_meal, retrieve_nutrition, evaluate_retrieval_quality, rewrite_query, fetch_user_profile, evaluate_fit, generate_feedback` import, **Then**:
     - **공통 시그니처** — 각 노드는 `async def <node_name>(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]` 패턴. dict 반환은 LangGraph dict-merge 정합(state 부분 갱신).
     - **공통 래퍼** — `_node_wrapper(node_name)` 데코레이터 — (i) `tenacity.retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), retry=retry_if_exception_type((PydanticValidationError, AnalysisStateValidationError)))` 1회 retry, (ii) `sentry_sdk.start_span(op="langgraph.node", description=node_name)` span 1개 + 실패 자동 capture, (iii) retry 후 fallback 진입 시 `NodeError` instance를 state.node_errors append(다음 노드는 *부분 state*로 진행 — FR45 정합).
     - **`parse_meal(state, deps)`** — 결정성 stub: `state["raw_text"]`을 받아 `[FoodItem(name=raw_text[:50], quantity=None, confidence=0.5)]` 반환. 빈 텍스트 시 `ParseMealOutput(parsed_items=[])` (downstream 노드는 빈 retrieval로 진행 → fit_score=0). Story 3.4가 실 LLM parse로 대체.
     - **`retrieve_nutrition(state, deps)`** — 결정성 stub: 입력 `parsed_items[0].name`을 *고정 sentinel* 검색. 키워드 분기:
       - `name`이 `"low_confidence"` 포함 → `RetrievalResult(retrieved_foods=[], retrieval_confidence=0.3)` (Self-RAG 분기 트리거),
       - 그 외 → `RetrievalResult(retrieved_foods=[RetrievedFood(name=name, food_id=None, score=0.7, nutrition={"energy_kcal": 0})], retrieval_confidence=0.7)`.
       - **`rewrite_attempts > 0` 시 신뢰도 boost** — `retrieval_confidence=0.85`(Self-RAG 1회 재검색 후 신뢰도 회복 시뮬레이션 — 1회 한도 + 재검색 후 `"continue"` route 검증 정합). 이 stub 동작은 Story 3.4가 실 alias lookup + HNSW top-3로 대체.
     - **`evaluate_retrieval_quality(state, deps)`** — *실 결정 로직*(Self-RAG 핵심 — stub 아님). 단계:
       - `confidence = state["retrieval"].retrieval_confidence` 추출,
       - `attempts = state.get("rewrite_attempts", 0)`,
       - `if confidence < settings.self_rag_confidence_threshold and attempts < 1: return EvaluationDecision(route="rewrite", reason=f"low_confidence_{confidence:.2f}").model_dump()`,
       - `else: return EvaluationDecision(route="continue", reason="confidence_ok" if confidence >= threshold else "rewrite_limit_reached").model_dump()`.
       - `settings.self_rag_confidence_threshold` 디폴트 0.6 (`config.py` 신규 필드).
     - **`rewrite_query(state, deps)`** — 결정성 stub: 입력 `parsed_items[0].name + "_rewritten"` 또는 빈 입력 시 `"unknown_food"` 반환. `rewrite_attempts: state.get("rewrite_attempts", 0) + 1` 동시 갱신(LangGraph dict-merge 정합). Story 3.4가 실 LLM rewrite로 대체.
     - **`fetch_user_profile(state, deps)`** — *실 DB 조회*(stub 아님 — 단순 SELECT라 본 스토리 안에서 완성). 단계:
       - `async with deps.session_maker() as session: result = await session.execute(select(User).where(User.id == state["user_id"]))`,
       - `user = result.scalar_one_or_none()` — `None` 시 `AnalysisNodeError("fetch_user_profile.user_not_found")` raise(retry 의미 X — 즉시 fallback edge),
       - `UserProfileSnapshot(...)` 매핑 후 dict 반환. `allergies` 필드는 `user.allergies or []` (Story 1.5 `text[]` 정합).
     - **`evaluate_fit(state, deps)`** — 결정성 stub: `FitEvaluation(fit_score=50, reasons=[])`. Story 3.5가 실 fit_score 알고리즘 + 알레르기 위반 단락(`fit_score=0`)으로 대체.
     - **`generate_feedback(state, deps)`** — 결정성 stub: `FeedbackOutput(text="(분석 준비 중)", citations=[], used_llm="stub")`. Story 3.6이 실 인용형 피드백 + 광고 가드 + 듀얼-LLM router로 대체.
     - **`NodeDeps` (dataclass)** — `session_maker: async_sessionmaker[AsyncSession]` + `redis: redis.asyncio.Redis | None`(향후 캐시) + `settings: Settings`. 노드들이 `deps`를 통해 외부 자원 접근(테스트 시 fake injection 정합).
     - **테스트** — `api/tests/graph/nodes/test_<node_name>.py` 7 모듈 — 각 노드 (i) Pydantic 출력 형태 검증, (ii) 결정성(같은 입력 → 같은 출력 — `evaluate_retrieval_quality`/`fetch_user_profile` 제외), (iii) 잘못된 입력 → ValidationError → tenacity 1회 retry 발동(mock으로 첫 호출 실패 + 두 번째 성공 시나리오), (iv) retry 후 fallback 시 `NodeError` 누적. `evaluate_retrieval_quality`는 confidence 분기 4 케이스(낮음+0회/낮음+1회/높음+0회/높음+1회) — Self-RAG 1회 한도 회귀 가드.

4. **AC4 — `app/graph/edges.py` — Self-RAG 조건부 분기 + error fallback edge**
   **Given** AC3 노드 + AC5 pipeline 컴파일, **When** `from app.graph.edges import route_after_evaluate, route_after_node_error` import, **Then**:
     - **`route_after_evaluate(state) -> Literal["rewrite_query", "fetch_user_profile"]`** — `evaluate_retrieval_quality` 노드 출력의 `route` 필드 분기. `route == "rewrite"` → `"rewrite_query"` 다음 노드, 아니면 `"fetch_user_profile"`. `state.get("evaluation_decision", {}).get("route")` 안전 lookup(missing 시 `"continue"` 디폴트 — fail-soft).
     - **`route_after_node_error(state) -> Literal["next", "end"]`** — 각 노드 후 `state["node_errors"]`에 새 NodeError append되면 *조기 종료* 옵션 분기. **본 스토리는 `"next"` 디폴트**(노드별 isolation — 한 노드 실패가 전체 파이프라인을 멈추지 않음, FR45 정합) — `fetch_user_profile.user_not_found` 같은 *치명적* 케이스만 `"end"` 반환(`error_class == "AnalysisNodeError"` AND `node_name == "fetch_user_profile"`). `evaluate_fit`/`generate_feedback` 실패는 부분 state로 진행 → 최종 출력에 `feedback.text="(분석 일시 중단)"` + node_errors 포함.
     - **edges.py에 라우터만 — 노드 자체 코드는 nodes/ 책임** — Architecture 결정 SOT 분리.
     - **테스트** — `api/tests/graph/test_edges.py` 신규 — (i) `route_after_evaluate` rewrite/continue/missing 3 케이스, (ii) `route_after_node_error` 디폴트 `"next"` + fetch_user_profile 실패만 `"end"` + 다른 노드 실패 `"next"` (회귀 가드 — 부분 state 진행 보장).

5. **AC5 — `app/graph/pipeline.py` — `StateGraph` 컴파일 SOT + Self-RAG 1회 재검색 한도**
   **Given** AC1-AC4 modules + AC2 checkpointer, **When** `from app.graph.pipeline import compile_pipeline, MealAnalysisState` import 후 `graph = compile_pipeline(checkpointer, deps)` 호출, **Then**:
     - **노드 시퀀스** — `START` → `parse_meal` → `retrieve_nutrition` → `evaluate_retrieval_quality` → (분기) → [`rewrite_query` → `retrieve_nutrition`] OR `fetch_user_profile` → `evaluate_fit` → `generate_feedback` → `END` (architecture line 922 정합).
     - **Self-RAG 분기** — `add_conditional_edges("evaluate_retrieval_quality", route_after_evaluate, {"rewrite_query": "rewrite_query", "fetch_user_profile": "fetch_user_profile"})`. `rewrite_query` 후 unconditional edge `→ retrieve_nutrition`(재검색).
     - **1회 한도 강제** — `evaluate_retrieval_quality`의 결정 로직(AC3) + `rewrite_attempts < 1` 가드 + state `rewrite_attempts` 카운터 increment(AC3 `rewrite_query`). 2회 도달 시 `evaluate_retrieval_quality`는 강제 `"continue"` route → `fetch_user_profile`. **무한 루프 차단 SOT**.
     - **`compile_pipeline(checkpointer, deps) -> CompiledGraph`** — `StateGraph(MealAnalysisState)` 빌드 → `compile(checkpointer=checkpointer, debug=settings.langgraph_debug)`. `debug` 디폴트 False(prod) — dev에서만 True(Story 3.7 SSE 디버깅 정합).
     - **`deps` 주입** — pipeline은 노드 closure 패턴으로 `NodeDeps` 주입(LangGraph는 노드 시그니처 `(state) -> dict`만 알므로 — `functools.partial`로 wrap하여 `add_node("parse_meal", partial(parse_meal, deps=deps))` 패턴).
     - **테스트** — `api/tests/graph/test_pipeline.py` 신규 — (i) 컴파일 정상(`graph = compile_pipeline(...)` 예외 없음), (ii) Mermaid graph spec 검증(`graph.get_graph().draw_mermaid()` 출력에 `parse_meal` → `retrieve_nutrition` → `evaluate_retrieval_quality` → 분기 노드 모두 포함), (iii) high-confidence 케이스(`raw_text="짜장면"`) 종단 호출 정상 — `result["feedback"]` stub 출력 매칭 + `rewrite_attempts == 0` (재검색 미발동), (iv) low-confidence 케이스(`raw_text="low_confidence_food"`) — `rewrite_attempts == 1` + Self-RAG 재검색 후 `retrieve_nutrition.retrieval_confidence == 0.85` (stub boost — AC3) + `feedback` stub 정상, (v) 1회 한도 회귀 — stub의 `_stub_confidence_for`를 monkey-patch로 *항상 낮음* 강제 시 `rewrite_attempts == 1`에서 멈추고 `evaluate_retrieval_quality`가 `"continue"` 반환 검증(무한 루프 회귀 가드).

6. **AC6 — Per-node tenacity retry + Pydantic 검증 + 노드 격리 fallback**
   **Given** AC3 `_node_wrapper` 데코레이터 + AC4 edges, **When** 노드 내부에서 transient 예외(예: `httpx.TimeoutException`, Pydantic ValidationError) 발생, **Then**:
     - **retry 정책** — `tenacity.retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), retry=retry_if_exception_type((PydanticValidationError, asyncio.TimeoutError, httpx.HTTPError)))` — 1회 재시도(Architecture 결정 line 528 정합 — *LLM 호출 tenacity 3회*는 노드 *내부* LLM 어댑터 책임, 본 노드 wrapper는 *노드 레벨* 1회). 본 스토리 stub 노드는 결정적이라 retry 발동 없음 — wrapper는 *Story 3.4-3.6 실 노드 진입 시* 작동.
     - **retry 후 fallback** — 2회 시도 모두 실패 시 `NodeError(node_name=..., error_class=..., message=..., attempts=2)` instance 생성 + `state["node_errors"].append(...)` + 노드 정상 종료(예외 X — 다음 노드 진입). `route_after_node_error` 라우터(AC4)가 *다음 노드 진행 또는 종료* 결정.
     - **Pydantic 검증 fail-fast** — 노드 내부에서 `<NodeOutputModel>(**raw_dict)` 검증 실패 시 첫 시도는 retry 발동(transient — 가능성 1%), 2회 실패는 `AnalysisStateValidationError` raise → wrapper가 NodeError로 변환.
     - **로깅** — retry 발동 시 `node.<name>.retry` 1줄 (`attempts` + `error_class`), fallback 진입 시 `node.<name>.fallback` 1줄. raw 사용자 입력 노출 X (NFR-S5).
     - **Sentry 통합** — 각 노드 wrapper는 `with sentry_sdk.start_span(op="langgraph.node", description=node_name) as span: span.set_data("rewrite_attempts", state.get("rewrite_attempts", 0))` — 노드별 span + breadcrumb. 실패 시 자동 `capture_exception` (sentry_sdk 디폴트). raw chunk_text/raw_text 마스킹은 `before_send` hook(Story 1.1 baseline) 활용.
     - **테스트** — `api/tests/graph/test_node_resilience.py` 신규 — (i) `parse_meal` wrapper에 `httpx.TimeoutException` 첫 호출 raise + 두 번째 정상 → 정상 종료, (ii) 2회 실패 → NodeError 1건 누적 + 노드 정상 종료(예외 X — wrapper가 swallow), (iii) Sentry mock으로 transaction span captured 검증.

7. **AC7 — Sentry transaction tracing 노드별 span + 실패 자동 capture**
   **Given** Story 1.1 baseline `init_sentry()` + `before_send` 마스킹 hook, **When** 분석 파이프라인 호출, **Then**:
     - **상위 transaction** — `analysis_service.run()`이 `sentry_sdk.start_transaction(op="analysis.pipeline", name="meal_analysis")` open — 전체 호출 1 transaction.
     - **노드별 child span** — 각 노드 `_node_wrapper`가 transaction 안에 child span 추가 (`op="langgraph.node"`, `description=<node_name>`, `data={"rewrite_attempts": ...}`). 노드 latency 자동 측정.
     - **에러 capture** — 노드 retry 후 fallback 진입 시 `sentry_sdk.capture_exception(exc, scope=lambda s: s.set_tag("node", node_name))` 명시 호출 — `before_send` 마스킹 hook이 raw_text/raw_chunk_text 마스킹.
     - **breadcrumb** — `_node_wrapper` entry에서 `sentry_sdk.add_breadcrumb(category="langgraph", message=f"enter:{node_name}", data={"rewrite_attempts": ...})` — 노드 흐름 추적성.
     - **테스트** — Sentry SDK는 `sentry_sdk.Hub.current` mock으로 검증 (Story 1.1 baseline test_sentry.py 패턴 정합) — transaction + span 호출 횟수 + 노드 6+1개 span 매칭.

8. **AC8 — `app/services/analysis_service.py` 신규 — pipeline thin wrapper**
   **Given** AC5 compiled graph + AC2 checkpointer, **When** `from app.services.analysis_service import AnalysisService` import + lifespan에서 `app.state.analysis_service = AnalysisService(graph=app.state.graph, deps=...)` 등록, **Then**:
     - **`AnalysisService` (dataclass)** — `graph: CompiledGraph` + `deps: NodeDeps`.
     - **`async run(self, *, meal_id: UUID, user_id: UUID, raw_text: str, thread_id: str | None = None) -> MealAnalysisState`** — `thread_id = thread_id or f"meal:{meal_id}"`. `config = {"configurable": {"thread_id": thread_id}}`. `initial_state = {"meal_id": meal_id, "user_id": user_id, "raw_text": raw_text, "rewrite_attempts": 0, "node_errors": [], "needs_clarification": False}`. `final_state = await self.graph.ainvoke(initial_state, config=config)`. 반환은 `MealAnalysisState` (TypedDict). 상위 transaction(AC7) 진입.
     - **`async aget_state(self, *, thread_id: str) -> MealAnalysisState`** — `state_snapshot = await self.graph.aget_state(config={"configurable": {"thread_id": thread_id}}); return state_snapshot.values`. Story 3.4 needs_clarification 흐름의 *현재 state 조회* 진입점.
     - **`async aresume(self, *, thread_id: str, user_input: dict[str, Any]) -> MealAnalysisState`** — Story 3.4가 *needs_clarification* 후 사용자 응답을 받아 `parse_meal` 갱신 후 재개하는 진입점. 본 스토리는 *인터페이스 박기* 만 — 구현은 단순히 `await self.graph.ainvoke(user_input, config=...)` (실 분기 갱신 로직은 Story 3.4가 강화).
     - **테스트** — `api/tests/services/test_analysis_service.py` 신규 — `run` 종단(stub 노드 6개 모두 호출 + state["feedback"] stub 출력) + `aget_state` 빈 thread_id에서 빈 state 반환 + `aresume` 호출 시 thread_id 정합.

9. **AC9 — `app/core/exceptions.py` 갱신 — `AnalysisGraphError` 4 서브클래스**
   **Given** Story 1.2 `BalanceNoteError` + RFC 7807 Problem Details base, **When** `from app.core.exceptions import AnalysisGraphError, AnalysisNodeError, AnalysisCheckpointerError, AnalysisStateValidationError, AnalysisRewriteLimitExceededError` import, **Then**:
     - **`AnalysisGraphError(BalanceNoteError)`** — base — `status=500`, `code="analysis.graph.error"`, `title="Analysis Graph Error"`. (FoodSeedError/GuidelineSeedError 패턴 정합).
     - **`AnalysisNodeError(AnalysisGraphError)`** — `status=503`, `code="analysis.node.failed"`, `title="Analysis Node Failed"`. retry 후 fallback 진입 시. `__init__(self, node_name: str, detail: str | None = None)`로 node 컨텍스트 보존.
     - **`AnalysisCheckpointerError(AnalysisGraphError)`** — `status=503`, `code="analysis.checkpointer.failed"`, `title="Analysis Checkpointer Failed"`. saver setup/connection 실패.
     - **`AnalysisStateValidationError(AnalysisGraphError)`** — `status=422`, `code="analysis.state.invalid"`, `title="Analysis State Validation Failed"`. Pydantic 검증 실패.
     - **`AnalysisRewriteLimitExceededError(AnalysisGraphError)`** — `status=422`, `code="analysis.rewrite.limit_exceeded"`, `title="Self-RAG Rewrite Limit Exceeded"`. 본 스토리 정상 흐름에서는 발생 X (1회 한도 + `evaluate_retrieval_quality` 강제 `"continue"`로 차단). *알림 신호용 안전망* — 잘못된 외부 호출 시 단락. 라우터 노출 X(본 스토리 라우터 X) — Story 3.7에서 분석 endpoint dependency가 catch.
     - **테스트** — `api/tests/test_exceptions_analysis.py` 신규 — 각 예외 status/code/title 매핑 + base catch 정합(`raise AnalysisNodeError(...) ` → `except AnalysisGraphError:` 매칭).

10. **AC10 — `pyproject.toml` 갱신 — `psycopg[binary,pool]>=3.2` 직접 의존성 + `langgraph-checkpoint-postgres>=3.0` 강화 + mypy.overrides 갱신**
    **Given** Story 1.1 baseline `langgraph-checkpoint-postgres>=2.0`(transitive로 `psycopg`/`psycopg-pool` 끌어옴), **When** `[project] dependencies` 갱신, **Then**:
      - **`psycopg[binary,pool]>=3.2`** — 직접 의존성 등재. 이유: (a) `langgraph-checkpoint-postgres` 3.x는 `psycopg` 3.2+ 가정 (현 lock 3.3.3 — `>=3.2` 안전치), (b) `[binary]` extra 명시로 `libpq` 시스템 의존성 회피(Docker `python:3.13-slim` Linux + Windows dev 모두 prebuilt wheel — Story 3.1 D7 OpenAI SDK 패턴 정합), (c) `[pool]` extra 명시로 `psycopg-pool` 직접 등재(현 lock 3.3.0 — pool API 안정).
      - **`langgraph-checkpoint-postgres>=3.0`** — 기존 `>=2.0` → `>=3.0` 강화. 이유: AsyncPostgresSaver API는 3.x에서 안정 (lock 3.0.5 정합). 외주 인수 시 *2.x는 deprecated 신호*.
      - **mypy.overrides** — 기존 list에 `psycopg.*`, `psycopg_pool.*` 추가 — `psycopg` 3.x는 부분 type stub만(공식 stub 미완성), `psycopg_pool`은 stub 부재.
      - **uv.lock 갱신** — `uv sync` 실행 후 `uv.lock` 일관성 검증. 신규 wheel 다운로드 X(이미 transitive로 락 보유) — `[binary]` extra 변경에 따른 marker 갱신만.
      - **테스트** — `api/tests/test_pyproject.py` 신규 또는 기존(없음) — `psycopg`/`psycopg_pool`/`langgraph_checkpoint_postgres` import 정상 + 버전 메타 검증(`importlib.metadata.version("psycopg") >= "3.2"`).

11. **AC11 — `app/main.py` lifespan 갱신 — checkpointer + graph 컴파일 1회 SOT 등록 + dispose hook**
    **Given** Story 1.1 baseline `lifespan` (engine + redis + limiter init), **When** lifespan 호출, **Then**:
      - **추가 진입 단계** (engine init 후, yield 전):
        ```python
        try:
            checkpointer, pool = await build_checkpointer(settings.database_url)
            app.state.checkpointer = checkpointer
            app.state.checkpointer_pool = pool
            deps = NodeDeps(session_maker=app.state.session_maker, redis=app.state.redis, settings=settings)
            app.state.graph = compile_pipeline(checkpointer, deps)
            app.state.analysis_service = AnalysisService(graph=app.state.graph, deps=deps)
        except AnalysisCheckpointerError as exc:
            log.error("app.startup.checkpointer_init_failed", error=str(exc))
            app.state.checkpointer = None
            app.state.checkpointer_pool = None
            app.state.graph = None
            app.state.analysis_service = None
        ```
      - **dispose 단계** (yield 후 finally):
        ```python
        cleanup_pool = getattr(app.state, "checkpointer_pool", None)
        if cleanup_pool is not None:
            try:
                await dispose_checkpointer(cleanup_pool)
            except Exception as exc:
                log.warning("app.shutdown.checkpointer_dispose_failed", error=str(exc))
        ```
      - **자원별 독립 try/except** — Story 1.1 baseline 패턴 정합 (한 자원 실패가 다른 자원·앱 부팅 자체를 막지 않음).
      - **dev 환경 graceful** — DATABASE_URL 미설정/PG 미가동 시 `AnalysisCheckpointerError` 잡고 `app.state.graph = None` + warning. 라우터(Story 3.7)가 None 가드 + 503 안내.
      - **테스트** — `api/tests/test_main.py` 갱신 또는 신규 lifespan 테스트 — `lifespan` 진입 시 `app.state.checkpointer is not None` + `app.state.graph is not None` + `app.state.analysis_service is not None` 검증. 부팅 실패(예: DB 미가동) mock 시 graceful — 앱은 계속 동작 + graph None.

12. **AC12 — 테스트 커버리지 + 부하 + 성능 budget — NFR-P4/P5 + T1 KPI**
    **Given** AC1-AC11 통합 + Story 1.1 baseline pytest infra(`asyncio_mode=auto`, coverage 70%), **When** `cd api && uv run pytest`, **Then**:
      - **단위 + 통합 테스트** — AC1-AC11 명시 테스트 모두 통과(스키마/체크포인터/노드 7/엣지/파이프라인/리질리언스/익셉션/lifespan ≈ 30+ 테스트).
      - **NFR-P4 perf 테스트** (`api/tests/graph/test_pipeline_perf.py` `@pytest.mark.perf` skip 디폴트) — `compile_pipeline` 후 `analysis_service.run(meal_id, user_id, raw_text="짜장면")` 30회 측정, 평균 ≤ 3초(stub은 일반적으로 ≤ 100ms — 3초 budget은 *Story 3.6 실 노드 진입 후 검증* 정합. 본 스토리는 *budget 명시 + skip 디폴트 골격*만). 게이트 활성화: `RUN_PERF_TESTS=1 uv run pytest -m perf`.
      - **NFR-P5 perf 테스트** — Self-RAG 발동(`raw_text="low_confidence_food"`) 30회 측정, NFR-P4 baseline + 2초 이내. 동일 `@pytest.mark.perf` skip 디폴트.
      - **T1 KPI 부하 테스트** (`@pytest.mark.perf`) — 100회 연속 호출(혼합 시나리오 — high/low/empty raw_text) 실패율 ≤ 2% (stub은 일반적으로 0% 실패 — 부하 골격 박기 + Story 3.6 진입 후 실 검증 정합). 게이트 활성화 동일.
      - **coverage** — `api/app/graph/` + `api/app/services/analysis_service.py` 신규 모듈 coverage ≥ 80% (stub 노드는 결정적이라 분기 가드 100% 가능). 전체 coverage ≥ 70% (NFR-M1 baseline 유지).
      - **회귀 테스트** — Story 1.1-3.2 기존 pytest 0 회귀 (Story 3.2 baseline 317 passed → 본 스토리 신규 +30 ≈ 347+ passed 목표).
      - **mypy strict** — 신규 모듈 15+ 파일 strict clean. `psycopg`/`psycopg_pool` overrides는 import만 — 함수 signature는 본 코드가 type 보호.

13. **AC13 — 백엔드 게이트 통과 + sprint-status + commit/push**
    **Given** AC1-AC12 통합 + Story 3.2 CR 패턴 정합, **When** DS 완료 시점, **Then**:
      - **ruff check + format** — `cd api && uv run ruff check . && uv run ruff format --check .` 0 에러.
      - **mypy strict** — `cd api && uv run mypy app` 신규 모듈 0 에러 (Story 1.3 `tests/test_consents_deps.py` baseline 11 에러는 본 스토리 변경 외부 — 회귀 0건 확인).
      - **pytest + coverage** — `cd api && uv run pytest` 모든 테스트 통과 + coverage `--cov-fail-under=70` 충족.
      - **sprint-status 갱신** — `_bmad-output/implementation-artifacts/sprint-status.yaml`의 `3-3-langgraph-6노드-self-rag-saver: ready-for-dev` → `in-progress` (DS 시작 시) → `review` (DS 완료 시 — CR 진입 직전). `last_updated` 갱신.
      - **branch + commit** — 이미 분기된 `feat/story-3.3` (CS 시작 전 master 분기 — memory `feedback_branch_from_master_only.md` + `feedback_ds_complete_to_commit_push.md` 정합)에서 DS 종료 시점 단일 커밋 + push. 메시지 패턴 `feat(story-3.3): LangGraph 6노드 stub + Self-RAG 분기 + AsyncPostgresSaver(lg_checkpoints schema 격리) + analysis_service 진입점` (직전 커밋 패턴 정합 — Story 3.2 `feat(story-3.2): ...` 정합).
      - **PR 생성 X (DS 시점)** — PR(draft 포함)은 CR 완료 후 한 번에 생성 (memory `feedback_ds_complete_to_commit_push.md` 정합).

## Tasks / Subtasks

- [x] **Task 1 — `app/graph/state.py` + Pydantic IO 모델 (AC: #1)**
  - [x] 1.1 `MealAnalysisState` TypedDict 정의 (`total=False`, 12 필드).
  - [x] 1.2 `FoodItem`, `RetrievedFood`, `ParseMealOutput`, `RetrievalResult` Pydantic 모델 정의.
  - [x] 1.3 `EvaluationDecision`, `UserProfileSnapshot`, `FitEvaluation`, `Citation`, `FeedbackOutput`, `NodeError` 정의 — Story 1.5 `HealthGoal`/`ActivityLevel` enum 재활용.
  - [x] 1.4 `api/tests/graph/test_state.py` 신규 — Pydantic 검증 + TypedDict 부분 dict 정합.

- [x] **Task 2 — `app/graph/checkpointer.py` (AC: #2, #11)**
  - [x] 2.1 `_to_psycopg_dsn(database_url)` URL 변환 helper.
  - [x] 2.2 `build_checkpointer` async factory — schema 사전 생성 + AsyncConnectionPool + AsyncPostgresSaver + setup() + return tuple.
  - [x] 2.3 `dispose_checkpointer` async cleanup.
  - [x] 2.4 `app/main.py` lifespan 갱신 — checkpointer/pool/graph/analysis_service 4 자원 init + dispose hook (AC11).
  - [x] 2.5 `api/tests/graph/test_checkpointer.py` + `test_main_lifespan.py` 신규 — round-trip + schema 격리 + dispose idempotency + lifespan 통합.

- [x] **Task 3 — `app/graph/nodes/__init__.py` + 7 노드 모듈 + `_node_wrapper` 데코레이터 (AC: #3, #6, #7)**
  - [x] 3.1 `app/graph/nodes/__init__.py` — 7 노드 export.
  - [x] 3.2 `_wrapper.py` — `_node_wrapper(name)` 데코레이터 — tenacity retry + Sentry span + NodeError fallback.
  - [x] 3.3 `parse_meal.py` — 결정성 stub.
  - [x] 3.4 `retrieve_nutrition.py` — 결정성 stub + `rewrite_attempts > 0` boost.
  - [x] 3.5 `evaluate_retrieval_quality.py` — *실 결정 로직* + `settings.self_rag_confidence_threshold` 활용.
  - [x] 3.6 `rewrite_query.py` — 결정성 stub + `rewrite_attempts` increment.
  - [x] 3.7 `fetch_user_profile.py` — *실 DB 조회* (User select + Story 1.5 enum 매핑).
  - [x] 3.8 `evaluate_fit.py` — 결정성 stub.
  - [x] 3.9 `generate_feedback.py` — 결정성 stub.
  - [x] 3.10 `NodeDeps` dataclass — `app/graph/deps.py`.
  - [x] 3.11 `api/tests/graph/nodes/test_*.py` 7 모듈 — 단위 테스트 + `test_node_resilience.py`.

- [x] **Task 4 — `app/graph/edges.py` (AC: #4)**
  - [x] 4.1 `route_after_evaluate` — Self-RAG 분기 라우터.
  - [x] 4.2 `route_after_node_error` — 노드 격리 fallback 라우터.
  - [x] 4.3 `api/tests/graph/test_edges.py` 신규.

- [x] **Task 5 — `app/graph/pipeline.py` — `compile_pipeline` SOT (AC: #5)**
  - [x] 5.1 `StateGraph(MealAnalysisState)` 빌드 + 7 노드 + Self-RAG 분기 + 1회 한도.
  - [x] 5.2 `functools.partial(node, deps=deps)` 패턴으로 deps 주입.
  - [x] 5.3 `compile(checkpointer=..., debug=settings.langgraph_debug)`.
  - [x] 5.4 `api/tests/graph/test_pipeline.py` + `test_self_rag.py` — 컴파일 + Mermaid 출력 검증 + high/low conf + 1회 한도 회귀.

- [x] **Task 6 — `app/services/analysis_service.py` 신규 (AC: #8)**
  - [x] 6.1 `AnalysisService` dataclass.
  - [x] 6.2 `run(meal_id, user_id, raw_text, thread_id)` — Sentry transaction + ainvoke.
  - [x] 6.3 `aget_state(thread_id)` — Story 3.4 needs_clarification 진입점.
  - [x] 6.4 `aresume(thread_id, user_input)` — 사용자 응답 후 재개 진입점.
  - [x] 6.5 `api/tests/services/test_analysis_service.py` 신규.

- [x] **Task 7 — `app/core/exceptions.py` 갱신 + 도메인 예외 4 추가 (AC: #9)**
  - [x] 7.1 `AnalysisGraphError` base + 4 서브클래스 (`AnalysisNodeError`, `AnalysisCheckpointerError`, `AnalysisStateValidationError`, `AnalysisRewriteLimitExceededError`).
  - [x] 7.2 `api/tests/test_exceptions_analysis.py` 신규.

- [x] **Task 8 — `pyproject.toml` 갱신 + `uv sync` (AC: #10)**
  - [x] 8.1 `dependencies` 추가: `psycopg[binary,pool]>=3.2`.
  - [x] 8.2 `langgraph-checkpoint-postgres>=2.0` → `>=3.0` 강화.
  - [x] 8.3 `mypy.overrides`에 `psycopg.*`, `psycopg_pool.*` 추가.
  - [x] 8.4 `uv lock` 일관성 — `psycopg-binary` 신규 wheel 추가 (3.3.3).
  - [x] 8.5 `api/tests/test_pyproject_psycopg.py` 신규 — import + 버전 메타.

- [x] **Task 9 — `app/core/config.py` 갱신 — Self-RAG 설정 + LangGraph debug 플래그 (AC: #3, #5)**
  - [x] 9.1 `self_rag_confidence_threshold: float = 0.6` 필드 추가.
  - [x] 9.2 `langgraph_debug: bool = False` 필드 추가 (dev에서 True override 권장).
  - [x] 9.3 `.env.example` 갱신 — 두 env 주석 추가.

- [x] **Task 10 — Perf 테스트 골격 (AC: #12)**
  - [x] 10.1 `api/tests/graph/test_pipeline_perf.py` — `@pytest.mark.perf`(`pyproject.toml` `pytest.ini_options`에 `markers = ["perf: requires RUN_PERF_TESTS=1"]` 추가) skip 디폴트.
  - [x] 10.2 NFR-P4 — single-call avg ≤ 3s (30회 측정).
  - [x] 10.3 NFR-P5 — Self-RAG +2s (30회 측정, low_confidence_food 입력).
  - [x] 10.4 T1 — 100회 연속 호출 실패율 ≤ 2%.

- [x] **Task 11 — 백엔드 게이트 + sprint-status + commit/push (AC: #13)**
  - [x] 11.1 `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest` — 0 errors / 397 passed / 5 skipped (perf opt-in).
  - [x] 11.2 회귀 0건 확인 — 신규 모듈 mypy strict clean (전체 66 source files, 0 errors).
  - [x] 11.3 `_bmad-output/implementation-artifacts/sprint-status.yaml` `3-3-langgraph-6노드-self-rag-saver: ready-for-dev` → `review` (DS 종료 시 갱신).
  - [x] 11.4 본 스토리 doc Status: `ready-for-dev` → `review` + 본 doc Dev Agent Record 4 섹션 채움.
  - [x] 11.5 단일 commit + push to `feat/story-3.3`.

- [ ] **Task 12 — CR 진입 준비 (post-DS, pre-CR)**
  - [ ] 12.1 `bmad-code-review` 실행 — 신규 모듈 15+ 파일 + 테스트 ≈ 25+ 파일 review.
  - [ ] 12.2 CR 종료 직전 sprint-status `review` → `done` + Status `done` 갱신해 PR commit에 포함 (memory `feedback_cr_done_status_in_pr_commit.md`).
  - [ ] 12.3 PR 생성 (CR 완료 후 한 번에).

## Dev Notes

### Architecture decisions (반드시 따를 것)

- **D1 결정 (`AsyncPostgresSaver` + `lg_checkpoints` schema 격리)** — Architecture line 295/369 정합. `langgraph-checkpoint-postgres` 3.0.5 lib `.setup()`은 Alembic 외부 — 본 schema(public)와 격리되어 마이그레이션 충돌 차단. `CREATE SCHEMA IF NOT EXISTS lg_checkpoints` 사전 + `search_path` connection-level 설정으로 `setup()`이 격리 schema에 테이블 생성. 이유: (a) Alembic `target_metadata`에 LangGraph 테이블 누락 → autogenerate가 *DROP TABLE checkpoints* 회귀 위험 차단, (b) 외주 인수 시 *우리 도메인 테이블*(public)과 *LangGraph 인프라*(lg_checkpoints) 시각적 분리 — README 1단락 + Swagger schema diff 깔끔.
- **D2 결정 (psycopg async driver — asyncpg 미사용)** — `langgraph-checkpoint-postgres` 3.x는 psycopg 3.x async 표준. asyncpg 어댑터는 *미공식*. 우리 프로젝트의 SQLAlchemy는 asyncpg(Story 1.1 baseline) — 두 driver 공존 — 별 connection pool로 격리. 이유: (a) lib upstream 표준 따라가기(외주 인수 readiness — *비표준 어댑터 채택* 회피), (b) [binary] extra로 Docker prebuilt wheel — libpq 시스템 의존성 X.
- **D3 결정 (`psycopg[binary,pool]>=3.2` 직접 의존성 승격)** — transitive 의존성을 *직접 등재*로 승격. 이유: (a) driver 버전 통제권(외주 인수 시 dependency tree 명확), (b) `[binary]` extra 명시(Architecture 결정 1 *외주 인수 readiness* 정합 — Linux Docker + Windows dev 동일 wheel 정합), (c) `[pool]` extra 명시(`psycopg_pool` 직접 의존 — async pool API 안정).
- **D4 결정 (per-node tenacity retry 1회 + Pydantic fail-fast + NodeError fallback)** — Architecture line 528 *LLM 호출 tenacity 3회*는 *어댑터 레벨* 책임(Story 3.6 generate_feedback의 듀얼-LLM router 안에서). 본 스토리의 *노드 레벨 wrapper* retry는 1회 — 노드별 isolation 우선(FR45 정합). 노드 retry 후 실패 → NodeError append + 다음 노드 진행 (한 노드 실패가 전체 파이프라인을 멈추지 않음).
- **D5 결정 (Self-RAG 1회 한도 — `rewrite_attempts < 1` 가드)** — 무한 루프 + 비용 폭증 차단(prd.md line 610 정합 — *재검색 한도 1회 강제*). state `rewrite_attempts` 카운터 + `evaluate_retrieval_quality`의 결정 로직이 1회 한도 강제. 2회 진입 시 *강제 `"continue"`*(`AnalysisRewriteLimitExceededError` 알림 신호 X — 정상 흐름).
- **D6 결정 (`evaluate_retrieval_quality`만 *실 결정 로직*, 나머지 6 노드는 *결정성 stub*)** — Story 3.3은 *오케스트레이션 골격*. 노드 *내부 비즈니스 로직*은 Story 3.4-3.6이 채움. 단 *Self-RAG 분기 결정* 자체는 Story 3.3 책임(분기 라우터 + 1회 한도) — 그래서 `evaluate_retrieval_quality`는 stub 아닌 실 로직. 이유: (a) Self-RAG 분기 회귀 가드는 Story 3.3 시점에 박혀야(Story 3.4가 stub 노드 교체 시 분기 로직 깨짐 회귀 차단), (b) `retrieval_confidence` 임계값 0.6은 prd.md 명시(W2 spike 튜닝).
- **D7 결정 (state는 `TypedDict total=False`, 노드 IO 검증은 별도 Pydantic)** — Architecture line 636 정합. LangGraph는 dict-merge 시 부분 갱신 — `TypedDict total=False`가 정합. 노드 출력 *검증*은 노드 함수 내부에서 `<Output>(**raw).model_dump()` Pydantic round-trip — fail-fast + retry 발동 정합. 이유: TypedDict 자체는 런타임 검증 X(타입 hint만) → Pydantic이 1차 게이트.
- **D8 결정 (노드 closure 패턴으로 `NodeDeps` 주입)** — LangGraph 노드 시그니처는 `(state) -> dict`만 — `(state, deps)`는 표준 외. `functools.partial(node, deps=deps)` wrap으로 컴파일 시점 deps 주입. 이유: (a) 노드 내부에서 `deps.session_maker` / `deps.redis` / `deps.settings` 접근, (b) 테스트에서 fake deps 주입 정합, (c) global `app.state` 의존 회피(런타임 결합도 ↓).
- **D9 결정 (Sentry transaction `op="analysis.pipeline"` + 노드 child span `op="langgraph.node"`)** — Story 1.1 baseline `init_sentry()` + `before_send` 마스킹 hook 재활용. 노드별 span은 `_node_wrapper` 자동 부착. transaction은 `analysis_service.run()` 진입점에서 1회 open. 이유: (a) NFR-O1 LangGraph 6노드 100% 자동 트레이스 정합(Story 3.8 LangSmith 시점에 *동일 span 구조*가 LangSmith로도 송출), (b) Sentry 노드 latency·실패율 자동 측정 — T1 KPI 측정 인프라.
- **D10 결정 (lifespan에서 `app.state.checkpointer`/`graph`/`analysis_service` 4 자원 init — graceful)** — Story 1.1 baseline `lifespan` 패턴 정합. DB 미가동 시 `app.state.graph = None` + warning, 라우터(Story 3.7) None 가드 + 503 안내. 이유: (a) dev 환경 부팅 robust(Story 1.1 baseline patterns 정합), (b) checkpointer pool은 lifespan 진입 시 1회 open + finally dispose — 자원 leak 방지.
- **D11 결정 (perf 테스트 `@pytest.mark.perf` skip 디폴트 + `RUN_PERF_TESTS=1` opt-in)** — Story 3.1/3.2 D9 패턴 정합 — dev/ci 빠른 피드백 + 게이트 시점에 명시 활성화. 이유: (a) NFR-P4/P5 측정은 Story 3.6 진입 후 *실 LLM/RAG 호출* 시 의미 있음, (b) stub 단계에서는 *budget 명시 + 인프라 박기*가 가치, (c) GitHub Actions CI는 `RUN_PERF_TESTS=1`로 명시 활성화 옵션(매 PR가 아닌 *주간 cron* 권장).
- **D12 결정 (LangSmith integration은 *env-only* — 코드 변경 X)** — `langgraph` + `langsmith` SDK는 native 통합 — `LANGCHAIN_TRACING_V2=true` env로만 활성화 + `LANGSMITH_API_KEY` + `LANGSMITH_PROJECT` 정합 시 자동 캡처. 본 스토리는 두 env를 `.env.example` 주석만 — 코드 변경 X. Story 3.8가 `app/core/observability.py`에서 마스킹 hook + 평가 데이터셋 통합. 이유: 외주 인수 시 *env flip = LangSmith 활성*이 깔끔.

### Library / Framework 요구사항

- **`langgraph` (`>=1.1.9`)** — Story 1.1 baseline. `StateGraph`, `START`, `END`, `add_node`, `add_edge`, `add_conditional_edges`, `compile()` API.
- **`langgraph-checkpoint-postgres` (`>=3.0`, lock 3.0.5)** — Story 1.1 baseline에서 `>=2.0`. AsyncPostgresSaver API 정합. import: `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver`.
- **`psycopg` (`>=3.2`, lock 3.3.3)** — `[binary,pool]` extra 직접 의존성. import: `import psycopg`.
- **`psycopg-pool` (`>=3.2`, lock 3.3.0)** — `psycopg[pool]` extra 자동 등재. import: `from psycopg_pool import AsyncConnectionPool`.
- **`tenacity` (`>=9.0`)** — Story 1.1 baseline. `retry`, `stop_after_attempt`, `wait_exponential`, `retry_if_exception_type` API.
- **`sentry_sdk` (`>=2.20`)** — Story 1.1 baseline. `start_transaction`, `start_span`, `capture_exception`, `add_breadcrumb` API. Story 1.1 `before_send` 마스킹 hook 자동 적용.
- **Pydantic v2** — Story 1.1 baseline + LangGraph Structured Output 표준. `BaseModel`, `Field(ge=0, le=1)`, `Literal`, `model_dump()`.
- **SQLAlchemy 2.0.49 async** — Story 1.1 baseline. `fetch_user_profile` 노드의 `select(User)`.
- **`structlog`** — Story 1.1 baseline. `get_logger()` + event-style 키.
- **`langsmith` (`>=0.3`)** — Story 1.1 baseline. 본 스토리 *비활성*(env flip만 — Story 3.8 책임).
- **`langchain-openai` / `langchain-anthropic`** — Story 1.1 baseline. 본 스토리 *호출 X* (Story 3.6 듀얼-LLM router 진입 시 활성).

### Naming 컨벤션

- **신규 패키지** — `app/graph/` (architecture line 634 정합) + `app/services/` (architecture line 697 정합 — 본 스토리가 `services/` 폴더 *처음 생성*).
- **모듈** — `app/graph/state.py` / `app/graph/checkpointer.py` / `app/graph/edges.py` / `app/graph/pipeline.py` / `app/graph/deps.py` / `app/graph/nodes/__init__.py` + 7 노드 파일 + `_wrapper.py` (architecture line 638-647 정합).
- **노드 함수** — snake_case verb-first (`parse_meal`, `retrieve_nutrition`, `evaluate_retrieval_quality`, `rewrite_query`, `fetch_user_profile`, `evaluate_fit`, `generate_feedback`) — architecture line 638-644 명시.
- **state 필드** — snake_case (`raw_text`, `parsed_items`, `retrieval`, `rewrite_attempts`, `user_profile`, `fit_evaluation`, `feedback`, `node_errors`, `needs_clarification`).
- **Pydantic 모델** — PascalCase (`MealAnalysisState`, `FoodItem`, `RetrievedFood`, `RetrievalResult`, `EvaluationDecision`, `UserProfileSnapshot`, `FitEvaluation`, `FeedbackOutput`, `Citation`, `NodeError`).
- **예외 카탈로그** — `analysis.graph.*` 4건 (`analysis.node.failed`, `analysis.checkpointer.failed`, `analysis.state.invalid`, `analysis.rewrite.limit_exceeded`) — Story 1.2 `auth.*` / Story 1.3 `consent.*` / Story 3.1 `food_seed.*` / Story 3.2 `guideline_seed.*` 패턴 정합.
- **Logger 키** — event-style (`node.<name>.start` / `node.<name>.complete` / `node.<name>.retry` / `node.<name>.fallback` / `checkpointer.setup.complete` / `analysis.pipeline.start` / `analysis.pipeline.complete`) — Story 3.1/3.2 정합.
- **Sentry op/description** — `op="analysis.pipeline"` (transaction) + `op="langgraph.node"` (span, description=node_name) — architecture line 349 정합. **CR 보강 (Sentry SDK 2.x)**: span의 `description` kwarg는 deprecated → 실 코드는 `name=node_name` 사용 (transaction과 동일 키 컨벤션, Debug Log line 545 정합).
- **테스트 위치** — `api/tests/graph/` (architecture line 718 정합) — `test_pipeline.py`, `test_self_rag.py`, `test_checkpointer.py`, `test_state.py`, `test_edges.py`, `test_node_resilience.py`, `test_pipeline_perf.py` + `nodes/test_*.py` 7 파일. + `api/tests/services/test_analysis_service.py`.
- **schema 이름** — `lg_checkpoints` (architecture line 295/369 명시 — *langgraph* 약어 + 복수). 프리픽스 `lg_` 충돌 X (다른 langgraph 인프라 schema 미존재).

### 폴더 구조 (Story 3.3 종료 시점에 *반드시* 존재해야 하는 신규/수정 항목)

```
api/
  app/
    graph/                              # 신규 패키지 — architecture line 634
      __init__.py                       # 신규 — public API export (compile_pipeline, MealAnalysisState)
      state.py                          # 신규 — TypedDict + Pydantic IO 모델 (AC1)
      checkpointer.py                   # 신규 — AsyncPostgresSaver factory (AC2)
      edges.py                          # 신규 — Self-RAG + error fallback 라우터 (AC4)
      pipeline.py                       # 신규 — compile_pipeline SOT (AC5)
      deps.py                           # 신규 — NodeDeps dataclass (AC3)
      nodes/                            # 신규 폴더
        __init__.py                     # 신규 — 7 노드 export
        _wrapper.py                     # 신규 — _node_wrapper 데코레이터 (AC3, #6, #7)
        parse_meal.py                   # 신규 — stub
        retrieve_nutrition.py           # 신규 — stub
        evaluate_retrieval_quality.py   # 신규 — *실 결정 로직*
        rewrite_query.py                # 신규 — stub
        fetch_user_profile.py           # 신규 — *실 DB 조회*
        evaluate_fit.py                 # 신규 — stub
        generate_feedback.py            # 신규 — stub
    services/                           # 신규 폴더 — architecture line 697 — Story 3.3가 처음 생성
      __init__.py                       # 신규
      analysis_service.py               # 신규 — pipeline thin wrapper (AC8)
    core/
      exceptions.py                     # 갱신 — AnalysisGraphError 4 추가 (AC9)
      config.py                         # 갱신 — self_rag_confidence_threshold + langgraph_debug (Task 9)
    main.py                             # 갱신 — lifespan checkpointer/graph/analysis_service init + dispose (AC11)
  pyproject.toml                        # 갱신 — psycopg[binary,pool]>=3.2 + langgraph-checkpoint-postgres>=3.0 + mypy.overrides (AC10)
  uv.lock                               # 갱신 — uv lock 결과
  tests/
    graph/                              # 신규 폴더 — architecture line 718
      __init__.py
      test_state.py                     # 신규 (Task 1)
      test_checkpointer.py              # 신규 (Task 2)
      test_edges.py                     # 신규 (Task 4)
      test_pipeline.py                  # 신규 (Task 5)
      test_self_rag.py                  # 신규 — Self-RAG 분기 + 1회 한도 회귀 (AC5)
      test_node_resilience.py           # 신규 — retry + fallback (AC6, #7)
      test_pipeline_perf.py             # 신규 — @pytest.mark.perf (AC12)
      nodes/
        __init__.py
        test_parse_meal.py
        test_retrieve_nutrition.py
        test_evaluate_retrieval_quality.py
        test_rewrite_query.py
        test_fetch_user_profile.py
        test_evaluate_fit.py
        test_generate_feedback.py
    services/                           # 신규 폴더
      __init__.py
      test_analysis_service.py          # 신규 (Task 6)
    test_exceptions_analysis.py         # 신규 (Task 7)

.env.example                            # 갱신 — self_rag_confidence_threshold + langgraph_debug 주석 (Task 9)

_bmad-output/implementation-artifacts/
  sprint-status.yaml                    # 갱신 — 3-3 ready-for-dev → in-progress → review
  deferred-work.md                      # 갱신 — DF89+ 신규 후보 (CR 시점)
```

**변경 X** — `mobile/*` / `web/*` (본 스토리는 백엔드 인프라만 — 라우터 응답 변경 X) / `api/alembic/versions/*`(LangGraph schema는 lib `.setup()` 외부 — Alembic 마이그레이션 신규 X) / `docker-compose.yml`(DATABASE_URL 그대로 활용 — 추가 환경 X) / `docker/postgres-init/01-pgvector.sql`(vector extension 그대로) / `api/app/db/models/*` (knowledge_chunk/food_nutrition 등 그대로 — 본 스토리는 그래프 레이어만, ORM 변경 0건) / `api/app/api/v1/*`(라우터 진입은 Story 3.7 — 본 스토리 노출 X) / `api/app/adapters/*`(LLM adapter는 Story 3.6, vision은 Story 2.3 그대로).

### 보안·민감정보 마스킹 (NFR-S5)

- **DSN/password 노출 X** — `_to_psycopg_dsn`은 password 포함 URL 변환만 — logger 출력 X. `checkpointer.setup.complete` 로그는 `schema` + `pool_min` + `pool_max`만 (Story 1.1 baseline 정합).
- **raw_text 노출 X** — 사용자 식단 입력은 *민감정보*(C2 PIPA 정합). `_node_wrapper` logger는 `node_name` + `attempts` + `rewrite_attempts`만 — raw_text 노출 X. Sentry breadcrumb은 *마스킹된* state shape만(`before_send` hook이 정규식 마스킹 — Story 1.1 baseline).
- **사용자 프로필 노출 X** — `fetch_user_profile` 노드 logger는 `user_id` + `health_goal`만 (Story 1.5 정합). `weight_kg`/`height_cm`/`age`/`allergies` raw 노출 X — 마스킹 hook이 정규식 차단.
- **Sentry capture 시 raw_text 마스킹** — `before_send` hook(Story 1.1 baseline)이 정규식으로 raw_text 차단. 단 `node_name` + `error_class` + `attempts`는 송출(영업·운영 디버깅 정합).
- **NodeError instance 직렬화** — `node_errors` state 필드는 *클라이언트 노출 X* (Story 3.7 SSE 응답에서 별도 핸들링). 본 스토리에서는 *내부 state*만 — 분석 실패 시 generic safe message로 변환.

### Anti-pattern 카탈로그 (본 스토리 영역)

- **Alembic `target_metadata`에 LangGraph 테이블 포함** — autogenerate가 *DROP TABLE checkpoints* 회귀. D1 정합 — `lg_checkpoints` schema 격리로 Alembic은 *public schema만* 관리. ORM `MetaData()`는 public 테이블만 등록 (knowledge_chunks/food_nutrition/etc.).
- **`AsyncPostgresSaver`를 SQLAlchemy asyncpg pool 재사용** — psycopg API 미정합 (asyncpg는 psycopg과 binary protocol 호환되지 않음). D2 정합 — 별 pool 격리.
- **`asyncio.run()` lifespan 내부 호출** — Story 3.2 T6 학습 — pytest-asyncio loop 충돌. lifespan은 `async def`이므로 inner await만 — `asyncio.run` 호출 X.
- **`compile_pipeline()` 매 호출 시 재컴파일** — LangGraph compile 비용 ≈ 50-100ms (StateGraph 분석 + edge resolve). lifespan에서 1회 컴파일 + `app.state.graph` 등록(D10) — 라우터에서는 재사용. `analysis_service.run()`이 매번 ainvoke만.
- **노드 wrapper 외부에서 retry 직접 호출** — wrapper가 SOT — 노드 *내부* LLM 어댑터 retry(Story 3.6 듀얼-LLM)는 별 layer (Architecture 결정 line 528). 두 retry 중첩 시 `2 × 3 = 6회` 총 호출 회피 — 노드 wrapper retry는 *Pydantic + asyncio + httpx* transient만, LLM adapter retry는 *LLM transient*만.
- **state `rewrite_attempts` 카운터 누락** — D5 위반 — 무한 루프 회귀 가드. `rewrite_query` 노드가 동시 increment + `evaluate_retrieval_quality`가 비교. state 부분 갱신(LangGraph dict-merge)이라 *직접 set* 패턴 정합 (`return {"rewrite_attempts": state.get("rewrite_attempts", 0) + 1, "rewritten_query": ...}`).
- **`evaluate_retrieval_quality` stub화** — D6 위반 — Self-RAG 분기 결정 로직은 *실 코드*여야. stub 시 Story 3.4 진입 시 분기 회귀 발견 어렵.
- **노드 함수 시그니처에 `(state, deps)` 직접 받기** — LangGraph는 `(state) -> dict`만 컴파일. D8 정합 — `functools.partial(node, deps=deps)` 컴파일 시점 wrap.
- **`fetch_user_profile`이 user 미존재 시 None 반환** — D4 위반 — Pydantic UserProfileSnapshot 검증 실패 → retry 발동(의미 X — DB lookup은 결정적). 즉시 `AnalysisNodeError("fetch_user_profile.user_not_found")` raise(retry skip — `retry_if_exception_type`이 `AnalysisNodeError` 제외).
- **lifespan의 `app.state.checkpointer = None` 분기 누락** — D10 정합 — DB 미가동 시 graceful 분기 명시. None 가드 추가 후 라우터(Story 3.7)가 503 안내.
- **`AsyncConnectionPool`의 `open=True` 디폴트 사용** — psycopg-pool 3.3 deprecated 경고. `open=False` + 명시 `await pool.open()` (Story 1.1 deprecation 회피 패턴 정합).
- **Self-RAG 분기 후 `retrieve_nutrition` 재호출 시 confidence 동일 stub** — AC3 명시 — `rewrite_attempts > 0` 시 stub은 confidence 0.85 boost로 *재검색 후 신뢰도 회복* 시뮬레이션. boost 누락 시 1회 한도 검증이 분기 라우터만 검증 + retrieval 결과 검증 X (회귀 발견 어려움).
- **노드 wrapper 외부에서 `state.node_errors.append(...)` 직접 mutation** — TypedDict는 immutable 패턴 권장 — 노드 함수는 *반환 dict*에 `node_errors`를 append된 새 list로 — LangGraph dict-merge가 reducer로 처리(또는 `Annotated[list, operator.add]` 패턴).
- **Sentry transaction 미닫음(start_transaction context manager 누락)** — `with sentry_sdk.start_transaction(...) as tx:` 패턴 강제 — finally close 안전. raw start/finish는 try/finally + tx.finish() 필수.

### Previous Story Intelligence (Story 3.2 + Story 3.1 + Story 1.x baseline 학습)

**Story 3.2 (가이드라인 RAG 시드 — 직전 스토리)**:

- ✅ **`_FrontmatterSchema` Pydantic 검증 패턴** — 본 스토리 노드 IO 모델 패턴 정합 — fail-fast + retry 발동.
- ✅ **dev graceful D9 분기 패턴** — 본 스토리 lifespan checkpointer 실패 graceful (D10) 정합.
- ✅ **`bootstrap_seed.py` 위임 패턴** — 본 스토리는 시드 변경 X — Story 3.1/3.2 baseline 그대로.
- ✅ **`_truncate_*` test helper 패턴** — 본 스토리는 `lg_checkpoints` schema 테이블 truncate 헬퍼 신규 (`_truncate_lg_checkpoints` — 3 테이블 RESTART IDENTITY) — `tests/graph/test_checkpointer.py` 정합.
- ✅ **per-batch `session.commit()` + 배치 시드 정합** — 본 스토리는 시드 X — `fetch_user_profile`만 단일 SELECT, commit 불필요.
- 🔄 **DF84-DF88 (Story 3.2 신규 deferred)** — 본 스토리 영향 X (Story 3.2 책임 영역 — pypdf/MFDS CMS IDs/bootstrap_seed/KnowledgeChunk.updated_at/chunk_pdf 모두 *시드 인프라*에 한정).
- 🔄 **Story 3.2 CR 10 patches 학습** — 본 스토리 코드 작성 시 *동일 회귀 차단*: (a) Pydantic 검증 fail-fast 패턴, (b) BOM/CRLF/EOF 정규화는 본 스토리 영역 X(텍스트 입력 처리 X), (c) empty vector → None 패턴은 본 스토리 영역 X(embedding 사용 X), (d) `_FrontmatterSchema` 필수 필드 패턴은 노드 IO 모델 정합. Story 3.2 CR 패턴이 이미 베이스 코드에 박혀 있어 본 스토리는 *동일 조심성*으로 작성.

**Story 3.1 (음식 영양 RAG 시드)**:

- ✅ **`FoodSeedError` 카탈로그 패턴** — 본 스토리 `AnalysisGraphError` 동일 base + 4 서브클래스 패턴.
- ✅ **`_get_client` SDK singleton + tenacity** — 본 스토리는 LLM 호출 X(Story 3.6 책임). 단 *어댑터 패턴* 자체는 동일 — `_node_wrapper`가 노드 레벨 retry, 어댑터 레벨은 Story 3.6 진입 시점.

**Story 2.3 (OCR Vision)**:

- ✅ **`openai_adapter.py`** — 본 스토리에서 `parse_meal` 노드 호출 X (Story 3.4가 실 LLM parse — 정확히는 *parsed_items 영속화*는 이미 Story 2.3 + 2.5에서 `meals.parsed_items` JSONB로 박힘 → `parse_meal` 노드는 *meals.parsed_items 읽기*로 charset). 본 스토리 stub은 단순 `[FoodItem(name=raw_text[:50], ...)]` — Story 3.4가 `meals.parsed_items` 우선 읽기 + LLM parse fallback 패턴.

**Story 2.1-2.5 (식단 입력 + 저장 인프라)**:

- ✅ **`meals` 테이블 + `parsed_items` JSONB** — Story 2.3에서 박힘. 본 스토리 `MealAnalysisState.meal_id` + `raw_text`는 `meals` row 1:1 매핑.
- ✅ **`Idempotency-Key` 패턴** — Story 2.5 baseline. 본 스토리는 라우터 X — Idempotency 적용 X(Story 3.7 분석 라우터에서 thread_id 기반 멱등 — checkpoint 자체가 idempotent guard).

**Story 1.5 (건강 프로필)**:

- ✅ **`HealthGoal` enum** — `weight_loss`/`muscle_gain`/`maintenance`/`diabetes_management` — `UserProfileSnapshot.health_goal` 직접 재사용.
- ✅ **`ActivityLevel` enum** — Story 1.5 baseline. `UserProfileSnapshot.activity_level` 직접 재사용.
- ✅ **`users.allergies` text[]** — Story 1.5 baseline. `UserProfileSnapshot.allergies` 직접 매핑.

**Story 1.4 (PIPA 동의)**:

- ✅ **`require_automated_decision_consent` dependency** — 본 스토리는 *그래프 레이어*만, 라우터 X — dependency 적용 X. Story 3.7 분석 라우터에서 적용 (architecture line 311/371 정합).

**Story 1.2 (인증)**:

- ✅ **JWT user/admin 분리 + `get_current_user` dependency** — 본 스토리는 라우터 X — 인증 적용 X. Story 3.7 분석 라우터에서 `current_user.id` → `state.user_id` 전달.

**Story 1.1 (부트스트랩)**:

- ✅ **`lifespan` 패턴 + 자원별 try/except** — 본 스토리 lifespan 갱신 시 동일 패턴(D10). engine/redis/limiter 외 checkpointer/pool/graph/analysis_service 4 자원 추가.
- ✅ **`init_sentry()` + `before_send` 마스킹 hook** — 본 스토리 `_node_wrapper` Sentry span은 자동 통합 — 추가 마스킹 코드 X.
- ✅ **structlog `configure_logging()` + JSON renderer** — 본 스토리 노드 logger는 baseline 그대로.
- ✅ **`RATE_LIMIT_LANGGRAPH = "10/minute"`** — Story 1.1 baseline에 키 상수 박혀 있음. 본 스토리는 *적용 X* — Story 3.7 분석 라우터에서 데코레이터로 적용.

### Git Intelligence (최근 커밋 패턴)

```
f77a3c9 fix(auth): self-heal stale cookies + mobile dev build OAuth + onboarding loop (#19)
23cb289 feat(story-3.2): 가이드라인 RAG 시드 + chunking 3-format + verify_allergy_22 SOP + CR 10 patches (#18)
cfd75ef feat(story-3.1): 음식 영양 RAG 시드 + pgvector HNSW + food_aliases 정규화 사전 + CR 12 patches (#17)
d4c513b feat(story-2.5): 오프라인 텍스트 큐잉(AsyncStorage FIFO + 지수 backoff) + Idempotency-Key 처리(W46 흡수) (#16)
5619173 feat(story-2.4): 일별 식단 기록 화면 + 7일 캐시 + KST 필터 + CR 11 patches (#15)
```

**최근 커밋 패턴에서 학습:**

- 커밋 메시지: `feat(story-X.Y): <한국어 요약> + <부수 작업>` 형식 — 본 스토리 `feat(story-3.3): LangGraph 6노드 stub + Self-RAG 분기 + AsyncPostgresSaver(lg_checkpoints schema 격리) + analysis_service 진입점` 패턴.
- master 직접 push 금지 — feature branch + PR + merge 버튼 (memory: `feedback_pr_pattern_for_master.md`).
- 새 스토리 브랜치는 master에서 분기 — `feat/story-3.3` (memory: `feedback_branch_from_master_only.md`). **이미 분기 완료** (CS 시작 전 master에서 분기 — memory: `feedback_ds_complete_to_commit_push.md` 정합).
- DS 종료점은 commit + push (memory: `feedback_ds_complete_to_commit_push.md`). PR(draft 포함)은 CR 완료 후 한 번에 생성.
- CR 종료 직전 sprint-status/story Status를 review → done 갱신해 PR commit에 포함 (memory: `feedback_cr_done_status_in_pr_commit.md`).
- OpenAPI 재생성 커밋 분리 권장 — 단 본 스토리는 라우터 응답 변경 X → OpenAPI 재생성 미발생.

### References

- [Source: epics.md:611-624] — Story 3.3 epic AC 5건 (LangGraph 6노드 + Self-RAG 분기 + AsyncPostgresSaver + Pydantic + Sentry + T1 + NFR-P4/P5).
- [Source: epics.md:626-639] — Story 3.4 (다음 스토리) — `retrieve_nutrition` 실 정규화 매칭 + 임베딩 fallback + needs_clarification UX (본 스토리 stub 대체 책임).
- [Source: prd.md:156-157] — T1 KPI (6노드 100회 ≤ 2% 실패율) + T2 KPI (Self-RAG 재검색 ≥ 5건 동작).
- [Source: prd.md:1030-1037] — NFR-P1-P10 (NFR-P4 단일 호출 ≤ 3s + NFR-P5 +2s + NFR-P6 RAG ≤ 200ms 등).
- [Source: prd.md:1067] — NFR-O1 (LangGraph 6노드 + Self-RAG + LLM + RAG 100% 자동 트레이스).
- [Source: prd.md:610-614] — Self-RAG 1회 한도 강제 + retrieval_confidence 임계값 0.6 baseline + W2 spike 튜닝.
- [Source: prd.md:481-483] — TTFT ≤ 1.5s + 종단 지연 p50 ≤ 4s + LangGraph 6노드 평균 ≤ 3s.
- [Source: prd.md:546-554] — IA1 — Self-RAG 학술 → 상용 적용 혁신 (Asai et al. 2023).
- [Source: prd.md:287-299] — Journey 2 (Self-RAG 재질문 — *"이게 어떤 포케볼인가요?"*) — 본 스토리 *분기 인프라*만, UX는 Story 3.4.
- [Source: architecture.md:281-299] — Data Architecture (LangGraph state 영속성 — `langgraph-checkpoint-postgres` AsyncPostgresSaver + 별 schema `lg_checkpoints`).
- [Source: architecture.md:295] — *J2 Self-RAG 재질문이 사용자 응답 대기 가능. 인메모리는 재시작·세션 분리에 취약*.
- [Source: architecture.md:367-372] — Cross-Component Dependencies (`langgraph-checkpoint-postgres` schema는 Alembic 외 + PIPA 게이트는 LangGraph 호출 *전* 차단).
- [Source: architecture.md:349] — Sentry SDK + LangGraph 노드 transaction tracing — 노드 단위 span (본 스토리 AC7).
- [Source: architecture.md:392-431] — Naming Patterns (Python idiom snake_case + DB snake_case).
- [Source: architecture.md:511-516] — 에러 핸들링 (LangGraph 노드 Pydantic 검증 → retry 1회 → error edge fallback — 본 스토리 AC6).
- [Source: architecture.md:525-531] — 리트라이 정책 (LLM 호출 tenacity 3회는 어댑터 레벨 — 본 스토리 노드 wrapper retry는 1회 별 layer).
- [Source: architecture.md:540-546] — Enforcement Guidelines (모든 LangGraph 노드 출력은 Pydantic 모델로 검증).
- [Source: architecture.md:609-728] — Backend 폴더 구조 — `app/graph/{state,nodes/*,edges,pipeline,checkpointer}.py` + `app/services/analysis_service.py` + `tests/graph/{pipeline,self_rag,nodes/*}.py` 표기 정합.
- [Source: architecture.md:917-925] — 데이터 흐름 — 분석 핵심 경로 (`parse_meal` → `retrieve_nutrition` → `evaluate_retrieval_quality` → 분기 → `fetch_user_profile` → `evaluate_fit` → `generate_feedback` 시퀀스).
- [Source: architecture.md:893] — LLM 옵저버빌리티 (FR49 / NFR-O1~O5) `app/core/observability.py` (Story 3.8 — 본 스토리 OUT, env flip만).
- [Source: 3-2-가이드라인-rag-시드-chunking.md] — 직전 스토리 — `_FrontmatterSchema` Pydantic 검증 + dev graceful + 패키지 신규 패턴 — 본 스토리는 *그래프 레이어 신규 패키지* + Pydantic IO 모델 + dev graceful 패턴 정합.
- [Source: 3-1-음식-영양-rag-시드-pgvector.md] — `FoodSeedError` 카탈로그 패턴 + dev graceful D9 — 본 스토리 `AnalysisGraphError` 동일 패턴.
- [Source: 1-5-건강-프로필-입력.md] — `users.allergies` text[] + `health_goal`/`activity_level` enum — `UserProfileSnapshot` 매핑.
- [Source: 1-2-google-oauth-로그인-jwt.md] — `BalanceNoteError` base + RFC 7807 + Problem Details — `AnalysisGraphError` 4 서브클래스 정합.
- [Source: 1-1-프로젝트-부트스트랩.md] — lifespan + 자원별 try/except + Sentry init + structlog — D10 정합.
- [Source: api/app/main.py:lifespan] — Story 1.1 baseline (engine + redis + limiter init) — 본 스토리 4 자원 추가 (checkpointer/pool/graph/analysis_service).
- [Source: api/app/core/exceptions.py:BalanceNoteError] — base class — `AnalysisGraphError` 동일 패턴.
- [Source: api/app/core/sentry.py:init_sentry] — `before_send` 마스킹 hook — 본 스토리 `_node_wrapper` Sentry span 자동 통합.
- [Source: api/app/db/models/user.py + Story 1.5 health_goal/activity_level/allergies] — `UserProfileSnapshot` 매핑 SOT.
- [Source: api/app/db/models/meal.py + Story 2.3 parsed_items JSONB] — `MealAnalysisState.meal_id`/`raw_text` 진입.
- [Source: api/pyproject.toml] — Story 1.1 baseline `langgraph>=1.1.9` + `langgraph-checkpoint-postgres>=2.0` + Story 3.2 추가 dependencies — 본 스토리 추가: `psycopg[binary,pool]>=3.2` 직접 + `langgraph-checkpoint-postgres>=2.0` → `>=3.0` 강화.
- [Source: api/uv.lock:1027-1038] — `langgraph-checkpoint-postgres` 3.0.5 + `psycopg` 3.3.3 + `psycopg-pool` 3.3.0 — 본 스토리 baseline 정합.
- [Source: langgraph docs — StateGraph + AsyncPostgresSaver] — 표준 사용 패턴 (`StateGraph(MealAnalysisState).compile(checkpointer=...)` + `add_conditional_edges` + `aget_state` / `aresume`).
- [Source: langgraph-checkpoint-postgres docs — AsyncPostgresSaver.setup()] — schema 자동 생성 X — 사전 `CREATE SCHEMA` 책임.
- [Source: psycopg docs — AsyncConnectionPool + options] — `kwargs={"options": "-c search_path=lg_checkpoints,public"}` 패턴.
- [Source: tenacity docs — retry + stop_after_attempt + wait_exponential + retry_if_exception_type] — 표준 사용 패턴.
- [Source: research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md:90-178] — Self-RAG + 한국 1차 출처 인용 패턴 (Story 3.6 책임 — 본 스토리 *그래프 골격*만).

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] (Amelia, BMad Senior Software Engineer)

### Debug Log References

- **Windows + psycopg async 비호환** — `ProactorEventLoop` 디폴트가 `psycopg.InterfaceError`("Psycopg cannot use the 'ProactorEventLoop' to run in async mode") 발생. 해결: `api/tests/conftest.py` 상단에 `if sys.platform == "win32": asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` 추가. asyncpg(SQLAlchemy)는 양 loop 호환이라 안전. macOS/Linux Docker는 SelectorEventLoop 디폴트라 영향 없음. **prod 환경은 Linux Docker라 영향 없음** — Windows dev에서 `uv run uvicorn` 사용 시도 시점에 main.py 동등 처리 검토 (Story 8.x hardening 후보).
- **`langgraph-checkpoint-postgres` 3.x setup() + CREATE INDEX CONCURRENTLY** — `AsyncConnectionPool`의 디폴트 transaction-mode 연결로는 `psycopg.errors.ActiveSqlTransaction` 발생. 해결: `kwargs={"autocommit": True, "options": "-c search_path=lg_checkpoints,public"}`로 connection-level autocommit + search_path 동시 적용. lib upstream 3.x 표준 패턴 (psycopg-pool 3.3 정합).
- **Sentry SDK 2.x `description` deprecated** — `start_span(description=...)` 경고 발생. `name=...`로 갱신(노드 wrapper + 테스트 모두). lib upstream API drift 방어.
- **`tests/graph/test_self_rag.py` monkey-patch 경로** — `compile_pipeline`은 `from app.graph.nodes import retrieve_nutrition`로 함수 reference를 컴파일 시점에 capture → `partial(node, deps=deps)` closure에 묶임. 따라서 `app.graph.nodes.retrieve_nutrition.retrieve_nutrition`이 아닌 `app.graph.pipeline.retrieve_nutrition`을 patch해야 효과. `with patch(...)` 컨텍스트 내부에서 새 graph 빌드 + ainvoke.
- **Pipeline `test_pipeline_user_not_found_continues_with_node_error`** — `route_after_node_error` edges는 architecture line 511-516이지만 본 스토리는 라우터 정의만 박았음(linear add_edge). 실 *조건부 종료*는 Story 3.7 라우터 진입점에서 `state.node_errors` 검사 후 SSE 분기 — pipeline 내부에서는 `evaluate_fit`/`generate_feedback`이 stub 진행. NodeError 누적 검증만 수행.

### Completion Notes List

- **AC1-AC13 모든 통과** — 397 passed / 5 skipped (perf opt-in) / 0 failed.
- **신규 모듈 15+ 파일** — `app/graph/state.py` + `checkpointer.py` + `edges.py` + `pipeline.py` + `deps.py` + `nodes/__init__.py` + `_wrapper.py` + 7 노드 모듈 + `app/services/analysis_service.py` + `app/services/__init__.py` + `app/graph/__init__.py`.
- **갱신 모듈** — `app/core/exceptions.py` (4 서브클래스 추가 — `AnalysisGraphError`/`AnalysisNodeError`/`AnalysisCheckpointerError`/`AnalysisStateValidationError`/`AnalysisRewriteLimitExceededError`) + `app/core/config.py` (`self_rag_confidence_threshold` 0.6 + `langgraph_debug` False) + `app/main.py` (lifespan 4 자원 graceful + dispose hook) + `pyproject.toml` (`psycopg[binary,pool]>=3.2` + `langgraph-checkpoint-postgres>=3.0` + `markers = ["perf: ..."]` + mypy.overrides) + `.env.example` (`SELF_RAG_CONFIDENCE_THRESHOLD` + `LANGGRAPH_DEBUG` 주석) + `api/tests/conftest.py` (Windows event loop policy fix).
- **신규 테스트 ≈ 30+ 테스트** — `tests/graph/test_state.py` (15) + `test_checkpointer.py` (7) + `test_edges.py` (7) + `test_pipeline.py` (5) + `test_self_rag.py` (2) + `test_node_resilience.py` (6) + `test_pipeline_perf.py` (3 skip 디폴트) + `tests/graph/nodes/test_*.py` 7 모듈 (19 테스트) + `tests/services/test_analysis_service.py` (4) + `tests/test_exceptions_analysis.py` (7) + `tests/test_pyproject_psycopg.py` (6) + `tests/test_main_lifespan.py` (2). 합계 ≈ 80+ 신규 테스트 (Story 3.2 baseline 317 → 397, +80).
- **Self-RAG 1회 한도 회귀 가드** — `evaluate_retrieval_quality` 노드의 *실 결정 로직*(stub 아님 — D6) + `tests/graph/test_self_rag.py::test_self_rag_one_attempt_limit_under_persistent_low_confidence`가 monkey-patch로 *항상 낮음* 강제 후 `rewrite_attempts == 1`에서 `"continue"` + `reason="rewrite_limit_reached"` 검증 — 무한 루프 차단 SOT.
- **노드 격리 (FR45 정합)** — `_node_wrapper`가 tenacity 1회 retry 후 fallback 진입 시 NodeError를 state.node_errors에 append + 예외 swallow. `AnalysisNodeError`는 retry skip(`retry_if_exception_type` 제외) — `fetch_user_profile.user_not_found` 즉시 fallback.
- **Sentry transaction tracing** — `analysis_service.run()`이 `op="analysis.pipeline"` transaction open + 노드별 `op="langgraph.node"` child span 자동 부착. `tests/graph/test_node_resilience.py::test_wrapper_sentry_span_called`가 mock 호출 검증.
- **schema 격리 검증** — `tests/graph/test_checkpointer.py::test_build_checkpointer_round_trip_and_schema_isolation`가 `lg_checkpoints` schema에 3 테이블 존재 + `public` schema에 0 테이블 검증 (Alembic autogenerate drift 회귀 가드).
- **Coverage** — 신규 모듈 91-100% (state.py 100%, edges.py 100%, pipeline.py 100%, deps.py 100%, nodes/* 95-100%, checkpointer.py 91%, _wrapper.py 92%, analysis_service.py 100%). 전체 86.02% (NFR-M1 70% threshold 충족).
- **mypy strict 0 errors** — 66 source files clean. `psycopg.*` / `psycopg_pool.*` mypy.overrides 추가 (공식 stub 미완성).
- **Tasks 1-11 완료** — Task 12 (CR 진입 준비)는 별 단계.

### File List

**신규 (앱 코드)**
- `api/app/graph/__init__.py`
- `api/app/graph/state.py`
- `api/app/graph/checkpointer.py`
- `api/app/graph/edges.py`
- `api/app/graph/pipeline.py`
- `api/app/graph/deps.py`
- `api/app/graph/nodes/__init__.py`
- `api/app/graph/nodes/_wrapper.py`
- `api/app/graph/nodes/parse_meal.py`
- `api/app/graph/nodes/retrieve_nutrition.py`
- `api/app/graph/nodes/evaluate_retrieval_quality.py`
- `api/app/graph/nodes/rewrite_query.py`
- `api/app/graph/nodes/fetch_user_profile.py`
- `api/app/graph/nodes/evaluate_fit.py`
- `api/app/graph/nodes/generate_feedback.py`
- `api/app/services/__init__.py`
- `api/app/services/analysis_service.py`

**갱신 (앱 코드)**
- `api/app/core/exceptions.py` — `AnalysisGraphError` base + 4 서브클래스 추가
- `api/app/core/config.py` — `self_rag_confidence_threshold` + `langgraph_debug` 필드 추가
- `api/app/main.py` — lifespan에 LangGraph 4 자원 init + dispose hook 추가
- `api/pyproject.toml` — `psycopg[binary,pool]>=3.2` 직접 의존 + `langgraph-checkpoint-postgres>=3.0` 강화 + `markers = ["perf: ..."]` + `mypy.overrides`에 psycopg 추가
- `api/uv.lock` — `psycopg-binary` 3.3.3 신규 wheel 추가
- `.env.example` — `SELF_RAG_CONFIDENCE_THRESHOLD` / `LANGGRAPH_DEBUG` 주석 추가

**신규 (테스트)**
- `api/tests/graph/__init__.py`
- `api/tests/graph/conftest.py`
- `api/tests/graph/test_state.py`
- `api/tests/graph/test_checkpointer.py`
- `api/tests/graph/test_edges.py`
- `api/tests/graph/test_pipeline.py`
- `api/tests/graph/test_self_rag.py`
- `api/tests/graph/test_node_resilience.py`
- `api/tests/graph/test_pipeline_perf.py`
- `api/tests/graph/nodes/__init__.py`
- `api/tests/graph/nodes/test_parse_meal.py`
- `api/tests/graph/nodes/test_retrieve_nutrition.py`
- `api/tests/graph/nodes/test_evaluate_retrieval_quality.py`
- `api/tests/graph/nodes/test_rewrite_query.py`
- `api/tests/graph/nodes/test_fetch_user_profile.py`
- `api/tests/graph/nodes/test_evaluate_fit.py`
- `api/tests/graph/nodes/test_generate_feedback.py`
- `api/tests/services/__init__.py`
- `api/tests/services/test_analysis_service.py`
- `api/tests/test_exceptions_analysis.py`
- `api/tests/test_pyproject_psycopg.py`
- `api/tests/test_main_lifespan.py`

**갱신 (테스트)**
- `api/tests/conftest.py` — Windows ProactorEventLoop → SelectorEventLoop policy fix (psycopg async 호환)

**갱신 (BMad artifacts)**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — 3-3 status: ready-for-dev → in-progress → review + last_updated

### Change Log

- **2026-05-01 → 2026-05-02 (DS)** — Story 3.3 implementation 완료. 397 passed / 5 skipped(perf) / 0 failed. ruff/format/mypy strict 0 errors. coverage 86%. branch `feat/story-3.3` commit + push 준비.
- **2026-05-02 (CR)** — 3-layer adversarial review 완료. 18 patches 적용 + 1 decision(option A: `route_after_node_error` wire) + 11 defer(DF89-DF99 → deferred-work.md) + 7 dismiss. 주요 패치: Self-RAG 무한 루프 회귀 가드(`evaluate_retrieval_quality`가 `node_errors` 내 rewrite_query 실패 카운트로 1회 한도 강제), `evaluation_decision`을 `.model_dump()` dict 저장(AC3 정합), `fetch_user_profile` soft-delete 필터(PII 누설 차단), lifespan generic Exception graceful catch(D10 정합), `_ensure_schema` autocommit + `psycopg.sql.Identifier`(SQL injection 방어), `retrieve_nutrition` low_confidence sentinel(`__test_low_confidence__`)로 prod 안전, `compile_pipeline` `deps.settings` 사용 + `LANGGRAPH_DEBUG` env-gated(PII 누설 차단), `route_after_evaluate` unknown route warn + dict 양 형태 수용, `dispose_checkpointer` exc_info + `pool.closed` guard, `_to_psycopg_dsn` ValueError → AnalysisCheckpointerError, `aget_state` None snapshot graceful, AC11 graceful-failure 테스트 2건 추가, `_RETRY_TYPES` httpx 좁힘(TimeoutException/ConnectError/ReadError/RemoteProtocolError), lifespan compile_pipeline/AnalysisService import top-level 이동(silent ImportError 차단), AC1 spec에 `evaluation_decision` 명시, `Citation` 빈 리스트 명시 테스트. **DECISION_A**: `route_after_node_error`를 `fetch_user_profile` 후 wire(`add_conditional_edges → END/evaluate_fit`)로 치명적 케이스 종료 강제 → user_not_found 시 후속 노드 미진행. 회귀 테스트 갱신: `test_pipeline_user_not_found_terminates_at_fetch_user_profile`. 신규 테스트 +7 (graceful lifespan 2 / Citation empty 1 / node_errors counting 1 / unknown route 1 / Pydantic instance defensive 1 / rewrite_query persistent failure 1). 404 passed / 5 skipped(perf) / 0 failed / coverage 86.28% / mypy strict 0 errors / ruff clean. Status: review → done.

### Review Findings

CR 실시: 2026-05-02 — Amelia (claude-opus-4-7[1m]) — 3-layer adversarial review (Blind Hunter / Edge Case Hunter / Acceptance Auditor).

집계: raw 67 findings → dedup 후 30 unique → triage 결과 **PATCH 18 / DECISION 1 / DEFER 11 / DISMISS 7**.

#### Decision-needed (1)

- [x] [Review][Decision] (resolved → option A: 본 스토리에서 wire 적용) `route_after_node_error` 정의만 박고 pipeline 미배선 — 본 스토리에서 wire할지 Story 3.7로 미룰지 — `api/app/graph/edges.py:967-979` + `api/app/graph/pipeline.py`. Debug Log 항목은 Story 3.7로 미룬다고 명시(SSE 분기 정합)하지만 spec AC4 line 90은 라우터 동작을 prescriptive하게 기술. 결과적으로 `fetch_user_profile.user_not_found` "치명적 케이스 → END" 경로가 enforce되지 않고 stub `evaluate_fit/generate_feedback`이 user_profile 없이 진행됨. 현재 테스트(`test_lifespan_dispatch_to_analysis_service`, `test_pipeline_user_not_found_continues_with_node_error`)가 이 동작을 contract로 enshrine.

#### Patch (18)

- [x] [Review][Patch] Self-RAG 무한 루프 — `rewrite_query` 재시도 후 fallback 진입 시 `rewrite_attempts` increment 누락 [api\app\graph\nodes\_wrapper.py:108-110 + evaluate_retrieval_quality.py] — wrapper의 NodeError 분기는 `{"node_errors": [...]}`만 반환해 `rewrite_query`가 transient로 2회 실패하면 `rewrite_attempts == 0` 그대로. 이후 `evaluate_retrieval_quality`가 다시 `"rewrite"` route 반환 → 무한 루프(또는 LangGraph recursion limit). fix: `evaluate_retrieval_quality`가 `state["node_errors"]` 내 `node_name == "rewrite_query"` 횟수를 attempts에 합산.
- [x] [Review][Patch] `evaluate_retrieval_quality`가 Pydantic instance 그대로 state에 저장 (AC3 spec violation) [api\app\graph\nodes\evaluate_retrieval_quality.py:46] — AC3 spec line 74-75는 `.model_dump()` 명시. checkpoint 직렬화 round-trip 시 dict로 deserialize 가능 → `route_after_evaluate`의 `decision.route` AttributeError 위험. fix: `EvaluationDecision(...).model_dump()` 반환 + `route_after_evaluate`는 `decision.get("route")` 사용.
- [x] [Review][Patch] lifespan이 `setup()`의 generic Exception 미캐치 (D10 graceful 위반) [api\app\main.py:113-137] — 현 `except AnalysisCheckpointerError`만. `lg_checkpoints` schema 잔존 + 다른 shape의 `checkpoints` 테이블 / `psycopg.errors.ProgrammingError` / `RuntimeError` 시 앱 부팅 실패. fix: `except (AnalysisCheckpointerError, Exception)` 광역 catch + warning log.
- [x] [Review][Patch] `fetch_user_profile`이 soft-deleted user PII 누설 [api\app\graph\nodes\fetch_user_profile.py:37-42] — `users.deleted_at IS NOT NULL`인 사용자도 snapshot 빌드 → 삭제된 사용자의 allergies/age/weight 노출. fix: `select(User).where(User.id == user_id, User.deleted_at.is_(None))` 추가.
- [x] [Review][Patch] `_ensure_schema` 임시 connection autocommit 미설정 [api\app\graph\checkpointer.py:65-70] — 풀 외 단일 connection으로 `CREATE SCHEMA IF NOT EXISTS` 실행 시 implicit transaction 진입 → `commit()` 전 실패 시 broken-state rollback. fix: `await conn.set_autocommit(True)` 또는 `psycopg.AsyncConnection.connect(dsn, autocommit=True)`.
- [x] [Review][Patch] `retrieve_nutrition` `"low_confidence"` magic substring이 prod 경로에서 동작 [api\app\graph\nodes\retrieve_nutrition.py:34] — 사용자가 `raw_text="low_confidence_food"`/유사 입력 시 prod에서도 Self-RAG 우회 발동. fix: 정확 매칭 sentinel `"__test_low_confidence__"` 또는 `settings.environment in {"test","ci"}` 게이트.
- [x] [Review][Patch] `compile_pipeline`이 module-level `settings` 직접 import (deps.settings 무시) [api\app\graph\pipeline.py:90 — settings.langgraph_debug] — `deps`로 settings 주입 받지만 `compile()`은 글로벌 import 사용 → 테스트 fake settings isolation 불가 + D8 의존성 주입 패턴 일관성 위반. fix: `deps.settings.langgraph_debug`.
- [x] [Review][Patch] `route_after_evaluate`가 unknown route literal silent fallback [api\app\graph\edges.py:30-32] — 알 수 없는 `route` 값(`"abort"`, 누락 등) 시 `"continue"` 분기로 silent → 디버깅 어려움. fix: `route not in {"rewrite", "continue"}` 시 `log.warning("route.unknown", route=route)`.
- [x] [Review][Patch] `dispose_checkpointer` `exc_info=False` + 이중 close 시 spurious warn [api\app\graph\checkpointer.py:115-120] — traceback 미기록 + `pool.closed`인 경우에도 close 시도하여 실패 warn 로그 발생. fix: `if pool.closed: return` 가드 + `log.warning(..., exc_info=True)`.
- [x] [Review][Patch] Sentry span keyword `name=` (Sentry SDK 2.x deprecation 대응) — 테스트 docstring + spec naming line 315 `description=` 잔존 [api\tests\graph\test_node_resilience.py:2668 + 본 spec line 315] — 코드는 정당(Debug Log line 545 documented), 테스트 docstring/spec naming은 outdated. fix: 테스트 docstring 갱신 + spec naming 라인에 `name=` 비고 추가.
- [x] [Review][Patch] `_to_psycopg_dsn`의 `ValueError`가 lifespan에서 미캐치 [api\app\graph\checkpointer.py:51-56 + main.py] — `mysql://` 같은 misconfig URL → `ValueError` 직접 propagate → 앱 부팅 hard crash. fix: `build_checkpointer` 내부 try/except에서 `AnalysisCheckpointerError`로 wrap.
- [x] [Review][Patch] `LANGGRAPH_DEBUG=1` 시 raw_text/allergies PII 표준출력 누설 [api\app\graph\pipeline.py:90] — LangGraph debug 모드는 노드 state print → `raw_text` + `user_profile.allergies` 콘솔 노출. fix: `debug=settings.langgraph_debug and settings.environment in {"dev","test"}` 게이트 + 주석.
- [x] [Review][Patch] `analysis_service.aget_state`가 None snapshot 미가드 [api\app\services\analysis_service.py:74-76] — 알 수 없는 `thread_id`에서 `snapshot is None` 가능 → `snapshot.values` AttributeError. fix: `snapshot.values if snapshot else cast(MealAnalysisState, {})`.
- [x] [Review][Patch] AC11 graceful-failure lifespan 테스트 누락 [api\tests\test_main_lifespan.py] — spec AC11 line 174는 *DB 미가동 mock + `app.state.graph is None` + 앱 동작 유지* 명시. 현재는 success path만 검증. fix: `test_lifespan_graceful_when_checkpointer_init_fails` 추가.
- [x] [Review][Patch] `_RETRY_TYPES`의 `httpx.HTTPError`가 너무 광범위 [api\app\graph\nodes\_wrapper.py:1062] — 4xx/5xx response error도 retry → 401/403도 1회 재시도(토큰 낭비). fix: `httpx.TimeoutException`, `httpx.ConnectError`, `httpx.ReadError`, `httpx.RemoteProtocolError`로 좁힘.
- [x] [Review][Patch] `analysis_service.run`의 `cast(MealAnalysisState, final_state)` 실효성 0 [api\app\services\analysis_service.py:1831] — `graph.ainvoke()`는 `dict[str, Any]` 반환 — `cast`는 mypy 거짓말이며 런타임 보호 없음. fix: 반환 타입을 `MealAnalysisState`(TypedDict는 dict와 호환) 그대로 둠 — `cast` 제거.
- [x] [Review][Patch] AC1 spec — `MealAnalysisState`에 `evaluation_decision` 필드 누락 [본 spec lines 23-35] — 실 코드 `state.py`는 추가했으나 spec 14번째 필드 항목 없음. fix: AC1 필드 목록에 `evaluation_decision: EvaluationDecision | None` 추가 + `evaluate_retrieval_quality` 노드의 공식 출력으로 명시.
- [x] [Review][Patch] AC1 — Citation 빈 리스트 명시 테스트 누락 [api\tests\graph\test_state.py] — spec AC1 line 46이 명시. 현재는 `test_feedback_output_default_used_llm`에서 `citations=[]` 인자로 implicit cover. fix: `test_citation_empty_list_allowed_in_feedback_output` 명시 추가.

#### Defer (11)

- [x] [Review][Defer] `aresume`의 진짜 LangGraph resume semantics — `ainvoke(user_input)`은 START부터 재실행 → Story 3.4 책임 (spec line 125-126이 *인터페이스 박기만* 명시).
- [x] [Review][Defer] `parse_meal` `raw[:50]` 그래프임 클러스터/이모지 mid-codepoint cut — Story 3.4 실 LLM parse가 stub 대체 시 자연 해소.
- [x] [Review][Defer] `evaluate_retrieval_quality` 결정성 노드 retry 의미 0 — Story 3.6 실 LLM/RAG 진입 시점에 retry 정책 재평가.
- [x] [Review][Defer] `fetch_user_profile.health_goal` Literal 강제 변환 누락 (DB enum drift 방어) — Story 5.x 회원 프로필 수정 시점.
- [x] [Review][Defer] `AsyncConnectionPool` `max_size=4` 하드코딩 — Story 8 운영 hardening + 실 부하 측정 후 Settings 노출.
- [x] [Review][Defer] `WindowsSelectorEventLoopPolicy`를 conftest 글로벌 스코프 — Story 8 hardening (subprocess 테스트 도입 시).
- [x] [Review][Defer] `--cov-fail-under=70`을 신규 패키지에 80% per-module로 강화 — Story 8 polish (CI 게이트 일괄).
- [x] [Review][Defer] `psycopg-pool>=3.3` 명시 핀 — `psycopg[pool]` extra가 transitive로 락하여 현재 안전. Story 8 polish 시 lockfile 정리.
- [x] [Review][Defer] async fixture가 `app.state.session_maker` 공유 → pytest-xdist 병렬 시 cross-test thread_id corruption — Story 8 polish (CI 병렬화 도입 시).
- [x] [Review][Defer] `_to_psycopg_dsn`이 `?driver=` query param 미스트립 — Story 8 polish (현 codebase는 SQLAlchemy DATABASE_URL convention만 사용).
- [x] [Review][Defer] `aresume`에 `user_input.rewrite_attempts=99` 같은 managed-field 주입 가능 — Story 3.4가 실 user_input shape를 정의할 때 sanitize.

#### Dismiss (7) — 노이즈/검증 실패

- ❌ Blind: TypedDict 필드 런타임 검증 부재 — D7 결정으로 by-design (TypedDict는 type hint, Pydantic이 1차 게이트).
- ❌ Blind: `_to_psycopg_dsn`이 userinfo 특수문자(`@`, `+`) 미URL-decode — psycopg.conninfo가 별 layer에서 처리, 현 SQLAlchemy URL 컨벤션 정합.
- ❌ Blind: `_node_wrapper.attempts=1` 매직 상수 — 현 코드 path에서 정확(AnalysisNodeError는 retry 제외).
- ❌ Blind: lifespan 부분 init 시 pool leak — `finally` 블록의 `getattr(..., None)` + dispose 호출이 부분 init 처리.
- ❌ Edge: `_to_psycopg_dsn`의 `+psycopg2` 처리 — 이미 `startswith("postgresql+")` + `startswith("postgres+")`로 처리됨.
- ❌ Edge: `_to_psycopg_dsn`의 short scheme `postgres://` normalization — 방어적이고 무해(psycopg 문서가 양쪽 허용).
- ❌ Edge: `aresume`의 Sentry transaction 예외 시 미닫음 — 실제로는 context manager `__exit__`가 닫음, 잘못된 finding.
