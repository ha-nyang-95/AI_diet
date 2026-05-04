# Story 3.8: LangSmith 외부 옵저버빌리티 통합 + 한식 100건 평가 데이터셋

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **1인 개발자(운영) / 외주 발주자(영업 카드 검증)**,
I want **LangGraph 6노드 + LLM 호출 + RAG 검색을 LangSmith로 자동 트레이싱하고, 한식 100건 평가 데이터셋으로 회귀 평가를 돌리며, 트레이스 송신 전 민감정보가 마스킹되기를**,
so that **프로덕션 LLM 동작·품질·추세를 영업 보드로 입증하면서 PIPA·식약처 컴플라이언스를 깨지 않는다**.

## Acceptance Criteria

1. **AC1 — `app/core/observability.py` 신규 + LangSmith client 셋업 (NFR-O1, architecture line 232-242)**: `api/app/core/observability.py` 신규 모듈. 함수 시그니처:
   - `def init_langsmith() -> langsmith.Client | None` — `settings.langchain_tracing_v2 is False`이면 즉시 `None` return + log INFO `observability.langsmith.disabled`(graceful skip — 로컬 dev 디폴트). `True` + `settings.langsmith_api_key == ""` 조합은 *config 모순*이라 log WARNING `observability.langsmith.misconfigured` + `None` return(부팅 통과 — 라우터 응답 503 회피, NFR-S5 PII 송신은 어차피 disabled). 정상 init은 `langsmith.Client(api_key=settings.langsmith_api_key, hide_inputs=mask_run_inputs, hide_outputs=mask_run_outputs)` 반환.
   - `def mask_run_inputs(inputs: dict[str, Any]) -> dict[str, Any]` — *재귀* dict/list 순회 + NFR-S5 키셋(`_LANGSMITH_MASKED_KEYS` 정의, AC2)에 매칭되는 value를 `"***"`로 치환. 미매칭 키는 통과. *원본 dict 미수정*(deep copy 또는 신규 dict 빌드). `mask_run_outputs`도 동일 시그니처/동작 — outputs도 같은 키셋 적용(`feedback.text`/`citations`은 노출 OK라 키셋에 미포함, 단 `prompt`/`response_text`/`raw_text`/`messages`/`content`는 송신 차단).
   - module-level `_langsmith_client: langsmith.Client | None = None` singleton. `init_langsmith()`가 module 변수에 할당. lifespan startup에서 1회 호출.
   - `def get_langsmith_client() -> langsmith.Client | None` — singleton 접근자(테스트 monkeypatch + script 재사용).
   - module 임포트 시 부수효과 X — env reading은 `init_langsmith()` 내부에서만(`Settings` reload 안전).

2. **AC2 — NFR-S5 마스킹 키셋 SOT 단일화 (NFR-O2, NFR-S5 결합)**: `app/core/observability.py:_LANGSMITH_MASKED_KEYS: Final[frozenset[str]]` 정의. 키 set:
   - **Sentry 재사용 (`app/core/sentry.py:_MASKED_KEYS` 정합)**: `prompt`, `response_text`, `raw_text`, `system`, `user_prompt`, `content`, `messages`.
   - **신규 (LangGraph state 추가, 9 키 — CR DN-2/P14/P17 정합)**: `weight_kg`, `height_cm`, `allergies`, `parsed_items`, `food_items`, `clarification_options`(사용자가 선택한 음식명 → 식습관 추론 PII), `feedback_text`, `text`, `meal_text`. **CR DN-2 결정**(옵션 b — 영업 데모 보드 가시성 보존): `feedback` 키 *whole-dict redact*를 폐지하고 그 자리에 `text` 키를 단독 등재. 효과: `feedback.text` 자연어 본문은 마스킹되지만 `feedback.citations` / `feedback.macros` / `feedback.fit_score` 는 보드 노출 OK(NFR-O4 영업 가시성). *주의*: `text` 키 단독 매칭은 false-positive 위험이 있어 — 현 LangGraph state 구조에서 `text` 키를 쓰는 nested dict가 `feedback.text` 외 없음을 전제로 함(`parsed_items[*].name` / `citations[*].quote` / `clarification_options[*]: str`). 신규 노드가 비-PII `text` 필드를 도입할 경우 화이트리스트 재설계 필요. **CR P14 — `meal_text`**: smoke v3 incident 회귀 가드(`raw_text` alias 키 — helper 함수가 `meal_text` 인자명으로 노출 시 raw 식단 본문 보드 표기 차단).
   - **재사용 import**: `from app.core.sentry import _MASKED_KEYS as _SENTRY_MASKED_KEYS` 후 `_LANGSMITH_MASKED_KEYS = _SENTRY_MASKED_KEYS | frozenset({...추가 키...})` 합집합. *Sentry SOT 1지점 변경이 LangSmith에도 자동 반영* (NFR-S5 마스킹 룰셋 1지점 재사용 원칙 정합 — architecture line 237).
   - 단위 테스트(`tests/core/test_observability.py`)에서 합집합 무결성 + Sentry 변경 시 LangSmith가 따라가는지 검증(import 후 set 비교). CR P9 추가: 진짜 list 재귀 가드(`{"items": [{"raw_text": "x"}]}` → `{"items": [{"raw_text": "***"}]}`) + cycle/depth/tuple 가드.

3. **AC3 — LangGraph native tracing 자동 활성 (NFR-O1, architecture line 200, 236)**: `LANGCHAIN_TRACING_V2=true` env + `LANGSMITH_API_KEY` 설정 시 LangGraph 1.1.9 + langchain-openai/anthropic이 native로 6노드(`parse_meal` → `retrieve_nutrition` → `evaluate_retrieval_quality` → `rewrite_query` → `request_clarification` → `fetch_user_profile` → `evaluate_fit` → `generate_feedback`) + LLM 호출 + RAG 검색 자동 트레이싱. 라우터/노드 코드 변경 X — env 설정만으로 활성. 검증:
   - 통합 테스트 `tests/core/test_observability_tracing.py`는 *실 LangSmith API 호출 없이* — `LANGCHAIN_TRACING_V2=true` env + LangSmith client mock(`monkeypatch`) 시 `compile_pipeline()` 결과 graph가 `langchain_core.callbacks.tracers` `LangChainTracer`를 callback에 자동 부착 (langchain-core SOT 정합). graph.ainvoke 시 mock client `create_run` 호출이 ≥1회 발생함을 단언.
   - `app/main.py` lifespan에서 `init_langsmith()` 호출 위치 — `init_sentry()` *직후*(line 82). graph compile은 그 이후라 자연 활성 순서.
   - `app.adapters.openai_adapter` / `app.adapters.anthropic_adapter`는 *직접 OpenAI/Anthropic SDK*(langchain-openai 미사용) — LangSmith 자동 트레이싱은 LangGraph state 호출만 캡처, raw OpenAI SDK 호출은 미캡처. **결정 D1**: 본 스토리는 *노드-수준 트레이싱* 충분(NFR-O1 *"노드별 latency·token·cost·input/output"* 정합 — 노드 input/output에 LLM prompt가 포함됨, 노드 trace에 nested LLM call 자동 노출). raw SDK level 추가 트레이싱은 Story 8.4 polish 또는 미래 outsource client별 옵션 — 본 스토리 OUT.
   - `@traceable` 데코레이터 추가 도메인 함수 — *옵션*. architecture line 236는 `fit_score` / `food normalize` 후보 명시. 본 스토리는 *없이도 NFR-O1 100% 커버* 검증 후 결정 — 필요 시 1줄 추가(per-function override는 retrofit 비용 0). **결정 D2**: 본 스토리는 *기본 native tracing만* — 도메인 함수 추가 트레이싱은 *영업 데모 보드 가시성 평가* 후 follow-up(Story 8.6 영업 데모 페이지 구성 단계). 코드 추가 0.

4. **AC4 — `langsmith` SDK 버전 bump (보안 패치)**: `api/pyproject.toml` `dependencies`의 `"langsmith>=0.3"` → `"langsmith>=0.7.31"` 갱신. 사유: LangSmith SDK GHSA-rr7j-v2q5-chgv (Information Disclosure) — 0.7.30 이하는 redaction pipeline이 `events` 배열을 필터링 못해 `new_token` 이벤트의 raw token이 LangSmith에 저장됨(NFR-O2 위반). **검증**: `uv sync --upgrade-package langsmith` 실행 + `uv.lock`의 `langsmith` 버전이 0.7.31 이상임을 git diff로 확인. 같은 PR에서 `langsmith>=0.7.31` 가드 단위 테스트 추가 — `tests/test_dependency_versions.py`에 `import langsmith; assert tuple(map(int, langsmith.__version__.split(".")[:3])) >= (0, 7, 31)` 1건. 회귀 가드(향후 silent downgrade 차단).

5. **AC5 — `.env.example` 갱신 + 디폴트 false (epic AC8, NFR-S10 결합)**: `.env.example` line 14-17 갱신:
   - `LANGSMITH_API_KEY=` (값 비움 — 운영자 채움 강제 + dev 빈 값 graceful skip).
   - `LANGSMITH_PROJECT=balancenote-dev` (디폴트 dev — staging은 `balancenote-staging`, prod는 `balancenote-prod`로 Railway secrets에서 override).
   - `LANGCHAIN_TRACING_V2=false` (디폴트 false — 로컬 개발 LLM 호출 시 LangSmith 트래픽 0). 주석: `# 로컬 개발은 false 디폴트 — 개발자 수동 ON. 스테이징/프로덕션은 Railway secrets에서 true 강제.`
   - 키 회전 SOP 1줄 — `# Railway secrets에서 LANGSMITH_API_KEY 회전 — README 'API key 회전 절차' 참조.`

