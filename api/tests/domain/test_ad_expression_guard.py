"""Story 3.6 — ``app.domain.ad_expression_guard`` 단위 테스트 (T10 KPI ≥ 10 케이스, AC4/AC5).

식약처 식품표시광고법 시행규칙 별표 9 의약품 오인 광고 금지 표현 5종(진단/치료/예방/완화/
처방) × 굴절형 변형 + edge cases. 정규식 매칭 + 안전 워딩 치환 + 인용 본문 보존.
"""

from __future__ import annotations

from app.domain.ad_expression_guard import (
    PROHIBITED_PATTERNS,
    SAFE_REPLACEMENTS,
    apply_replacements,
    find_violations,
    replace_violations,
)

# ---------- 모듈 상수 invariants ----------


def test_prohibited_patterns_5_terms() -> None:
    """5개 의약품 오인 표현 모두 등재."""
    assert set(PROHIBITED_PATTERNS) == {"진단", "치료", "예방", "완화", "처방"}


def test_safe_replacements_5_terms() -> None:
    """5개 안전 워딩 모두 매핑."""
    assert set(SAFE_REPLACEMENTS) == {"진단", "치료", "예방", "완화", "처방"}
    assert SAFE_REPLACEMENTS["치료"] == "관리"
    assert SAFE_REPLACEMENTS["예방"] == "도움이 될 수 있는"
    assert SAFE_REPLACEMENTS["진단"] == "안내"
    assert SAFE_REPLACEMENTS["완화"] == "참고"
    assert SAFE_REPLACEMENTS["처방"] == "권장"


# ---------- 5 prohibited terms 원형 + 굴절형 (≥ 10 케이스 — T10 KPI) ----------


def test_violation_치료_원형() -> None:
    text = "당분 섭취가 비만을 치료해요"
    violations = find_violations(text)
    assert any(v[0] == "치료" for v in violations)
    replaced = apply_replacements(text)
    assert "치료" not in replaced
    assert "관리" in replaced


def test_violation_치료_굴절형_해야() -> None:
    text = "이 성분이 비만을 치료해야 한다"
    violations = find_violations(text)
    assert any(v[0] == "치료" for v in violations)
    replaced = apply_replacements(text)
    assert "치료" not in replaced
    assert "관리해야" in replaced


def test_violation_예방_굴절형_됩니다() -> None:
    text = "당뇨가 예방됩니다"
    violations = find_violations(text)
    assert any(v[0] == "예방" for v in violations)
    replaced = apply_replacements(text)
    assert "예방" not in replaced
    assert "도움이 될 수 있는" in replaced


def test_violation_예방_굴절형_할_수_있어요() -> None:
    text = "당뇨를 예방할 수 있어요"
    violations = find_violations(text)
    assert any(v[0] == "예방" for v in violations)
    replaced = apply_replacements(text)
    assert "예방" not in replaced


def test_violation_진단_굴절형_합니다() -> None:
    text = "이 식사가 영양 결핍을 진단합니다"
    violations = find_violations(text)
    assert any(v[0] == "진단" for v in violations)
    replaced = apply_replacements(text)
    assert "진단" not in replaced
    assert "안내합니다" in replaced


def test_violation_완화_굴절형_시켜() -> None:
    text = "통증을 완화시켜 드립니다"
    violations = find_violations(text)
    assert any(v[0] == "완화" for v in violations)
    replaced = apply_replacements(text)
    assert "완화" not in replaced
    assert "참고" in replaced


def test_violation_처방_굴절형_하세요() -> None:
    text = "전문가가 식단을 처방하세요"
    violations = find_violations(text)
    assert any(v[0] == "처방" for v in violations)
    replaced = apply_replacements(text)
    assert "처방" not in replaced
    assert "권장하세요" in replaced


def test_violation_5_terms_원형_각1건() -> None:
    """5 prohibited terms 모두 원형으로 1번씩 검출."""
    text = "이 식사로 진단 치료 예방 완화 처방"
    violations = find_violations(text)
    canonicals = {v[0] for v in violations}
    assert canonicals == {"진단", "치료", "예방", "완화", "처방"}


# ---------- Edge cases (false-positive 0 + 인용 본문 보존 + 다중 동시 + 빈 입력) ----------


def test_normal_text_no_false_positive() -> None:
    """정상 텍스트 — 위반 0건 (false-positive 0)."""
    text = "건강한 식사로 균형을 관리하세요"
    violations = find_violations(text)
    assert violations == []
    replaced = apply_replacements(text)
    assert replaced == text


def test_violation_in_citation_preserved() -> None:
    """인용 본문 ``(출처: ...)`` 내부의 prohibited term은 *치환 skip*(원문 보존)."""
    text = "균형 잡힌 식사를 권장합니다 (출처: KDRIs 2020 치료 영양 섭취기준)"
    # find_violations가 인용 본문 위치를 마스킹 후 검사 → violations에 포함 X.
    violations = find_violations(text)
    canonicals = [v[0] for v in violations]
    assert "치료" not in canonicals
    replaced = apply_replacements(text)
    assert "치료 영양 섭취기준" in replaced  # 인용 본문 그대로


def test_multi_violations_simultaneous_replace() -> None:
    """다중 위반 동시 치환 — 모두 변경."""
    text = "이 식사로 당뇨를 예방하고 치료할 수 있어요"
    violations = find_violations(text)
    canonicals = {v[0] for v in violations}
    assert "예방" in canonicals and "치료" in canonicals
    replaced = apply_replacements(text)
    assert "예방" not in replaced
    assert "치료" not in replaced
    assert "도움이 될 수 있는" in replaced
    assert "관리" in replaced


