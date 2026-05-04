"""Story 3.7 — SSE event helper + AnalysisDonePayload 단위 테스트 (Task 3.3)."""

from __future__ import annotations

import json
import uuid

import pytest

from app.api.v1.meals import MealMacros
from app.core.exceptions import ProblemDetail
from app.graph.state import Citation, ClarificationOption
from app.services.sse_emitter import (
    AnalysisDonePayload,
    chunk_text_for_streaming,
    event_citation,
    event_clarify,
    event_done,
    event_error,
    event_progress,
    event_token,
)


def _decode_event(event) -> tuple[str, dict]:
    """ServerSentEvent → (event_name, parsed_data dict)."""
    raw = event.encode().decode("utf-8")
    name = ""
    data_lines: list[str] = []
    for line in raw.splitlines():
        if line.startswith("event: "):
            name = line[len("event: ") :]
        elif line.startswith("data: "):
            data_lines.append(line[len("data: ") :])
    payload = json.loads("".join(data_lines)) if data_lines else {}
    return name, payload


# --- chunk_text_for_streaming -----------------------------------------------


def test_chunk_text_for_streaming_ascii_split() -> None:
    """ASCII 영문 — chunk_chars 단위 정확 분할."""
    text = "Hello World!"
    chunks = list(chunk_text_for_streaming(text, chunk_chars=5))
    assert chunks == ["Hello", " Worl", "d!"]


def test_chunk_text_for_streaming_korean_jamo_safe() -> None:
    """한국어 자모결합 — NFC 후 단일 codepoint 분할 안전."""
    text = "한국어 영양 분석입니다"
    chunks = list(chunk_text_for_streaming(text, chunk_chars=4))
    # 정확히 합치면 원본 동일 — codepoint cut 손실 0.
    assert "".join(chunks) == text
    # 4자 단위 분할 검증.
    assert len(chunks[0]) == 4


def test_chunk_text_for_streaming_empty() -> None:
    """빈 문자열 → 빈 iterator(yield 0회)."""
    assert list(chunk_text_for_streaming("", chunk_chars=10)) == []


def test_chunk_text_for_streaming_single_char() -> None:
    """1글자 → 1 chunk."""
    assert list(chunk_text_for_streaming("가", chunk_chars=24)) == ["가"]


def test_chunk_text_for_streaming_invalid_chunk_chars() -> None:
    """chunk_chars=0 또는 음수 → ValueError(호출 측 가드 신호)."""
    with pytest.raises(ValueError):
        list(chunk_text_for_streaming("text", chunk_chars=0))
    with pytest.raises(ValueError):
        list(chunk_text_for_streaming("text", chunk_chars=-1))


# --- event_* builders -------------------------------------------------------


def test_event_progress_builds_correct_payload() -> None:
    sse = event_progress("parse", elapsed_ms=12)
    name, payload = _decode_event(sse)
    assert name == "progress"
    assert payload == {"phase": "parse", "elapsed_ms": 12}


def test_event_token_korean_raw_byte_no_ascii_escape() -> None:
    """token JSON은 ensure_ascii=False — 한국어 raw byte 보존(token 비용 절감)."""
    sse = event_token("안녕")
    raw = sse.encode().decode("utf-8")
    # \uXXXX 이스케이프 없이 raw 한국어 출력 검증.
    assert "안녕" in raw
    assert "\\u" not in raw


def test_event_citation_serializes_optional_year() -> None:
    citation = Citation(source="MFDS", doc_title="알레르기 22종", published_year=2022)
    sse = event_citation(0, citation)
    name, payload = _decode_event(sse)
    assert name == "citation"
    assert payload == {
        "index": 0,
        "source": "MFDS",
        "doc_title": "알레르기 22종",
        "published_year": 2022,
    }


def test_event_clarify_serializes_options() -> None:
    options = [
        ClarificationOption(label="연어 포케", value="연어 포케 1인분"),
        ClarificationOption(label="참치 포케", value="참치 포케 1인분"),
    ]
    sse = event_clarify(options)
    name, payload = _decode_event(sse)
    assert name == "clarify"
    assert payload == {
        "options": [
            {"label": "연어 포케", "value": "연어 포케 1인분"},
            {"label": "참치 포케", "value": "참치 포케 1인분"},
        ]
    }


def test_event_done_full_payload_serialization() -> None:
    meal_id = uuid.uuid4()
    payload = AnalysisDonePayload(
        meal_id=meal_id,
        final_fit_score=72,
        fit_score_label="good",
        macros=MealMacros(carbohydrate_g=80.0, protein_g=25.0, fat_g=15.0, energy_kcal=580.0),
        feedback_text="평가 완료",
        citations_count=2,
        used_llm="gpt-4o-mini",
    )
    sse = event_done(payload)
    name, parsed = _decode_event(sse)
    assert name == "done"
    assert parsed["meal_id"] == str(meal_id)
    assert parsed["final_fit_score"] == 72
    assert parsed["fit_score_label"] == "good"
    assert parsed["macros"]["carbohydrate_g"] == 80.0
    assert parsed["citations_count"] == 2
    assert parsed["used_llm"] == "gpt-4o-mini"


def test_event_error_serializes_problem_detail() -> None:
    problem = ProblemDetail(
        title="Test Error",
        status=503,
        detail="upstream 일시 장애",
        instance="/v1/analysis/stream",
        code="analysis.checkpointer.unavailable",
    )
    sse = event_error(problem)
    name, parsed = _decode_event(sse)
    assert name == "error"
    assert parsed["status"] == 503
    assert parsed["code"] == "analysis.checkpointer.unavailable"
    assert parsed["title"] == "Test Error"
    assert parsed["instance"] == "/v1/analysis/stream"
    # CR Wave 1 #24 — RFC 7807 6 필드 SOT 검증(`type` 회귀 차단).
    assert "type" in parsed
    assert parsed["type"]  # default 또는 명시 type 모두 truthy


# --- AnalysisDonePayload bounds ---------------------------------------------


def test_analysis_done_payload_score_bounds() -> None:
    """final_fit_score는 0-100 강제 (Pydantic ValidationError)."""
    from pydantic import ValidationError

    base = dict(
        meal_id=uuid.uuid4(),
        fit_score_label="good",
        macros=MealMacros(carbohydrate_g=0, protein_g=0, fat_g=0, energy_kcal=0),
        feedback_text="x",
        citations_count=0,
        used_llm="stub",
    )
    with pytest.raises(ValidationError):
        AnalysisDonePayload(final_fit_score=-1, **base)
    with pytest.raises(ValidationError):
        AnalysisDonePayload(final_fit_score=101, **base)
    AnalysisDonePayload(final_fit_score=0, **base)
    AnalysisDonePayload(final_fit_score=100, **base)
