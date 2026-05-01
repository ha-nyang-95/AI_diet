"""Story 3.2 — ``verify_allergy_22.py`` 통합 테스트 (AC #7).

3 케이스:
  1. lookup vs frontmatter 일치 → exit 0 + stdout *"OK (22 items match)"*.
  2. frontmatter ``allergens`` 누락(임시 파일 + monkeypatch) → exit 1 + stderr 차이.
  3. ``KOREAN_22_ALLERGENS`` lookup 차이(monkeypatch) → exit 1 + 차이 항목 출력.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

# scripts/ 모듈 import — sys.path 추가 (Story 3.1 패턴 정합).
_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _import_verify_allergy_22() -> ModuleType:
    sys.modules.pop("verify_allergy_22", None)
    import verify_allergy_22  # type: ignore[import-not-found]

    module: ModuleType = verify_allergy_22
    return module


def test_verify_allergy_22_lookup_matches_frontmatter(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """현 baseline lookup + frontmatter 22종 일치 → exit 0."""
    va = _import_verify_allergy_22()
    exit_code = va.main()
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "check 1/3" in out
    assert "OK (22 items match)" in out
    assert "check 2/3" in out
    assert "official_law_attachment" in out
    assert "check 3/3" in out
    assert "quarterly" in out.lower()


def test_verify_allergy_22_frontmatter_allergens_missing_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """frontmatter ``allergens`` 누락(빈 list) → exit 1 + stderr 차이 출력."""
    # 임시 frontmatter 파일 — allergens 항목 없음.
    bad_md = tmp_path / "mfds-allergens-22.md"
    bad_md.write_text(
        "---\n"
        "source: MFDS\n"
        "source_id: MFDS-ALLERGEN-22\n"
        "authority_grade: A\n"
        "topic: allergen\n"
        "applicable_health_goals: []\n"
        "published_year: 2024\n"
        'doc_title: "식품 등의 표시기준 별표 — 알레르기 유발물질 22종"\n'
        "allergens: []\n"
        "---\n\n"
        "본문\n",
        encoding="utf-8",
    )
    va = _import_verify_allergy_22()
    monkeypatch.setattr(va, "_GUIDELINE_FILE", bad_md)

    exit_code = va.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "FAILED" in captured.err
    assert "lookup count: 22" in captured.err
    assert "frontmatter count: 0" in captured.err


def test_verify_allergy_22_lookup_extra_item_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """lookup에 3개 추가 (25개) — frontmatter 22 vs lookup 25 차이 → exit 1."""
    va = _import_verify_allergy_22()
    extended = (*va.KOREAN_22_ALLERGENS, "신규알레르겐1", "신규알레르겐2", "신규알레르겐3")
    monkeypatch.setattr(va, "KOREAN_22_ALLERGENS", extended)

    exit_code = va.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "FAILED" in captured.err
    # only_in_lookup 항목 출력 확인.
    assert "신규알레르겐1" in captured.err or "only in lookup" in captured.err
