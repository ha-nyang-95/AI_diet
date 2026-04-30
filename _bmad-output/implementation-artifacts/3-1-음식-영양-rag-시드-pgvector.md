# Story 3.1: 음식 영양 RAG 시드 + food_aliases 정규화 사전 + pgvector HNSW

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **1인 개발자(시드 작업) / 외주 인수 클라이언트(시드 표준 활용)**,
I want **식약처 식품영양성분 DB OpenAPI 기반 1,500-3,000건 한식 우선 음식 영양 데이터를 시드하고 정규화 사전(food_aliases ≥ 50건)을 구성하기를**,
So that **LangGraph `retrieve_nutrition` 노드(Story 3.3)가 식약처 표준 키 jsonb + HNSW 임베딩 검색으로 한국식 음식명 변형(짜장면/자장면)을 통합 매칭할 수 있고, 외주 클라이언트는 같은 jsonb 키 표준으로 자사 SKU를 변환 코스트 0으로 시드 추가할 수 있다.**

본 스토리는 Epic 3(AI 영양 분석 — Self-RAG + 인용 피드백)의 *데이터 기반 베이스라인*을 박는다 — **(a) `food_nutrition` 테이블 신규 — 식약처 OpenAPI 응답 키 그대로(`energy_kcal`/`carbohydrate_g`/`protein_g`/`fat_g`/`saturated_fat_g`/`sugar_g`/`fiber_g`/`sodium_mg`/`cholesterol_mg`/`serving_size_g`/`serving_unit`/`source`/`source_id`/`source_updated`) jsonb + `embedding vector(1536)` HNSW 인덱스(vector_cosine_ops, m=16, ef_construction=64) — Story 3.3 retrieve_nutrition 노드의 1차 검색 인덱스**, **(b) `food_aliases` 테이블 신규 — `(alias text NOT NULL, canonical_name text NOT NULL)` + `UNIQUE(alias)` 제약 — 짜장면/자장면, 김치찌개/김치 찌개, 떡볶이/떡뽁이 등 핵심 변형 ≥ 50건 시드 (Story 3.4 normalize.py 1차 lookup 입력)**, **(c) `app/adapters/mfds_openapi.py` 신규 — 식품영양성분 DB OpenAPI(공공데이터포털 15127578) httpx 어댑터 + tenacity 1회 retry + 페이지네이션(`pIndex`/`pSize`) + `MFDS_OPENAPI_KEY` env 미설정 시 503 fail-fast + 한식 우선 필터(품목분류 — 한식/중식/양식 등 카테고리 코드 화이트리스트) + 응답 키 → 식약처 표준 키 매핑 함수**, **(d) `app/adapters/openai_adapter.py` 확장 — `embed_texts(texts: list[str]) -> list[list[float]]` 신규 함수 — `text-embedding-3-small` 모델(1536 dim, $0.02/1M 토큰) + 100건 batch + tenacity 1회 retry + 503 변환 — Vision OCR `_call_vision`과 SDK singleton 공유(P1 정합)**, **(e) `scripts/seed_food_db.py` 신규 — entry point — (1) `mfds_openapi.fetch_food_items()` 1차 시도 → (2) 응답 부족(< 1,500건) 또는 OpenAPI 장애(503) 시 `data/mfds_food_nutrition_seed.csv` 정적 백업 ZIP fallback 시도(통합 자료집 다운로드 미리 commit) → (3) 두 경로 모두 실패 시 비-zero exit + Sentry capture (NFR-I1, R7) — 시드 멱등(`ON CONFLICT (source, source_id) DO UPDATE SET nutrition = EXCLUDED.nutrition, embedding = EXCLUDED.embedding, source_updated = EXCLUDED.source_updated, updated_at = now()`) — 재실행 안전**, **(f) `app/rag/food/seed.py` 신규 — 시드 비즈니스 로직 (어댑터 응답 → ORM 매핑 + 임베딩 호출 + bulk INSERT 멱등) — 1,500-3,000건을 100건 batch로 처리, 임베딩 텍스트 = `f"{name} ({category})"` (검색 정확도 ↑ — 동일명 카테고리 분리)**, **(g) `app/rag/food/aliases_data.py` 신규 — 50+ 핵심 변형 모듈 const dict — 짜장면/자장면, 김치찌개/김치 찌개, 떡볶이/떡뽁이, 비빔밥/비빔/돌솥비빔밥, 갈비탕/갈비, 순두부찌개/순두부, 잡채/당면 잡채, 라면/인스턴트 라면, 군만두/만두, 김밥/마끼, 떡국/가래떡, 짬뽕/짬봉, 우동/우롱, 부대찌개/부대 찌개, 곱창/내장, 삼겹살/돼지 삼겹, 회/사시미, 초밥/스시, 냉면/냉면 사발, 미역국/해초국 등** — `seed_aliases.py` 또는 동일 entry에서 `INSERT ... ON CONFLICT (alias) DO UPDATE SET canonical_name = EXCLUDED.canonical_name` 멱등 + 시드 후 `SELECT count(*) FROM food_aliases >= 50` 게이트, **(h) `scripts/bootstrap_seed.py` 갱신 — `seed_food_db.main()` 호출 + `food_aliases` 시드 호출 + 두 시드 실패는 비-zero exit로 컨테이너에 신호(현 placeholder no-op 폐기)**, **(i) Docker Compose `seed` 서비스 자동 시드 — 현 `command: ["uv", "run", "python", "/app/scripts/bootstrap_seed.py"]` + `depends_on: api(service_healthy)` 그대로 활용(`docker compose up`만으로 자동 시드 — FR47/AC5 정합)**, **(j) `app/db/models/food_nutrition.py` + `app/db/models/food_alias.py` 신규 ORM — `embedding` 컬럼은 `pgvector.sqlalchemy.Vector(1536)` 매핑 + `nutrition` JSONB + `__table_args__`에 HNSW 인덱스 등재(SQLAlchemy + Alembic은 raw `op.create_index(..., postgresql_using='hnsw', postgresql_with={...}, postgresql_ops={...})`로 마이그레이션 책임 — ORM `Index` 객체는 SOT만)**, **(k) 신규 도메인 예외 — `FoodSeedAdapterError(503)` / `FoodSeedSourceUnavailableError(503)` / `FoodSeedQuotaExceededError(503)` — `app/core/exceptions.py` 등재 + RFC 7807 표준 정합 (라우터 노출은 Story 3.3+ — 본 스토리는 정의만)**, **(l) Epic 3 진입 baseline — Story 3.1 종료 후 Story 3.2(가이드라인 RAG 시드 + chunking 모듈) 진입 가능 — `food_nutrition` + `food_aliases` 두 SOT가 박혀 retrieve_nutrition 노드(Story 3.3)의 1차 검색 인프라 충족**의 데이터·인프라 baseline을 박는다.

부수적으로 (a) **LangGraph `retrieve_nutrition` 노드 통합은 OUT** — 본 스토리는 *데이터 시드 + 인덱스*만, 노드 내부 검색 흐름(`select` 쿼리 + Self-RAG `evaluate_retrieval_quality` 분기)은 Story 3.3 책임, (b) **`food_aliases` runtime 갱신 API는 OUT** — 본 스토리는 *시드 시점* 50+ 변형만, 외주 클라이언트가 자기 메뉴 별칭 추가하는 admin 라우터(POST/DELETE)는 Story 7.x(관리자 + Audit Trust) 책임 — architecture line 292 *"runtime 갱신"*은 *DB 직접 INSERT*로 충족(추후 admin UI는 별 스토리), (c) **`knowledge_chunks` 테이블 + 가이드라인 RAG 시드는 OUT** — Story 3.2 책임(KDRIs/대비/대당/식약처 광고 가드 PDF chunking + applicable_health_goals 메타데이터), (d) **Self-RAG `rewrite_query` / `evaluate_retrieval_quality` 노드는 OUT** — Story 3.3 책임, (e) **fit_score / `evaluate_fit` 노드는 OUT** — Story 3.5 책임, (f) **음식명 normalize.py(`food_aliases` 1차 lookup + 임베딩 fallback) 검색 흐름은 OUT** — Story 3.4 책임 (본 스토리는 *데이터 시드*만, 검색 코드 X), (g) **USDA FoodData Central fallback은 OUT** — 한식 매칭 부족 + 8주 일정 정합으로 *식약처 OpenAPI + ZIP 백업 2단*만 채택, USDA는 Growth 시점 도입 검토(D1 결정), (h) **분기 1회 수동 갱신 SOP는 OUT** — 본 스토리는 *최초 시드*만, 분기 갱신 SOP 문서는 Story 8(인수인계 패키지) 책임, (i) **`food_nutrition` 행/임베딩 versioning(다중 버전 보존)은 OUT** — `source_updated` 타임스탬프 1개 + 멱등 UPDATE 패턴만, 변경 이력 보존은 Story 8 polish, (j) **임베딩 모델 변경 마이그레이션은 OUT** — 본 스토리는 `text-embedding-3-small` (1536 dim) 단일, 모델 업그레이드(예: 3-large 3072 dim) 시 컬럼 타입 변경 + 재 시드는 Growth deferred(`vector(1536)` 고정).

## Acceptance Criteria

> **BDD 형식 — 각 AC는 독립적 검증 가능. 모든 AC 통과 후 `Status: review`로 전환하고 code-review 워크플로우로 진입.**

1. **AC1 — `alembic 0010` 마이그레이션 — `food_nutrition` + `food_aliases` 테이블 + HNSW 인덱스 + ORM 등록**
   **Given** Story 2.5 baseline `meals` 테이블 + Epic 3 진입, **When** `cd api && uv run alembic upgrade head` 실행, **Then**:
     - **신규 테이블 `food_nutrition`** — 컬럼:
       - `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`,
       - `name TEXT NOT NULL` (한국어 표준 음식명, 예: `"짜장면"`),
       - `category TEXT NULL` (식약처 품목분류 — 한식/중식/양식/일식/양식/디저트 등 — 임베딩 텍스트 분리용),
       - `nutrition JSONB NOT NULL` (식약처 OpenAPI 응답 키 그대로 — `energy_kcal`/`carbohydrate_g`/`protein_g`/`fat_g`/`saturated_fat_g`/`sugar_g`/`fiber_g`/`sodium_mg`/`cholesterol_mg`/`serving_size_g`/`serving_unit`/`source`/`source_id`/`source_updated` 키 모두 포함 — 키 추가는 jsonb 무중단),
       - `embedding vector(1536) NULL` (text-embedding-3-small — NULL 허용 for partial seed graceful — 검색 시 NULL 행 자동 제외),
       - `source TEXT NOT NULL` (`MFDS_FCDB` / `MFDS_ZIP` / `CUSTOM` — 시드 출처 식별),
       - `source_id TEXT NOT NULL` (식약처 식품코드 — 예: `"K-115001"` / ZIP 케이스는 `MFDS-ZIP-{seq}`),
       - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` / `updated_at TIMESTAMPTZ NOT NULL DEFAULT now() ON UPDATE now()`,
     - **`food_nutrition` UNIQUE 제약** — `UNIQUE(source, source_id)` (멱등 시드 입력 — 재실행 시 같은 source+source_id row 충돌 → ON CONFLICT UPDATE 분기). naming: `uq_food_nutrition_source_source_id` (Story 1.2 W9 정합 patterns — autogenerate `uq_*` 허용).
     - **`food_nutrition` HNSW 인덱스** — `idx_food_nutrition_embedding` (architecture line 395 명시) — `USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)`. **NULL embedding은 인덱싱 X** (pgvector 0.8.2 기본 — partial-index 명시 X 시 자동 제외).
     - **신규 테이블 `food_aliases`** — 컬럼:
       - `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`,
       - `alias TEXT NOT NULL` (변형 음식명 — 예: `"자장면"`),
       - `canonical_name TEXT NOT NULL` (정규화 표준 음식명 — 예: `"짜장면"` — `food_nutrition.name`과 join 매칭 입력),
       - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` / `updated_at TIMESTAMPTZ NOT NULL DEFAULT now() ON UPDATE now()`.
     - **`food_aliases` UNIQUE 제약** — `UNIQUE(alias)` (epic AC line 594 *"unique 제약"* 명시 — 같은 alias 중복 시드 차단). naming: `uq_food_aliases_alias`.
     - **인덱스** — `food_aliases.alias` UNIQUE는 자동 b-tree 인덱스 (정규화 lookup 1차 입력 — Story 3.4). `canonical_name`은 별 인덱스 X (forward join 키만 — Story 3.4 시점에 검토).
     - **ORM 신규** — `app/db/models/food_nutrition.py` + `app/db/models/food_alias.py` — declarative 등록 + `app/db/models/__init__.py`에 export 추가. `embedding` 컬럼은 `from pgvector.sqlalchemy import Vector` import + `Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)`. `nutrition` 컬럼은 `Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)`.
     - **마이그레이션 파일 신규** — `api/alembic/versions/0010_food_nutrition_and_aliases.py` — `down_revision: str | None = "0009_meals_idempotency_key"`. `upgrade`에서 `op.create_table(...)` 두 건 + `op.create_unique_constraint(...)` 두 건 + `op.create_index('idx_food_nutrition_embedding', 'food_nutrition', ['embedding'], postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})`. `downgrade`에서 `op.drop_index` + `op.drop_constraint` + `op.drop_table` 순(역순). `vector` extension은 `docker/postgres-init/01-pgvector.sql`에서 이미 설치(no-op 보장).
     - **`pgvector>=0.3` 의존성** — `api/pyproject.toml` 이미 등재(0.4.2 venv 확인). 추가 설치 X.
     - **CHECK 제약 X** — `nutrition` jsonb 키 검증 / `embedding` 차원(1536) 검증은 application-level Pydantic + 시드 함수 책임, DB CHECK는 마이그레이션 마찰 회피 (Story 8 hardening 시점에 검토).
     - **응답 wire 변경 X** — 본 스토리는 *내부 인프라*만, 라우터 응답 노출은 Story 3.3+ 책임.
     - **테스트** — `api/tests/test_food_nutrition_aliases_schema.py` 신규 — alembic 0010 round-trip(`upgrade head` → `downgrade 0009_meals_idempotency_key` → `upgrade head`) 정상 + 두 테이블 + UNIQUE 제약 + HNSW 인덱스 존재 검증(`SELECT indexname FROM pg_indexes WHERE tablename = 'food_nutrition' AND indexname = 'idx_food_nutrition_embedding'`).

