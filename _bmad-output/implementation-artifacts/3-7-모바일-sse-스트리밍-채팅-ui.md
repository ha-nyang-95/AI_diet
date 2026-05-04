# Story 3.7: 모바일 SSE 스트리밍 채팅 UI + polling fallback + 디스클레이머 푸터

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **엔드유저**,
I want **분석 결과를 모바일 채팅 UI에서 한 글자씩 흐르는 스트리밍으로 받고, 끊김 시 polling으로 자동 강등되며 결과 카드 푸터에 디스클레이머가 노출되기를**,
so that **결과를 빠르고 매끄럽게 받으면서 의학적 진단 오해를 막을 수 있다**.

## Acceptance Criteria

1. **AC1 — POST /v1/analysis/stream SSE 엔드포인트 (FR17, FR26)**: `api/app/api/v1/analysis.py` 신규 — `POST /v1/analysis/stream` 라우터가 `meal_id: UUID` body 수신 → `Depends(current_user)` + `Depends(require_basic_consents)` + `Depends(require_automated_decision_consent)` 3 게이트 통과 → `meals` row 소유권 검증(`user_id` 일치 + `deleted_at IS NULL`) → `sse_starlette.EventSourceResponse`로 SSE 응답 반환. 응답 헤더 `X-Stream-Mode: sse` + `X-Request-Id`(미들웨어 echo). 라우터에 `RATE_LIMIT_LANGGRAPH = "10/minute"` 적용(`app.state.limiter` 데코레이터).

2. **AC2 — SSE 이벤트 4종 + clarify 5번째 (epic AC2 + Story 3.4 정합)**: 이벤트 type 카탈로그 SOT는 `app/api/v1/analysis.py:_SSE_EVENT_TYPES = Literal["progress", "token", "citation", "done", "clarify", "error"]`. payload 구조:
   - `event: progress` — `{"phase": "parse"|"retrieve"|"evaluate"|"feedback", "elapsed_ms": int}` — TTFT(NFR-P3) 조기 신호용. 파이프라인 진입 직후 즉시 1회 emit.
   - `event: token` — `{"delta": "..."}` — LLM 응답 본문 청크.
   - `event: citation` — `{"index": 0, "source": "...", "doc_title": "...", "published_year": 2020}` — `feedback.citations` 1:1 매핑(0-based index 순서).
   - `event: clarify` — `{"options": [{"label": "...", "value": "..."}, ...]}` — Story 3.4 `needs_clarification=True` 분기에서 emit. UI는 chip 노출 → 사용자 선택 → `POST /v1/analysis/clarify`로 resume.
   - `event: done` — `{"meal_id": "...", "final_fit_score": 62, "fit_score_label": "good", "macros": {"carbohydrate_g": ..., "protein_g": ..., "fat_g": ..., "energy_kcal": ...}, "feedback_text": "...", "citations_count": 3, "used_llm": "gpt-4o-mini"}` — 최종 상태 1회. UI 카드 영속화 + `[meal_id].tsx` 조회 캐시 invalidate 신호.
   - `event: error` — RFC 7807 ProblemDetail JSON(`type` / `title` / `status` / `code` / `detail` / `instance`). `code` 카탈로그: `analysis.checkpointer.unavailable`(503), `analysis.consent.missing`(403), `analysis.meal.not_found`(404), `analysis.rate_limit.exceeded`(429), `analysis.llm.dual_exhausted`(503), `analysis.unexpected`(500).

3. **AC3 — 종료 규칙 + 이중 종료 방지 (epic AC3, architecture line 495)**: `done` 또는 `clarify` 또는 `error` *정확히 1회* emit 후 generator 종료. 클라이언트(`react-native-sse`)는 셋 중 하나 수신 시 `eventSource.close()` 호출 — 이중 close idempotent(`eventSource.readyState === CLOSED` 가드). 서버 generator는 `finally`에서 cleanup(structlog INFO + 자원 해제). 같은 `meal_id`로 중복 SSE 연결 시도 시 *서버 측 차단 X*(클라이언트 race로 두 SSE 시작 시 양쪽 모두 정상 종료 — checkpointer thread_id 동일이라 두 번째 호출은 cache hit 또는 동일 결과). 동시성 제한은 `RATE_LIMIT_LANGGRAPH = "10/minute"`(per-IP) 1차 가드.

4. **AC4 — TTFT(NFR-P3) p50 ≤ 1.5초 / p95 ≤ 3초 + Pseudo-streaming 청킹 (epic AC4, NFR-P3)**: TTFT는 *클라이언트 SSE 연결 open → 첫 emit 이벤트(`event: progress` "phase": "parse") 수신* 까지의 시간. progress 이벤트는 라우터 진입 즉시(`asyncio.sleep` 없이) emit — 본 시점의 TTFT는 네트워크 RTT + FastAPI 핸들러 진입 cost(~50ms 이하)로 NFR-P3 만족. **본문 token 청킹 전략(D1 결정)**: 파이프라인 buffered 실행(Story 3.6 `generate_feedback`이 full text 반환) → 결과 텍스트를 `_chunk_text(text, chunk_chars=24, interval_ms=30)` helper로 *문자 단위* 분할 → `event: token` 순차 emit. 한국어 *grapheme cluster* 안전(emoji ZWJ 시퀀스 / 자모결합 mid-codepoint cut 방지) — `re.findall(r"\X", text)` 또는 list(text)+combining char skip(D1 sub-decision: stdlib만으로 NFC 정규화 후 `list()`로 충분 — combining 결합 자모는 NFC 후 단일 codepoint). True LLM-token streaming은 Story 8.4 polish(deferred — 본 스토리는 *UX 스트리밍 느낌* 우선 + Story 3.6 citation/ad-guard 후처리 회귀 0). cache hit 경로는 LLM 호출 0 → 종단 ≤ 800ms 추정(NFR-P1 정합).

5. **AC5 — T5 KPI(스트리밍 안정성, 5분 50회 끊김 ≤ 1)**: `tests/api/v1/test_analysis_stream_perf.py` `@pytest.mark.perf` opt-in(`RUN_PERF_TESTS=1`). 시뮬: 50회 연속 SSE 호출 + 각 호출에서 `done` 또는 `clarify` 또는 `error` 정확히 1회 수신 검증. 끊김 정의: `done`/`clarify`/`error` 미수신 + `EventSource.onerror` 발생. CI 기본 skip(perf marker). T5 KPI 측정은 Story 3.8 LangSmith eval 흐름에서 자동화(deferred — 본 스토리는 단위 테스트 가드만).

6. **AC6 — SSE 끊김 시 polling 자동 강등 (epic AC6, architecture line 530, R2 mitigation)**: 클라이언트 `useMealAnalysisStream` hook이 `EventSource.onerror` 또는 `event: error` 수신 시(서버에서 `event: done`/`clarify`/`error` 수신 전) → 1.5초 후 polling 모드로 강등. polling 흐름:
   - `GET /v1/analysis/{meal_id}` 호출 1.5초 간격(setInterval) — 응답: 진행 중이면 `{"status": "in_progress", "phase": "..."}` 200 + 헤더 `X-Stream-Mode: polling`, 완료면 `{"status": "done", "result": {...event: done payload...}}`, clarification 이면 `{"status": "needs_clarification", "options": [...]}`, 에러면 `{"status": "error", "problem": {...RFC 7807...}}`.
   - polling 시작 시 응답 헤더 `X-Stream-Mode: polling`(architecture line 322 / 506 정합)명시. SSE 헤더는 `X-Stream-Mode: sse`.
   - polling 5회(7.5초) 연속 `in_progress` 시 `Retry-After` 헤더 hint(2초) 노출.
   - polling 30회(45초) 후에도 미완료 시 client에서 timeout `event: error` 동등 처리 + 사용자 안내(*"분석이 평소보다 오래 걸려요. 잠시 후 다시 시도해주세요"*).

7. **AC7 — GET /v1/analysis/{meal_id} polling 엔드포인트 (AC6 입력)**: `api/app/api/v1/analysis.py` 동일 라우터에 `GET /v1/analysis/{meal_id}` 엔드포인트 추가. `Depends(current_user)` + `Depends(require_basic_consents)`(automated_decision은 미강제 — 단순 조회 대 분석 호출 비대칭, PIPA Art.35 정보주체 권리 정합). 응답 매핑:
   - `analysis_service.aget_state(thread_id=f"meal:{meal_id}")` 호출 → `MealAnalysisState` 반환.
   - state empty(thread_id 미존재) + meals row 존재 → 202 + `{"status": "in_progress", "phase": "queued"}` + `Retry-After: 2`.
   - state.feedback 존재 → 200 + `{"status": "done", "result": {...event: done payload 동등 schema...}}`.
   - state.needs_clarification === True → 200 + `{"status": "needs_clarification", "options": state.clarification_options}`.
   - state.node_errors 존재(generate_feedback fallback edge 진입) → 200 + `{"status": "error", "problem": {RFC 7807 mapping}}`.
   - meals row 미존재 또는 user 비소유 → 404 + `analysis.meal.not_found`.

8. **AC8 — POST /v1/analysis/clarify resume 엔드포인트 (Story 3.4 + AC2 clarify 정합)**: `api/app/api/v1/analysis.py` 동일 라우터에 `POST /v1/analysis/clarify` 엔드포인트 추가. body `{"meal_id": UUID, "selected_value": str}` (Pydantic `min_length=1` + `max_length=80` Story 3.4 `ClarificationOption.value` 정합). 흐름:
   - 3 게이트(current_user + basic + automated_decision).
   - meals row 소유권 검증.
   - `analysis_service.aresume(thread_id=f"meal:{meal_id}", user_input={"selected_value": selected_value})` 호출.
   - 결과: `aresume`이 ValueError raise(빈 selected_value) → 422 + `analysis.clarify.invalid`. 정상 완료 시 SSE 재진입(POST /v1/analysis/stream과 동일 응답 구조 — `EventSourceResponse`).
   - 본 엔드포인트는 SSE 응답 — 모바일이 `clarify` 후 동일 ChatStreaming UI 재사용 가능.

9. **AC9 — 모바일 ChatStreaming UI (`features/meals/ChatStreaming.tsx`) (epic AC1, AC7, NFR-UX1, NFR-UX3)**: `mobile/features/meals/ChatStreaming.tsx` 신규. props `{ mealId: string; isOnline: boolean }`. 흐름:
   - 마운트 시 `useMealAnalysisStream(mealId)` hook 호출(AC10) — SSE 또는 polling 자동 선택.
   - 본문 영역: 누적 `text` state(token delta append) — 점진 렌더(`<Text>{text}</Text>` + 자동 스크롤 bottom).
   - clarification 분기: `event: clarify` 또는 polling `needs_clarification` 응답 시 chip 리스트(`Pressable`) 노출 → 사용자 탭 시 `POST /v1/analysis/clarify` mutation + chip 제거 + 본문 reset + 재 stream 시작.
   - 완료 시: `done` payload의 `feedback_text` 본문 + `MacroCard`(접힘, AC11) + `FitScoreBadge`(`[meal_id].tsx` 컴포넌트 재사용 또는 inline) + `DisclaimerFooter` 노출(AC12).
   - 에러 시: `event: error` 또는 polling timeout 시 *"분석에 실패했어요 — 다시 시도"* 메시지 + Retry 버튼 노출.
   - `isOnline=false` 시 컴포넌트 *진입 자체 차단* — 부모(`[meal_id].tsx`)가 가드(NFR-R4 정합 — 오프라인 시 read-only).
   - structlog 등가 — `console.warn`/`Sentry.captureException` 기록 시 `meal_id` 만 raw, raw_text/feedback 본문 X(NFR-S5).

10. **AC10 — `useMealAnalysisStream` hook (AC6, AC9)**: `mobile/features/meals/useMealAnalysisStream.ts` 신규. 시그니처 `(mealId: string) => { state: StreamState; reset: () => void; submitClarification: (value: string) => Promise<void> }`. `StreamState`: `{ phase: "connecting"|"streaming"|"clarify"|"done"|"error"|"polling"; text: string; citations: Citation[]; clarificationOptions?: Option[]; result?: DonePayload; error?: ProblemDetail; mode: "sse"|"polling" }`. 흐름:
   - 마운트 시 `react-native-sse`로 `POST /v1/analysis/stream` SSE 연결 — Authorization 헤더 + Content-Type: application/json + body 전송.
   - 이벤트 핸들러 — `progress`/`token`/`citation`/`clarify`/`done`/`error` 각각 state 갱신.
   - `EventSource.onerror` 또는 `event: error` 수신 + `done`/`clarify` 미수신 시 → `setTimeout(() => switchToPolling(), 1500)` (AC6 1.5초 강등).
   - polling 모드: `setInterval(1500)` + `GET /v1/analysis/{mealId}` 호출 + 동일 state 갱신.
   - cleanup: `eventSource.close()` + `clearInterval()` 멱등 호출. component unmount 시 자동.
   - `submitClarification(value)`: `POST /v1/analysis/clarify` 호출 + state reset(`text=""`, `phase="streaming"`) + 새 SSE 응답 stream 처리 진입.

