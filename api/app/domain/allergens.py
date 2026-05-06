"""식약처 *식품 등의 표시기준 별표* 22종 알레르기 유발물질 SOT — Story 1.5 + 3.5 + 4.3.

SOT 단일 위치: 본 모듈의 ``KOREAN_22_ALLERGENS`` tuple + 4 false-positive 가드 constant
(``_LABEL_SUBSTRING_EXCLUSIONS`` / ``_ALIAS_TEXT_EXCLUSIONS`` / ``_SKIP_SUBSTRING_LABELS`` /
``ALLERGEN_ALIAS_MAP``). Story 3.5 시점에 ``fit_score.py`` 내부에 박혀 있던 4 constant를
Story 4.3 시점에 본 모듈로 *재배치* — ``contains_allergen`` 헬퍼(주간 리포트 알레르기
노출 매칭) + ``detect_allergen_violations`` (Story 3.5 fit_score 단락) 양쪽이 동일
SOT를 공유(중복 정의 0). ``fit_score.py``는 본 모듈에서 import로 인계.

변경 시:
1. ``KOREAN_22_ALLERGENS`` tuple 갱신 → 정의 순서 보존(식약처 표시기준 별표 PDF 순).
2. 새 alembic revision으로 ``users.allergies`` CHECK 제약 drop+recreate
   (``app/db/models/user.py`` 모델 선언과 동일 SQL 사용).
3. ``scripts/verify_allergy_22.py`` 분기 1회 cron(R8 SOP, Story 8) 실행 결과 동기.

응용:
- ``app/api/v1/users.py:HealthProfileSubmitRequest`` Pydantic validator가
  ``normalize_allergens()``로 22종 부분집합 검증 + dedup.
- ``users.allergies`` Postgres ``text[]`` 컬럼에 DB CHECK 제약(``<@`` 부분집합)이
  본 tuple SQL 인라인으로 박힘(0005 마이그레이션).
- Story 3.5 ``domain/fit_score.py``가 본 모듈의 SOT 재사용 — ``users.allergies`` ∩
  ``parsed_items`` 단락 매칭.
- Story 4.3 ``services/report_service.py``가 ``contains_allergen`` 호출 — 주간
  알레르기 노출 횟수 카운트.
"""

from __future__ import annotations

import unicodedata
from typing import Final

# 식약처 별표 22종 — 정의 순서는 표시기준 PDF 순(우유 → 메밀 → 땅콩 → … → 기타).
# 본 순서를 *바꾸지 말 것* — 마이그레이션 SQL 인라인 + Story 3.5 fit_score 단위
# 테스트가 본 순서에 의존.
KOREAN_22_ALLERGENS: Final[tuple[str, ...]] = (
    "우유",
    "메밀",
    "땅콩",
    "대두",
    "밀",
    "고등어",
    "게",
    "새우",
    "돼지고기",
    "아황산류",
    "복숭아",
    "토마토",
    "호두",
    "닭고기",
    "난류(가금류)",
    "쇠고기",
    "오징어",
    "조개류(굴/전복/홍합 포함)",
    "잣",
    "아몬드",
    "잔류 우유 단백",
    "기타",
)

KOREAN_22_ALLERGENS_SET: Final[frozenset[str]] = frozenset(KOREAN_22_ALLERGENS)

# SOT drift fail-fast — 22종 정의 갯수가 23/21로 변경되면 import 시점에 즉시 실패.
# DB CHECK 제약(<@ ARRAY[...]) + Story 3.5 fit_score 22-단위 테스트가 22를 가정.
assert len(KOREAN_22_ALLERGENS) == 22, "MFDS spec defines exactly 22 allergens"
assert len(KOREAN_22_ALLERGENS_SET) == 22, "KOREAN_22_ALLERGENS contains duplicate labels"


# Story 3.5 CR B-3: 22-라벨 substring 매칭에서 *제외* 할 라벨 — `기타`는 generic
# placeholder로 식약처 카테고리 `기타가공식품` 같은 광범 텍스트에 false positive 발화.
# 본 라벨은 `ALLERGEN_ALIAS_MAP`의 explicit alias 경로로만 매칭(``기타알레르기성분``).
_SKIP_SUBSTRING_LABELS: Final[frozenset[str]] = frozenset({"기타"})

# Story 3.5 CR B-1: 22-라벨 substring 매칭 시 텍스트에서 먼저 제거할 *neighbor*
# 부분 문자열. 메밀(buckwheat, Fagopyrum)과 밀(wheat, Triticum)은 taxonomy/clinic
# 모두 별개 — `밀 in 메밀국수` false positive를 차단해 cross-allergen 오발화를 방지.
_LABEL_SUBSTRING_EXCLUSIONS: Final[dict[str, tuple[str, ...]]] = {
    "밀": ("메밀",),
}

