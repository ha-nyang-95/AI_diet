"""Story 3.8 — 한식 100건 → LangSmith Dataset 업로드 (AC6 / NFR-O3).

사용법:
    LANGSMITH_API_KEY=... python scripts/upload_eval_dataset.py
    LANGSMITH_API_KEY=... python scripts/upload_eval_dataset.py --force
    python scripts/upload_eval_dataset.py --dry-run

idempotent — 같은 이름 dataset이 이미 examples를 가지면 skip.

Story 3.4 ``korean_foods_100.json`` SOT를 LangSmith Dataset
``balancenote-korean-foods-v1``로 변환 + 업로드. 영업/외주 client별 회귀 평가 보드의
*고정 baseline*. ``balancenote-korean-foods-v1`` dataset은 LangSmith ``evaluate`` 또는
PR ``langsmith-eval-regression`` job(`.github/workflows/ci.yml`)에서 회귀 정확도
측정에 재사용.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO_ROOT / "api" / "tests" / "data" / "korean_foods_100.json"
DEFAULT_NAME = "balancenote-korean-foods-v1"
DEFAULT_DESC = "한식 100건 음식명 정규화 정확도 회귀 데이터셋 (Story 3.4 T3 KPI 90%)"

_REQUIRED_KEYS: frozenset[str] = frozenset(
    {"input", "expected_canonical", "expected_path", "category"}
)


def _load_dataset(path: Path) -> list[dict[str, str]]:
    """JSON 파일 로드 + schema 검증.

    Raises:
        ``FileNotFoundError`` — path 부재.
        ``ValueError`` — row가 list of dict 형태가 아니거나 row schema 불일치.
    """
    if not path.exists():
        raise FileNotFoundError(f"dataset not found: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"dataset root must be JSON array, got {type(rows).__name__}")
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"row {idx} is not a dict: {row!r}")
        missing = _REQUIRED_KEYS - row.keys()
        if missing:
            raise ValueError(f"row {idx} missing keys {sorted(missing)}: {row!r}")
    return rows


def _build_examples(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """LangSmith Example schema(``inputs`` / ``outputs`` / ``metadata``)로 변환."""
    return [
        {
            "inputs": {"meal_text": r["input"]},
            "outputs": {
                "canonical": r["expected_canonical"],
                "path": r["expected_path"],
            },
            "metadata": {"category": r["category"]},
        }
        for r in rows
    ]


def _resolve_dataset(client: Any, name: str, description: str) -> Any:
    """dataset name으로 read 시도 → 미존재 시 신규 create.

    LangSmith SDK는 read_dataset이 미존재 시 LangSmithNotFoundError를 raise하지만,
    SDK 버전별 예외 클래스가 달라 ``Exception`` catch 후 create fallback.
    """
    try:
        return client.read_dataset(dataset_name=name)
    except Exception:
        return client.create_dataset(dataset_name=name, description=description)


def _upload(
    client: Any,
    name: str,
    description: str,
    examples: list[dict[str, Any]],
    *,
    force: bool,
) -> int:
    """dataset 생성 또는 read fallback + examples 삽입.

    Returns:
        삽입된 example 개수. 기존 examples 존재 + force=False → 0.
    """
    dataset = _resolve_dataset(client, name, description)
    existing = list(client.list_examples(dataset_id=dataset.id, limit=1))
    if existing and not force:
        print(
            f"[skip] dataset {name!r} already has examples; use --force to append",
            file=sys.stderr,
        )
        return 0
    client.create_examples(dataset_id=dataset.id, examples=examples)
    return len(examples)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-name", default=DEFAULT_NAME)
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--description", default=DEFAULT_DESC)
    parser.add_argument(
        "--force",
        action="store_true",
        help="기존 dataset에 examples 존재해도 추가 append (중복 위험 — 기본 skip)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="LangSmith 호출 0회 — payload structure만 stdout 출력",
    )
    args = parser.parse_args(argv)

    rows = _load_dataset(args.input_path)
    examples = _build_examples(rows)

    if args.dry_run:
        print(
            f"[dry-run] would upload {len(examples)} examples to {args.dataset_name!r} "
            f"(description={args.description!r})"
        )
        # 첫 행만 표시 — 100건 전체 dump는 stdout 폭주 회피.
        if examples:
            print(f"[dry-run] sample example: {json.dumps(examples[0], ensure_ascii=False)}")
        return 0

    if not os.environ.get("LANGSMITH_API_KEY"):
        print(
            "LANGSMITH_API_KEY required — set in env before run",
            file=sys.stderr,
        )
        return 1

    # langsmith는 dry-run 분기와 import boundary를 분리 — `--dry-run`만 쓰는 사용자가
    # langsmith SDK 미설치 환경에서도 본 스크립트를 동작시킬 수 있게 한다.
    from langsmith import Client

    client = Client()
    inserted = _upload(
        client,
        args.dataset_name,
        args.description,
        examples,
        force=args.force,
    )
    if inserted == 0:
        print(f"[ok] no examples inserted (skipped) — dataset {args.dataset_name!r}")
    else:
        print(f"[ok] uploaded {inserted} examples to {args.dataset_name!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
