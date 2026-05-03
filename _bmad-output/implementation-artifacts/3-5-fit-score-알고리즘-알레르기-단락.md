# Story 3.5: fit_score 알고리즘 + 알레르기 위반 단락

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **엔드유저(데모 페르소나)**,
I want **`evaluate_fit` 노드가 사용자 건강 프로필(나이/체중/신장/활동수준/`health_goal`/22종 알레르기)과 식사 영양(parse 결과 + RAG 매칭 nutrition)을 입력받아 0-100 *건강 목표 부합도 점수*를 산출하고(가중치 = Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15), 알레르기 위반 발견(`users.allergies` ∩ 식사 식별 알레르기 ≠ ∅) 시 즉시 `fit_score = 0` + `fit_reason = "allergen_violation"`로 단락(매크로/칼로리/균형 점수 무시)되며, 응답에 색상·숫자·텍스트 라벨 동시 노출용 `fit_label` band 필드가 포함되기를**,
so that **단일 점수로 한 끼의 건강 목표 정합 정도를 직관적으로 파악하고, 알레르기 위반은 절대 안전 우선으로 처리받으며(NFR-C5 SOP 정합), 색약 사용자도 색상 단독에 의존하지 않고 점수를 인지할 수 있다(NFR-A4)**.

본 스토리는 Epic 3(AI 영양 분석 — Self-RAG + 인용 피드백)의 *fit_score 결정성 알고리즘 + 알레르기 단락 가드 SOT*를 박는다 — **(a) `app/domain/bmr.py` 신규 — `compute_bmr_mifflin(*, sex, age, weight_kg, height_cm)`(Mifflin-St Jeor 1990 표준 식: 남성 `10w + 6.25h - 5a + 5`, 여성 `10w + 6.25h - 5a - 161` — kcal/day 반환) + `ACTIVITY_MULTIPLIERS: Mapping[ActivityLevel, float]`(sedentary 1.2 / light 1.375 / moderate 1.55 / active 1.725 / very_active 1.9 — Harris-Benedict 표준) + `compute_tdee(*, bmr, activity_level)`(BMR × multiplier — kcal/day 반환). `health_goal` 별 calorie deficit/surplus 적용은 *호출자 책임*(domain/fit_score.py에서 `weight_loss=-500`/`muscle_gain=+300`/`maintenance=0`/`diabetes_management=0` 적용 — 단순 lookup으로 분리)**, **(b) `app/domain/kdris.py` 신규 — `MacroTargets` Pydantic frozen BaseModel(`carb_pct: float` + `protein_pct: float` + `fat_pct: float`, sum ≈ 1.0 ± 0.001 invariant validator) + `KDRIS_MACRO_TARGETS: dict[HealthGoal, MacroTargets]` lookup table — 보건복지부 KDRIs 2020 AMDR + 대한비만학회/대한당뇨학회 권고 baseline: weight_loss(0.50/0.25/0.25), muscle_gain(0.45/0.30/0.25), maintenance(0.55/0.20/0.25), diabetes_management(0.45/0.25/0.30) + `get_macro_targets(health_goal: HealthGoal) -> MacroTargets`(KeyError fallback `maintenance` — fail-soft) + `get_calorie_adjustment(health_goal: HealthGoal) -> int`(weight_loss -500 / muscle_gain +300 / 그 외 0)**, **(c) `app/domain/fit_score.py` 신규 — *순수 결정성 알고리즘 SOT*: (i) `aggregate_meal_macros(parsed_items, retrieved_foods) -> MealMacros`(per-item nutrition을 quantity multiplier(1인분/200g/None → 1.0/2.0/1.0 휴리스틱)와 함께 aggregate — 매칭 실패 item은 0 처리 + `coverage_ratio: float`로 매칭율 노출 — `coverage_ratio < 0.5` 시 confidence 낮음 신호), (ii) `compute_macro_score(meal: MealMacros, target: MacroTargets) -> int`(meal의 탄/단/지 비율을 target과 비교 — `score = round(40 × (1 - min(2.0, total_deviation) / 2.0))` 0-40 clamp), (iii) `compute_calorie_score(meal_kcal: float, recommended_meal_kcal: float) -> int`(deviation_ratio = abs(meal-rec)/rec — `0~0.15 → 25, 0.15~0.30 → 25 × (1 - (deviation - 0.15)/0.15) clamp, > 0.30 → 0` — 0-25 clamp), (iv) `compute_balance_score(meal: MealMacros) -> int`(0-15 — 단백질 ≥ 10g +5, 식이섬유 ≥ 3g +5, 채소/과일 RetrievedFood category 1+ +5 — 부족 항목당 -5 from 15), (v) `detect_allergen_violations(parsed_items, retrieved_foods, user_allergies) -> set[str]`(parsed_items[].name + retrieved_foods[].name + nutrition.category에서 22종 라벨 substring + ALLERGEN_ALIAS_MAP 매핑 후 user_allergies와 intersect — set 반환), (vi) `compute_fit_score(*, profile: UserProfileSnapshot, parsed_items, retrieved_foods) -> FitEvaluation`(전체 통합 entry — 단계: 알레르기 위반 검출 → 위반 시 fit_score=0 단락 + fit_reason="allergen_violation" + reasons=[f"알레르기 위반: {a}"...], 정상 시 BMR→TDEE→meal target kcal=TDEE/3+adjustment/3 + macro/calorie/balance 합산 → 최종 점수 + fit_label band)**, **(d) `app/domain/fit_score.py:ALLERGEN_ALIAS_MAP` — 한국 음식명 → 22종 라벨 매핑 baseline 8-12건(예: `"계란"→"난류(가금류)"`, `"달걀"→"난류(가금류)"`, `"치즈"→"우유"`, `"요구르트"→"우유"`, `"버터"→"우유"`, `"쉬림프"→"새우"`, `"포크"→"돼지고기"`, `"비프"→"쇠고기"`, `"치킨"→"닭고기"`). 외주 인수 시 클라이언트가 자사 메뉴 alias 보강하는 SOP는 `data/README.md`(Story 3.1) 패턴 정합 — 본 baseline은 외식·배달 한국 데모 메뉴 검출률 우선**, **(e) `app/domain/fit_score.py:FIT_LABEL_BANDS` — `Literal["good", "caution", "needs_adjust", "allergen_violation"]` band 분류: 알레르기 위반 → `"allergen_violation"`, 80-100 → `"good"`, 60-79 → `"caution"`, 0-59 → `"needs_adjust"`. NFR-A4 색약 대응의 *백엔드 신호* — 모바일/웹이 색상+라벨+숫자 매핑(텍스트 라벨 i18n SOT — 한국어 직역은 클라이언트 i18n 자원 영역)**, **(f) `app/graph/state.py` 확장 — `FitEvaluation` Pydantic 모델 확장: 기존 `fit_score: int` + `reasons: list[str]` + 신규 `fit_reason: Literal["ok", "allergen_violation", "incomplete_data"]`(분석 실패 사유 분류) + 신규 `fit_label: Literal["good", "caution", "needs_adjust", "allergen_violation"]`(NFR-A4 band) + 신규 `components: FitScoreComponents`(`macro: int` + `calorie: int` + `allergen: int` + `balance: int` + `coverage_ratio: float` — 4 컴포넌트 분해 노출 — Story 3.6 인용 피드백 텍스트가 component별 reason 인용 가능 + Story 4.3 주간 리포트 분포 분석 입력)**, **(g) `app/graph/nodes/evaluate_fit.py` 갱신 — Story 3.3 stub(`fit_score=50`) 폐지 → *실 결정성 알고리즘*: (i) `state["user_profile"]` 부재 또는 `state["retrieval"]` 부재 시 `FitEvaluation(fit_score=0, reasons=["incomplete_data"], fit_reason="incomplete_data", fit_label="needs_adjust", components=FitScoreComponents.zero())` graceful 반환(downstream `generate_feedback`이 fallback 텍스트 — Story 3.6 책임), (ii) 정상 케이스 `compute_fit_score(profile=..., parsed_items=..., retrieved_foods=...)` 호출 → 결과 `model_dump()` dict 반환. **LLM 호출 X — 순수 결정성**(epic L641의 "Claude 보조 LLM"은 Story 3.6 듀얼-LLM router 책임 — 본 스토리는 *score 결정성 SOT만* 박음 — analytics는 LLM 미경유로 i18n/cost 안정)**, **(h) `app/graph/nodes/evaluate_fit.py` 마스킹 — `state["user_profile"]`의 weight/height/age/allergies raw 로그 X(NFR-S5 SOT 정합 — Story 3.4 패턴 정합). fit_score + fit_label + components(int만) + violated_count + latency_ms만 1줄 INFO 로그**, **(i) 테스트 인프라 — `api/tests/domain/test_bmr.py` 신규 — Mifflin 남/녀 + 5 activity multiplier × 2 baseline 케이스 ≥ 12건(epic L650 ≥ 10 만족) + edge(0/음수/극단값 → ValueError) + `api/tests/domain/test_kdris.py` 신규 — 4 health_goal lookup + invariant(sum=1.0) + invalid → fallback maintenance + `api/tests/domain/test_fit_score.py` 신규 — Macro/Calorie/Balance 컴포넌트 단위 + aggregate_meal_macros quantity 휴리스틱 + detect_allergen_violations alias 매핑 + `api/tests/domain/test_fit_score_allergen_22.py` 신규 — *22종 알레르기 100% 케이스 회귀 가드*(epic L654 ≥ 22건 100% 통과 정합 — 각 알레르기에 대해 user_allergies=[allergen] + meal_text=음식 매칭 → fit_score=0 + fit_reason=allergen_violation 검증) + `api/tests/graph/nodes/test_evaluate_fit.py` 갱신 — 결정성 알고리즘 happy path / incomplete profile / allergen short-circuit / coverage_ratio 낮음 / fit_label band 분기 4종**, **(j) `data/README.md` Story 3.5 섹션 추가 — KDRIs AMDR baseline 권장 비율 + Mifflin BMR 식 + ALLERGEN_ALIAS_MAP 외주 클라이언트 보강 SOP 1페이지(8-12 → 50+ 확장 권장 사항) + 의료기기 미분류 정합(`fit_score` 명명 + UI 푸터 — prd.md L409 정합 — *"건강 목표 부합도 점수 — 의학적 진단이 아닙니다"* 동일 SOT)**, **(k) sprint-status — 3-5 backlog → in-progress → review(DS 종료 시) → done(CR 완료 시 PR commit 포함). 단일 commit + push, PR은 CR 완료 후**의 결정성 SOT를 박는다.