# Story 3.5 CR B-2: ALLERGEN_ALIAS_MAP substring 매칭 시 텍스트에서 먼저 제거할
# 부분 문자열. `넛 → 호두` alias가 `도넛`(donut, no walnut), `코코넛`(coconut, *Cocos
# nucifera* — 호두/Juglans와 별개) 같은 비 호두 단어에 false positive 발화하지 않도록.
_ALIAS_TEXT_EXCLUSIONS: Final[dict[str, tuple[str, ...]]] = {
    "넛": ("도넛", "코코넛"),
}

# 한국 외식·배달 메뉴 alias → 22종 표준 라벨 baseline (8-13건).
# 외주 인수 시 클라이언트가 자사 메뉴별 보강 — SOP는 ``api/data/README.md``.
# Story 3.5 CR B-3: `기타알레르기성분` → `기타` alias 추가 — 22-라벨 substring
# 매칭에서 `기타`를 제외(generic substring false positive 차단)하면서도 explicit
# 음식명을 통한 매칭은 유지.
ALLERGEN_ALIAS_MAP: Final[dict[str, str]] = {
    "계란": "난류(가금류)",
    "달걀": "난류(가금류)",
    "오믈렛": "난류(가금류)",
    "마요네즈": "난류(가금류)",
    "치즈": "우유",
    "요구르트": "우유",
    "버터": "우유",
    "쉬림프": "새우",
    "포크": "돼지고기",
    "비프": "쇠고기",
    "치킨": "닭고기",
    "넛": "호두",
    "기타알레르기성분": "기타",
}


# Story 4.3 CR DN-2 — 알레르기 noise gate. Story 3.6 ``feedback_text``는 LLM 본문
# coaching 톤으로 *부정문* 자주 포함(예: "우유는 들어있지 않아 안심하세요"). substring
# 매칭만으로는 이런 phantom 노출을 차단할 수 없어 ``contains_allergen``의 매칭 직후
# 윈도우 검사로 해소. ``feedback_text``가 광고 가드(Story 3.6) 통과한 신뢰 텍스트라
# 안전한 KO negation marker 4종 휴리스틱 — 의미 분석 X(향후 NLP 도입은 Story 8.4 polish).
_NEGATION_PATTERNS: Final[tuple[str, ...]] = (
    "않",  # 않아/않다/않습니다/않은/않으
    "없",  # 없다/없어/없습니다/없음
    "아니",  # 아니다/아니에요/아니라/아니고
    "아닙",  # 아닙니다 (NFC에서 "아니"가 "아닙"으로 fuse — 별도 패턴 필요)
    "제외",  # 제외
)
# 매칭 위치 ± 윈도우 — 짧을수록 false negative ↑, 길수록 false positive ↑. 한국어
# 어절 평균 ~3-5자 + 보조용언 1-2어절 → 12자가 안정적 trade-off.
_NEGATION_WINDOW_CHARS: Final[int] = 12


def is_valid_allergen(value: str) -> bool:
    """단일 알레르기 라벨이 22종 도메인 내 인지 확인 — Pydantic validator/route 검증에서 사용.

    ``value``는 NFC 정규화 후 비교(NFD-encoded Hangul 클립보드 paste 호환).
    """
    return unicodedata.normalize("NFC", value) in KOREAN_22_ALLERGENS_SET


def normalize_allergens(values: list[str]) -> list[str]:
    """22종 부분집합 검증 + dedup + NFC 정규화. invalid 항목 발견 시 ``ValueError`` 발생.

    반환 순서는 ``KOREAN_22_ALLERGENS`` 정의 순(결정성). dedup은 frozenset 거친 후
    정의 순 재정렬. 빈 입력 → 빈 리스트.

    NFC 정규화: macOS 클립보드 등 일부 source는 Hangul을 NFD(decomposed jamo)로 인코딩.
    SOT의 NFC 라벨과 byte 비교가 실패하지 않도록 입력값을 NFC로 normalize 후 비교.
    """
    seen: set[str] = set()
    for v in values:
        normalized = unicodedata.normalize("NFC", v)
        if normalized not in KOREAN_22_ALLERGENS_SET:
            raise ValueError(f"unknown allergen: {v!r}; must be one of 22 식약처 standard.")
        seen.add(normalized)
    return [a for a in KOREAN_22_ALLERGENS if a in seen]


