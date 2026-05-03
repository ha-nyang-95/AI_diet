"""LangGraph 분석 파이프라인 SOT state + 노드 IO Pydantic 모델 (Story 3.3 AC1).

설계:
- `MealAnalysisState`: TypedDict `total=False` — LangGraph가 노드별 *부분 dict 갱신*으로
  채우는 SOT 컨테이너. 런타임 검증 X(타입 hint만) — 노드 출력은 별 Pydantic 모델로
  fail-fast 검증(D7).
- 노드 IO 6세트: `ParseMealOutput`/`RetrievalResult`/`EvaluationDecision`/
  `UserProfileSnapshot`/`FitEvaluation`/`FeedbackOutput`. 각 노드 함수 내부에서
  `<Output>(**raw).model_dump()` round-trip — Pydantic ValidationError 발생 시 노드
  wrapper(`tenacity.retry`)가 1회 retry, 2회 실패는 `AnalysisStateValidationError`
  로 변환되어 NodeError append + 다음 노드 진행(FR45).
- enum 재사용: `HealthGoal`/`ActivityLevel`은 Story 1.5 `app.domain.health_profile`
  Literal SOT(중복 정의 금지 — DB ENUM과 wire drift 회피).
- 체크포인터 직렬화 일관성: LangGraph `JsonPlusSerializer`(default)는 Pydantic v2
  round-trip 보존하나, 안전성 정합으로 노드 간 access는 `get_state_field` helper로
  양 형태(Pydantic instance / dict) 모두 수용. 라우터/평가 노드의 attribute access
  가 dict 역직렬화 시 `AttributeError` 회귀 차단.
"""

from __future__ import annotations

import uuid
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.domain.fit_score import FitScoreComponents
from app.domain.health_profile import ActivityLevel, HealthGoal


class FoodItem(BaseModel):
    """`parse_meal` 노드 출력의 단일 음식 — Story 3.4가 실 LLM parse로 대체."""

    model_config = ConfigDict(extra="forbid")

    name: str
    quantity: str | None = None
    confidence: float = Field(ge=0, le=1)


class ParseMealOutput(BaseModel):
    """`parse_meal` 노드 *공식 출력* — 빈 list 허용(downstream은 빈 retrieval로 진행)."""

    model_config = ConfigDict(extra="forbid")

    parsed_items: list[FoodItem]


class RetrievedFood(BaseModel):
    """RAG top-k 결과 단일 음식 — Story 3.4가 실 alias lookup + HNSW로 채움.

    Story 3.5 — ``nutrition`` value 타입에 ``str`` 추가: ``category`` 등 텍스트 메타가
    jsonb에 동거(``detect_allergen_violations`` substring 매칭 입력).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    food_id: uuid.UUID | None = None
    score: float = Field(ge=0, le=1)
    nutrition: dict[str, float | int | str]


class RetrievalResult(BaseModel):
    """`retrieve_nutrition` 노드 *공식 출력* — top-1 score 또는 평균을 신뢰도로."""

    model_config = ConfigDict(extra="forbid")

    retrieved_foods: list[RetrievedFood]
    retrieval_confidence: float = Field(ge=0, le=1)


class EvaluationDecision(BaseModel):
    """`evaluate_retrieval_quality` 노드 *공식 출력* — Self-RAG 분기 라우팅 신호.

    Story 3.4 — `route` Literal 3-way 확장: `"clarify"` 추가. confidence 미달 +
    rewrite_attempts >= 1 시 재질문 분기(`request_clarification` 노드).
    """

    model_config = ConfigDict(extra="forbid")

    route: Literal["rewrite", "continue", "clarify"]
    reason: str


class ClarificationOption(BaseModel):
    """Story 3.4 — Self-RAG 재질문 옵션 (FR20 재질문 UX 백엔드 신호).

    `request_clarification` 노드가 1+개 채움. `aresume` 시 사용자가 선택한 옵션의
    `value`가 `parse_meal` 진입 `raw_text`로 주입(LLM parse + alias 1차 hit 가능성 ↑).

    - `label`: UI 노출 라벨 — 짧은 한국어(예: ``"연어 포케"``).
    - `value`: `aresume` 시 정제 텍스트(라벨 + 양 추정 — 예: ``"연어 포케 1인분"``).
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=50)
    value: str = Field(min_length=1, max_length=80)


