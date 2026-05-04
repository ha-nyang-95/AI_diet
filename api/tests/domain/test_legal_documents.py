"""Story 3.8 — 개인정보 처리방침 LangSmith 단락 + version bump 회귀 가드 (AC9).

본 가드는 *PR diff에서 LangSmith 단락 누락이 회귀로 들어오는 케이스* 차단.
NFR-O5(외부 의존 제3자 제공·국외 이전) 정합 — privacy 본문에 LangSmith Inc.
운영 옵저버빌리티 단락이 한·영 양쪽 동기화돼있어야 함.

CR DN-1 / P16 — version SOT를 doc-key별 dict로 분리. privacy/sensitive_personal_info
만 ``ko-2026-05-04``으로 bump, 나머지 4개 문서(disclaimer/terms/automated-decision)는
baseline ``ko-2026-04-28`` 유지. 본 가드가 ``CURRENT_VERSIONS`` 분리 회귀를 차단.
"""

from __future__ import annotations

from app.domain.legal_documents import CURRENT_VERSIONS, LEGAL_DOCUMENTS

PRIVACY_VERSION_AFTER_STORY_3_8_KO = "ko-2026-05-04"
BASELINE_VERSION_KO = "ko-2026-04-28"


def test_privacy_ko_includes_langsmith_paragraph() -> None:
    """한국어 처리방침 본문에 LangSmith 운영 옵저버빌리티 단락 포함 (AC9 verbatim 핵심)."""
    doc = LEGAL_DOCUMENTS[("privacy", "ko")]
    body = doc.body
    assert "LangSmith Inc." in body
    assert "PII 송신 0" in body
    # 마스킹 PII 카테고리 명시 — 5종 모두 단락에 등재.
    for keyword in ("체중", "신장", "알레르기", "식단 raw text", "사용자 식별자"):
        assert keyword in body, f"missing PII category in privacy_ko: {keyword!r}"


def test_privacy_ko_includes_processing_outsourcing_classification() -> None:
    """CR DN-3 — 처리 위탁 분류 명시 + 거부 권리 후속 약속 텍스트 회귀 가드.

    종전 본문은 "제3자 제공: 없음" 옆에 LangSmith Inc. 수령자를 같은 섹션에 나열해
    PIPA 정합 모호성 + 거부 UX 미구현 약속 leak. 본 가드는 (a) "처리 위탁(국외)"
    별도 분류 + (b) 거부 권리는 Story 5.1 / 8.4 후속에서 제공 약속 텍스트가 본문에
    유지되는지 확인.
    """
    body = LEGAL_DOCUMENTS[("privacy", "ko")].body
    # (a) 위탁 분류 명시.
    assert "처리 위탁" in body, "처리 위탁 분류 섹션 누락 — DN-3 회귀"
    # (b) 거부 권리 후속 약속 — 설정 화면 스토리 참조.
    assert "거부 권리" in body, "거부 권리 텍스트 누락 — DN-3 회귀"
    assert "Story 5.1" in body or "Story 8.4" in body, "거부 UX 후속 스토리 참조 누락 — DN-3 회귀"


def test_privacy_en_includes_langsmith_paragraph() -> None:
    """영문 처리방침 본문에 LangSmith 운영 옵저버빌리티 단락 포함 — 한·영 동기화."""
    doc = LEGAL_DOCUMENTS[("privacy", "en")]
    body = doc.body
    assert "LangSmith Inc." in body
    assert "zero PII" in body
    # 마스킹 PII 카테고리 영문 표기 — 5종.
    for keyword in ("weight", "height", "allergies", "raw meal text", "user identifiers"):
        assert keyword in body, f"missing PII category in privacy_en: {keyword!r}"


def test_privacy_en_includes_processing_outsourcing_classification() -> None:
    """CR DN-3 영문 동기화 — 처리 위탁 분류 + 거부 권리 후속 약속."""
    body = LEGAL_DOCUMENTS[("privacy", "en")].body
    assert "Outsourced processing" in body, "Outsourced processing 분류 섹션 누락 — DN-3 회귀"
    assert "Right to decline" in body, "Right to decline 텍스트 누락 — DN-3 회귀"
    assert "Story 5.1" in body or "Story 8.4" in body, "거부 UX 후속 스토리 참조 누락 — DN-3 회귀"


def test_privacy_version_bumped_to_2026_05_04_exact() -> None:
    """CR P13 — privacy version 정확 일치 가드(lex 비교 폐지).

    종전: ``privacy_version >= "ko-2026-05-04"`` 문자열 lex 비교는 ``"ko-2026-05-9"`` <
    ``"ko-2026-05-10"`` 같은 latent 버그(같은 자릿수 보장이 깨질 때). 본 가드는 *정확
    일치* — Story 3.8 시점 SOT는 단일 값.
    """
    privacy_version = CURRENT_VERSIONS["privacy"]
    assert privacy_version == PRIVACY_VERSION_AFTER_STORY_3_8_KO, (
        f"privacy version {privacy_version!r} != "
        f"{PRIVACY_VERSION_AFTER_STORY_3_8_KO!r} — Story 3.8 bump 회귀"
    )
    # ``LegalDocument.version`` 필드 자체와 정합.
    assert LEGAL_DOCUMENTS[("privacy", "ko")].version == privacy_version


def test_sensitive_personal_info_version_shares_privacy_bump() -> None:
    """CR P16 — ``sensitive_personal_info`` 키는 privacy 본문의 *민감정보* 단락을
    공유하므로 동일 version으로 bump되어야 함(PIPA 23조 별도 동의 분리 의무 정합).
    """
    assert CURRENT_VERSIONS["sensitive_personal_info"] == PRIVACY_VERSION_AFTER_STORY_3_8_KO


def test_unchanged_docs_keep_baseline_version() -> None:
    """CR DN-1 / P16 — disclaimer / terms / automated-decision 본문 미변경이라
    baseline ``ko-2026-04-28`` 유지. 종전 단일 ``_VERSION_KO`` 공유 SOT는 privacy
    bump를 4개 문서에 전파해 Story 1.4 ``ConsentVersionMismatchError``가 모든 기존
    사용자에게 점화될 위험 — 본 가드가 회귀를 차단.
    """
    assert CURRENT_VERSIONS["disclaimer"] == BASELINE_VERSION_KO, (
        "disclaimer 본문 미변경 — baseline 유지여야 함(기존 사용자 재동의 회귀)"
    )
    assert CURRENT_VERSIONS["terms"] == BASELINE_VERSION_KO, (
        "terms 본문 미변경 — baseline 유지여야 함"
    )
    assert CURRENT_VERSIONS["automated-decision"] == BASELINE_VERSION_KO, (
        "automated-decision 본문 미변경 — baseline 유지여야 함"
    )
    # LegalDocument 항목 자체도 baseline.
    assert LEGAL_DOCUMENTS[("disclaimer", "ko")].version == BASELINE_VERSION_KO
    assert LEGAL_DOCUMENTS[("terms", "ko")].version == BASELINE_VERSION_KO
    assert LEGAL_DOCUMENTS[("automated-decision", "ko")].version == BASELINE_VERSION_KO


def test_automated_decision_text_already_referenced_langsmith() -> None:
    """Story 1.4 자동화 의사결정 본문은 이미 LangSmith 명시 — Story 3.8 회귀 0건 가드."""
    doc = LEGAL_DOCUMENTS[("automated-decision", "ko")]
    assert "LangSmith" in doc.body