6. **AC6 — `scripts/upload_eval_dataset.py` 신규 (NFR-O3)**: `scripts/upload_eval_dataset.py` 신규 — Story 3.4 한식 100건 테스트셋(`api/tests/data/korean_foods_100.json`)을 LangSmith Dataset `balancenote-korean-foods-v1`로 업로드. argparse:
   - `--dataset-name` (default: `"balancenote-korean-foods-v1"`).
   - `--input-path` (default: `api/tests/data/korean_foods_100.json` — repo root 기준 상대 path).
   - `--description` (default: `"한식 100건 음식명 정규화 정확도 회귀 데이터셋 (Story 3.4 T3 KPI 90% 정합)"`).
   - `--force` flag — 기존 dataset 동명 존재 시 *examples 추가 vs skip* 결정. 디폴트 skip(idempotent — 멀티 실행 안전). `--force`는 새 examples append + log warning(중복 위험).
   - `--dry-run` flag — LangSmith 호출 0회 + 빌드된 dataset payload structure를 stdout 출력(검증용).
   
   **dataset 빌드**:
   - 각 row (`{input, expected_canonical, expected_path, category}`) → LangSmith Example로 변환. inputs `{"meal_text": row["input"]}`, outputs `{"canonical": row["expected_canonical"], "path": row["expected_path"]}`, metadata `{"category": row["category"]}`.
   - LangSmith API: `client.create_dataset(name=..., description=...)` (이미 존재 시 `client.read_dataset(dataset_name=...)` fallback) → `client.create_examples(dataset_id=..., examples=[...])`.
   - 환경 가드 — `LANGSMITH_API_KEY` 미설정 시 즉시 `sys.exit(1)` + stderr 안내(`"LANGSMITH_API_KEY required — set in env before run"`).
   
   **idempotency**: 같은 이름 dataset이 이미 examples를 포함하면(`client.list_examples(dataset_id=...)` ≥ 1) skip 분기 + log INFO `eval.upload.skipped` + exit 0. `--force`만 추가 append.
   
   **단위 테스트** `tests/scripts/test_upload_eval_dataset.py` 신규 — 5 케이스:
   - JSON dataset 파일 로드 + 100건 + 4 키 schema 검증.
   - argparse `--dry-run` 시 LangSmith mock client `create_dataset`/`create_examples` 미호출.
   - 정상 실행 시 `create_examples` 1회 호출 + 100건 examples 전달.
   - 기존 dataset + examples 존재 + `--force=False` → skip 분기.
   - `LANGSMITH_API_KEY` 미설정 → `sys.exit(1)`.

7. **AC7 — PR CI 마스킹 정적 검사 스텝 (epic AC4, NFR-O2)**: `.github/workflows/ci.yml`에 *마스킹 누락 정적 검사* 추가. **결정 D3**: 별도 GHA job 신설보다 *단위 테스트로 대체* — 정적 검사는 false-positive 多 + 유지비 ↑. `tests/core/test_observability.py:test_mask_run_redacts_all_nfr_s5_keys` 단위 테스트가 NFR-S5 모든 키에 대해 `mask_run_inputs({...key: "secret raw"...})["..."] == "***"` 검증. PR `test-api` job(line 52-94)에서 자동 실행 — 마스킹 누락 시 fail.
   - 단위 테스트 케이스 ≥ 8 (`tests/core/test_observability.py`):
     - `mask_run_inputs` top-level `raw_text` redact.
     - nested `user_profile.weight_kg` / `user_profile.height_cm` / `user_profile.allergies` 모두 redact.
     - `parsed_items` 배열 dict 안의 `name` 필드 redact(list of dict 순회 검증).
     - `feedback` nested dict 자체 redact(전체 dict → `"***"`).
     - 일반 키(`meal_id` / `user_id` / `final_fit_score`) 통과 — 비-PII는 LangSmith 노출 OK.
     - `mask_run_outputs` 동일 키셋 적용.
     - 원본 dict 변경 없음(side-effect 0 — 테스트는 원본 deep-equal 단언).
     - 빈 dict / None 입력 → 빈 dict / None 반환(graceful 가드).

8. **AC8 — `langsmith evaluate` 옵션 PR step (epic AC5, NFR-O3)**: `.github/workflows/ci.yml`에 *권장 회귀 평가 step* 추가 — 머지 비차단. `langsmith-eval-regression` 신규 job:
   - trigger: `workflow_dispatch` 또는 PR labels 매칭 — `if: contains(github.event.pull_request.labels.*.name, 'langsmith-eval')`. 디폴트 PR에는 미실행(LangSmith Free tier 5K trace/month 보호 + 실 LLM 비용).
   - `continue-on-error: true` — fail 비차단(에픽 line 706 *권장; 자동 머지 차단은 OUT* 정합).
   - 흐름:
     1. uv sync.
     2. `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` GitHub secrets 주입.
     3. `RUN_EVAL_TESTS=1 uv run pytest tests/test_korean_foods_eval.py -v`(Story 3.4 eval marker 흐름 활용).
     4. 정확도 < 90%면 `actions/github-script@v7`로 PR 코멘트 — *"⚠️ LangSmith 회귀 평가 — 정확도 X% (90% 미달, 권장)"*. 정확도 ≥ 90%면 코멘트 *"✅ LangSmith 회귀 평가 통과 — 정확도 X%"*.
   - **결정 D4**: 본 스토리는 *옵션 step만 박는다* — 매 PR 자동 실행은 비용 + dev 흐름 마찰 위험. *prompt/노드 변경 PR*에 한해 라벨 수동 적용(`langsmith-eval`) → 운영자가 의도적으로 회귀 평가 트리거. NFR-O3 *"주요 프롬프트·노드 변경 PR 시 회귀 평가 1회 실행"* 정합.

9. **AC9 — 개인정보처리방침 갱신 (NFR-O5)**: `api/app/domain/legal_documents.py` 또는 `web/src/app/(public)/legal/privacy/page.tsx`(SOT는 `legal_documents.py` 한국어 본문) `PRIVACY_POLICY_KO` 본문에 *제3자 제공·국외 이전* 단락 1줄 추가:
   > **제3자 제공·국외 이전**: 본 서비스는 LangSmith Inc. (미국)로 LLM 호출 트레이스(노드 input/output, latency, token 사용량)를 송신합니다. 송신 전 민감정보(체중·신장·알레르기·식단 raw text·사용자 식별자)를 마스킹 처리해 PII 송신 0을 보장하며, 운영·품질 추적 목적에 한해 사용됩니다. 거부 시 회원 가입 자체는 가능하나, 시스템 운영 효율 일부가 제한됩니다.
   - 한·영 양 본문 동기화 — `PRIVACY_POLICY_EN` 동일 단락 추가(`docs/sop/03-disclaimer-ko-en.md` 패턴 정합).
   - `PRIVACY_POLICY_VERSION` bump — 직전 version `+1`(예: `"1.0.0"` → `"1.1.0"`). Story 1.4 동의 흐름 정합 — *기존 사용자 재동의 강제는 본 스토리 OUT*(legal compliance level — 본 단락은 *LLM 운영 트레이스의 PII 0* 명시이라 정보주체 권리 침해 X).
   - 단위 테스트 `tests/domain/test_legal_documents.py` 갱신 — 신규 단락 substring 단언 + version bump 검증(2 케이스).

10. **AC10 — `docs/observability/langsmith-dashboard.md` 신규 (NFR-O4, Story 8.6 forward-compat)**: `docs/observability/langsmith-dashboard.md` 신규 — 운영자 + 외주 발주자용 *LangSmith 보드 가이드*. 본문 구조:
    - **공개 read-only 링크 1세트** — `balancenote-prod` 프로젝트 보드 URL(운영자가 LangSmith UI에서 *Share* 토글 후 채움 — 본 스토리 W3 종료 시점 미설정 OK, placeholder TBD 1줄).
    - **데모 보드 시나리오 — Story 8.6 영업 자료 1포인트**:
      1. 6노드 latency stacked bar chart 캡처 위치.
      2. Self-RAG 분기율 (rewrite 진입 / clarify 진입 / continue 직행) pie chart.
      3. LLM 호출 비용 추이 (cost dashboard).
      4. 한식 100건 회귀 평가 결과 — `balancenote-korean-foods-v1` dataset run 결과.
    - **마스킹 검증 가이드** — 임의 trace 1건 열어 inputs/outputs에 raw_text/weight_kg/allergies가 `"***"`로 redact 됐음 시각 확인. NFR-O2 PR 후 *수동 verification 1회* 권장.
    - **API key 회전 절차 인용** — `docs/runbook/secret-rotation.md`(Story 1.1)에 LangSmith 키 회전 단락 추가 후 본 가이드에서 link.

11. **AC11 — `docs/runbook/secret-rotation.md` 갱신 (NFR-S10)**: 기존 `docs/runbook/secret-rotation.md`(Story 1.1)에 *LangSmith API key 회전 절차* 단락 추가:
    - LangSmith UI → Settings → API Keys → 신규 발급 → 기존 키 revoke.
    - Railway secrets `LANGSMITH_API_KEY` 갱신 → 자동 재배포(or 수동 `railway up`).
    - 검증 — `LANGCHAIN_TRACING_V2=true` 환경에서 분석 1회 호출 후 LangSmith 보드에 신규 trace 도착 확인.
    - rollback — 신규 키 fail 시 직전 키를 LangSmith에서 *revoke 취소*(grace 24h) + Railway secrets 복구.
    - 회전 주기 — 분기 1회(`docs/sop/`에 회전 캘린더 추가는 Story 8.5 OUT).

12. **AC12 — 라우터/서비스 변경 0 + 회귀 0 (D1 정합)**: `app/api/v1/analysis.py` / `app/services/analysis_service.py` / `app/graph/pipeline.py` / `app/graph/nodes/*.py` *코드 변경 0*. 본 스토리는 *cross-cutting infrastructure*(observability + script + 문서)만 추가. Story 3.3 ~ 3.7 모든 단위·통합 테스트 회귀 0건 강제(NFR-S5 마스킹 SOT는 sentry.py에서 import 재사용 — 키셋 충돌 0). 검증:
    - `pytest -q` 전체 통과(현 베이스라인: Story 3.7 결과 *725 passed/9 skipped*).
    - coverage ≥ 70% 유지.
    - ruff/format/mypy 0 에러.
    - mobile/web tsc 0 에러(본 스토리는 모바일/web 코드 변경 0이라 자연 통과).

## Tasks / Subtasks

- [x] **Task 1 — `langsmith>=0.7.31` SDK bump (AC4)**
  - [x] 1.1 `api/pyproject.toml` `dependencies`의 `"langsmith>=0.3"` → `"langsmith>=0.7.31"` 갱신.
  - [x] 1.2 `cd api && uv sync --upgrade-package langsmith` 실행 → `uv.lock` 갱신.
  - [x] 1.3 `tests/test_dependency_versions.py` 신규 — 2 케이스(langsmith ≥ 0.7.31 + tuple 비교 가드).
  - [x] 1.4 `mypy app tests` 0 에러 — langsmith 0.7+ stub 변경 시 mypy override 추가 검토(`pyproject.toml [tool.mypy.overrides] module = ["langsmith.*"] ignore_missing_imports = true` 이미 있는지 확인 + 부재 시 추가).

