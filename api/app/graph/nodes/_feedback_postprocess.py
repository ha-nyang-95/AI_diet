"""Story 3.6 — `generate_feedback` 후처리 helper (AC2, AC6).

`generate_feedback` 노드에서 import — 인용 검증 / 출력 구조 검증 / 안전 워딩 fallback.
모든 함수 *pure*(deps 미사용) — 단위 테스트 격리. 도메인 레이어와 달리 `app.graph.*`
import 가능 (노드 helper는 graph 내부 — 단순화).

설계:
- ``validate_citations(text, available_chunks)`` — `(출처: 기관명, 문서명, 연도)`
  3-tuple 패턴(≥2 commas) ≥ 1건 + 모든 cited 기관명이 available_chunks의 source
  화이트리스트 안. (CR MJ-3 — 3-tuple comma 강제)
- ``has_required_sections(text)`` — `## 평가` + `## 다음 행동` 마크다운 헤더 정규식.
- ``append_safe_action_section(text)`` — `## 다음 행동` 부재 시 fallback append.
- ``append_safe_citation(text, available_chunks)`` — 인용 누락 시 fallback append.
"""

from __future__ import annotations

import re
from typing import Final

from app.graph.state import KnowledgeChunkContext

# CR MJ-9 — 1-level nested paren 지원 (`(출처: 기관 (2020) 문서)` 같은 학술 인용).
# 첫 ``)``에서 끊어지면 본문 후반부 leak 회귀 차단. ``ad_expression_guard`` 와 동일 패턴.
_CITATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"\(출처:[^()]*(?:\([^)]*\)[^()]*)*\)")
_EVALUATION_HEADER: Final[re.Pattern[str]] = re.compile(r"(?m)^##\s*평가\b")
_ACTION_HEADER: Final[re.Pattern[str]] = re.compile(r"(?m)^##\s*다음\s*행동\b")

# CR mn-15 — safe-action fallback 텍스트 단일 SOT(이전: 3곳 dup).
SAFE_ACTION_FALLBACK_TEXT: Final[str] = "오늘 한 끼 더 균형 잡힌 식사를 시도해보세요."
_SAFE_ACTION_FALLBACK: Final[str] = f"\n\n## 다음 행동\n{SAFE_ACTION_FALLBACK_TEXT}"


def _extract_cited_sources(text: str) -> list[str]:
    """``(출처: 기관명, 문서명, 연도)`` 패턴 안의 첫 토큰(기관명)을 추출.

    CR MJ-3 — 3-tuple `(기관, 문서, 연도)` 강제: 본문에 콤마 ≥2 (= 토큰 ≥3) 발견 시에만
    유효 citation으로 인정. 콤마 1개 이하면 빈 리스트(= 화이트리스트 검증 실패) 반환 →
    상위 ``validate_citations``가 regen 트리거.

    예: ``(출처: 식약처, 2020 한국인 영양소 섭취기준, 2020)`` → ``["식약처"]``.
    예: ``(출처: 식약처)`` → ``[]`` (3-tuple 미충족 → 검증 실패 시그널).
    """
    sources: list[str] = []
    for match in _CITATION_PATTERN.finditer(text):
        body = match.group(0)[len("(출처:") : -1].strip()
        parts = [p.strip() for p in body.split(",") if p.strip()]
        # CR MJ-3 — 3-tuple 미충족(<3 토큰)이면 *유효 citation 아님*.
        if len(parts) < 3:
            continue
        first_chunk = parts[0]
        if first_chunk:
            sources.append(first_chunk)
    return sources


def validate_citations(text: str, available_chunks: list[KnowledgeChunkContext]) -> bool:
    """인용 패턴 검증 — 3-tuple ``(기관, 문서, 연도)`` ≥ 1건 + cited 기관명이 화이트리스트 안.

    - 3-tuple 패턴 0건 → False (CR MJ-3 — `(출처: 식약처)` 단독 통과 차단).
    - 화이트리스트(available_chunks의 source 집합) 미포함 인용 발견 → False.
    - 모두 통과 → True.

    available_chunks 빈 경우(가이드라인 미발견 fallback) → 인용은 *권장 X*. 호출자가
    별도 분기.
    """
    cited_sources = _extract_cited_sources(text)
    if not cited_sources:
        return False
    whitelist = {c.source for c in available_chunks}
    if not whitelist:
        # available_chunks 부재 → 인용 자체가 화이트리스트 위반(자유 인용 금지 정합).
        return False
    return all(src in whitelist for src in cited_sources)


def has_required_sections(text: str) -> bool:
    """`## 평가` + `## 다음 행동` 헤더 둘 다 존재."""
    return bool(_EVALUATION_HEADER.search(text)) and bool(_ACTION_HEADER.search(text))


def append_safe_action_section(text: str) -> str:
    """`## 다음 행동` 부재 시 안전 fallback append. 이미 존재하면 그대로 반환."""
    if _ACTION_HEADER.search(text):
        return text
    return text.rstrip() + _SAFE_ACTION_FALLBACK


def append_safe_citation(text: str, available_chunks: list[KnowledgeChunkContext]) -> str:
    """인용 누락 시 안전 워딩 fallback append.

    available_chunks가 있으면 첫 chunk의 source / doc_title / year 사용 (3-tuple 형식
    유지 — CR MJ-3와 정합). 없으면 KDRIs 기본 cite 1줄(CR mn-28=a — chunks=[] 분기에서도
    인용 형식 유지 → 다운스트림 ``validate_citations`` 만족).
    """
    if available_chunks:
        first = available_chunks[0]
        if first.published_year is not None:
            citation = f"(출처: {first.source}, {first.doc_title}, {first.published_year})"
        else:
            # 3-tuple 유지를 위해 year 자리에 doc 메타 표기 — `미상` 한국어 leak 회피.
            citation = f"(출처: {first.source}, {first.doc_title}, n.d.)"
    else:
        # CR mn-28=a — chunks=[] 분기에서도 KDRIs 기본 1줄 cite (3-tuple 형식).
        citation = "(출처: 보건복지부, 2020 한국인 영양소 섭취기준, 2020)"
    return text.rstrip() + f"\n\n한국 1차 출처를 참고했습니다 {citation}"


__all__ = [
    "SAFE_ACTION_FALLBACK_TEXT",
    "append_safe_action_section",
    "append_safe_citation",
    "has_required_sections",
    "validate_citations",
]