class UserProfileSnapshot(BaseModel):
    """`fetch_user_profile` 노드 출력 — Story 1.5 enum 재활용."""

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    health_goal: HealthGoal
    age: int
    weight_kg: float
    height_cm: float
    activity_level: ActivityLevel
    allergies: list[str]


class FitEvaluation(BaseModel):
    """`evaluate_fit` 노드 *공식 출력* — Story 3.5 결정성 알고리즘.

    Story 3.3/3.4 stub 호환을 위해 신규 필드는 모두 default 값 부여:
    - ``fit_reason``: ``"ok"`` 정상, ``"allergen_violation"`` 단락, ``"incomplete_data"``
      profile/parsed_items 부재.
    - ``fit_label`` band(NFR-A4 색약 대응): ``good`` 80+ / ``caution`` 60-79 /
      ``needs_adjust`` <60 / ``allergen_violation`` 단락 케이스.
    - ``components``: 4 컴포넌트(macro/calorie/allergen/balance) + coverage_ratio
      분해 노출 — Story 3.6 인용 피드백 입력 + Story 4.3 차트 입력.
    """

    model_config = ConfigDict(extra="forbid")

    fit_score: int = Field(ge=0, le=100)
    reasons: list[str]
    fit_reason: Literal["ok", "allergen_violation", "incomplete_data"] = "ok"
    fit_label: Literal["good", "caution", "needs_adjust", "allergen_violation"] = "needs_adjust"
    components: FitScoreComponents = Field(default_factory=FitScoreComponents.zero)


class Citation(BaseModel):
    """`generate_feedback` 인용 — Story 3.2 `knowledge_chunks` 메타데이터 정합."""

    model_config = ConfigDict(extra="forbid")

    source: str
    doc_title: str
    published_year: int | None = None


class FeedbackOutput(BaseModel):
    """`generate_feedback` 노드 *공식 출력* — Story 3.6 stub은 `used_llm="stub"`."""

    model_config = ConfigDict(extra="forbid")

    text: str
    citations: list[Citation]
    used_llm: Literal["gpt-4o-mini", "claude", "stub"] = "stub"


class NodeError(BaseModel):
    """노드 retry 후 fallback 진입 컨텍스트 — Sentry breadcrumb 정합."""

    model_config = ConfigDict(extra="forbid")

    node_name: str
    error_class: str
    message: str
    attempts: int


def get_state_field(obj: object, name: str, default: object = None) -> object:
    """Pydantic instance + dict 양 형태 수용 — 체크포인터 직렬화 round-trip 안전.

    LangGraph `JsonPlusSerializer`는 Pydantic v2 모델을 round-trip 보존하지만, 다른
    serializer(예: `JsonSerializer`)나 외부 도구가 dict로 변환할 가능성에 대비하여
    state 필드 access는 본 helper를 거치는 것이 안전. `node_errors`/`retrieval`/
    `evaluation_decision` 등 객체 access 모든 지점이 대상.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class MealAnalysisState(TypedDict, total=False):
    """LangGraph 분석 파이프라인 SOT — `total=False`로 부분 dict-merge 정합.

    각 노드는 *반환 dict*에 자신의 출력 필드만 set — LangGraph가 dict-merge로 누적.
    런타임 검증 X(D7) — 노드 함수 내부에서 노드별 Pydantic 모델로 fail-fast 검증.
    """

    meal_id: uuid.UUID
    user_id: uuid.UUID
    raw_text: str
    parsed_items: list[FoodItem]
    retrieval: RetrievalResult
    rewrite_attempts: int
    rewritten_query: str | None
    user_profile: UserProfileSnapshot
    fit_evaluation: FitEvaluation
    feedback: FeedbackOutput
    node_errors: list[NodeError]
    needs_clarification: bool
    clarification_options: list[ClarificationOption]
    evaluation_decision: EvaluationDecision
    # Story 3.4 CR fix #1 (BLOCKER) — `aresume`이 True 주입 → `parse_meal` 노드가 DB
    # `meals.parsed_items` 우선 분기를 skip하고 LLM fallback 직진(사용자 정제 텍스트
    # 반영). 신규 분석은 미설정(False/missing).
    force_llm_parse: bool
