"""Story 3.7 — derive_feedback_summary 단위 테스트 (Task 16.8 / AC17)."""

from __future__ import annotations

import pytest

from app.services.feedback_summary import derive_feedback_summary


def test_derive_extracts_first_sentence_of_eval_section() -> None:
    """## 평가 섹션 첫 문장 추출 — Story 3.6 OUTPUT_STRUCTURE_RULE 정합."""
    text = (
        "## 평가\n"
        "오늘 식단은 단백질이 부족하지만 탄수화물 균형은 양호합니다. 추가 보충이 필요해요.\n\n"
        "## 다음 행동\n"
        "닭가슴살 100g 추가를 권장합니다."
    )
    summary = derive_feedback_summary(text)
    assert summary == "오늘 식단은 단백질이 부족하지만 탄수화물 균형은 양호합니다."


def test_derive_falls_back_when_no_eval_section() -> None:
    """``## 평가`` 헤더 부재 → 전체 텍스트 첫 문장 fallback(헤더 strip 후)."""
    text = "오늘 식단은 양호한 편입니다. 단백질을 조금 더 보충해보세요."
    summary = derive_feedback_summary(text)
    assert summary == "오늘 식단은 양호한 편입니다."


def test_derive_short_text_passthrough() -> None:
    """짧은 텍스트(120자 이하) → 원본 유지(truncate 없음)."""
    text = "잘 먹었습니다."
    summary = derive_feedback_summary(text)
    assert summary == text


def test_derive_truncates_with_ellipsis() -> None:
    """120자 초과 → ``...`` suffix 포함 truncate (결과 ≤ 120자)."""
    long_text = "가" * 200
    summary = derive_feedback_summary(long_text, max_chars=120)
    assert len(summary) == 120
    assert summary.endswith("...")
    # ``...`` 앞부분은 원본 첫 117자.
    assert summary[:-3] == "가" * 117


def test_derive_strips_markdown_headers_in_fallback() -> None:
    """헤더 라인은 fallback 추출 시 제거 — 헤더 자체가 summary가 되지 않도록."""
    text = "## 잘못된 헤더\n실제 본문 첫 줄입니다."
    summary = derive_feedback_summary(text)
    assert "##" not in summary
    assert "실제 본문" in summary


def test_derive_empty_input_returns_empty() -> None:
    """빈 문자열 → 빈 문자열(호출 측 가드 신호)."""
    assert derive_feedback_summary("") == ""
    assert derive_feedback_summary("   \n  ") == ""


def test_derive_invalid_max_chars() -> None:
    """max_chars=0 또는 음수 → ValueError(호출 측 가드)."""
    with pytest.raises(ValueError):
        derive_feedback_summary("text", max_chars=0)