11. **AC11 — `MacroCard` 보조 카드 (NFR-UX3)**: `mobile/features/meals/MacroCard.tsx` 신규(또는 ChatStreaming 인접 inline). props `{ macros: MealMacros }`. 디폴트 *접힘* 상태 — *"매크로 자세히 보기"* `Pressable` 헤더 → 탭 시 4개 수치(`탄 ${carbohydrate_g}g · 단 ${protein_g}g · 지 ${fat_g}g · ${energy_kcal} kcal`) 노출. NFR-UX3 SOT — *단순 g/kcal 수치는 채팅 본문이 아닌 별도 데이터 카드(접힘 가능)*. 채팅 본문은 코칭 톤 자연어 우선(NFR-UX1).

12. **AC12 — DisclaimerFooter 노출 (FR11, epic AC8)**: ChatStreaming `done` 분기 카드 *최하단*에 `DisclaimerFooter`(`mobile/features/legal/DisclaimerFooter.tsx`, Story 1.3 컴포넌트) 1줄 노출 — *"건강 목표 부합도 점수 — 의학적 진단이 아닙니다"*. 컴포넌트 변경 X(이미 const SOT — Story 1.3 정합). 단, `clarify` 또는 `error` 분기에는 노출 X — *분석 결과* 노출 시점에만(FR11 의미 정합).

13. **AC13 — 종단 지연 (NFR-P1) p50 ≤ 4초 / p95 ≤ 8초 (사진 OCR 포함)**: 측정 지점 — 모바일 `meals/input.tsx` 제출 → `[meal_id].tsx` 진입 → ChatStreaming `event: done` 수신. 사진 OCR 경로(Story 2.3 `/v1/meals/images/parse`) + meal POST + analysis SSE 합산. 본 스토리는 *측정 인프라*(Sentry transaction `op="analysis.sse.complete"` + tag mode=sse|polling) 만 박음 — 실 KPI 측정은 Story 3.8 LangSmith / Story 8.4 polish(deferred).

14. **AC14 — `[meal_id].tsx` ChatStreaming 통합 (epic AC1, D5 변경 정합)**: `mobile/app/(tabs)/meals/[meal_id].tsx` 갱신 — 기존 *"AI에게 질문하기 (Epic 3 통합 후 활성화)"* disabled placeholder 제거 → ChatStreaming 활성 진입점으로 교체. UX 분기:
   - meal `analysis_summary === null`(최초 분석 — `meal_analyses` row 없음) + `isOnline=true` → *"AI 분석 시작"* `Pressable` 노출 → 탭 시 ChatStreaming 컴포넌트 expand(또는 같은 화면 inline 렌더).
   - meal `analysis_summary !== null`(이미 분석 완료 — `meal_analyses` JOIN populated) → **이전 분석 결과 카드 즉시 표시**(피드백 본문 + 매크로 보조 카드 + fit_score 배지 + DisclaimerFooter). ChatStreaming 미마운트 — 추가 LLM 호출 0. 재분석 트리거(*"AI 다시 분석"* 버튼)는 Story 8.4 polish OUT(D5 결정 정합).
   - `isOnline=false` 시 — `analysis_summary === null` 케이스만 차단(*"오프라인 — 온라인 시 분석 가능"*). `analysis_summary !== null`은 캐시 데이터 표시 정상(NFR-R4 read-only 정합).
   - ChatStreaming `done` 후 `queryClient.invalidateQueries({ queryKey: ['meals'] })` — 7일 캐시 갱신 → 다음 list 응답에 `analysis_summary` populated → `[meal_id].tsx` 재진입 시 *"AI 분석 시작"* 버튼 미노출(이전 결과 즉시 표시).
   - 상세 화면 본문은 Story 3.6 `feedback.text` full text 노출 — 목록 화면 1줄 `feedback_summary`와 별개(AC17 derive helper 정합).

15. **AC15 — `react-native-sse` 의존성 추가 (architecture line 149)**: `mobile/package.json` `dependencies`에 `"react-native-sse": "^1.2"` 추가. `expo install` 호환 검증(SDK 54 + RN 0.81 호환). 단순 `EventSource` polyfill — Authorization 헤더 + POST body 송신 가능(architecture R2 mitigation 정합).

16. **AC16 — NFR-S5 마스킹 (Story 3.6 패턴 정합)**: 라우터 INFO 로그 1줄 — `analysis.sse.complete` with `meal_id` / `mode`(sse|polling) / `phase_count`(progress emit 수) / `token_count`(emit 수) / `citation_count` / `used_llm` / `final_fit_score` / `latency_ms` / `persisted`(bool — meal_analyses UPSERT 성공 여부). raw_text / feedback 본문 텍스트 / parsed_items name / allergies / weight / height raw 출력 X. polling 라우터 동일 패턴(`analysis.poll.fetch`). clarify 라우터 동일(`analysis.clarify.resume`). RFC 7807 error 응답 본문에는 `code` + `title`만 노출 — `detail`은 일반화된 메시지(예: *"분석을 완료하지 못했어요"*) — 내부 stack/exception 메시지 leak 차단(Story 1.2 정합).

17. **AC17 — `meal_analyses` 테이블 신규 + UPSERT 영속화 (D5 결정 — 식단 *관리* 앱 본연의 UX 정합)**: alembic 마이그레이션 `0012_create_meal_analyses.py` 신규. 스키마:
    - `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`.
    - `meal_id UUID NOT NULL REFERENCES meals(id) ON DELETE CASCADE` — 1:1 관계(UNIQUE 제약).
    - `user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE` — Story 4.3 user-level 리포트 입력 + 소유권 검증 redundant 가드.
    - **fit score 컬럼**: `fit_score INT NOT NULL CHECK (0-100)` / `fit_score_label TEXT NOT NULL CHECK IN ('allergen_violation','low','moderate','good','excellent')` (5-band, `MealAnalysisSummary` 정합) / `fit_reason TEXT NOT NULL` (`'ok'|'allergen_violation'|'incomplete_data'`, Story 3.5 정합).
    - **매크로 컬럼**: `carbohydrate_g NUMERIC NOT NULL` / `protein_g NUMERIC NOT NULL` / `fat_g NUMERIC NOT NULL` / `energy_kcal INT NOT NULL` (식약처 OpenAPI 키 정합 + `MealMacros` 정합).
    - **feedback 컬럼**: `feedback_text TEXT NOT NULL` (full LLM 본문 — 상세 화면용) / `feedback_summary TEXT NOT NULL CHECK (length(feedback_summary) <= 120)` (1줄 — 목록 화면용, AC18) / `citations JSONB NOT NULL DEFAULT '[]'` (`[{source, doc_title, published_year}]` 배열, Story 3.6 Citation 정합) / `used_llm TEXT NOT NULL CHECK IN ('gpt-4o-mini','claude','stub')`.
    - **타임스탬프**: `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` / `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` + `onupdate=now()`.
    - **인덱스**: `CREATE UNIQUE INDEX idx_meal_analyses_meal_id_unique ON meal_analyses (meal_id)` (1 meal = 1 analysis, 재분석은 UPSERT) + `CREATE INDEX idx_meal_analyses_user_id_created_at ON meal_analyses (user_id, created_at DESC)` (Story 4.3 주간 리포트 forward-compat).
    
    **UPSERT 패턴**: SSE generator의 `event: done` emit *직전* `INSERT ... ON CONFLICT (meal_id) DO UPDATE SET ...` 단일 SQL 실행. fresh session(`request.app.state.session_maker()`)으로 분리(라우터 진입 시점 `DbSession`은 SSE generator 진입 후 일찍 release 가능 — `EventSourceResponse` 라이프사이클 정합). UPSERT 실패는 *fatal X* — Sentry capture + log warning + SSE는 정상 `event: done` emit 진행(사용자에게 결과는 보임, 다음 재진입 시 미저장이라 다시 분석 — graceful degradation). `persisted: bool` 필드 NFR-S5 log에 기록(AC16).
    
    **`feedback_summary` derive helper**: `app/services/feedback_summary.py` 신규. 함수 `def derive_feedback_summary(text: str, *, max_chars: int = 120) -> str`:
    - `## 평가` 섹션 *첫 문장*(첫 마침표/물음표/느낌표까지) 추출.
    - 추출 실패(섹션 없음) 시 *전체 텍스트 첫 120자* fallback.
    - `## 다음 행동` / `## 평가` 마크다운 헤더는 strip.
    - 120자 초과 시 `...` suffix 포함 truncate.
    - 단위 테스트 `tests/services/test_feedback_summary.py` ≥ 5 케이스(평가 섹션 있음/없음/짧은 텍스트/긴 텍스트/마크다운 strip).

18. **AC18 — `GET /v1/meals` 응답 `analysis_summary` 채움 (D5 결정 — 목록 화면 점수 배지 표시)**: `api/app/api/v1/meals.py:list_meals` 갱신:
    - SQLAlchemy 쿼리에 `.options(selectinload(Meal.analysis))` 추가 — N+1 회피 + 단일 round-trip 로딩.
    - `_meal_to_response(meal: Meal)` 갱신 — `meal.analysis` (ORM relationship) 존재 시 `MealAnalysisSummary` 빌드, 미존재 시 `None`.
    - `Meal` ORM 모델에 `analysis: Mapped[MealAnalysis | None] = relationship(back_populates="meal", uselist=False, lazy="raise_on_sql")` 추가 — `lazy="raise_on_sql"` 강제로 implicit lazy load 차단(N+1 가드).
    - `_meal_to_response` 시그니처 변경(`meal: Meal` 그대로 — relationship으로 자연 access). `MealAnalysisSummary._validate_score_label_consistency` 검증은 그대로 통과(Story 2.4 invariant 보존).
    - GET /v1/meals 응답 schema 변경 X — `analysis_summary` 필드는 이미 정의됨(Story 2.4 forward-compat 슬롯). 본 스토리는 *항상 null*에서 *실 데이터*로 전환만.
    - 기존 GET /v1/meals 단위 테스트 — `analysis_summary === null` 단언이 있을 수 있음(Story 2.4 baseline). 갱신 검증: 본 스토리에서 *meal_analyses row가 없는 meal*은 여전히 `null` 응답이라 회귀 0건. *row 있는 meal*만 populated. 신규 테스트 케이스 ≥ 4 (analysis 없음 → null / analysis 정상 → 5-band label 매핑 / 알레르기 위반 → fit_score=0 + label='allergen_violation' / 다중 meal 일부만 analysis 보유 → 정확히 매핑).

## Tasks / Subtasks

- [x] **Task 1 — `react-native-sse` 의존성 + Settings 신규 필드 (AC15)**
  - [x] 1.1 `mobile/package.json` `dependencies`에 `"react-native-sse": "^1.2"` 추가. `pnpm install` 또는 `npm install` 실행 → lock 갱신.
  - [x] 1.2 import 검증 — `mobile/features/meals/useMealAnalysisStream.ts`에서 `import EventSource from 'react-native-sse';` 컴파일 통과 확인.
  - [x] 1.3 `api/app/core/config.py` `Settings`에 신규 필드(선택) — `analysis_polling_interval_seconds: float = 1.5` / `analysis_polling_max_attempts: int = 30` / `analysis_token_chunk_chars: int = 24` / `analysis_token_chunk_interval_ms: int = 30`. 모바일 hard-code도 무방하나 백엔드 polling AC9의 polling 응답 헤더 `Retry-After`는 settings 참조.

- [x] **Task 2 — 신규 예외 카탈로그 (AC2 error code, AC9, Task 6)**
  - [x] 2.1 `api/app/core/exceptions.py`에 `AnalysisStreamError(BalanceNoteError)` base + 3 서브클래스 추가:
    - `AnalysisStreamConsentMissingError(AnalysisStreamError)` — status 403, code `analysis.consent.missing`. (기존 `AutomatedDecisionConsentMissingError` 재사용 가능 — 본 분기는 *deduplication* 위해 wire 시점에 reuse 결정. 별도 클래스 추가 X — `Depends(require_automated_decision_consent)` 위반 시 기존 `AutomatedDecisionConsentMissingError`가 RFC 7807 403 변환).
    - `AnalysisMealNotFoundError(AnalysisStreamError)` — status 404, code `analysis.meal.not_found`. meals row 미존재 또는 user 비소유. enumeration 차단(소유권 미일치도 동일 응답).
    - `AnalysisCheckpointerUnavailableError(AnalysisStreamError)` — status 503, code `analysis.checkpointer.unavailable`. `app.state.analysis_service is None` 분기(D10 graceful — Story 3.3 lifespan 패턴 정합).
    - `AnalysisClarifyValidationError(AnalysisStreamError)` — status 422, code `analysis.clarify.invalid`. `aresume` ValueError catch.
  - [x] 2.2 *기존 `AnalysisGraphError` / `AnalysisNodeError` / `AnalysisStateValidationError`* 재사용 — 라우터 노출 신규 분기는 위 4건만(BalanceNoteError 글로벌 핸들러가 RFC 7807 변환).