2. **AC2 — `app/adapters/mfds_openapi.py` 신규 — 식품영양성분 DB OpenAPI httpx 어댑터**
   **Given** 식약처 식품영양성분 DB OpenAPI(공공데이터포털 데이터셋 ID 15127578 — base URL `https://api.odcloud.kr/api/15127578/v1/uddi:` 또는 `https://api.data.go.kr/openapi/tn_pubr_public_nutri_food_info_api`) + `MFDS_OPENAPI_KEY` env, **When** `fetch_food_items(target_count: int = 1500, *, page_size: int = 100) -> list[FoodNutritionRaw]` 호출, **Then**:
     - **httpx async 클라이언트** — `httpx.AsyncClient(timeout=30.0)` lazy singleton + `threading.Lock` double-checked locking (`r2.py` / `openai_adapter.py` P1 정합).
     - **API key 환경변수** — `settings.mfds_openapi_key` truthy 확인 — 미설정 시 `FoodSeedSourceUnavailableError("MFDS OpenAPI key not configured (MFDS_OPENAPI_KEY missing)")` 즉시 raise (cost 0 / fail-fast).
     - **Pagination** — 공공데이터포털 표준 — `serviceKey` + `pageNo` + `numOfRows`(또는 신 표준 `page` + `perPage`) 쿼리 파라미터. 어댑터 모듈 const에 박음:
       ```python
       MFDS_API_BASE_URL: Final[str] = "https://api.odcloud.kr/api/15127578/v1/uddi:..."  # DS 시점 공공데이터포털 데이터셋 페이지에서 정확한 URL 확인 의무
       MFDS_PAGE_KEY: Final[str] = "page"           # 신 표준 (구 표준은 "pageNo")
       MFDS_SIZE_KEY: Final[str] = "perPage"        # 신 표준 (구 표준은 "numOfRows")
       MFDS_AUTH_KEY: Final[str] = "serviceKey"     # 공공데이터포털 인증 키 파라미터
       MFDS_DEFAULT_PAGE_SIZE: Final[int] = 100     # 한 페이지당 항목 수
       ```
       한 페이지 100건 + 한식 우선 카테고리 필터 적용 후 `target_count` 도달까지 순차 fetch. **DS 의무**: 실제 endpoint URL + 파라미터 키는 `https://www.data.go.kr/data/15127578/openapi.do` 페이지에서 OpenAPI 문서 확인 후 모듈 const 값을 *최종 확정*하고 docstring에 *"확인일자 2026-XX-XX"* 명시 — 공공데이터포털은 신/구 표준 혼재 + 데이터셋별 endpoint 변동 위험 (DS 시점 검증 안 하면 401/404로 시드 fail).
     - **응답 키 정규화** — `FoodNutritionRaw` Pydantic 모델로 dict → 식약처 표준 키(`name`/`category`/`energy_kcal`/`carbohydrate_g`/`protein_g`/`fat_g`/`saturated_fat_g`/`sugar_g`/`fiber_g`/`sodium_mg`/`cholesterol_mg`/`serving_size_g`/`serving_unit`/`source_id`) 매핑 함수 (`_raw_to_standard(item: dict) -> FoodNutritionRaw`). **응답 원본 키 추정 매핑** (DS 시점 OpenAPI 문서로 검증 의무):
       ```python
       MFDS_RAW_KEY_MAP: Final[dict[str, str]] = {
           "FOOD_NM_KR": "name",            # 한국어 식품명 (예: "짜장면")
           "FOOD_GROUP_NM": "category",     # 품목분류 (예: "면류")
           "AMT_NUM1": "energy_kcal",       # 에너지 (kcal)
           "AMT_NUM3": "carbohydrate_g",    # 탄수화물 (g)
           "AMT_NUM4": "protein_g",         # 단백질 (g)
           "AMT_NUM5": "fat_g",             # 지방 (g)
           "AMT_NUM6": "sugar_g",           # 당류 (g)
           "AMT_NUM7": "fiber_g",           # 식이섬유 (g)
           "AMT_NUM8": "sodium_mg",         # 나트륨 (mg)
           "AMT_NUM9": "cholesterol_mg",    # 콜레스테롤 (mg)
           "AMT_NUM21": "saturated_fat_g",  # 포화지방산 (g)
           "SERVING_SIZE": "serving_size_g",# 1회 제공량 (g)
           "FOOD_CD": "source_id",          # 식품코드 (예: "K-115001")
       }
       ```
       원본 키(`AMT_NUM1` 등)는 식약처 OpenAPI 변동 위험으로 어댑터 내부에 격리. 하부 시드 코드는 *식약처 표준 키*만 사용. **DS 의무**: 위 매핑은 *추정값* — 데이터셋 15127578 OpenAPI 문서 또는 샘플 응답으로 *최종 키 명 확정*. 누락 키(예: `cholesterol_mg`)는 jsonb 키 omission으로 graceful 처리.
     - **타입 변환** — 식약처 OpenAPI는 영양 수치를 *문자열 또는 숫자*로 혼용 가능 — `float()` 명시 변환 + `ValueError` catch 후 `None` fallback (개별 항목 — 결측치는 jsonb에서 키 누락 또는 null로 보존). `serving_size_g`는 식약처 OpenAPI에서 양 단위 혼용(`g`/`mL`/`인분`) — 단위는 `serving_unit` 별 컬럼으로 분리.
     - **한식 우선 필터** — 식약처 OpenAPI는 *품목분류* 필드(`FOOD_GROUP_NM` 또는 `FOOD_GROUP_CD`) 보유. 한식 카테고리 화이트리스트 어댑터 모듈 const:
       ```python
       MFDS_KOREAN_FOOD_CATEGORIES: Final[frozenset[str]] = frozenset({
           "밥류", "면류", "죽 및 스프류", "국 및 탕류", "찌개 및 전골류",
           "찜류", "구이류", "전·적 및 부침류", "볶음류", "조림류", "튀김류",
           "나물·숙채류", "김치류", "장아찌·절임류", "젓갈류", "회류",
           "떡류", "한과류", "음청류",
       })  # 식약처 식품군 분류 한식 우선 19종 — DS 시점 정확한 카테고리 명 검증 의무
       ```
       한식 카테고리 매칭 row만 1차 fetch (총 ~3K건 후보), `target_count` 도달 후 추가 카테고리 확장 X (한식 1.5K건 충족 가정). 실제 카테고리 명은 OpenAPI 응답 샘플 확인 후 final.
     - **tenacity retry** — `_TRANSIENT_RETRY_TYPES = (httpx.HTTPError, httpx.TimeoutException)` — 1회 retry + `wait_exponential(min=1, max=4)` (Story 2.3 OpenAI 어댑터 P1 정합). 영구 오류(401/403 — API key 무효, 429 — quota 초과)는 즉시 `FoodSeedAdapterError` raise — retry 무효 + cost 낭비 차단.
     - **Quota 초과 분기** — HTTP 429 또는 응답 본문에 quota error code(공공데이터포털 표준 — 응답 XML/JSON에 `resultCode != "00"` + 특정 quota 코드) 시 `FoodSeedQuotaExceededError(503)` raise — 시드 스크립트가 ZIP fallback 분기 트리거.
     - **logger.info 마스킹** — API key 노출 X (`MFDS_OPENAPI_KEY`는 `_redact()` 없이도 어댑터 logger에 절대 출력 X). 1줄 페이지 로그(`mfds.openapi.fetch_page`, `page_index=...`, `items_count=...`, `latency_ms=...`).
     - **테스트** — `api/tests/adapters/test_mfds_openapi.py` 신규 — httpx mock(`respx` 또는 `httpx.MockTransport`) 사용. 케이스: (1) 정상 응답 → 100건 매핑 검증, (2) 페이지네이션 5페이지 합산 500건, (3) API key 미설정 → `FoodSeedSourceUnavailableError` raise, (4) HTTP 429 → `FoodSeedQuotaExceededError`, (5) HTTP 500 → tenacity 1회 retry → 최종 `FoodSeedAdapterError`, (6) 응답 키 매핑 — 누락된 영양 수치는 jsonb에서 키 omission 보존.

3. **AC3 — `app/adapters/openai_adapter.py` 확장 — `embed_texts` 함수 신규**
   **Given** Story 2.3 `parse_meal_image` Vision OCR 패턴 + 본 스토리 임베딩 호출 요구, **When** `embed_texts(texts: list[str], *, batch_size: int = 300) -> list[list[float]]` 호출, **Then**:
     - **모델** — `EMBEDDING_MODEL: Final[str] = "text-embedding-3-small"` (1536 dim, $0.02/1M tokens — 3K건 × 평균 50토큰 → 150K 토큰 → ~$0.003 — 비용 0). `text-embedding-3-large`(3072 dim)는 OUT(architecture `vector(1536)` 고정 + 비용 5배).
     - **Batch 처리** — `EMBEDDING_BATCH_SIZE: Final[int] = 300` (OpenAI embeddings API 단일 요청 한계 2048건 + 입력 토큰 합산 cap 8192 — 음식명 평균 ~10 토큰 × 300건 = 3,000 토큰 안전치). 1,500건 시드 = 5 batches → latency ↓ vs 100건 batch (15 → 5 round-trip), 비용 동등. `len(texts) > batch_size` 시 자동 chunk + 결과 concat. retry cost는 batch당 ↑(300건 transient 시 재호출 비용 ↑이지만 transient 빈도 < 1%로 합리치).
     - **빈 입력 처리** — `len(texts) == 0` 시 빈 리스트 즉시 반환 (API 호출 X — cost 0).
     - **SDK singleton 공유** — `_get_client()` (Vision OCR과 동일 `AsyncOpenAI` instance — connection pool 공유). 별 client 생성 X (P1 정합).
     - **timeout** — Vision OCR은 30초 hard cap이지만 embeddings는 100건 batch에서 보통 < 5초 — 동일 30초 cap으로 통일(코드 단순성 + transient 에러 catch all).
     - **tenacity retry** — `_TRANSIENT_RETRY_TYPES`(Vision OCR과 공유) — `httpx.HTTPError`/`openai.APIConnectionError`/`openai.APITimeoutError`/`openai.RateLimitError`/`openai.InternalServerError` 1회 retry. `openai.AuthenticationError`/`openai.BadRequestError` 등 영구 오류는 즉시 `FoodSeedAdapterError(503, "OpenAI embeddings API failure")` 변환 (retry 무효).
     - **응답 차원 검증** — `response.data[i].embedding` 길이가 정확히 1536이 아닌 경우 `FoodSeedAdapterError("OpenAI embeddings: dimension mismatch (expected 1536)")` — 모델 변경 회귀 차단.
     - **logger.info 마스킹** — `texts` raw 출력 X (잠재 raw_text 포함 가능 — NFR-S5 정합). `texts_count` + `latency_ms` + `model`만 1줄.
     - **OPENAI_API_KEY 미설정 분기** — Vision OCR과 동일 — `_get_client()` 진입에서 `MealOCRUnavailableError(503)` raise — 본 스토리는 *시드 컨텍스트*에서 호출되므로 *raise 그대로 전파*하면 시드 스크립트가 비-zero exit 처리 (별 변환 X — 503 의미 동등 + 본 스토리는 신규 `FoodSeedAdapterError`로 매핑하지 않고 *Vision OCR과 같은 상위 503*로 통일).
     - **테스트** — `api/tests/adapters/test_openai_embeddings.py` 신규 — `AsyncOpenAI` monkeypatch. 케이스: (1) 300건 입력 → 단일 batch 호출 → 300×1536 응답, (2) 700건 입력 → 3 batches(300+300+100) 합산, (3) 차원 불일치(1024) → `FoodSeedAdapterError`, (4) RateLimitError → 1회 retry → 최종 503, (5) AuthenticationError → 즉시 503 (retry 무효), (6) 빈 리스트 → API 호출 0건 + 빈 리스트 응답.