부수적으로 (a) **인용형 피드백 + 광고 표현 가드는 OUT** — `generate_feedback`은 Story 3.3 stub(`text="(분석 준비 중)"` + `used_llm="stub"`) 유지, Story 3.6 책임. 본 스토리 fit_score `components` 분해는 *Story 3.6 시스템 프롬프트가 인용*할 *입력 데이터*만 박음, (b) **듀얼-LLM router(`adapters/llm_router.py`) + Anthropic Claude fallback은 OUT** — Story 3.6 책임. 본 스토리는 *evaluate_fit 노드에서 LLM 호출 X* — 순수 결정성 알고리즘만(Claude 호출 가정 epic L641 wording은 Story 3.6 fit/feedback 통합 시점에 "보조 LLM"이 활용 — 본 스토리는 *결정성 score SOT*만), (c) **모바일 SSE 채팅 UI fit_score 카드 + 색상/숫자/텍스트 라벨 렌더링은 OUT** — Story 3.7 책임. 본 스토리 응답의 `fit_label` band 필드(Literal 4종)는 *백엔드 신호*만. UI 한국어 텍스트 라벨(*"양호"/"주의"/"조정 필요"/"알레르기 위반"*)은 모바일 i18n 자원, (d) **meal_analyses 테이블 영속화(meal_id, fit_score, fit_reason, components, citations) + Web 주간 리포트 차트 입력은 OUT** — Story 3.6 `generate_feedback` 후처리 단계 책임. 본 스토리 `evaluate_fit`은 *state 갱신*(`state["fit_evaluation"] = ...`)만, DB 쓰기 X, (e) **PIPA 동의 게이트(`Depends(require_automated_decision_consent)`)는 OUT** — Story 3.7 분석 라우터 책임(architecture L311 정합). 본 스토리 `evaluate_fit` 노드는 라우터 노출 X — 게이트 적용 X, (f) **Rate limit 적용은 OUT** — Story 3.7/8.4 책임, (g) **LangSmith 외부 옵저버빌리티 + `mask_run` hook은 OUT** — Story 3.8 책임. 본 스토리는 native 자동 트레이스 활성화 시 동작하지만, *`state["user_profile"]` PII 마스킹 hook 부착*은 3.8, (h) **Redis 캐시(`cache:llm:{...}`)는 OUT** — Story 3.6 정합. 본 스토리는 *순수 결정성 함수*라 캐시 ROI 0(동일 입력 → 동일 출력 보장 + 계산 < 5ms), (i) **fit_score 정밀 튜닝(W2 spike 후 KDRIs 권고 비율 미세 조정·BMR 변형 도입·`age × sex × ethnicity` 보정 등)은 OUT** — Story 8.4 polish 슬롯. 본 스토리 baseline은 *MVP 데모 가능 정확도*가 통과 기준, (j) **`saturated_fat_g`/`sodium_mg`/`sugar_g` 등 micronutrient 점수는 OUT** — `compute_balance_score`는 단백질·식이섬유 + category 다양성 3 컴포넌트만. 미세영양소는 Story 4.4 인사이트 카드/Story 8.4 polish 슬롯, (k) **알레르기 alias map 50+ 확장(외식·배달 메뉴 다양성)은 OUT** — `data/README.md` SOP 등재 + 외주 인수 클라이언트 보강 영역. 본 스토리 baseline 8-12건은 *9포인트 데모 시나리오* 통과 + T7 100% 케이스 검증 정합.

## Acceptance Criteria

> **BDD 형식 — 각 AC는 독립적 검증 가능. 모든 AC 통과 후 `Status: review`로 전환하고 code-review 워크플로우로 진입.**

1. **AC1 — `app/domain/bmr.py` 신규 — Mifflin-St Jeor BMR + Activity TDEE**
   **Given** Story 1.5 baseline `ActivityLevel` 5종 Literal SOT(`app.domain.health_profile`), **When** `from app.domain.bmr import compute_bmr_mifflin, compute_tdee, ACTIVITY_MULTIPLIERS` import, **Then**:
   - **`compute_bmr_mifflin(*, sex: Literal["male", "female"], age: int, weight_kg: float, height_cm: float) -> float`** — Mifflin-St Jeor 1990 표준식. 남성 `10*w + 6.25*h - 5*a + 5`, 여성 `10*w + 6.25*h - 5*a - 161`. **반환 단위 kcal/day**, 양수 float. **입력 검증** — `age < 1` or `age > 150` or `weight_kg <= 0` or `height_cm <= 0` → `ValueError("invalid bmr inputs")`(`users` CHECK 제약 정합 + fail-fast).
   - **`ACTIVITY_MULTIPLIERS: Mapping[ActivityLevel, float]`** — 5단계 표준 계수 SOT: `sedentary=1.2`, `light=1.375`, `moderate=1.55`, `active=1.725`, `very_active=1.9`. Harris-Benedict 활동 계수 기반(prd.md L745 KDRIs AMDR 매크로 룰 정합). `Mapping` 타입(immutable view) — runtime 변경 불가.
   - **`compute_tdee(*, bmr: float, activity_level: ActivityLevel) -> float`** — `bmr * ACTIVITY_MULTIPLIERS[activity_level]` — 양수 float. 알 수 없는 `activity_level`은 Literal 타입이 컴파일타임 차단 + runtime KeyError raise(LangGraph 노드는 `_node_wrapper`가 NodeError로 변환).
   - **`UserProfileSnapshot.sex` 부재 가드** — `UserProfileSnapshot`(state.py L97-108)은 현재 `sex` 필드 미보유. **본 스토리에서 `compute_bmr_mifflin`을 *직접 호출하는 caller* (`fit_score.py`)가 *암묵 default `"female"`*** 를 적용(데모 페르소나 *지수* 정합 — prd.md L275). `UserProfileSnapshot`에 `sex` 필드 추가는 OUT(Story 1.5 변경 범위 외 — 추가 시 alembic + Pydantic + fetch_user_profile + tests 6 모듈 변경 → 본 스토리 범위 폭증 → Story 8.4 polish 슬롯). **default 결정 사유 docstring 명시 + `data/README.md` SOP 등재**.
   - **NFR-S5 마스킹** — bmr/tdee 함수 자체는 입력 raw 로그 X(pure function — caller 책임). caller(fit_score) 로그도 `tdee_kcal` 정수만(weight/height/age 라벨 X).
   - **테스트** — `api/tests/domain/test_bmr.py` 신규 — (i) male `(age=30, w=70, h=175)` → `10*70 + 6.25*175 - 5*30 + 5 = 1648.75`, (ii) female `(age=30, w=60, h=165)` → `10*60 + 6.25*165 - 5*30 - 161 = 1320.25`, (iii) sedentary multiplier 1.2 적용 TDEE, (iv-viii) 5 activity 모두 `bmr × multiplier` 정합, (ix) age=0 → ValueError, (x) weight_kg=-1 → ValueError, (xi) height_cm=0 → ValueError, (xii) very_active female age=50 baseline. 총 ≥ 12건(epic L650 ≥ 10 충족).