- [x] **Task 3 — SSE event helper 모듈 신규 (AC2, AC4)**
  - [x] 3.1 `api/app/services/sse_emitter.py` 신규 — pure helper(deps 미사용). 함수:
    - `def chunk_text_for_streaming(text: str, *, chunk_chars: int = 24) -> Iterable[str]` — NFC 정규화 후 char 단위 분할(grapheme cluster 안전 — `regex` 라이브러리 미도입 대신 stdlib `unicodedata` 사용. 단순 `list(text)` + `chunk_chars` slice면 한국어 자모결합은 NFC 후 단일 codepoint이라 안전. emoji ZWJ 시퀀스는 본 스토리 OUT — 피드백 텍스트는 LLM 자연어 한국어 본문이라 emoji 출현 빈도 낮음, 발생 시 *cosmetic* 분리 — Story 8.4 polish).
    - `def event_progress(phase: str, elapsed_ms: int) -> ServerSentEvent` — sse_starlette `ServerSentEvent` builder. event="progress" + data=json.dumps({"phase": phase, "elapsed_ms": elapsed_ms}, ensure_ascii=False).
    - `def event_token(delta: str) -> ServerSentEvent` — event="token" + data=json.dumps({"delta": delta}, ensure_ascii=False).
    - `def event_citation(index: int, citation: Citation) -> ServerSentEvent` — event="citation" + data=json.dumps({...}, ensure_ascii=False).
    - `def event_clarify(options: list[ClarificationOption]) -> ServerSentEvent` — event="clarify" + data.
    - `def event_done(payload: AnalysisDonePayload) -> ServerSentEvent` — event="done" + data.
    - `def event_error(problem: ProblemDetail) -> ServerSentEvent` — event="error" + data=problem.to_response_dict() JSON.
  - [x] 3.2 `AnalysisDonePayload(BaseModel)` Pydantic 모델 신규 — `app/services/sse_emitter.py` 또는 `app/api/v1/analysis.py` 모듈 const(인접 정의 권장). fields: `meal_id: UUID` / `final_fit_score: int` / `fit_score_label: Literal[...]` / `macros: MealMacros` / `feedback_text: str` / `citations_count: int` / `used_llm: Literal["gpt-4o-mini", "claude", "stub"]`. `MealMacros`는 `app/api/v1/meals.py:MealMacros` 재사용(import).
  - [x] 3.3 단위 테스트 `tests/services/test_sse_emitter.py` 신규 — 6 케이스:
    - `chunk_text_for_streaming` ASCII 영문 + 한국어 자모결합 정상 분할 검증.
    - 빈 문자열 → 빈 iterable.
    - 1글자 → 1 chunk.
    - chunk_chars=1 정상 동작(extreme).
    - `event_token` JSON `ensure_ascii=False` — 한국어 raw byte 검증(token 비용 절감).
    - `event_error` ProblemDetail 정확한 직렬화(type/title/status/code/detail/instance).

- [x] **Task 4 — 라우터 신규 `/v1/analysis/*` (AC1, AC2, AC3, AC6, AC7, AC8, AC16)**
  - [x] 4.1 `api/app/api/v1/analysis.py` 신규. APIRouter 1개 + 3 endpoint(POST stream / GET poll / POST clarify).
  - [x] 4.2 module-level constant — `_DONE_EVENT_TIMEOUT_SECONDS: Final[float] = 30.0`(SSE 전체 budget cap — Story 3.6 router 25s + chunking margin), `_TOKEN_CHUNK_CHARS: Final[int] = 24`, `_TOKEN_CHUNK_INTERVAL_MS: Final[int] = 30`, `_PHASE_NAMES = ("parse", "retrieve", "evaluate", "feedback")`.
  - [x] 4.3 `class AnalysisStreamRequest(BaseModel)` — `meal_id: UUID`(extra="forbid"). `class AnalysisClarifyRequest(BaseModel)` — `meal_id: UUID` + `selected_value: str = Field(min_length=1, max_length=80)`(Story 3.4 정합).
  - [x] 4.4 helper `async def _resolve_meal(db: AsyncSession, *, meal_id: UUID, user_id: UUID) -> Meal` — `meals` row 소유권 + `deleted_at IS NULL` 검증. 미일치 시 `AnalysisMealNotFoundError` raise.
  - [x] 4.5 helper `async def _get_analysis_service(request: Request) -> AnalysisService` — `app.state.analysis_service is None` 시 `AnalysisCheckpointerUnavailableError` raise.
  - [x] 4.6 helper `def _state_to_done_payload(state: MealAnalysisState, *, meal_id: UUID) -> AnalysisDonePayload` — `state.fit_evaluation` + `state.feedback` + 매크로 합산(`aggregate_meal_macros`(`app.domain.fit_score` Story 3.5 helper) 또는 `state.retrieval` 기반 — 단순 합산 helper inline). `fit_score_label`은 `to_summary_label(state.fit_evaluation.fit_label)`(Story 3.5 D-2 helper 재사용).
  - [x] 4.7 helper `def _state_to_polling_response(state: MealAnalysisState, *, meal_id: UUID, meal_exists: bool) -> dict[str, Any]` — AC7 분기:
    - state.feedback 존재 → `{"status": "done", "result": _state_to_done_payload(...)}`.
    - state.needs_clarification → `{"status": "needs_clarification", "options": state.clarification_options}`.
    - state.node_errors → `{"status": "error", "problem": {...}}`.
    - state empty + meal_exists → `{"status": "in_progress", "phase": "queued"}` (202 status).

- [x] **Task 5 — `POST /v1/analysis/stream` SSE generator (AC1-AC4, AC9, AC16)**
  - [x] 5.1 함수 시그니처 — `async def stream_analysis(request: Request, body: AnalysisStreamRequest, db: DbSession, user: Annotated[User, Depends(require_basic_consents)], _consent: Annotated[User, Depends(require_automated_decision_consent)]) -> EventSourceResponse`.
  - [x] 5.2 generator 흐름:
    1. `meal = await _resolve_meal(db, meal_id=body.meal_id, user_id=user.id)`.
    2. `service = await _get_analysis_service(request)`.
    3. `start = time.monotonic()`.
    4. `async def _generator()`:
       - **emit progress("parse")** 즉시 — TTFT 보장.
       - 백그라운드로 `analysis_state = await service.run(meal_id=body.meal_id, user_id=user.id, raw_text=meal.raw_text)` 호출. `await`이 종료될 때까지 1차 buffered.
       - 도중 phase 신호는 미세하게 — *본 MVP는 4단계 stub progress만*. 상세 phase 추적은 Story 8.4 polish(LangGraph `astream_events()` 통합).
       - 완료 후 분기:
         - state.needs_clarification → emit `clarify`(options=state.clarification_options) → return.
         - state.node_errors *AND* state.feedback 없음 → emit `error`(`AnalysisNodeError` → ProblemDetail) → return.
         - state.feedback 정상 → 본문 청킹 + citation 순차 emit + `done`.
    5. **본문 chunking emit**:
       - `text = state.feedback.text`.
       - `for chunk in chunk_text_for_streaming(text, chunk_chars=_TOKEN_CHUNK_CHARS):`
         - `yield event_token(chunk)`.
         - `await asyncio.sleep(_TOKEN_CHUNK_INTERVAL_MS / 1000.0)`.
       - `for idx, citation in enumerate(state.feedback.citations):`
         - `yield event_citation(idx, citation)`.
       - `yield event_done(_state_to_done_payload(state, meal_id=body.meal_id))`.
    6. **try/except**:
       - `BalanceNoteError as exc` → `yield event_error(exc.to_problem(instance=str(request.url.path)))`.
       - `Exception as exc` (예상 외) → `sentry_sdk.capture_exception(exc)` + `yield event_error(_unexpected_problem())`. *generator는 정상 종료*(yield 후 return) — exception을 SSE 스트림 안에서 propagate X(클라이언트가 일관된 종료 이벤트 수신).
    7. **finally**: structlog `analysis.sse.complete` 1줄(AC16) — meal_id/mode="sse"/phase_count/token_count/citation_count/used_llm/final_fit_score/latency_ms.
  - [x] 5.3 `EventSourceResponse(_generator(), headers={"X-Stream-Mode": "sse"})` 반환. `media_type` 자동(text/event-stream).
  - [x] 5.4 `RATE_LIMIT_LANGGRAPH = "10/minute"` 데코레이터 적용 — `@router.post("/stream")` 위에 `request.app.state.limiter.limit(RATE_LIMIT_LANGGRAPH)` (slowapi 패턴). 분산 limiter는 `app.state.limiter`(`main.py:104` Redis or memory backend) 재사용.

- [x] **Task 6 — `GET /v1/analysis/{meal_id}` polling (AC6, AC7, AC16)**
  - [x] 6.1 함수 시그니처 — `async def poll_analysis(request: Request, meal_id: UUID, db: DbSession, user: Annotated[User, Depends(require_basic_consents)]) -> JSONResponse`.
  - [x] 6.2 흐름:
    1. `meal = await _resolve_meal(db, meal_id=meal_id, user_id=user.id)` (404 분기 정상).
    2. `service = await _get_analysis_service(request)`.
    3. `state = await service.aget_state(thread_id=f"meal:{meal_id}")`.
    4. `payload = _state_to_polling_response(state, meal_id=meal_id, meal_exists=True)`.
    5. status_code 분기:
       - status="done" or "needs_clarification" or "error" → 200.
       - status="in_progress" → 202 + `Retry-After` 헤더(`settings.analysis_polling_interval_seconds` 기본 1.5초 → ceil 2초).
    6. response 헤더 `X-Stream-Mode: polling` 강제(architecture line 322 정합).
    7. structlog `analysis.poll.fetch` — meal_id/mode="polling"/state_status/elapsed_since_start.
  - [x] 6.3 *PIPA 자동화 의사결정 동의는 미요구* — AC7 명시. *polling = 단순 조회*, automated decision은 분석 *호출* 시점 게이트. PIPA Art.35 정보주체 권리 정합(`require_basic_consents`만 wire).

- [x] **Task 7 — `POST /v1/analysis/clarify` resume (AC8, AC16)**
  - [x] 7.1 함수 시그니처 — `async def resume_clarification(request: Request, body: AnalysisClarifyRequest, db: DbSession, user: Annotated[User, Depends(require_basic_consents)], _consent: Annotated[User, Depends(require_automated_decision_consent)]) -> EventSourceResponse`.
  - [x] 7.2 흐름:
    1. `meal = await _resolve_meal(db, meal_id=body.meal_id, user_id=user.id)`.
    2. `service = await _get_analysis_service(request)`.
    3. generator 진입 — Task 5의 `_generator` 재사용 패턴(공통 helper로 추출 권장 — `_run_and_stream(service, *, meal_id, user_id, raw_text=None, clarify_value=None)`).
    4. `clarify_value` 분기 — `aresume(thread_id=..., user_input={"selected_value": clarify_value})` 호출(Story 3.4 패턴 정합 — `force_llm_parse=True` 자동 주입).
    5. ValueError(빈 selected_value) catch — `AnalysisClarifyValidationError` raise → 422.
    6. 결과 분기는 Task 5와 동일(needs_clarification 재발 시 `event: clarify` 다시 emit — Story 3.4 1회 한도 가드 보존).
  - [x] 7.3 동일 rate limit 적용(`RATE_LIMIT_LANGGRAPH`).

- [x] **Task 8 — main.py 라우터 등록 (AC1)**
  - [x] 8.1 `api/app/main.py` import 라인 추가 — `from app.api.v1 import analysis as analysis_router`.
  - [x] 8.2 `app.include_router` 추가 — `app.include_router(analysis_router.router, prefix="/v1/analysis", tags=["analysis"])`.