4. **AC4 — `app/rag/food/seed.py` + `scripts/seed_food_db.py` — 시드 비즈니스 로직 + entry point**
   **Given** AC1~AC3 baseline + 시드 자동화 요구, **When** `cd api && uv run python /app/scripts/seed_food_db.py` 실행 (Docker `seed` 컨테이너 + 로컬 dev), **Then**:
     - **시드 우선순위 — 2단 fallback + dev graceful** (NFR-I1, R7 정합):
       1. **1차** — `mfds_openapi.fetch_food_items(target_count=1500)` 호출 → 응답 ≥ 1,500건 시 채택.
       2. **2차** — 1차가 (a) `FoodSeedSourceUnavailableError`(API key 미설정) / (b) `FoodSeedAdapterError`(503 transient 후 retry 실패) / (c) `FoodSeedQuotaExceededError` / (d) 응답 < 1,500건 (target 미달) 중 하나로 종료 시 → ZIP fallback 시도. ZIP 경로: `api/data/mfds_food_nutrition_seed.csv` (식약처 통합 자료집 다운로드 미리 commit — 본 스토리에서 *placeholder 빈 CSV + 헤더만* 생성, 실제 데이터는 운영자가 수동 갱신 SOP 따라 채움 — `data/README.md` 1단락 추가). CSV 컬럼은 식약처 표준 키 정합. 빈 placeholder 파일(헤더만)은 *2차 fallback 데이터 없음*으로 분류.
       3. **두 경로 모두 실패** — `settings.environment` 분기로 분리 처리:
          - **prod / staging**: 비-zero exit (`return 1`) + Sentry capture(`scope.set_tag("seed", "food_db_total_failure")`) + stderr stack trace + `food_aliases` 시드 skip — 운영 환경은 *cost runaway / 영업 demo 깨짐* 차단.
          - **dev / ci / test**: `food_nutrition` 0건 graceful 진행 + `food_aliases` 시드는 정상 진행 + main() returns 0 + stdout/structlog warning(`[seed_food_db] WARN — food_nutrition seed unavailable (MFDS_OPENAPI_KEY missing or ZIP empty), aliases-only mode for dev`). 이유: 외주 인수 클라이언트 *첫 git clone + docker compose up* 시점에 `MFDS_OPENAPI_KEY` 미발급 + ZIP placeholder 상태가 디폴트 — *시드 컨테이너 fail*로 영업 demo가 즉시 깨지는 UX 회피. food_aliases 50+건만 있어도 `food_nutrition` row 0건 + Story 3.4 normalize.py가 unmatched alias → 임베딩 fallback에서 *"음식 데이터 부재 — MFDS_OPENAPI_KEY 발급 후 재 시드 권장"* graceful 안내(Story 3.4 책임).
          - **graceful 분기 단언** — `settings.environment` 분기는 어댑터/seed.py 모듈 docstring + AC11 시나리오 2 명시. dev 환경에서도 `RUN_FOOD_SEED_STRICT=1` 환경 변수 설정 시 prod와 동일 fail-fast(테스트 강제 + CI 게이트 옵션).
     - **시드 멱등 — `ON CONFLICT (source, source_id) DO UPDATE`** — `INSERT INTO food_nutrition (id, name, category, nutrition, embedding, source, source_id, ...) VALUES (...) ON CONFLICT (source, source_id) DO UPDATE SET name = EXCLUDED.name, category = EXCLUDED.category, nutrition = EXCLUDED.nutrition, embedding = EXCLUDED.embedding, source_updated = EXCLUDED.source_updated, updated_at = now()`. 재실행 시 회귀 0건 + UPDATE 분기 — 시드 스크립트는 `(inserted, updated)` 카운터 logger.info 출력.
     - **임베딩 텍스트 포맷** — `_embedding_text(item: FoodNutritionRaw) -> str` — `f"{item.name} ({item.category})"` (category None 시 `f"{item.name}"`) — 동일 음식명(예: *"국수"* 한식 vs 양식)을 카테고리로 분리 → 검색 정확도 ↑.
     - **Batch 처리** — 300건 단위 — (1) 300건 fetch (어댑터, 3 페이지 합산) → (2) 300건 단일 임베딩 호출 → (3) 300건 INSERT (single transaction) → (4) commit. transaction 단위 batch 300건은 메모리(~5MB) + recovery cost 합리치(D6 결정 — 100→300 상향). 1,500건 시드 = 5 batch / 5 commit / 5 OpenAI round-trip → cold start latency 단축.
     - **DB session** — `app.db.session.async_sessionmaker` 또는 `create_async_engine` 직접 — 시드 스크립트는 *FastAPI 서버 외부 컨텍스트*이므로 `app.state` 의존 X — 별도 engine 생성 + dispose 패턴.
     - **응답 < 1,500건 + 1차 성공** — 1차에서 1,000건만 fetch된 경우 → 본 스토리 baseline은 *부족분 ZIP fallback로 보강*(target 1,500 정합). 1차 + 2차 union으로 final ≥ 1,500건 충족. 단 같은 `(source, source_id)`는 UNIQUE 제약 + `ON CONFLICT` UPDATE — 자연 dedupe.
     - **`scripts/seed_food_db.py` entry point** — `if __name__ == "__main__": sys.exit(main())` — `main()` returns int (0 success / 1 failure). main()은 `app.rag.food.seed.run_food_seed()` 호출 + 통계 stdout 출력 (`[seed_food_db] inserted={n_insert} updated={n_update} skipped={n_skip} source={primary|fallback}`).
     - **logger.info 마스킹** — 음식명/영양 raw 노출 X (NFR-S5 raw_text 마스킹 정합 — 식습관 추론 잠재) — `items_count` + `model` + `source` 1줄.
     - **테스트** — `api/tests/rag/test_food_seed.py` 신규 — `mfds_openapi.fetch_food_items` + `embed_texts` 두 어댑터 monkeypatch. 케이스: (1) 1차 1,500건 성공 → DB row 1,500건 + 임베딩 NOT NULL, (2) 1차 failure → ZIP fallback 1,000건 + 1차 0건 → DB row 1,000건, (3) 두 경로 모두 failure → main() returns 1 + DB row 0건, (4) 멱등 — 동일 (source, source_id)로 두 번째 시드 → ON CONFLICT UPDATE → DB row 동일 count + `updated_at` 갱신, (5) 응답 키 누락(예: `sodium_mg` 없음) → jsonb에서 key omission 보존(NULL 채움 X — 식약처 표준 정합), (6) 임베딩 호출 실패 → 해당 row만 NULL embedding INSERT(나머지 정상) — 부분 실패 graceful (검색 시 NULL 자동 제외).

5. **AC5 — `app/rag/food/aliases_data.py` + 시드 — 50+ 핵심 변형 정규화 사전**
   **Given** 한국식 음식명 변형(짜장면/자장면, 김치찌개/김치 찌개) 정규화 요구, **When** `seed_food_aliases()` 호출 (entry point는 `seed_food_db.py` 시드 직후 자동 호출), **Then**:
     - **모듈 const dict** — `app/rag/food/aliases_data.py` 신규 — `FOOD_ALIASES: Final[dict[str, str]] = { "자장면": "짜장면", "김치 찌개": "김치찌개", "떡뽁이": "떡볶이", "비빔": "비빔밥", "돌솥비빔밥": "비빔밥", "갈비": "갈비탕", "순두부": "순두부찌개", "당면 잡채": "잡채", "인스턴트 라면": "라면", "만두": "군만두", "마끼": "김밥", "가래떡": "떡국", "짬봉": "짬뽕", "우롱": "우동", "부대 찌개": "부대찌개", "내장": "곱창", "돼지 삼겹": "삼겹살", "사시미": "회", "스시": "초밥", "냉면 사발": "냉면", "해초국": "미역국", "타코": "타코야끼", "호떡": "호떡", "꼬치": "꼬치", "오뎅": "어묵", "오뎅탕": "어묵탕", "튀김 우동": "우동", "잔치 국수": "국수", "공기밥": "쌀밥", "흰밥": "쌀밥", "현미밥": "현미밥", "잡곡밥": "잡곡밥", "보리밥": "보리밥", "콩나물 국": "콩나물국", "된장 찌개": "된장찌개", "추어탕": "추어탕", "곰탕": "곰탕", "설렁탕": "설렁탕", "삼계탕": "삼계탕", "닭갈비": "닭갈비", "찜닭": "찜닭", "양념 치킨": "양념치킨", "프라이드 치킨": "프라이드치킨", "닭 가슴살": "닭가슴살", "물 만두": "물만두", "찐 만두": "찐만두", "튀김 만두": "튀김만두", "쥐포": "쥐포", "오징어 튀김": "오징어튀김", "감자튀김": "감자튀김", "양념게장": "양념게장", "간장 게장": "간장게장" }` — 총 50+건 (epic AC line 594 충족).
     - **시드 멱등 — `ON CONFLICT (alias) DO UPDATE`** — `INSERT INTO food_aliases (id, alias, canonical_name, ...) VALUES (...) ON CONFLICT (alias) DO UPDATE SET canonical_name = EXCLUDED.canonical_name, updated_at = now()`. 재실행 안전 + UPDATE 분기 — `seed_food_aliases()`는 `(inserted, updated)` 카운터 logger.info 출력.
     - **시드 후 게이트 검증** — `SELECT count(*) FROM food_aliases >= 50` 미달 시 `FoodSeedAdapterError("food_aliases seed insufficient: count={n} < 50")` raise → entry point 비-zero exit.
     - **단일 transaction** — 50+건 시드는 단일 `BEGIN`/`COMMIT` — 부분 실패 시 전체 롤백 (50건은 메모리 + 트랜잭션 비용 무시 가능).
     - **`canonical_name` ↔ `food_nutrition.name` 매칭** — 본 스토리는 *데이터 시드*만 (검색 흐름은 Story 3.4 책임) — `canonical_name`이 `food_nutrition.name`과 1:1 매칭되지 않아도 시드 통과(검증 X — Story 3.4에서 *unmatched alias*는 임베딩 fallback 분기). 단 `aliases_data.py` 작성 시 `food_nutrition` 시드 결과 검토 후 *주요 매칭*은 만족하도록 best-effort.
     - **테스트** — `api/tests/rag/test_food_aliases_seed.py` 신규 — DB session monkeypatch. 케이스: (1) 시드 성공 → DB row ≥ 50건 + UNIQUE 제약 만족, (2) 멱등 — 두 번째 시드 → ON CONFLICT UPDATE → DB row 동일 count, (3) `count < 50` → `FoodSeedAdapterError` raise (test 환경에서는 모듈 const monkeypatch로 49건 시뮬레이션), (4) 같은 alias 중복 입력 시(예: `FOOD_ALIASES`에 `"자장면"` 두 번) → UNIQUE 제약 위반 → 첫 INSERT만 성공 + 두 번째는 UPDATE (이상치 — 테스트는 dict 단일 출처 정합 + 중복 차단 차단 단언).