def _has_negation_after(text: str, pos: int, length: int) -> bool:
    """매칭 위치 직후 윈도우(``_NEGATION_WINDOW_CHARS``자) 내 negation marker 검사.

    Story 4.3 CR DN-2 — Story 3.6 ``feedback_text`` 본문에 "X는 들어있지 않아",
    "X 없음", "X 아닙니다" 등 부정문이 자주 등장. substring 매칭만으로는 phantom
    노출 카운트가 발생해 AllergyExposureChart 과대보고. 매칭 직후 윈도우에 negation
    marker가 있으면 매칭 무효화.
    """
    window_end = min(len(text), pos + length + _NEGATION_WINDOW_CHARS)
    window = text[pos + length : window_end]
    return any(pattern in window for pattern in _NEGATION_PATTERNS)


def contains_allergen(text: str, allergen: str) -> bool:
    """``text``의 NFC 정규화 후 ``allergen`` (22종 중 1) 노출 여부 검사 — Story 4.3.

    매칭 의미론: 자연어 텍스트(``parsed_items[].name`` 또는 ``feedback_text``)가
    22종 알레르기 라벨을 *substring* 또는 *alias substring* 형태로 포함하는지.
    Story 3.5의 4 false-positive 가드 SOT(``_LABEL_SUBSTRING_EXCLUSIONS`` /
    ``_ALIAS_TEXT_EXCLUSIONS`` / ``_SKIP_SUBSTRING_LABELS`` / ``ALLERGEN_ALIAS_MAP``)를
    그대로 재사용하여 *주간 리포트 알레르기 노출 횟수*와 *fit_score 단락* 양쪽이
    *동일* 매칭 결과를 갖도록.

    Story 4.3 CR DN-2: 매칭 직후 윈도우(12자)에 negation marker(``않``/``없``/``아니``/
    ``제외``)가 있으면 phantom 매칭으로 간주 — Story 3.6 ``feedback_text`` 부정문
    false positive 차단(예: "우유는 들어있지 않아 안심하세요" → False).

    가드:

    - ``allergen``이 22종 SOT 외 → ``ValueError``(prevention보다 fail-fast 정합).
    - ``text`` ``None`` → ``ValueError``. 빈 문자열은 ``False`` 반환(매칭 없음).

    예시 (Story 4.3 AC6 정의):

    - ``contains_allergen("메밀국수", "밀")`` → ``False`` (``_LABEL_SUBSTRING_EXCLUSIONS``)
    - ``contains_allergen("밀빵 샐러드", "밀")`` → ``True``
    - ``contains_allergen("도넛 1개", "호두")`` → ``False`` (``_ALIAS_TEXT_EXCLUSIONS``,
      ``넛`` alias가 ``도넛`` 매칭 차단)
    - ``contains_allergen("기타 가공품", "기타")`` → ``False`` (``_SKIP_SUBSTRING_LABELS``)
    - ``contains_allergen("기타알레르기성분 함유", "기타")`` → ``True`` (explicit alias)
    - ``contains_allergen("치즈피자", "우유")`` → ``True`` (alias ``치즈``→``우유``)
    - ``contains_allergen("우유는 들어있지 않아 안심", "우유")`` → ``False`` (DN-2 negation)
    """
    if text is None:
        raise ValueError("text must not be None")
    if allergen not in KOREAN_22_ALLERGENS_SET:
        raise ValueError(f"unknown allergen: {allergen!r}; must be one of 22 식약처 standard.")
    if not text:
        return False

    normalized_text = unicodedata.normalize("NFC", text)
    normalized_label = unicodedata.normalize("NFC", allergen)

    # (1) 22종 직접 substring 매칭 — _SKIP_SUBSTRING_LABELS 우회 + neighbor exclusion.
    if normalized_label not in _SKIP_SUBSTRING_LABELS:
        candidate = normalized_text
        for excl in _LABEL_SUBSTRING_EXCLUSIONS.get(normalized_label, ()):
            candidate = candidate.replace(excl, "")
        pos = candidate.find(normalized_label)
        if pos >= 0 and not _has_negation_after(candidate, pos, len(normalized_label)):
            return True

    # (2) ALLERGEN_ALIAS_MAP — alias substring → 22종 표준 라벨. 본 alias가 입력
    # ``allergen``으로 매핑되는지 검사.
    for alias, standard in ALLERGEN_ALIAS_MAP.items():
        if standard != normalized_label:
            continue
        candidate = normalized_text
        for excl in _ALIAS_TEXT_EXCLUSIONS.get(alias, ()):
            candidate = candidate.replace(excl, "")
        pos = candidate.find(alias)
        if pos >= 0 and not _has_negation_after(candidate, pos, len(alias)):
            return True

    return False