- [x] **Task 9 — 단위 테스트 백엔드 (T5 기반 + AC2/AC3/AC6/AC7/AC8 contract)**
  - [x] 9.1 `tests/api/v1/test_analysis_stream.py` 신규 — 12 케이스(`@pytest.mark.asyncio` 자동 적용):
    - happy path — 정상 meal + analysis_service mock(`run` 결과 fixture FeedbackOutput) → SSE 응답에 `progress` ≥1 + `token` ≥1 + `citation` ≥0 + `done` 정확히 1회 + 종료 후 close. event 순서 검증(progress → token → citation → done).
    - PIPA basic consent 부재 → 403 + `consent.basic.missing`.
    - PIPA automated_decision 부재 → 403 + `consent.automated_decision.missing`.
    - meal 미존재(잘못된 UUID) → 404 + `analysis.meal.not_found`.
    - meal 비소유(다른 user_id의 meal_id) → 404(enumeration 차단).
    - meal soft-deleted → 404.
    - `app.state.analysis_service is None` → 503 + `analysis.checkpointer.unavailable`.
    - state.needs_clarification=True 결과 → SSE `clarify` 정확히 1회 + `done` 미발생.
    - state.node_errors 결과 → SSE `error` 정확히 1회.
    - rate limit 초과(11회 호출 in 1분) → 429.
    - 빈 raw_text meal → mock state는 정상 — token chunk 0건 + done 정상 emit(빈 text 가드 검증).
    - 비-ASCII raw_text(한국어 emoji 포함) → token chunks 한국어 정상 분할.
  - [x] 9.2 `tests/api/v1/test_analysis_polling.py` 신규 — 8 케이스:
    - state empty + meal 존재 → 202 + `{"status": "in_progress", "phase": "queued"}` + `Retry-After: 2`.
    - state.feedback 정상 → 200 + `{"status": "done", "result": {...}}`.
    - state.needs_clarification → 200 + `{"status": "needs_clarification", "options": [...]}`.
    - state.node_errors → 200 + `{"status": "error", "problem": {...}}`.
    - meal 미존재 → 404.
    - meal soft-deleted → 404.
    - PIPA basic 부재 → 403. (automated_decision은 미요구 — 통과).
    - 응답 헤더 `X-Stream-Mode: polling` 검증.
  - [x] 9.3 `tests/api/v1/test_analysis_clarify.py` 신규 — 6 케이스:
    - happy path — `aresume` mock 정상 결과 → SSE 정상 흐름 + `done` 1회.
    - 빈 selected_value → 422 + `analysis.clarify.invalid`.
    - 81자 selected_value(spec 한도 초과) → 422 (Pydantic ValidationError).
    - meal 미존재 → 404.
    - PIPA basic + automated_decision 둘 다 wire 검증.
    - aresume 후 needs_clarification=True 재발 → `event: clarify` 다시 emit(Story 3.4 1회 한도 — 본 라우터는 재진입 단순 처리).
  - [x] 9.4 `tests/services/test_sse_emitter.py` — Task 3.3 케이스(6건).

- [x] **Task 10 — `useMealAnalysisStream` hook 신규 (AC10)**
  - [x] 10.1 `mobile/features/meals/useMealAnalysisStream.ts` 신규.
  - [x] 10.2 type `StreamPhase = "connecting" | "streaming" | "clarify" | "done" | "error" | "polling"` + `StreamState` interface(AC10).
  - [x] 10.3 hook 흐름:
    - `useEffect`로 마운트 시 `react-native-sse` `EventSource` 생성. URL `${API_BASE}/v1/analysis/stream`. method "POST" + headers `{ Authorization: Bearer ${accessToken}, Content-Type: 'application/json' }` + body `JSON.stringify({ meal_id })`.
    - `eventSource.addEventListener("progress" | "token" | "citation" | "clarify" | "done" | "error", handler)` 6건 등록.
    - `eventSource.addEventListener("error", onErrorEvent)` — connection error vs server-emitted error 분기. server-emitted `event: error`는 위 등록 핸들러가 처리. connection error는 onErrorEvent가 polling 강등.
    - `done`/`clarify`/`error` 수신 시 — `eventSource.close()` 호출 + state.phase 갱신.
    - connection error(SSE 끊김) + (`done`/`clarify`/`error` 미수신) → `setTimeout(() => switchToPolling(), 1500)`.
  - [x] 10.4 polling 흐름:
    - `setInterval(1500)` + `fetch('/v1/analysis/{mealId}')` 호출 + JSON 파싱.
    - `status: 'done'` → state 갱신 + clearInterval + token chunks pseudo-emit(text 한 번에 set, 또는 빠르게 chunking — UX 정합).
    - `status: 'in_progress'` → 다음 interval 대기.
    - `status: 'needs_clarification'` / `status: 'error'` → state 갱신 + clearInterval.
    - 30회(45초) 후에도 in_progress → timeout error state.
  - [x] 10.5 `submitClarification(value)`:
    - `fetch('/v1/analysis/clarify', { method: 'POST', headers, body: JSON.stringify({ meal_id, selected_value: value }) })` 호출.
    - 응답이 SSE이므로 `react-native-sse` 같은 로직 재진입 — Task 10.3 SSE 핸들러 재사용.
    - state reset(`text=""`, `citations=[]`, `phase="streaming"`).
  - [x] 10.6 cleanup — useEffect return → `eventSource?.close()` + `clearInterval(pollingTimerRef.current)`. unmount 시 idempotent.

- [x] **Task 11 — `ChatStreaming` 컴포넌트 신규 (AC9, AC11, AC12)**
  - [x] 11.1 `mobile/features/meals/ChatStreaming.tsx` 신규.
  - [x] 11.2 props `{ mealId: string; isOnline: boolean; onAnalysisDone?: () => void }`.
  - [x] 11.3 layout(per phase):
    - phase "connecting" / "streaming" / "polling" — 본문(`<Text>{state.text}</Text>`) + 진행 안내 *"AI 분석 중…"* (스피너).
    - phase "clarify" — 본문 영역 + chip 리스트(`state.clarificationOptions.map(opt => <Pressable onPress={() => submitClarification(opt.value)}>...)`).
    - phase "done" — 본문 + `MacroCard`(접힘) + `FitScoreBadge`(`[meal_id].tsx`에서 추출 또는 inline 동일 디자인) + `DisclaimerFooter`.
    - phase "error" — *"분석에 실패했어요 — 다시 시도"* + Retry `Pressable`(`reset()` 호출 + 재 stream 시작).
  - [x] 11.4 `onAnalysisDone` callback — phase=="done" 진입 시 1회 호출. 부모(`[meal_id].tsx`)가 `queryClient.invalidateQueries`.
  - [x] 11.5 `ScrollView` `ref` + `onContentSizeChange` → 자동 bottom scroll.
  - [x] 11.6 NFR-A3 폰트 스케일 200% 대응 — `flexShrink: 1` + 텍스트 wrap + 명시 lineHeight(`MealCard.tsx` 패턴 정합).
  - [x] 11.7 NFR-S5 — `console.error`/`console.warn` 기록 시 `meal_id` 만 raw, 본문 X. Sentry 통합은 본 스토리 OUT(deferred Story 8.4 — Sentry RN SDK는 Story 1.5+ Wired but breadcrumb only).

- [x] **Task 12 — `MacroCard` 신규 (AC11, NFR-UX3)**
  - [x] 12.1 `mobile/features/meals/MacroCard.tsx` 신규(또는 ChatStreaming inline). props `{ macros: MealMacros }`.
  - [x] 12.2 useState `expanded: boolean` 초기 `false`.
  - [x] 12.3 헤더 `Pressable` — 텍스트 *"매크로 자세히 보기 ▾"* / expanded 시 *"매크로 접기 ▴"* + 카드 본문 토글.
  - [x] 12.4 본문 — `탄 ${carbohydrate_g}g · 단 ${protein_g}g · 지 ${fat_g}g · ${energy_kcal} kcal` 1줄(MealCard.tsx 패턴 재사용).

- [x] **Task 13 — `[meal_id].tsx` ChatStreaming 통합 (AC14)**
  - [x] 13.1 `mobile/app/(tabs)/meals/[meal_id].tsx` 갱신.
  - [x] 13.2 기존 *"AI에게 질문하기 (Epic 3 통합 후 활성화)"* `View` placeholder 제거.
  - [x] 13.3 `useState analysisStarted: boolean` 추가 + *"AI 분석 시작"* `Pressable` (analysisStarted=false + isOnline=true + summary===null 분기에서만 노출). 탭 시 `setAnalysisStarted(true)` → ChatStreaming 마운트.
  - [x] 13.4 ChatStreaming `onAnalysisDone` callback — `queryClient.invalidateQueries({ queryKey: ['meals'] })`.
  - [x] 13.5 `summary !== null` 분기는 기존 그대로 유지 + ChatStreaming 미마운트(이미 분석 완료된 meal은 summary 카드 + DisclaimerFooter 노출). D5 결정(영속화 IN — AC17/AC18) 정합으로 GET /v1/meals 응답이 `analysis_summary` populated 시 새로고침 후 재진입에도 *이전 분석 즉시 표시* — 추가 LLM 호출 0. 재분석 트리거(*"AI 다시 분석"*)는 Story 8.4 polish OUT.
  - [x] 13.6 `isOnline=false` 시 *"AI 분석 시작"* 버튼 disabled + 안내 *"오프라인 — 온라인 시 분석 가능"*(NFR-R4 정합).

- [x] **Task 14 — OpenAPI typegen + 모바일 client 갱신 (AC1, AC7, AC8)**
  - [x] 14.1 `pnpm gen:api`(또는 `bash scripts/gen_openapi_clients.sh`) 실행 — `mobile/lib/api-client.ts` + (web 있으면) 자동 갱신.
  - [x] 14.2 갱신 검증 — `paths`에 `/v1/analysis/stream` / `/v1/analysis/{meal_id}` / `/v1/analysis/clarify` 3 endpoint 등재. SSE 라우터는 OpenAPI 자동 schema가 application/json response로 inferred(SSE는 text/event-stream — `EventSourceResponse` content_type 명시 필요 시 라우터 데코레이터 `responses={200: {"content": {"text/event-stream": {}}}}` 추가, fallback은 그대로 inferred).
  - [x] 14.3 SSE 호출은 OpenAPI client 미사용 — 모바일 hook 직접 fetch + react-native-sse. polling/clarify는 OpenAPI typed client 사용 권장(typed types for `AnalysisDonePayload` / `AnalysisStreamRequest` / etc.).

- [x] **Task 15 — 모바일 단위 테스트 (AC9, AC10, AC11)**
  - [x] 15.1 모바일은 현재 단위 테스트 인프라 부재(pnpm test 미설정 — `package.json` line 5-12 scripts에 test 부재). 본 스토리는 *컴포넌트 레벨 테스트 미강제* — 후속 스토리 Story 8.4 polish가 RN 테스트 인프라(jest + react-native-testing-library) 도입. 현 스토리는 *수동 verification* + tsc --noEmit 통과만 가드.
  - [x] 15.2 `pnpm tsc --noEmit`(또는 `expo lint`) 0 에러 강제 — TypeScript 타입 정합.

- [x] **Task 16 — `meal_analyses` 영속화 (AC17, AC18)**
  - [x] 16.1 `api/app/db/models/meal_analysis.py` 신규 — SQLAlchemy ORM 모델. `Meal.id` FK + `User.id` FK + 12 컬럼(AC17 명시). `Mapped`/`mapped_column` 패턴 정합(Story 2.x meal.py).
  - [x] 16.2 `api/app/db/models/meal.py` 갱신 — `analysis: Mapped[MealAnalysis | None] = relationship(back_populates="meal", uselist=False, lazy="raise_on_sql")` 추가. import는 `TYPE_CHECKING` 가드(circular import 회피).
  - [x] 16.3 `api/alembic/versions/0012_create_meal_analyses.py` 신규 — `op.create_table` + 5 CHECK 제약 + 2 인덱스(UNIQUE meal_id + user_id+created_at DESC). `op.f("idx_*")` naming convention(Story 1.5 패턴 정합).
  - [x] 16.4 `api/app/services/feedback_summary.py` 신규 — `derive_feedback_summary(text: str, *, max_chars: int = 120) -> str` 함수. AC17 명시 4 분기.
  - [x] 16.5 `api/app/services/meal_analysis_persistence.py` 신규 — `async def upsert_meal_analysis(session: AsyncSession, *, meal_id: UUID, user_id: UUID, payload: AnalysisDonePayload, full_text: str, fit_reason: str, citations: list[Citation]) -> bool` 함수. INSERT ... ON CONFLICT (meal_id) DO UPDATE SET ... 단일 SQL. 성공/실패 bool 반환(예외 swallow + Sentry capture + log warning — graceful degradation per AC17).
  - [x] 16.6 `api/app/api/v1/analysis.py` SSE generator(Task 5) 갱신 — `event: done` emit *직전* `async with request.app.state.session_maker() as persist_session: persisted = await upsert_meal_analysis(persist_session, ...); await persist_session.commit()`. `persisted` bool을 NFR-S5 log에 추가(AC16).
  - [x] 16.7 `api/app/api/v1/meals.py:list_meals` 갱신 — `select(Meal).options(selectinload(Meal.analysis)).where(...)` + `_meal_to_response`에서 `meal.analysis` access → `MealAnalysisSummary` 빌드(또는 None).
  - [x] 16.8 단위 테스트:
    - `tests/services/test_feedback_summary.py` 신규 — 5 케이스(AC17).
    - `tests/services/test_meal_analysis_persistence.py` 신규 — 5 케이스(INSERT 신규 / UPDATE 기존 / DB 장애 graceful False / `meal_id` UNIQUE 위반 → UPDATE 분기 / `citations` JSONB roundtrip).
    - `tests/api/v1/test_meals.py` 갱신 — list_meals 신규 케이스 4건(AC18).
    - `tests/api/v1/test_analysis_stream.py` 갱신 — happy path에 `meal_analyses` row INSERT 검증 추가 + 두 번째 같은 meal 호출 시 UPDATE 분기 검증(`updated_at` 갱신 + row count 1 유지).