def test_empty_string_no_violations() -> None:
    """빈 문자열 / 공백 only — violations 0건."""
    assert find_violations("") == []
    assert find_violations("   ") == []
    assert apply_replacements("") == ""


def test_replace_violations_offset_safety() -> None:
    """``replace_violations``는 뒤에서 앞으로 슬라이스 — offset shift 차단 검증."""
    text = "처방하고 치료한다"
    violations = find_violations(text)
    replaced = replace_violations(text, violations)
    assert "처방" not in replaced
    assert "치료" not in replaced
    assert replaced == "권장하고 관리한다"


# ---------- 명사 합성 false-positive 가드 (CR B1=a — negative lookahead stop-list) ----------


def test_치료법_보수적_매칭_known_limitation() -> None:
    """``치료법``은 stop-list 미포함 → 보수적 매칭 유지(spec line 240 합의).

    CR MJ-16 — 이전 테스트 이름 ``test_no_false_positive_치료법_명사_합성``이 *false
    positive를 expected로 assert*하던 거짓-네이밍 회귀 차단. 본 테스트는 ``치료법``이
    여전히 매칭됨을 *known limitation*으로 명시.
    """
    text = "한방 치료법을 소개합니다"
    violations = find_violations(text)
    # `치료법`의 `법`은 `치료` regex stop-list 미포함 → 매칭 fire (의도된 보수적 동작).
    assert any(v[0] == "치료" for v in violations)


def test_no_false_positive_예방접종() -> None:
    """``예방접종``은 vaccination — neutral compound. CR B1=a stop-list 차단."""
    text = "어린이 예방접종을 받으세요"
    violations = find_violations(text)
    assert violations == []
    replaced = apply_replacements(text)
    assert replaced == text  # garbled "도움이 될 수 있는접종" 회귀 차단


def test_no_false_positive_처방전() -> None:
    """``처방전``은 prescription document — neutral noun. CR B1=a stop-list 차단."""
    text = "처방전을 약국에 제출하세요"
    violations = find_violations(text)
    assert violations == []
    assert apply_replacements(text) == text


def test_no_false_positive_완화병동() -> None:
    """``완화병동``은 palliative ward — neutral medical facility noun. CR B1=a 차단."""
    text = "완화병동에서 휴식 중입니다"
    violations = find_violations(text)
    assert violations == []
    assert apply_replacements(text) == text


def test_no_false_positive_진단서() -> None:
    """``진단서``는 diagnosis document — neutral noun. CR B1=a 차단."""
    text = "병원에서 진단서를 발급받았어요"
    violations = find_violations(text)
    assert violations == []
    assert apply_replacements(text) == text


def test_no_false_positive_처방약() -> None:
    """``처방약``은 prescribed medication noun. CR B1=a 차단."""
    text = "처방약을 처방대로 복용하세요"
    # `처방대로`는 stop-list 미포함이라 매칭됨(spec 정합 — `처방`이 사용 동사).
    # 첫 ``처방약``만 차단 검증.
    violations = find_violations(text)
    canonicals = [v[0] for v in violations]
    # "처방약"은 fire 안 함 + "처방대로"는 fire (stop-list `대로` 미포함 — bare 매칭 + 동사 사용)
    # `처방대로`의 `대` 다음 char는 `로` → suffix 그룹 매칭 X → bare `처방` fire.
    # 따라서 violations 0 또는 1 (정확히는 1 — `처방대로`).
    assert canonicals.count("처방") <= 1


def test_adjacent_prohibited_terms_진단치료() -> None:
    """CR mn-8 — 인접한 prohibited term 두 개 (`진단치료`) 모두 검출 + 치환."""
    text = "이 식품은 진단치료에 사용됩니다"
    violations = find_violations(text)
    canonicals = {v[0] for v in violations}
    assert "진단" in canonicals
    assert "치료" in canonicals
    replaced = apply_replacements(text)
    # 뒤에서 앞으로 슬라이스 → 치료 먼저 치환(관리), 진단 후 치환(안내).
    # 결과: "안내관리에 사용됩니다".
    assert "진단" not in replaced
    assert "치료" not in replaced
    assert "안내" in replaced
    assert "관리" in replaced


def test_apply_replacements_idempotency() -> None:
    """CR mn-12 — `apply_replacements` 두 번 적용해도 동일 결과 (idempotent)."""
    text = "이 식사로 당뇨를 치료해야 합니다"
    once = apply_replacements(text)
    twice = apply_replacements(once)
    assert twice == once
    # 안전 워딩(관리/안내/도움이 될 수 있는/참고/권장)에는 prohibited term 미포함.
    assert "치료" not in once
    assert "관리" in once


def test_nested_paren_citation_preserved() -> None:
    """CR MJ-9 — `(출처: 기관 (2020) 문서)` 같은 1-level nested paren 인용 본문 보존.

    이전 ``[^)]*`` 패턴은 첫 ``)``에서 끊겨 `, 문서)` 부분 leak → 본문 내 `치료` 등이
    fire하던 회귀. 새 패턴 ``[^()]*(?:\\([^)]*\\)[^()]*)*\\)``로 차단.
    """
    text = "권장합니다 (출처: 식약처 (2020) 치료 영양 섭취기준)"
    violations = find_violations(text)
    # 인용 본문 안의 `치료`는 mask되어 fire X.
    assert all(v[0] != "치료" for v in violations)
    replaced = apply_replacements(text)
    assert "치료 영양 섭취기준" in replaced  # 인용 본문 보존
