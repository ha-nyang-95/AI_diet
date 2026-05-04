"""Story 3.8 — `scripts/upload_eval_dataset.py` 단위 검증 (AC6).

5 케이스(spec verbatim):
- JSON dataset 파일 로드 + 100건 + 4 키 schema 검증.
- ``--dry-run`` → LangSmith mock client 미인스턴스화.
- 정상 실행 → ``client.create_examples`` 1회 호출 + 100건 examples 전달.
- 기존 dataset + examples 존재 + ``--force=False`` → skip(0 return).
- ``LANGSMITH_API_KEY`` 미설정 → ``sys.exit(1)``.

본 모듈은 ``scripts/`` 위치 SOT라 import path가 standard package 외부 — 본 테스트
파일은 ``importlib.util.spec_from_file_location``로 모듈을 로드한다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "upload_eval_dataset.py"
DATASET_PATH = REPO_ROOT / "api" / "tests" / "data" / "korean_foods_100.json"


@pytest.fixture(scope="module")
def upload_module() -> ModuleType:
    """`scripts/upload_eval_dataset.py`를 별 모듈로 로드 — package 외부."""
    spec = importlib.util.spec_from_file_location("upload_eval_dataset", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["upload_eval_dataset"] = module
    spec.loader.exec_module(module)
    return module


def test_load_dataset_returns_100_rows_with_required_schema(upload_module: ModuleType) -> None:
    """``korean_foods_100.json`` SOT 100건 + 4키 schema 검증.

    필수 키: ``input`` / ``expected_canonical`` / ``expected_path`` / ``category``.
    """
    rows = upload_module._load_dataset(DATASET_PATH)
    assert len(rows) == 100
    required = {"input", "expected_canonical", "expected_path", "category"}
    for row in rows:
        assert required <= row.keys()


def test_build_examples_maps_rows_to_langsmith_schema(upload_module: ModuleType) -> None:
    """row → ``{inputs.meal_text, outputs.{canonical,path}, metadata.category}`` 변환 정합."""
    rows = [
        {
            "input": "자장면",
            "expected_canonical": "짜장면",
            "expected_path": "alias",
            "category": "면류",
        }
    ]
    examples = upload_module._build_examples(rows)
    assert len(examples) == 1
    assert examples[0] == {
        "inputs": {"meal_text": "자장면"},
        "outputs": {"canonical": "짜장면", "path": "alias"},
        "metadata": {"category": "면류"},
    }


def test_dry_run_does_not_instantiate_langsmith_client(
    upload_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--dry-run` flag 시 LangSmith Client 미생성 + payload structure stdout 출력."""
    fake_client_class = MagicMock(name="LangSmithClient")
    # 본 스크립트는 ``from langsmith import Client``를 ``main()`` 분기 *내부*에서 import —
    # dry-run 분기는 import 자체에 도달하지 않아야 함. monkeypatch는 모듈 import 후
    # langsmith를 mock해 *만약 호출 시 fail*을 보장.
    monkeypatch.setitem(
        sys.modules,
        "langsmith",
        MagicMock(Client=fake_client_class),
    )

    rc = upload_module.main(
        [
            "--input-path",
            str(DATASET_PATH),
            "--dry-run",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "[dry-run]" in captured.out
    assert "100 examples" in captured.out
    fake_client_class.assert_not_called()


def test_normal_run_calls_create_examples_with_100_rows(
    upload_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """정상 실행 → ``client.create_examples`` 1회 호출 + 100건 examples 전달."""
    fake_dataset = MagicMock()
    fake_dataset.id = "ds-test-1"
    fake_client = MagicMock()
    fake_client.read_dataset.return_value = fake_dataset
    fake_client.list_examples.return_value = iter([])  # 비어있음 → skip 분기 미발동.

    fake_client_class = MagicMock(return_value=fake_client)
    monkeypatch.setitem(
        sys.modules,
        "langsmith",
        MagicMock(Client=fake_client_class),
    )
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls__mock")

    rc = upload_module.main(["--input-path", str(DATASET_PATH)])
    assert rc == 0
    fake_client_class.assert_called_once_with()
    fake_client.create_examples.assert_called_once()
    kwargs = fake_client.create_examples.call_args.kwargs
    assert kwargs["dataset_id"] == "ds-test-1"
    assert len(kwargs["examples"]) == 100
    captured = capsys.readouterr()
    assert "uploaded 100 examples" in captured.out


def test_existing_examples_skip_when_force_false(
    upload_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """기존 dataset + examples 존재 + ``--force=False`` → 0 return + skip log."""
    fake_dataset = MagicMock()
    fake_dataset.id = "ds-test-2"
    fake_client = MagicMock()
    fake_client.read_dataset.return_value = fake_dataset
    fake_client.list_examples.return_value = iter([MagicMock(id="ex-1")])

    fake_client_class = MagicMock(return_value=fake_client)
    monkeypatch.setitem(
        sys.modules,
        "langsmith",
        MagicMock(Client=fake_client_class),
    )
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls__mock")

    rc = upload_module.main(["--input-path", str(DATASET_PATH)])
    assert rc == 0
    fake_client.create_examples.assert_not_called()
    captured = capsys.readouterr()
    # skip log는 stderr.
    assert "skip" in captured.err.lower()


def test_force_flag_bypasses_skip_when_examples_exist(
    upload_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--force`` flag → 기존 examples 존재해도 append (중복 위험 인지 사용)."""
    fake_dataset = MagicMock()
    fake_dataset.id = "ds-test-3"
    fake_client = MagicMock()
    fake_client.read_dataset.return_value = fake_dataset
    fake_client.list_examples.return_value = iter([MagicMock(id="ex-1")])

    fake_client_class = MagicMock(return_value=fake_client)
    monkeypatch.setitem(
        sys.modules,
        "langsmith",
        MagicMock(Client=fake_client_class),
    )
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls__mock")

    rc = upload_module.main(["--input-path", str(DATASET_PATH), "--force"])
    assert rc == 0
    fake_client.create_examples.assert_called_once()


def test_missing_api_key_returns_exit_code_1(
    upload_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``LANGSMITH_API_KEY`` 미설정 + non-dry-run → exit code 1."""
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    rc = upload_module.main(["--input-path", str(DATASET_PATH)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "LANGSMITH_API_KEY" in captured.err


def test_load_dataset_rejects_row_missing_required_keys(
    upload_module: ModuleType, tmp_path: Path
) -> None:
    """schema 위반 row(필수 키 누락) → ``ValueError``."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(
        json.dumps([{"input": "X", "expected_canonical": "Y"}], ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing keys"):
        upload_module._load_dataset(bad_path)


def test_load_dataset_rejects_non_array_root(upload_module: ModuleType, tmp_path: Path) -> None:
    """root가 dict이면 ``ValueError`` — list of row 강제."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps({"rows": []}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        upload_module._load_dataset(bad_path)