- [x] **Task 17 — 회귀 가드 검증 + 운영 hardening**
  - [x] 17.1 `pytest -q` 전체 통과 + coverage ≥ 70%(`--cov-fail-under=70` 강제). 신규 라우터 + helper + ORM 자체 coverage ≥ 85%(라우터 + sse_emitter + meal_analysis_persistence + feedback_summary).
  - [x] 17.2 `ruff check` + `ruff format --check` + `mypy app tests` 0 에러.
  - [x] 17.3 Story 3.3 / 3.4 / 3.5 / 3.6 회귀 0건 — 특히 `test_pipeline.py` / `test_self_rag.py` / `test_evaluate_fit.py` / `test_generate_feedback.py` / `test_llm_router.py` / `test_analysis_service.py` 통과(본 스토리는 노드 자체 변경 X — 라우터 + 서비스 wrapper + DB 모델 신규 추가).
  - [x] 17.4 `compile_pipeline` 변경 X — `test_pipeline.py:test_compile_pipeline_smoke` 재변경 없이 통과.
  - [x] 17.5 `analysis_service.py` 변경 X — 기존 `run`/`aget_state`/`aresume` 시그니처 그대로 사용(라우터가 wrapper만 추가).
  - [x] 17.6 alembic 마이그레이션 `0012_create_meal_analyses.py` `upgrade` + `downgrade` 양방향 검증 — `tests/conftest.py` 테스트 DB 재생성 흐름에서 자동 적용. downgrade도 `op.drop_table("meal_analyses")` 정상 동작.
  - [x] 17.7 `tests/conftest.py:_truncate_user_tables` autouse fixture에 `meal_analyses` 추가 — Story 3.6 패턴 정합(per-test 격리 강화 — meal_analyses row가 다음 테스트로 leak 차단).

## Dev Notes

### 1. 핵심 사실관계 (Story 3.6 → 3.7 인계)

- **SSE 인프라는 이미 박혀 있음** — `sse-starlette>=2.2`(pyproject.toml line 40)는 Story 1.1 부트스트랩 시점에 설치되어 있음. `EventSourceResponse` + `ServerSentEvent` 직접 사용 가능.
- **`app.state.analysis_service`는 lifespan에서 init**(`api/app/main.py:127-130`) — `D10 graceful 분기`로 None 가능(checkpointer init 실패 시). 라우터는 None 가드 필수(AC1 + Task 4.5).
- **`AnalysisService.run` / `aget_state` / `aresume` 시그니처 변경 X** — Story 3.3/3.4 SOT 그대로 사용. `run`은 `meal_id` + `user_id` + `raw_text` + 옵션 `thread_id`. `aget_state`는 `thread_id` only. `aresume`은 `thread_id` + `user_input={"selected_value": ...}`.
- **`generate_feedback` 노드는 변경 X** — Story 3.6 buffered 패턴 보존(citation/ad-guard/구조 검증이 full text 필요). 본 스토리는 *서비스 레이어 위에 SSE wrapper만 박는다*.
- **`require_basic_consents` + `require_automated_decision_consent`는 이미 박혀 있음** — `api/app/api/deps.py:136-192`. analysis 라우터는 *두 게이트 모두* wire(LLM 비용 0 보호 + 데이터 정합 검증, deps.py:182-187 주석 명시).
- **3-tier rate limit 키도 이미 정의됨** — `api/app/main.py:59-62`: `RATE_LIMIT_LANGGRAPH = "10/minute"`. analysis 라우터는 본 키 적용(per-IP).

### 2. SSE 스트리밍 전략 D1 결정 (pseudo-streaming + early progress)

**문제**: NFR-P3(TTFT p50 ≤ 1.5초)는 *첫 token 도착*. Story 3.6 `generate_feedback`은 buffered 응답(citation/ad-guard/구조 검증이 full text 요구 — token-level streaming 시 후처리 회귀). 직접 LLM token streaming은 검증 회귀 + 라우터-노드 결합도 ↑.

**결정**:
- (a) **early `event: progress` heartbeat** — 라우터 진입 즉시 emit. TTFT는 *첫 emit 이벤트*까지(progress도 emit이므로 정의 충족 — 본 결정은 spec line 685 *"event: token" 첫 emit*과 미세하게 다름. spec literal "첫 token"은 본문 token 이벤트로 해석 가능 — 그러나 실 UX는 "분석 시작 신호"가 보이면 ≈만족. **본 결정은 *NFR-P3 의도(사용자 인지 latency)* 만족** — Spec deviation 명시: "TTFT는 first-emitted-event(progress 포함) 기준 — 본문 token-level 첫 emit은 cache hit 경로 ≤ 1.5초, cache miss 경로 ~3초").
- (b) **본문은 buffered + synthetic chunking** — 24자 / 30ms 간격 token emit. 한국어 평균 LLM 응답 길이 200-400자 → 250-500ms 추가 — UX는 "한 글자씩 흐르는" 정합(epic line 679).
- (c) **True LLM-token streaming은 Story 8.4 deferred** — `astream_events()` 통합 + post-processing 재구성(부분 token 스트림 + 마지막에 validated full text replace 또는 streaming 중 incremental validation).

**구현 가드**:
- `chunk_chars=24` / `interval_ms=30` settings 기본값 — env override로 운영 시 튜닝 가능(`analysis_token_chunk_chars` / `analysis_token_chunk_interval_ms`, Task 1.3).
- 한국어 grapheme cluster — NFC 정규화 후 `list(text)` 분할은 *대부분 안전*(자모결합은 NFC 후 단일 codepoint). emoji ZWJ 시퀀스 / fitzpatrick modifier 분리는 *cosmetic only* — 본 스토리는 cosmetic 수용 + Story 8.4 polish에서 `regex` 라이브러리 도입(현재 stdlib only로 회피).

### 3. polling 응답 구조 D2 결정 (status discriminator)

응답을 `{"status": "in_progress"|"done"|"needs_clarification"|"error", ...}` 단일 envelope으로 통일. 클라이언트 분기 단순화 + TypeScript discriminated union 자연 매핑. RFC 7807 응답은 `error` 분기에 nest(`{"status": "error", "problem": {...RFC 7807}}`) — 단순 200 + envelope이라 fetch 분기 단순(`response.ok` 분기 X — `payload.status === "error"`로 분기). 단, *meal 미존재 / 인증 실패* 같은 라우터 자체 4xx는 RFC 7807 글로벌 핸들러로 직접 응답(401/403/404 status code + RFC 7807 body — *envelope 미적용*). 즉 envelope는 *분석 자체의 상태 discriminator*만, 게이트/소유권은 일반 HTTP 분기.

### 4. clarification 5번째 이벤트 D3 결정 (spec extension)

epic AC2 line 685는 4 이벤트 type만 명시(`token` / `citation` / `done` / `error`). 그러나 Story 3.4 `needs_clarification` 흐름은 백엔드에 박혀 있고 라우터 노출 시점이 본 스토리. 옵션:

- (a) `event: clarify` 5번째 type 추가(spec extension).
- (b) `event: error` 사용 + payload에 `code: "analysis.needs_clarification"`. 의미적으로 *error*가 아니라 *user input required* — 부적절.
- (c) `event: done` payload에 `needs_clarification` boolean — *done의 의미*("분석 완료")와 충돌.

**결정**: (a) `event: clarify`. spec deviation 1건 — Story 3.4 SOT 정합 + UI 분기 명료성 우선. epic AC line 685의 4 이벤트는 *primary path*, `clarify`는 *Self-RAG 분기 path*로 자연 확장(`progress`도 동일하게 자연 확장 — TTFT 보장 안전망).

### 5. polling 1.5초 D4 결정 (architecture line 322 정합)

architecture line 530: *"SSE | 클라이언트가 `event: error` 수신 → 1.5초 후 polling 강등"*. polling interval도 1.5초(architecture line 322 *"RN SSE 끊김 ≥ 임계 시 1.5초 polling"*). 본 스토리는 SOT 그대로 적용 — 30회 ≈ 45초 cap(LLM 호출 25s outer budget + chunking margin + 2x 안전 여유). polling timeout 시 client는 사용자 안내 + retry CTA 노출.

### 6. NFR-S5 마스킹 / Sentry 통합 (Story 3.6 패턴 정합)

라우터 INFO 로그 1줄(AC16): `meal_id` / `mode` / `phase_count` / `token_count` / `citation_count` / `used_llm` / `final_fit_score` / `latency_ms`. *raw_text / feedback 본문 / parsed_items name / allergies / weight / height raw 출력 X*. SSE 본문에 노출되는 텍스트는 사용자 화면에 보이는 것과 동일이라 통신 path는 안전, log path만 가드. Sentry transaction `op="analysis.sse.complete"` + tag `mode=sse|polling` — 종단 latency 측정용. raw payload는 Story 8.4 mask_event hook이 1차 가드(Story 3.6 anchor 패턴 정합).

### 7. meal_analyses 영속화 D5 결정 (IN — 식단 *관리* 앱 본연 UX 정합)

**결정 변경 (2026-05-04 hwan 피드백 반영)**: 초기 D5는 영속화 OUT(Story 8.4 deferred)이었으나, 식단 *관리* 앱 본연의 UX 검토 후 IN으로 변경.

**문제**: 영속화 OUT 시 사용자 경험:
- `GET /v1/meals` 응답 `analysis_summary` 항상 null → 목록 화면 점수 배지가 *"AI 분석 대기"* 회색으로 표시.
- 어제 분석한 식단도 오늘 재로그인 시 *"분석 안 한 것처럼"* 보임 → 한 주 식습관 한눈에 안 보임.
- `[meal_id].tsx` 재진입 시 *"AI 분석 시작"* 버튼 다시 노출 → 사용자가 한 번 더 탭(Redis 캐시 hit으로 LLM 비용은 0이지만 UX 마찰).
- *식단 관리 앱*이 아닌 *음식 영양 1회 체크 앱* 인상 → 영업 차별화 카드 약화.

**해결 (D5=IN)**: `meal_analyses` 테이블 신규 + SSE `event: done` 시점 UPSERT + `GET /v1/meals` LEFT JOIN으로 `analysis_summary` populated.

**구현 범위**:
- 1 테이블 + 1 마이그레이션 (`0012_create_meal_analyses`).
- 1 ORM 모델 (`app/db/models/meal_analysis.py`) + `Meal.analysis` relationship 1줄.
- 2 helper 모듈 (`feedback_summary.py` + `meal_analysis_persistence.py`).
- 라우터 SSE generator에 UPSERT 1 분기 + `meals.py:list_meals` JOIN 1 분기.
- 테스트 ~14건(영속화 단위 + JOIN + UPSERT 분기 + feedback_summary derive).

**위험 평가**: *낮음*.
- 신규 테이블 — 기존 데이터 0건이라 마이그레이션 destructive risk 0.
- `analysis_summary === null` 분기는 보존 — meal_analyses row 없는 meal은 여전히 null 응답(회귀 0건).
- UPSERT 실패는 graceful — 사용자에게 결과는 보임, 다음 재진입 시 다시 분석.

**얻는 효과**:
- 한 주 식습관 한눈에 보임 → 식단 *관리* 앱 본연 UX.
- Story 4.3 주간 리포트가 자연스럽게 데이터 SOT 사용 가능 — `idx_meal_analyses_user_id_created_at DESC` 인덱스가 forward-compat.
- `[meal_id].tsx` 재진입 시 즉시 결과 표시 — 추가 LLM 호출 0.

**Re-analysis 처리**: 1 meal = 1 analysis (UNIQUE 제약 + UPSERT 패턴). 같은 meal 재분석 시 row 1개를 update — `updated_at` 갱신. 재분석 UI 트리거(*"AI 다시 분석"* 버튼)는 본 스토리 OUT(Story 8.4 polish — 정상 흐름은 *최초 분석 1회*만 wire).

### 8. 회피 사항 (Out of Scope)

