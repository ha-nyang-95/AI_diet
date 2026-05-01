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
"""

from __future__ import annotations

import uuid
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

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
    """RAG top-k 결과 단일 음식 — Story 3.4가 실 alias lookup + HNSW로 채움."""

    model_config = ConfigDict(extra="forbid")

    name: str
    food_id: uuid.UUID | None = None
    score: float = Field(ge=0, le=1)
    nutrition: dict[str, float | int]


class RetrievalResult(BaseModel):
    """`retrieve_nutrition` 노드 *공식 출력* — top-1 score 또는 평균을 신뢰도로."""

    model_config = ConfigDict(extra="forbid")

    retrieved_foods: list[RetrievedFood]
    retrieval_confidence: float = Field(ge=0, le=1)


class EvaluationDecision(BaseModel):
    """`evaluate_retrieval_quality` 노드 *공식 출력* — Self-RAG 분기 라우팅 신호."""

    model_config = ConfigDict(extra="forbid")

    route: Literal["rewrite", "continue"]
    reason: str


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
    """`evaluate_fit` 노드 *공식 출력* — Story 3.5 stub: 50 + []."""

    model_config = ConfigDict(extra="forbid")

    fit_score: int = Field(ge=0, le=100)
    reasons: list[str]


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
    evaluation_decision: EvaluationDecision