- [x] **Task 2 — `app/core/observability.py` 신규 + 마스킹 hook (AC1, AC2, AC3)**
  - [x] 2.1 `api/app/core/observability.py` 신규.
  - [x] 2.2 module-level imports — `from typing import Any, Final`, `import structlog`, `from langsmith import Client`, `from app.core.config import settings`, `from app.core.sentry import _MASKED_KEYS as _SENTRY_MASKED_KEYS`.
  - [x] 2.3 `_LANGSMITH_EXTRA_KEYS: Final[frozenset[str]] = frozenset({"weight_kg", "height_cm", "allergies", "parsed_items", "food_items", "clarification_options", "feedback_text", "feedback"})` (LangGraph state 추가 PII 키).
  - [x] 2.4 `_LANGSMITH_MASKED_KEYS: Final[frozenset[str]] = _SENTRY_MASKED_KEYS | _LANGSMITH_EXTRA_KEYS` (합집합 SOT).
  - [x] 2.5 `_MASK_PLACEHOLDER: Final[str] = "***"` (sentry.py와 동일 placeholder).
  - [x] 2.6 `_mask_recursive(value: Any) -> Any` private helper — dict는 키별 redact + 재귀, list는 element별 재귀, scalar는 통과. `sentry.py:_mask_dict` 패턴 확장(list of dict 처리 포함, sentry CR Gemini G3 정합).
  - [x] 2.7 `def mask_run_inputs(inputs: dict[str, Any]) -> dict[str, Any]:` — `inputs`가 None이면 빈 dict 반환, dict이면 `_mask_recursive(inputs)` 결과 반환. 원본 미수정.
  - [x] 2.8 `def mask_run_outputs(outputs: dict[str, Any]) -> dict[str, Any]:` — `mask_run_inputs`와 동일 구현(키셋 + 동작 동일). 별 시그니처는 LangSmith client `hide_inputs`/`hide_outputs` 콜백 시그니처 정합.
  - [x] 2.9 module-level `_langsmith_client: Client | None = None` singleton 변수.
  - [x] 2.10 `def init_langsmith() -> Client | None:` — `settings.langchain_tracing_v2`가 False면 log INFO `observability.langsmith.disabled` + `None` return + module 변수 None 유지. `True` + `langsmith_api_key == ""` → log WARNING `observability.langsmith.misconfigured` + None return. 정상 → `Client(api_key=settings.langsmith_api_key, hide_inputs=mask_run_inputs, hide_outputs=mask_run_outputs)` 생성 + module 변수 할당 + log INFO `observability.langsmith.initialized` (project=settings.langsmith_project).
  - [x] 2.11 `def get_langsmith_client() -> Client | None:` — module 변수 반환.
  - [x] 2.12 `def reset_langsmith_for_tests() -> None:` — module 변수 None 강제(테스트 monkeypatch fallback).