- **True LLM-token streaming** — Story 8.4 polish (D1 결정 — pseudo-streaming + post-processing 회귀 0).
- **재분석 UI 트리거 (*"AI 다시 분석"* 버튼)** — Story 8.4 polish (D5 변경 정합 — 정상 흐름은 *최초 분석 1회*만 wire. UPSERT 인프라는 본 스토리에 박힘).
- **모바일 컴포넌트 단위 테스트 인프라(jest + RN testing library)** — Story 8.4 polish(현재 mobile/package.json 미설정).
- **Sentry RN SDK breadcrumb 정교화** — Story 8.4(현재는 console.warn fallback).
- **재분석 차단 로직(이미 분석된 meal 재시도 시 cache hit only로 LLM 호출 0)** — Story 3.6 Redis cache가 자연 가드 + 본 스토리 OUT(rate limit + cache hit 1차 보호 충분).
- **POST 요청 body로 SSE — react-native-sse 호환성** — 라이브러리는 POST + body 지원(architecture R2 mitigation 정합). browser EventSource API는 POST 미지원 — Web 클라이언트는 본 스토리 OUT(epic line 676 *"모바일 SSE"* 명시 — Web은 Story 4.3 주간 리포트 흐름이 SSE 미사용, polling만).
- **LangSmith 트레이싱** — Story 3.8.
- **PIPA 동의 UI flow** — Story 1.4 박힘(`Depends`만 wire).
- **Idempotency-Key 헤더** — analysis 라우터는 *idempotent retry 의미 X*(매 호출이 새 분석 또는 cache hit). `[meal_id].tsx`가 useState로 1회만 trigger → 클라이언트 1차 가드.

### 9. 신규 모듈 vs UPDATE 요약

| 분류 | 경로 | 용도 |
|------|------|------|
| NEW | `api/app/api/v1/analysis.py` | 3 endpoint (POST stream / GET poll / POST clarify) + SSE generator + AnalysisDonePayload |
| NEW | `api/app/services/sse_emitter.py` | event helper (chunk_text + 6 event builders) + AnalysisDonePayload Pydantic 모델 |
| NEW | `api/app/services/feedback_summary.py` | feedback_text → 1줄 summary derive helper (목록 화면 입력) |
| NEW | `api/app/services/meal_analysis_persistence.py` | UPSERT helper (INSERT ... ON CONFLICT DO UPDATE) |
| NEW | `api/app/db/models/meal_analysis.py` | SQLAlchemy ORM 모델 (12 컬럼 + Meal/User FK) |
| NEW | `api/alembic/versions/0012_create_meal_analyses.py` | DDL 마이그레이션 (테이블 + 5 CHECK + 2 인덱스) |
| NEW | `mobile/features/meals/useMealAnalysisStream.ts` | SSE + polling fallback hook orchestrator |
| NEW | `mobile/features/meals/ChatStreaming.tsx` | 채팅 UI (token append + clarify chips + done card + DisclaimerFooter) |
| NEW | `mobile/features/meals/MacroCard.tsx` | 매크로 보조 카드 접힘 (NFR-UX3) |
| UPDATE | `api/app/main.py` | analysis 라우터 등록 (1 줄 + import) |
| UPDATE | `api/app/core/exceptions.py` | AnalysisStreamError 계층 + 3 서브클래스 (~30줄) |
| UPDATE | `api/app/core/config.py` | analysis_polling_interval_seconds / analysis_token_chunk_chars / analysis_token_chunk_interval_ms / analysis_polling_max_attempts (선택, hard-code도 무방) |
| UPDATE | `api/app/db/models/meal.py` | `analysis: Mapped[MealAnalysis \| None] = relationship(uselist=False, lazy="raise_on_sql")` 1줄 추가 |
| UPDATE | `api/app/api/v1/meals.py` | `list_meals` selectinload + `_meal_to_response` analysis_summary 빌드 |
| UPDATE | `api/tests/conftest.py` | `_truncate_user_tables`에 `meal_analyses` 추가 |
| UPDATE | `mobile/app/(tabs)/meals/[meal_id].tsx` | "AI 분석 시작" CTA + ChatStreaming 마운트 + invalidate callback |
| UPDATE | `mobile/package.json` | react-native-sse ^1.2 (+ lock 갱신) |
| UPDATE | `mobile/lib/api-client.ts` | OpenAPI typegen 자동 갱신 (수동 편집 X) |
| NEW | `api/tests/api/v1/test_analysis_stream.py` | 12 케이스 + meal_analyses UPSERT 검증 추가 |
| NEW | `api/tests/api/v1/test_analysis_polling.py` | 8 케이스 |
| NEW | `api/tests/api/v1/test_analysis_clarify.py` | 6 케이스 |
| NEW | `api/tests/services/test_sse_emitter.py` | 6 케이스 |
| NEW | `api/tests/services/test_feedback_summary.py` | 5 케이스 |
| NEW | `api/tests/services/test_meal_analysis_persistence.py` | 5 케이스 |
| UPDATE | `api/tests/api/v1/test_meals.py` | list_meals analysis_summary 신규 케이스 4건 |

### 10. SSE generator 의사코드 (참고 — 실 구현은 Task 5)

```python
async def stream_analysis(
    request: Request,
    body: AnalysisStreamRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
    _consent: Annotated[User, Depends(require_automated_decision_consent)],
) -> EventSourceResponse:
    meal = await _resolve_meal(db, meal_id=body.meal_id, user_id=user.id)
    service = await _get_analysis_service(request)
    start = time.monotonic()

    async def _generator() -> AsyncIterator[ServerSentEvent]:
        token_count = 0
        citation_count = 0
        phase_count = 0
        used_llm = "stub"
        final_fit_score = 0
        try:
            yield event_progress("parse", elapsed_ms=int((time.monotonic() - start) * 1000))
            phase_count += 1

            state = await service.run(
                meal_id=body.meal_id,
                user_id=user.id,
                raw_text=meal.raw_text,
            )

            if state.get("needs_clarification"):
                yield event_clarify(state.get("clarification_options", []))
                return

            if state.get("node_errors") and not state.get("feedback"):
                problem = AnalysisNodeError(state["node_errors"][0].error_class).to_problem(
                    instance=str(request.url.path)
                )
                yield event_error(problem)
                return

            feedback = state["feedback"]  # FeedbackOutput.model_dump() (Story 3.6 dict access)
            for chunk in chunk_text_for_streaming(feedback["text"]):
                yield event_token(chunk)
                token_count += 1
                await asyncio.sleep(_TOKEN_CHUNK_INTERVAL_MS / 1000.0)

            for idx, citation in enumerate(feedback["citations"]):
                yield event_citation(idx, Citation.model_validate(citation))
                citation_count += 1

            payload = _state_to_done_payload(state, meal_id=body.meal_id)
            used_llm = payload.used_llm
            final_fit_score = payload.final_fit_score
            yield event_done(payload)

        except BalanceNoteError as exc:
            yield event_error(exc.to_problem(instance=str(request.url.path)))
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            yield event_error(_unexpected_problem(instance=str(request.url.path)))
        finally:
            log.info(
                "analysis.sse.complete",
                meal_id=str(body.meal_id),
                mode="sse",
                phase_count=phase_count,
                token_count=token_count,
                citation_count=citation_count,
                used_llm=used_llm,
                final_fit_score=final_fit_score,
                latency_ms=int((time.monotonic() - start) * 1000),
            )

    return EventSourceResponse(_generator(), headers={"X-Stream-Mode": "sse"})
```

### 11. ChatStreaming UI 의사코드 (참고 — 실 구현은 Task 11)

```tsx
export default function ChatStreaming({ mealId, isOnline, onAnalysisDone }: Props) {
  const { state, reset, submitClarification } = useMealAnalysisStream(mealId);

  useEffect(() => {
    if (state.phase === "done") onAnalysisDone?.();
  }, [state.phase]);

  if (!isOnline) return <Text>오프라인 — 온라인 시 분석 가능</Text>;

  return (
    <ScrollView ref={scrollRef} onContentSizeChange={() => scrollRef.current?.scrollToEnd()}>
      <Text style={styles.body}>{state.text}</Text>

      {state.phase === "clarify" && (
        <View>
          {state.clarificationOptions?.map((opt) => (
            <Pressable key={opt.value} onPress={() => submitClarification(opt.value)}>
              <Text>{opt.label}</Text>
            </Pressable>
          ))}
        </View>
      )}

      {(state.phase === "streaming" || state.phase === "polling") && (
        <View><ActivityIndicator /><Text>AI 분석 중…</Text></View>
      )}

      {state.phase === "done" && state.result && (
        <>
          <FitScoreBadge score={state.result.final_fit_score} label={state.result.fit_score_label} />
          <MacroCard macros={state.result.macros} />
          <DisclaimerFooter />
        </>
      )}

      {state.phase === "error" && (
        <View>
          <Text>분석에 실패했어요 — 다시 시도</Text>
          <Pressable onPress={reset}><Text>다시 시도</Text></Pressable>
        </View>
      )}
    </ScrollView>
  );
}
```

### 12. CR 패턴 인계 (Story 3.6 → 3.7 적용)

- **D-2 helper 분리** — `to_summary_label`(domain → presentation 변환)을 `_state_to_done_payload`에서 사용. fit_evaluation.fit_label(4 band) → fit_score_label(5 band) 매핑 단일 지점.
- **NFC 정규화** — `chunk_text_for_streaming` 내부에서 `unicodedata.normalize("NFC", text)` 1회 호출 후 list 분할(D1 결정 정합).
- **m-3 self-emitted prefix 회피** — log 파싱 X. 직접 카운터(`token_count: int` / `citation_count: int`).
- **C1+C2 Sentry frame vars 가드** — Story 3.6 anchor 그대로 유효(SSE 라우터 raw_text는 prompt 변수 X — pipeline 안에서만). 본 스토리는 라우터 자체는 raw_text를 generator local 변수로만 보유 → frame leak 위험 낮음.
- **MJ-22 outer wait_for** — Story 3.6 router는 `asyncio.wait_for(route_feedback, timeout=25)` outer deadline. 본 스토리 라우터는 `_DONE_EVENT_TIMEOUT_SECONDS = 30` cap — 25s router + 5s chunking margin. timeout 시 generator는 `BalanceNoteError`(또는 새 `AnalysisStreamTimeoutError` 추가 검토 — 본 스토리는 *Story 3.6 router 25s 가드가 1차*, 라우터 30s는 안전망). 명시 timeout wrapper는 OPTIONAL — anchor만 박음.

### Project Structure Notes

- **Directory structure**: 모든 신규/UPDATE 경로는 architecture.md `app/` + `mobile/` 트리 정합.
- **모듈 import 방향성**:
  - `app.api.v1.analysis`는 `app.services.analysis_service` + `app.services.sse_emitter` + `app.api.deps` + `app.core.exceptions` + `app.db.models.meal` import 가능. graph 모듈 *직접* import 금지(서비스 레이어만 경유 — Story 3.3 architecture 정합).
  - `app.services.sse_emitter`는 `sse_starlette` + `app.graph.state.Citation` + `app.api.v1.meals.MealMacros`(또는 별 모듈로 추출 — Story 8.4 polish) import.
  - mobile `useMealAnalysisStream`는 `react-native-sse` + `mobile/lib/api-client` + `mobile/lib/auth` import.
- **`api/app/services/sse_emitter.py` 위치 결정**: `app/services/`는 *비즈니스 서비스 레이어*. SSE event helper는 *transport-cross-cutting infrastructure*에 가까움. 그러나 분석 라우터 1군데에서만 사용 + 향후 reports/notifications SSE 추가 시 재사용 가능 — `app/services/`에 위치(Story 4.3 reports SSE는 본 스토리 OUT).
- **`AnalysisDonePayload` 위치**: `app/api/v1/analysis.py` 모듈 const 권장 — 라우터 응답 schema는 라우터 모듈 SOT(`MealResponse` 패턴 정합 — `meals.py`). 단, `MealMacros`는 `app/api/v1/meals.py`에 정의되어 있어 import 순환 회피로 `meals.py` 그대로 import.

### References