6. **AC6 — `scripts/bootstrap_seed.py` 갱신 + Docker Compose `seed` 자동 시드 (epic AC #5)**
   **Given** Story 1.1 baseline `bootstrap_seed.py` placeholder no-op + Docker Compose `seed` 서비스 wired + 본 스토리 시드 추가, **When** `docker compose up` 실행, **Then**:
     - **`bootstrap_seed.py` 갱신** — `main()` 내부에서 `from app.rag.food.seed import run_food_seed; from app.rag.food.aliases_seed import seed_food_aliases` 동적 import → 두 시드 순차 호출 → 어느 한 쪽 실패는 `return 1` (별 stack trace + Sentry capture). 성공 시 `return 0` + 통계 stdout 출력.
     - **`seed_food_db.py` entry point** — `bootstrap_seed.py` 또는 직접 호출 둘 다 지원 (`if __name__ == "__main__": sys.exit(main())`). 둘 다 동일 `run_food_seed()` 호출 — entry point는 wrapper.
     - **순서** — `food_nutrition` 시드 1차 → `food_aliases` 시드 2차. `food_aliases.canonical_name`이 `food_nutrition.name`을 가리키는 forward join이지만 *본 스토리는 시드 시점 검증 X*(Story 3.4 책임), 두 시드는 *독립*(`food_aliases`는 `food_nutrition` row 미존재여도 INSERT 성공).
     - **Docker `seed` 컨테이너 — 자동 시드** — 현 `docker-compose.yml` `seed` 서비스 `command: ["uv", "run", "python", "/app/scripts/bootstrap_seed.py"]` 그대로 활용. `depends_on: api(service_healthy)` (alembic upgrade head 완료 후 실행 보장 — Story 1.1 W4 정합). seed 컨테이너 종료 시 `restart: "no"` (재시작 회피 — 멱등 시드라도 cost 발생).
     - **`docker compose up` 1-cmd** — `postgres` healthy → `api` (alembic upgrade head 완료 + healthcheck 통과) → `seed` (food_nutrition + food_aliases 시드 + exit 0) — 첫 cold start 시 시드 완료까지 ~5분 (식약처 OpenAPI 1500건 fetch + 임베딩 호출 + INSERT). FR47 정합 — *"`docker compose up`만으로 자동 시드"* (epic AC #5).
     - **재 부팅 시 멱등** — `docker compose down && up` → seed 컨테이너 재실행 → 모든 INSERT가 ON CONFLICT UPDATE 분기 → DB row 변경 0건 (timestamp만 갱신).
     - **`MFDS_OPENAPI_KEY` 미설정 + ZIP placeholder graceful** — `settings.environment ∈ {dev, ci, test}` + `RUN_FOOD_SEED_STRICT` 미설정 시 → `food_nutrition` 시드 0건 + `food_aliases` 시드 50건 + main() returns 0 + warning logger.info — 외주 인수 클라이언트 *첫 부팅* 영업 demo 보호(D9 결정). prod / staging 또는 `RUN_FOOD_SEED_STRICT=1` 시 비-zero exit + Sentry capture.
     - **테스트** — `api/tests/integration/test_bootstrap_seed.py` 신규 — subprocess + DB session monkeypatch. 케이스: (1) 정상 시드 → `food_nutrition` ≥ 1500 + `food_aliases` ≥ 50 + main() returns 0, (2) **dev graceful** — `MFDS_OPENAPI_KEY` 미설정 + `ENVIRONMENT=dev` + ZIP placeholder → main() returns 0 + `food_nutrition` 0건 + `food_aliases` ≥ 50 + warning logger.info captured, (3) **prod fail-fast** — 같은 입력 + `ENVIRONMENT=prod` → main() returns 1 + Sentry tag `food_db_total_failure` set, (4) **dev strict opt-in** — `ENVIRONMENT=dev` + `RUN_FOOD_SEED_STRICT=1` → prod와 동일 fail, (5) 재 시드 멱등 (DB row 동일).

7. **AC7 — HNSW 검색 응답 p95 ≤ 200ms (NFR-P6)**
   **Given** AC1+AC4+AC5 baseline 시드 1,500건 + HNSW 인덱스, **When** `SELECT id, name, embedding <=> :query_embedding AS distance FROM food_nutrition WHERE embedding IS NOT NULL ORDER BY embedding <=> :query_embedding LIMIT 3` 쿼리 실행, **Then**:
     - **HNSW 검색 패턴** — `<=>` 연산자(cosine distance — `vector_cosine_ops` 정합) + `ORDER BY ... LIMIT 3` (top-3 검색 — Story 3.3 retrieve_nutrition 노드 1차 패턴). HNSW 인덱스가 `embedding` 컬럼 + `vector_cosine_ops` 매칭 시 자동 활용.
     - **응답 시간 p95 ≤ 200ms** (NFR-P6 정합) — 1,500건 + ef_construction=64 / m=16 + Postgres 17 + Railway 표준 인스턴스 (4GB RAM 추정) — pgvector 0.8.2 HNSW 표준 벤치마크 ≤ 50ms (overshoot 허용 200ms p95).
     - **본 스토리 검증** — 검색 흐름은 Story 3.3 책임 (retrieve_nutrition 노드 + Self-RAG). 본 스토리는 *인덱스 존재 + EXPLAIN ANALYZE 패턴 검증*만 — `EXPLAIN (ANALYZE, BUFFERS) SELECT ... ORDER BY embedding <=> ...` 출력에 `Index Scan using idx_food_nutrition_embedding` 명시 확인 (Sequential Scan 아님 — 인덱스 활용 검증).
     - **테스트** — `api/tests/rag/test_food_search_performance.py` 신규 — *integration smoke*만 (CI에서 강제 X — 환경 변수 `RUN_PERF_TEST=1` 시점에만 실행). 케이스: (1) `EXPLAIN` 출력에 `idx_food_nutrition_embedding` 사용 확인, (2) 100회 검색 latency 측정 → p95 < 200ms 통과 (실제 시드 1,500건 + 임베딩 정상 케이스 + Docker 환경). 단 CI는 *시드 데이터 + Postgres + 임베딩 모두 가짜* 환경이라 perf test는 skip 디폴트.
     - **OUT — 검색 흐름 자체는 Story 3.3 책임** — 본 AC는 *인덱스 + EXPLAIN 활용*만 단언. 실제 retrieve_nutrition 노드 + Self-RAG `evaluate_retrieval_quality` 분기는 Story 3.3 AC.

8. **AC8 — 신규 도메인 예외 — `FoodSeedAdapterError` / `FoodSeedSourceUnavailableError` / `FoodSeedQuotaExceededError`**
   **Given** Story 1.2~2.5 `BalanceNoteError` 계층 + 본 스토리 시드 어댑터 도입, **When** 시드 어댑터/스크립트가 외부 의존성 실패, **Then**:
     - **`app/core/exceptions.py` 등재** — `MealError` 카탈로그 패턴 정합 — `FoodSeedError(BalanceNoteError)` base + 3 서브클래스:
       - `FoodSeedSourceUnavailableError(FoodSeedError)`: `status=503`, `code="food_seed.source_unavailable"`, `title="Food seed source unavailable"` — API key 미설정 / 정적 백업 ZIP 미존재 케이스.
       - `FoodSeedAdapterError(FoodSeedError)`: `status=503`, `code="food_seed.adapter_error"`, `title="Food seed adapter failure"` — httpx transient 후 retry 실패 / OpenAI embeddings transient 후 retry 실패 / 응답 차원 불일치 / quota 초과 외 일반 어댑터 오류.
       - `FoodSeedQuotaExceededError(FoodSeedError)`: `status=503`, `code="food_seed.quota_exceeded"`, `title="Food seed API quota exceeded"` — 식약처 OpenAPI quota / OpenAI embeddings rate limit 후 retry 실패.
     - **`FoodSeedError` base** — `status=503`, `code="food_seed.error"`, `title="Food seed error"` — 직접 raise 회피 (서브클래스만 사용 권장).
     - **라우터 노출 X** — 본 스토리는 *시드 시점 예외*만, FastAPI 라우터에 노출 X (시드 스크립트가 자체 catch + 비-zero exit + Sentry capture). RFC 7807 변환은 정의만 — Story 3.3+ retrieve_nutrition 노드가 503 raise 시 main.py 핸들러가 자동 변환.
     - **테스트** — `api/tests/test_food_seed_exceptions.py` 신규 — 3 예외 instantiate + `to_problem(instance="/v1/seed")` 호출 → status/code/title 단언. ProblemDetail wire 형식 검증.

9. **AC9 — `.env.example` + `data/README.md` 갱신 — 환경 변수 + ZIP fallback SOP 안내**
   **Given** Story 1.1 baseline `.env.example` + 본 스토리 시드 자동화 환경 변수 도입 + ZIP fallback 운영 SOP 필요, **When** 외주 인수 클라이언트 또는 신규 dev가 `.env` 설정 + 시드 절차 follow, **Then**:
     - **`.env.example` 갱신** — `MFDS_OPENAPI_KEY=` 라인 (이미 등재 — Story 1.1) — 주석 갱신: `# 식품영양성분 DB 시드 (Story 3.1 — 공공데이터포털 15127578) — 미설정 시 ZIP fallback 시도, 둘 다 실패 시 시드 컨테이너 비-zero exit. data.go.kr 가입 후 발급 (분당 100회 limit).` `OPENAI_API_KEY=` 주석 갱신: `# Story 2.3 (OCR Vision) + Story 3.1 (text-embedding-3-small 시드) — 미설정 시 시드 비-zero exit.`
     - **`api/data/README.md` 신규** — 2단락 SOP:
       1. **ZIP fallback 갱신 SOP** — *"식약처 식품영양성분 DB 통합 자료집 — `data.go.kr/data/15047698/fileData.do`에서 다운로드 후 `mfds_food_nutrition_seed.csv`로 변환 후 `api/data/`에 commit. CSV 컬럼은 식약처 표준 키(`name`/`category`/`energy_kcal`/`carbohydrate_g`/`protein_g`/`fat_g`/`saturated_fat_g`/`sugar_g`/`fiber_g`/`sodium_mg`/`cholesterol_mg`/`serving_size_g`/`serving_unit`/`source_id`). 본 repo는 placeholder(헤더만 commit) — 운영 사용 시 실제 데이터 갱신. 분기 1회 수동 갱신 권장."* + 컬럼 스키마 표 1개.
       2. **외주 인수 클라이언트 — 자기 메뉴 별칭 추가 SOP (D10 결정)** — 3 경로 명시:
          - **경로 A — Python 코드 편집 (PR 게이트)**: `api/app/rag/food/aliases_data.py` 의 `FOOD_ALIASES` dict에 `"<자사 메뉴 별칭>": "<표준 음식명>"` entry 추가 → PR + ruff/mypy/pytest 통과 → master 머지 → `docker compose restart seed` 또는 prod 배포 후 자동 시드(ON CONFLICT UPDATE 멱등). 코드 변경 추적 + 회귀 게이트 보호 — 권장.
          - **경로 B — DB 직접 INSERT (런타임 즉시 반영)**: `psql -U app -d app -c "INSERT INTO food_aliases (alias, canonical_name) VALUES ('자사 메뉴 별칭', '표준 음식명') ON CONFLICT (alias) DO UPDATE SET canonical_name = EXCLUDED.canonical_name;"` — Story 3.4 normalize.py가 자동 lookup. 코드 배포 X + 즉시 영업 demo 반영 — 1회성 / 시연 직전 빠른 추가 case.
          - **경로 C — admin UI (Story 7.x)**: `POST /v1/admin/food-aliases` + audit log + role gate — 비개발자 운영자 + 변경 이력 추적이 필요한 시점. 본 스토리 baseline OUT.
          - **`canonical_name` ↔ `food_nutrition.name` 매칭** — `canonical_name`이 `food_nutrition`에 미존재해도 시드 OK(forward FK 없음). Story 3.4 normalize.py가 unmatched 시 임베딩 fallback → LLM 재선택 분기 자연 흡수.
     - **`api/data/mfds_food_nutrition_seed.csv` 신규** — placeholder (헤더만 — `name,category,energy_kcal,carbohydrate_g,protein_g,fat_g,...,source_id` 1줄). 실제 데이터는 운영자가 수동 갱신 SOP 따름.
     - **`api/.gitignore`** — placeholder CSV는 commit (헤더만), 실데이터 갱신 시 *별도 brand-specific*은 gitignore 검토 (본 스토리 baseline은 placeholder commit).
     - **`README.md` 갱신** — Story 3.1 시드 SOP 1단락 추가 — *"`docker compose up`으로 첫 부팅 시 식약처 OpenAPI에서 1,500건 한식 우선 음식 영양 시드 + 50+ 한국식 변형 정규화 사전 시드. `MFDS_OPENAPI_KEY` 미설정 시 ZIP fallback 시도. 시드 멱등 — 재 부팅 시 회귀 0건."*

10. **AC10 — 테스트 게이트 — 백엔드 pytest + ruff + mypy 통과 + Story 2.5 baseline 244 케이스 회귀 0건**
    **Given** Story 2.5 baseline 244 케이스 + 본 스토리 신규 테스트 ~30 케이스, **When** `cd api && uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy .`, **Then**:
     - **신규 테스트 ≥ 30 케이스**:
       - `test_food_nutrition_aliases_schema.py` — alembic 0010 round-trip + 두 테이블 + UNIQUE + HNSW 인덱스 (4 케이스).
       - `test_mfds_openapi.py` — 어댑터 6 케이스 (정상/페이지/key 미설정/quota/transient retry/매핑).
       - `test_openai_embeddings.py` — 어댑터 6 케이스 (batch 처리/차원/RateLimit/Auth/빈 입력/multi-batch).
       - `test_food_seed.py` — 시드 비즈니스 6 케이스 (1차/fallback/실패/멱등/키 누락/임베딩 부분 실패).
       - `test_food_aliases_seed.py` — 4 케이스 (시드/멱등/count<50/중복).
       - `test_bootstrap_seed.py` — 3 케이스 (정상/key 미설정/멱등).
       - `test_food_seed_exceptions.py` — 3 케이스 (3 예외 ProblemDetail).
       - `test_food_search_performance.py` — 2 케이스 (EXPLAIN/p95 — 후자 skip 디폴트).
     - **회귀 0건** — Story 2.5 baseline 244 케이스 모두 통과 (alembic 0010 영향 X — 신규 테이블만, 기존 `meals` 테이블 무영향).
     - **coverage** — 본 스토리 신규 코드 ≥ 70% (NFR-M1 정합).
     - **ruff/format/mypy clean** — 본 스토리 신규 모듈 모두 lint/type clean. `mypy.overrides`에 `pgvector.*`/`pgvector.sqlalchemy` 추가 (이미 deferred — Story 1.1 backlog 정합).
     - **OpenAPI 클라이언트 재생성 X** — 본 스토리는 *내부 인프라*만, 라우터 응답 변경 X — `mobile/lib/api-client.ts` / `web/src/lib/api-client.ts` 갱신 0건 (Story 3.3+ 책임).

11. **AC11 — smoke 검증 시나리오 (사용자 별도 수행 권장)**
    **Given** AC1~AC10 통과 + 로컬 Docker 환경, **When** 다음 4 시나리오 실행, **Then**:
     - **시나리오 1 — 정상 시드 부팅**:
       - `docker compose down -v && docker compose up` → seed 컨테이너 ~5분 후 exit 0.
       - `docker exec balancenote-postgres psql -U app -d app -c "SELECT count(*) FROM food_nutrition;"` ≥ 1500.
       - `docker exec balancenote-postgres psql -U app -d app -c "SELECT count(*) FROM food_aliases;"` ≥ 50.
       - `docker exec balancenote-postgres psql -U app -d app -c "SELECT indexdef FROM pg_indexes WHERE indexname='idx_food_nutrition_embedding';"` 출력에 `USING hnsw` + `vector_cosine_ops` 포함.
     - **시나리오 2 — `MFDS_OPENAPI_KEY` 미설정 + ZIP placeholder (외주 인수 첫 부팅 graceful)**:
       - `.env`에서 `MFDS_OPENAPI_KEY=`(빈) + `ENVIRONMENT=dev` → `docker compose down -v && up` → seed 컨테이너 exit 0 + stdout warning(`[seed_food_db] WARN — food_nutrition seed unavailable, aliases-only mode for dev`).
       - `docker exec balancenote-postgres psql -U app -d app -c "SELECT count(*) FROM food_nutrition;"` = 0 (graceful — 영업 demo 진행 가능).
       - `docker exec balancenote-postgres psql -U app -d app -c "SELECT count(*) FROM food_aliases;"` ≥ 50 (정상 시드).
       - **prod 동등 fail-fast 검증**: `ENVIRONMENT=prod RUN_FOOD_SEED_STRICT=1 uv run python /app/scripts/bootstrap_seed.py` → 비-zero exit + stderr stack trace.
     - **시나리오 3 — 멱등 재 부팅**:
       - 시나리오 1 후 `docker compose restart seed` → seed 컨테이너 재실행 → exit 0 + DB row count 변경 0건 + `food_nutrition.updated_at`만 갱신.
     - **시나리오 4 — HNSW 인덱스 활용 검증**:
       - `psql` 진입 → `EXPLAIN (ANALYZE, BUFFERS) SELECT id, name, embedding <=> '[0.1, 0.2, ..., 0.0]'::vector(1536) AS dist FROM food_nutrition WHERE embedding IS NOT NULL ORDER BY embedding <=> '[...]'::vector(1536) LIMIT 3;` 출력에 `Index Scan using idx_food_nutrition_embedding` 명시 + 응답 < 200ms.
     - **smoke 검증 게이트 X** — 본 AC는 *사용자 수동 검증 권장*. 백엔드 게이트(AC10) + 단위·통합 테스트로 *코드 정합성 + 회귀 차단*은 baseline 충족.

## Tasks / Subtasks

### Task 1 — alembic 0010 마이그레이션 + Meal-style ORM 모델 신규 (AC: #1)

- [x] `api/alembic/versions/0010_food_nutrition_and_aliases.py` 신규 — `down_revision = "0009_meals_idempotency_key"` + 두 테이블 + UNIQUE 제약 + HNSW 인덱스 + downgrade 역순.
- [x] `api/app/db/models/food_nutrition.py` 신규 — `from pgvector.sqlalchemy import Vector` + `embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)` + `nutrition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)` + `__table_args__`에 `UniqueConstraint("source", "source_id", name="uq_food_nutrition_source_source_id")` + HNSW Index는 *마이그레이션에서만* 명시(ORM Index 객체는 SQLAlchemy autogen 한계로 raw `op.create_index`로 마이그레이션에 박음).
- [x] `api/app/db/models/food_alias.py` 신규 — `alias: Mapped[str] = mapped_column(Text, nullable=False)` + `canonical_name: Mapped[str] = mapped_column(Text, nullable=False)` + `__table_args__`에 `UniqueConstraint("alias", name="uq_food_aliases_alias")`.
- [x] `api/app/db/models/__init__.py` 갱신 — `from app.db.models.food_nutrition import FoodNutrition` + `from app.db.models.food_alias import FoodAlias` + `__all__` 추가.
- [x] `api/tests/test_food_nutrition_aliases_schema.py` 신규 — alembic round-trip + UNIQUE + HNSW 인덱스 존재 검증 (4 케이스).
- [x] `cd api && uv run alembic upgrade head` 로컬 검증 + `alembic downgrade 0009_meals_idempotency_key` + `alembic upgrade head` 라운드트립 정상.

### Task 2 — 신규 도메인 예외 등재 (AC: #8)

- [x] `api/app/core/exceptions.py` 갱신 — `FoodSeedError(BalanceNoteError)` base + 3 서브클래스(`FoodSeedSourceUnavailableError`/`FoodSeedAdapterError`/`FoodSeedQuotaExceededError`) — Story 2.5 `MealError` 카탈로그 패턴 정합.
- [x] `api/tests/test_food_seed_exceptions.py` 신규 — 3 예외 instantiate + `to_problem` 호출 → status/code/title 단언 (3 케이스).

### Task 3 — `app/adapters/mfds_openapi.py` 식약처 OpenAPI httpx 어댑터 (AC: #2)

- [x] `api/app/adapters/mfds_openapi.py` 신규 — `httpx.AsyncClient` lazy singleton (P1 정합) + `fetch_food_items(target_count, page_size)` 함수 + `_raw_to_standard(item)` 매핑 + 한식 카테고리 화이트리스트 모듈 const + tenacity 1회 retry + 503/quota 분기.
- [x] `FoodNutritionRaw` Pydantic 모델 — 식약처 표준 키 매핑 (`name`/`category`/`energy_kcal`/...).
- [x] `MFDS_API_BASE_URL` / `MFDS_PAGE_KEY` / `MFDS_SIZE_KEY` 모듈 const — 식약처 OpenAPI 실제 키 명은 `data.go.kr/data/15127578/openapi.do` 문서 참조 후 박음.
- [x] `api/tests/adapters/test_mfds_openapi.py` 신규 — `respx` 또는 `httpx.MockTransport` 사용 6 케이스.

### Task 4 — `app/adapters/openai_adapter.py` 확장 — `embed_texts` 함수 (AC: #3)

- [x] `api/app/adapters/openai_adapter.py` 갱신 — `EMBEDDING_MODEL: Final[str] = "text-embedding-3-small"` const + `embed_texts(texts, batch_size=100)` 함수 — `_get_client()` 재활용 + tenacity 1회 retry (`_call_embedding` 내부 함수) + 차원 검증 (1536) + 빈 입력 빠른 반환 + masked logger.
- [x] `api/tests/adapters/test_openai_embeddings.py` 신규 — `AsyncOpenAI` monkeypatch 6 케이스.

### Task 5 — `app/rag/food/seed.py` + `aliases_data.py` + `aliases_seed.py` 시드 비즈니스 (AC: #4, #5)

- [x] `api/app/rag/__init__.py` + `api/app/rag/food/__init__.py` 신규 (architecture line 257 — `app/rag/food/` 폴더).
- [x] `api/app/rag/food/seed.py` 신규 — `run_food_seed(*, target_count: int = 1500) -> SeedResult` — 1차 식약처 OpenAPI → 2차 ZIP fallback → DB INSERT 멱등 + `(inserted, updated, source)` 통계 반환.
- [x] `api/app/rag/food/aliases_data.py` 신규 — `FOOD_ALIASES: Final[dict[str, str]]` 50+건.
- [x] `api/app/rag/food/aliases_seed.py` 신규 — `seed_food_aliases() -> SeedResult` — `FOOD_ALIASES` dict → DB INSERT 멱등 + count ≥ 50 게이트.
- [x] `api/data/mfds_food_nutrition_seed.csv` 신규 — placeholder (헤더만).
- [x] `api/data/README.md` 신규 — ZIP fallback SOP 1단락 + CSV 컬럼 표.
- [x] `api/tests/rag/test_food_seed.py` + `test_food_aliases_seed.py` 신규 — 6+4 케이스 (어댑터 monkeypatch + DB session 사용).

### Task 6 — `scripts/seed_food_db.py` entry point + `bootstrap_seed.py` 갱신 (AC: #4, #6)

- [x] `scripts/seed_food_db.py` 신규 — `main() -> int` (run_food_seed 호출 + `sys.exit`) + 통계 stdout 출력.
- [x] `scripts/bootstrap_seed.py` 갱신 — placeholder no-op 폐기 → `run_food_seed()` + `seed_food_aliases()` 순차 호출 + 어느 한 쪽 실패는 `return 1` + Sentry capture.
- [x] `api/tests/integration/test_bootstrap_seed.py` 신규 — subprocess + DB session monkeypatch 3 케이스.

### Task 7 — `.env.example` + `README.md` + Docker 자동 시드 검증 (AC: #6, #9)

- [x] `.env.example` 갱신 — `MFDS_OPENAPI_KEY` / `OPENAI_API_KEY` 주석 갱신 (Story 3.1 시드 명시).
- [x] `README.md` 갱신 — Story 3.1 시드 SOP 1단락 추가 (Quick start 섹션 또는 Architecture overview).
- [x] `docker-compose.yml` `seed` 서비스 변경 X — 현 wired 그대로 활용 (Story 1.1 baseline + 본 스토리 시드 자연 hook).
- [x] 로컬 검증 — `docker compose down -v && docker compose up` → seed 컨테이너 exit 0 + DB row 검증 (AC11 시나리오 1).

### Task 8 — HNSW 검색 perf 검증 (AC: #7)

- [x] `api/tests/rag/test_food_search_performance.py` 신규 — EXPLAIN 검증 1 케이스 (필수) + p95 latency 측정 1 케이스 (skip 디폴트, `RUN_PERF_TEST=1` 환경 변수 시 실행).
- [x] EXPLAIN 출력에 `Index Scan using idx_food_nutrition_embedding` 명시 확인 (Sequential Scan 아님).

### Task 9 — 백엔드 게이트 + sprint-status + commit/push (AC: #10)

- [x] `cd api && uv run pytest` — Story 2.5 baseline 244 + 본 스토리 신규 ~30 → 총 ~274 케이스 통과 + coverage ≥ 70%.
- [x] `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy .` — clean.
- [x] `_bmad-output/implementation-artifacts/sprint-status.yaml` 갱신 — `3-1-음식-영양-rag-시드-pgvector: ready-for-dev` → `in-progress` (DS 시작) → `review` (DS 완료) + `epic-3: backlog` → `in-progress` (epic 진입).
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` — 본 스토리 신규 deferred 후보 등재 (DF70+).
- [x] `git add -A && git commit -m "feat(story-3.1): 음식 영양 RAG 시드(식약처 OpenAPI + 1.5K건 + HNSW vector(1536)) + food_aliases 정규화 사전 50+건 + 멱등 시드 + Epic 3 진입"` + `git push -u origin story/3-1-rag-seed-pgvector`.

### Task 10 — CR 진입 준비 (post-DS, pre-CR)

- [x] story Status: `in-progress` → `review` 갱신.
- [x] sprint-status: `3-1-...: in-progress` → `review`.
- [x] CR 워크플로우 `bmad-code-review` 실행 (별 단계).

## Dev Notes

### Architecture decisions (반드시 따를 것)

- **D1 결정 (식약처 OpenAPI 1차 + 통합 자료집 ZIP 백업 2단 fallback — *시드*는 한국 1차 출처만, USDA *시드 OUT*)** — NFR-I1, R7 정합. 1차: `api.data.go.kr/openapi/...` 동적 fetch (분기 1회 갱신 자동화 가능). 2차: `data.go.kr/data/15047698` 통합 자료집 ZIP (정적, 운영자 수동 갱신 SOP). **USDA FoodData Central은 시드 OUT** — 한식 매칭 부족(영문 fallback만 → 짜장면/김치찌개/비빔밥 매칭 0%) + 8주 일정 정합. **단 *런타임 fallback 카드*는 영업 데모 가치 보유** — Story 3.4 retrieve_nutrition 노드의 *unmatched 한식 → USDA 영문 검색 fallback 분기*는 Growth deferred(글로벌 식품기업 페르소나 — Journey 7 자사 SKU 통합 차별화 카드 +1). 본 스토리는 *시드 baseline*만 — USDA 어댑터 / 검색 fallback 모두 OUT.
- **D2 결정 (`text-embedding-3-small` 모델 + 1536 dim 고정)** — architecture `vector(1536)` 명시 정합. `text-embedding-3-large`(3072 dim)는 비용 5배 + architecture 컬럼 변경 필요로 OUT. 모델 업그레이드는 Growth deferred (`vector(1536)` 컬럼 + 재 시드 + Story 3.4 임베딩 재계산 등 광범위 영향).
- **D3 결정 (HNSW `vector_cosine_ops` + m=16 / ef_construction=64)** — pgvector 0.8.2 표준 권장 (1.5K-3K 데이터 규모 + 음식 임베딩 패턴). cosine distance는 OpenAI embeddings 표준(L2 정규화된 vector) — `vector_l2_ops` 대비 성능 동등 + 의미 명료. `m=16`은 빌드 시간 vs 정확도 trade-off의 기본값.
- **D4 결정 (`food_nutrition.embedding` NULL 허용)** — 부분 실패 graceful (어댑터 transient 시 일부 row 임베딩 없이 INSERT 성공) + 검색 시 `WHERE embedding IS NOT NULL` 자동 제외. NULL 차단 (`NOT NULL`)은 임베딩 호출 1건 실패 시 전체 batch 롤백 → 시드 비-멱등성. NULL 허용은 graceful + Story 3.4 시점에 NULL row를 wakeful repair 호출로 백필 (deferred 등재 후보).
- **D5 결정 (시드 멱등 — `ON CONFLICT (source, source_id) DO UPDATE`)** — `(source, source_id)` UNIQUE 제약 + ON CONFLICT UPDATE로 재실행 안전. INSERT 시 `id`(UUID)는 random — 재실행 시 다른 UUID로 충돌 회피 패턴 X (UPDATE는 같은 row 유지). source_id가 식약처 식품코드(`K-115001`)로 안정 — 키 충돌 시드 차단.
- **D6 결정 (시드 batch 300건 단위 transaction)** — 메모리(~5MB) + recovery cost trade-off — 1,500-3,000건을 300건 batch로 fetch + 임베딩 + INSERT + commit. 1,500건 = 5 batch / 5 commit / 5 OpenAI round-trip — cold start latency 단축(100건 batch 대비 OpenAI round-trip 1/3). 부분 실패 시 마지막 commit 이전 batch는 보존. 300건은 OpenAI embeddings API 한계(2048건/요청 + 8K context 토큰 합산) 안전치 — 음식명 평균 10 토큰 × 300 = 3K 토큰.
- **D7 결정 (Vision OCR + Embeddings는 동일 SDK client singleton)** — Story 2.3 P1 패턴 정합 — `_get_client()` 재활용. connection pool + httpx timeout 공유. 별 client 생성은 ~50ms 오버헤드 + connection 누수 위험.
- **D8 결정 (`embedding_text` 포맷 = `f"{name} ({category})"`)** — 동일 음식명 다중 카테고리 분리(예: *"국수"* 한식 vs 양식). category None 시 name only. Story 3.4 normalize.py 검색 시 query는 `name`만 사용 → 임베딩이 category 정보를 *세부 분리*만 담당 (matching key는 name).
- **D9 결정 (`MFDS_OPENAPI_KEY` 미설정 + ZIP placeholder 시 dev/ci/test 환경 graceful + prod/staging fail-fast)** — 외주 인수 클라이언트 *첫 git clone + docker compose up* 시점에 `MFDS_OPENAPI_KEY` 미발급 + ZIP placeholder 디폴트 → *시드 컨테이너 fail*로 영업 demo 즉시 깨짐 회피. dev/ci/test는 food_aliases만 시드 + main() returns 0 + warning. prod/staging은 비-zero exit + Sentry capture(cost runaway / 운영 demo 보호). `RUN_FOOD_SEED_STRICT=1` 환경 변수로 dev에서도 fail-fast opt-in 가능(테스트 강제 + CI 게이트 옵션). 메모리 `feedback_out_criteria_must_be_redundant_or_antipattern.md` 정합 — *외주 인수 첫 부팅 영업 demo*는 UIUX 가시 기본기능, 환경별 분기로 보호.
- **D10 결정 (외주 인수 클라이언트 alias 추가 SOP — `data/README.md` 1단락)** — architecture line 292 *"외주 클라이언트가 자기 메뉴 별칭 추가 시 코드 배포 불필요"* 부분 충족. 본 스토리 baseline은 3 경로 명시: (a) `aliases_data.py` `FOOD_ALIASES` dict 편집 + 재 시드 (PR 게이트 통과), (b) `psql` 직접 INSERT (런타임 즉시 — Story 3.4 normalize.py가 자동 lookup), (c) admin UI(POST/DELETE 라우터 + audit log)는 Story 7.x 책임. SOP 1단락만 박음 — 운영 자동화는 Story 8 polish.

### Library / Framework 요구사항

- **pgvector (Python lib `>=0.3`, Postgres extension 0.8.2)** — `pyproject.toml` 등재 0.4.2 venv 확인. `from pgvector.sqlalchemy import Vector` + `Vector(1536)` 컬럼. Postgres extension은 `docker/postgres-init/01-pgvector.sql` 자동 설치(Story 1.1 baseline 정합).
- **`text-embedding-3-small`** — 1536 dim, $0.02/1M tokens, 8K context. SDK: `openai>=1.55` 이미 등재 (Story 2.3 baseline) — `_get_client()` 재활용.
- **httpx** — 식약처 OpenAPI fetch — Story 1.2 google_oauth + Story 2.3 OCR Vision 정합 — `httpx.AsyncClient(timeout=30.0)`.
- **tenacity** — 1회 retry + exponential wait — Story 2.3 OCR Vision 정합 (`_TRANSIENT_RETRY_TYPES` 명시).
- **SQLAlchemy 2.0.49 async** — Story 1.2 baseline + 본 스토리 신규 두 모델 — `Mapped` + `mapped_column` 패턴 정합.
- **Alembic** — 0010 마이그레이션 — `op.create_index` raw + `postgresql_using='hnsw'` + `postgresql_with={'m': 16, 'ef_construction': 64}` + `postgresql_ops={'embedding': 'vector_cosine_ops'}`. autogenerate는 vector + HNSW 미지원 → 수동 작성 필수.

### Naming 컨벤션

- **테이블** — `food_nutrition` / `food_aliases` (snake_case 복수 — architecture line 392 정합).
- **컬럼** — snake_case (`source_id`, `created_at`, `embedding`, `nutrition`).
- **UNIQUE 제약** — `uq_food_nutrition_source_source_id` / `uq_food_aliases_alias` (autogenerate `uq_*` allow — Story 1.2 W9 정합).
- **HNSW 인덱스** — `idx_food_nutrition_embedding` (architecture line 395 명시 정합).
- **신규 모듈** — `app/adapters/mfds_openapi.py` / `app/rag/food/seed.py` / `app/rag/food/aliases_data.py` / `app/rag/food/aliases_seed.py` / `app/db/models/food_nutrition.py` / `app/db/models/food_alias.py` (architecture 폴더 구조 정합).
- **테스트 위치** — `api/tests/<feature>/test_<thing>.py` (Story 2.5 패턴 정합 — flat or nested by feature).
- **예외 카탈로그 prefix** — `food_seed.*` (`MealError` `meals.*` 정합 — Story 2.5 패턴).
- **logger.info 키** — `mfds.openapi.fetch_page` / `food_seed.insert` / `food_aliases.seed` (event-style 로깅, Story 2.3+ 정합).

### 폴더 구조 (Story 3.1 종료 시점에 *반드시* 존재해야 하는 신규/수정 항목)

```
api/
  alembic/versions/
    0010_food_nutrition_and_aliases.py    # 신규 — AC1
  app/
    adapters/
      mfds_openapi.py                     # 신규 — AC2
      openai_adapter.py                   # 갱신 — embed_texts 추가 (AC3)
    core/
      exceptions.py                       # 갱신 — FoodSeed* 3 예외 추가 (AC8)
    db/models/
      __init__.py                         # 갱신 — FoodNutrition + FoodAlias export
      food_nutrition.py                   # 신규 — AC1
      food_alias.py                       # 신규 — AC1
    rag/                                  # 신규 폴더 — architecture line 255-258
      __init__.py                         # 신규
      food/
        __init__.py                       # 신규
        seed.py                           # 신규 — AC4 (run_food_seed)
        aliases_data.py                   # 신규 — AC5 (FOOD_ALIASES dict)
        aliases_seed.py                   # 신규 — AC5 (seed_food_aliases)
  data/                                   # 신규 폴더
    mfds_food_nutrition_seed.csv          # 신규 — AC9 placeholder (헤더만)
    README.md                             # 신규 — AC9 ZIP fallback SOP
  tests/
    test_food_nutrition_aliases_schema.py # 신규 — AC1
    test_food_seed_exceptions.py          # 신규 — AC8
    adapters/
      test_mfds_openapi.py                # 신규 — AC2
      test_openai_embeddings.py           # 신규 — AC3
    rag/
      test_food_seed.py                   # 신규 — AC4
      test_food_aliases_seed.py           # 신규 — AC5
      test_food_search_performance.py     # 신규 — AC7 (skip 디폴트)
    integration/
      test_bootstrap_seed.py              # 신규 — AC6 (subprocess)

scripts/
  bootstrap_seed.py                       # 갱신 — placeholder no-op 폐기, run_food_seed 호출
  seed_food_db.py                         # 신규 — AC4 entry point

.env.example                              # 갱신 — MFDS_OPENAPI_KEY 주석 (AC9)
README.md                                 # 갱신 — Story 3.1 시드 SOP 1단락 (AC9)
_bmad-output/implementation-artifacts/
  sprint-status.yaml                      # 갱신 — 3-1 ready-for-dev → in-progress → review
  deferred-work.md                        # 갱신 — DF70+ 신규 후보
```

**변경 X** — `mobile/*` / `web/*` (본 스토리는 백엔드 인프라만 — 라우터 응답 변경 X) / `docker-compose.yml`(현 `seed` 서비스 wiring 그대로 활용) / `docker/postgres-init/01-pgvector.sql`(이미 vector extension 설치).

### 보안·민감정보 마스킹 (NFR-S5)

- **API 키 노출 X** — `MFDS_OPENAPI_KEY` / `OPENAI_API_KEY` 모두 logger 출력 X. 어댑터에서 query 파라미터 전송 시 URL에 key가 포함되지만 *logger에 raw URL 출력 X* — `logger.info("mfds.openapi.fetch_page", page_index=..., items_count=..., latency_ms=...)` 형태로 *masked* 1줄.
- **음식명 + 영양 raw 노출 회피** — `texts` 입력은 logger 출력 X (잠재 raw_text 포함 가능 — NFR-S5 식습관 추론 마스킹 정합 — Story 2.3 OCR Vision 패턴 정합). `texts_count` + `model` + `latency_ms`만.
- **시드 통계 출력** — stdout `[seed_food_db] inserted={n} updated={n} source={primary|fallback}` — 음식명 노출 X (count + source만).
- **Sentry capture** — 시드 실패 시 `scope.set_tag("seed", "food_db_total_failure")` + stack trace. raw 음식명 + 영양 데이터는 Sentry breadcrumb에 노출 X (Story 1.1 + Story 2.3 베이스라인 마스킹 hook 활용).

### Anti-pattern 카탈로그 (본 스토리 영역)

- **`embedding NOT NULL` + 부분 실패 시 전체 batch 롤백** — D4 결정으로 회피 — `embedding NULL` 허용으로 graceful degradation. 1건 임베딩 실패가 1500건 batch 롤백을 트리거하면 *시드 영원히 실패* 가능성.
- **시드 비멱등 (INSERT 만 + ON CONFLICT 미적용)** — `docker compose restart seed` 시 row 중복 + UNIQUE 위반 시드 fail. `ON CONFLICT (source, source_id) DO UPDATE`로 회피 (D5).
- **카테고리 정보 임베딩 미반영** — 동일 *"국수"* 한식 vs 양식 임베딩 충돌 → 검색 정확도 ↓. `f"{name} ({category})"` 포맷으로 회피 (D8).
- **HNSW autogenerate 의존** — Alembic autogenerate는 vector + HNSW 미지원. 수동 `op.create_index` raw 작성 필수 (autogen 누락 회귀 차단).
- **`food_aliases.canonical_name` ↔ `food_nutrition.name` 시드 시점 검증** — 본 스토리 OUT (Story 3.4 책임). 시드 시점 검증 시 *`food_nutrition` 시드 부분 실패 → `food_aliases.canonical_name` orphan*  → 시드 fail. 본 스토리는 두 시드 *독립* 처리 (graceful — orphan은 Story 3.4 normalize.py에서 *unmatched alias* 분기로 자연 처리).
- **`text-embedding-3-large` 사용 (3072 dim)** — architecture `vector(1536)` 컬럼 변경 필요 + 비용 5배 + 모델 업그레이드 광범위 영향. `text-embedding-3-small`(1536 dim) 고정 (D2).
- **USDA FoodData Central fallback 도입** — 한식 매칭 부족(영문 fallback만) + 8주 일정 정합 OUT. 식약처 OpenAPI + ZIP 백업 2단만 (D1).
- **SDK client 매 호출 재생성** — Story 2.3 P1 회피 패턴 정합 — `_get_client()` lazy singleton + double-checked lock 재활용 (Vision OCR + Embeddings 공유 — D7).
- **`Vector` 컬럼 raw `JSON` array로 저장** — `from pgvector.sqlalchemy import Vector` 사용 필수 (`Vector(1536)`). raw JSON array는 HNSW 인덱스 비활용 + cast 비용.
- **빈 `texts` 입력에도 API 호출 발생** — `len(texts) == 0` 시 빈 리스트 즉시 반환 (cost 0 — AC3 명시).

### Previous Story Intelligence (Story 2.5 + Story 2.3 학습)

**Story 2.5 (오프라인 텍스트 큐잉 — 직전 스토리)**:

- ✅ **W46 closed (Story 2.1 deferred → Story 2.5에서 흡수)** — `meals.idempotency_key` partial UNIQUE + race-free SELECT-INSERT-CATCH 패턴. 본 스토리는 *idempotency 패턴 sharing* (시드 멱등 — `ON CONFLICT (source, source_id) DO UPDATE`).
- 🔄 **DF54-DF69 (Story 2.5 신규 deferred)** — 본 스토리 영향 X (offline-queue 책임 영역).
- 🔄 **W42 (`MealError` base 추상 가드)** — `FoodSeedError` 본 스토리 신규 base — 동일 패턴(직접 raise 회피 권장)으로 추상화 미적용 (Story 8 일괄). MealError 패턴 정합 — 직접 raise 회피 docstring 명시.

**Story 2.3 (OCR Vision)**:

- ✅ **`openai_adapter.py` SDK singleton + double-checked lock** — 본 스토리 `embed_texts`도 `_get_client()` 재활용 — connection pool + timeout 공유 (D7).
- ✅ **tenacity 1회 retry + `_TRANSIENT_RETRY_TYPES` 명시 subset** — 본 스토리 `_call_embedding`도 동일 패턴 (CR P1 정합 — 영구 오류 즉시 fail).
- ✅ **`response.choices` empty 가드** — `embeddings.data` empty 가드 + 차원 불일치 검증으로 패턴 정합.
- ✅ **logger raw 입력 회피** — `texts` raw 출력 X (NFR-S5 마스킹 정합) — `texts_count` + `latency_ms` + `model`만.
- 🔄 **DF7 — `parsed_items` 음식명 정규화 미적용** — 본 스토리 `food_aliases` 시드로 *normalize.py 입력 데이터* 박음. Story 3.4에서 normalize.py가 `food_aliases` lookup → orphan은 임베딩 fallback (DF7 closed 후보).

**Story 1.1 (부트스트랩)**:

- ✅ **`vector` extension** — `docker/postgres-init/01-pgvector.sql` baseline (Story 1.1 W4 — 본 스토리 마이그레이션은 `CREATE EXTENSION` 호출 X).
- ✅ **`MFDS_OPENAPI_KEY` env** — `.env.example` 등재 baseline (Story 1.1) — 본 스토리는 주석 갱신만.
- ✅ **`bootstrap_seed.py` placeholder + `seed` 컨테이너 wired** — Story 1.1 baseline + 본 스토리 갱신 — placeholder no-op 폐기 → `run_food_seed()` + `seed_food_aliases()` 호출.
- 🔄 **mypy `[[tool.mypy.overrides]]` 누락 모듈 (Story 1.1 deferred)** — 본 스토리 `pgvector.*` 추가 (이미 deferred 등재) → 본 스토리 시점 wire (`api/pyproject.toml` `[[tool.mypy.overrides]]` 추가).

**Story 1.4 (PIPA 동의)**:

- ✅ **`require_automated_decision_consent` dependency** — 본 스토리는 *시드 시점*만, 라우터 노출 X — dependency 적용 X. Story 3.3 retrieve_nutrition 노드 + analysis 라우터에서 적용 (Story 3.3 책임).

**Story 1.5 (건강 프로필)**:

- ✅ **22종 알레르기 enum (`domain/allergens.py`)** — 본 스토리는 *food_nutrition + food_aliases*만, 알레르기 도메인 X (Story 3.5 fit_score 노드 책임).

### Git Intelligence (최근 커밋 패턴)

```
d4c513b feat(story-2.5): 오프라인 텍스트 큐잉(AsyncStorage FIFO + 지수 backoff) + Idempotency-Key 처리(W46 흡수) (#16)
5619173 feat(story-2.4): 일별 식단 기록 화면 + 7일 캐시 + KST 필터 + CR 11 patches (#15)
40403f3 feat(story-2.3): OCR Vision 추출 + 사용자 확인 카드 + parsed_items 영속화 + CR 8 patch (#14)
cf93900 chore(story-2.2): mark done — sprint-status + spec Status review → done (post-merge fix) (#13)
9119710 feat(story-2.2): 식단 사진 입력 + R2 presigned URL + 권한 흐름 (#12)
```

**최근 커밋 패턴에서 학습:**

- 커밋 메시지: `feat(story-X.Y): <한국어 요약> + <부수 작업>` 형식 — 본 스토리 `feat(story-3.1): 음식 영양 RAG 시드(식약처 OpenAPI + 1.5K건 + HNSW vector(1536)) + food_aliases 정규화 사전 50+건 + Epic 3 진입` 패턴.
- master 직접 push 금지 — feature branch + PR + merge 버튼 (memory: `feedback_pr_pattern_for_master.md`).
- 새 스토리 브랜치는 master에서 분기 — `git checkout master && git pull && git checkout -b story/3-1-rag-seed-pgvector` (memory: `feedback_branch_from_master_only.md`). **이미 분기 완료** (CS 시작 전 — memory: `feedback_ds_complete_to_commit_push.md` 정합).
- DS 종료점은 commit + push (memory: `feedback_ds_complete_to_commit_push.md`). PR(draft 포함)은 CR 완료 후 한 번에 생성.
- CR 종료 직전 sprint-status/story Status를 review → done 갱신해 PR commit에 포함 (memory: `feedback_cr_done_status_in_pr_commit.md`).
- OpenAPI 재생성 커밋 분리 권장 — 단 본 스토리는 라우터 응답 변경 X → OpenAPI 재생성 미발생.

### References

- [Source: epics.md:583-595] — Story 3.1 epic AC 5건 (식약처 OpenAPI 시드 + jsonb 표준 키 + HNSW + food_aliases 50+건 + Docker 자동 시드).
- [Source: epics.md:579-581] — Epic 3 (AI 영양 분석 + Self-RAG + 인용 피드백) 입장 단락.
- [Source: prd.md:967-971] — FR17~FR20 (분석 파이프라인 + Self-RAG 재검색 + 음식명 변형 매칭 + 재질문).
- [Source: prd.md:482-484] — NFR-P6 (음식 RAG 검색 응답 ≤ 200ms, Redis 캐시 hit ≤ 30ms — 본 스토리는 캐시 OUT, HNSW만).
- [Source: prd.md:496-505] — I1 외부 데이터 소스 (식약처 OpenAPI + 통합 자료집 ZIP + USDA fallback) — D1 결정 정합.
- [Source: prd.md:531-538] — R1, R7, R8 — 음식명 매칭 정확도 + 식약처 OpenAPI 장애 + 표시기준 22종 갱신.
- [Source: architecture.md:285-299] — Data Architecture (Postgres 17 + pgvector 0.8.2 + jsonb 표준 키 + HNSW 별 인덱스).
- [Source: architecture.md:255-258] — `app/rag/food/` 폴더 구조 + chunking 모듈 분리.
- [Source: architecture.md:386-431] — Naming Patterns (DB 테이블 snake_case 복수 + 인덱스 `idx_<table>_<columns>`).
- [Source: architecture.md:580-695] — Backend 폴더 구조 — `app/rag/food/seed.py` / `app/rag/food/normalize.py` / `app/db/models/food_nutrition.py` / `app/db/models/food_alias.py` 표기 정합.
- [Source: architecture.md:355-365] — Implementation Sequence (1번 pgvector + Alembic + 5번 음식 RAG 시드 W1-W2 spike) — 본 스토리는 5번 슬롯 정합.
- [Source: research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md:103-107] — 식약처 식품영양성분 DB OpenAPI(공공데이터포털 15127578) + 통합 자료집(15047698) + 식의약 데이터 포털 출처 매핑.
- [Source: research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md:180-201] — `food_nutrition.nutrition` jsonb 권장 키 스키마 (energy_kcal/carbohydrate_g/...).
- [Source: research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md:203-213] — `knowledge_chunks` 메타데이터 (Story 3.2 입력) — 본 스토리 OUT.
- [Source: 2-5-오프라인-텍스트-큐잉-sync.md] — `meals.idempotency_key` ON CONFLICT 패턴 정합 / 직전 스토리 학습.
- [Source: 2-3-ocr-vision-추출-확인-카드.md] — `openai_adapter.py` 패턴 (SDK singleton + tenacity + structured outputs).
- [Source: 1-1-프로젝트-부트스트랩.md] — Docker Compose seed 컨테이너 + bootstrap_seed.py placeholder baseline.
- [Source: deferred-work.md DF7 (Story 2.3)] — `parsed_items` 음식명 정규화 미적용 — 본 스토리 `food_aliases` 시드로 baseline 박음 + Story 3.4 normalize.py에서 closed.
- [Source: api/app/db/models/meal.py] — Story 2.5 ORM 패턴 (Mapped + mapped_column + JSONB + UUID + __table_args__).
- [Source: api/app/adapters/openai_adapter.py] — Story 2.3 SDK singleton + tenacity 1회 retry + masked logger 패턴.
- [Source: api/app/core/exceptions.py] — `BalanceNoteError` + `MealError` 카탈로그 패턴 (FoodSeedError 신규 정합).
- [Source: api/app/core/config.py] — `MFDS_OPENAPI_KEY` settings 등재 + `.env.example` baseline.
- [Source: api/pyproject.toml] — `pgvector>=0.3` + `openai>=1.55` + `tenacity>=9.0` 등재 baseline.
- [Source: docker-compose.yml] — `seed` 서비스 wired (`bootstrap_seed.py` 호출 + `depends_on: api(service_healthy)`).
- [Source: docker/postgres-init/01-pgvector.sql] — `CREATE EXTENSION vector` baseline (Story 1.1).
- [Source: pgvector/pgvector docs] — HNSW 인덱스 (m, ef_construction 파라미터) + `vector_cosine_ops` 표준.
- [Source: OpenAI Embeddings API docs] — `text-embedding-3-small` 1536 dim, $0.02/1M tokens, 8K context.
- [Source: 공공데이터포털 데이터셋 15127578] — 식품영양성분 DB OpenAPI 가입 + 키 발급 + 분당 100회 limit + JSON 응답 표준.
- [Source: 공공데이터포털 데이터셋 15047698] — 식품영양성분 DB 통합 자료집 (다운로드 ZIP/CSV) — 정적 백업 SOP.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] (Amelia, BMad Senior Software Engineer)

### Debug Log References

- mfds_openapi 어댑터 — 5xx 서버 오류를 internal `_TransientServerError` marker로 격리해 tenacity retry 적용 (`httpx.HTTPError` 기반 catch가 영구 4xx까지 retry하던 cost 누수 방지).
- run_food_seed source 라벨 — `_try_primary_source`가 부분 결과(items < target)도 보존하도록 분리, `primary_sufficient` 플래그로 fallback 분기 결정. source는 "primary" / "primary+fallback" / "fallback" / "none" 4종.
- bootstrap_seed.py 통합 테스트 — pytest-asyncio event loop와 `asyncio.run()` 충돌로 `main()` wrapper 직접 호출 X. 대신 async core `_run_seeds()`를 직접 await하는 패턴으로 검증.

### Completion Notes List

- alembic 0010 — `food_nutrition` (12 컬럼 + `embedding vector(1536)` + UNIQUE(source, source_id)) + `food_aliases` (5 컬럼 + UNIQUE(alias)) + HNSW 인덱스(`vector_cosine_ops` m=16 ef_construction=64). pgvector raw `ALTER TABLE` 패턴으로 `vector(1536)` 컬럼 추가(SQLAlchemy autogen 미지원).
- ORM 2종 — `pgvector.sqlalchemy.Vector(1536)` 매핑 + `JSONB` `nutrition` + `__table_args__`에 UNIQUE 제약 등재. HNSW 인덱스는 마이그레이션 SOT (ORM `Index` 객체는 vector_cosine_ops opclass 미지원).
- `FoodSeedError` 3 서브클래스(`SourceUnavailable`/`AdapterError`/`QuotaExceeded`) — 모두 status=503, `food_seed.*` code prefix. RFC 7807 변환 정의만 (라우터 노출은 Story 3.3+).
- `mfds_openapi.py` 어댑터 — httpx async singleton + `MFDS_RAW_KEY_MAP` 13키 매핑(원본 `AMT_NUM*` 격리) + `MFDS_KOREAN_FOOD_CATEGORIES` 19종 화이트리스트 + tenacity 1회 retry + 401/403 즉시 fail + 429/quota 분기 + 5xx transient → `_TransientServerError` marker.
- `openai_adapter.embed_texts` 확장 — `text-embedding-3-small` (1536 dim) + 300건 batch + 빈 입력 cost 0 + 차원 불일치 가드 + Vision OCR `_get_client()` SDK singleton 공유 (D7).
- `app/rag/food/seed.py` — 1차 OpenAPI + 2차 ZIP fallback CSV + `settings.environment` 분기 graceful (dev/ci/test 0건 + main returns 0) vs strict fail-fast (prod/staging or `RUN_FOOD_SEED_STRICT=1`). 300건 batch transaction + `ON CONFLICT (source, source_id) DO UPDATE` 멱등.
- `app/rag/food/aliases_data.py` — 52건 한국식 변형 매핑(epic AC 50+ 충족). `app/rag/food/aliases_seed.py` — 멱등 INSERT + count >= 50 게이트.
- `scripts/seed_food_db.py` — entry point + Sentry capture(`scope.set_tag("seed", "food_db_total_failure")`) + stdout 통계 (NFR-S5 음식명 raw 노출 X). `scripts/bootstrap_seed.py` — placeholder no-op 폐기 + sibling import로 위임.
- `.env.example` — `MFDS_OPENAPI_KEY` + `OPENAI_API_KEY` 주석 갱신 + `RUN_FOOD_SEED_STRICT=1` opt-in 명시. `README.md` Quick start에 시드 1단락 추가. `api/data/README.md` — ZIP fallback SOP + 외주 alias 추가 3 경로 (D10).
- 신규 테스트 31 케이스: schema 6 + exceptions 4 + mfds_openapi 6 + embeddings 6 + food_seed 6 + aliases_seed 4 + bootstrap_seed 3 + perf 2(1 skip 디폴트). 회귀 0건(Story 2.5 baseline 244 케이스 모두 통과).
- 게이트 — pytest 280 passed / 1 skipped / coverage 84.73% (≥70%) / ruff clean / format clean / mypy 신규 에러 0 (pre-existing 11건은 test_consents_deps.py Story 1.4 baseline).

### File List

신규:
- `api/alembic/versions/0010_food_nutrition_and_aliases.py` (AC1)
- `api/app/db/models/food_nutrition.py` (AC1)
- `api/app/db/models/food_alias.py` (AC1)
- `api/app/adapters/mfds_openapi.py` (AC2)
- `api/app/rag/__init__.py` + `api/app/rag/food/__init__.py` (AC4-5)
- `api/app/rag/food/seed.py` (AC4)
- `api/app/rag/food/aliases_data.py` (AC5)
- `api/app/rag/food/aliases_seed.py` (AC5)
- `api/data/mfds_food_nutrition_seed.csv` (AC9 placeholder)
- `api/data/README.md` (AC9)
- `scripts/seed_food_db.py` (AC4 entry)
- `api/tests/test_food_nutrition_aliases_schema.py` (AC1)
- `api/tests/test_food_seed_exceptions.py` (AC8)
- `api/tests/adapters/__init__.py` + `api/tests/adapters/test_mfds_openapi.py` (AC2)
- `api/tests/adapters/test_openai_embeddings.py` (AC3)
- `api/tests/rag/__init__.py` + `api/tests/rag/test_food_seed.py` (AC4)
- `api/tests/rag/test_food_aliases_seed.py` (AC5)
- `api/tests/rag/test_food_search_performance.py` (AC7)
- `api/tests/integration/__init__.py` + `api/tests/integration/test_bootstrap_seed.py` (AC6)

수정:
- `api/app/db/models/__init__.py` (FoodNutrition + FoodAlias export)
- `api/app/adapters/openai_adapter.py` (embed_texts 추가 — AC3)
- `api/app/core/exceptions.py` (FoodSeed* 3 예외 추가 — AC8)
- `scripts/bootstrap_seed.py` (placeholder no-op 폐기 — AC6)
- `.env.example` (Story 3.1 주석 — AC9)
- `README.md` (시드 1단락 — AC9)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (3.1 review + Epic 3 in-progress)
- `_bmad-output/implementation-artifacts/3-1-음식-영양-rag-시드-pgvector.md` (Status review + Dev Agent Record)

### Change Log

| Date | Author | Note |
|------|--------|------|
| 2026-04-30 | Amelia (claude-opus-4-7[1m]) | Story 3.1 ready-for-dev — 식약처 식품영양성분 DB OpenAPI 1차 + 통합 자료집 ZIP 백업 2단 fallback(USDA OUT) + `food_nutrition` jsonb 표준 키 + `vector(1536)` HNSW(`vector_cosine_ops` m=16/ef_construction=64) + `food_aliases` 50+건 핵심 변형 + 시드 멱등 `ON CONFLICT (source, source_id) DO UPDATE` + Docker Compose `seed` 자동 시드(`docker compose up` 1-cmd) + `app/adapters/mfds_openapi.py` httpx 어댑터 + `app/adapters/openai_adapter.py` `embed_texts` 확장(SDK singleton 공유 — D7) + `app/rag/food/seed.py` + `aliases_data.py` + `aliases_seed.py` + `scripts/seed_food_db.py` entry + `bootstrap_seed.py` 갱신 + `FoodSeedError` 3 예외 + alembic 0010 + ORM 2종 + `.env.example` 주석 + `data/README.md` ZIP fallback SOP + `README.md` Quick start 시드 1단락 baseline 컨텍스트 작성. Status: backlog → ready-for-dev. |
| 2026-04-30 | Amelia (claude-opus-4-7[1m]) | Story 3.1 DS 완료 → review. alembic 0010(food_nutrition + food_aliases + HNSW vector_cosine_ops) + ORM 2종 + mfds_openapi.py(httpx async + 한식 카테고리 화이트리스트 + tenacity retry + 5xx _TransientServerError marker) + openai_adapter.embed_texts(text-embedding-3-small 1536 dim batch 300건 + Vision SDK singleton 공유 D7) + app/rag/food/seed.py(1차 OpenAPI + 2차 ZIP CSV + dev graceful D9 + RUN_FOOD_SEED_STRICT opt-in + ON CONFLICT 멱등) + aliases_data.py 52건 + aliases_seed.py + scripts/seed_food_db.py entry + bootstrap_seed.py 위임 + FoodSeedError 3 서브클래스 + .env.example/README.md/api/data/README.md SOP. 신규 테스트 31 케이스 통과(schema 6 + exceptions 4 + mfds 6 + embeddings 6 + seed 6 + aliases 4 + bootstrap 3 + perf 2[1 skip]). 회귀 0건(Story 2.5 baseline 244 모두 통과). Gate: pytest 280 passed / 1 skipped / coverage 84.73% / ruff·format clean / mypy 신규 0(pre-existing 11건 test_consents_deps.py Story 1.4 baseline). |
| 2026-04-30 | Amelia (claude-opus-4-7[1m]) | Story 3.1 spec refinement — 5건 적용: (1) **AC2** 식약처 OpenAPI endpoint URL + 응답 키 매핑(`MFDS_RAW_KEY_MAP` 13키 추정) + 한식 카테고리 화이트리스트(`MFDS_KOREAN_FOOD_CATEGORIES` 19종) 어댑터 모듈 const 박음 + DS 시점 OpenAPI 문서 검증 의무 명시(공공데이터포털 신/구 표준 혼재 변동 위험), (2) **AC4 + AC11 시나리오 2 + D9 신규** dev/ci/test 환경 graceful 분기 — `MFDS_OPENAPI_KEY` 미설정 + ZIP placeholder 시 food_aliases만 시드 + main() returns 0 + warning(외주 인수 클라이언트 첫 부팅 영업 demo 보호) + `RUN_FOOD_SEED_STRICT=1` opt-in으로 dev fail-fast 강제 + prod/staging 비-zero exit + Sentry capture 유지 + 테스트 케이스 3 → 5(graceful + strict + 멱등 추가), (3) **D1** USDA FoodData Central — *시드 OUT*은 그대로 유지, *런타임 fallback 카드*(Story 3.4 unmatched 한식 → USDA 영문 검색 분기, Journey 7 글로벌 식품기업 차별화 카드 +1) Growth deferred 명시 강화, (4) **AC5 + AC9 + D10 신규** 외주 인수 클라이언트 alias 추가 3경로 SOP(경로 A 코드 PR + 경로 B `psql` 직접 INSERT 런타임 즉시 + 경로 C admin UI Story 7.x OUT) `data/README.md` 박음 — architecture line 292 *"코드 배포 불필요"* 부분 충족, (5) **AC3 + D6** embeddings batch size 100 → 300 상향 — 1,500건 시드 = 5 batch / 5 commit / 5 OpenAI round-trip(100건 batch 대비 round-trip 1/3) — cold start latency 단축, OpenAI 한계(2048건/요청 + 8K context) 안전치 + 테스트 케이스 batch 갯수 정합 갱신. Status: ready-for-dev 유지(스펙 보강만, 구현 영향 0건). |

### Review Findings

(채워질 예정 — CR 완료 시점)
