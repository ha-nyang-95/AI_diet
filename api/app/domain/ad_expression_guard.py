"""Story 3.6 — 광고 표현 가드 (식약처 의약품 오인 광고 금지 표현, AC4/AC5).

식품표시광고법 시행규칙 별표 9에서 의약품 오인 광고 금지 5표현(진단/치료/예방/완화/처방)
을 정규식으로 검출 + 안전 워딩으로 치환. 인용 본문 ``(출처: ...)`` 내부의 단어는
*치환 skip*(원문 보존 — 1차 출처 인용은 광고 표현이 아니라 *문서 제목 일부*일 수 있음).

설계:
- ``PROHIBITED_PATTERNS``: ``{canonical_term: re.Pattern}``. 굴절형 매칭(`치료해야` /
  `예방됩니다`)은 *그룹 외* 어미 — 매칭 시작 위치는 prohibited term 자체에 한정.
- ``SAFE_REPLACEMENTS``: ``{canonical_term: replacement}``. canonical term만 치환 →
  어미는 보존(예: `치료해야` → `관리해야`). 일부 어미는 어색할 수 있으나 spec line 240
  *"어색하지만 안전"* 정합.
- ``find_violations(text)``: 인용 본문 마스킹 후 정규식 검색. 반환은
  ``[(canonical_term, start, end), ...]`` — start/end는 *canonical term 자체* 위치.
- ``replace_violations(text, violations)``: 뒤에서 앞으로 슬라이스 치환(offset shift 차단).
- ``apply_replacements(text)``: convenience — find + replace 결합.

도메인 레이어 — graph 모듈 import 금지(SOT 분리, Story 3.5 패턴 정합).
"""

from __future__ import annotations

import re
from typing import Final

# 식약처 식품표시광고법 시행규칙 별표 9 — 의약품 오인 광고 금지 표현.
# 굴절형 매칭은 *그룹 외* 어미(`(?:합니다|...)?`). 매칭 시작 위치는 canonical term 자체에 한정.
#
# CR B1=a — `?`-optional suffix가 substring fallback을 만들어 명사 합성어
# (`예방접종 → 도움이 될 수 있는접종` 등 garbled output 발생)도 fire하던 회귀 차단:
# 각 term 직후 negative lookahead로 손상 큰 명사 합성 stop-list를 명시 차단.
# `치료법`/`치료실`은 spec line 240 *"보수적 정합 우선"* 합의대로 cosmetic 수용
# (stop-list에 미포함 → 매칭). 후속 Story 8.4에서 alias 확장 가능.
PROHIBITED_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "진단": re.compile(r"진단(?!(?:서|명|키트|의학|기관))(?:합니다|해야|됩|을|받|에)?"),
    "치료": re.compile(r"치료(?!(?:감호))(?:합니다|해야|됩|효과|받|에|중)?"),
    "예방": re.compile(
        r"예방(?!(?:접종|의학|주사|약|차원|책|학|법|기관))(?:합니다|돼|됩|에|받|효과|할 수)?"
    ),
    "완화": re.compile(r"완화(?!(?:제|의료|케어|병동))(?:시켜|돼|됩|효과|하|할 수)?"),
    "처방": re.compile(r"처방(?!(?:전|약|료|기록|책))(?:합니다|받|돼|에|할 수)?"),
}

SAFE_REPLACEMENTS: Final[dict[str, str]] = {
    "진단": "안내",
    "치료": "관리",
    "예방": "도움이 될 수 있는",
    "완화": "참고",
    "처방": "권장",
}

# 인용 본문 마스킹 — ``(출처: ...)`` 내부의 prohibited term은 광고 표현이 아니라 *문서
# 제목 일부*일 수 있어 보존. 마스킹은 같은 길이의 공백 문자로 대체 → 정규식 매칭
# 우회 + offset 보존(공백은 1 codepoint이므로 길이 보존).
#
# CR MJ-9 — 1-level nested paren 지원 패턴(`(출처: 기관 (2020) 문서)` 같은 한국 학술
# 인용 형식에서 첫 `)`에서 끊어지면 본문 후반 leak). 추가 nested 깊이는 드물어 OUT.
_CITATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"\(출처:[^()]*(?:\([^)]*\)[^()]*)*\)")


def _mask_citations(text: str) -> str:
    """``(출처: ...)`` 영역을 같은 길이의 공백 문자로 마스킹 → 정규식 매칭 영역에서 제외."""

    def _replace(match: re.Match[str]) -> str:
        return " " * len(match.group(0))

    return _CITATION_PATTERN.sub(_replace, text)


def find_violations(text: str) -> list[tuple[str, int, int]]:
    """광고 금지 표현 위반 검출.

    인용 본문 ``(출처: ...)`` 내부의 단어는 마스킹 후 검사 → 위반 X (원문 보존).
    반환은 ``[(canonical_term, start, end), ...]`` — start/end는 canonical term 자체 위치
    (굴절형 어미는 매칭 트리거이지 치환 대상 X). 결과는 *시작 위치 오름차순* 정렬.
    """
    if not text:
        return []
    masked = _mask_citations(text)
    found: list[tuple[str, int, int]] = []
    for canonical, pattern in PROHIBITED_PATTERNS.items():
        canonical_len = len(canonical)
        for match in pattern.finditer(masked):
            start = match.start()
            found.append((canonical, start, start + canonical_len))
    found.sort(key=lambda v: v[1])
    return found


def replace_violations(text: str, violations: list[tuple[str, int, int]]) -> str:
    """``find_violations`` 출력을 받아 canonical term만 ``SAFE_REPLACEMENTS``로 치환.

    뒤에서 앞으로 슬라이스 치환 — offset shift 차단(spec Task 6.3). 어미는 자동 보존
    (start/end가 canonical term에 한정).
    """
    if not violations:
        return text
    # 뒤에서 앞으로 — start 내림차순.
    result = text
    for canonical, start, end in sorted(violations, key=lambda v: v[1], reverse=True):
        replacement = SAFE_REPLACEMENTS[canonical]
        result = result[:start] + replacement + result[end:]
    return result


def apply_replacements(text: str) -> str:
    """``find_violations`` + ``replace_violations`` 결합. 정상 텍스트는 그대로 반환."""
    violations = find_violations(text)
    if not violations:
        return text
    return replace_violations(text, violations)


__all__ = [
    "PROHIBITED_PATTERNS",
    "SAFE_REPLACEMENTS",
    "apply_replacements",
    "find_violations",
    "replace_violations",
]
