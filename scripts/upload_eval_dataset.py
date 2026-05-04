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

import structlog

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO_ROOT / "api" / "tests" / "data" / "korean_foods_100.json"
DEFAULT_NAME = "balancenote-korean-foods-v1"
DEFAULT_DESC = "한식 100건 음식명 정규화 정확도 회귀 데이터셋 (Story 3.4 T3 KPI 90%)"

_REQUIRED_KEYS: frozenset[str] = frozenset(
    {"input", "expected_canonical", "expected_path", "category"}
)

_log = structlog.get_logger(__name__)


def _load_dataset(path: Path) -> list[dict[str, str]]:
    """JSON 파일 로드 + schema 검증.

    Raises:
        ``FileNotFoundError`` — path 부재.
        ``ValueError`` — JSON malformed / row가 list of dict 형태가 아니거나 row schema 불일치 / 값 type 위반.
    """
    if not path.exists():
        raise FileNotFoundError(f"dataset not found: {path}")

    # CR P10 — UnicodeDecodeError(file이 UTF-8 아님) → ValueError로 변환해 호출자가
    # 단일 ValueError catch로 안내 메시지 일관 처리.
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"dataset must be UTF-8 encoded: {exc}") from exc

    # CR P10 — JSONDecodeError를 ValueError로 변환(docstring 정합 + 호출자 단일
    # except path).
    try:
        rows = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc

    if not isinstance(rows, list):
        raise ValueError(f"dataset root must be JSON array, got {type(rows).__name__}")
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"row {idx} is not a dict: {row!r}")
        missing = _REQUIRED_KEYS - row.keys()
        if missing:
            raise ValueError(f"row {idx} missing keys {sorted(missing)}: {row!r}")
        # CR P10 — value type 검증. LangSmith 보드/eval 비교가 string-equal 기반이라
        # ``None``/list/dict 같은 비-string 값이 silently 업로드되면 회귀 baseline이
        # 깨짐(eval false-negative). 4개 키 모두 비-empty string 강제.
        for key in _REQUIRED_KEYS:
            value = row[key]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"row {idx} field {key!r} must be non-empty string: {value!r}"
                )
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

    CR P5 — 종전 ``except Exception`` blanket catch는 transient(timeout/5xx/auth
    fail)도 미존재로 오인하여 *중복 dataset 생성*을 유발. ``LangSmithNotFoundError``
    만 catch해 미존재 → create 분기, 그 외 예외는 propagate해 운영자에게 명확한
    incident 신호 노출.
    """
    try:
        from langsmith.utils import LangSmithNotFoundError  # noqa: PLC0415
    except ImportError:
        # 0.7.x 이전/이후 SDK rename 안전망 — utils 모듈 미공개 시 generic 예외로 fallback.
        # ``langsmith>=0.7.31,<0.9`` 상한 하에서는 도달하지 않지만 silent break 차단용.
        LangSmithNotFoundError = Exception  # type: ignore[assignment, misc]

    try:
        return client.read_dataset(dataset_name=name)
    except LangSmithNotFoundError:
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
        # CR P11 — print(stderr) → structlog INFO 이벤트(spec AC6 ``eval.upload.skipped``
        # 정합). stderr는 사용자 즉시 식별용으로 유지(터미널 가시성).
        _log.info("eval.upload.skipped", dataset=name, reason="examples_exist_no_force")
        print(
            f"[skip] dataset {name!r} already has examples; use --force to append",
            file=sys.stderr,
        )
        return 0

    if existing and force:
        # CR P15 — ``--force``는 dedupe 없이 append만 함 → 기존 100건 + 신규 100건
        # = 200건 dataset. 회귀 baseline 오염 위험. stderr WARNING + structlog event
        # 둘 다 emit해 비대화형(CI) / 대화형(터미널) 양쪽에서 인지 가능.
        _log.warning(
            "eval.upload.force_append_no_dedupe",
            dataset=name,
            existing_examples=True,
            warning="기존 examples 존재 — append만 수행, dedupe 없음(중복 row 위험)",
        )
        print(
            f"[warn] --force: {name!r} already has examples — appending without dedupe "
            f"(중복 row가 보드에 누적됩니다. 의도와 일치하는지 확인하세요)",
            file=sys.stderr,
        )

    client.create_examples(dataset_id=dataset.id, examples=examples)
    _log.info("eval.upload.created", dataset=name, examples_count=len(examples))
    return len(examples)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-name", default=DEFAULT_NAME)
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--description", default=DEFAULT_DESC)
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "기존 dataset에 examples 존재해도 추가 append (dedupe 없음 — 중복 row "
            "위험. 회귀 baseline 오염 가능. 기본 skip)"
        ),
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
        _log.info(
            "eval.upload.dry_run",
            dataset=args.dataset_name,
            examples_count=len(examples),
        )
        print(
            f"[dry-run] would upload {len(examples)} examples to {args.dataset_name!r} "
            f"(description={args.description!r})"
        )
        # 첫 행만 표시 — 100건 전체 dump는 stdout 폭주 회피.
        if examples:
            print(f"[dry-run] sample example: {json.dumps(examples[0], ensure_ascii=False)}")
        return 0

    api_key = os.environ.get("LANGSMITH_API_KEY", "")
    # CR P10 — 종전 ``not os.environ.get("LANGSMITH_API_KEY")``는 빈 문자열만 거름.
    # whitespace-only 값(``"   "``)이 truthy → SDK가 401 cryptic fail.
    if not api_key.strip():
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
