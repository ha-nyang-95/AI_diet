"""Story 3.8 — 개인정보 처리방침 LangSmith 단락 + version bump 회귀 가드 (AC9).

본 가드는 *PR diff에서 LangSmith 단락 누락이 회귀로 들어오는 케이스* 차단.
NFR-O5(외부 의존 제3자 제공·국외 이전) 정합 — privacy 본문에 LangSmith Inc.
운영 옵저버빌리티 단락이 한·영 양쪽 동기화돼있어야 함.
"""

from __future__ import annotations

from app.domain.legal_documents import CURRENT_VERSIONS, LEGAL_DOCUMENTS


def test_privacy_ko_includes_langsmith_paragraph() -> None:
    """한국어 처리방침 본문에 LangSmith 운영 옵저버빌리티 단락 포함 (AC9 verbatim 핵심)."""
    doc = LEGAL_DOCUMENTS[("privacy", "ko")]
    body = doc.body
    assert "LangSmith Inc." in body
    assert "PII 송신 0" in body
    # 마스킹 PII 카테고리 명시 — 5종 모두 단락에 등재.
    for keyword in ("체중", "신장", "알레르기", "식단 raw text", "사용자 식별자"):
        assert keyword in body, f"missing PII category in privacy_ko: {keyword!r}"


def test_privacy_en_includes_langsmith_paragraph() -> None:
    """영문 처리방침 본문에 LangSmith 운영 옵저버빌리티 단락 포함 — 한·영 동기화."""
    doc = LEGAL_DOCUMENTS[("privacy", "en")]
    body = doc.body
    assert "LangSmith Inc." in body
    assert "zero PII" in body
    # 마스킹 PII 카테고리 영문 표기 — 5종.
    for keyword in ("weight", "height", "allergies", "raw meal text", "user identifiers"):
        assert keyword in body, f"missing PII category in privacy_en: {keyword!r}"


def test_privacy_version_bumped_to_2026_05_04() -> None:
    """``CURRENT_VERSIONS["privacy"]``가 Story 3.8 시점 minor bump 반영 (AC9).

    이전 baseline은 ``"ko-2026-04-28"`` — bump 후 ``"ko-2026-05-04"``. 정확한 값은
    수정될 수 있으나, *2026-04-28 이상의 datetime을 인코딩한 문자열*이어야 한다.
    """
    privacy_version = CURRENT_VERSIONS["privacy"]
    # 직전 baseline ko-2026-04-28보다 *최신* ISO date prefix.
    assert privacy_version >= "ko-2026-05-04", (
        f"privacy version {privacy_version!r} did not bump past ko-2026-04-28 baseline"
    )
    # ``LegalDocument.version`` 필드 자체와 정합.
    assert LEGAL_DOCUMENTS[("privacy", "ko")].version == privacy_version


def test_automated_decision_text_already_referenced_langsmith() -> None:
    """Story 1.4 자동화 의사결정 본문은 이미 LangSmith 명시 — Story 3.8 회귀 0건 가드."""
    doc = LEGAL_DOCUMENTS[("automated-decision", "ko")]
    assert "LangSmith" in doc.body