2. **AC2 — `app/domain/kdris.py` 신규 — KDRIs AMDR 매크로 룰 lookup**
   **Given** Story 1.5 baseline `HealthGoal` 4종 Literal SOT, **When** `from app.domain.kdris import MacroTargets, KDRIS_MACRO_TARGETS, get_macro_targets, get_calorie_adjustment` import, **Then**:
   - **`MacroTargets` Pydantic frozen BaseModel** — `model_config = ConfigDict(extra="forbid", frozen=True)` + 3 필드 `carb_pct: float = Field(ge=0, le=1)` + `protein_pct: float = Field(ge=0, le=1)` + `fat_pct: float = Field(ge=0, le=1)`. **invariant validator** — `@model_validator(mode="after")`로 `abs(carb + protein + fat - 1.0) < 0.001` 검증, 위반 시 `ValueError("macro targets must sum to 1.0")`.
   - **`KDRIS_MACRO_TARGETS: dict[HealthGoal, MacroTargets]` lookup table** — 보건복지부 KDRIs 2020 AMDR + 대한비만학회 9판 + 대한당뇨병학회 권고 baseline:
     - `weight_loss`: `MacroTargets(carb_pct=0.50, protein_pct=0.25, fat_pct=0.25)` (체중 감량 단백질 우선 + 지방 절제),
     - `muscle_gain`: `MacroTargets(carb_pct=0.45, protein_pct=0.30, fat_pct=0.25)` (근비대 단백질 1.6-2.0g/kg 정합),
     - `maintenance`: `MacroTargets(carb_pct=0.55, protein_pct=0.20, fat_pct=0.25)` (KDRIs AMDR 중간값),
     - `diabetes_management`: `MacroTargets(carb_pct=0.45, protein_pct=0.25, fat_pct=0.30)` (당뇨 탄수화물 절감 + 식이섬유 우선 — 대당학회 매크로 권고).
     **각 행에 인용 docstring**: 출처 baseline 1줄(Story 3.6 인용 피드백 시스템 프롬프트가 본 docstring을 *직접 참조 X* — RAG로 별도 검색 — 본 스토리는 *내부 SOT*만).
   - **`get_macro_targets(health_goal: HealthGoal) -> MacroTargets`** — `KDRIS_MACRO_TARGETS[health_goal]` lookup. 알 수 없는 enum은 `KDRIS_MACRO_TARGETS["maintenance"]` fail-soft fallback + `log.warning("kdris.unknown_health_goal", value=...)`. *`health_goal`이 None인 경우*도 동일 fallback(`fetch_user_profile`이 None 보장 막지만, 회귀 가드).
   - **`get_calorie_adjustment(health_goal: HealthGoal) -> int`** — kcal/day adjustment lookup: `weight_loss=-500`, `muscle_gain=+300`, `maintenance=0`, `diabetes_management=0`. fail-soft fallback 0.
   - **테스트** — `api/tests/domain/test_kdris.py` 신규 — (i) 4 health_goal MacroTargets sum=1.0 invariant, (ii) `MacroTargets(carb_pct=0.5, protein_pct=0.3, fat_pct=0.3)` → ValueError(sum=1.1), (iii) `frozen=True`로 instance attribute set 시 ValidationError, (iv) 4 health_goal `get_macro_targets` 정합, (v) 알 수 없는 enum → fallback maintenance + warn 로그, (vi) `get_calorie_adjustment` 4 enum 매핑.

3. **AC3 — `app/domain/fit_score.py` 신규 — 결정성 SOT (`compute_fit_score` entry)**
   **Given** AC1 BMR/TDEE + AC2 KDRIs lookup + Story 1.5 22종 알레르기 SOT + Story 3.4 `RetrievedFood`(name+nutrition jsonb), **When** `from app.domain.fit_score import compute_fit_score, FitScoreComponents` import, **Then**:
   - **`FitScoreComponents` Pydantic frozen BaseModel** — `extra="forbid"`, `frozen=True`. 필드: `macro: int = Field(ge=0, le=40)` + `calorie: int = Field(ge=0, le=25)` + `allergen: int = Field(ge=0, le=20)` + `balance: int = Field(ge=0, le=15)` + `coverage_ratio: float = Field(ge=0, le=1)`. classmethod `zero()` — 모든 필드 0(incomplete data fallback). classmethod `allergen_violation()` — `macro=0, calorie=0, allergen=0(단락 표시), balance=0, coverage_ratio=0.0`(단락 케이스 표준 직렬화).
   - **`compute_fit_score(*, profile: UserProfileSnapshot, parsed_items: list[FoodItem], retrieved_foods: list[RetrievedFood]) -> FitEvaluation`** — *결정성 entry*. 단계:
     - **(i) 알레르기 위반 1차 검출** — `violations = detect_allergen_violations(parsed_items, retrieved_foods, profile.allergies)`. **`violations` 비어있지 않으면 *즉시 단락*** — `FitEvaluation(fit_score=0, fit_reason="allergen_violation", fit_label="allergen_violation", reasons=[f"알레르기 위반: {a}" for a in sorted(violations)], components=FitScoreComponents.allergen_violation())` 반환(매크로/칼로리/균형 계산 X — 비용 절약 + epic L652 단락 약속 정합).
     - **(ii) `parsed_items` 빈 리스트 또는 `profile` 미완** — `FitEvaluation(fit_score=0, fit_reason="incomplete_data", fit_label="needs_adjust", reasons=["parsed_items 또는 user_profile 부재"], components=FitScoreComponents.zero())` graceful 반환.
     - **(iii) 정상 케이스** — `bmr = compute_bmr_mifflin(sex="female", age=profile.age, weight_kg=profile.weight_kg, height_cm=profile.height_cm)`(default `sex="female"` — AC1 docstring 정합), `tdee = compute_tdee(bmr=bmr, activity_level=profile.activity_level)`, `target_meal_kcal = (tdee + get_calorie_adjustment(profile.health_goal)) / 3.0`(3끼 분배 가정), `target_macros = get_macro_targets(profile.health_goal)`.
     - **(iv) 컴포넌트 합산** — `meal = aggregate_meal_macros(parsed_items, retrieved_foods)`, `macro_score = compute_macro_score(meal, target_macros)` (0-40), `calorie_score = compute_calorie_score(meal.kcal, target_meal_kcal)` (0-25), `balance_score = compute_balance_score(meal, retrieved_foods)` (0-15), `allergen_score = 20`(violation 없으면 만점 — 단락 케이스는 step (i)에서 이미 처리), `total = macro_score + calorie_score + allergen_score + balance_score`(0-100 합).
     - **(v) `fit_label` band 분류** — `band_for_score(total)`: `total >= 80` → `"good"`, `60 <= total < 80` → `"caution"`, `total < 60` → `"needs_adjust"`. 알레르기 위반 케이스는 step (i)에서 `"allergen_violation"` 직접 set.
     - **(vi) 반환** — `FitEvaluation(fit_score=total, fit_reason="ok", fit_label=band, reasons=[<component summary>...], components=FitScoreComponents(macro=macro_score, calorie=calorie_score, allergen=20, balance=balance_score, coverage_ratio=meal.coverage_ratio))`. `reasons`는 1-3건의 짧은 한국어 (예: `"탄수화물 비중 71% — 권장 50% 초과"`, `"칼로리 적정 범위(±15%)"` — 본 스토리는 string baseline, Story 3.6 인용 피드백 generation의 *입력*).
   - **NFR-S5 마스킹** — `compute_fit_score` 자체는 함수 — 호출자(evaluate_fit 노드)가 마스킹 SOT. domain 함수 내부 raw weight/height/age 로그 X(`structlog` 사용 X — 순수 함수).
   - **결정성 / 캐싱 X** — 동일 입력 → 동일 출력 보장(test 스냅샷 안정 — Story 3.6 시스템 프롬프트 회귀 측정 입력 안정화). 부동소수 미세 차이는 `round()`로 정수 출력 + `coverage_ratio`만 float 0-1.
   - **테스트** — `api/tests/domain/test_fit_score.py` 신규 — (i) `FitScoreComponents` invariant 0-40/0-25/0-20/0-15 + frozen, (ii) `compute_fit_score` happy path(*지수* persona — female 30세 60kg 165cm light + weight_loss + 짜장면 1인분 + RetrievedFood nutrition jsonb 시뮬레이션) → 합리적 score 60-80 범위 + components 분해 노출, (iii) incomplete_data(빈 parsed_items) → fit_score=0 + fit_reason=incomplete_data, (iv) coverage_ratio < 0.5(2개 item 중 1개 매칭 실패) → score 손실 + reasons에 "매칭 신뢰도 낮음" 포함, (v) `aggregate_meal_macros`가 quantity="1인분" → multiplier 1.0, "200g" → 2.0(휴리스틱), None → 1.0, (vi) `compute_macro_score` 정확 매칭 시 40, (vii) `compute_calorie_score` ±15% → 25, ±30% → 0, (viii) `compute_balance_score` 단백질/식이섬유/카테고리 분기, (ix) `band_for_score`(95→good, 70→caution, 30→needs_adjust). 총 ≥ 18건(coverage ≥ 90% 신규 모듈 권장).

