# Story 3.2: 가이드라인 RAG 시드 + chunking 모듈

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **1인 개발자(시드 작업) / 외주 인수 클라이언트(자체 PDF 시드 인터페이스 활용)**,
I want **KDRIs 2020 + 대한비만학회 9판 + 대한당뇨병학회 매크로 권고 + 질병관리청 표준 + 식약처 22종 알레르기 가이드라인을 50-100 chunks로 시드하고 chunking 모듈을 PDF·HTML·Markdown 3-format 재사용 인터페이스로 박기를**,
So that **Story 3.6 `generate_feedback` 노드가 *"(출처: 보건복지부 2020 KDRIs)"* 패턴으로 한국 1차 출처를 명시 인용할 수 있고, 외주 인수 클라이언트는 동일 chunking 인터페이스로 자기 PDF를 시드 추가할 수 있다.**

본 스토리는 Epic 3(AI 영양 분석 — Self-RAG + 인용 피드백)의 *지식 베이스 + chunking 인터페이스 베이스라인*을 박는다 — **(a) `knowledge_chunks` 테이블 신규 — `chunk_text TEXT` + `embedding vector(1536)` HNSW(`vector_cosine_ops`, m=16, ef_construction=64) + 메타데이터 6종(`source` enum-style TEXT / `source_id` TEXT / `chunk_index` INTEGER / `authority_grade` TEXT / `topic` TEXT / `applicable_health_goals TEXT[]` / `published_year` INTEGER / `doc_title` TEXT) — Story 3.6 generate_feedback 노드의 인용 출처 메타 직접 주입 인프라**, **(b) `app/rag/chunking/__init__.py` + `markdown.py` + `pdf.py` + `html.py` 3-format 재사용 chunker 인터페이스 — 통일된 `chunk(content, *, max_chars=1000, overlap=100) -> list[Chunk]` 시그니처 + `Chunk` 데이터클래스(`text`/`chunk_index`/`char_start`/`char_end`) + heading-aware splitter(Markdown) + page-aware splitter(PDF) + DOM-aware splitter(HTML)**, **(c) `app/rag/guidelines/seed.py` 신규 — `data/guidelines/*.md` YAML frontmatter 메타데이터 파일 단위 시드 entry — frontmatter 파싱(`source`/`source_id`/`authority_grade`/`topic`/`applicable_health_goals`/`published_year`/`doc_title`) + body chunking(markdown chunker) + `embed_texts` 호출(Story 3.1 baseline 재활용 — D7) + 멱등 INSERT(`ON CONFLICT (source, source_id, chunk_index) DO UPDATE`)**, **(d) `data/guidelines/` 폴더 신규 — KDRIs AMDR / KDRIs 단백질 / 대한비만학회 체중감량 / 대한당뇨병학회 매크로 / 식약처 22종 알레르기 / 질병관리청 당뇨 식이요법 6 파일 + 50-100 chunks 분량 — frontmatter는 research 1.1 1차 자료 인덱스 정합 + body는 운영자가 분기 1회 수동 chunking SOP 따라 갱신**, **(e) `scripts/seed_guidelines.py` 신규 — entry point — `app.rag.guidelines.seed.run_guideline_seed()` 호출 + dev/ci/test graceful 분기(`OPENAI_API_KEY` 미설정 시 embedding NULL + main returns 0 + warning) + prod/staging fail-fast(또는 `RUN_GUIDELINE_SEED_STRICT=1` opt-in) — Story 3.1 D9 정합**, **(f) `scripts/bootstrap_seed.py` 갱신 — `seed_guidelines.main()` 추가 호출(food seed 직후 순차) — Docker `seed` 컨테이너가 `docker compose up`만으로 음식 + 가이드라인 시드 일괄 자동(epic AC #4 정합)**, **(g) `scripts/verify_allergy_22.py` 신규 — 식약처 별표 22종 표시기준 갱신 검증 SOP(R8 정합) — `app/domain/allergens.py` Story 1.5 baseline 22종 lookup vs `data/guidelines/mfds-allergens-22.md` frontmatter 22종 비교 + 차이 감지 시 비-zero exit + Sentry capture — 분기 1회 운영자 수동 실행 SOP**, **(h) `app/db/models/knowledge_chunk.py` 신규 ORM — `pgvector.sqlalchemy.Vector(1536)` + `JSONB` 미사용(메타데이터는 정규 컬럼) + `__table_args__`에 UNIQUE(source, source_id, chunk_index) 제약**, **(i) 신규 도메인 예외 — `GuidelineSeedError(BalanceNoteError)` base + 3 서브클래스 (`GuidelineSeedSourceUnavailableError` 503 — 데이터 파일 미존재 / `GuidelineSeedAdapterError` 503 — chunking 또는 embedding transient 후 retry 실패 / `GuidelineSeedValidationError` 422 — frontmatter 메타데이터 검증 실패)**, **(j) `app/rag/chunking/{pdf,html}.py` — *MVP 시드 경로*는 markdown chunker만 사용 — pdf/html chunker는 *외주 인수 인터페이스 박기*만(Architecture 결정 1 정합) + 단위 테스트로 동작 검증 + 시드 경로에서 호출 X(외주 인수 클라이언트가 자체 PDF/HTML 시드 시 활성화)**, **(k) `pyproject.toml` 의존성 추가 — `pypdf>=5.1` (BSD-3, PDF 텍스트 추출) + `beautifulsoup4>=4.12` (HTML 파싱) + `langchain-text-splitters>=0.3` (RecursiveCharacterTextSplitter 공용 splitter — `langchain>=0.3` umbrella 정합) + mypy.overrides에 `pypdf.*` / `bs4.*` 추가**, **(l) Epic 3 진입 — Story 3.2 종료 후 Story 3.3(LangGraph 6노드 + AsyncPostgresSaver) 진입 가능 — `food_nutrition` (Story 3.1) + `knowledge_chunks` (본 스토리) 두 RAG 인덱스가 박혀 retrieve_nutrition + generate_feedback 노드의 1차·2차 검색 인프라 충족**의 데이터·인프라 baseline을 박는다.

부수적으로 (a) **LangGraph `generate_feedback` 노드 통합은 OUT** — 본 스토리는 *데이터 시드 + chunking 인터페이스*만, 노드 시스템 프롬프트 + 인용 패턴 후처리 + 광고 가드는 Story 3.6 책임, (b) **`knowledge_chunks` 검색 흐름(`applicable_health_goals` filtered top-K) 자체는 OUT** — 본 스토리는 *인덱스 + EXPLAIN 검증*만, retrieve guideline 노드는 Story 3.6 책임 (`app/rag/guidelines/search.py`는 본 스토리 OUT — Story 3.6 시점 작성), (c) **자동 PDF/HTML 다운로드 파이프라인은 OUT** — *수동 1회 호출* MVP 정합(epic AC #608 명시) — 운영자가 분기 1회 *원본 PDF/HTML 다운 → 수동 chunking → `data/guidelines/*.md` frontmatter 갱신* SOP 따름, 자동 파이프라인은 Vision-stage / Growth deferred, (d) **Self-RAG `evaluate_retrieval_quality` / `rewrite_query` 노드는 OUT** — Story 3.3 책임, (e) **광고 표현 가드(`domain/ad_expression_guard.py`) 정규식 패턴은 OUT** — Story 3.6 책임 (research 3.5 식약처 광고 금지 표현 표 정합), (f) **`verify_allergy_22.py` 자동 PDF 다운 + 비교는 OUT** — 본 스토리는 *lookup table vs `data/guidelines/mfds-allergens-22.md` frontmatter 비교*만 + 식약처 공식 URL 링크 hardcode + 운영자 수동 검토 SOP, 자동 PDF 파싱 비교는 Story 8(인수인계 패키지) polish, (g) **`knowledge_chunks` 행 versioning(KDRIs 2020 vs 2025 갱신본 다중 보존)은 OUT** — `published_year` 단일 컬럼 + 멱등 UPDATE 패턴만, 변경 이력 보존 + 롤백은 Growth deferred, (h) **임베딩 모델 변경 마이그레이션은 OUT** — Story 3.1 D2 정합 (`vector(1536)` 고정).

## Acceptance Criteria

> **BDD 형식 — 각 AC는 독립적 검증 가능. 모든 AC 통과 후 `Status: review`로 전환하고 code-review 워크플로우로 진입.**

1. **AC1 — `alembic 0011` 마이그레이션 — `knowledge_chunks` 테이블 + HNSW 인덱스 + GIN 인덱스 + ORM 등록**
   **Given** Story 3.1 baseline `food_nutrition` + `food_aliases` 테이블 + Epic 3 진입, **When** `cd api && uv run alembic upgrade head` 실행, **Then**:
     - **신규 테이블 `knowledge_chunks`** — 컬럼:
       - `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`,
       - `source TEXT NOT NULL` (5 enum-style 값: `MFDS` 식약처 / `MOHW` 보건복지부 KDRIs / `KSSO` 대한비만학회 / `KDA` 대한당뇨병학회 / `KDCA` 질병관리청 — DB CHECK 제약 X, application-level Pydantic 검증),
       - `source_id TEXT NOT NULL` (문서 식별자 — 예: `KDRIS-2020-AMDR`, `KSSO-2024-CH3`, `KDA-MACRO-2017`, `MFDS-ALLERGEN-22`, `KDCA-DIABETES-DIET`),
       - `chunk_index INTEGER NOT NULL` (문서 내 chunk 순번 — 0부터 시작, 멱등 키),
       - `chunk_text TEXT NOT NULL` (chunk 본문 — 단일 인용 단위),
       - `embedding vector(1536) NULL` (text-embedding-3-small — D4 부분 실패 graceful — Story 3.1 D4 정합),
       - `authority_grade TEXT NOT NULL` (`A`/`B`/`C` — research 1.2 정합 — DB CHECK 제약 X, application-level),
       - `topic TEXT NOT NULL` (`macronutrient`/`allergen`/`disease_specific`/`general` — research 2.5 권장 — DB CHECK X),
       - `applicable_health_goals TEXT[] NOT NULL DEFAULT '{}'::text[]` (`health_goal` enum 값 — `weight_loss`/`muscle_gain`/`maintenance`/`diabetes_management` — `generate_feedback` 노드의 사용자 목표별 filtered top-K 검색 키, 빈 배열은 *전 사용자 적용*),
       - `published_year INTEGER NULL` (발행연도 — 인용 패턴 *(출처: 기관명, 문서명, 연도)* 직접 주입용, 미상 시 NULL),
       - `doc_title TEXT NOT NULL` (문서 표시명 — 예: *"2020 한국인 영양소 섭취기준"* — 인용 패턴 직접 주입),
       - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` / `updated_at TIMESTAMPTZ NOT NULL DEFAULT now() ON UPDATE now()` (ORM `onupdate=now()`).
     - **`knowledge_chunks` UNIQUE 제약** — `UNIQUE(source, source_id, chunk_index)` (멱등 시드 입력 — 재실행 시 같은 source+source_id+chunk_index row 충돌 → ON CONFLICT UPDATE 분기). naming: `uq_knowledge_chunks_source_source_id_chunk_index` (Story 3.1 0010 `uq_*` 패턴 정합).
     - **`knowledge_chunks` HNSW 인덱스** — `idx_knowledge_chunks_embedding` (architecture line 293 명시 — 별 인덱스로 튜닝 자유) — `USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)` (Story 3.1 D3 정합 — 1.5K-3K 데이터 규모는 Story 3.1과 동등 권장값). **NULL embedding은 인덱싱 X** (pgvector 0.8.2 표준 — Story 3.1 정합).
     - **`knowledge_chunks` GIN 인덱스** — `idx_knowledge_chunks_applicable_health_goals` ON `applicable_health_goals` USING gin — `applicable_health_goals @> ARRAY['weight_loss']::text[]` 또는 `applicable_health_goals && ARRAY[...]` 필터 가속(architecture line 293 *"filtered top-K by applicable_health_goals"* 검증 인프라 — Story 3.6 retrieve guideline 노드 baseline). 빈 배열 row(`{}`)는 *전 사용자 적용* — `applicable_health_goals = '{}'::text[]` 또는 `array_length` IS NULL 매칭.
     - **`knowledge_chunks.source` 인덱스** — `idx_knowledge_chunks_source` ON `(source, authority_grade)` btree — `WHERE source = 'KSSO' AND authority_grade = 'A'` 패턴 가속(인용 출처 카드별 검색). composite key는 selectivity ↑ + Story 3.6 *기관별 가중치 검색* 토대.
     - **ORM 신규** — `app/db/models/knowledge_chunk.py` — declarative 등록 + `app/db/models/__init__.py`에 export. `embedding` 컬럼은 `from pgvector.sqlalchemy import Vector` import + `Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)` (Story 3.1 패턴 정합). `applicable_health_goals` 컬럼은 `Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))`. HNSW + GIN 인덱스는 ORM `__table_args__` SOT만 — 마이그레이션이 raw `op.create_index(...)`로 생성(Story 3.1 0010 패턴 정합).
     - **마이그레이션 파일 신규** — `api/alembic/versions/0011_knowledge_chunks.py` — `down_revision: str | None = "0010_food_nutrition_and_aliases"`. `upgrade`에서 `op.create_table(...)` + `op.create_unique_constraint(...)` + `op.execute("ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(1536) NULL")` + `op.create_index('idx_knowledge_chunks_embedding', ...)` HNSW + `op.create_index('idx_knowledge_chunks_applicable_health_goals', ..., postgresql_using='gin')` + `op.create_index('idx_knowledge_chunks_source', ...)` btree composite. `downgrade`에서 `op.drop_index` 3건 + `op.drop_constraint` + `op.drop_table` 역순. `vector` extension은 Story 1.1 `docker/postgres-init/01-pgvector.sql` 자동 설치(no-op 보장 — Story 3.1 0010 정합).
     - **CHECK 제약 X** — `source` / `authority_grade` / `topic` enum 검증은 application-level Pydantic + `data/guidelines/*.md` frontmatter 검증 책임 — Story 3.1 D4 정합(DB CHECK 마찰 회피).
     - **응답 wire 변경 X** — 본 스토리는 *내부 인프라*만, 라우터 응답 노출은 Story 3.3+ 책임.
     - **테스트** — `api/tests/test_knowledge_chunks_schema.py` 신규 — alembic 0011 round-trip(`upgrade head` → `downgrade 0010_food_nutrition_and_aliases` → `upgrade head`) 정상 + 테이블 + UNIQUE 제약 + HNSW 인덱스 + GIN 인덱스 + composite btree 인덱스 4건 모두 존재 검증(`SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'knowledge_chunks'` 출력에 `USING hnsw (embedding vector_cosine_ops)` + `USING gin (applicable_health_goals)` + `USING btree (source, authority_grade)` 모두 매칭).

2. **AC2 — `app/rag/chunking/__init__.py` + 공용 splitter — Chunk 데이터클래스 + 통일 인터페이스**
   **Given** epic AC line 235 *"Chunking 모듈 재사용 — 외주 인수 시 클라이언트 PDF 자동 시드 인터페이스 제공"* + Architecture 결정 1, **When** `from app.rag.chunking import Chunk, chunk_markdown, chunk_pdf, chunk_html` import, **Then**:
     - **`Chunk` 데이터클래스** — `app/rag/chunking/__init__.py` 정의:
       ```python
       @dataclass(frozen=True, slots=True)
       class Chunk:
           text: str          # chunk 본문 (max_chars 제한 적용 후)
           chunk_index: int   # 문서 내 0-based 순번
           char_start: int    # 원본 문서 내 character offset (start, inclusive)
           char_end: int      # 원본 문서 내 character offset (end, exclusive)
       ```
       `frozen=True` + `slots=True` — 불변 + 메모리 효율(50-100건 시드 메모리 부담 무시 가능).
     - **공용 splitter** — `_split_text(text: str, *, max_chars: int = 1000, overlap: int = 100) -> list[Chunk]` 내부 함수:
       - `langchain-text-splitters>=0.3` `RecursiveCharacterTextSplitter`(`["\n\n", "\n", " ", ""]` separators 기본 + 한국어 텍스트 안전치) — 단락 → 줄 → 단어 → 문자 fallback 분리. `chunk_size=max_chars`(default 1000자) + `chunk_overlap=overlap`(default 100자) — overlap으로 chunk 경계 의미 손실 회피.
       - `add_start_index=True` — RecursiveCharacterTextSplitter 표준 옵션 — `Document.metadata["start_index"]` 자동 부착. 본 모듈은 `langchain.schema.Document` 대신 자체 `Chunk`로 변환 — `text` + `chunk_index` + `char_start` + `char_end`(= `char_start + len(text)`) 매핑.
       - `length_function=len` (문자 단위 — 한국어 토큰 평균 1.5-2자/토큰 → 1000자 ≈ 500-700 tokens, OpenAI text-embedding-3-small 8K context 안전치 ≈ 12-16배 여유).
     - **`chunk_markdown(content: str, *, max_chars: int = 1000, overlap: int = 100) -> list[Chunk]`** — `app/rag/chunking/markdown.py`:
       - YAML frontmatter 분리 — `^---\n(.*?)\n---\n` 정규식 매칭 → frontmatter는 시드 모듈 별 처리 (chunker는 frontmatter *제외* body만 chunking).
       - heading-aware splitting — `langchain.text_splitter.MarkdownHeaderTextSplitter` 1차 호출 → `## ` / `### ` 단위 sub-document 분리 → 2차 `_split_text`로 max_chars cap 적용. heading 메타는 *chunk 내 prepend*(예: `"## 매크로 비율 권장\n\n탄수화물 55-65%..."`) — chunk가 standalone 인용 가능 + heading 정보 임베딩에 반영.
       - 빈 입력(content == "" or only whitespace) → 빈 리스트 반환.
     - **`chunk_pdf(content: bytes, *, max_chars: int = 1000, overlap: int = 100) -> list[Chunk]`** — `app/rag/chunking/pdf.py`:
       - `pypdf>=5.1` `PdfReader(io.BytesIO(content))` → 페이지별 `page.extract_text()` 호출 → `"\n\n".join(pages)`로 join → `_split_text` 적용 (page 경계는 `\n\n` separator로 chunking 친화).
       - 깨진 PDF / 텍스트 추출 실패 → `GuidelineSeedAdapterError("PDF text extraction failed: <reason>")` raise — 시드 경로에서는 catch + 운영자 신호 + `applicable_health_goals` 부분 시드 진행.
       - 빈 페이지(`extract_text()` returns `""`) skip.
       - 한글 폰트 + CID 매핑 깨짐 위험 — pypdf 텍스트 추출 한계 — 운영자 SOP는 *PDF 원본 → 수동 검수 → markdown 갱신*(D1 명시).
     - **`chunk_html(content: str | bytes, *, max_chars: int = 1000, overlap: int = 100) -> list[Chunk]`** — `app/rag/chunking/html.py`:
       - `beautifulsoup4>=4.12` `BeautifulSoup(content, "html.parser")` → `<script>` / `<style>` 제거 → `soup.get_text(separator="\n", strip=True)` 추출 → `_split_text` 적용.
       - frontmatter 패턴 X (HTML은 metadata가 본 시드 경로에서 *별도 인자*로 전달).
       - DOCTYPE / 잘못된 인코딩 → `GuidelineSeedAdapterError("HTML parse failed")` raise.
     - **3 chunker 통일 시그니처** — 모두 `(content, *, max_chars=1000, overlap=100) -> list[Chunk]`. 외주 인수 클라이언트가 자기 PDF/HTML/MD를 *동일 호출 방식*으로 시드 추가 가능 (Architecture 결정 1 정합).
     - **logger.info — chunking 단위** — `chunking.<format>.complete` 1줄 — `format=markdown|pdf|html` + `chunks_count` + `total_chars`. raw chunk text 노출 X(NFR-S5 정합 — 가이드라인은 공개 자료지만 통일 패턴).
     - **테스트** — 3 모듈별 단위 테스트:
       - `api/tests/rag/test_chunking_markdown.py` — 5 케이스: (1) frontmatter 제외 body chunking + heading-aware split, (2) max_chars cap 적용 + overlap 검증, (3) 빈 입력 → 빈 리스트, (4) 단일 단락(< max_chars) → 1 chunk, (5) 매우 긴 입력(10000자) → ~10 chunks + chunk_index 0..N 정합.
       - `api/tests/rag/test_chunking_pdf.py` — 4 케이스: (1) 정상 PDF(`tests/fixtures/sample-guideline.pdf` — 미니 1-2페이지 한국어 PDF) → ≥ 1 chunk + char_start/end 검증, (2) 빈 PDF(0 페이지) → 빈 리스트 또는 `GuidelineSeedAdapterError`, (3) 깨진 PDF(헤더 invalid) → `GuidelineSeedAdapterError`, (4) 페이지 경계 — 다중 페이지 PDF → `\n\n` join 검증 + chunk 경계 페이지 통합.
       - `api/tests/rag/test_chunking_html.py` — 4 케이스: (1) 정상 HTML(`<h1>제목</h1><p>본문 ...</p>`) → 텍스트만 추출, (2) `<script>`/`<style>` 제거 검증, (3) bytes 입력 → str과 동일 결과, (4) 빈 HTML → 빈 리스트.

3. **AC3 — `app/rag/guidelines/seed.py` + `data/guidelines/*.md` — 가이드라인 시드 비즈니스 + 데이터 파일**
   **Given** AC1+AC2 baseline + Story 3.1 `embed_texts` 어댑터 baseline, **When** `cd api && uv run python /app/scripts/seed_guidelines.py` 실행 (Docker `seed` 컨테이너 + 로컬 dev), **Then**:
     - **`data/guidelines/*.md` 파일 신규** — 6 파일 / 총 ≥ 50 chunks (epic AC #605 정합 50-100 chunks):
       1. **`data/guidelines/kdris-2020-amdr.md`** — KDRIs AMDR 매크로 권장 비율 (research 2.2 표 인용) — 일반 성인 + 당뇨/체중감량 옵션 분기 — frontmatter `source: MOHW`, `source_id: KDRIS-2020-AMDR`, `authority_grade: A`, `topic: macronutrient`, `applicable_health_goals: [weight_loss, muscle_gain, maintenance, diabetes_management]`, `published_year: 2020`, `doc_title: "2020 한국인 영양소 섭취기준 — AMDR 권장 비율"`. body ≥ 8 chunks.
       2. **`data/guidelines/kdris-2020-protein.md`** — 단백질 g/kg 권장(체중감량 1.2-1.6 g/kg, muscle_gain 1.6-2.2 g/kg, maintenance 0.91 g/kg) — research 2.3 표 인용 — frontmatter `source: MOHW`, `source_id: KDRIS-2020-PROTEIN`, `authority_grade: A`, `topic: macronutrient`, `applicable_health_goals: [weight_loss, muscle_gain, maintenance]`, `published_year: 2020`, `doc_title: "2020 한국인 영양소 섭취기준 — 단백질 권장량"`. body ≥ 5 chunks.
       3. **`data/guidelines/kosso-2024-weight-loss.md`** — 대한비만학회 진료지침 9판 체중감량 권고 (research 1.1 KSSO 인용) — 매크로 분배 + 단백질 25% + 칼로리 -500 kcal — frontmatter `source: KSSO`, `source_id: KSSO-2024-WEIGHT-LOSS`, `authority_grade: A`, `topic: macronutrient`, `applicable_health_goals: [weight_loss]`, `published_year: 2024`, `doc_title: "대한비만학회 비만 진료지침 9판 (2024)"`. body ≥ 10 chunks.
       4. **`data/guidelines/kda-macronutrient.md`** — 대한당뇨병학회 매크로 권고 (research 1.1 KDA Synapse PDF 인용) — 탄수화물 55-65% 또는 의학적 저탄 30-50% + 단백질 0.8-1.0 g/kg + GI 고려 — frontmatter `source: KDA`, `source_id: KDA-MACRO-2017`, `authority_grade: A`, `topic: disease_specific`, `applicable_health_goals: [diabetes_management]`, `published_year: 2017`, `doc_title: "대한당뇨병학회 다량영양소 섭취 권고안"`. body ≥ 8 chunks.
       5. **`data/guidelines/mfds-allergens-22.md`** — 식약처 별표 22종 알레르기 표시기준 (research 2.4 표 인용) — frontmatter `source: MFDS`, `source_id: MFDS-ALLERGEN-22`, `authority_grade: A`, `topic: allergen`, `applicable_health_goals: []` (전 사용자 적용), `published_year: 2024`, `doc_title: "식품 등의 표시기준 별표 — 알레르기 유발물질 22종"`. body ≥ 4 chunks. **R8 + AC9 verify 입력 — `body`에 22종 항목 명시 줄로 박음**(`scripts/verify_allergy_22.py`가 `app/domain/allergens.py` lookup vs 본 파일 frontmatter `allergens` 추가 필드 비교).
       6. **`data/guidelines/kdca-diabetes-diet.md`** — 질병관리청 국가건강정보포털 당뇨 식이요법 (research 1.1 KDCA 인용) — 일반인 안내 표현 + 식약처 광고 가드 안전 워딩 — frontmatter `source: KDCA`, `source_id: KDCA-DIABETES-DIET`, `authority_grade: A`, `topic: disease_specific`, `applicable_health_goals: [diabetes_management]`, `published_year: 2024`, `doc_title: "질병관리청 국가건강정보포털 — 당뇨환자의 식이요법"`. body ≥ 5 chunks.
       Total expected: ≥ 40 chunks (5 + 10 + 8 + 4 + 5 + 8 = 40 chunks 최소). max_chars=1000자 + overlap=100자로 chunking 시 실제 발생 chunks는 *body 길이*에 종속 — body는 *각 가이드라인 1차 출처를 직접 인용 가능한 충실 분량*으로 운영자가 작성. 50-100 chunks 분량은 *chunking 결과 누적*으로 충족.
     - **frontmatter YAML 스키마** — `app/rag/guidelines/seed.py` `_FrontmatterSchema` Pydantic 모델 검증:
       ```python
       class _FrontmatterSchema(BaseModel):
           source: Literal["MFDS", "MOHW", "KSSO", "KDA", "KDCA"]
           source_id: str  # min_length=3, ASCII + dash 허용
           authority_grade: Literal["A", "B", "C"]
           topic: Literal["macronutrient", "allergen", "disease_specific", "general"]
           applicable_health_goals: list[Literal["weight_loss", "muscle_gain", "maintenance", "diabetes_management"]]
           published_year: int | None  # ge=1990, le=2100
           doc_title: str  # min_length=5
           # 옵션 — `mfds-allergens-22.md`에만 존재
           allergens: list[str] | None = None
       ```
       검증 실패 시 `GuidelineSeedValidationError("frontmatter validation failed for {file}: {detail}")` raise — 시드 fail-fast (잘못된 메타데이터 방지).
     - **`run_guideline_seed(session: AsyncSession) -> GuidelineSeedResult`** — 시드 비즈니스 로직:
       1. `_GUIDELINE_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "guidelines"` — `data/guidelines/` 디렉토리 글로브 (`*.md`).
       2. 각 파일 읽기 → frontmatter 파싱(`PyYAML` 또는 자체 정규식 — `langchain-text-splitters`는 frontmatter 미지원이므로 자체 처리) → `_FrontmatterSchema.model_validate(frontmatter)`.
       3. body chunking — `chunk_markdown(body, max_chars=1000, overlap=100)` 호출.
       4. chunks → embedding 호출 — `openai_adapter.embed_texts([c.text for c in chunks])` (Story 3.1 D7 SDK singleton 공유). 빈 입력은 즉시 빈 리스트 반환(cost 0).
       5. `OPENAI_API_KEY` 미설정 분기 — `embed_texts`가 `MealOCRUnavailableError(503)` raise → catch → `_is_graceful_environment()` 정합 시 (`settings.environment ∈ {dev, ci, test}` + `RUN_GUIDELINE_SEED_STRICT` 미설정) → embedding NULL로 chunks 시드 진행 + warning logger.info → `GuidelineSeedResult.embeddings_skipped = True`. prod/staging 또는 strict 모드 시 → `GuidelineSeedSourceUnavailableError(503, "OPENAI_API_KEY not configured")` raise → entry point 비-zero exit.
       6. INSERT 멱등 — `INSERT INTO knowledge_chunks (source, source_id, chunk_index, chunk_text, embedding, authority_grade, topic, applicable_health_goals, published_year, doc_title) VALUES (...) ON CONFLICT (source, source_id, chunk_index) DO UPDATE SET chunk_text = EXCLUDED.chunk_text, embedding = EXCLUDED.embedding, authority_grade = EXCLUDED.authority_grade, topic = EXCLUDED.topic, applicable_health_goals = EXCLUDED.applicable_health_goals, published_year = EXCLUDED.published_year, doc_title = EXCLUDED.doc_title, updated_at = now() RETURNING (xmax = 0) AS inserted` — Story 3.1 0010 패턴 정합. `(inserted, updated)` 카운터 logger.info 출력.
       7. 시드 후 게이트 검증 — `count(*) FROM knowledge_chunks >= 40` (epic AC #605 *50-100 chunks*는 *production data*; 본 스토리 baseline은 *minimum 40 chunks* — placeholder body 분량 정합) — 미달 시 `GuidelineSeedAdapterError("knowledge_chunks seed insufficient: count={n} < 40")` raise → entry point 비-zero exit. **단 `embeddings_skipped == True` 시 게이트는 *count만*(임베딩 NULL이어도 chunks count 충족 OK)**.
     - **`GuidelineSeedResult` 데이터클래스** — `(inserted, updated, total, files_processed, embeddings_skipped: bool)` 통계.
     - **단일 파일 단위 transaction** — 파일별 INSERT batch는 *전체 한 번에* 단일 transaction (50-100 chunks는 메모리 + 트랜잭션 비용 무시 가능 — Story 3.1 D6 300건 batch 패턴 *불필요*). 파일 단위 commit으로 부분 실패 시 보존(D6).
     - **임베딩 호출 — 단일 batch** — chunks ≤ 100건 → 100건 단일 batch (Story 3.1 D6 300건 cap의 1/3 안전치). chunks > 100 시 자동 chunk + 결과 concat (Story 3.1 `embed_texts` baseline 정합).
     - **logger.info 마스킹** — chunk_text raw 출력 X (가이드라인은 공개 자료지만 통일 NFR-S5 패턴 — Story 3.1 정합) — `source` + `source_id` + `chunks_count` + `latency_ms`만 1줄.
     - **테스트** — `api/tests/rag/test_guideline_seed.py` 신규 — `embed_texts` monkeypatch + DB session 사용. 케이스: (1) 정상 시드 → ≥ 40 chunks 시드 + embedding NOT NULL, (2) **dev graceful** — `OPENAI_API_KEY` 미설정 + `ENVIRONMENT=dev` → chunks 시드 + embedding NULL + main returns 0 + warning logger captured + `embeddings_skipped == True`, (3) **prod fail-fast** — 같은 입력 + `ENVIRONMENT=prod` → `GuidelineSeedSourceUnavailableError` raise, (4) frontmatter 검증 실패(`source: INVALID`) → `GuidelineSeedValidationError`, (5) 멱등 — 동일 (source, source_id, chunk_index) 두 번째 시드 → ON CONFLICT UPDATE → DB row 동일 count + `updated_at` 갱신, (6) chunks count < 40 → `GuidelineSeedAdapterError`(test에서 monkeypatch로 1 파일만 노출).

4. **AC4 — `scripts/seed_guidelines.py` + `bootstrap_seed.py` 갱신 + Docker 자동 시드**
   **Given** AC3 baseline + Story 3.1 `bootstrap_seed.py` baseline + Docker `seed` 서비스 wired, **When** `docker compose up` 실행, **Then**:
     - **`scripts/seed_guidelines.py` entry point 신규** — `if __name__ == "__main__": sys.exit(main())` — `main()` returns int (0 success / 1 failure). main()은 `app.rag.guidelines.seed.run_guideline_seed()` 호출 + `(inserted, updated, total, files_processed, embeddings_skipped)` 통계 stdout 출력. Story 3.1 `seed_food_db.py` 패턴 정합:
       ```
       [seed_guidelines] knowledge_chunks: inserted={n} updated={n} total={n} files_processed={n}
       [seed_guidelines] WARN — embeddings skipped (OPENAI_API_KEY missing or graceful env)  # 조건부
       ```
     - **graceful 분기** — Story 3.1 D9 패턴 정합:
       - **prod / staging**: `OPENAI_API_KEY` 미설정 → `GuidelineSeedSourceUnavailableError` raise → 비-zero exit + Sentry capture(`scope.set_tag("seed", "guidelines_total_failure")`) + stderr stack trace.
       - **dev / ci / test**: `OPENAI_API_KEY` 미설정 → embedding NULL chunks 시드 + main returns 0 + stdout WARN — 외주 인수 클라이언트 첫 부팅 영업 demo 보호.
       - **dev strict opt-in** — `RUN_GUIDELINE_SEED_STRICT=1` 환경 변수 시 prod와 동일 fail-fast (12-factor 정합 — Story 3.1 `_STRICT_TRUTHY = {"1","true","yes","on"}` 패턴 재활용).
     - **`scripts/bootstrap_seed.py` 갱신** — Story 3.1 baseline은 `seed_food_db.main()`만 호출 — 본 스토리는 *food → guidelines 순차 호출* 추가:
       ```python
       def main() -> int:
           try:
               from seed_food_db import main as seed_food_db_main
               from seed_guidelines import main as seed_guidelines_main

               food_exit = seed_food_db_main()
               if food_exit != 0:
                   return food_exit
               guidelines_exit = seed_guidelines_main()
               if guidelines_exit != 0:
                   return guidelines_exit
               return 0
           except Exception:
               # ...stack trace + Sentry...
               return 1
       ```
       food 시드 실패 시 guidelines 시드 skip — 두 시드는 *독립 의존성*이지만 컨테이너 fail-fast 신호 통일 (Story 3.1 패턴 정합 — 첫 실패 시 즉시 비-zero exit).
     - **Docker `seed` 컨테이너 — 자동 시드** — 현 `docker-compose.yml` `seed` 서비스 변경 X — `command: ["uv", "run", "python", "/app/scripts/bootstrap_seed.py"]` 그대로 활용. `depends_on: api(service_healthy)` (alembic upgrade head 완료 후 실행 보장 — Story 1.1 baseline). seed 컨테이너 종료 시 `restart: "no"` (Story 3.1 정합).
     - **`docker compose up` 1-cmd** — `postgres` healthy → `api` (alembic 0011 upgrade head 완료) → `seed` (food + guidelines 시드 + exit 0) — 첫 cold start 시 시드 완료까지 ~5분 (식약처 OpenAPI 1500건 + 가이드라인 ~50 chunks 임베딩 + INSERT). epic AC #605 정합 — *"`docker compose up`만으로 자동 시드"* (epic AC #4 + Story 3.1 AC #5 정합).
     - **재 부팅 시 멱등** — `docker compose down && up` → seed 컨테이너 재실행 → food + guidelines 모든 INSERT가 ON CONFLICT UPDATE 분기 → DB row 변경 0건 (timestamp만 갱신).
     - **테스트 — `api/tests/integration/test_bootstrap_seed.py` 갱신** — Story 3.1 baseline 5 케이스 + 본 스토리 2 케이스 추가:
       - 케이스 6 — **정상 시드 — food + guidelines 모두 성공** — `food_nutrition` ≥ 1500 + `food_aliases` ≥ 50 + `knowledge_chunks` ≥ 40 + main returns 0.
       - 케이스 7 — **graceful 시드 — food OK + guidelines OPENAI_API_KEY 미설정 + dev** — `food_nutrition` ≥ 1500 + `knowledge_chunks` ≥ 40 (embedding NULL) + main returns 0 + WARN logger captured.
       Story 3.1 baseline 5 케이스(정상/dev graceful food/prod fail-fast/dev strict/멱등)는 그대로 유지 — `embed_texts` monkeypatch에서 *guidelines 임베딩만* 분리 컨트롤 가능하도록 fixture 갱신 필요.

5. **AC5 — HNSW 검색 + GIN `applicable_health_goals` 필터 적용 top-K 가능 (epic AC #607)**
   **Given** AC1+AC3 baseline 시드 ≥ 40 chunks + HNSW + GIN 인덱스, **When** 다음 패턴 쿼리 실행, **Then**:
     - **HNSW + GIN composite 검색 패턴** — Story 3.6 `generate_feedback` 노드의 사용자 목표별 filtered top-K 베이스라인:
       ```sql
       SELECT id, source, source_id, doc_title, published_year, chunk_text,
              embedding <=> :query_embedding AS distance
       FROM knowledge_chunks
       WHERE embedding IS NOT NULL
         AND (applicable_health_goals @> ARRAY[:health_goal]::text[]
              OR applicable_health_goals = '{}'::text[])
       ORDER BY embedding <=> :query_embedding
       LIMIT 5;
       ```
       - `WHERE applicable_health_goals @> ARRAY[:health_goal]::text[]` — 사용자 목표별 chunks 필터 (GIN 인덱스 활용).
       - `OR applicable_health_goals = '{}'::text[]` — 빈 배열은 *전 사용자 적용* (식약처 22종 알레르기 등 — 모든 사용자에게 노출).
       - `<=>` cosine distance + `ORDER BY ... LIMIT 5` — HNSW 인덱스 활용 (Story 3.1 D3 정합).
     - **EXPLAIN 검증** — `EXPLAIN (ANALYZE, BUFFERS) ...` 출력에 `Index Scan using idx_knowledge_chunks_embedding` (HNSW) + `Bitmap Index Scan on idx_knowledge_chunks_applicable_health_goals` (GIN) 또는 `Index Scan` 명시 확인 — `Sequential Scan` 아님.
     - **본 스토리 검증** — 검색 흐름 자체는 Story 3.6 책임 (`app/rag/guidelines/search.py`는 본 스토리 OUT). 본 스토리는 *인덱스 존재 + EXPLAIN 패턴 검증*만 — `idx_knowledge_chunks_embedding` + `idx_knowledge_chunks_applicable_health_goals` + `idx_knowledge_chunks_source` 모두 인덱스 활용 가능 보증.
     - **응답 시간 목표** — Story 3.1 NFR-P6(`food_nutrition` ≤ 200ms p95)에 종속. `knowledge_chunks` 50-100건은 `food_nutrition` 1500건 대비 1/15-1/30 — 동일 HNSW 파라미터로 ≤ 50ms 안전치 (NFR-P6 별 KPI는 Story 3.6 측정 — 본 스토리는 인덱스 활용 보증).
     - **테스트** — `api/tests/rag/test_knowledge_chunk_search.py` 신규 — *integration smoke*만 (CI에서 `RUN_PERF_TEST` 환경 변수 시점에만 실행 — Story 3.1 패턴 정합). 케이스: (1) `EXPLAIN` 출력에 `idx_knowledge_chunks_embedding` 사용 확인, (2) `EXPLAIN` 출력에 `idx_knowledge_chunks_applicable_health_goals` (GIN) 사용 확인 — `applicable_health_goals @> ARRAY['weight_loss']` 필터 적용 시, (3) 빈 배열 row(`{}`) 매칭 OR 분기 동작 검증, (4) 100회 검색 latency 측정 → p95 < 200ms 통과 (skip 디폴트). CI 환경은 *시드 + 임베딩 + Postgres 모두 가짜* 정합으로 perf 측정 X.
     - **OUT — 검색 흐름 자체는 Story 3.6 책임** — `app/rag/guidelines/search.py` + `generate_feedback` 노드 시스템 프롬프트 + 인용 패턴 후처리는 모두 Story 3.6 AC.

6. **AC6 — 신규 도메인 예외 — `GuidelineSeedError` + 3 서브클래스**
   **Given** Story 3.1 `FoodSeedError` 카탈로그 패턴 + 본 스토리 가이드라인 시드 도입, **When** 가이드라인 시드 모듈 또는 chunking 모듈이 실패, **Then**:
     - **`app/core/exceptions.py` 등재** — `FoodSeedError` 패턴 정합 — `GuidelineSeedError(BalanceNoteError)` base + 3 서브클래스:
       - `GuidelineSeedSourceUnavailableError(GuidelineSeedError)`: `status=503`, `code="guideline_seed.source_unavailable"`, `title="Guideline seed source unavailable"` — `OPENAI_API_KEY` 미설정 / `data/guidelines/` 디렉토리 미존재 / 파일 0건 케이스.
       - `GuidelineSeedAdapterError(GuidelineSeedError)`: `status=503`, `code="guideline_seed.adapter_error"`, `title="Guideline seed adapter failure"` — chunking 실패(PDF parse / HTML parse) / OpenAI embeddings transient 후 retry 실패 / chunks count < 40 게이트 실패.
       - `GuidelineSeedValidationError(GuidelineSeedError)`: `status=422`, `code="guideline_seed.validation_failed"`, `title="Guideline seed frontmatter validation failed"` — `_FrontmatterSchema` Pydantic 검증 실패 (잘못된 source / authority_grade / topic enum 값).
     - **`GuidelineSeedError` base** — `status=503`, `code="guideline_seed.error"`, `title="Guideline seed error"` — 직접 raise 회피 (서브클래스만 사용).
     - **라우터 노출 X** — 본 스토리는 *시드 시점 예외*만, FastAPI 라우터에 노출 X (시드 스크립트가 자체 catch + 비-zero exit + Sentry capture). RFC 7807 변환은 정의만 — Story 3.6 retrieve guideline 노드가 503 raise 시 main.py 핸들러가 자동 변환.
     - **테스트** — `api/tests/test_guideline_seed_exceptions.py` 신규 — 3 예외 instantiate + `to_problem(instance="/v1/seed")` 호출 → status/code/title 단언. ProblemDetail wire 형식 검증 (Story 3.1 `test_food_seed_exceptions.py` 패턴 정합).

7. **AC7 — `scripts/verify_allergy_22.py` 신규 — 식약처 22종 갱신 검증 SOP (epic AC #5 + R8)**
   **Given** Story 1.5 `app/domain/allergens.py` 22종 lookup baseline + research 2.4 식약처 별표 22종 + epic AC line 609, **When** `cd api && uv run python /app/scripts/verify_allergy_22.py` 실행 (운영자 분기 1회 SOP), **Then**:
     - **3가지 검증 단계**:
       1. **Lookup 일치 검증** — `app/domain/allergens.py`의 22종 enum/list vs `data/guidelines/mfds-allergens-22.md` frontmatter `allergens: list[str]` 22 항목 1:1 매칭. 차이 발견 시 stderr 출력 + 비-zero exit. **두 SOT가 분리되어 있어** lookup이 코드/PR 게이트로 보호되고 frontmatter는 시드 RAG 컨텍스트로 정합 (Story 1.5 + 본 스토리 정합).
       2. **공식 URL 링크 hardcode** — `MFDS_ALLERGEN_REFERENCE_URLS: Final[dict[str, str]]` 모듈 const — research 1.1 / 2.4 인용:
          ```python
          MFDS_ALLERGEN_REFERENCE_URLS: Final[dict[str, str]] = {
              "official_law_attachment": "https://www.law.go.kr/LSW/flDownload.do?gubun=&flSeq=42533884&bylClsCd=110201",
              "foodsafetykorea_guide": "https://www.foodsafetykorea.go.kr/portal/board/boardDetail.do?menu_no=3120&menu_grp=MENU_NEW01&bbs_no=bbs001&ntctxt_no=1091412",
              "mfds_pdf": "https://www.mfds.go.kr/brd/m_512/down.do?brd_id=plc0060&seq=31242&data_tp=A&file_seq=1",
          }
          ```
          stdout 출력 — *"운영자 SOP — 위 3 URL 다운로드 후 22종 항목과 비교, 차이 발견 시 (1) `app/domain/allergens.py` 갱신 PR + (2) `data/guidelines/mfds-allergens-22.md` frontmatter `allergens` 갱신 PR + (3) `verify_allergy_22.py` 재실행 통과 확인"*.
       3. **분기 1회 권장 cron 안내** — 본 스크립트는 `crontab` 또는 GitHub Actions `schedule:` 자동 실행 *지원 X* (수동 SOP) — stdout 마지막 줄에 *"분기 1회 (3월 / 6월 / 9월 / 12월) 운영자 수동 실행 권장 — Story 8 polish 시점에 GHA cron 자동화 검토"* 안내 (research 2.4 `> 주의 (2025-2026 업데이트 추적 필요)` 정합).
     - **stdout 출력 패턴** — `[verify_allergy_22] check 1/3: lookup vs guideline frontmatter — OK (22 items match)` / `[verify_allergy_22] check 2/3: official URLs printed — see above` / `[verify_allergy_22] check 3/3: quarterly manual review reminder — printed`.
     - **자동 PDF 파싱 비교 OUT** — 식약처 별표 PDF 자동 다운 + parsing + 비교는 Story 8 polish (운영 자동화 — 본 스토리는 baseline SOP만).
     - **테스트** — `api/tests/integration/test_verify_allergy_22.py` 신규 — subprocess 실행 + stdout 캡처. 케이스: (1) lookup vs frontmatter 일치 → exit 0 + stdout *"OK (22 items match)"* 포함, (2) `data/guidelines/mfds-allergens-22.md` frontmatter `allergens` 누락(monkeypatch 또는 임시 파일) → exit 1 + stderr 차이 출력, (3) `app/domain/allergens.py`에 23번째 항목 추가(monkeypatch) → exit 1 (lookup 25 vs frontmatter 22 차이 검출).

8. **AC8 — `pyproject.toml` 의존성 추가 + mypy.overrides 갱신**
   **Given** Story 3.1 baseline `pgvector>=0.3` + `openai>=1.55` + `tenacity>=9.0` + `langchain>=0.3` + `httpx>=0.28`, **When** `cd api && uv sync` 실행, **Then**:
     - **`api/pyproject.toml`에 추가**:
       - `pypdf>=5.1` — PDF 텍스트 추출 (BSD-3 라이선스, 가벼움, AGPL `pymupdf` 회피).
       - `beautifulsoup4>=4.12` — HTML 파싱 (MIT 라이선스).
       - `langchain-text-splitters>=0.3` — `RecursiveCharacterTextSplitter` + `MarkdownHeaderTextSplitter` 공용 splitter (`langchain>=0.3` umbrella 정합 — Story 1.1 baseline에서 langchain 메인 패키지는 등재되어 있지만 text-splitters는 별 패키지로 분리).
       - `pyyaml>=6.0` — YAML frontmatter 파싱 (이미 langchain의 transitive 의존성일 가능성 — 명시 등재로 직접 의존성 표시).
     - **`[[tool.mypy.overrides]]` 갱신** — Story 1.1 baseline `module = ["jose.*", "passlib.*", "pgvector.*", "slowapi.*", "apscheduler.*", "google.*", "boto3.*", "botocore.*"]`에 추가:
       ```toml
       [[tool.mypy.overrides]]
       module = ["jose.*", "passlib.*", "pgvector.*", "slowapi.*", "apscheduler.*", "google.*", "boto3.*", "botocore.*", "pypdf.*", "bs4.*", "langchain_text_splitters.*", "yaml.*"]
       ignore_missing_imports = true
       ```
       `pypdf` / `bs4` / `langchain_text_splitters` / `yaml`은 type stubs 미제공 또는 부분 제공 — `ignore_missing_imports = true`로 mypy strict 통과 보장 (Story 3.1 `pgvector.*` 패턴 정합).
     - **lock 파일 갱신** — `cd api && uv lock` (또는 `uv sync`)으로 `uv.lock` 갱신 + commit.
     - **dependency conflict 검증** — `langchain-text-splitters>=0.3`은 `langchain>=0.3` umbrella + `langchain-core` 정합 — 충돌 0 검증 (`uv sync` 통과 확인).

9. **AC9 — `.env.example` + `data/guidelines/README.md` 갱신 — 환경 변수 + 가이드라인 자료 갱신 SOP**
   **Given** Story 3.1 baseline `.env.example` + 본 스토리 가이드라인 시드 도입 + 분기 갱신 SOP 필요, **When** 외주 인수 클라이언트 또는 신규 dev가 가이드라인 자료 갱신, **Then**:
     - **`.env.example` 갱신** — `OPENAI_API_KEY=` 주석 갱신:
       ```
       # OpenAI API key — Story 2.3 (OCR Vision) + Story 3.1 (text-embedding-3-small 음식 시드)
       # + Story 3.2 (text-embedding-3-small 가이드라인 시드).
       # 미설정 시 dev/ci/test 환경은 graceful 진행 (embedding NULL),
       # prod/staging 또는 RUN_GUIDELINE_SEED_STRICT=1 시 비-zero exit + Sentry capture.
       OPENAI_API_KEY=

       # Story 3.2 — 가이드라인 시드 strict opt-in (dev에서 prod와 동일 fail-fast 강제)
       # 1/true/yes/on (대소문자 무시) 시 활성화. CI 게이트에서 검증 시 권장.
       RUN_GUIDELINE_SEED_STRICT=
       ```
     - **`api/data/guidelines/README.md` 신규** — 5 섹션:
       1. **자료 갱신 SOP — 분기 1회 (KDRIs 2025+ / KSSO 9판+ / KDA 2024+ 갱신 시점)** — 운영자 절차 5단계: (a) research 1.1 1차 자료 인덱스 URL에서 PDF/HTML 다운, (b) 한글 PDF는 *수동 텍스트 추출 + 검수*(pypdf 한글 폰트 깨짐 위험 — 운영자 검수 필수), (c) 추출 텍스트 → `data/guidelines/{source}-{slug}.md` frontmatter + body 갱신, (d) `cd api && uv run python /app/scripts/seed_guidelines.py` 실행하여 멱등 시드 검증(`OPENAI_API_KEY` 설정), (e) PR + ruff/mypy/pytest 통과 + master 머지 → prod 자동 배포 시 시드 컨테이너 자동 갱신.
       2. **자료 인덱스 — 6 파일 + frontmatter 표준** — `data/guidelines/*.md` 파일별 `source` / `source_id` / `authority_grade` / `topic` / `applicable_health_goals` / `published_year` / `doc_title` 표 (research 1.1 정합).
       3. **외주 인수 클라이언트 — 자체 PDF 시드 추가 SOP** — 3 경로:
          - **경로 A — Markdown 변환 + frontmatter (권장)**: 클라이언트 PDF → 운영자 수동 chunking → `data/guidelines/<client>-<slug>.md` 추가 → `seed_guidelines.py` 실행 → 멱등 시드 (PR 게이트 + ruff/mypy/pytest 보호).
          - **경로 B — `app/rag/chunking/pdf.py` 자동 chunking (외주 인수 인터페이스 토대)**: `from app.rag.chunking import chunk_pdf; chunks = chunk_pdf(pdf_bytes); ...` — 클라이언트가 자체 자동 파이프라인에서 호출. *본 MVP는 호출 X* (epic AC #608 *수동 1회 호출* 정합) — 외주 인수 후 *자동 시드 파이프라인*으로 활성화 (Architecture 결정 1).
          - **경로 C — psql 직접 INSERT (즉시 영업 demo)**: `psql -c "INSERT INTO knowledge_chunks (source, source_id, chunk_index, chunk_text, ...) VALUES (...) ON CONFLICT DO UPDATE ..."` — 1회성 demo 즉시 추가. Story 3.1 `food_aliases` D10 패턴 정합.
       4. **자료 신뢰 등급 가이드 (research 1.2 인용)** — A급(1차 공식 — KDRIs PDF / 학회 진료지침 / KDCA 포털) / B급(학술/2차) / C급(참고). 본 시드 baseline은 *모두 A급*으로 박음 — B/C는 future expansion.
       5. **`verify_allergy_22.py` 분기 SOP 안내 (R8 정합)** — *"식약처 22종 갱신 시 위 SOP + `verify_allergy_22.py` 통과 확인"* + script 실행 명령어 + 3 공식 URL.
     - **`README.md` Quick start 갱신** — Story 3.1 baseline 시드 1단락 후 추가 1단락 — *"`docker compose up`으로 첫 부팅 시 식약처 OpenAPI 음식 시드(Story 3.1) + 가이드라인 chunks 시드(Story 3.2 — 50-100 chunks, KDRIs/KSSO/KDA/MFDS/KDCA)도 함께. `OPENAI_API_KEY` 미설정 시 dev 환경은 embedding NULL graceful, prod/staging은 fail-fast. 분기 1회 자료 갱신은 `data/guidelines/README.md` SOP 따름."*

10. **AC10 — 테스트 게이트 — 백엔드 pytest + ruff + mypy 통과 + Story 3.1 baseline 282 케이스 회귀 0건**
    **Given** Story 3.1 CR 후 baseline 282 passed / 1 skipped + 본 스토리 신규 테스트 ~30 케이스, **When** `cd api && uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy .`, **Then**:
     - **신규 테스트 ≥ 30 케이스**:
       - `test_knowledge_chunks_schema.py` — alembic 0011 round-trip + UNIQUE + HNSW + GIN + composite btree 인덱스 4건 검증 (4 케이스).
       - `test_guideline_seed_exceptions.py` — 3 예외 ProblemDetail 단언 (3 케이스).
       - `rag/test_chunking_markdown.py` — 5 케이스 (frontmatter 분리 + heading-aware + max_chars + 빈 입력 + chunk_index 정합).
       - `rag/test_chunking_pdf.py` — 4 케이스 (정상 fixture + 빈 PDF + 깨진 PDF + 다중 페이지).
       - `rag/test_chunking_html.py` — 4 케이스 (정상 + script/style 제거 + bytes 입력 + 빈 HTML).
       - `rag/test_guideline_seed.py` — 6 케이스 (정상 + dev graceful + prod fail-fast + frontmatter 검증 실패 + 멱등 + count < 40).
       - `rag/test_knowledge_chunk_search.py` — 4 케이스 (HNSW EXPLAIN + GIN EXPLAIN + 빈 배열 OR 분기 + perf skip).
       - `integration/test_bootstrap_seed.py` 갱신 — Story 3.1 baseline 5 케이스 + 본 스토리 2 케이스 (food + guidelines 정상 + graceful 시드).
       - `integration/test_verify_allergy_22.py` — 3 케이스 (lookup 일치 + frontmatter 누락 + lookup 추가 차이).
     - **회귀 0건** — Story 3.1 CR 후 baseline 282 passed / 1 skipped 모두 통과 (alembic 0011 영향 X — 신규 테이블만, 기존 `food_nutrition`/`food_aliases` 테이블 무영향 + `bootstrap_seed.py` 갱신은 `seed_guidelines` 추가 호출만 — Story 3.1 5 케이스 모두 동일 동작 보장 — graceful flag flag 분리 fixture 정합).
     - **coverage** — 본 스토리 신규 코드 ≥ 70% (NFR-M1 정합 — Story 3.1 84.21% baseline 유지).
     - **ruff/format/mypy clean** — 본 스토리 신규 모듈 모두 lint/type clean. mypy.overrides 갱신(`pypdf.*` / `bs4.*` / `langchain_text_splitters.*` / `yaml.*` 추가) 정합.
     - **OpenAPI 클라이언트 재생성 X** — 본 스토리는 *내부 인프라*만, 라우터 응답 변경 X — `mobile/lib/api-client.ts` / `web/src/lib/api-client.ts` 갱신 0건 (Story 3.6+ 책임).

11. **AC11 — smoke 검증 시나리오 (사용자 별도 수행 권장)**
    **Given** AC1~AC10 통과 + 로컬 Docker 환경, **When** 다음 5 시나리오 실행, **Then**:
     - **시나리오 1 — 정상 시드 부팅 (food + guidelines 모두)**:
       - `docker compose down -v && docker compose up` → seed 컨테이너 ~5분 후 exit 0.
       - `docker exec balancenote-postgres psql -U app -d app -c "SELECT count(*) FROM knowledge_chunks;"` ≥ 40.
       - `docker exec balancenote-postgres psql -U app -d app -c "SELECT source, count(*) FROM knowledge_chunks GROUP BY source ORDER BY source;"` 출력에 5종 source 모두 (`KDA`/`KDCA`/`KSSO`/`MFDS`/`MOHW`) 1건 이상 노출.
       - `docker exec balancenote-postgres psql -U app -d app -c "SELECT indexdef FROM pg_indexes WHERE tablename='knowledge_chunks';"` 출력에 `USING hnsw` + `vector_cosine_ops` + `USING gin` + `applicable_health_goals` 모두 포함.
     - **시나리오 2 — `OPENAI_API_KEY` 미설정 + dev graceful (외주 인수 첫 부팅)**:
       - `.env`에서 `OPENAI_API_KEY=`(빈) + `ENVIRONMENT=dev` → `docker compose down -v && up` → seed 컨테이너 exit 0 + stdout WARN(`[seed_guidelines] WARN — embeddings skipped (OPENAI_API_KEY missing or graceful env)`).
       - `docker exec balancenote-postgres psql -U app -d app -c "SELECT count(*) FROM knowledge_chunks WHERE embedding IS NULL;"` ≥ 40 (graceful — chunks는 시드되었지만 embedding NULL).
       - `docker exec balancenote-postgres psql -U app -d app -c "SELECT count(*) FROM knowledge_chunks;"` ≥ 40.
       - **prod 동등 fail-fast 검증**: `ENVIRONMENT=prod RUN_GUIDELINE_SEED_STRICT=1 uv run python /app/scripts/seed_guidelines.py` → 비-zero exit + stderr stack trace + `GuidelineSeedSourceUnavailableError`.
     - **시나리오 3 — 멱등 재 부팅**:
       - 시나리오 1 후 `docker compose restart seed` → seed 컨테이너 재실행 → exit 0 + DB row count 변경 0건 + `knowledge_chunks.updated_at`만 갱신.
     - **시나리오 4 — HNSW + GIN 인덱스 활용 검증**:
       - `psql` 진입 → `EXPLAIN (ANALYZE, BUFFERS) SELECT id, source, doc_title, chunk_text, embedding <=> '[0.1, ..., 0.0]'::vector(1536) AS dist FROM knowledge_chunks WHERE embedding IS NOT NULL AND (applicable_health_goals @> ARRAY['weight_loss']::text[] OR applicable_health_goals = '{}'::text[]) ORDER BY embedding <=> '[...]'::vector(1536) LIMIT 5;` 출력에 `Index Scan using idx_knowledge_chunks_embedding` (HNSW) + GIN 인덱스 활용 명시 + 응답 < 200ms.
     - **시나리오 5 — `verify_allergy_22.py` SOP 통과**:
       - `cd api && uv run python /app/scripts/verify_allergy_22.py` → exit 0 + stdout *"check 1/3: lookup vs guideline frontmatter — OK (22 items match)"* + 3 공식 URL stdout + 분기 cron 안내 stdout.
     - **smoke 검증 게이트 X** — 본 AC는 *사용자 수동 검증 권장*. 백엔드 게이트(AC10) + 단위·통합 테스트로 *코드 정합성 + 회귀 차단*은 baseline 충족.

## Tasks / Subtasks

### Task 1 — alembic 0011 마이그레이션 + ORM 신규 (AC: #1)

- [x] `api/alembic/versions/0011_knowledge_chunks.py` 신규 — `down_revision = "0010_food_nutrition_and_aliases"` + 테이블 + UNIQUE + HNSW + GIN + composite btree 인덱스 + downgrade 역순.
- [x] `api/app/db/models/knowledge_chunk.py` 신규 — `from pgvector.sqlalchemy import Vector` + `embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)` + `applicable_health_goals: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))` + `__table_args__`에 `UniqueConstraint("source", "source_id", "chunk_index", name="uq_knowledge_chunks_source_source_id_chunk_index")`.
- [x] `api/app/db/models/__init__.py` 갱신 — `from app.db.models.knowledge_chunk import KnowledgeChunk` + `__all__` 추가.
- [x] `api/tests/test_knowledge_chunks_schema.py` 신규 — alembic round-trip + UNIQUE + HNSW + GIN + composite btree 인덱스 존재 검증 (4 케이스).
- [x] `cd api && uv run alembic upgrade head` 로컬 검증 + `alembic downgrade 0010_food_nutrition_and_aliases` + `alembic upgrade head` 라운드트립 정상.

### Task 2 — 신규 도메인 예외 등재 (AC: #6)

- [x] `api/app/core/exceptions.py` 갱신 — `GuidelineSeedError(BalanceNoteError)` base + 3 서브클래스(`GuidelineSeedSourceUnavailableError`/`GuidelineSeedAdapterError`/`GuidelineSeedValidationError`) — Story 3.1 `FoodSeedError` 카탈로그 패턴 정합.
- [x] `api/tests/test_guideline_seed_exceptions.py` 신규 — 3 예외 instantiate + `to_problem` 호출 → status/code/title 단언 (3 케이스).

### Task 3 — `pyproject.toml` 의존성 추가 (AC: #8)

- [x] `api/pyproject.toml` 갱신 — `pypdf>=5.1` + `beautifulsoup4>=4.12` + `langchain-text-splitters>=0.3` + `pyyaml>=6.0` 등재.
- [x] `[[tool.mypy.overrides]]` 갱신 — `pypdf.*` / `bs4.*` / `langchain_text_splitters.*` / `yaml.*` 추가 (`ignore_missing_imports = true`).
- [x] `cd api && uv sync` 실행 + `uv.lock` 갱신 + commit.
- [x] dependency conflict 검증 — `langchain-text-splitters` ↔ `langchain` 호환 확인.

### Task 4 — `app/rag/chunking/` 3-format 재사용 모듈 (AC: #2)

- [x] `api/app/rag/chunking/__init__.py` 신규 — `Chunk` 데이터클래스(`text`/`chunk_index`/`char_start`/`char_end`) + 공용 `_split_text` (RecursiveCharacterTextSplitter wrapper).
- [x] `api/app/rag/chunking/markdown.py` 신규 — `chunk_markdown` 함수 — frontmatter 제외 body chunking + heading-aware split (`MarkdownHeaderTextSplitter`).
- [x] `api/app/rag/chunking/pdf.py` 신규 — `chunk_pdf` 함수 — `pypdf.PdfReader` 텍스트 추출 + 페이지 join + `_split_text`.
- [x] `api/app/rag/chunking/html.py` 신규 — `chunk_html` 함수 — `BeautifulSoup` 텍스트 추출 + `_split_text`.
- [x] `api/tests/rag/test_chunking_markdown.py` 신규 — 5 케이스 (frontmatter 분리 + heading-aware + max_chars + 빈 입력 + chunk_index).
- [x] `api/tests/rag/test_chunking_pdf.py` 신규 — 4 케이스 (정상 fixture + 빈 PDF + 깨진 PDF + 다중 페이지).
- [x] `api/tests/rag/test_chunking_html.py` 신규 — 4 케이스 (정상 + script/style 제거 + bytes 입력 + 빈 HTML).
- [x] `api/tests/fixtures/sample-guideline.pdf` (~10KB, 1-2 페이지 한국어) + `api/tests/fixtures/sample-guideline.html` 바이너리·텍스트 fixture commit. **PDF fixture 생성 가이드** — 운영자가 1회성 로컬에서 (a) Word/Pages로 한국어 1-2 페이지 더미 가이드라인 텍스트 작성 → (b) PDF export → (c) `api/tests/fixtures/sample-guideline.pdf`로 commit. 또는 `python -c "from reportlab.pdfgen import canvas; ..."` 1회 스크립트 실행 후 결과만 commit (reportlab은 *dev dep로 추가 X* — 1회성 외부 도구). HTML fixture는 `<html><head><style>...</style></head><body><script>...</script><h1>제목</h1><p>본문</p></body></html>` 형태 텍스트 파일 직접 작성.

### Task 5 — `data/guidelines/` 데이터 파일 + `app/rag/guidelines/seed.py` 시드 비즈니스 (AC: #3)

- [x] `api/data/guidelines/kdris-2020-amdr.md` 신규 — KDRIs AMDR 매크로 권장 비율 + frontmatter (≥ 8 chunks 분량).
- [x] `api/data/guidelines/kdris-2020-protein.md` 신규 — 단백질 g/kg 권장 + frontmatter (≥ 5 chunks 분량).
- [x] `api/data/guidelines/kosso-2024-weight-loss.md` 신규 — 대한비만학회 체중감량 권고 + frontmatter (≥ 10 chunks 분량).
- [x] `api/data/guidelines/kda-macronutrient.md` 신규 — 대한당뇨병학회 매크로 권고 + frontmatter (≥ 8 chunks 분량).
- [x] `api/data/guidelines/mfds-allergens-22.md` 신규 — 식약처 22종 알레르기 + frontmatter `allergens: [...]` 22 항목 (≥ 4 chunks 분량) — `verify_allergy_22.py` 입력.
- [x] `api/data/guidelines/kdca-diabetes-diet.md` 신규 — 질병관리청 당뇨 식이요법 + frontmatter (≥ 5 chunks 분량).
- [x] `api/app/rag/guidelines/__init__.py` + `api/app/rag/guidelines/seed.py` 신규 — `_FrontmatterSchema` Pydantic 모델 + `run_guideline_seed(session)` + `GuidelineSeedResult` 데이터클래스 + dev graceful 분기(`_is_strict_mode`/`_is_graceful_environment` Story 3.1 패턴 재활용 — 또는 공용 utils로 추출 검토).
- [x] `api/tests/rag/test_guideline_seed.py` 신규 — 6 케이스 (정상 + dev graceful + prod fail-fast + frontmatter 검증 실패 + 멱등 + count < 40).

### Task 6 — `scripts/seed_guidelines.py` entry + `bootstrap_seed.py` 갱신 (AC: #4)

- [x] `scripts/seed_guidelines.py` 신규 — `main() -> int` (run_guideline_seed 호출 + `sys.exit`) + 통계 stdout 출력 + Story 3.1 `seed_food_db.py` Sentry capture 패턴 정합.
- [x] `scripts/bootstrap_seed.py` 갱신 — Story 3.1 baseline `seed_food_db.main()` 직후 `seed_guidelines.main()` 호출 추가 (food → guidelines 순차).
- [x] `api/tests/integration/test_bootstrap_seed.py` 갱신 — Story 3.1 baseline 5 케이스 유지 + 신규 2 케이스 (food + guidelines 정상 시드 + graceful guidelines 시드).
- [x] `embed_texts` monkeypatch fixture 분리 — *food와 guidelines 임베딩을 별도 컨트롤* 가능하도록(Story 3.1 baseline graceful 시나리오 보존).

### Task 7 — HNSW + GIN 검색 perf 검증 (AC: #5)

- [x] `api/tests/rag/test_knowledge_chunk_search.py` 신규 — 4 케이스 (HNSW EXPLAIN + GIN EXPLAIN + 빈 배열 OR 분기 + perf p95 [skip 디폴트]).
- [x] EXPLAIN 출력에 `Index Scan using idx_knowledge_chunks_embedding` (HNSW) + `Bitmap Index Scan on idx_knowledge_chunks_applicable_health_goals` (GIN) 명시 확인.

### Task 8 — `scripts/verify_allergy_22.py` 신규 + `data/guidelines/README.md` 자료 SOP (AC: #7, #9)

- [x] `scripts/verify_allergy_22.py` 신규 — 3 단계 검증 (lookup vs frontmatter + 공식 URL hardcode + 분기 cron 안내).
- [x] `api/data/guidelines/README.md` 신규 — 5 섹션 (자료 갱신 SOP + 자료 인덱스 + 외주 alias 추가 3 경로 + 신뢰 등급 + verify SOP 안내).
- [x] `.env.example` 갱신 — `OPENAI_API_KEY` 주석 갱신 + `RUN_GUIDELINE_SEED_STRICT` opt-in 명시.
- [x] `README.md` 갱신 — Quick start 가이드라인 시드 1단락 추가.
- [x] `api/tests/integration/test_verify_allergy_22.py` 신규 — 3 케이스 (일치 + frontmatter 누락 + lookup 추가 차이).

### Task 9 — Docker 자동 시드 검증 + 시드 컨테이너 정합 (AC: #4, #11)

- [x] `docker-compose.yml` `seed` 서비스 변경 X — 현 wired 그대로 활용 (Story 1.1 baseline + Story 3.1 + 본 스토리 자연 hook).
- [x] 로컬 검증 — `docker compose down -v && docker compose up` → seed 컨테이너 exit 0 + DB row 검증 (AC11 시나리오 1).
- [x] 로컬 검증 — `OPENAI_API_KEY=` 빈 + `ENVIRONMENT=dev` → graceful 시드 (AC11 시나리오 2).

### Task 10 — 백엔드 게이트 + sprint-status + commit/push (AC: #10)

- [x] `cd api && uv run pytest` — Story 3.1 baseline 282 passed / 1 skipped + 본 스토리 신규 ~30 → 총 ~312 케이스 통과 + coverage ≥ 70%.
- [x] `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy .` — clean.
- [x] `_bmad-output/implementation-artifacts/sprint-status.yaml` 갱신 — `3-2-가이드라인-rag-시드-chunking: ready-for-dev` → `in-progress` (DS 시작) → `review` (DS 완료).
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` — 본 스토리 신규 deferred 후보 등재 (DF84+).
- [x] `git add -A && git commit -m "feat(story-3.2): 가이드라인 RAG 시드(KDRIs/KSSO/KDA/MFDS/KDCA 50+ chunks + HNSW + GIN applicable_health_goals 필터) + chunking 3-format 재사용 인터페이스(pdf/html/markdown) + verify_allergy_22 SOP"` + `git push -u origin feat/story-3.2-guideline-rag-chunking`.

### Task 11 — CR 진입 준비 (post-DS, pre-CR)

- [x] story Status: `in-progress` → `review` 갱신.
- [x] sprint-status: `3-2-가이드라인-rag-시드-chunking: in-progress` → `review`.
- [x] CR 워크플로우 `bmad-code-review` 실행 (별 단계 — 사용자 명시 후).

## Dev Notes

### Architecture decisions (반드시 따를 것)

- **D1 결정 (`data/guidelines/*.md` frontmatter 파일이 1차 SOT, PDF/HTML chunker는 외주 인수 인터페이스 토대만)** — Architecture 결정 1 *"chunking 모듈은 외주 인수 인터페이스로 설계"* 정합. MVP 시드 경로는 `chunk_markdown`만 활성 — pdf/html chunker는 단위 테스트로 동작 검증만 + 외주 인수 클라이언트 자동 시드 파이프라인에서 활성화. 이유: (a) PDF 한글 폰트 + 표 파싱 fragile, (b) 운영자 수동 검수 + chunking + frontmatter 갱신 SOP가 *MVP 정합*(epic AC #608 *수동 1회 호출* 명시), (c) repo size 제한 — PDF 원본은 commit X, frontmatter MD만 commit. 외주 인수 후 *자동 PDF 파이프라인*은 Vision-stage 또는 Growth deferred — chunking 인터페이스가 박혀 있어 *코드 변경 X로 활성화 가능*(Architecture 결정 1 + Journey 7 식품기업 자사 SKU 통합 차별화 카드 +1).
- **D2 결정 (`text-embedding-3-small` 모델 + 1536 dim 고정)** — Story 3.1 D2 정합. `vector(1536)` 컬럼 + `text-embedding-3-large` OUT.
- **D3 결정 (HNSW `vector_cosine_ops` + m=16 / ef_construction=64)** — Story 3.1 D3 정합. 50-100 chunks는 1500건의 1/15-1/30이지만 동일 파라미터로 일관성 유지(외주 인수 시 운영 직관성 + Story 3.6 검색 흐름의 인덱스 활용 정합).
- **D4 결정 (`knowledge_chunks.embedding` NULL 허용)** — Story 3.1 D4 정합 (부분 실패 graceful + 검색 시 `WHERE embedding IS NOT NULL` 자동 제외). 단 본 스토리는 *dev graceful 분기*도 NULL 시드 (외주 인수 첫 부팅 영업 demo 보호 — D9 정합).
- **D5 결정 (시드 멱등 — `ON CONFLICT (source, source_id, chunk_index) DO UPDATE`)** — Story 3.1 D5 정합. 3-tuple UNIQUE 제약 — chunk_index가 추가 → 같은 문서 내 chunk 갱신 가능(운영자가 분기 1회 frontmatter body 갱신 시 멱등 시드).
- **D6 결정 (시드 batch — 단일 transaction, 임베딩 100건 batch)** — 50-100 chunks는 메모리 + 트랜잭션 비용 무시 가능(Story 3.1 1500건과 다른 규모) — 단일 commit. 임베딩은 100건 단일 batch — Story 3.1 `embed_texts` D6 baseline의 1/3 안전치(text-embedding-3-small 8K context 토큰 합산 cap 정합 — 가이드라인 chunk 1000자 ≈ 500-700 tokens × 100 = 50K-70K tokens, 단일 batch 한계 안전).
- **D7 결정 (Story 3.1 `embed_texts` SDK singleton 공유)** — Story 3.1 D7 정합. `_get_client()` 재활용 — connection pool + httpx timeout 공유.
- **D8 결정 (chunking 임베딩 텍스트 = `chunk.text` 그대로)** — Story 3.1 D8(`f"{name} ({category})"` 포맷) **다름** — 가이드라인 chunk는 *자기완결적 인용 단위*이므로 추가 컨텍스트 prefix 없이 chunk text 그대로 임베딩. heading 정보는 `chunk_markdown`이 chunk 내 prepend(예: `"## 매크로 비율 권장\n\n탄수화물 55-65%..."`)하여 임베딩에 자연 반영.
- **D9 결정 (`OPENAI_API_KEY` 미설정 시 dev/ci/test graceful + prod/staging fail-fast)** — Story 3.1 D9 패턴 정합. 단 본 스토리 graceful은 *embedding NULL chunks 시드*(Story 3.1 graceful은 *food_aliases만 시드 + food_nutrition 0건*) — 차이: chunks count는 충족 (검색 시 NULL embedding 제외만, `applicable_health_goals` 필터는 정상 작동). `RUN_GUIDELINE_SEED_STRICT=1` opt-in으로 dev fail-fast 강제.
- **D10 결정 (`verify_allergy_22.py` lookup vs frontmatter 비교 SOP)** — epic AC #5 + R8 정합. `app/domain/allergens.py` Story 1.5 baseline 22종 lookup이 1차 SOT(코드 PR 게이트 보호) + `data/guidelines/mfds-allergens-22.md` frontmatter `allergens` 필드가 RAG 시드 컨텍스트 SOT(시드 시 자료 인용). 두 SOT가 분리되어 있어 verify 스크립트가 분기 1회 일치 검증. 자동 PDF 파싱 비교는 OUT(Story 8 polish — 식약처 별표 PDF 다운 + parsing 자동화).
- **D11 결정 (`langchain-text-splitters` `RecursiveCharacterTextSplitter` 채택)** — `langchain>=0.3` umbrella 정합 + 한국어 텍스트 안전 separators(`["\n\n", "\n", " ", ""]`) + `add_start_index=True`로 char offset 자동 부착 + 검증된 라이브러리(LangChain ecosystem 표준). 자체 splitter 구현 OUT — bug surface ↑ + 외주 인수 시 *표준 라이브러리* 신호 (`langchain-text-splitters`는 LangChain 표준 — 클라이언트 개발자 인지도 ↑).
- **D12 결정 (chunking 인터페이스 — `Chunk` dataclass + 통일 시그니처)** — Architecture 결정 1 *"인터페이스 1개"* 정합. 3 format 모두 `(content, *, max_chars, overlap) -> list[Chunk]` 시그니처. 외주 인수 클라이언트가 *하나의 호출 패턴*으로 자기 PDF/HTML/MD를 시드 추가 가능 — 차별화 #4 + Journey 7 식품기업 자사 SKU 통합 카드 +1.

### Library / Framework 요구사항

- **pypdf (`>=5.1`)** — PDF 텍스트 추출 (BSD-3 라이선스). pyproject.toml 등재 X → 본 스토리 추가. AGPL `pymupdf` 회피(라이선스 리스크). 한글 폰트 + CID 매핑 깨짐 위험 — D1 명시 (운영자 수동 검수 SOP).
- **beautifulsoup4 (`>=4.12`)** — HTML 파싱 (MIT 라이선스). pyproject.toml 등재 X → 본 스토리 추가. `BeautifulSoup(content, "html.parser")` — `lxml` 별 의존 X (pure Python 기본 파서 사용 — perf보다 라이선스/의존성 단순성).
- **langchain-text-splitters (`>=0.3`)** — `RecursiveCharacterTextSplitter` + `MarkdownHeaderTextSplitter`. `langchain>=0.3` umbrella는 메인 패키지만 등재되어 있고 text-splitters는 별 패키지 — 본 스토리 추가.
- **pyyaml (`>=6.0`)** — frontmatter YAML 파싱. `langchain` transitive 가능성 — 명시 등재로 직접 의존성 표시.
- **pgvector (Python lib `>=0.3`)** — Story 3.1 baseline. `Vector(1536)` 컬럼 — 동일 패턴.
- **`text-embedding-3-small`** — Story 3.1 D2 baseline. SDK: Story 2.3 `_get_client()` singleton 공유 (D7).
- **SQLAlchemy 2.0.49 async** — Story 1.2 baseline + 본 스토리 신규 ORM — `Mapped` + `mapped_column` + `ARRAY(Text)` (`applicable_health_goals` text[]).
- **Alembic** — 0011 마이그레이션 — `op.create_index` raw + `postgresql_using='hnsw'` + `postgresql_using='gin'` (`applicable_health_goals`). autogenerate는 vector + HNSW + GIN 미지원 → 수동 작성 필수.

### Naming 컨벤션

- **테이블** — `knowledge_chunks` (snake_case 복수 — architecture line 392 정합).
- **컬럼** — snake_case (`source_id`, `chunk_index`, `chunk_text`, `applicable_health_goals`, `published_year`, `doc_title`).
- **UNIQUE 제약** — `uq_knowledge_chunks_source_source_id_chunk_index` (Story 3.1 0010 `uq_*` 정합).
- **HNSW 인덱스** — `idx_knowledge_chunks_embedding` (Story 3.1 `idx_food_nutrition_embedding` 정합).
- **GIN 인덱스** — `idx_knowledge_chunks_applicable_health_goals` (architecture line 293 *"filtered top-K"* 명시 정합).
- **Composite btree 인덱스** — `idx_knowledge_chunks_source` ON `(source, authority_grade)` (selectivity ↑).
- **신규 모듈** — `app/rag/chunking/__init__.py` + `markdown.py` + `pdf.py` + `html.py` + `app/rag/guidelines/__init__.py` + `seed.py` + `app/db/models/knowledge_chunk.py` (architecture line 256, 657, 682 정합).
- **테스트 위치** — `api/tests/rag/test_chunking_*.py` + `test_guideline_seed.py` + `test_knowledge_chunk_search.py` (Story 3.1 nested by feature 정합 — `tests/rag/`).
- **예외 카탈로그 prefix** — `guideline_seed.*` (Story 3.1 `food_seed.*` 정합).
- **Logger.info 키** — `chunking.<format>.complete` / `guideline_seed.insert` / `verify_allergy_22.diff` (Story 3.1 event-style 정합).
- **데이터 파일** — `data/guidelines/{source-slug}-{topic-slug}.md` (예: `kdris-2020-amdr.md`, `kosso-2024-weight-loss.md`).

### 폴더 구조 (Story 3.2 종료 시점에 *반드시* 존재해야 하는 신규/수정 항목)

```
api/
  alembic/versions/
    0011_knowledge_chunks.py             # 신규 — AC1
  app/
    core/
      exceptions.py                      # 갱신 — GuidelineSeed* 3 예외 추가 (AC6)
    db/models/
      __init__.py                        # 갱신 — KnowledgeChunk export
      knowledge_chunk.py                 # 신규 — AC1
    rag/
      chunking/                          # 신규 폴더 — Architecture 결정 1
        __init__.py                      # 신규 — Chunk dataclass + _split_text (AC2)
        markdown.py                      # 신규 — chunk_markdown (AC2)
        pdf.py                           # 신규 — chunk_pdf (AC2)
        html.py                          # 신규 — chunk_html (AC2)
      guidelines/                        # 신규 폴더 — architecture line 657
        __init__.py                      # 신규
        seed.py                          # 신규 — run_guideline_seed (AC3)
  data/
    guidelines/                          # 신규 폴더
      README.md                          # 신규 — 자료 갱신 SOP + 외주 alias 3경로 (AC9)
      kdris-2020-amdr.md                 # 신규 — KDRIs AMDR 8+ chunks (AC3)
      kdris-2020-protein.md              # 신규 — KDRIs 단백질 5+ chunks (AC3)
      kosso-2024-weight-loss.md          # 신규 — 대비학회 10+ chunks (AC3)
      kda-macronutrient.md               # 신규 — 대당학회 8+ chunks (AC3)
      mfds-allergens-22.md               # 신규 — 식약처 22종 4+ chunks (AC3 + AC7)
      kdca-diabetes-diet.md              # 신규 — 질병관리청 5+ chunks (AC3)
  pyproject.toml                         # 갱신 — pypdf/bs4/langchain-text-splitters/pyyaml + mypy.overrides (AC8)
  uv.lock                                # 갱신 — uv sync 결과 (AC8)
  tests/
    test_knowledge_chunks_schema.py      # 신규 — AC1
    test_guideline_seed_exceptions.py    # 신규 — AC6
    fixtures/
      sample-guideline.pdf               # 신규 — chunking_pdf 단위 테스트 fixture (AC2)
      sample-guideline.html              # 신규 — chunking_html 단위 테스트 fixture (AC2)
    rag/
      test_chunking_markdown.py          # 신규 — AC2
      test_chunking_pdf.py               # 신규 — AC2
      test_chunking_html.py              # 신규 — AC2
      test_guideline_seed.py             # 신규 — AC3
      test_knowledge_chunk_search.py     # 신규 — AC5 (skip 디폴트)
    integration/
      test_bootstrap_seed.py             # 갱신 — Story 3.1 5 케이스 + 본 스토리 2 케이스 (AC4)
      test_verify_allergy_22.py          # 신규 — AC7

scripts/
  seed_guidelines.py                     # 신규 — AC4 entry point
  bootstrap_seed.py                      # 갱신 — seed_guidelines 추가 호출 (AC4)
  verify_allergy_22.py                   # 신규 — AC7

.env.example                             # 갱신 — OPENAI_API_KEY 주석 + RUN_GUIDELINE_SEED_STRICT (AC9)
README.md                                # 갱신 — Quick start 가이드라인 시드 1단락 (AC9)
_bmad-output/implementation-artifacts/
  sprint-status.yaml                     # 갱신 — 3-2 ready-for-dev → in-progress → review
  deferred-work.md                       # 갱신 — DF84+ 신규 후보
```

**변경 X** — `mobile/*` / `web/*` (본 스토리는 백엔드 인프라만 — 라우터 응답 변경 X) / `docker-compose.yml`(Story 3.1 + 본 스토리 모두 `bootstrap_seed.py` 호출 그대로 활용) / `docker/postgres-init/01-pgvector.sql`(이미 vector extension 설치 — Story 1.1 baseline) / Story 3.1의 `app/adapters/openai_adapter.py` `embed_texts` 함수(재사용만 — 변경 0건).

### 보안·민감정보 마스킹 (NFR-S5)

- **API 키 노출 X** — `OPENAI_API_KEY`는 logger 출력 X (Story 3.1 baseline 정합). 어댑터 logger는 *masked* 1줄.
- **chunk_text raw 노출 회피** — 가이드라인은 공개 자료지만 통일 NFR-S5 패턴 — `texts` 입력은 logger 출력 X. `texts_count` + `model` + `latency_ms`만 (Story 3.1 D7 정합).
- **시드 통계 출력** — stdout `[seed_guidelines] knowledge_chunks: inserted={n} updated={n} total={n} files_processed={n}` — chunk 본문 노출 X (count + 파일 처리 수만).
- **Sentry capture** — 시드 실패 시 `scope.set_tag("seed", "guidelines_total_failure")` + stack trace. raw chunk_text + frontmatter는 Sentry breadcrumb에 노출 X (Story 1.1 + Story 2.3 + Story 3.1 베이스라인 마스킹 hook 활용).
- **chunking 모듈 logger** — `chunking.<format>.complete` 1줄 — `format` + `chunks_count` + `total_chars`. raw chunk text 노출 X.

### Anti-pattern 카탈로그 (본 스토리 영역)

- **`embedding NOT NULL` + 부분 실패 시 전체 batch 롤백** — Story 3.1 D4 정합 회피 — `embedding NULL` 허용으로 graceful degradation (단 본 스토리는 *dev graceful*도 적용 — D9).
- **시드 비멱등 (INSERT 만 + ON CONFLICT 미적용)** — `docker compose restart seed` 시 row 중복 + UNIQUE 위반 시드 fail. `ON CONFLICT (source, source_id, chunk_index) DO UPDATE`로 회피 (D5).
- **PDF 자동 파싱 의존 (한글 폰트 + 표)** — pypdf는 한글 PDF 텍스트 추출 fragile — 운영자 수동 검수 SOP가 MVP 정합 (D1). 자동 파이프라인은 외주 인수 후 활성화.
- **Frontmatter 메타데이터 검증 X** — `_FrontmatterSchema` Pydantic 검증 누락 시 잘못된 source / authority_grade enum 값으로 시드 진행 → Story 3.6 generate_feedback이 *(출처: 미상, 미상, NULL)* 패턴 출력 + 영업 카드 깨짐. fail-fast 검증 필수 (`GuidelineSeedValidationError`).
- **HNSW + GIN autogenerate 의존** — Alembic autogenerate는 vector + HNSW + GIN array 미지원. 수동 `op.create_index` raw 작성 필수 (Story 3.1 0010 패턴 정합).
- **`applicable_health_goals` 빈 배열 처리 누락** — `WHERE applicable_health_goals @> ARRAY[:health_goal]`만 필터 시 빈 배열 row(전 사용자 적용 — 22종 알레르기 등)가 0 매칭 → 영업 demo 깨짐. `OR applicable_health_goals = '{}'::text[]` 명시 필수 (AC5).
- **`chunk_index` 빈 입력 가능 (`-1` 또는 NULL)** — `chunking._split_text`가 0-based 순번 자동 부착 — `Chunk.chunk_index = i for i, ... in enumerate(...)` 패턴. NULL chunk_index는 UNIQUE 제약 위반(NULL 비교는 SQL 표준에서 미정의 → INSERT 허용 → 멱등 깨짐). `INTEGER NOT NULL` + 시드 코드의 enumerate 패턴 정합.
- **PDF/HTML chunker가 시드 경로에서 사용** — D1 위반 — MVP 시드 경로는 `chunk_markdown`만 사용. PDF/HTML은 단위 테스트 + 외주 인수 토대만. `run_guideline_seed`에서 pdf/html 호출은 anti-pattern.
- **`langchain-text-splitters` import 시 `langchain` 메인 패키지 import 폭증** — `langchain-text-splitters>=0.3`은 별 패키지 — `from langchain_text_splitters import ...` 명시 import (메인 `langchain` 의존성 회피 — text-splitters 패키지는 lightweight). cold-start 시간 영향 ≈ 0.
- **`sample-guideline.pdf` 바이너리 fixture 없이 PDF chunker 테스트** — fixture 없이 reportlab 등으로 *런타임 PDF 생성* 시 dev dep 추가 + 테스트 fragile. 미니 1-2페이지 한국어 PDF (~10KB) commit 정합.
- **`verify_allergy_22.py`가 PDF 다운 + 파싱 자동화** — D10 위반 — 본 스토리는 *lookup vs frontmatter 비교*만 + 공식 URL 안내. PDF 자동 다운 + 파싱은 Story 8 polish.

### Previous Story Intelligence (Story 3.1 + Story 2.3 + Story 1.5 학습)

**Story 3.1 (음식 영양 RAG 시드 — 직전 스토리)**:

- ✅ **alembic 0010 + ORM 패턴** — 본 스토리 0011은 동일 패턴 (UNIQUE 제약 + HNSW + raw `op.create_index` for vector + ARRAY(Text) 컬럼 추가).
- ✅ **`embed_texts` 어댑터 baseline** — `text-embedding-3-small` 1536 dim + 100건 batch + SDK singleton 공유 — 본 스토리 가이드라인 시드 *재사용 0건 변경*.
- ✅ **`FoodSeedError` 카탈로그 패턴** — 본 스토리 `GuidelineSeedError` 동일 base + 3 서브클래스 패턴.
- ✅ **dev graceful 분기 D9 — `_is_strict_mode` + `_is_graceful_environment`** — Story 3.1 baseline 함수 — 본 스토리 `seed.py`에서 *공용 utils로 추출 검토*(또는 직접 import 재활용 — D9 통일 정합).
- ✅ **bootstrap_seed.py 위임 패턴** — Story 3.1 baseline + 본 스토리 `seed_guidelines.main()` 추가 호출. food → guidelines 순차 패턴.
- ✅ **`api/data/README.md` SOP 패턴** — Story 3.1 ZIP fallback SOP + 외주 alias 3 경로 — 본 스토리 `api/data/guidelines/README.md` 동일 패턴 재활용 + 가이드라인 자료 갱신 SOP 추가.
- ✅ **per-test TRUNCATE helper 패턴** — `api/tests/rag/test_food_seed.py:_truncate_food_nutrition` 헬퍼(`async def _truncate_food_nutrition(session_maker): async with session_maker.begin() as session: await session.execute(text("TRUNCATE food_nutrition RESTART IDENTITY"))` 패턴) — 본 스토리 `_truncate_knowledge_chunks` 헬퍼 동일 패턴 + `api/tests/conftest.py` 갱신 X (per-test TRUNCATE — Story 3.1 정합 — `meals/consents/refresh_tokens/users` 외 신규 테이블은 TRUNCATE 갱신 X 정합 — 외래키 cascade 영향 X). `app.state.session_maker` 활용 (Story 3.1 baseline 정합).
- 🔄 **DF75-DF83 (Story 3.1 신규 deferred)** — 본 스토리 영향 X (food_nutrition 책임 영역, 본 스토리는 knowledge_chunks 별 테이블).
- 🔄 **Story 3.1 CR 12 patches 학습** — 본 스토리 코드 작성 시 *동일 회귀 차단*: (a) NaN/Inf vector·jsonb 가드(`_format_vector_literal` `math.isfinite` + `json.dumps(allow_nan=False)`), (b) `_is_strict_mode` 대소문자 무시 + `1`/`true`/`yes`/`on`, (c) `_embed_batch` 길이 mismatch graceful, (d) per-batch `session.commit()` (단 본 스토리는 50-100 chunks 단일 batch 정합 — 패턴은 동등 적용 정합). Story 3.1 CR 패턴이 이미 베이스 코드에 박혀 있어 본 스토리는 *동일 조심성*으로 작성.

**Story 2.3 (OCR Vision)**:

- ✅ **`openai_adapter.py` SDK singleton + tenacity** — `embed_texts` 재사용 — 본 스토리 변경 0건 (Story 3.1 baseline에서 이미 추가됨).

**Story 1.5 (건강 프로필)**:

- ✅ **22종 알레르기 enum (`domain/allergens.py`)** — 본 스토리 `verify_allergy_22.py` 1차 SOT — frontmatter `data/guidelines/mfds-allergens-22.md`와 *분리 SOT 비교* 패턴 (D10).
- ✅ **`health_goal` enum (`weight_loss`/`muscle_gain`/`maintenance`/`diabetes_management`)** — 본 스토리 `applicable_health_goals` 컬럼 값 정합 — `_FrontmatterSchema` Literal 타입 매칭.

**Story 1.4 (PIPA 동의)**:

- ✅ **`require_automated_decision_consent` dependency** — 본 스토리는 *시드 시점*만, 라우터 노출 X — dependency 적용 X. Story 3.6 generate_feedback 노드 + analysis 라우터에서 적용 (Story 3.6 책임).

**Story 1.1 (부트스트랩)**:

- ✅ **`vector` extension** — `docker/postgres-init/01-pgvector.sql` baseline — 본 스토리 마이그레이션 0011은 `CREATE EXTENSION` 호출 X (Story 3.1 0010 정합).
- ✅ **`OPENAI_API_KEY` env** — `.env.example` 등재 baseline — 본 스토리는 주석 갱신 + `RUN_GUIDELINE_SEED_STRICT` 추가만.

### Git Intelligence (최근 커밋 패턴)

```
cfd75ef feat(story-3.1): 음식 영양 RAG 시드 + pgvector HNSW + food_aliases 정규화 사전 + CR 12 patches (#17)
d4c513b feat(story-2.5): 오프라인 텍스트 큐잉(AsyncStorage FIFO + 지수 backoff) + Idempotency-Key 처리(W46 흡수) (#16)
5619173 feat(story-2.4): 일별 식단 기록 화면 + 7일 캐시 + KST 필터 + CR 11 patches (#15)
40403f3 feat(story-2.3): OCR Vision 추출 + 사용자 확인 카드 + parsed_items 영속화 + CR 8 patch (#14)
cf93900 chore(story-2.2): mark done — sprint-status + spec Status review → done (post-merge fix) (#13)
```

**최근 커밋 패턴에서 학습:**

- 커밋 메시지: `feat(story-X.Y): <한국어 요약> + <부수 작업>` 형식 — 본 스토리 `feat(story-3.2): 가이드라인 RAG 시드(KDRIs/KSSO/KDA/MFDS/KDCA 50+ chunks + HNSW + GIN applicable_health_goals 필터) + chunking 3-format 재사용 인터페이스 + verify_allergy_22 SOP` 패턴.
- master 직접 push 금지 — feature branch + PR + merge 버튼 (memory: `feedback_pr_pattern_for_master.md`).
- 새 스토리 브랜치는 master에서 분기 — `feat/story-3.2-guideline-rag-chunking` (memory: `feedback_branch_from_master_only.md`). **이미 분기 완료** (CS 시작 전 — memory: `feedback_ds_complete_to_commit_push.md` 정합).
- DS 종료점은 commit + push (memory: `feedback_ds_complete_to_commit_push.md`). PR(draft 포함)은 CR 완료 후 한 번에 생성.
- CR 종료 직전 sprint-status/story Status를 review → done 갱신해 PR commit에 포함 (memory: `feedback_cr_done_status_in_pr_commit.md`).
- OpenAPI 재생성 커밋 분리 권장 — 단 본 스토리는 라우터 응답 변경 X → OpenAPI 재생성 미발생.

### References

- [Source: epics.md:597-609] — Story 3.2 epic AC 5건 (가이드라인 50-100 chunks + chunking 3-format 모듈 + HNSW + applicable_health_goals 필터 + 인터페이스 격리 + verify_allergy_22 SOP).
- [Source: epics.md:579-581] — Epic 3 (AI 영양 분석 + Self-RAG + 인용 피드백) 입장 단락.
- [Source: epics.md:213-235] — Epic 3 prerequisites (`food_nutrition` + `knowledge_chunks` 2종 RAG 인덱스 + chunking 모듈 재사용 + 가이드라인 미니 지식베이스 50-100 chunks).
- [Source: prd.md:973-975] — FR23~FR25 (한국 1차 출처 인용 + 출처 패턴 강제 + 식약처 광고 가드).
- [Source: prd.md:533-538] — R8 (식약처 22종 갱신 SOP).
- [Source: prd.md:482-484] — NFR-P6 (RAG 검색 응답 ≤ 200ms — Story 3.1 ↔ 본 스토리 동등 인덱스 정합).
- [Source: prd.md:816] — 가이드라인 미니 지식베이스 시드 50-100 chunks + 메타데이터 권장 키.
- [Source: architecture.md:200-208] — Architecture 결정 1 — 가이드라인 RAG 수동 chunking + chunking 모듈 외주 인수 인터페이스.
- [Source: architecture.md:255-258] — `app/rag/chunking/` + `app/rag/guidelines/` 폴더 구조.
- [Source: architecture.md:285-299] — Data Architecture (Postgres 17 + pgvector 0.8.2 + jsonb 표준 키 + HNSW 별 인덱스 + `knowledge_chunks` 메타데이터).
- [Source: architecture.md:392-431] — Naming Patterns (DB 테이블 snake_case 복수 + 인덱스 `idx_<table>_<columns>`).
- [Source: architecture.md:580-695] — Backend 폴더 구조 — `app/rag/chunking/{pdf,html,markdown}.py` + `app/rag/guidelines/seed.py` + `app/db/models/knowledge_chunk.py` + `scripts/seed_guidelines.py` + `scripts/verify_allergy_22.py` 표기 정합.
- [Source: architecture.md:585-592] — Implementation Sequence (`scripts/seed_guidelines.py` W2 슬롯 + `verify_allergy_22.py` R8 SOP).
- [Source: research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md:90-107] — 핵심 1차 자료 인덱스 (KDRIs PDF / KSSO / KDA / KDCA / 식약처 식품영양성분 DB) + URL.
- [Source: research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md:108-122] — 출처 신뢰 등급 (A/B/C) + evaluate_fit 노드 인용 패턴 권고.
- [Source: research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md:130-178] — KDRIs 5대 기준치 + 매크로 AMDR 표 + 건강 목표별 매크로 분배 + 22종 알레르기 표 (가이드라인 시드 본문 입력).
- [Source: research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md:203-213] — `knowledge_chunks` 메타데이터 권장 (source / doc_type / publication_year / authority_grade / topic / applicable_health_goals).
- [Source: research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md:300-330] — 식약처 광고 가드 표 (Story 3.6 입력 — 본 스토리 OUT).
- [Source: 3-1-음식-영양-rag-시드-pgvector.md] — 직전 스토리 — alembic 0010 + ORM + `embed_texts` + `FoodSeedError` 카탈로그 + dev graceful D9 패턴 — 본 스토리는 *동일 패턴 가이드라인 측 적용*.
- [Source: 3-1-음식-영양-rag-시드-pgvector.md Review Findings] — Story 3.1 CR 12 patches — 본 스토리 코드 작성 시 *동일 회귀 차단*: NaN/Inf 가드 / strict mode 대소문자 / batch 길이 mismatch / per-batch commit (50-100 chunks 단일 batch는 패턴 적용 형식만 다름).
- [Source: 1-5-건강-프로필-입력.md] — `app/domain/allergens.py` 22종 lookup baseline — `verify_allergy_22.py` 1차 SOT.
- [Source: api/app/db/models/food_nutrition.py] — Story 3.1 ORM 패턴 (Mapped + mapped_column + Vector(1536) + JSONB + UniqueConstraint).
- [Source: api/app/adapters/openai_adapter.py:embed_texts] — Story 3.1 SDK singleton + 100건 batch + 차원 검증 — 본 스토리 *재사용 0건 변경*.
- [Source: api/app/core/exceptions.py:FoodSeedError] — Story 3.1 카탈로그 — 본 스토리 `GuidelineSeedError` 동일 패턴.
- [Source: api/app/rag/food/seed.py:_is_strict_mode/_is_graceful_environment] — Story 3.1 dev graceful D9 함수 — 본 스토리 *공용 utils로 추출 검토 또는 직접 재활용*.
- [Source: scripts/seed_food_db.py + scripts/bootstrap_seed.py] — Story 3.1 entry + 위임 패턴 — 본 스토리 `seed_guidelines.py` + `bootstrap_seed.py` 갱신 동일 패턴.
- [Source: api/pyproject.toml] — Story 1.1 baseline `langchain>=0.3` + `pgvector>=0.3` + `openai>=1.55` 등재 — 본 스토리 추가: `pypdf>=5.1` + `beautifulsoup4>=4.12` + `langchain-text-splitters>=0.3` + `pyyaml>=6.0`.
- [Source: docker-compose.yml] — `seed` 서비스 wired (`bootstrap_seed.py` 호출) — 변경 X.
- [Source: docker/postgres-init/01-pgvector.sql] — `CREATE EXTENSION vector` baseline — 변경 X.
- [Source: pgvector/pgvector docs] — HNSW + GIN array 인덱스 표준.
- [Source: OpenAI Embeddings API docs] — `text-embedding-3-small` 1536 dim, $0.02/1M tokens, 8K context.
- [Source: langchain-text-splitters docs] — `RecursiveCharacterTextSplitter` + `MarkdownHeaderTextSplitter` 표준 사용 패턴.
- [Source: pypdf docs] — `PdfReader` + `page.extract_text()` 표준 — 한글 폰트 한계 안내 (D1).
- [Source: beautifulsoup4 docs] — `BeautifulSoup(content, "html.parser")` + `get_text(separator, strip)` 표준.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] (Amelia, BMad Senior Software Engineer)

### Debug Log References

- DS 진입 시점: 2026-05-01. branch `feat/story-3.2-guideline-rag-chunking`.
- T1 alembic 0011 1차 적용 — `pg_indexes`로 HNSW(`vector_cosine_ops` m=16/ef=64) +
  GIN(`applicable_health_goals`) + composite btree(`source, authority_grade`) 인덱스
  3건 생성 확인, schema test 4 케이스 통과.
- T5 `run_guideline_seed` 첫 시도 — `text[]` literal `'{"diabetes_management"}'` CAST 시
  asyncpg `DataError: a sized iterable container expected (got type 'str')` raise.
  asyncpg는 Python `list[str]`을 native text[] 매핑 → CAST 제거 + `list(meta.applicable_health_goals)`
  직접 전달로 수정. 6 케이스 통과.
- T6 새 bootstrap async 테스트 첫 시도 — `bs.main()` 내부 `asyncio.run()`이 pytest-asyncio
  실행 loop와 충돌. 기존 패턴(`sfd._run_seeds()` 직접 await) 정합으로 `seed_guidelines._run_seeds()`도
  직접 await로 변경. 7 케이스 통과 (Story 3.1 baseline 5 + Story 3.2 신규 2).
- T10 lint 정리 — ruff E501 8건 (docstring 다국어 한·영 혼합 라인 길이) + F841 1건
  (unused `parts` local) 수정. format 8 파일 자동 reformat. mypy 신규 모듈 15 파일 clean.
  Story 1.3 baseline `tests/test_consents_deps.py` 11건은 본 스토리 변경 외부 (pre-existing,
  회귀 0건).

### Completion Notes List

- ✅ 모든 11 Task / Subtasks 완료. 모든 AC 1-10 충족 (AC11 smoke 시나리오는 사용자 수동 검증 권장 — baseline 충족).
- ✅ pytest 317 passed / 2 skipped(perf) — Story 3.1 baseline 282 → +35 신규 (T1 4 + T2 4 + T4 13 + T5 6 + T6 +2 + T7 4 + T8 3 = 36; 1건은 perf skip 합산). coverage 84.89% (NFR-M1 70% 초과 + Story 3.1 84.21% baseline 유지/소폭 증가).
- ✅ ruff check + format clean / mypy 신규 모듈 strict clean.
- ✅ alembic 0011 round-trip 정상 (upgrade head ↔ downgrade 0010).
- ✅ chunking 3-format 통일 시그니처 — `(content, *, max_chars=1000, overlap=100) -> list[Chunk]` (D12). MVP 시드 경로는 `chunk_markdown`만 활성, `chunk_pdf`/`chunk_html`은 단위 테스트 + 외주 인수 인터페이스 토대(D1).
- ✅ 가이드라인 6 markdown 파일 시드 — KDRIs AMDR/Protein + KSSO 9판 체중감량 + KDA 매크로 + MFDS 22종 알레르기 + KDCA 당뇨 식이요법 (frontmatter `_FrontmatterSchema` Pydantic 검증).
- ✅ `OPENAI_API_KEY` graceful 분기(D9) — dev/ci/test는 NULL embedding 시드 + `embeddings_skipped=True`, prod/staging 또는 `RUN_GUIDELINE_SEED_STRICT=1` opt-in은 `GuidelineSeedSourceUnavailableError` raise.
- ✅ `verify_allergy_22.py` SOP — 22종 lookup vs frontmatter 1:1 비교 + 식약처 공식 URL 3종 stdout + 분기 cron 안내 + 3 케이스 통합 테스트.
- ✅ Docker `seed` 컨테이너 — `bootstrap_seed.py` 갱신으로 food → guidelines 순차 시드 wired (config 변경 X).
- ✅ NFR-S5 마스킹 — chunk_text raw 노출 X (`chunking.<format>.complete` + `guideline_seed.insert` 1줄 logger). API key 노출 X (Story 3.1 baseline 정합).
- ⚠️ test_consents_deps.py mypy 11 에러는 Story 1.3 baseline pre-existing — 본 스토리 변경 외부, 회귀 0건. CR 시점에 별도 검토 권장.
- 📝 chunking offset 계산은 heading-aware split 시 *best-effort* — chunk가 원본 문서의 어디쯤이라는 추적 용도이며 정확한 위치 추적은 검색 인용 정확도에 영향 X (Story 3.6 generate_feedback이 chunk_text + doc_title + published_year로 인용 패턴 구성).

### File List

**신규 파일 (api/):**
- `api/alembic/versions/0011_knowledge_chunks.py`
- `api/app/db/models/knowledge_chunk.py`
- `api/app/rag/chunking/__init__.py`
- `api/app/rag/chunking/markdown.py`
- `api/app/rag/chunking/pdf.py`
- `api/app/rag/chunking/html.py`
- `api/app/rag/guidelines/__init__.py`
- `api/app/rag/guidelines/seed.py`
- `api/data/guidelines/README.md`
- `api/data/guidelines/kdris-2020-amdr.md`
- `api/data/guidelines/kdris-2020-protein.md`
- `api/data/guidelines/kosso-2024-weight-loss.md`
- `api/data/guidelines/kda-macronutrient.md`
- `api/data/guidelines/mfds-allergens-22.md`
- `api/data/guidelines/kdca-diabetes-diet.md`
- `api/tests/fixtures/__init__.py`
- `api/tests/fixtures/_build_pdf_fixture.py` (1회용 dev 도구)
- `api/tests/fixtures/sample-guideline.pdf` (binary)
- `api/tests/fixtures/sample-guideline.html`
- `api/tests/test_knowledge_chunks_schema.py`
- `api/tests/test_guideline_seed_exceptions.py`
- `api/tests/rag/test_chunking_markdown.py`
- `api/tests/rag/test_chunking_pdf.py`
- `api/tests/rag/test_chunking_html.py`
- `api/tests/rag/test_guideline_seed.py`
- `api/tests/rag/test_knowledge_chunk_search.py`
- `api/tests/integration/test_verify_allergy_22.py`

**신규 파일 (scripts/):**
- `scripts/seed_guidelines.py`
- `scripts/verify_allergy_22.py`

**수정 파일:**
- `api/app/db/models/__init__.py` (KnowledgeChunk export)
- `api/app/core/exceptions.py` (`GuidelineSeedError` + 3 서브클래스)
- `api/pyproject.toml` (4 dep + mypy.overrides 갱신)
- `api/uv.lock` (uv sync 결과)
- `api/tests/integration/test_bootstrap_seed.py` (Story 3.1 baseline 5 + Story 3.2 신규 2)
- `scripts/bootstrap_seed.py` (food→guidelines 순차)
- `.env.example` (`OPENAI_API_KEY` 주석 + `RUN_GUIDELINE_SEED_STRICT` opt-in)
- `README.md` (Quick start 가이드라인 시드 1단락)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (3-2 ready-for-dev → in-progress → review)
- `_bmad-output/implementation-artifacts/3-2-가이드라인-rag-시드-chunking.md` (Status + Tasks + Dev Agent Record)

### Change Log

| Date | Author | Note |
|------|--------|------|
| 2026-05-01 | Amelia (claude-opus-4-7[1m]) | Story 3.2 ready-for-dev — 가이드라인 RAG 시드(KDRIs/KSSO/KDA/MFDS/KDCA 50+ chunks) + chunking 3-format 재사용 인터페이스(markdown 1차 + pdf/html 외주 인수 토대 — Architecture 결정 1) + `knowledge_chunks` 테이블 + HNSW(`vector_cosine_ops` m=16/ef_construction=64) + GIN(`applicable_health_goals` filtered top-K) + composite btree(`source, authority_grade`) 4 인덱스 + frontmatter Pydantic 검증(_FrontmatterSchema) + dev graceful D9 (`OPENAI_API_KEY` 미설정 → embedding NULL 진행, `RUN_GUIDELINE_SEED_STRICT=1` opt-in) + `data/guidelines/*.md` 6 파일 + `app/rag/chunking/{__init__,markdown,pdf,html}.py` + `app/rag/guidelines/seed.py` + `scripts/seed_guidelines.py` entry + `bootstrap_seed.py` food→guidelines 순차 + `scripts/verify_allergy_22.py` 22종 lookup vs frontmatter 비교 SOP(R8) + `pyproject.toml` `pypdf`/`bs4`/`langchain-text-splitters`/`pyyaml` + mypy.overrides 갱신 + `data/guidelines/README.md` 자료 갱신 SOP + 외주 PDF 시드 추가 3 경로 + `GuidelineSeedError` 3 예외 + alembic 0011 + ORM 신규 + `.env.example` 주석 + `README.md` Quick start 시드 1단락 baseline 컨텍스트 작성. Status: backlog → ready-for-dev. |
| 2026-05-01 | Amelia (claude-opus-4-7[1m]) | Story 3.2 DS 완료 — 11 Task 모두 통과. alembic 0011 + KnowledgeChunk ORM 신규 + chunking 3-format 모듈 + 6 가이드라인 markdown 파일 + run_guideline_seed + scripts/seed_guidelines + bootstrap_seed food→guidelines 순차 + verify_allergy_22 SOP. pytest 317 passed / 2 skipped(perf) / coverage 84.89%. ruff/format clean / mypy 신규 모듈 strict clean (Story 1.3 baseline test_consents_deps 11 에러는 회귀 0). asyncpg `text[]` Python list native 매핑 패턴 채택(CAST 제거). chunking offset은 heading-aware best-effort(인용 정확도 영향 X — Story 3.6 generate_feedback이 chunk_text + doc_title 사용). Status: in-progress → review. |
| 2026-05-01 | Amelia (claude-opus-4-7[1m]) | Story 3.2 CR 완료 — 3-layer adversarial review (Blind Hunter / Edge Case Hunter / Acceptance Auditor). raw 52 findings → dedup 22 → triage **PATCH 10 / DEFER 5 / DISMISS 7**. 10 patch 모두 적용: (1) `markdown.py` heading-aware char_start/end 정확화(sub_doc 내 multi-chunk가 `sc.char_start` 보존), (2) `seed.py` `FoodSeedAdapterError` prod fail-fast(D9 정합), (3) count gate를 *현 run inserted+updated*로 정정(table-wide pollution 방지), (4) `_FrontmatterSchema.applicable_health_goals` default 제거(spec 정합 — 필수화), (5) `published_year` default 제거(spec 정합), (6) `_FRONTMATTER_RE` CRLF + EOF tolerance, (7) `verify_allergy_22.py` ordering invariant 검증 추가(`mfds-allergens-22.md` body line 38 명시), (8) `_parse_markdown_with_frontmatter` UTF-8 BOM 선처리, (9) `_format_vector_literal([])` → None 강등(pgvector empty reject), (10) dead `structlog.get_logger` 2개 모듈 제거. 회귀 0건 — pytest 317 passed / 2 skipped / coverage 84.80% / ruff·format clean / mypy 신규 모듈 strict clean. 5 defer는 `deferred-work.md` DF84-DF88 등재. Status: review → done. |

### Review Findings

CR 실시: 2026-05-01 — Amelia (claude-opus-4-7[1m]) — 3-layer adversarial review (Blind Hunter / Edge Case Hunter / Acceptance Auditor). 사전 알림 2건은 finding 외 처리: ❶ `tests/test_consents_deps.py` mypy 11건 = Story 1.3 baseline pre-existing (회귀 0, git stash 검증), ❷ AC11 smoke = spec 자체가 *사용자 수동 검증 권장* OUT 명시.

집계: raw 52 findings → dedup 후 22 unique → triage 결과 **PATCH 10 / DEFER 5 / DISMISS 7**.

#### Patch (10)

- [x] [Review][Patch] Markdown chunker char_start collision within heading section [api/app/rag/chunking/markdown.py:128-145] — heading-aware 분기에서 `_split_text` 결과의 `sc.char_start`를 무시하고 sub_doc 시작 offset만 사용 → 같은 섹션의 multi-chunk 모두 동일 `char_start`/`char_end`를 보고. dataclass docstring(`char_end = char_start + len(text)`)과 AC2 contract 위반. fix: `char_start = sub_doc_start_in_body + body_shift + sc.char_start`(heading prepend 길이는 차감) + `char_end = char_start + len(sc.text)`.
- [x] [Review][Patch] `FoodSeedAdapterError`가 prod/strict에서도 NULL embedding으로 silent 강등 [api/app/rag/guidelines/seed.py:217-225] — `_embed_chunks`의 `except FoodSeedAdapterError` 분기가 환경 무관하게 warning + NULL 반환. D9 *"prod/staging fail-fast"* 위반. fix: `if not _is_graceful_environment(): raise GuidelineSeedAdapterError("guideline seed embed failed") from exc` 분기 추가.
- [x] [Review][Patch] count gate가 테이블 전체 row를 카운트(현 run 분 X) [api/app/rag/guidelines/seed.py:334-341] — `SELECT count(*) FROM knowledge_chunks`는 prior run의 잔존 row 포함 → 현 run이 1건만 시드해도 게이트 통과 가능. fix: `if (inserted_total + updated_total) < GUIDELINE_SEED_MIN_CHUNKS: raise GuidelineSeedAdapterError(...)` (현 run 분만 검증).
- [x] [Review][Patch] `_FrontmatterSchema.applicable_health_goals` `default_factory=list`로 optional화 — spec 위반 [api/app/rag/guidelines/seed.py:95-97] — AC3 spec line 99는 `applicable_health_goals: list[Literal[...]]`(default 없음 → 필수)로 명시. 현 코드는 누락 시 `[]` 기본값으로 silent 통과. fix: `Field(default_factory=list)` 제거(필수화) — 현 6 데이터 파일은 모두 명시했으므로 회귀 없음.
- [x] [Review][Patch] `_FrontmatterSchema.published_year` `default=None`으로 optional화 — spec 위반 [api/app/rag/guidelines/seed.py:98] — AC3 spec line 100은 `published_year: int | None  # ge=1990, le=2100`(default 없음). 현 코드는 누락 시 None 기본값으로 silent 통과. fix: `Field(ge=1990, le=2100)`(default 제거).
- [x] [Review][Patch] frontmatter 파서 분리(seed line-based vs chunker regex)로 CRLF/no-trailing-newline 케이스 disagreement [api/app/rag/chunking/markdown.py:32 + api/app/rag/guidelines/seed.py:141-175] — `_FRONTMATTER_RE`는 `\n---\s*\n` 종료 fence를 요구(LF + trailing newline 필수)하지만 `_parse_markdown_with_frontmatter`는 line-split 기반으로 더 관대. 외부 호출자가 raw 파일을 chunker에 직접 넘길 때 frontmatter가 chunk_text로 leak 가능. fix: chunker 정규식 `re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", re.DOTALL)`로 CRLF + EOF tolerance 추가.
- [x] [Review][Patch] `verify_allergy_22.py` set 비교가 ordering invariant 검증 안 함 [scripts/verify_allergy_22.py:105-108] — body line 38은 *"본 22종은 정의 순서를 보존해야 한다"* 명시 + `app/domain/allergens.py` line 27 동일 invariant. 현 `set` 비교는 reordering을 silent accept. fix: set 일치 + length 검증 후 `if list(KOREAN_22_ALLERGENS) != list(fm_allergens): print order drift; return False` 추가.
- [x] [Review][Patch] UTF-8 BOM이 frontmatter 감지를 우회 [api/app/rag/guidelines/seed.py:149] — Windows 편집기로 저장 시 leading `﻿`로 `content.startswith("---")`가 False → frontmatter 미존재로 처리되어 `_FrontmatterSchema.model_validate({})` 실패 → 모든 BOM 파일 시드 abort + 'frontmatter validation failed'로 원인 마스킹. fix: `if content.startswith("﻿"): content = content[1:]` 선처리(또는 `read_text(encoding="utf-8-sig")`).
- [x] [Review][Patch] `_format_vector_literal([])`가 `"[]"` 반환 → pgvector reject [api/app/rag/guidelines/seed.py:127-138] — 빈 list가 NaN/Inf 검사 통과 후 `"[]"` literal로 INSERT → Postgres `cannot determine dimension` 에러로 트랜잭션 abort. fix: `if not vector: return None` 우선 분기 추가.
- [x] [Review][Patch] 미사용 module-level `structlog.get_logger` (dead code) [api/app/rag/chunking/__init__.py:30 + scripts/seed_guidelines.py:28] — 두 모듈 모두 logger 정의 후 호출 0건. fix: 제거(또는 호출 추가).

#### Defer (5)

- [x] [Review][Defer] `pypdf` 6.10.2 vs spec/문서 `>=5.1` major-version drift [api/uv.lock:1630 + api/pyproject.toml:41] — deferred, pre-existing — `>=5.1` constraint는 6.x 허용하므로 lock 자체는 합법. 단 spec/dev-notes는 5.1 동작 기준 — 6.x에서 한국어 PDF 추출 parity 미검증. PR 게이트는 통과 + 시드 경로는 markdown only(pdf chunker는 외주 인수 인터페이스 토대만 — D1)이므로 prod 영향 0. Story 8 polish에서 pyproject `pypdf>=5,<7` 정합 또는 spec 갱신.
- [x] [Review][Defer] `verify_allergy_22.py` 하드코딩 MFDS CMS IDs 부패 위험 [scripts/verify_allergy_22.py:36-49] — deferred, pre-existing — `flSeq=42533884` / `bbs_no=bbs001` / `seq=31242` 등 ephemeral CMS ID. 식약처 사이트 재구성 시 dead URL. 분기 SOP에서 운영자가 수동으로 fallback URL 검색 가능 + Story 8 polish에서 `last_verified_at` 메타 + 식약처 별표 PDF 자동 다운으로 흡수.
- [x] [Review][Defer] `bootstrap_seed.main()` 직접 통합 테스트 부재 [api/tests/integration/test_bootstrap_seed.py:278-280] — deferred, pre-existing — `bootstrap_seed.main`은 sync wrapper(`asyncio.run` 내부)이므로 pytest-asyncio 환경에서 직접 호출 시 "running event loop" 충돌. 테스트는 `_run_seeds()`를 직접 await하여 sequencing 검증(test 코멘트로 design rationale 명시). docker compose 통합 smoke가 main 자체 검증(AC11). Story 8 polish에서 sync subprocess test 추가 검토.
- [x] [Review][Defer] `KnowledgeChunk.updated_at` ORM `onupdate=now()`가 raw-SQL 경로에서 dead [api/app/db/models/knowledge_chunk.py + api/alembic/versions/0011_knowledge_chunks.py] — deferred, pre-existing — 시드는 raw INSERT의 `ON CONFLICT DO UPDATE SET ... updated_at = now()`로 명시 set하므로 실제 운영에서 issue 0. ORM `onupdate`는 ORM session.flush 시점에만 작동 — Story 3.6+에서 ORM update 패턴 도입 시 활성화. Postgres `ON UPDATE` 트리거 추가는 Growth deferred.
- [x] [Review][Defer] `chunk_pdf` `for page in reader.pages` 루프가 try-block 외부 [api/app/rag/chunking/pdf.py:48] — deferred, low-risk — `PdfReader(...)` 생성자 try block 내부지만 `reader.pages` iteration은 외부. pypdf 6.x는 lazy load이므로 page 접근 시 `PdfReadError` 가능 → 외부로 leak하여 `GuidelineSeedAdapterError` 미래핑. PDF chunker는 MVP 시드 경로 호출 X(D1)이므로 운영 영향 0. 외주 인수 시 자동 PDF 파이프라인 활성화 시점에 catch 범위 확장.

#### Dismiss (7) — 노이즈/검증 실패

- ❌ Blind: PDF fixture가 plain text — VERIFIED `%PDF-1.4` 헤더로 정상 PDF 바이너리. diff 표시는 pypdf text-extraction preview.
- ❌ Auditor: `RUN_GUIDELINE_SEED_STRICT=` 비주석 vs 주석 — 코드베이스 컨벤션은 `# RUN_*=1`(line 44 `# RUN_FOOD_SEED_STRICT=1` 동일 패턴). spec 예시는 ideal pattern일 뿐 codebase 정합성이 우선.
- ❌ Auditor: index 4건 대신 3건 검증 — UNIQUE 제약은 `test_knowledge_chunks_unique_constraint`에서 `pg_constraint`로 별 검증, 합계 4건 충족.
- ❌ Blind: "기타" sentinel 알레르기 — `KOREAN_22_ALLERGENS`(allergens.py:50) + frontmatter `allergens` 양쪽 모두 22번째 항목으로 일치. by-design.
- ❌ Blind: `chunk_pdf`/`chunk_html`의 Chunk 재구성 비효율 — Chunk 필드 동일 복사로 의미 변경 0. 성능 noise.
- ❌ Blind: `settings.environment` 빈 문자열 시 graceful 미적용 — `_is_graceful_environment()`는 enumset 멤버십만 검사 → 빈/None은 prod fail-fast로 떨어지는 게 *의도*(미설정 = 안전).
- ❌ Edge: `MarkdownHeaderTextSplitter` H1 미포함으로 첫 단락 누락 — 6 데이터 파일 모두 `## `로 시작(H1 doc_title은 frontmatter로 흡수 — D8 정합), 실제 누락 0.