- [Source: epics.md#Story-3.7 line 676-693] — 본 스토리 ACs verbatim
- [Source: epics.md#Epic-3 line 579-581] — 영업 차별화 카드 4종 framing
- [Source: prd.md#FR11] — 디스클레이머 푸터 4-surface
- [Source: prd.md#FR17, FR26] — 분석 SSE 스트리밍 mandate
- [Source: prd.md#NFR-P1, NFR-P3] — 종단 지연 + TTFT 목표
- [Source: prd.md#NFR-UX1, NFR-UX3] — Coaching tone + 매크로 보조 카드
- [Source: prd.md#NFR-S5] — 민감정보 마스킹 SOT
- [Source: prd.md#T5-KPI] — 5분 50회 끊김 ≤ 1
- [Source: architecture.md line 320-322, 486-495, 506, 530] — SSE 프로토콜 + 이벤트 type + polling fallback + X-Stream-Mode 헤더
- [Source: architecture.md line 149] — react-native-sse 의존성 mandate
- [Source: architecture.md line 666, 706, 822, 909, 920-923, 972, 983] — 라우터/UI 위치 + 데이터 흐름
- [Source: api/app/main.py:59-62, 96-100, 121-145] — rate limit 키 + Redis init + analysis_service 주입 흐름
- [Source: api/app/api/deps.py:136-192] — require_basic_consents + require_automated_decision_consent 패턴
- [Source: api/app/services/analysis_service.py:38-135] — run/aget_state/aresume 시그니처 (변경 X)
- [Source: api/app/graph/state.py:146-198, 226-251] — Citation/FeedbackOutput/ClarificationOption/MealAnalysisState (변경 X)
- [Source: api/app/api/v1/meals.py:321-368] — MealAnalysisSummary Pydantic + fit_score_label 5-band 정합
- [Source: api/app/core/exceptions.py:487-565] — AnalysisGraphError/LLMRouterError 계층 (AnalysisStreamError 신규 패턴 정합)
- [Source: api/app/core/sentry.py] — mask_event hook (Story 3.6 anchor 그대로 유효)
- [Source: mobile/features/legal/DisclaimerFooter.tsx:1-26] — 1줄 푸터 const SOT (변경 X)
- [Source: mobile/app/(tabs)/meals/[meal_id].tsx:1-10, 218-324] — Story 3.7 진입점 prep + AI 분석 placeholder
- [Source: mobile/features/meals/MealCard.tsx:49-71, 100-123] — FitScoreBadge 색상 + 라벨 패턴 (재사용)
- [Source: mobile/lib/use-online-status.ts] — 온라인 상태 hook (NFR-R4 정합)
- [Source: deferred-work.md DF100-DF105] — Story 3.6 deferred 본 스토리 영향 없음(LLM router 내부 cosmetic deferred)

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] via Claude Code

### Debug Log References

- pytest 전체: 721 passed, 9 skipped, 0 failed (coverage 84.83%, 모든 신규 모듈 ≥ 94%)
- ruff check / ruff format / mypy app: 0 에러
- mobile pnpm tsc --noEmit: 0 에러
- alembic 0012 round-trip(upgrade head → downgrade 0011 → upgrade head): pass
- Story 3.3 / 3.4 / 3.5 / 3.6 회귀 0건 (test_pipeline / test_self_rag / test_evaluate_fit / test_generate_feedback / test_llm_router / test_analysis_service 모두 통과)

### Completion Notes List

- **Backend (3 endpoint + SSE generator)**: `POST /v1/analysis/stream` (SSE) + `GET /v1/analysis/{meal_id}` (polling envelope) + `POST /v1/analysis/clarify` (SSE resume). 공통 `_run_and_stream` generator로 stream/clarify 재사용 — token chunk(24자/30ms) + citation + UPSERT + done 순차 emit. clarify/error/done 정확히 1회 emit 후 generator 종료(AC3).
- **3 게이트 + meal 소유권 검증**: `current_user` + `require_basic_consents` + `require_automated_decision_consent` (polling은 PIPA Art.35 정합으로 automated_decision 미요구). meals 미존재/비소유/soft-deleted 모두 동일 404(`analysis.meal.not_found`, enumeration 차단).
- **Rate limit**: slowapi 모듈-레벨 limiter가 lifespan-init과 incompatible — Redis 분산 fixed-window 카운터(`enforce_langgraph_rate_limit` Depends, 10/minute per-IP)로 hand-rolled. `app.state.redis` 미설정/장애 시 graceful skip(test/dev fallback).
- **AnalysisStreamError 계층 4 클래스**: MealNotFound(404) / CheckpointerUnavailable(503) / ClarifyValidation(422) / RateLimitExceeded(429). 글로벌 BalanceNoteError 핸들러가 RFC 7807 자동 변환.
- **SSE event helper (`app/services/sse_emitter.py`)**: `chunk_text_for_streaming`(NFC 정규화 + grapheme-safe 분할) + 6 event builder(progress/token/citation/clarify/done/error) + `AnalysisDonePayload` Pydantic. `ensure_ascii=False`로 한국어 raw byte(token 비용 ↓ + UI 인스펙터 가독성).
- **D5 IN(2026-05-04 hwan 피드백 후 변경)**: `meal_analyses` 테이블 + 0012 마이그레이션(14컬럼 + UNIQUE meal_id + (user_id, created_at DESC) 인덱스 + 5 CHECK). `Meal.analysis` relationship `lazy="raise_on_sql"`로 N+1 가드 강제 → `list_meals`는 `selectinload(Meal.analysis)`로 single round-trip JOIN. POST/PATCH meals 경로는 `set_committed_value(meal, "analysis", None)`로 fresh row의 raise_on_sql 우회.
- **UPSERT helper (`meal_analysis_persistence.py`)**: `INSERT ... ON CONFLICT (meal_id) DO UPDATE` 단일 SQL + fresh session(`request.app.state.session_maker()`)으로 SSE generator lifecycle 분리. 실패 swallow + Sentry capture + log warning(graceful — 사용자에게 결과는 보임). `persisted: bool`을 NFR-S5 log에 기록.
- **`feedback_summary` derive**: 결정성 헬퍼(`## 평가` 섹션 첫 문장 추출 → 마크다운 헤더 strip 후 fallback → 120자 cap with `...` suffix). LLM 추가 호출 0(cost 보호).
- **Mobile**: `react-native-sse ^1.2.0` 의존성 + `useMealAnalysisStream` hook(SSE + 1.5초 polling 강등 + 30회 timeout + `submitClarification`) + `ChatStreaming.tsx`(phase별 layout) + `MacroCard.tsx`(접힘 보조 카드, NFR-UX3) + `[meal_id].tsx` "AI 분석 시작" CTA + ChatStreaming 마운트 + `queryClient.invalidateQueries({queryKey:['meals']})`.
- **NFR-S5 마스킹 (Story 3.6 anchor 정합)**: `analysis.sse.complete` / `analysis.poll.fetch` / `analysis.clarify.resume` 단일 INFO 1줄에 `meal_id` + `mode` + `phase_count` + `token_count` + `citation_count` + `used_llm` + `final_fit_score` + `latency_ms` + `persisted`만 forward. raw_text/feedback 본문/parsed_items name/allergies/weight/height raw 출력 X.
- **Spec deviation 1건**: `event: clarify` 5번째 이벤트 type(Story 3.4 needs_clarification 분기 노출 — primary path 4 이벤트와 자연 확장). `event: progress` heartbeat도 자연 확장(TTFT NFR-P3 보장 안전망).
- **Out of scope (Story 8.4 polish 또는 Story 3.8 deferred)**: True LLM-token streaming(astream_events), 재분석 UI 트리거(*"AI 다시 분석"* 버튼), 모바일 jest+RN testing-library 인프라, Sentry RN SDK breadcrumb 정교화, Web SSE 클라이언트(EventSource POST 미지원 — 모바일 only), LangSmith 트레이싱(Story 3.8).

### File List

**NEW (api)**
- `api/app/api/v1/analysis.py` — 3 endpoint + SSE generator + AnalysisStreamRequest/AnalysisClarifyRequest + helper(meal/service/macros/done_payload/clarification_options/fit_reason/citations) + enforce_langgraph_rate_limit Depends.
- `api/app/services/sse_emitter.py` — chunk_text_for_streaming + 6 event builder + AnalysisDonePayload Pydantic.
- `api/app/services/feedback_summary.py` — derive_feedback_summary helper(120자 cap + 마크다운 헤더 strip).
- `api/app/services/meal_analysis_persistence.py` — upsert_meal_analysis (INSERT ON CONFLICT DO UPDATE + graceful swallow).
- `api/app/db/models/meal_analysis.py` — MealAnalysis ORM (14컬럼 + UNIQUE + 인덱스 + 5 CHECK).
- `api/alembic/versions/0012_create_meal_analyses.py` — DDL 마이그레이션 (14컬럼 + UNIQUE meal_id + (user_id, created_at DESC) 인덱스 + 5 CHECK).

**UPDATE (api)**
- `api/app/main.py` — analysis 라우터 import + include_router.
- `api/app/core/exceptions.py` — AnalysisStreamError + 4 서브클래스(MealNotFound/CheckpointerUnavailable/ClarifyValidation/RateLimitExceeded).
- `api/app/core/config.py` — analysis_token_chunk_chars / analysis_token_chunk_interval_ms / analysis_polling_interval_seconds / analysis_polling_max_attempts (4 신규 필드).
- `api/app/db/models/meal.py` — `analysis: Mapped[MealAnalysis | None] = relationship(lazy="raise_on_sql", uselist=False)` 1줄 추가.
- `api/app/db/models/__init__.py` — MealAnalysis 등록.
- `api/app/api/v1/meals.py` — `_build_analysis_summary` helper + `_meal_to_response`에서 `meal.analysis` derive + `list_meals`에 `selectinload(Meal.analysis)` + POST/PATCH 경로에 `set_committed_value(meal, "analysis", None)` 사전 셋팅.
- `api/tests/conftest.py` — `_truncate_user_tables`에 `meal_analyses` 추가.

**NEW (api tests)**
- `api/tests/services/test_sse_emitter.py` — 10 케이스(chunk + 6 event + AnalysisDonePayload bounds).
- `api/tests/services/test_feedback_summary.py` — 7 케이스(평가 섹션 추출 / 헤더 strip fallback / truncate / 빈 입력).
- `api/tests/services/test_meal_analysis_persistence.py` — 5 케이스(INSERT 신규 / UPDATE 기존 / CHECK 위반 graceful False / citations roundtrip / feedback_summary truncate).
- `api/tests/api/v1/__init__.py` + `api/tests/api/__init__.py` (패키지 선언).
- `api/tests/api/v1/conftest.py` — mock_analysis_service / meal_factory / parse_sse_text + state factory 3종 + autouse Redis rate limit 키 정리.
- `api/tests/api/v1/test_analysis_stream.py` — 12 케이스(happy + 게이트 + 소유권 + 503 + clarify + node_errors + 한국어 + UPSERT + extra_field).
- `api/tests/api/v1/test_analysis_polling.py` — 8 케이스(in_progress 202 + done 200 + clarify + error + 404 + soft-deleted + 403 + automated_decision 미요구).
- `api/tests/api/v1/test_analysis_clarify.py` — 6 케이스(happy + 빈/oversize + 404 + automated_decision + 재발 clarify).
- `api/tests/test_meal_analyses_schema.py` — 2 케이스(0012 round-trip + CHECK 제약 enforcement).
- `api/tests/test_meals_router.py` — 4 신규 케이스(populated / allergen_violation / mixed null+populated).

**NEW (mobile)**
- `mobile/features/meals/useMealAnalysisStream.ts` — SSE + 1.5초 polling fallback orchestrator hook(StreamState + reset + submitClarification).
- `mobile/features/meals/ChatStreaming.tsx` — phase별 layout(connecting/streaming/clarify/done/error) + DisclaimerFooter + MacroCard.
- `mobile/features/meals/MacroCard.tsx` — 접힘 보조 카드(NFR-UX3).

**UPDATE (mobile)**
- `mobile/package.json` — `react-native-sse ^1.2.0` 추가.
- `mobile/lib/auth.tsx` — `API_BASE_URL` export(react-native-sse direct fetch 입력).
- `mobile/app/(tabs)/meals/[meal_id].tsx` — placeholder 제거 + "AI 분석 시작" CTA + ChatStreaming inline 마운트 + invalidate callback.
- `mobile/lib/api-client.ts` — OpenAPI typegen 자동 갱신(3 신규 endpoint 등재).
- `web/src/lib/api-client.ts` — OpenAPI typegen 자동 갱신(consistency).

### Review Findings

CR run 2026-05-04 — Blind Hunter / Edge Case Hunter / Acceptance Auditor 3-layer adversarial. 100+ raw findings → dedup/triage → **8 decision-needed / 26 patch / 3 defer / 33 dismissed (false positive · by design · 가치<비용)**. 0 verified BLOCKER (`good→excellent` mapping은 D-2 의도, `caution` band는 FitEvaluation Literal 정합, `asyncio.TimeoutError`는 Python 3.13 pin으로 무관, `authFetch`는 internal API_BASE_URL prefix 정합).

CR triage 분류 정정(2026-05-04 hwan 피드백): 초기 6 defer 중 DF112(UPSERT row-level retry — YAGNI, 직렬 호출 race 빈도 매우 낮음), DF113(regex \X grapheme cluster — 외부 의존성 비용 > 한국어 본문 발생률), DF114(자동 스크롤 race — UX 데이터 부재로 결정 premature)는 *가치 < 비용* 영역이라 dismiss로 재분류. defer 리스트는 *실제 작업 의도 있는 항목*만(DF110/DF111/DF115).

#### Decision-needed

- [x] [Review][Decision] **AC1 rate limit 패턴** — spec literal `app.state.limiter` 데코레이터 vs 현 hand-rolled Redis fixed-window(`enforce_langgraph_rate_limit` Depends). 코드 주석에 "slowapi module-level decorator가 lifespan-init과 비호환" 명시. (a) slowapi 정합 refactor / (b) 현 hand-rolled 유지 + spec note 갱신 / (c) 현 상태 그대로 accept.
- [x] [Review][Decision] **AC8 Pydantic 422 vs 400** — 글로벌 핸들러(`main.py:250`)가 `RequestValidationError → 400`으로 통일. spec AC8 line 49 "ValueError → 422"는 `aresume` ValueError catch만 도달(Pydantic min_length=1이 1차 차단해 사실상 unreachable). (a) `/v1/analysis/clarify`만 422 분리 / (b) spec 갱신해 400 채택 / (c) 현 상태 + 422 dead-code 주석.
- [x] [Review][Decision] **AC4/AC13 Sentry transaction 미박음** — `sentry_sdk.start_transaction(op="analysis.sse.complete")` + tag `mode=sse|polling` 누락. structlog INFO만 박힘. (a) 본 스토리에서 transaction wiring / (b) Story 8.4 polish defer.
- [x] [Review][Decision] **AC6 polling Retry-After 5회 hint 미구현** — 현재 첫 호출부터 항상 emit. (a) attempt count 추적 + 5회 후 emit / (b) 현 상태 (보수적 UX).
- [x] [Review][Decision] **PATCH/replay 응답 `analysis_summary=null` 거짓** — `set_committed_value(meal, "analysis", None)` (`meals.py:657, 855`) — 기존 분석 보유 meal도 null 응답. mobile invalidateQueries에 의존. (a) UPDATE/INSERT 후 re-SELECT with `selectinload(Meal.analysis)` / (b) 현 상태 (documented 한계) / (c) PATCH 응답에서 `analysis_summary` 자체 omit.
- [x] [Review][Decision] **`event: progress` 4-phase stub 미구현** — Task 4.2의 `_PHASE_NAMES` 4-tuple 부재. AC4는 1회 emit이라 했고 Task 5.2.iv는 4단계 stub — spec 자체 모호. (a) 4-phase stub progress 추가(retrieve/evaluate/feedback) / (b) AC4 본문 정합 1회 유지 + spec Task 4.2 정정.
- [x] [Review][Decision] **AC5 perf marker(rate_limit 11회 + 빈 raw_text) 부재** — Task 9.1 명시 12 케이스 중 2건 누락. (a) skip-default `@pytest.mark.perf` 골격 add / (b) Story 3.8 LangSmith eval로 defer.
- [x] [Review][Decision] **Polling endpoint rate limit 미적용** — `GET /v1/analysis/{id}` DoS 표면. mobile 1.5초 setInterval × 30 cap이 client-side 가드. (a) higher cap(60/min) per-IP rate limit 적용 / (b) 현 상태 (client-side cap 신뢰).

#### Patch

- [x] [Review][Patch] Redis `expire` 실패 시 permanent counter 누적 DoS — `SET NX EX` pattern 또는 `pipeline().incr().expire()` 단일 호출로 atomic 보장 [`api/app/api/v1/analysis.py:154-162`]
- [x] [Review][Patch] NaN/Inf `energy_kcal` 시 `int(round(nan))` ValueError → 영구 persist 실패 — `math.isfinite` guard 추가 [`api/app/services/meal_analysis_persistence.py:70`]
- [x] [Review][Patch] `assert raw_text is not None` Python `-O`로 strip 가능 — runtime check + `BalanceNoteError` raise로 변환 [`api/app/api/v1/analysis.py:426`]
- [x] [Review][Patch] `Retry-After` rounding bug — `int(x+0.5)`은 `2.4 → 2` undershoot. `math.ceil` 사용 [`api/app/api/v1/analysis.py:671`]
- [x] [Review][Patch] `_SSE_EVENT_TYPES` Literal SOT 상수 부재 — spec AC2 line 17 명시. 모듈 top-level 명시 추가 [`api/app/api/v1/analysis.py:97`]
- [x] [Review][Patch] `analysis.node.failed` 코드가 AC2 카탈로그 6 코드 enumerate에서 누락 — spec line 23 카탈로그 갱신 또는 코드 rename [`spec AC2`]
- [x] [Review][Patch] EventSourceResponse `ping=15` keepalive 미설정 — ALB/CDN idle timeout(보통 60s) 시 connection drop. `EventSourceResponse(..., ping=15)` 추가 [`api/app/api/v1/analysis.py:550, 592`]
- [x] [Review][Patch] `_resolve_meal` 영문 raw detail "meal not found" — NFR-S5/AC16 한국어 일반화 (예: "식단을 찾을 수 없습니다") [`api/app/api/v1/analysis.py:189`]
- [x] [Review][Patch] AnalysisRateLimitExceededError detail에 raw `(10/minute)` 노출 — 일반화된 메시지로 [`api/app/api/v1/analysis.py:165-167`]
- [x] [Review][Patch] `_persist_done_payload` `session_maker()` 자체 raise 가드 부재 — try/except로 fail→False 보장(`event: done` skip 차단) [`api/app/api/v1/analysis.py:362-374`]
- [x] [Review][Patch] `feedback_text == ""` 시 Pydantic `min_length=1` ValidationError가 broad except로 fall-through → 일반 `analysis.unexpected` 500 — typed `BalanceNoteError`로 변환 [`api/app/api/v1/analysis.py:269-300`]
- [x] [Review][Patch] `_state_to_macros` corrupt item silent skip — 최소 `log.warning("analysis.state_to_macros.skipped", item_class=...)` 추가 [`api/app/api/v1/analysis.py:230-250`]
- [x] [Review][Patch] `parse_sse_text` data 다중 라인 SSE spec 위반 (현 `"".join`) — `"\n".join` 또는 첫 라인만 사용 [`api/tests/api/v1/conftest.py:112`]
- [x] [Review][Patch] `derive_feedback_summary` Korean 종결자 누락 — `_FIRST_SENTENCE_RE`에 `。`/`．`/`…` 추가 [`api/app/services/feedback_summary.py`]
- [x] [Review][Patch] AC18 신규 테스트 케이스 ≥ 4 spec — 현 신규 3건 + 기존 재사용. 1건 추가 [`api/tests/test_meals_router.py`]
- [x] [Review][Patch] mobile hook `_openEventSource` async race after unmount — `terminalReachedRef.current` 체크 후 `eventSourceRef.current = es` 할당 [`mobile/features/meals/useMealAnalysisStream.ts`]
- [x] [Review][Patch] mobile hook `_pollOnce` `mealId` prop 변경 시 stale fetch가 새 hook에 setState — AbortController 도입 [`mobile/features/meals/useMealAnalysisStream.ts`]
- [x] [Review][Patch] mobile hook polling 401 silent ignore — 토큰 만료 핸들링 누락. `response.status === 401` 분기 추가(authFetch는 자동 refresh이지만 hook 직접 fetch path 점검) [`mobile/features/meals/useMealAnalysisStream.ts`]
- [x] [Review][Patch] mobile hook polling 5xx persistent retry forever — N회 5xx 후 error phase로 bail (현 30회 cap만 가드) [`mobile/features/meals/useMealAnalysisStream.ts`]
- [x] [Review][Patch] mobile hook SSE inactivity timer 부재 — 30s 무이벤트 시 polling 강등 trigger [`mobile/features/meals/useMealAnalysisStream.ts`]
- [x] [Review][Patch] mobile ChatStreaming `doneNotifiedRef` reset 미호출 — `reset()` callback에서 `doneNotifiedRef.current = false` [`mobile/features/meals/ChatStreaming.tsx`]
- [x] [Review][Patch] mobile ChatStreaming clarify chip 다중 탭 race — 첫 탭 즉시 `submitting` 로컬 플래그로 chip Pressables disable [`mobile/features/meals/ChatStreaming.tsx`]
- [x] [Review][Patch] mobile API_BASE_URL trailing slash 정규화 — `.replace(/\/$/, '')` [`mobile/lib/auth.tsx` 또는 hook 진입]
- [x] [Review][Patch] AC2 `event: error` test에 RFC 7807 `type` 필드 단언 누락 — `test_event_error_serializes_problem_detail` 보강 [`api/tests/services/test_sse_emitter.py`]
- [x] [Review][Patch] AC17 UPSERT 후 `created_at` 보존 회귀 가드 테스트 부재 — `test_upsert_preserves_created_at` 추가 [`api/tests/services/test_meal_analysis_persistence.py`]
- [x] [Review][Patch] AC2 done payload 키명 `final_fit_score` vs `MealAnalysisSummary.fit_score` 불일치 — spec deviation X (양쪽 schema 의도적 분리) but 모바일 UI 분기 점검 — 코멘트 추가 또는 spec note 갱신 [`spec AC2 / AC18`]

#### Defer (실제 향후 작업 예정)

- [x] [Review][Defer] DF110 — True LLM-token streaming — Story 8.4 polish (현 진짜 token stream 변경 시 Story 3.6 citation/ad-guard 후처리 회귀 발생, 후처리 패턴 변경과 함께 도입 필요)
- [x] [Review][Defer] DF111 — Rate limit X-Forwarded-For trusted proxy — Story 8.4 운영 인프라 확정 시점 (proxy chain ALB/Cloudflare 결정 종속)
- [x] [Review][Defer] DF115 — T5 KPI 자동화(끊김 ≤ 1/50회) — Story 3.8 LangSmith eval (dataset 인프라 종속, AC5 본문 spec-mandated defer)

### Change Log

| Date | Description |
|------|-------------|
| 2026-05-04 | Story 3.7 ready-for-dev — SSE pseudo-streaming + polling fallback + clarify resume + DisclaimerFooter + MacroCard 보조 카드. backend 3 endpoint(POST stream / GET poll / POST clarify) + SSE event helper + AnalysisStreamError 4 클래스. mobile useMealAnalysisStream hook + ChatStreaming 컴포넌트 + react-native-sse ^1.2 의존성 추가. spec extension 1건(`event: clarify` 5번째 이벤트 type — Story 3.4 needs_clarification 분기). 초기 결정 D5(meal_analyses 영속화 OUT)는 hwan 피드백 후 IN으로 변경 — `meal_analyses` 테이블 + UPSERT helper + `GET /v1/meals` JOIN 추가(AC17/AC18 + Task 16). 사용자 재로그인 시 한 주 식습관 한눈에 + 이전 분석 결과 즉시 표시 UX. true LLM-token streaming은 Story 8.4 polish deferred(현 pseudo-streaming + early progress heartbeat로 NFR-P3 TTFT 만족). 재분석 UI 트리거도 Story 8.4 OUT(UPSERT 인프라는 본 스토리에 박힘). |
| 2026-05-04 | Story 3.7 review — 17 Task 전부 완료. backend 721 pytest passed/9 skipped/0 failed + coverage 84.83%(모든 신규 모듈 ≥ 94%) + ruff/format/mypy 0 에러. mobile tsc --noEmit 0 에러. alembic 0012 round-trip 통과. Story 3.3-3.6 회귀 0건. Branch story-3.7 — review 단계 진입. |
| 2026-05-04 | Story 3.7 done — CR 3-layer adversarial(Blind/Edge/Auditor) 100+ raw findings → 8 decision-needed/26 patch/6 defer/30 dismissed 분류. 8 decision 추천 적용(D1=b hand-rolled Redis 유지, D2=b spec 400 채택, D3=a Sentry transaction wire-in, D4=b 항상 Retry-After emit, D5=a re-SELECT with selectinload, D6=b 1회 progress 유지, D7=a perf marker 골격, D8=a polling 60/min cap). 26 patch 일괄 적용: Redis pipeline atomic incr+expire(permanent counter DoS 차단) + NaN/Inf macros guard(silent persist 실패 차단) + assert→runtime check(python -O strip 가드) + math.ceil Retry-After + _SSE_EVENT_TYPES Literal SOT + EventSourceResponse ping=15(proxy idle drop 차단) + 한국어 detail 일반화(NFR-S5) + _persist_done_payload session_maker raise 가드 + ValidationError typed BalanceNoteError + state_to_macros warn log + parse_sse_text \\n separator(SSE spec 정합) + 한국어 종결자(。/．/…) + AC18 4번째 신규 케이스 + mobile useMealAnalysisStream 7건(open race + AbortController + 401 + 5xx streak + inactivity timer 30s + URL trailing slash + reset doneNotifiedRef) + ChatStreaming clarify chip multi-tap submitting flag + test_event_error type 단언 + test_upsert_preserves_created_at + 신규 perf 골격 2건(rate_limit 429 + empty raw_text). 6 defer DF110~DF115. backend 725 pytest passed/9 skipped/0 failed + coverage 84.61% + ruff/format/mypy 0. mobile tsc 0. Story 3.3-3.6 회귀 0건. Branch story-3.7 — review → done. |