4. **AC4 — `app/domain/fit_score.py:detect_allergen_violations` + `ALLERGEN_ALIAS_MAP` baseline**
   **Given** Story 1.5 22종 알레르기 SOT + AC3 fit_score 단락 가드, **When** `from app.domain.fit_score import detect_allergen_violations, ALLERGEN_ALIAS_MAP` import, **Then**:
   - **`detect_allergen_violations(parsed_items: list[FoodItem], retrieved_foods: list[RetrievedFood], user_allergies: list[str]) -> set[str]`** — 단계:
     - **(a) 검색 텍스트 수집** — `texts = [item.name for item in parsed_items] + [food.name for food in retrieved_foods] + [food.nutrition.get("category", "") for food in retrieved_foods if food.nutrition]`. 빈 문자열 제외.
     - **(b) 22종 라벨 substring 매칭** — 각 `text`에 대해 `KOREAN_22_ALLERGENS` 22 라벨 중 `label in text`(substring). 매칭된 라벨을 `detected: set[str]`에 추가.
     - **(c) ALLERGEN_ALIAS_MAP 매핑** — `text`에 대해 `ALLERGEN_ALIAS_MAP` (예: `{"계란": "난류(가금류)", "달걀": "난류(가금류)", "치즈": "우유", "요구르트": "우유", "버터": "우유", "쉬림프": "새우", "포크": "돼지고기", "비프": "쇠고기", "치킨": "닭고기", "오믈렛": "난류(가금류)", "마요네즈": "난류(가금류)", "넛": "호두"}` baseline 8-12건) substring 매칭 → 매칭 발견 시 `detected.add(value)` (22종 표준 라벨로 정규화).
     - **(d) `user_allergies` 교집합** — `user_allergies = [unicodedata.normalize("NFC", a) for a in user_allergies]`(NFD 안전 — Story 1.5 패턴 정합) 후 `detected & set(user_allergies)` set 반환.
   - **`ALLERGEN_ALIAS_MAP: dict[str, str]`** — 8-12건 한국 외식·배달 메뉴 baseline 매핑. **22종 라벨 자체와 동일 키 등재 X**(키는 *alias*, 값은 *22종 표준 라벨* — 직접 매칭은 step (b)가 처리). **외주 인수 SOP** — `data/README.md`에 *클라이언트 자사 메뉴별 alias 보강 1페이지* 섹션 추가.
   - **NFC 정규화** — Story 1.5 패턴 정합. macOS 클립보드 paste의 NFD 인코딩이 `users.allergies`에 들어와도 22종 SOT와 매칭 가능. `parsed_items[].name`/`retrieved_foods[].name`도 NFC 정규화 후 substring 매칭(false negative 회피).
   - **빈 `user_allergies` 안전** — 빈 리스트 입력 → 빈 set 반환(intersect 안전, AttributeError X).
   - **테스트** — `api/tests/domain/test_fit_score.py`에 통합(별도 함수 묶음) — (i) 22종 직접 매칭(예: `parsed_items=[FoodItem(name="땅콩버터")] + user_allergies=["땅콩"]` → `{"땅콩"}`), (ii) ALLERGEN_ALIAS_MAP 매핑(`parsed_items=[FoodItem(name="치즈피자")] + user_allergies=["우유"]` → `{"우유"}`), (iii) `retrieved_foods.nutrition.category` 매칭(`category="조개류"` + `user_allergies=["조개류(굴/전복/홍합 포함)"]` — substring 정합 검증), (iv) 빈 user_allergies → 빈 set, (v) violation 없음(`parsed_items=[FoodItem(name="채소볶음")]` + `user_allergies=["땅콩"]`) → 빈 set, (vi) 다중 violation(`parsed_items=[FoodItem(name="우유땅콩쿠키")]` + `user_allergies=["우유", "땅콩"]`) → `{"우유", "땅콩"}`, (vii) NFD-encoded `user_allergies` → 정상 매칭(NFC 정규화), (viii) ALLERGEN_ALIAS_MAP 8-12건 모두 SOT 22종 매핑 검증(invariant test).

5. **AC5 — 22종 알레르기 100% 회귀 가드 (`api/tests/domain/test_fit_score_allergen_22.py`)**
   **Given** AC4 detection + AC3 단락 가드, **When** `pytest api/tests/domain/test_fit_score_allergen_22.py` 실행, **Then**:
   - **22 케이스 매개변수화 테스트** — `pytest.mark.parametrize`로 22종 알레르기 각각에 대해 1 케이스 — `(allergen, food_name)` 튜플 22행. 각 행: `food_name`은 `allergen` 또는 `ALLERGEN_ALIAS_MAP`의 key를 substring으로 포함하는 한국 음식명(예: `("우유", "우유라떼")`, `("메밀", "메밀국수")`, `("땅콩", "땅콩버터쿠키")`, `("새우", "쉬림프카레")`, `("난류(가금류)", "달걀말이")`, ...).
   - **각 케이스 검증** — `compute_fit_score(profile=UserProfileSnapshot(allergies=[allergen], ...), parsed_items=[FoodItem(name=food_name, confidence=0.9)], retrieved_foods=[])` 호출 → `result.fit_score == 0` + `result.fit_reason == "allergen_violation"` + `result.fit_label == "allergen_violation"` + `result.reasons[0].startswith("알레르기 위반:")` + `allergen in result.reasons[0]`.
   - **22 라벨 무결성** — `KOREAN_22_ALLERGENS`와 매개변수 `allergen` 컬럼 1:1 정합 검증(SOT drift 회귀 가드).
   - **NFR-C5 정합** — epic L654 *"≥ 22건(각 알레르기 1건) 100% 통과"* 정합. 본 테스트는 *PR 머지 전 default 실행*(`@pytest.mark.eval` skip X — fast pure function — 게이트 통과).
   - **`기타` 알레르기 처리** — 22종 마지막 항목 `"기타"`는 generic — *substring 매칭 false positive 위험*(예: `"기타치킨"` → 단어 `"기타"`로 false 단락). **본 스토리 baseline은 generic substring 우선** — 외주 클라이언트가 `"기타"` 알레르기 등록 시 자기 메뉴별 explicit alias로 보강하는 SOP는 `data/README.md` 등재. 본 22 케이스 테스트는 `"기타"`는 explicit `food_name="기타알레르기성분"` (인위적 명시 매칭 — false positive 회피)으로 검증.
   - **테스트** — 위 매개변수화 22 케이스 + ALLERGEN_ALIAS_MAP 8-12 케이스 별도(detection 매칭 layer 검증 — `detect_allergen_violations` 단위) + invariant 1 케이스(22 케이스의 `allergen` 컬럼이 `KOREAN_22_ALLERGENS`와 정확 일치 — SOT drift 가드) ≥ 31 케이스(epic L654 ≥ 22 충족 + alias 보강).

6. **AC6 — `app/graph/state.py` 확장 — `FitEvaluation` + `FitScoreComponents`**
   **Given** Story 3.3 baseline `FitEvaluation(fit_score, reasons)` Pydantic, **When** `from app.graph.state import FitEvaluation, FitScoreComponents` import, **Then**:
   - **`FitScoreComponents` import** — `from app.domain.fit_score import FitScoreComponents` 재노출(`app/graph/state.py` 모듈 attribute로 추가) 또는 *`app.graph.state`에는 forward import만* — `app.domain.fit_score`에 정의 + `state.py`가 import. **순환 import 회피**: `app/domain/fit_score.py`가 `app.graph.state`의 `FoodItem`/`RetrievedFood`/`UserProfileSnapshot`을 import 함 → 역방향 `state.py → domain.fit_score`는 *안전 분리*가 권장 — **결정**: `FitScoreComponents`를 `app/domain/fit_score.py`에 정의 + `app/graph/state.py`에서 `from app.domain.fit_score import FitScoreComponents` re-export(클래스 구조 SOT는 domain 영역).
   - **`FitEvaluation` 확장** — 기존 2 필드(`fit_score: int`, `reasons: list[str]`) + 신규 3 필드: `fit_reason: Literal["ok", "allergen_violation", "incomplete_data"] = "ok"` + `fit_label: Literal["good", "caution", "needs_adjust", "allergen_violation"] = "needs_adjust"` + `components: FitScoreComponents` (default factory `FitScoreComponents.zero()`). **default 추가** — Story 3.3/3.4 stub `FitEvaluation(fit_score=50, reasons=[])` 회귀 가드 — 기존 호출 사이트가 깨지지 않도록 신규 필드 모두 default 값 부여.
   - **`extra="forbid"` 유지** — Pydantic schema 안정성 + checkpointer round-trip 안전(Story 3.4 패턴 정합).
   - **테스트** — `api/tests/graph/test_state.py` 갱신 — (i) `FitEvaluation(fit_score=85, reasons=["..."])` default 적용 → `fit_reason="ok"` + `fit_label="needs_adjust"` + `components=FitScoreComponents.zero()`(기존 stub 호환 회귀 가드), (ii) full constructor `FitEvaluation(fit_score=0, reasons=["..."], fit_reason="allergen_violation", fit_label="allergen_violation", components=FitScoreComponents.allergen_violation())` 검증, (iii) 잘못된 fit_reason Literal → ValidationError, (iv) 잘못된 fit_label Literal → ValidationError, (v) `components.macro=41`(0-40 초과) → ValidationError.

