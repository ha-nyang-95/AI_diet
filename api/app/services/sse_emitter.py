"""Story 3.7 — SSE event helper + AnalysisDonePayload Pydantic 모델 (AC2 / AC4).

설계:
- ``chunk_text_for_streaming``: NFC 정규화 후 char-단위 분할 — 한국어 자모결합은
  NFC 후 단일 codepoint이라 ``list(text)`` 분할 안전(D1 결정 정합). emoji ZWJ /
  Fitzpatrick modifier 분리는 cosmetic only — Story 8.4 polish에서 ``regex`` 라이브
  러리 도입 검토.
- ``event_*`` 6 builder: ``sse_starlette.ServerSentEvent``를 wrap — ``data`` 인자에
  ``json.dumps(payload, ensure_ascii=False)`` 직렬화. ``ensure_ascii=False``는
  한국어 raw byte 보존(token 비용 절감 + UI 인스펙터 가독성).
- ``AnalysisDonePayload``: SSE ``event: done`` 응답 schema — ``GET /v1/analysis/{meal_id}``
  polling 응답 ``status="done"``의 ``result`` 필드와도 동일 schema.

Story 3.6 anchor 정합:
- ``frozen=True`` extra="forbid" — payload immutable + 미정 필드 차단.
- citations 필드는 0-based index 기반(spec AC2 정합).
"""

from __future__ import annotations

import json
import unicodedata
import uuid
from collections.abc import Iterator
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sse_starlette import ServerSentEvent

from app.api.v1.meals import MealMacros
from app.core.exceptions import ProblemDetail
from app.graph.state import Citation, ClarificationOption

_FitScoreLabel = Literal["allergen_violation", "low", "moderate", "good", "excellent"]
_UsedLLM = Literal["gpt-4o-mini", "claude", "stub"]


class AnalysisDonePayload(BaseModel):
    """SSE ``event: done`` payload + polling ``status="done"`` 응답 result schema (AC2/AC7).

    설계:
    - ``meal_id``: 클라이언트가 캐시 invalidate 키로 사용.
    - ``final_fit_score`` + ``fit_score_label``: ``MealAnalysisSummary`` 5-band과 정합
      (`to_summary_label` helper로 변환). 0-100 + 5단계 라벨 SOT.
    - ``macros``: ``app.api.v1.meals.MealMacros`` 재사용(import 단방향 — meals.py가
      MealMacros SOT 정의).
    - ``feedback_text``: full LLM 본문(UI 단일 표시 + 영속화 입력).
    - ``citations_count``: 별 ``event: citation`` emit 수 검증용 보조 필드.
    - ``used_llm``: 라우터/dual-LLM 결정 추적(`gpt-4o-mini`/`claude`/`stub` 3-way).

    ``frozen=True``로 응답 directly mutate 차단. ``extra="forbid"``로 미정 필드 leak 차단.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    meal_id: uuid.UUID
    final_fit_score: int = Field(ge=0, le=100)
    fit_score_label: _FitScoreLabel
    macros: MealMacros
    feedback_text: str = Field(min_length=1)
    citations_count: int = Field(ge=0)
    used_llm: _UsedLLM


def chunk_text_for_streaming(text: str, *, chunk_chars: int = 24) -> Iterator[str]:
    """본문 텍스트 → 24자 chunk iterator (D1 결정 — pseudo-streaming + NFC).

    NFC 정규화 후 ``list(text)``로 codepoint 분할 → ``chunk_chars`` 단위 슬라이스.
    한국어 자모결합은 NFC 후 단일 codepoint이라 mid-codepoint cut 안전. emoji ZWJ
    시퀀스 / Fitzpatrick modifier는 cosmetic split 가능(Story 8.4 polish).

    빈 텍스트 → 빈 iterator(yield 없음). chunk_chars=0 또는 음수는 ValueError —
    호출 측 가드(설정값은 항상 양수).
    """
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    if not text:
        return
    normalized = unicodedata.normalize("NFC", text)
    codepoints = list(normalized)
    for start in range(0, len(codepoints), chunk_chars):
        yield "".join(codepoints[start : start + chunk_chars])


def _serialize(payload: dict[str, Any]) -> str:
    """JSON 직렬화 SOT — ``ensure_ascii=False``(한국어 raw byte) + ``allow_nan=False``
    (NaN/Inf 차단 — 클라이언트 JSON.parse 회귀 방지)."""
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def event_progress(phase: str, *, elapsed_ms: int) -> ServerSentEvent:
    """``event: progress`` builder — TTFT(NFR-P3) 조기 신호용. 라우터 진입 직후 1회 emit."""
    return ServerSentEvent(
        data=_serialize({"phase": phase, "elapsed_ms": elapsed_ms}),
        event="progress",
    )


def event_token(delta: str) -> ServerSentEvent:
    """``event: token`` builder — LLM 본문 청크."""
    return ServerSentEvent(
        data=_serialize({"delta": delta}),
        event="token",
    )


def event_citation(index: int, citation: Citation) -> ServerSentEvent:
    """``event: citation`` builder — feedback.citations 1:1 매핑(0-based index 순서)."""
    return ServerSentEvent(
        data=_serialize(
            {
                "index": index,
                "source": citation.source,
                "doc_title": citation.doc_title,
                "published_year": citation.published_year,
            }
        ),
        event="citation",
    )


def event_clarify(options: list[ClarificationOption]) -> ServerSentEvent:
    """``event: clarify`` builder — Story 3.4 needs_clarification 분기 emit.

    chip 리스트로 사용자에게 노출 → 선택 시 ``POST /v1/analysis/clarify``로 resume.
    """
    return ServerSentEvent(
        data=_serialize({"options": [{"label": opt.label, "value": opt.value} for opt in options]}),
        event="clarify",
    )


def event_done(payload: AnalysisDonePayload) -> ServerSentEvent:
    """``event: done`` builder — 종료 1회 emit. UI는 카드 영속화 + invalidate 신호."""
    return ServerSentEvent(
        data=_serialize(payload.model_dump(mode="json")),
        event="done",
    )


def event_error(problem: ProblemDetail) -> ServerSentEvent:
    """``event: error`` builder — RFC 7807 ProblemDetail JSON. AC2 code 카탈로그 정합."""
    return ServerSentEvent(
        data=_serialize(problem.to_response_dict()),
        event="error",
    )


__all__ = [
    "AnalysisDonePayload",
    "chunk_text_for_streaming",
    "event_citation",
    "event_clarify",
    "event_done",
    "event_error",
    "event_progress",
    "event_token",
]
