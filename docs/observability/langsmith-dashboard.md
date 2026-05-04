# LangSmith 보드 운영 가이드 (Story 3.8)

> 운영자 + 외주 발주자(영업 카드 검증)용 — LangSmith 보드에서 BalanceNote LLM
> 동작·품질·추세를 cross-reference 하는 절차. NFR-O4 영업 산출물 보드 링크
> 정합.

## 1. 공개 read-only 보드 링크

| 환경 | 프로젝트 | 보드 URL | 비고 |
|------|----------|---------|------|
| dev | `balancenote-dev` | TBD (운영자가 LangSmith UI → Settings → Share → Public read-only 토글 후 채움) | 본 스토리 W3 종료 시점 |
| staging | `balancenote-staging` | TBD | Story 3.8 W3 종료 시점 wire |
| prod | `balancenote-prod` | (외주 client별 옵션 — 본 스토리 OUT) | architecture line 241 정합 |

운영자 워크플로우(Task 12.1):
1. LangSmith UI([https://smith.langchain.com](https://smith.langchain.com))에 운영자 계정으로 로그인.
2. `Projects` → `+ New Project` → 위 3개 이름으로 생성.
3. 각 프로젝트 → `Settings` → `Sharing` → `Public read-only` 토글 ON(dev/staging만).
4. 발급된 share URL을 본 표 `TBD` 자리 채움 + Story 8.6 영업 페이지에 wire.

## 2. 데모 보드 시나리오 — Story 8.6 영업 4포인트

발주자(외주 client)가 영업 카드를 검증할 때 *5분 안에 클릭해서 확인할 수 있는*
4시나리오:

### 2.1. 6노드 latency stacked bar chart

- LangSmith 보드 → `Runs` → 임의 분석 trace 1건 클릭.
- `Runs hierarchy`(왼쪽 트리) — 6노드(`parse_meal` → `retrieve_nutrition` →
  `evaluate_retrieval_quality` → `fetch_user_profile` → `evaluate_fit` →
  `generate_feedback`) per-node latency가 각 row로 노출.
- 노드별 평균 latency: dev 환경 baseline (mock LLM) — 모든 노드 ≤ 50ms.
  staging/prod 실 LLM — `generate_feedback` ~2-3s (LLM 본문 생성), 나머지
  ≤ 200ms.
- **영업 카드 키 메시지** — *"6노드 분해로 병목 즉시 식별 + cost·latency
  per-node attribution."*

### 2.2. Self-RAG 분기율 pie chart

- `Filters` → `Tags` → `route` 선택(노드별 routing tag — Story 3.4 wired).
- 4 분기 분포: `continue_directly` / `rewrite_query` / `request_clarification` /
  `node_error`. dev 환경 baseline (Story 3.3 결정성 stub) — 100% `continue`,
  staging/prod 실 LLM에서는 ~70% `continue` / 20% `rewrite` / 10% `clarify`
  분포 예상(NFR-A3 정합).
- **영업 카드 키 메시지** — *"음식명 모호성 자동 처리율 + 사용자 추가 입력 요청
  비율 추적 — 사용자 경험 개선 직결."*

### 2.3. LLM 호출 비용 추이 (cost dashboard)

- LangSmith 보드 → `Cost` 탭(2026-05 시점 Pricing tab UI). 일별 cost 추세
  + 모델별(`gpt-4o-mini` / `claude-haiku-4-5`) breakdown.
- staging baseline ~$0.5-1/day (dev usage). prod baseline은 외주 client별
  사용량 의존.
- **영업 카드 키 메시지** — *"LLM cost 일·월 단위 가시성 + dual-LLM router
  fallback 발동율 즉시 식별 — Anthropic fallback 빈도가 OpenAI quota
  안정성의 leading indicator."*

### 2.4. 한식 100건 회귀 평가 결과

- `Datasets` → `balancenote-korean-foods-v1` → `Runs` 탭 → 최신 eval run 클릭.
- per-row 정확도 + 카테고리별 분포(`metadata.category`) + Story 3.4 T3 KPI
  ≥ 90% 통과 여부.
- **영업 카드 키 메시지** — *"한식 100건 baseline + PR마다 회귀 측정 → prompt
  변경이 정확도에 미치는 영향 즉시 가시화."*

## 3. NFR-O2 마스킹 검증 가이드

PR 머지 후 *수동 verification 1회 권장* — `app/core/observability.py:mask_run_inputs/outputs`
hook이 LangSmith trace에서 정확히 동작하는지 시각 확인.

검증 절차:
1. `LANGCHAIN_TRACING_V2=true` + `LANGSMITH_API_KEY=...` 로컬 dev에서
   `POST /v1/analysis/stream` 호출(임의 식단 텍스트 + JWT).
2. LangSmith 보드 → `balancenote-dev` 프로젝트 → 방금 업로드된 trace 클릭.
3. `Inputs` 탭 — `raw_text` / `meal_text` / `weight_kg` / `height_cm` / `allergies` /
   `parsed_items` / `feedback_text` / `feedback.text` 필드 모두 `"***"` 표시 확인.
4. `meal_id` / `final_fit_score` / `phase` / `node_errors` / `feedback.citations` /
   `feedback.macros` / `feedback.fit_score` 등 비-PII 필드는 *원본 그대로* 노출됨을 확인
   (CR DN-2 — `feedback.text` 자연어만 마스킹, citation/macro/fit_score는 영업 데모
   가시성 보존).
5. 하나라도 raw value가 노출되면 즉시 `tests/core/test_observability.py`
   회귀 추가 + ``_LANGSMITH_MASKED_KEYS`` 키 보강.

대안 단위 테스트 — CI에서 자동 실행: `tests/core/test_observability.py:test_mask_run_inputs_*`
(NFR-O2 키별 redact 가드 19건 + cycle/depth/tuple 가드). PR 머지 차단 가드.

## 4. API key 회전 절차

LangSmith API key 회전 SOP는 [docs/runbook/secret-rotation.md](../runbook/secret-rotation.md)
의 *LangSmith API key 회전 절차* 단락 참조 (Story 3.8 AC11).

회전 주기 — 분기 1회(Story 8.5 운영 polish 단계에서 정기 자동화 검토).

## 5. 트러블슈팅

| 증상 | 원인 후보 | 조치 |
|------|----------|------|
| trace가 보드에 안 보임 | `LANGCHAIN_TRACING_V2 != "true"` 또는 `LANGSMITH_API_KEY` 미설정 | `.env` / Railway secrets 확인 + 라우터 재시작 |
| `LangSmith 401 Unauthorized` startup 로그 | 만료/회전된 key | secret-rotation.md 절차 + Railway secret 갱신 |
| inputs에 raw_text 노출 (마스킹 누락) | `_LANGSMITH_MASKED_KEYS` 키 누락 | `tests/core/test_observability.py` 회귀 케이스 추가 + observability.py 키셋 보강 |
| 회귀 평가 cost 폭증 | PR마다 `langsmith-eval` 라벨 자동 적용 (오용) | 라벨은 *프롬프트/노드 변경 PR*에 한해 수동 적용 — Story 3.8 D3 정합 |

## References

- [Source: prd.md#NFR-O1] — 트레이싱 커버리지 100%
- [Source: prd.md#NFR-O2] — 민감정보 마스킹(NFR-S5 결합)
- [Source: prd.md#NFR-O4] — 영업 산출물 보드 링크
- [Source: architecture.md line 232-242] — LangSmith 통합 결정 3
- [Source: api/app/core/observability.py] — 마스킹 hook + Client init SOT
- [Source: api/tests/core/test_observability.py] — NFR-O2 단위 회귀 가드 19건 + cycle/depth/tuple 가드
- [Source: api/tests/test_korean_foods_eval.py] — 한식 100건 회귀 평가 marker (`@pytest.mark.eval`)
- [Source: scripts/upload_eval_dataset.py] — `balancenote-korean-foods-v1` 업로드 스크립트