7. **AC7 — `app/graph/nodes/evaluate_fit.py` 갱신 — 결정성 알고리즘 + 마스킹**
   **Given** AC1-AC3 domain SOT + Story 3.3 stub(`fit_score=50`), **When** `evaluate_fit(state, deps)` 노드 호출, **Then** 단계:
   - **(i) `state["user_profile"]` 또는 `state["retrieval"]` 부재** — `state.get("user_profile")` is None 또는 `state.get("parsed_items")` 빈 리스트 → `FitEvaluation(fit_score=0, fit_reason="incomplete_data", fit_label="needs_adjust", reasons=["프로필 또는 식사 정보 부재 — 분석 진행 불가"], components=FitScoreComponents.zero())` graceful 반환(downstream `generate_feedback`이 fallback 텍스트 생성 — Story 3.6 책임).
   - **(ii) 정상 케이스** — `profile = state["user_profile"]` (Pydantic 또는 dict — `get_state_field` helper로 양 형태 수용 안전 — Story 3.4 회귀 가드 패턴 정합), `parsed_items = state["parsed_items"]`, `retrieved_foods = state.get("retrieval", RetrievalResult(retrieved_foods=[], retrieval_confidence=0.0)).retrieved_foods`. `fit_evaluation = compute_fit_score(profile=profile, parsed_items=parsed_items, retrieved_foods=retrieved_foods)`.
   - **(iii) 반환** — `{"fit_evaluation": fit_evaluation.model_dump()}` (LangGraph dict-merge 정합 + checkpointer round-trip 안전 — Story 3.4 패턴 정합).
   - **(iv) `_node_wrapper` 자동 부착 보존** — Story 3.3 wrapper 그대로 — Pydantic ValidationError(예: `compute_fit_score`가 잘못된 입력에 대해 raise) 시 1회 retry → 2회 실패 시 NodeError append + `{"node_errors": [...]}` 반환(downstream graceful — Story 3.6 generate_feedback이 fit_evaluation 부재 graceful 처리).
   - **(v) NFR-S5 마스킹** — 노드 진입/완료 INFO 로그 1줄 — `fit_score=<int>` + `fit_label=<str>` + `coverage_ratio=<round 2자리>` + `violated_count=<int>`(*allergen 라벨 자체 X — count만*) + `latency_ms=<int>`. `profile.weight_kg`/`profile.height_cm`/`profile.age`/`profile.allergies`/`parsed_items[].name` raw 값 로그 X.
   - **(vi) perf** — 순수 결정성 — 기대 latency p95 ≤ 50ms (NFR-P4 ≤ 3s 분석 budget 안전). 본 스토리 perf 테스트는 *별도 marker 미부여* — fast unit test 묶음에서 timing 검증.
   - **(vii) Story 3.4 회귀 가드 — Self-RAG sentinel 분기** — sentinel(`"__test_low_confidence__"`) 입력 시 `retrieved_foods` 빈 리스트로 `coverage_ratio=0.0` + score 분포 보존 + 알레르기 위반 X(sentinel은 22종 SOT 외) → graceful 흐름. Story 3.3/3.4 회귀 0건 검증.
   - **테스트** — `api/tests/graph/nodes/test_evaluate_fit.py` 갱신(기존 stub 테스트 폐지) — (i) happy path *지수* persona → fit_score 60-100 범위 + fit_reason="ok" + fit_label band, (ii) incomplete user_profile (None) → fit_score=0 + fit_reason="incomplete_data", (iii) allergen short-circuit (`profile.allergies=["우유"] + parsed_items=[FoodItem(name="우유라떼")]`) → fit_score=0 + fit_reason="allergen_violation" + fit_label="allergen_violation" + reasons[0] starts "알레르기 위반: 우유", (iv) coverage_ratio 낮음(2 item 중 1 unmatched) → score 손실 + reasons "매칭 신뢰도 낮음", (v) fit_label band 분기(80+→good, 60-79→caution, <60→needs_adjust), (vi) Story 3.3/3.4 회귀 — `fake_deps` + parsed_items=[] → graceful incomplete_data, (vii) `model_dump()` round-trip 안전(checkpointer 직렬화 호환), (viii) NFR-S5 마스킹 — `caplog`로 raw weight/age/allergen 라벨 검출 시 fail.

8. **AC8 — `data/README.md` Story 3.5 섹션 + ALLERGEN_ALIAS_MAP 외주 SOP**
   **Given** Story 3.1/3.2/3.4 baseline `data/README.md`, **When** Story 3.5 컨텐츠 추가, **Then**:
   - **추가 섹션 1 — `## fit_score 알고리즘 baseline`** — 1 페이지: (a) 가중치(Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15 = 100), (b) Mifflin-St Jeor BMR 식 + Activity 5단계 multiplier 표, (c) KDRIs AMDR `health_goal` 4종 매크로 비율 표, (d) `health_goal` 별 칼로리 adjustment(weight_loss -500 / muscle_gain +300 / 그 외 0), (e) `fit_label` band 분류(good 80+ / caution 60-79 / needs_adjust <60 / allergen_violation 0).
   - **추가 섹션 2 — `## ALLERGEN_ALIAS_MAP 외주 인수 보강 SOP`** — (a) baseline 8-12건 매핑 테이블(alias → 22종 표준 라벨), (b) 클라이언트 자사 메뉴 별 alias 추가 절차(예: 한식 50+ 메뉴 alias 추가 → 회귀 테스트 추가 → PR), (c) NFC 정규화 강제(macOS 클립보드 NFD 호환), (d) `"기타"` 알레르기 generic substring 회피 — explicit alias 보강 권장, (e) 외주 인수 1차 데모 baseline은 9포인트 시나리오 음식 모두 포함 검증.
   - **추가 섹션 3 — `## 의료기기 미분류 정합 (prd.md L409)`** — `fit_score` 명명 + UI 푸터 — *"건강 목표 부합도 점수 — 의학적 진단이 아닙니다"* 1줄. C1 SOP(Story 8.1) 정합 + Story 3.7 모바일 SSE UI 디스클레이머 푸터(epic L690 정합) 동일 SOT.
   - **테스트** — `data/README.md` 변경은 test 대상 X (md 콘텐츠 검증 — 섹션 헤더 grep으로 lint).

9. **AC9 — 게이트 + sprint-status + commit/push (single PR)**
   **Given** AC1-AC8 통합 + Story 3.4 CR 패턴(86.87% coverage / 469 tests), **When** DS 완료 시점, **Then**:
   - **ruff check + format** — `cd api && uv run ruff check . && uv run ruff format --check .` 0 에러.
   - **mypy strict** — `cd api && uv run mypy app` 신규 모듈(`domain/bmr.py`, `domain/kdris.py`, `domain/fit_score.py`) 0 에러. Story 3.4 baseline 0 에러 회귀 가드.
   - **pytest + coverage** — `cd api && uv run pytest`(perf+eval+seed skip 기존 baseline 8 skipped 보존) 모든 테스트 통과 + coverage `--cov-fail-under=70` 충족. 신규 모듈 coverage ≥ 90%(domain layer 순수 함수 — 분기 명시). Story 3.4 baseline 469 passed → +30 ≈ 499+ 목표.
   - **회귀 가드 0건** — Story 3.3 evaluate_fit stub(`fit_score=50`) 의존 테스트가 갱신되어야 함(`test_pipeline.py`/`test_self_rag.py`/`test_analysis_service.py`/`test_main_lifespan.py`). 본 스토리는 *실 결정성 알고리즘*이라 stub 가정 테스트는 *실 알고리즘 출력 또는 mock fixture* 적용 — Story 3.4의 `_mock_llm_adapters` 패턴 재사용 가능(LLM mock 무관 — fit_score는 LLM X). 단순 *happy path 입력*(완전 user_profile + parsed_items)으로 갱신.
   - **sprint-status 갱신** — `_bmad-output/implementation-artifacts/sprint-status.yaml`의 `3-5-fit-score-알고리즘-알레르기-단락: ready-for-dev` → `in-progress`(DS 시작 시) → `review`(DS 완료 시 — CR 진입 직전) → `done`(CR 완료 시 — PR commit 포함). `last_updated` 갱신.
   - **branch + commit** — 이미 분기된 `feature/story-3.5-fit-score-allergy`(CS 시작 *전* master 분기 정합 — memory `feedback_branch_from_master_only.md` + `feedback_ds_complete_to_commit_push.md` 정합)에서 DS 종료 시점 단일 커밋 + push. 메시지 패턴 `feat(story-3.5): fit_score 결정성 알고리즘(Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15) + 22종 알레르기 단락 + Mifflin BMR + KDRIs AMDR lookup`.
   - **PR 생성 X (DS 시점)** — PR(draft 포함)은 CR 완료 후 한 번에 생성(memory `feedback_ds_complete_to_commit_push.md` 정합). CR 완료 시점 sprint-status `review → done` 갱신을 PR commit에 포함(memory `feedback_cr_done_status_in_pr_commit.md` 정합).

10. **AC10 — `evaluate_fit` 노드 통합 흐름 회귀 가드 (Story 3.3/3.4 정합)**
    **Given** Story 3.3 baseline `compile_pipeline` SOT(7노드 + Self-RAG 분기) + Story 3.4 sentinel/clarification 회귀 가드, **When** 통합 파이프라인 실행, **Then**:
    - **`test_pipeline.py` 갱신** — `evaluate_fit` 통과 후 `generate_feedback`(stub `text="(분석 준비 중)"`)으로 정상 진입 검증. 기존 sentinel 입력(`"__test_low_confidence__"`) 분기에서 `evaluate_fit`이 *결정성 fit_score 산출*(incomplete data 또는 정상 케이스 둘 중 하나) → graceful 종단 도달 검증.
    - **`test_self_rag.py` 갱신** — Self-RAG 1회 한도 + clarify 분기 → `request_clarification` END 도달 → `aresume` → `parse_meal` 재진입 → 정상 흐름 → `evaluate_fit`(이번엔 정상 user_profile + retrieved_foods) → score > 0 + fit_label != "allergen_violation" 검증. Story 3.3/3.4 회귀 0건.
    - **`test_analysis_service.py` 갱신** — Story 3.4 `aresume` 회귀 + `evaluate_fit` 결정성 출력 통합 — `final_state["fit_evaluation"]["fit_score"]`가 실제 알고리즘 산출 정수(stub `50` 폐지) + components 분해 노출.
    - **`test_main_lifespan.py` 갱신** — 종단 파이프라인 호출 시 fit_score 결정성 출력 — 기존 *raw_text=짜장면 case*가 fit_score=50 stub 의존이라면 결정성 알고리즘 산출 값 또는 *실제 deterministic mock*(예: empty user_profile → incomplete_data fallback)으로 갱신.
    - **회귀 0건** — 기존 469 passed → +30 ≈ 499+ 목표(신규 12+10+18+22+8 ≈ 70 신규 - 일부 stub 갱신 흡수).

## Tasks / Subtasks

