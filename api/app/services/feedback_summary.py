"""Story 3.7 — feedback_text → 1줄 요약 derive helper (AC17).

목표: ``meal_analyses.feedback_summary``(목록 화면용 1줄)는 ``feedback_text``(상세
화면용 full LLM 본문, Story 3.6 ``generate_feedback`` 결과)에서 *결정성으로* 파생.
LLM 추가 호출 0(cost 보호) + Story 3.6 출력 구조 검증 패턴 정합(``## 평가`` /
``## 다음 행동`` 마크다운 헤더 SOT).

규칙:
- ``## 평가`` 섹션 *첫 문장*(첫 마침표/물음표/느낌표까지) 추출 — Story 3.6
  ``OUTPUT_STRUCTURE_RULE``의 *"## 평가" 헤더가 항상 첫 섹션* 가정.
- 추출 실패(섹션 없음 또는 본문 없음) → 마크다운 헤더 strip 후 *전체 텍스트 첫 N자*
  fallback.
- ``max_chars`` 초과 시 ``...`` suffix 포함 truncate(`max_chars=120` baseline,
  ``meal_analyses.feedback_summary`` CHECK 제약 동기).
"""

from __future__ import annotations

import re
import unicodedata

# 마크다운 헤더 라인 매칭(``## 평가`` / ``## 다음 행동`` 등 — Story 3.6 SOT).
_HEADER_LINE_RE = re.compile(r"^\s{0,3}#{1,6}\s+.*$", re.MULTILINE)
# ``## 평가`` 섹션 본문 추출 — 다음 헤더 또는 EOF까지.
_EVAL_SECTION_RE = re.compile(
    r"^\s{0,3}#{1,6}\s*평가\s*$\s*(?P<body>.*?)(?=^\s{0,3}#{1,6}\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
# 첫 문장 — 영문 ``.``/``?``/``!`` + 한국어 fullwidth ``。``/``．`` + 말줄임표 ``…``
# 또는 줄바꿈 종료. CR Wave 1 #14 — Korean LLM 출력 종결자 다양성 수용.
_SENTENCE_TERMINATORS = r".!?。．…"
_FIRST_SENTENCE_RE = re.compile(
    rf"[^{_SENTENCE_TERMINATORS}\n]+(?:[{_SENTENCE_TERMINATORS}]|$)", re.DOTALL
)


def derive_feedback_summary(text: str, *, max_chars: int = 120) -> str:
    """``feedback_text`` → 1줄 요약 (목록 화면 입력).

    설계:
    1. NFC 정규화(grapheme cluster 안전 — Story 3.6 패턴 정합).
    2. ``## 평가`` 섹션 첫 문장 추출 시도.
    3. 추출 실패 시 *전체 텍스트* 마크다운 헤더 strip 후 첫 의미 라인 fallback.
    4. ``max_chars`` 초과 시 ``...``(3자) 포함 truncate — 결과 길이 ≤ ``max_chars``.

    빈 문자열 입력 → 빈 문자열 반환(호출 측이 가드 — Pydantic ``min_length=1`` 강제).
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    normalized = unicodedata.normalize("NFC", text or "").strip()
    if not normalized:
        return ""

    # 1차 — ``## 평가`` 섹션 첫 문장.
    eval_match = _EVAL_SECTION_RE.search(normalized)
    candidate: str | None = None
    if eval_match is not None:
        body = eval_match.group("body").strip()
        if body:
            sentence_match = _FIRST_SENTENCE_RE.search(body)
            if sentence_match is not None:
                candidate = sentence_match.group(0).strip()

    # 2차 — fallback: 전체 텍스트에서 헤더 strip 후 첫 비-헤더 라인.
    if not candidate:
        no_headers = _HEADER_LINE_RE.sub("", normalized).strip()
        if no_headers:
            sentence_match = _FIRST_SENTENCE_RE.search(no_headers)
            candidate = (
                sentence_match.group(0).strip() if sentence_match is not None else no_headers
            )

    if not candidate:
        # 정말로 비어있음 — fallback to original truncated.
        candidate = normalized

    return _truncate_with_ellipsis(candidate, max_chars=max_chars)


def _truncate_with_ellipsis(text: str, *, max_chars: int) -> str:
    """``max_chars`` 초과 시 ``...``(3자) 포함 truncate. ≤ max_chars면 원본."""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3] + "..."


__all__ = ["derive_feedback_summary"]
