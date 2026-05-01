"""Story 3.2 — 식약처 별표 22종 알레르기 갱신 검증 SOP (R8 + AC #7).

운영자가 분기 1회(3월/6월/9월/12월) 수동 실행하는 SOP — ``app/domain/allergens.py``의
22종 lookup vs ``data/guidelines/mfds-allergens-22.md`` frontmatter ``allergens`` 22
항목 1:1 매칭. 차이 발견 시 비-zero exit + stderr 출력 + 운영자 갱신 PR 안내.

자동 PDF 다운 + 파싱은 OUT — Story 8 polish (식약처 별표 PDF 자동화).

종료 코드:
- 0 — 모든 검증 통과 (lookup 22종 == frontmatter 22종).
- 1 — lookup vs frontmatter 차이 발견 또는 frontmatter 파일 미존재.

stdout 출력 패턴:
- ``[verify_allergy_22] check 1/3: lookup vs guideline frontmatter — OK (22 items match)``
- ``[verify_allergy_22] check 2/3: official URLs printed — see above``
- ``[verify_allergy_22] check 3/3: quarterly manual review reminder — printed``
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Final

import yaml

# ``api/scripts/verify_allergy_22.py`` 또는 ``scripts/verify_allergy_22.py``로부터 sys.path
# 추가 — Docker는 ``/app``이 cwd, 로컬은 repo root 또는 api/.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_API_DIR = _REPO_ROOT / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from app.domain.allergens import KOREAN_22_ALLERGENS  # noqa: E402

# 식약처 공식 URL — research 1.1 / 2.4 인용. 운영자 분기 1회 다운 + 비교 SOP 입력.
MFDS_ALLERGEN_REFERENCE_URLS: Final[dict[str, str]] = {
    "official_law_attachment": (
        "https://www.law.go.kr/LSW/flDownload.do?gubun=&flSeq=42533884&bylClsCd=110201"
    ),
    "foodsafetykorea_guide": (
        "https://www.foodsafetykorea.go.kr/portal/board/boardDetail.do"
        "?menu_no=3120&menu_grp=MENU_NEW01&bbs_no=bbs001&ntctxt_no=1091412"
    ),
    "mfds_pdf": (
        "https://www.mfds.go.kr/brd/m_512/down.do"
        "?brd_id=plc0060&seq=31242&data_tp=A&file_seq=1"
    ),
}

_GUIDELINE_FILE: Final[Path] = (
    _API_DIR / "data" / "guidelines" / "mfds-allergens-22.md"
)


def _load_frontmatter(path: Path) -> dict[str, Any]:
    """``mfds-allergens-22.md`` frontmatter YAML 파싱."""
    if not path.exists():
        print(
            f"[verify_allergy_22] FAILED: guideline file not found: {path}",
            file=sys.stderr,
        )
        sys.exit(1)
    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        print(
            f"[verify_allergy_22] FAILED: frontmatter block missing in {path}",
            file=sys.stderr,
        )
        sys.exit(1)
    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        print(
            f"[verify_allergy_22] FAILED: frontmatter close marker missing in {path}",
            file=sys.stderr,
        )
        sys.exit(1)
    yaml_text = "\n".join(lines[1:end_idx])
    loaded = yaml.safe_load(yaml_text) or {}
    if not isinstance(loaded, dict):
        print(
            f"[verify_allergy_22] FAILED: frontmatter must be a mapping in {path}",
            file=sys.stderr,
        )
        sys.exit(1)
    return loaded


def check_lookup_vs_frontmatter() -> bool:
    """check 1/3 — lookup vs frontmatter ``allergens`` 1:1 매칭."""
    fm = _load_frontmatter(_GUIDELINE_FILE)
    fm_allergens = fm.get("allergens")
    if not isinstance(fm_allergens, list):
        print(
            "[verify_allergy_22] check 1/3: FAILED — frontmatter `allergens` is not a list",
            file=sys.stderr,
        )
        return False

    lookup_set = set(KOREAN_22_ALLERGENS)
    fm_set = set(fm_allergens)

    if lookup_set == fm_set and len(KOREAN_22_ALLERGENS) == len(fm_allergens) == 22:
        # 본 22종은 *정의 순서*를 보존해야 한다(`mfds-allergens-22.md` body 명시 +
        # `app/domain/allergens.py` line 27 invariant). set 비교만으로는 reorder를
        # 잡지 못하므로 list 순서 일치까지 검증.
        if list(KOREAN_22_ALLERGENS) != list(fm_allergens):
            print(
                "[verify_allergy_22] check 1/3: FAILED — set matches but order drift detected",
                file=sys.stderr,
            )
            print(f"  lookup order: {list(KOREAN_22_ALLERGENS)}", file=sys.stderr)
            print(f"  frontmatter order: {list(fm_allergens)}", file=sys.stderr)
            return False
        print(
            f"[verify_allergy_22] check 1/3: lookup vs guideline frontmatter — OK "
            f"({len(KOREAN_22_ALLERGENS)} items match, order preserved)"
        )
        return True

    only_in_lookup = lookup_set - fm_set
    only_in_frontmatter = fm_set - lookup_set
    print(
        "[verify_allergy_22] check 1/3: FAILED — lookup vs frontmatter mismatch",
        file=sys.stderr,
    )
    print(f"  lookup count: {len(KOREAN_22_ALLERGENS)}", file=sys.stderr)
    print(f"  frontmatter count: {len(fm_allergens)}", file=sys.stderr)
    if only_in_lookup:
        print(f"  only in lookup: {sorted(only_in_lookup)}", file=sys.stderr)
    if only_in_frontmatter:
        print(f"  only in frontmatter: {sorted(only_in_frontmatter)}", file=sys.stderr)
    return False


def print_official_urls() -> None:
    """check 2/3 — 식약처 공식 URL 3종 stdout 출력 + 운영자 SOP 안내."""
    print("[verify_allergy_22] check 2/3: official MFDS reference URLs:")
    for key, url in MFDS_ALLERGEN_REFERENCE_URLS.items():
        print(f"  - {key}: {url}")
    print(
        "  운영자 SOP — 위 3 URL 다운로드 후 22종 항목과 비교, 차이 발견 시 "
        "(1) `app/domain/allergens.py` 갱신 PR + "
        "(2) `data/guidelines/mfds-allergens-22.md` frontmatter `allergens` 갱신 PR + "
        "(3) `verify_allergy_22.py` 재실행 통과 확인"
    )


def print_quarterly_reminder() -> None:
    """check 3/3 — 분기 1회 cron 안내."""
    print(
        "[verify_allergy_22] check 3/3: quarterly manual review reminder — "
        "분기 1회 (3월 / 6월 / 9월 / 12월) 운영자 수동 실행 권장. "
        "Story 8 polish 시점에 GHA cron 자동화 검토."
    )


def main() -> int:
    ok = check_lookup_vs_frontmatter()
    print_official_urls()
    print_quarterly_reminder()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