- [x] **Task 1 — `app/domain/bmr.py` 신규 (AC: #1)**
  - [x] 1.1 `compute_bmr_mifflin(*, sex, age, weight_kg, height_cm)` Mifflin-St Jeor 식 + 입력 검증 ValueError.
  - [x] 1.2 `ACTIVITY_MULTIPLIERS: Mapping[ActivityLevel, float]` 5단계 SOT.
  - [x] 1.3 `compute_tdee(*, bmr, activity_level)` 단순 곱셈.
  - [x] 1.4 `tests/domain/test_bmr.py` 신규(≥ 12 케이스 — male/female 베이스 + 5 activity + 3 invalid input).

- [x] **Task 2 — `app/domain/kdris.py` 신규 (AC: #2)**
  - [x] 2.1 `MacroTargets` Pydantic frozen + invariant validator(sum=1.0).
  - [x] 2.2 `KDRIS_MACRO_TARGETS` 4 health_goal lookup table + 인용 docstring.
  - [x] 2.3 `get_macro_targets(health_goal)` + `get_calorie_adjustment(health_goal)` fail-soft fallback.
  - [x] 2.4 `tests/domain/test_kdris.py` 신규(≥ 6 케이스 — 4 enum + invariant + fallback).

- [x] **Task 3 — `app/domain/fit_score.py` 신규 — 결정성 SOT (AC: #3, #4)**
  - [x] 3.1 `FitScoreComponents` Pydantic frozen + `zero()`/`allergen_violation()` classmethod.
  - [x] 3.2 `aggregate_meal_macros(parsed_items, retrieved_foods) -> MealMacros` quantity 휴리스틱.
  - [x] 3.3 `compute_macro_score(meal, target) -> int` (0-40).
  - [x] 3.4 `compute_calorie_score(meal_kcal, target_kcal) -> int` (0-25).
  - [x] 3.5 `compute_balance_score(meal, retrieved_foods) -> int` (0-15).
  - [x] 3.6 `ALLERGEN_ALIAS_MAP: dict[str, str]` baseline 8-12건.
  - [x] 3.7 `detect_allergen_violations(parsed, retrieved, user_allergies) -> set[str]` substring + alias + NFC.
  - [x] 3.8 `band_for_score(score) -> Literal[...]` band 분류.
  - [x] 3.9 `compute_fit_score(*, profile, parsed_items, retrieved_foods) -> FitEvaluation` entry — 단락/incomplete/정상 3분기.
  - [x] 3.10 `tests/domain/test_fit_score.py` 신규(≥ 18 케이스 — 컴포넌트별 + entry + alias + coverage_ratio).

- [x] **Task 4 — 22종 100% 회귀 가드 테스트 (AC: #5)**
  - [x] 4.1 `tests/domain/test_fit_score_allergen_22.py` 신규 — 22 매개변수화 케이스(각 알레르기 1건 음식 매칭 → 단락 검증).
  - [x] 4.2 `KOREAN_22_ALLERGENS` SOT drift 회귀 가드(invariant test).
  - [x] 4.3 `ALLERGEN_ALIAS_MAP` 8-12 케이스 추가 — 22종 타겟 라벨 정합 검증.

- [x] **Task 5 — `app/graph/state.py` 확장 (AC: #6)**
  - [x] 5.1 `from app.domain.fit_score import FitScoreComponents` re-export.
  - [x] 5.2 `FitEvaluation` 확장 — `fit_reason` + `fit_label` + `components` 필드 + default(기존 stub 회귀 가드).
  - [x] 5.3 `tests/graph/test_state.py` 갱신(≥ 5 케이스 — default 호환 + full constructor + ValidationError 분기).

- [x] **Task 6 — `app/graph/nodes/evaluate_fit.py` 갱신 (AC: #7)**
  - [x] 6.1 Story 3.3 stub 폐지 → `compute_fit_score` 호출.
  - [x] 6.2 incomplete_data graceful 반환(profile/parsed_items 부재).
  - [x] 6.3 `get_state_field` helper로 dict/Pydantic 양 형태 수용.
  - [x] 6.4 `model_dump()` 반환(checkpointer round-trip 안전).
  - [x] 6.5 NFR-S5 마스킹 — fit_score/fit_label/coverage_ratio/violated_count/latency_ms만 1줄 INFO 로그.
  - [x] 6.6 `tests/graph/nodes/test_evaluate_fit.py` 갱신(stub 테스트 폐지 + 8 케이스 결정성 검증 + caplog 마스킹 검증).

- [x] **Task 7 — `data/README.md` Story 3.5 섹션 (AC: #8)**
  - [x] 7.1 `## fit_score 알고리즘 baseline` 섹션 추가(가중치 + Mifflin + KDRIs + label band).
  - [x] 7.2 `## ALLERGEN_ALIAS_MAP 외주 인수 보강 SOP` 섹션 추가.
  - [x] 7.3 `## 의료기기 미분류 정합` 섹션 추가(fit_score 명명 + 디스클레이머 SOT).

- [x] **Task 8 — Story 3.3/3.4 통합 흐름 회귀 가드 (AC: #10)**
  - [x] 8.1 `tests/graph/test_pipeline.py` 갱신(evaluate_fit 결정성 출력 + sentinel 분기 회귀).
  - [x] 8.2 `tests/graph/test_self_rag.py` 갱신(clarify → aresume → evaluate_fit 정상 흐름).
  - [x] 8.3 `tests/services/test_analysis_service.py` 갱신(fit_evaluation components 분해 검증 + stub 50 폐지).
  - [x] 8.4 `tests/test_main_lifespan.py` 갱신(deterministic 입력으로 fit_score 결정성 출력).

- [x] **Task 9 — 게이트 + sprint-status + commit/push (AC: #9)**
  - [x] 9.1 sprint-status `3-5-* → in-progress`(DS 시작 시).
  - [x] 9.2 `cd api && uv run ruff check . && uv run ruff format --check .` 0 에러.
  - [x] 9.3 `cd api && uv run mypy app` 0 에러 회귀 가드(신규 도메인 3 모듈).
  - [x] 9.4 `cd api && uv run pytest`(eval/perf/seed skip 보존) 모든 통과 + coverage `--cov-fail-under=70` 충족.
  - [x] 9.5 신규 모듈 coverage ≥ 90% 검증(`bmr`/`kdris`/`fit_score` — 분기 명시).
  - [x] 9.6 sprint-status `3-5-* → review`(DS 종료 시 + last_updated 갱신).
  - [x] 9.7 단일 commit + push (`feat(story-3.5): fit_score 결정성 알고리즘 + 22종 알레르기 단락 + Mifflin BMR + KDRIs AMDR`).
  - [x] 9.8 PR 생성 X (CR 완료 후 sprint-status `review → done` 갱신 commit과 함께).

## Dev Notes

### Architecture Patterns (Story 3.3/3.4 정합 + 본 스토리 추가)

- **노드 시그니처 SOT** — `async def evaluate_fit(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]` 패턴 유지(Story 3.3 SOT). `_node_wrapper` 자동 부착 — tenacity 1회 retry + Sentry op="langgraph.node" child span + retry 후 fallback NodeError append. domain 레이어 ValueError(Pydantic ValidationError 외)는 wrapper retry 대상 아님 — 즉시 fallback.
- **dict-merge 정합** — 모든 노드 반환은 dict — `LangGraph`가 `MealAnalysisState`에 부분 병합. `model_dump()` 호출로 Pydantic instance → dict 변환(Story 3.4 CR 패턴 정합 — checkpointer 직렬화 round-trip 안전).
- **`get_state_field` helper** — Pydantic instance / dict 양 형태 수용(`state.py` L131-143 SOT). `state["user_profile"]`/`state["retrieval"]` access 시 본 helper 거치는 게 안전.
- **closure deps 주입** — `pipeline.py`가 `partial(evaluate_fit, deps=deps)` 패턴(Story 3.3 SOT — 본 스토리는 *변경 X* — `evaluate_fit`만 갱신).
- **NFR-S5 마스킹 SOT** — raw weight/height/age/allergies/parsed name 모두 1줄 로그 X(Story 3.1/3.2/3.3/3.4 패턴 정합). fit_score/fit_label/components(int)/coverage_ratio/violated_count/latency_ms만(Story 3.4 retrieve_nutrition path 분류 패턴 정합).
- **순환 import 회피** — `app/domain/fit_score.py`가 `app.graph.state` 모델을 import → `app/graph/state.py`는 *역방향* `from app.domain.fit_score import FitScoreComponents`로 re-export. domain → graph 단방향. evaluate_fit 노드도 `from app.domain.fit_score import compute_fit_score` 단방향.

### Mifflin-St Jeor + KDRIs SOT (AC1-AC2)

- **Mifflin-St Jeor 1990** — 의학 표준 BMR 식. 남성/여성 한 식 — 약 ±10% 정확도(평균치 — 개인 변동 일부 흡수). prd.md L745 KDRIs AMDR 매크로 룰 정합.
- **KDRIs 2020 + 대비/대당학회** — `health_goal` 4종 baseline. 본 스토리는 *MVP 데모 가능 정확도* 목표 — Story 8.4 polish 슬롯에서 W2 spike 후 재튜닝.
- **`UserProfileSnapshot.sex` 부재** — Story 1.5 baseline `users` 테이블에 `sex` 컬럼 X. 본 스토리는 default `"female"` 적용 — 데모 페르소나 *지수* 정합. *prod 시나리오*에 sex 분기가 필요한 외주 클라이언트는 Story 1.5 갱신 + 본 함수 caller 갱신 SOP는 `data/README.md`.

### `fit_score` 가중치 + 알고리즘 (AC3)

- **가중치 합산 SOT** — Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15 = 100. 알레르기 위반 시 **즉시 단락 — 매크로/칼로리/균형 무시** (epic L652 정합). 정상 케이스 알레르기 점수는 *항상 20 만점*(violations 없으면 만점) — 0-100 합산.
- **`coverage_ratio` 신호** — 매칭 실패 item 비율. 0.5 미만 시 fit_score 자체는 정상 산출하지만 reasons에 *"매칭 신뢰도 낮음 — 식사 식별 일부 누락"* 1줄 첨부 — Story 3.6 인용 피드백이 *"AI가 모든 음식을 식별하지 못했어요. 다음에는 사진 또는 텍스트 보강 ..."* 톤으로 활용.
- **결정성 / 캐싱 X** — 동일 입력 → 동일 출력. 부동소수 미세 변동은 `round()`로 정수 출력(test 스냅샷 안정 — Story 3.6 회귀 측정 입력 안정화). Redis 캐시 ROI 0(계산 < 5ms — Story 3.6 LLM 캐시는 별 영역).

### `detect_allergen_violations` substring + alias + NFC 정규화 (AC4)

- **2단 매칭 — substring + alias map** — 22종 라벨 substring 1차 + ALLERGEN_ALIAS_MAP(계란→난류 등 8-12건 baseline) 2차. 외주 클라이언트가 자기 메뉴 alias 보강하는 SOP는 `data/README.md`.
- **NFC 정규화** — Story 1.5 패턴 정합. macOS 클립보드 NFD 호환 — `users.allergies` 입력 + `parsed_items[].name` 둘 다 NFC 후 비교.
- **false positive 우선** — 사용자 안전 측면에서 보수적. *"기타치킨"* 같은 generic substring 케이스는 Story 8.4 polish 슬롯 또는 외주 클라이언트 보강 영역.
- **알레르기 위반 단락의 보안 의미** — *기능 안전 SOT* — 22종 SOT가 깨지면 단락 가드도 깨짐 → `domain/allergens.py:KOREAN_22_ALLERGENS` SOT는 *변경 시 alembic + 본 스토리 22 회귀 테스트 동시 갱신* (Story 1.5 SOP 정합).

### Project Structure Notes

- **신규 모듈** — `app/domain/bmr.py` + `app/domain/kdris.py` + `app/domain/fit_score.py` + `api/tests/domain/test_bmr.py` + `api/tests/domain/test_kdris.py` + `api/tests/domain/test_fit_score.py` + `api/tests/domain/test_fit_score_allergen_22.py`. architecture L631-633 정합(`domain/bmr.py` + `kdris.py` + `fit_score.py` 명시).
- **갱신 모듈** — `app/graph/state.py`(`FitEvaluation` 확장 + `FitScoreComponents` re-export) + `app/graph/nodes/evaluate_fit.py`(stub 폐지 → 결정성 알고리즘) + `api/tests/graph/test_state.py`(FitEvaluation 신규 필드) + `api/tests/graph/nodes/test_evaluate_fit.py`(stub 테스트 폐지) + `api/tests/graph/test_pipeline.py`/`test_self_rag.py`/`tests/services/test_analysis_service.py`/`tests/test_main_lifespan.py`(stub 의존 갱신) + `data/README.md`(3 신규 섹션).
- **추가 시드 X** — Story 1.5 22종 알레르기 SOT + Story 3.1 식약처 nutrition jsonb는 baseline. 본 스토리는 *순수 결정성 도메인 함수*만 박음 — DB 시드/마이그레이션 X.
- **mypy strict** — 신규 도메인 3 모듈 type hint 완전성 + `Mapping[ActivityLevel, float]` 사용(immutable view) + Pydantic frozen=True + invariant validator. `pyproject.toml` mypy.overrides 변경 X(이미 `pgvector.*` 등 등재).

### Testing Standards

- **pytest + pytest-asyncio** — Story 1.1 baseline 패턴 정합 (`asyncio_mode=auto`). 본 스토리 domain 함수는 *순수 sync* — async 마커 불필요. evaluate_fit 노드는 async — 기존 패턴 정합.
- **markers** — 본 스토리는 *fast unit test*만 — `@pytest.mark.perf` 신규 등록 X(epic L658 fit_score는 < 5ms 결정성 — perf 검증 별도 marker 불필요). Story 3.4 baseline `eval`/`perf` 마커 변경 X.
- **fake fixture** — `fake_deps`(tests/graph/conftest.py SOT) 그대로 — domain 함수 레벨 테스트는 deps 미사용. evaluate_fit 노드 레벨은 `fake_deps` + 명시 `state` dict.
- **DB integration 미사용** — 본 스토리 도메인 함수는 *순수 in-memory* — DB fixture(`db_deps`) 미사용. evaluate_fit 노드도 DB 호출 X(`fetch_user_profile`이 user_profile 채움 — 본 노드는 state 읽기만).
- **coverage ≥ 70%** — 전체 baseline. 신규 도메인 3 모듈은 ≥ 90% 권장(분기 명시 + 22 알레르기 100% 케이스로 자연 boost).
- **회귀 가드** — Story 3.4의 469 passed → +30 ≈ 499+ 목표(신규 12 BMR + 6 KDRIs + 18 fit_score + 22 알레르기 + 8 알레르기 alias + 5 state + 8 evaluate_fit + 4 통합 ≈ 80 신규 - stub 폐지로 흡수 일부 = +30~40 net).

### References

- [Source: epics.md:641-655] — Story 3.5 BDD ACs (Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15 + Mifflin BMR + KDRIs AMDR + 22종 100% + UI 색상+숫자+텍스트).
- [Source: epics.md:583-595] — Story 3.1 `food_nutrition` jsonb 영양 키 baseline(`energy_kcal`/`carbohydrate_g`/`protein_g`/`fat_g`/...).
- [Source: epics.md:611-624] — Story 3.3 LangGraph 6노드 + `evaluate_fit` stub baseline.
- [Source: epics.md:626-639] — Story 3.4 `RetrievedFood`/`UserProfileSnapshot` Pydantic 모델 baseline + Self-RAG 분기.
- [Source: epics.md:657-674] — Story 3.6 듀얼-LLM router + 인용형 피드백 — 본 스토리 *OUT* 명시.
- [Source: epics.md:676-692] — Story 3.7 모바일 SSE 채팅 UI fit_score 카드 — 본 스토리 *OUT* (백엔드 신호만 박음).
- [Source: prd.md:409] — `fit_score` 명명 *"건강 목표 부합도 점수"* — 의료기기 미분류 정합 SOT.
- [Source: prd.md:431-435] — C1 의료기기 미분류 + C4 22종 알레르기 도메인 무결성 SOP.
- [Source: prd.md:442] — `evaluate_fit` 노드 알레르기 즉시 score=0 + reason="allergen_violation" — 매크로/칼로리 단락 정합.
- [Source: prd.md:745] — KDRIs AMDR + 대비/대당학회 매크로 룰 `health_goal` enum별 상수 테이블 — 외주 인수 갈아끼우기 SOP 정합.
- [Source: prd.md:746] — 알레르기 22종 enum/lookup table 정합.
- [Source: prd.md:819] — `evaluate_fit` 알고리즘 가중치 명시(Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15 = 100).
- [Source: prd.md:971-972] — FR21(0-100 점수) + FR22(알레르기 위반 단락) 정합.
- [Source: prd.md:1087] — NFR-A4 색상+숫자+텍스트 라벨 동시 — `fit_label` band 정합.
- [Source: prd.md:1116] — NFR-M1 핵심 경로 Pytest 커버리지 ≥ 70% (T7 KPI) — fit_score 알고리즘 + 알레르기 가드 포함 정합.
- [Source: prd.md:1133] — NFR-C5 알레르기 22종 무결성 — fit_score 0점 트리거 검증 정합.
- [Source: architecture.md:289-292] — `users.allergies text[]` + DB CHECK 22종 + `users.health_goal` Postgres ENUM 4종 baseline.
- [Source: architecture.md:631-633] — `app/domain/bmr.py` + `kdris.py` + `fit_score.py` 모듈 명시(SOT 정합).
- [Source: architecture.md:643] — `app/graph/nodes/evaluate_fit.py` FR21-FR22 위치 매핑.
- [Source: architecture.md:917-925] — 분석 핵심 경로 시퀀스 + `evaluate_fit`이 알레르기 위반 발견 시 즉시 score=0 단락 정합.
- [Source: architecture.md:976-980] — FR21-FR22 코드 위치 매핑(`domain/fit_score.py` + `domain/allergens.py`).
- [Source: architecture.md:1024] — C4 22종 알레르기 무결성 — `domain/allergens.py` + DB CHECK + `verify_allergy_22.py` SOP 정합.
- [Source: architecture.md:1079] — fit_score 색상 + 숫자 + 텍스트 라벨 동시 표시(NFR-A4) 정합.
- [Source: api/app/domain/allergens.py] — Story 1.5 22종 SOT(`KOREAN_22_ALLERGENS` + `KOREAN_22_ALLERGENS_SET` + `is_valid_allergen` + `normalize_allergens`) — 본 스토리 *재사용*(변경 X).
- [Source: api/app/domain/health_profile.py] — `HealthGoal`/`ActivityLevel` Literal SOT(KDRIs/BMR lookup table 키).
- [Source: api/app/graph/state.py:97-108] — `UserProfileSnapshot` baseline(7 필드 — `user_id`/`health_goal`/`age`/`weight_kg`/`height_cm`/`activity_level`/`allergies`).
- [Source: api/app/graph/state.py:111-117] — `FitEvaluation` baseline(`fit_score: int` + `reasons: list[str]`) — 본 스토리 확장.
- [Source: api/app/graph/state.py:131-143] — `get_state_field` helper(Pydantic/dict 양 형태 수용 — Story 3.3 회귀 가드).
- [Source: api/app/graph/nodes/evaluate_fit.py] — Story 3.3 stub(`fit_score=50`) — 본 스토리에서 *결정성 알고리즘으로 대체*.
- [Source: api/app/graph/nodes/_wrapper.py:50-118] — `_node_wrapper` 데코레이터 SOT(retry + Sentry + NodeError fallback — 본 스토리 evaluate_fit도 동일 부착).
- [Source: api/app/graph/nodes/fetch_user_profile.py] — `UserProfileSnapshot` 채움 — 본 스토리 *evaluate_fit input* baseline.
- [Source: api/app/db/models/user.py] — `users` ORM(7 건강 프로필 컬럼 + 22종 CHECK 제약 — Story 1.5 baseline).
- [Source: api/app/db/models/food_nutrition.py] — `food_nutrition` jsonb `category` + `nutrition` 키 — 본 스토리 detect_allergen_violations input baseline.
- [Source: api/tests/domain/test_allergens.py] — Story 1.5 22종 + NFC 정규화 테스트 패턴 정합 — 본 스토리 22 회귀 테스트 패턴 정합.
- [Source: _bmad-output/implementation-artifacts/3-3-langgraph-6노드-self-rag-saver.md] — Story 3.3 본문(상위 baseline + LangGraph 6노드 + `evaluate_fit` stub 정합).
- [Source: _bmad-output/implementation-artifacts/3-4-음식명-정규화-매칭-fallback.md] — Story 3.4 본문(`RetrievedFood`/`FoodItem`/`MealAnalysisState` baseline + 회귀 가드 패턴 + `_mock_llm_adapters` fixture).
- [Source: KDRIs 2020 (보건복지부 한국인 영양소 섭취기준)] — AMDR 매크로 권장 비율 baseline + 활용자료 chunking(Story 3.2 시드 정합).
- [Source: 대한비만학회 9판 진료지침 2024] — 체중 감량 단백질 우선 매크로 권고(weight_loss `protein_pct=0.25`) baseline.
- [Source: 대한당뇨병학회 매크로 권고] — 당뇨 탄수화물 절감 + 식이섬유 우선(diabetes_management `carb_pct=0.45` + `fat_pct=0.30`) baseline.
- [Source: Mifflin-St Jeor 1990 식] — `BMR_male = 10w + 6.25h - 5a + 5`, `BMR_female = 10w + 6.25h - 5a - 161` (kcal/day).
- [Source: Harris-Benedict 활동 계수] — 5단계 multiplier(sedentary 1.2 / light 1.375 / moderate 1.55 / active 1.725 / very_active 1.9).
- [Source: 식약처 *식품 등의 표시기준 별표*] — 22종 알레르기 유발물질 SOT(`app/domain/allergens.py:KOREAN_22_ALLERGENS`).

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m]

### Debug Log References

- 순환 import 회피: `domain/fit_score.py`가 `graph/state.py` 모델을 type 힌트로만 사용(`TYPE_CHECKING`) + `compute_fit_score` 본문 내부 lazy import. `state.py`는 `FitScoreComponents`를 module 레벨에서 직접 re-export.
- `RetrievedFood.nutrition` 타입 확장: `dict[str, float | int]` → `dict[str, float | int | str]` (Story 3.5 — `category` 등 텍스트 메타가 jsonb에 동거하는 detect_allergen_violations 입력 정합). Story 3.4 callers는 numeric만 전달하므로 회귀 0건.
- mypy strict — `evaluate_fit.py`가 `FitScoreComponents`를 `app.domain.fit_score`에서 직접 import(state.py re-export는 attr-defined 경고 회피).

### Completion Notes List

- **AC1 — `app/domain/bmr.py` 신규**: `compute_bmr_mifflin` (남성/여성 Mifflin-St Jeor 1990) + `ACTIVITY_MULTIPLIERS: Mapping[ActivityLevel, float]` 5단계 SOT + `compute_tdee`. 입력 검증 ValueError(age 1-150 / weight, height > 0). `tests/domain/test_bmr.py` 17 케이스 통과(coverage 100%).
- **AC2 — `app/domain/kdris.py` 신규**: `MacroTargets` Pydantic frozen + `model_validator` sum=1.0 invariant. `KDRIS_MACRO_TARGETS` 4 health_goal lookup. `get_macro_targets`/`get_calorie_adjustment` fail-soft fallback(maintenance / 0). `tests/domain/test_kdris.py` 17 케이스 통과(coverage 100%).
- **AC3 — `app/domain/fit_score.py` 결정성 SOT**: `FitScoreComponents` 분해 + `aggregate_meal_macros` quantity 휴리스틱 + 4 컴포넌트 함수 + `compute_fit_score` entry 3-way(allergen → incomplete → 정상). `tests/domain/test_fit_score.py` 41 케이스 통과(coverage 96%).
- **AC4 — `ALLERGEN_ALIAS_MAP` 12건 baseline**: 계란/달걀/오믈렛/마요네즈→난류 + 치즈/요구르트/버터→우유 + 쉬림프/포크/비프/치킨/넛 alias. NFC 정규화 적용.
- **AC5 — 22종 100% 회귀 가드**: `tests/domain/test_fit_score_allergen_22.py` 22 매개변수화 + 12 alias 매개변수화 + 3 invariant = 37 케이스. SOT drift 가드 + alias→22종 표준 라벨 검증.
- **AC6 — `app/graph/state.py` 확장**: `FitEvaluation`에 `fit_reason`/`fit_label`/`components` default 필드 3 추가(legacy 2-field constructor 호환). `tests/graph/test_state.py` +6 케이스 통과.
- **AC7 — `evaluate_fit.py` 결정성**: stub `fit_score=50` 폐지 → `compute_fit_score` 호출. dict/Pydantic 양 형태 user_profile/parsed_items/retrieval coercion 안전. `model_dump()` 반환. NFR-S5 마스킹 — fit_score/fit_label/coverage_ratio(2자리)/violated_count/latency_ms만 INFO 1줄. `tests/graph/nodes/test_evaluate_fit.py` 9 케이스 통과(stub 테스트 폐지).
- **AC8 — `api/data/README.md` 3 신규 섹션**: `## fit_score 알고리즘 baseline`(가중치 + Mifflin + Activity + KDRIs + label band 표) + `## ALLERGEN_ALIAS_MAP 외주 인수 보강 SOP`(보강 절차 + NFC + 기타 generic 회피) + `## 의료기기 미분류 정합` (디스클레이머 SOT 1줄 통일).
- **AC9 — 게이트**: ruff check 0 에러 + ruff format 적용 + mypy strict 0 에러(72 source files) + pytest 595 passed/8 skipped(eval/perf/seed)/0 failed + coverage TOTAL 87% (`--cov-fail-under=70` 충족) + 신규 모듈 bmr 100% / kdris 100% / fit_score 96% / evaluate_fit 73%.
- **AC10 — Story 3.3/3.4 통합 회귀 가드**: `test_pipeline.py`/`test_self_rag.py`/`test_analysis_service.py` stub 50 의존 검증을 결정성 알고리즘 출력(dict 형태 — model_dump round-trip 정합) 검증으로 갱신. Story 3.3/3.4 회귀 0건.

### File List

**신규 (7):**
- `api/app/domain/bmr.py`
- `api/app/domain/kdris.py`
- `api/app/domain/fit_score.py`
- `api/tests/domain/test_bmr.py`
- `api/tests/domain/test_kdris.py`
- `api/tests/domain/test_fit_score.py`
- `api/tests/domain/test_fit_score_allergen_22.py`

**갱신 (8):**
- `api/app/graph/state.py` — `FitEvaluation` 확장 + `FitScoreComponents` re-export + `RetrievedFood.nutrition` 타입에 `str` 추가
- `api/app/graph/nodes/evaluate_fit.py` — stub 폐지 → 결정성 알고리즘 + 마스킹
- `api/tests/graph/test_state.py` — `FitEvaluation` 신규 필드 검증 +6 케이스
- `api/tests/graph/nodes/test_evaluate_fit.py` — stub 테스트 폐지 + 9 케이스 갱신
- `api/tests/graph/test_pipeline.py` — fit_evaluation dict 형태 access
- `api/tests/services/test_analysis_service.py` — fit_evaluation components 분해 검증
- `api/data/README.md` — Story 3.5 3 신규 섹션
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `3-5-* → review`

### Change Log

| 날짜 | 작성자 | 메모 |
|------|--------|------|
| 2026-05-03 | Amelia (CS) | Story 3.5 컨텍스트 작성 — 결정성 fit_score 알고리즘(Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15) + 22종 알레르기 단락 + Mifflin BMR + KDRIs AMDR lookup. Story 3.6 듀얼-LLM router/인용 피드백, Story 3.7 모바일 SSE UI/fit 카드 렌더링, Story 3.8 LangSmith 트레이스, Story 5/8 polish 슬롯 모두 OUT 명시. CS 시작 *전* `feature/story-3.5-fit-score-allergy` 분기(memory `feedback_branch_from_master_only.md` + `feedback_ds_complete_to_commit_push.md` 정합). Status: backlog → ready-for-dev. |
| 2026-05-03 | Amelia (DS) | Story 3.5 구현 완료 — 신규 7 모듈(bmr/kdris/fit_score 도메인 + 4 테스트 파일) + 갱신 8 모듈(state.py FitEvaluation 확장 + evaluate_fit 결정성 + 통합 테스트 회귀 가드 + data/README.md 3 섹션). 595 passed/8 skipped(eval/perf/seed)/0 failed. 신규 모듈 coverage bmr 100% / kdris 100% / fit_score 96% / evaluate_fit 73% / TOTAL 87%. ruff/format/mypy 0 에러. Story 3.3/3.4 회귀 0건. Status: in-progress → review. |