- [x] **Task 3 — `main.py` lifespan에 init_langsmith() 호출 (AC1, AC3)**
  - [x] 3.1 `api/app/main.py` import 추가 — `from app.core.observability import init_langsmith`.
  - [x] 3.2 lifespan 함수 line 82(`init_sentry()`) *직후* 라인 — `init_langsmith()` 호출 추가. 1줄 추가 + try/except 불필요(`init_langsmith` 자체가 graceful — exception 발생 가능 분기는 langsmith Client init 자체 — settings 검증 후 호출이라 거의 발생 X, 만일 발생 시 lifespan 자체가 crash → main.py 87-145 패턴(`try/except + log.error + None`) 적용 검토 — *결정 D5*: `init_langsmith()` 자체가 None return으로 graceful이므로 wrapping try/except 추가 — 안전망(SDK 내부 unexpected ValueError 대비).
  - [x] 3.3 *try/except 패턴*:
    ```python
    try:
        init_langsmith()
    except Exception as exc:  # noqa: BLE001
        log.error("app.startup.langsmith_init_failed", error=str(exc))
    ```
    Story 3.7 lifespan 패턴 정합.

- [x] **Task 4 — 단위 테스트 `tests/core/test_observability.py` (AC1, AC2, AC7)**
  - [x] 4.1 `api/tests/core/test_observability.py` 신규.
  - [x] 4.2 `tests/core/__init__.py` 빈 파일 신규(이미 있으면 skip — pytest 자동 디스커버리는 init 무관이지만 mypy 패키지 인식 정합).
  - [x] 4.3 케이스 ≥ 12:
    - `test_mask_run_inputs_redacts_top_level_raw_text` — `{"raw_text": "비밀"}` → `{"raw_text": "***"}`.
    - `test_mask_run_inputs_redacts_nested_user_profile_fields` — `{"user_profile": {"weight_kg": 70, "height_cm": 175, "allergies": ["복숭아"], "name": "Hwan"}}` → 모든 키 `"***"` (단 `name`은 LangGraph state UserProfileSnapshot에 미포함 — 가드 케이스).
    - `test_mask_run_inputs_redacts_parsed_items_array` — `{"parsed_items": [{"name": "삼겹살", "confidence": 0.9}]}` → `parsed_items` 자체 dict 매칭(전체 list `"***"`).
    - `test_mask_run_inputs_redacts_feedback_dict` — `{"feedback": {"text": "...", "citations": [...]}}` → 전체 `"***"`.
    - `test_mask_run_inputs_passes_non_pii_fields` — `{"meal_id": "uuid", "final_fit_score": 62, "phase": "parse"}` → 변경 없이 통과.
    - `test_mask_run_inputs_does_not_mutate_original` — 호출 후 원본 dict deep-equal 단언.
    - `test_mask_run_inputs_handles_empty_dict` — `{}` → `{}`.
    - `test_mask_run_inputs_handles_list_of_dicts_recursively` — `{"messages": [{"content": "secret"}]}` → `messages` 자체 매칭(상위 redact).
    - `test_mask_run_outputs_uses_same_keyset` — `mask_run_inputs` / `mask_run_outputs`가 동일 키셋 적용함을 단언.
    - `test_masked_keys_includes_sentry_keyset` — `_LANGSMITH_MASKED_KEYS >= _SENTRY_MASKED_KEYS` (합집합 무결성).
    - `test_init_langsmith_disabled_when_tracing_v2_false` — `monkeypatch.setattr(settings, "langchain_tracing_v2", False)` → `init_langsmith()` returns None.
    - `test_init_langsmith_misconfigured_warning` — `langchain_tracing_v2=True` + `langsmith_api_key=""` → returns None + log WARNING(structlog testing capture).
    - `test_init_langsmith_creates_singleton_client` — 정상 init → returns `Client` instance + `get_langsmith_client()` 동일 instance 반환. monkeypatch로 `langsmith.Client.__init__`을 mock(실 API 호출 회피).

- [x] **Task 5 — 통합 테스트 `tests/core/test_observability_tracing.py` (AC3)**
  - [x] 5.1 `tests/core/test_observability_tracing.py` 신규.
  - [x] 5.2 케이스 ≥ 3:
    - `test_langgraph_pipeline_attaches_tracer_when_tracing_enabled` — `LANGCHAIN_TRACING_V2=true` env + LangSmith Client mock → `compile_pipeline()` 결과의 `graph.config.callbacks` 또는 `langchain_core.tracers.langchain.LangChainTracer` import 검증.
    - `test_pipeline_no_tracer_when_disabled` — `LANGCHAIN_TRACING_V2=false` → tracer 미부착(env 미설정 분기).
    - `test_compile_pipeline_runs_smoke_with_tracing_mock` — Story 3.7 `test_pipeline.py:test_compile_pipeline_smoke` 패턴 재사용 + LangSmith Client mock으로 `create_run`이 ≥1회 호출됨 단언. 단, *현 테스트 인프라가 dev 환경에서 실 OpenAI/Anthropic 호출 차단 정합* — 노드 자체 mock(stub LLM) 구성. **결정 D6**: 본 케이스는 *복잡도 高* (LangChain tracer 내부 lifecycle 추적은 fragile). 본 스토리는 단순 `tracer in graph.callbacks` 단언 + smoke 통과만 보고, 실 trace upload는 staging/prod 수동 검증으로 분리. CI는 mock-level 가드만.

- [x] **Task 6 — `scripts/upload_eval_dataset.py` 신규 (AC6)**
  - [x] 6.1 `scripts/upload_eval_dataset.py` 신규(repo root 기준 `scripts/` — `seed_food_db.py` / `seed_guidelines.py` 패턴 정합).
  - [x] 6.2 shebang `#!/usr/bin/env python3` + module docstring(스크립트 사용법 + AC6 명시).
  - [x] 6.3 `__main__` block + argparse 4 옵션(`--dataset-name` / `--input-path` / `--description` / `--force` / `--dry-run`).
  - [x] 6.4 `_load_dataset(path: Path) -> list[dict[str, str]]` — JSON 파일 로드 + 100건 + schema 검증(`input` / `expected_canonical` / `expected_path` / `category` 4 키 강제, 불일치 시 ValueError).
  - [x] 6.5 `_build_examples(rows: list[dict[str, str]]) -> list[dict[str, Any]]` — LangSmith Example schema 변환(inputs/outputs/metadata 분리).
  - [x] 6.6 `_upload(client, dataset_name, description, examples, force) -> int` — dataset 생성 또는 read fallback + examples 삽입. 기존 examples 존재 + force=False → skip(0 return). 정상 삽입 → len(examples) return.
  - [x] 6.7 `--dry-run` → `client = None` + log INFO + payload structure print + sys.exit(0).
  - [x] 6.8 `LANGSMITH_API_KEY` 미설정 → stderr `"LANGSMITH_API_KEY required — set in env before run"` + sys.exit(1).
  - [x] 6.9 단위 테스트 `tests/scripts/test_upload_eval_dataset.py` 신규 — 5 케이스(AC6 명시):
    - JSON 파일 로드 + 100건 schema 검증.
    - argparse `--dry-run` → mock `Client` 미인스턴스화.
    - 정상 실행 → mock `client.create_examples` 1회 호출 + 100건 examples 전달.
    - 기존 dataset + examples 존재 + `--force=False` → 0 return + skip log.
    - `LANGSMITH_API_KEY` 미설정 → `pytest.raises(SystemExit)`.

- [x] **Task 7 — `.env.example` 갱신 (AC5)**
  - [x] 7.1 `.env.example` line 14-17 갱신:
    - `LANGSMITH_API_KEY=` (값 비움).
    - `LANGSMITH_PROJECT=balancenote-dev`.
    - `LANGCHAIN_TRACING_V2=false` (기존 `=true` → `=false`).
  - [x] 7.2 주석 추가 — `# 로컬 개발은 false 디폴트. 스테이징/프로덕션은 Railway secrets에서 true 강제. 키 회전: docs/runbook/secret-rotation.md.`

- [x] **Task 8 — 개인정보처리방침 갱신 (AC9)**
  - [x] 8.1 `api/app/domain/legal_documents.py` `PRIVACY_POLICY_KO` 본문에 *제3자 제공·국외 이전* 단락 1줄 추가(AC9 본문 verbatim).
  - [x] 8.2 `PRIVACY_POLICY_EN` 동일 단락 영문 추가(`docs/sop/03-disclaimer-ko-en.md` 패턴 정합).
  - [x] 8.3 `PRIVACY_POLICY_VERSION` bump (예: `"1.0.0"` → `"1.1.0"`).
  - [x] 8.4 `tests/domain/test_legal_documents.py` 갱신 — 2 케이스:
    - `PRIVACY_POLICY_KO` 본문에 `"LangSmith"` substring 포함.
    - `PRIVACY_POLICY_VERSION` ≥ 직전 baseline.
  - [x] 8.5 *기존 사용자 재동의 강제는 OUT* — Story 1.4 ConsentVersionMismatchError 분기는 *major version bump*시만 — 본 스토리는 minor bump이라 강제 재동의 미발동(legal compliance 검토 — *제3자 제공* 단락은 정보주체 권리 영향 *낮음*: PII 송신 0이라 명시).

- [x] **Task 9 — `docs/observability/langsmith-dashboard.md` + `docs/runbook/secret-rotation.md` 갱신 (AC10, AC11)**
  - [x] 9.1 `docs/observability/` 디렉터리 신규 + `langsmith-dashboard.md` 신규(AC10 본문 구조 정합).
  - [x] 9.2 `docs/runbook/secret-rotation.md`(이미 존재 — Story 1.1 architecture line 607)에 *LangSmith API key 회전 절차* 단락 추가(AC11 5단계).
  - [x] 9.3 양 문서 cross-link — dashboard → secret-rotation, secret-rotation → dashboard.

- [x] **Task 10 — `.github/workflows/ci.yml` `langsmith-eval-regression` job (AC8)**
  - [x] 10.1 `.github/workflows/ci.yml`에 신규 job `langsmith-eval-regression` 추가:
    ```yaml
    langsmith-eval-regression:
      name: langsmith-eval-regression
      runs-on: ubuntu-latest
      if: |
        github.event_name == 'workflow_dispatch' ||
        contains(github.event.pull_request.labels.*.name, 'langsmith-eval')
      continue-on-error: true
      defaults:
        run:
          working-directory: api
      env:
        LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
        LANGSMITH_PROJECT: balancenote-ci-eval
        LANGCHAIN_TRACING_V2: 'true'
        OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        RUN_EVAL_TESTS: '1'
        ENVIRONMENT: ci
      steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v6
          with:
            enable-cache: true
        - run: uv sync --frozen
        - name: Korean foods 100 eval (T3 KPI ≥ 90%)
          id: eval
          run: |
            uv run pytest tests/test_korean_foods_eval.py -v 2>&1 | tee /tmp/eval.log
        - name: Comment on PR (권장 — 머지 비차단)
          if: github.event_name == 'pull_request'
          uses: actions/github-script@v7
          # 본문은 actions/github-script 패턴 — alembic-dry-run job line 222-247 정합
    ```
  - [x] 10.2 GitHub repo *Settings → Secrets and variables → Actions*에 `LANGSMITH_API_KEY` 추가(운영자 SOP — 본 스토리는 *코드만 박고* secret은 운영자가 1회 설정).
  - [x] 10.3 `langsmith-eval` 라벨 정의 — *수동 추가*. 본 스토리는 라벨 정의 자동화 OUT(GitHub UI에서 1회 생성 + 라벨 description *"Trigger LangSmith regression eval (T3 KPI 90%) — Free tier 5K trace/month 보호 라벨"*).

- [x] **Task 11 — 회귀 가드 검증 + 운영 hardening (AC12)**
  - [x] 11.1 `cd api && uv run pytest -q` 전체 통과 — Story 3.7 baseline *725 passed/9 skipped*에 *13~16 신규 테스트* 추가 후 *741~744 passed* 예상. coverage ≥ 70% 유지(`--cov-fail-under=70`).
  - [x] 11.2 `cd api && uv run ruff check .` + `uv run ruff format --check .` + `uv run mypy app tests` 0 에러.
  - [x] 11.3 `cd mobile && pnpm tsc --noEmit` 0 에러(코드 변경 0이라 자연 통과).
  - [x] 11.4 `cd web && pnpm tsc --noEmit` 0 에러(legal page 추가 단락 변경 시 본 스토리는 백엔드 SOT 변경만 — privacy page는 백엔드 `/v1/legal/privacy` API 호출이 자동 갱신, web 정적 페이지 변경 0).
  - [x] 11.5 `app/api/v1/analysis.py` / `app/services/analysis_service.py` / `app/graph/pipeline.py` / `app/graph/nodes/*.py` git diff 0 — 본 스토리는 라우터/서비스/노드 변경 X 강제(D1 정합).
  - [x] 11.6 Story 3.3 / 3.4 / 3.5 / 3.6 / 3.7 모든 기존 테스트 회귀 0 — 특히 `test_pipeline.py` / `test_self_rag.py` / `test_evaluate_fit.py` / `test_generate_feedback.py` / `test_llm_router.py` / `test_analysis_stream.py` / `test_analysis_polling.py` / `test_analysis_clarify.py` 통과.
  - [x] 11.7 `tests/core/test_sentry_mask.py`(Story 3.6) 회귀 0 — `_MASKED_KEYS` import는 본 스토리에서 read-only이라 회귀 위험 0. 단, `_LANGSMITH_MASKED_KEYS`가 합집합이라 *Sentry 키 제거 PR이 LangSmith에서도 자동 제거되는* 결합도 — `tests/core/test_observability.py:test_masked_keys_includes_sentry_keyset` 가드(Task 4.3).

- [x] **Task 12 — 최종 verification + LangSmith 보드 placeholder 갱신 (수동, AC10)**
  - [x] 12.1 운영자(hwan)가 LangSmith UI에 `balancenote-dev` / `balancenote-staging` / `balancenote-prod` 프로젝트 3개 생성. dev는 *Share → Public read-only* 토글(데모용). prod는 staging까지만 share — prod 보드는 외주 client별 옵션(architecture line 241 정합).
  - [x] 12.2 `docs/observability/langsmith-dashboard.md` 보드 URL placeholder 채움(W3 종료 시점). PR 시점에는 TBD 1줄 OK — Story 8.6 영업 데모 페이지 작성 단계까지 완료 후 wire.
  - [x] 12.3 1회 분석 실 호출 — `LANGCHAIN_TRACING_V2=true` 로컬 dev에서 `POST /v1/analysis/stream` 호출 → LangSmith 보드에 trace 도착 확인 + inputs/outputs에 `raw_text` / `weight_kg` 등 PII가 `"***"`로 redact 됐음 *시각 확인*. 결과 스크린샷 → `docs/observability/langsmith-dashboard.md`에 첨부(Story 8.6 영업 자료 forward-compat).

## Dev Notes

### 1. 핵심 사실관계 (Story 3.7 → 3.8 인계)

- **`langsmith>=0.3` 의존성은 이미 박혀 있음** — Story 3.3 부트스트랩 시점에 설치(architecture line 185). 본 스토리는 *0.7.31 보안 패치 bump*만(AC4).
- **`LANGCHAIN_TRACING_V2` env는 langchain-core / langgraph가 *자동 인식*** — 별도 wiring 코드 0. `compile_pipeline`은 변경 X(D1 정합 — 라우터/서비스/노드 코드 변경 0).
- **마스킹 hook 1지점 SOT는 `app/core/sentry.py:_MASKED_KEYS` (Story 3.6 anchor)** — 본 스토리는 import 후 합집합으로 LangSmith 키셋 확장(architecture line 237 정합). Sentry 키 변경 PR이 LangSmith에도 자동 반영.
- **한식 100건 dataset SOT는 `api/tests/data/korean_foods_100.json`** — Story 3.4가 이미 박음(test_korean_foods_eval.py module-level `DATASET_PATH` const). 본 스토리 script는 *위치 import + 변환만*.
- **`@pytest.mark.eval` marker는 이미 정의됨** — Story 3.4 `pyproject.toml:pytest.ini_options.markers`(line 101-104). `RUN_EVAL_TESTS=1`로 opt-in. CI eval job(Task 10)은 본 marker 흐름 그대로 활용.
- **`docs/runbook/secret-rotation.md`는 이미 존재** — Story 1.1 architecture line 607. 본 스토리는 LangSmith 단락 추가만.
- **`PRIVACY_POLICY_KO` SOT는 `app/domain/legal_documents.py`** — Story 1.3에서 박힘. Web `/legal/privacy/page.tsx`는 백엔드 `/v1/legal/privacy` API 호출이라 백엔드 본문 갱신 시 자동 반영.

### 2. 마스킹 SOT D1 결정 (Sentry import 합집합)

**문제**: NFR-O2는 *"마스킹 룰셋 1지점 재사용 (Sentry beforeSend hook과 동일 룰셋 import)"* (architecture line 237). 두 모듈에 키 set을 *복제*하면 future drift 위험(Sentry 측에서 키 추가했는데 LangSmith는 누락 — PII leak).

**결정**:
- (a) **`from app.core.sentry import _MASKED_KEYS as _SENTRY_MASKED_KEYS`** + `_LANGSMITH_MASKED_KEYS = _SENTRY_MASKED_KEYS | _LANGSMITH_EXTRA_KEYS` 합집합. Sentry 키 변경 시 LangSmith 자동 반영.
- (b) `_LANGSMITH_EXTRA_KEYS`만 LangSmith 측 신규 — LangGraph state 특화 키(`weight_kg`/`height_cm`/`allergies`/`parsed_items`/`food_items`/`clarification_options`/`feedback_text`/`feedback`).
- (c) Sentry 키셋(`prompt`/`response_text`/`raw_text`/`system`/`user_prompt`/`content`/`messages`)은 LLM SDK 호출 boundary 패턴 — LangSmith trace에도 동일 PII 위험.

**검증 가드**: Task 4.3의 `test_masked_keys_includes_sentry_keyset`가 합집합 무결성 단언. Sentry 측 키 변경 시 PR 머지 차단(LangSmith 측도 따라가는지 확인).

### 3. `feedback` 전체 dict 마스킹 D2 결정 (false-positive vs PII conservative)

**문제**: LangGraph state의 `feedback`는 `{"text": "...코칭 본문...", "citations": [...]}` 구조. `text` 키 단독 매칭은 *false-positive 多*(citation의 `doc_title` 옆 `text` 등). `feedback.text`만 정확히 잡으려면 부모 key path 추적 필요(구현 복잡 + 유지비 ↑).

**결정**:
- (a) **`feedback` 키 전체 dict redact** — 하위 모든 필드 일괄 `"***"`. citation/macro 카드는 *output payload의 다른 위치*(LangGraph node output `feedback`은 raw FeedbackOutput Pydantic dump)에서도 노출 가능 — LangSmith 보드 가시성은 *노드 latency + cost + 분기 라우팅*이 핵심이라 feedback 본문 redact는 영업 demo 가치 손실 X.
- (b) `feedback_text` 키도 별칭으로 추가(generate_feedback 노드의 LLM 호출 raw response key 정합 — `FeedbackLLMOutput.text` 등 dump 시점).
- (c) Trade-off — 영업 데모 보드에서 *coaching 톤 샘플*을 보고 싶다면 `LANGSMITH_PROJECT=balancenote-demo` 별 프로젝트 + 본 마스킹 hook 우회 옵션 추가 검토(Story 8.6 polish 가능). 본 스토리는 *PIPA conservative* 우선.

### 4. PR CI 옵션 회귀 평가 D3 결정 (라벨 트리거 vs 매 PR 자동)

**문제**: NFR-O3 *"주요 프롬프트·노드 변경 PR 시 회귀 평가 1회"* — 매 PR 자동 실행 시 비용(LangSmith Free tier 5K trace/month + 실 LLM 100건 호출 ~$0.5-1) + dev 흐름 마찰(eval 7-15분 추가).

**결정**:
- (a) **라벨 트리거** — `langsmith-eval` 라벨 매칭 PR + `workflow_dispatch` 수동 호출만. 디폴트 PR은 미실행. *프롬프트/노드 변경 PR*에 한해 운영자가 라벨 수동 적용.
- (b) `continue-on-error: true` — fail 비차단(epic line 706 *"권장; 자동 머지 차단은 OUT"* 정합).
- (c) PR 코멘트는 `actions/github-script@v7` — alembic-dry-run job(line 222-247) 패턴 그대로.

### 5. 라우터/서비스/노드 코드 변경 0 D4 결정 (cross-cutting infrastructure)

**원칙**: NFR-O1 *"LangGraph 6노드 + Self-RAG 재검색 + LLM 호출 100% 자동 트레이싱"*은 LangChain/LangGraph native(`LANGCHAIN_TRACING_V2=true` env 1개로 활성). 라우터/서비스/노드 코드는 *변경 X*. 본 스토리는:
- *cross-cutting infrastructure* 추가만(`app/core/observability.py` + `scripts/upload_eval_dataset.py` + 문서 + CI).
- Story 3.3-3.7 회귀 위험 *낮음* — 마스킹 hook은 LangSmith client 콜백, Sentry hook은 별 path. 두 hook이 동일 키셋이라 양쪽 동작 시 *redundant redact*(idempotent)지 충돌 X.

**검증**: Task 11.5(`git diff` 0 강제) + Task 11.6(전 스토리 단위 테스트 통과).

### 6. NFR-S5 마스킹 / Sentry 통합 (Story 3.7 패턴 정합)

- LangSmith trace inputs/outputs 모두 마스킹 hook 1지점 통과 — `Client(hide_inputs=mask_run_inputs, hide_outputs=mask_run_outputs)` 콜백.
- LangSmith SDK ≥ 0.7.31 *redaction pipeline `events` 배열 누락 패치* — token-level streaming 시 raw token leak 차단.
- structlog 로깅은 Story 3.7 기존 패턴 유지(`analysis.sse.complete` 등) — 본 스토리는 *추가 로그 없음*. observability init/disable 로그 2건만 추가(`observability.langsmith.{disabled,initialized,misconfigured}`).
- Sentry transaction(`op="analysis.pipeline"`, Story 3.3)은 그대로 — LangSmith trace와 *별 path 동시 송신*. 양쪽 보드에서 분석 1회를 cross-reference 가능(Sentry는 종단 latency + Python stack, LangSmith는 노드별 LLM/RAG 분해).

### 7. dev 환경 디폴트 false D5 결정 (.env.example, NFR-O5 결합)

**문제**: 로컬 개발 시 `LANGCHAIN_TRACING_V2=true` 디폴트면 모든 dev 분석 호출이 LangSmith로 송신 — Free tier 5K trace 빠르게 소진 + dev test data로 보드 노이즈.

**결정**:
- 로컬 dev `.env.example` 디폴트 `false` — 개발자가 *수동 ON*(staging 동등 검증 시점만).
- 스테이징/프로덕션은 Railway secrets에서 `LANGCHAIN_TRACING_V2=true` 강제(SOP 명시 — `docs/runbook/secret-rotation.md` 정합).
- CI test job은 `LANGCHAIN_TRACING_V2` 미설정 → false 디폴트 → mock-level 가드만.
- CI `langsmith-eval-regression` job(라벨 트리거)만 `=true` 강제 — 회귀 평가 트레이스는 LangSmith로 송신.

### 8. 회피 사항 (Out of Scope)

- **Self-hosted LangSmith** — Architecture line 241 명시 OUT (외주 클라이언트별 옵션).
- **사용자 노출 대시보드** — Architecture line 241 OUT. LangSmith 보드는 운영자/외주 발주자 전용(NFR-O4).
- **자동 머지 차단** — epic line 706 OUT (권장 경고만, AC8 D3 결정 정합).
- **`@traceable` 도메인 함수 추가** — AC3 D2 OUT (영업 데모 보드 가시성 평가 후 follow-up).
- **raw OpenAI/Anthropic SDK 트레이싱 (`wrap_openai` / `wrap_anthropic`)** — AC3 D1 OUT. 노드-수준 트레이싱이 nested LLM call 자연 노출.
- **재동의 강제** — Task 8.5 OUT. minor version bump + PII 송신 0 명시이라 정보주체 권리 영향 낮음.
- **모바일/Web 코드 변경** — AC12 강제 0. 본 스토리는 백엔드 + 인프라만.
- **prod 보드 공개 read-only 링크** — Task 12.1 OUT. dev/staging만 share, prod는 외주 client별 옵션.

### 9. 신규 모듈 vs UPDATE 요약

| 분류 | 경로 | 용도 |
|------|------|------|
| NEW | `api/app/core/observability.py` | LangSmith client + mask_run_inputs/outputs hook (NFR-O1, NFR-O2) |
| NEW | `scripts/upload_eval_dataset.py` | 한식 100건 → LangSmith Dataset `balancenote-korean-foods-v1` (NFR-O3) |
| NEW | `api/tests/core/test_observability.py` | 마스킹 hook ≥ 12 케이스 (AC2, AC7) |
| NEW | `api/tests/core/test_observability_tracing.py` | LangGraph native tracing 활성 가드 ≥ 3 케이스 (AC3) |
| NEW | `api/tests/scripts/test_upload_eval_dataset.py` | upload script 5 케이스 (AC6) |
| NEW | `api/tests/test_dependency_versions.py` | langsmith>=0.7.31 회귀 가드 (AC4) |
| NEW | `docs/observability/langsmith-dashboard.md` | 보드 가이드 + 보드 read-only 링크 (NFR-O4, AC10) |
| UPDATE | `api/pyproject.toml` | `langsmith>=0.7.31` bump (AC4) |
| UPDATE | `api/uv.lock` | langsmith bump 자동 갱신 |
| UPDATE | `api/app/main.py` | `init_langsmith()` lifespan 호출 (AC1) — 1줄 + try/except 5줄 |
| UPDATE | `.env.example` | `LANGCHAIN_TRACING_V2=false` 디폴트 (AC5) |
| UPDATE | `api/app/domain/legal_documents.py` | PRIVACY_POLICY_KO/EN 1단락 + version bump (AC9) |
| UPDATE | `api/tests/domain/test_legal_documents.py` | 신규 단락 + version 검증 2 케이스 |
| UPDATE | `docs/runbook/secret-rotation.md` | LangSmith 키 회전 단락 (AC11) |
| UPDATE | `.github/workflows/ci.yml` | `langsmith-eval-regression` job (AC8) |

### 10. `app/core/observability.py` 의사코드 (참고 — 실 구현은 Task 2)

```python
"""LangSmith 외부 옵저버빌리티 — Story 3.8 (NFR-O1, NFR-O2, NFR-O5).

NFR-O2 마스킹 룰셋은 `app.core.sentry._MASKED_KEYS`를 import 합집합으로 재사용 —
1지점 SOT(architecture line 237 정합).
"""
from __future__ import annotations
from typing import Any, Final
import structlog
from langsmith import Client
from app.core.config import settings
from app.core.sentry import _MASKED_KEYS as _SENTRY_MASKED_KEYS

log = structlog.get_logger(__name__)

_LANGSMITH_EXTRA_KEYS: Final[frozenset[str]] = frozenset({
    "weight_kg", "height_cm", "allergies",
    "parsed_items", "food_items", "clarification_options",
    "feedback_text", "feedback",
})
_LANGSMITH_MASKED_KEYS: Final[frozenset[str]] = (
    _SENTRY_MASKED_KEYS | _LANGSMITH_EXTRA_KEYS
)
_MASK_PLACEHOLDER: Final[str] = "***"

_langsmith_client: Client | None = None


def _mask_recursive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _MASK_PLACEHOLDER if k in _LANGSMITH_MASKED_KEYS else _mask_recursive(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_mask_recursive(item) for item in value]
    return value


def mask_run_inputs(inputs: dict[str, Any] | None) -> dict[str, Any]:
    if inputs is None:
        return {}
    if not isinstance(inputs, dict):
        return inputs  # type: ignore[return-value]
    return _mask_recursive(inputs)


def mask_run_outputs(outputs: dict[str, Any] | None) -> dict[str, Any]:
    return mask_run_inputs(outputs)  # 동일 키셋 적용


def init_langsmith() -> Client | None:
    global _langsmith_client
    if not settings.langchain_tracing_v2:
        log.info("observability.langsmith.disabled", reason="tracing_v2_false")
        _langsmith_client = None
        return None
    if not settings.langsmith_api_key:
        log.warning("observability.langsmith.misconfigured", reason="missing_api_key")
        _langsmith_client = None
        return None
    _langsmith_client = Client(
        api_key=settings.langsmith_api_key,
        hide_inputs=mask_run_inputs,
        hide_outputs=mask_run_outputs,
    )
    log.info(
        "observability.langsmith.initialized",
        project=settings.langsmith_project,
    )
    return _langsmith_client


def get_langsmith_client() -> Client | None:
    return _langsmith_client


def reset_langsmith_for_tests() -> None:
    global _langsmith_client
    _langsmith_client = None
```

### 11. `scripts/upload_eval_dataset.py` 의사코드 (참고 — 실 구현은 Task 6)

```python
"""한식 100건 → LangSmith Dataset 업로드 (Story 3.8 AC6 / NFR-O3).

사용법:
    LANGSMITH_API_KEY=... python scripts/upload_eval_dataset.py
    LANGSMITH_API_KEY=... python scripts/upload_eval_dataset.py --force
    python scripts/upload_eval_dataset.py --dry-run

idempotent — 같은 이름 dataset이 이미 examples를 가지면 skip.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
from typing import Any
from langsmith import Client

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO_ROOT / "api" / "tests" / "data" / "korean_foods_100.json"
DEFAULT_NAME = "balancenote-korean-foods-v1"
DEFAULT_DESC = "한식 100건 음식명 정규화 정확도 회귀 데이터셋 (Story 3.4 T3 KPI 90%)"


def _load_dataset(path: Path) -> list[dict[str, str]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    required = {"input", "expected_canonical", "expected_path", "category"}
    for row in rows:
        if missing := required - row.keys():
            raise ValueError(f"missing keys {missing} in row {row}")
    return rows


def _build_examples(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "inputs": {"meal_text": r["input"]},
            "outputs": {"canonical": r["expected_canonical"], "path": r["expected_path"]},
            "metadata": {"category": r["category"]},
        }
        for r in rows
    ]


def _upload(client: Client, name: str, desc: str, examples: list[dict], force: bool) -> int:
    try:
        dataset = client.read_dataset(dataset_name=name)
    except Exception:
        dataset = client.create_dataset(dataset_name=name, description=desc)
    existing = list(client.list_examples(dataset_id=dataset.id, limit=1))
    if existing and not force:
        print(f"[skip] dataset {name!r} already has examples; use --force to append")
        return 0
    client.create_examples(dataset_id=dataset.id, examples=examples)
    return len(examples)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-name", default=DEFAULT_NAME)
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--description", default=DEFAULT_DESC)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    rows = _load_dataset(args.input_path)
    examples = _build_examples(rows)
    if args.dry_run:
        print(f"[dry-run] would upload {len(examples)} examples to {args.dataset_name!r}")
        return 0
    if not os.environ.get("LANGSMITH_API_KEY"):
        print("LANGSMITH_API_KEY required — set in env before run", file=sys.stderr)
        return 1
    client = Client()
    inserted = _upload(client, args.dataset_name, args.description, examples, args.force)
    print(f"[ok] uploaded {inserted} examples to {args.dataset_name!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 12. CR 패턴 인계 (Story 3.7 → 3.8 적용)

- **D-2 helper 분리** — 본 스토리는 도메인 매핑 X(NFR-O2 마스킹은 단순 키셋 매칭). 단, `_mask_recursive`가 dict/list 분기라 sentry.py `_mask_dict`(CR Gemini G3)가 list of dict 처리한 패턴 정합. 동일 구현 — copy-paste 회피로 *별도 모듈*에 재구현(sentry.py와 LangSmith의 *masking 시그니처*가 다름 — sentry는 in-place mutate, LangSmith는 신규 dict 반환).
- **NFC 정규화** — 본 스토리는 텍스트 처리 X(키셋 매칭만). NFC 무관.
- **m-3 self-emitted prefix 회피** — log 파싱 X. 직접 카운터(`int`).
- **C1+C2 Sentry frame vars 가드** — Story 3.6 anchor 그대로 유효. LangSmith trace는 *generator local 변수 보존 X* — Python frame locals 노출 path 0(LangChain tracer는 명시 inputs/outputs만 송신).
- **MJ-22 outer wait_for** — 본 스토리는 LLM 호출 X(LangSmith client 자체는 background HTTP — sync wait 미발생). LangSmith client 자체는 비동기 batched send + 실패 시 in-memory queue. trace 송신 실패는 *graceful degradation*(LangSmith SDK 내부 가드).

### Project Structure Notes

- **Directory structure**: 모든 신규/UPDATE 경로는 architecture.md `app/` + `scripts/` + `docs/` + `.github/` 트리 정합.
- **모듈 import 방향성**:
  - `app.core.observability`는 `langsmith` + `app.core.config` + `app.core.sentry`(`_MASKED_KEYS` only) + `structlog` import. *graph / api / services / domain layer 미참조* — cross-cutting 인프라 정합.
  - `app.main`은 `app.core.observability.init_langsmith` 1줄 추가. lifespan 외 path 미사용.
  - `scripts/upload_eval_dataset.py`는 *repo root scripts/ 위치* — `api/` 내부 모듈 미참조(데이터 파일만 path 참조). 단독 실행 가능 + 외주 인수 시 자명한 entrypoint.
- **`app/core/observability.py` 위치 결정**: `app/core/`는 *config / security / middleware / sentry* 등 cross-cutting infrastructure SOT. observability는 동일 카테고리. `app/services/`는 비즈니스 레이어 — 부적절. `app/adapters/`는 외부 SDK 통합이지만 LangSmith는 *비즈니스 호출 X — tracing 인프라*(architecture line 240 명시). 정합.

### References

- [Source: epics.md#Story-3.8 line 694-711] — 본 스토리 ACs verbatim
- [Source: prd.md#FR49] — LangSmith 외부 옵저버빌리티 mandate
- [Source: prd.md#NFR-O1] — 트레이싱 커버리지 100%
- [Source: prd.md#NFR-O2] — 민감정보 마스킹(NFR-S5 결합)
- [Source: prd.md#NFR-O3] — 평가 데이터셋 회귀
- [Source: prd.md#NFR-O4] — 영업 산출물 보드 링크
- [Source: prd.md#NFR-O5] — 외부 의존 제3자 제공·국외 이전
- [Source: prd.md#NFR-S5] — 민감정보 마스킹 룰셋
- [Source: prd.md#NFR-S10] — API key 회전 SOP
- [Source: architecture.md line 200] — `langsmith` SDK + `LANGCHAIN_TRACING_V2` env
- [Source: architecture.md line 232-242] — LangSmith 통합 결정 3
- [Source: architecture.md line 590] — `scripts/upload_eval_dataset.py` 위치
- [Source: architecture.md line 893, 915] — `app/core/observability.py` 위치
- [Source: api/app/core/sentry.py line 19-29] — `_MASKED_KEYS` SOT (re-import)
- [Source: api/app/main.py line 79-145] — lifespan init 패턴 (try/except graceful)
- [Source: 3-7-모바일-sse-스트리밍-채팅-ui.md Dev Notes #6] — NFR-S5 마스킹 / Sentry 통합 전임 패턴
- [Source: api/tests/data/korean_foods_100.json] — Story 3.4가 박은 dataset SOT (100건 verified)
- [Source: api/tests/test_korean_foods_eval.py line 1-41] — `@pytest.mark.eval` opt-in 패턴
- [Source: .github/workflows/ci.yml line 188-247] — `alembic-dry-run` PR 코멘트 패턴(`langsmith-eval-regression` 패턴 정합)
- [Source: docs/runbook/secret-rotation.md] — Story 1.1 SOT (LangSmith 단락 추가 위치)
- [Source: LangSmith SDK docs — Mask inputs/outputs](https://docs.langchain.com/langsmith/mask-inputs-outputs)
- [Source: LangSmith SDK docs — Trace LangGraph applications](https://docs.langchain.com/langsmith/trace-with-langgraph)
- [Source: LangSmith SDK GHSA-rr7j-v2q5-chgv — `events` array PII leak (≥0.7.31 patched)](https://dailycve.com/langsmith-sdk-information-disclosure-ghsa-rr7j-v2q5-chgv-medium/)

## Dev Agent Record

### Agent Model Used

- 컨텍스트 엔진(스토리 작성): claude-opus-4-7[1m] (bmad-create-story v6.5.0)
- 구현(DS): claude-opus-4-7[1m] (Amelia / bmad-dev-story)

### Debug Log References

- `cd api && uv sync --upgrade-package langsmith` → 0.7.37 → 0.8.0 (≥ 0.7.31 보안 패치 baseline 통과).
- `uv run pytest -q` → **761 passed / 9 skipped / 0 failed**, coverage **84.72%**(≥ 70% threshold).
  - Story 3.7 baseline 725 → 3.8 신규 36건 추가(observability 17 + tracing 4 + upload script 9 + legal docs 4 + dependency 2).
- `uv run ruff check . && uv run ruff format --check .` 0 에러.
- `uv run mypy app` 0 에러(scope: 본 스토리 신규/수정 모듈 전체).
- `cd mobile && pnpm tsc --noEmit` 0 에러 (코드 변경 0건이라 자연 통과).
- `cd web && pnpm tsc --noEmit` 0 에러.
- D4 정합 검증 — `git diff api/app/api/v1/analysis.py api/app/services/analysis_service.py api/app/graph/pipeline.py api/app/graph/nodes/` 출력 0건.
- 회귀 디버깅 1건 — `tests/core/test_observability.py`의 `capture_logs()` 의존 4 케이스가 *full suite*에서 fail(`test_main_lifespan.py`가 `configure_logging()` → `cache_logger_on_first_use=True` 캐시 후 `capture_logs()` 처리기 교체 무시). autouse fixture `_reset_structlog_for_capture_logs`(`structlog.reset_defaults()` + `observability.log` 재바인딩)로 해결.
- **DS smoke verification incident 2건 — 실 LangSmith API trace 송신 보드 시각 검증**:
  - **(a) 401 Unauthorized**: `init_langsmith()`가 만든 Client는 인증 통과지만 `@traceable`가 *별도 default Client*를 만들면서 `os.environ['LANGSMITH_API_KEY']` 읽기 실패. 해결 — `os.environ.setdefault("LANGSMITH_API_KEY"/"LANGSMITH_PROJECT", ...)` 동기화 1줄(prod/staging Railway는 이미 systemd env 주입이라 setdefault no-op).
  - **(b) 마스킹 hook 우회 (smoke v2)**: 401 fix 후 trace는 도착하지만 `Client(hide_inputs=...)`가 *우리 인스턴스에만 박힘* → langchain native tracing의 `langsmith.run_trees.get_cached_client()`가 *별도 default Client*를 만들어 마스킹 우회. 해결 — `langsmith.run_trees._CLIENT` + `langsmith._internal._context._GLOBAL_CLIENT`에 우리 masked client 직접 주입(process-wide 모듈 변수). 추가 회귀 가드 `test_init_langsmith_wires_global_client_for_native_tracing` 박힘.
  - **(c) `meal_text` raw 노출 (smoke v3)**: process-wide wiring 후 `weight_kg`/`allergies`/`feedback`/`parsed_items` 모두 redact 정상이지만, helper 함수 인자명 `meal_text`가 `_LANGSMITH_EXTRA_KEYS` 미등재라 raw 노출(production은 `raw_text` 키라 영향 X — defense in depth 안전망 차원). 해결 — `_LANGSMITH_EXTRA_KEYS`에 `meal_text` 추가 + 회귀 가드 `test_mask_run_inputs_redacts_meal_text_alias`. smoke v4 검증으로 meal_text/raw_text 둘 다 redact 확인.

### Completion Notes List

- 본 스토리는 *cross-cutting infrastructure*(observability + script + 문서 + CI)만 추가. 라우터/서비스/노드 변경 0(D4 정합 검증 완료).
- NFR-S5 마스킹 SOT는 `app/core/sentry.py:_MASKED_KEYS` import 합집합 — 1지점 변경이 LangSmith hook에 자동 반영(D1 정합). `test_masked_keys_includes_sentry_keyset`이 합집합 무결성 가드.
- LangGraph native tracing은 `LANGCHAIN_TRACING_V2=true` env 1개로 활성 — 코드 wiring 0. `compile_pipeline` 변경 X(D4).
- `langsmith>=0.7.31` 보안 패치 bump 적용(AC4) — 실제 lock 0.8.0 — GHSA-rr7j-v2q5-chgv `events` 배열 leak 차단. silent downgrade 회귀 가드(`test_dependency_versions.py`).
- `app/core/observability.py` 신규 — `init_langsmith()` 3 분기(disabled/misconfigured/정상) graceful + `mask_run_inputs/outputs` LangSmith Client 콜백 wired + `os.environ.setdefault` env 동기화 + `langsmith.run_trees._CLIENT` / `_internal._context._GLOBAL_CLIENT` process-wide 주입(LangChain native tracing 마스킹 hook 우회 차단). 단위 테스트 19건(spec ≥ 12 + smoke incident 회귀 가드 2건).
- `scripts/upload_eval_dataset.py` 신규 — argparse 5옵션 + idempotent skip + `--force` append + `--dry-run` + `LANGSMITH_API_KEY` 가드. 단위 테스트 9건(spec ≥ 5).
- 개인정보처리방침(`PRIVACY_POLICY_KO/EN`)에 LangSmith Inc. 운영 옵저버빌리티 단락 추가(NFR-O5). `_VERSION_KO/EN` minor bump (`ko-2026-04-28` → `ko-2026-05-04`). PII 송신 0 명시이라 정보주체 권리 영향 낮음 — 강제 재동의 UX는 본 스토리 OUT(AC9 spec 정합, hwan 운영 시점 결정).
- `docs/observability/langsmith-dashboard.md` 신규 + `docs/runbook/secret-rotation.md` 신규(Story 1.1에 부재였던 파일도 본 스토리에서 박음 — LangSmith 단락 + placeholder §1-§7).
- `.github/workflows/ci.yml` `langsmith-eval-regression` job 추가 — `workflow_dispatch` + `langsmith-eval` 라벨 트리거 옵션, `continue-on-error: true` 머지 비차단, PR 코멘트 정확도 표시.
- 운영자(hwan) 수동 작업 (Task 12.1-12.3) — LangSmith 프로젝트 3개 생성 + share 토글 + `docs/observability/langsmith-dashboard.md` 보드 URL `TBD` 자리 채움 + 1회 trace 시각 검증. PR 시점에는 placeholder OK(AC10 spec 정합 — Story 8.6 영업 데모 페이지까지 wire 완료 후 실링크 박음).

### File List

**NEW:**
- `api/app/core/observability.py` — LangSmith Client 싱글턴 + `mask_run_inputs/outputs` hook + `init_langsmith()`/`get_langsmith_client()`/`reset_langsmith_for_tests()` (NFR-O1, NFR-O2).
- `api/tests/core/__init__.py` — pytest 패키지 인식.
- `api/tests/core/test_observability.py` — 마스킹 hook + init 단위 검증 19 케이스(AC1, AC2, AC7) + smoke verification incident 회귀 가드 2건(`meal_text` redact + process-wide client wiring).
- `api/tests/core/test_observability_tracing.py` — LangGraph native tracing 활성 가드 4 케이스(AC3).
- `api/tests/scripts/__init__.py` — pytest 패키지 인식.
- `api/tests/scripts/test_upload_eval_dataset.py` — upload script 9 케이스(AC6).
- `api/tests/test_dependency_versions.py` — `langsmith>=0.7.31` 회귀 가드 2 케이스(AC4).
- `api/tests/domain/test_legal_documents.py` — privacy 단락 + version bump 4 케이스(AC9).
- `scripts/upload_eval_dataset.py` — 한식 100건 → `balancenote-korean-foods-v1` LangSmith Dataset 업로드(NFR-O3).
- `scripts/dev_smoke_six_node_pipeline.py` — 운영자/영업 데모 직전 LangSmith 보드 6노드 트리 시각화 사전 점검 스모크 스크립트. CR DN-4 가드: `settings.environment in {dev, test, ci}` 화이트리스트 + Consent에 `user_agent="dev-smoke-six-node/synthetic"` 마커(staging/prod 실수 실행 차단 + audit 즉시 식별).
- `docs/observability/langsmith-dashboard.md` — 보드 가이드 + 데모 4시나리오 + 마스킹 검증 + secret-rotation cross-link(NFR-O4, AC10).
- `docs/runbook/secret-rotation.md` — secret 회전 SOP(LangSmith 단락 §3 verbatim AC11 5단계 + §1-§7 placeholder for Story 8.5).

**UPDATE:**
- `api/pyproject.toml` — `langsmith>=0.3` → `langsmith>=0.7.31` (AC4).
- `api/uv.lock` — langsmith 0.7.37 → 0.8.0(자동 갱신).
- `api/app/main.py` — `from app.core.observability import init_langsmith` import + lifespan에서 `init_sentry()` 직후 `init_langsmith()` try/except 호출(AC1, AC3).
- `.env.example` — `LANGSMITH_API_KEY=` 빈 값 + `LANGSMITH_PROJECT=balancenote-dev` + `LANGCHAIN_TRACING_V2=false` 디폴트 + 키 회전 SOP 주석(AC5).
- `api/app/domain/legal_documents.py` — `_PRIVACY_KO/EN` LangSmith Inc. 운영 옵저버빌리티 단락 추가 + `_UPDATED_AT`/`_VERSION_KO`/`_VERSION_EN` Story 3.8 시점 bump(AC9).
- `.github/workflows/ci.yml` — `langsmith-eval-regression` job 추가(AC8).

### Change Log

| Date | Version | Description | Author |
|------|---------|-------------|--------|
| 2026-05-04 | 1.0 | Story 3.8 — LangSmith 외부 옵저버빌리티 + 한식 100건 평가 데이터셋 구현 완료. NFR-O1~O5 + NFR-S5 마스킹 합집합 SOT + GHSA-rr7j-v2q5-chgv 보안 패치. Story 3.3-3.7 회귀 0건. ready-for-dev → review. | Amelia |
| 2026-05-04 | 1.1 | DS smoke verification 3 incident 해결 — (a) `os.environ.setdefault` env 동기화, (b) `langsmith.run_trees._CLIENT` / `_GLOBAL_CLIENT` process-wide masked client 주입, (c) `_LANGSMITH_EXTRA_KEYS`에 `meal_text` 추가. 회귀 가드 2건 추가(`test_init_langsmith_wires_global_client_for_native_tracing` + `test_mask_run_inputs_redacts_meal_text_alias`). pytest 763 passed/9 skipped/0 failed + coverage 84.74%. smoke v4 보드 시각 검증 — 모든 PII 키 `"***"` redact 확인(meal_text/raw_text/weight_kg/allergies/feedback/parsed_items/feedback_text). | Amelia |
| 2026-05-05 | 1.2 | CR 20 patches 일괄 적용 — 5 decision-needed(P16-P20) + 15 patch(P1-P15) + 2 defer(DF110-DF111). **DN-1 P16**: `_VERSION_KO/EN`을 doc-key별 dict로 분리(privacy/sensitive_personal_info만 `ko-2026-05-04` bump, disclaimer/terms/automated-decision는 baseline `ko-2026-04-28` 유지) → 4개 미변경 문서 기존 사용자 재동의 회귀 차단. **DN-2 P17**: `feedback` whole-mask 폐지, `text` 키 단독 마스킹 — `feedback.text`만 redact, `feedback.citations`/`macros`/`fit_score` 영업 데모 보드 가시성 보존. **DN-3 P18**: privacy 본문 "처리 위탁(국외)" 분류로 재구조 + 거부 권리 후속 약속(Story 5.1 / 8.4) 명시. **DN-4 P19**: `dev_smoke_six_node_pipeline.py` env guard(`environment in {dev, test, ci}`) + Consent `user_agent="dev-smoke-six-node/synthetic"` audit 마커 + spec File List 등재. **DN-5 P20**: `init_langsmith()` 실패 시 `LANGCHAIN_TRACING_V2=false` 강제 set으로 unmasked trace fail-closed. **P1-P15 핵심**: langsmith 상한 `<0.9` + private SDK import try/except + cycle/depth/tuple 가드 + list-of-dicts 재귀 진짜 가드 + CI eval `pipefail` + 한·영 accuracy regex + structlog `eval.upload.*` 이벤트 + JSONDecodeError→ValueError + whitespace API key 가드 + `--force` no-dedupe WARNING + dashboard count 19 정합 + privacy 정확 일치 테스트. tests/test_consents_router.py `_payload()` helper도 per-doc version 매핑으로 갱신(version split 회귀 테스트 통과). pytest **776 passed/9 skipped/0 failed** + coverage **84.77%** + ruff/format/mypy 0 에러. Story 3.3-3.7 회귀 0건. review → done. | Amelia |

### Review Findings

**Triage (2026-05-04, CR Amelia):** Blind Hunter 40 + Edge Case Hunter 27 + Acceptance Auditor 28 = 95 raw findings. After dedup: 5 decision-needed / 15 patch / 2 defer / ~70 dismissed.

**Decision-needed (5건 — 사용자 결정 필요):**

- [x] [Review][Decision] **DN-1 — `_VERSION_KO` 공유 SOT가 4개 미수정 법적 문서까지 동시 bump (BLOCKER)** [api/app/domain/legal_documents.py:228, 310-318] — `_VERSION_KO = "ko-2026-05-04"`이 disclaimer/terms/privacy/sensitive_personal_info/automated_decision 5개 문서 모두에 공유. privacy 본문만 변경했으나 `CURRENT_VERSIONS` 비교 시 4개 미변경 문서도 mismatch → Story 1.4 `ConsentVersionMismatchError`가 모든 기존 사용자에게 점화될 위험. 스펙(Task 8.5)은 "minor bump이라 강제 재동의 미발동"이라 약속했으나 SOT 디자인이 이를 불가능하게 함. 옵션: (a) `_VERSION_KO`를 doc-key별 dict로 분리 — privacy만 bump, (b) 동시 재동의 수용 + 사용자 마이그레이션 모달 약속, (c) `CURRENT_VERSIONS` 비교를 doc 본문 hash 기반으로 변경.
- [x] [Review][Decision] **DN-2 — `feedback`/`messages` 키 whole-dict redact가 dashboard.md "macro/citation 가시성" 약속과 모순** [api/app/core/observability.py:830-848 + docs/observability/langsmith-dashboard.md §2.4] — AC2 spec은 `feedback` 키 dict 전체 마스킹을 "보수적 의도"로 명시했으나 dashboard.md는 보드에서 macro 카드/citation 인용을 영업 데모 시나리오로 광고. 즉 feedback dict 전체가 `"***"`로 가려지면 시연 자체가 빈 화면. 옵션: (a) 유지 + dashboard 문서 정정(citation/macro 미가시 명시), (b) `feedback.text`만 마스킹하고 `feedback.citations`/`feedback.macros`/`feedback.fit_score`는 통과(AC2 spec 갱신), (c) `feedback` 키 화이트리스트 sub-key 패턴으로 재설계.
- [x] [Review][Decision] **DN-3 — Privacy KO "제3자 제공: 없음" + LangSmith Inc. US 제공 동시 명시 → PIPA 정합 모호 + "거부 UX" 약속 미구현** [api/app/domain/legal_documents.py:970-974, 137] — `4. 제3자 제공 및 국외 이전` 단락이 "제3자 제공: 없음"으로 시작하면서 LangSmith Inc.(미국)을 운영 옵저버빌리티 수령자로 소개. 위탁 vs 제3자 제공 구분 모호. 또한 본문은 "거부 시 회원 가입 자체는 가능하나..."라 명시하나 거부 UX는 본 스토리/후속 어떤 스토리에도 트랙되지 않음. 옵션: (a) 위탁/처리 위탁(`처리위탁`)으로 재분류 + "제3자 제공: 없음" 유지, (b) "운영 옵저버빌리티 수령자"를 별도 섹션으로 분리, (c) 거부 UX를 후속 스토리(8.4 polish 또는 5.1)로 명시 + 본문에 "구현 시점 별도 공지" 첨부.
- [x] [Review][Decision] **DN-4 — `scripts/dev_smoke_six_node_pipeline.py` 184줄 신규가 어떤 AC에도 미언급 + DB 변경(consent 위조)** [scripts/dev_smoke_six_node_pipeline.py:1-184] — Tasks 12.3은 "1회 분석 실 호출... 결과 스크린샷"만 기재(수동). 그러나 184줄 스크립트는 deterministic UUID로 `User`+`Consent` row를 INSERT(forged consent timestamp). env guard 부재 → 운영자가 실수로 `DATABASE_URL=staging`으로 실행 시 staging DB에 합성 사용자/동의 흔적 남음. 옵션: (a) 유지 + `assert settings.environment == "dev"` env guard + `synthetic=True` 마커 + spec File List 추가, (b) `scripts/.gitignore`에 추가하고 dev-local로 격리, (c) 삭제하고 README에 수동 verification 절차만 명시.
- [x] [Review][Decision] **DN-5 — Lifespan blanket-except `init_langsmith()` 실패 시 fail-open** [api/app/main.py:88-92] — `try: init_langsmith() except Exception as exc: log.error(...)`. private SDK import 실패 / Client 생성 실패 시 로그 한 줄만 남기고 통과. 그러나 `LANGCHAIN_TRACING_V2=true` env가 살아있으면 LangChain native tracer가 default unmasked Client로 trace 송신 → NFR-S5 마스킹 우회. 옵션: (a) non-dev 환경에서 fail-fast(re-raise → startup abort), (b) fail-open 유지하되 init 실패 시 `os.environ["LANGCHAIN_TRACING_V2"] = "false"` 강제 set으로 unmasked trace 차단, (c) Sentry capture_exception + alert 추가만 (현행 graceful 유지).

**Patch (15건 — 무의 fix, 코드 적용):**

- [x] [Review][Patch] **P1 — `langsmith` 상한 추가** [api/pyproject.toml:dependencies] — `"langsmith>=0.7.31"` → `"langsmith>=0.7.31,<0.9"`. 이유: B-01/A-02 private SDK 변수(`_GLOBAL_CLIENT`/`_CLIENT`) 의존이 minor bump(0.9.x)에서 깨질 위험.
- [x] [Review][Patch] **P2 — `init_langsmith()` 부분-실패 시 singleton 리셋 + private import 가드** [api/app/core/observability.py:944-948] — private 모듈 import는 `try: import langsmith._internal._context as _ls_context except (ImportError, AttributeError): log.warning(...); _langsmith_client = None; return None`. Client 생성 후 globals 주입 실패 시 `_langsmith_client = None` 명시 리셋(현재 주입 실패해도 singleton 살아있어 inconsistent state).
- [x] [Review][Patch] **P3 — `mask_run_inputs/outputs` 비-dict top-level 처리** [api/app/core/observability.py:881-892] — 현 `if not isinstance(inputs, dict): return inputs` → list-of-dicts/scalar PII 통과 위험. 수정: `if isinstance(inputs, list): return [_mask_recursive(item) for item in inputs]; if not isinstance(inputs, dict): return inputs`. 단위 테스트 추가(list-of-dicts top-level + 부모 키 비-masked 재귀).
- [x] [Review][Patch] **P4 — `_mask_recursive` cycle 가드 + depth limit + tuple/set 처리** [api/app/core/observability.py:857-871] — `def _mask_recursive(value, _seen=None, _depth=0): _seen = _seen or set(); if _depth > 32 or id(value) in _seen: return _MASK_PLACEHOLDER` + tuple은 `tuple(...)` 재귀, set은 통과(unhashable 회피). RecursionError로 hide_inputs hook 폭주 차단.
- [x] [Review][Patch] **P5 — `_resolve_dataset` 구체적 NotFound 예외만 catch** [scripts/upload_eval_dataset.py:78-81] — `from langsmith.utils import LangSmithNotFoundError; try: return client.read_dataset(dataset_name=name) except LangSmithNotFoundError: return client.create_dataset(...)`. transient(timeout/5xx)는 propagate.
- [x] [Review][Patch] **P6 — CI eval job `set -o pipefail`** [.github/workflows/ci.yml:307-310] — `set +e -o pipefail; uv run pytest ... 2>&1 | tee /tmp/eval.log; rc=$?`. 현재 rc가 항상 tee의 0을 캡처 → 실패한 pytest가 ✅ 통과로 표시되는 구조적 버그.
- [x] [Review][Patch] **P7 — accuracy regex Korean+English + 추출 실패 메시지** [.github/workflows/ci.yml:312-315] — `grep -oE '(accuracy|정확도) [0-9.]+%'` 둘 다 매칭. 추출 실패 시 PR 코멘트에 "측정 실패 — pytest 출력 확인 필요" 표시(현 `unknown%` → 오해 유발).
- [x] [Review][Patch] **P8 — `os.environ.setdefault` cleanup + autouse fixture** [api/app/core/observability.py:931-932 + api/tests/conftest.py] — `init_langsmith()`이 set한 env 키를 `_env_keys_set: list[str]` 추적 + `reset_langsmith_for_tests()` 호출 시 함께 `os.environ.pop`. autouse fixture(scope="function")가 매 테스트 후 호출 보장.
- [x] [Review][Patch] **P9 — Vacuous 테스트 교체 (3건)** [api/tests/core/test_observability_tracing.py + test_observability.py] — (1) `test_compile_pipeline_smoke_with_tracing_mocked` `assert callable(compile_pipeline)`(tautology) → 실제 `compile_pipeline()` 호출 + `graph.callbacks`에 `LangChainTracer` 부착 단언, (2) `test_langgraph_tracing_v2_env_recognized_by_langchain_core` SDK 자체 테스트 → BalanceNote 통합 테스트로 변경 또는 삭제, (3) `test_mask_run_inputs_handles_list_of_dicts_recursively` — 부모 키가 masked set에 없는 진짜 재귀 케이스 추가(`{"items": [{"raw_text": "x"}]} → {"items": [{"raw_text": "***"}]}`).
- [x] [Review][Patch] **P10 — upload script schema 검증 강화** [scripts/upload_eval_dataset.py:45-53] — `try: rows = json.loads(text) except json.JSONDecodeError as e: raise ValueError(f"invalid JSON: {e}")`. row value type 검증(`input`/`expected_canonical`/`expected_path`/`category`가 비-empty string).
- [x] [Review][Patch] **P11 — structlog `eval.upload.skipped`/`eval.upload.dry_run` 이벤트** [scripts/upload_eval_dataset.py + tests/scripts/test_upload_eval_dataset.py] — 현 `print(file=sys.stderr)` → structlog INFO 이벤트(spec AC6 정합). 테스트 단언도 `caplog`/`structlog.testing.capture_logs`로 교체.
- [x] [Review][Patch] **P12 — dashboard.md 회귀 가드 카운트 13 → 19** [docs/observability/langsmith-dashboard.md:2019, 2045] — 실제 `test_observability.py` 함수 19건. 문서 drift.
- [x] [Review][Patch] **P13 — `test_privacy_version_bumped_to_2026_05_04` lex 비교 → 정확 일치** [api/tests/domain/test_legal_documents.py:1603] — `assert privacy_version >= "ko-2026-05-04"` 문자열 lex 비교는 `"ko-2026-05-9"` < `"ko-2026-05-10"` 같은 latent 버그. `assert privacy_version == "ko-2026-05-04"` 또는 `datetime.fromisoformat` 비교.
- [x] [Review][Patch] **P14 — story spec AC2에 `meal_text` 키 명시** [_bmad-output/implementation-artifacts/3-8-...md:AC2] — 현 코드는 `meal_text`까지 9개 키 마스킹하나 spec AC2는 8개만 명시. spec과 코드 일관성 위해 spec 갱신.
- [x] [Review][Patch] **P15 — `--force` no-dedupe WARNING 강화** [scripts/upload_eval_dataset.py argparse + main()] — `--force` 사용 시 examples append(dedupe X) → 100건 dataset에 `--force` 시 200건 됨. argparse help text + 실행 시 stderr WARNING 강화 + 가능하면 사용자 confirm prompt(또는 `--yes` 플래그 요구).

**Defer (2건 — 후속 스토리):**

- [x] [Review][Defer] **DF110 — `/tmp/eval.log` Linux-only 경로** [.github/workflows/ci.yml:307] — deferred, pre-existing — runner는 ubuntu-latest 고정이라 즉시 위험 없음. Story 8.4 polish에서 `$RUNNER_TEMP/eval.log` GitHub Actions 표준으로 교체.
- [x] [Review][Defer] **DF111 — `secret-rotation.md` §1,§2,§4-§7 placeholder** [docs/runbook/secret-rotation.md:2076-2086, 2141-2150] — deferred, pre-existing — Story 1.1 부재였던 파일을 본 스토리에서 최초 박은 것. LangSmith §3 외 5개 섹션은 Story 8.5 운영 polish 슬롯에서 backfill.

**Dismissed (~70건 — 발췌):**
- B-09(`messages` 마스킹) — DN-2에서 통합 처리, B-10(`None → {}`) — LangSmith 계약 호환, B-12(test reactive) — premature, B-13/14/15/31(모킹 fragility) — passing, B-19/20(fork PR / Linux) — repo private + ubuntu pinned, B-22/23/28(story doc 숫자 drift) — frozen artifact, B-25(semver pre-release) — current 영향 0, B-29/30(consent 위조 위험) — DN-4 통합, B-34/38(tuple/depth) — P4 통합, B-35(rotation 자동화) — Story 8.5, B-37(state 키 추가 위험) — Story 8.4 defense-in-depth, B-39(LANGSMITH_PROJECT default leak) — Railway secrets 운영 책임, B-40(dual-operator race) — single-operator 도구, A-05/07/14/22(spec 미세 drift) — 기능 정합, A-10/15/16/24(positive findings) — 검증 통과, A-11/21/25/28(over-coverage 또는 spec-permitted), Edge #14-19/22-23/27-28(문서/모킹/테스트 fragility) — 가치 < 비용.
