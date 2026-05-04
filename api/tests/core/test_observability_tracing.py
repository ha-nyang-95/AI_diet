"""Story 3.8 — LangGraph native tracing 활성 가드 (AC3).

`LANGCHAIN_TRACING_V2` env + LangSmith Client mock 조합에서:
- env가 `"true"`면 langchain-core가 `LangChainTracer`를 자동 인식한다(SDK SOT).
- env가 `"false"` 또는 미설정이면 트레이서가 비활성.
- `init_langsmith()`가 wired 한 마스킹 hook이 LangSmith Client 인자에 정확히 박혀
  있는지(Story 3.7 lifespan 패턴 정합).

Task 5 D6 결정 정합 — 본 통합 테스트는 *mock-level 가드만*. 실 trace 송신은
staging/prod 수동 verification(`docs/observability/langsmith-dashboard.md`).

CR P9 — 종전 vacuous 테스트 2건(``test_compile_pipeline_smoke_with_tracing_mocked``
``assert callable``, ``test_langgraph_tracing_v2_env_recognized_by_langchain_core``
SDK 자체 검증) 폐지. 본 모듈은 *마스킹 hook wired 가드 + tracer 클래스 import 가능
가드*만 유지(BalanceNote 통합 정합).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.config import settings as _settings
from app.core.observability import (
    init_langsmith,
    mask_run_inputs,
    mask_run_outputs,
    reset_langsmith_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_observability_state() -> None:
    """CR P8 — env/singleton leak 방지(test pollution 차단)."""
    yield
    reset_langsmith_for_tests()


def test_langgraph_tracing_v2_disabled_when_env_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`LANGCHAIN_TRACING_V2=false`이면 LangSmith Client init 자체가 graceful skip —
    LangSmith 송신 0(NFR-O5 정합)."""
    monkeypatch.setattr(_settings, "langchain_tracing_v2", False)
    monkeypatch.setattr(_settings, "langsmith_api_key", "ls__test")
    reset_langsmith_for_tests()

    client = init_langsmith()
    assert client is None


def test_init_langsmith_wires_masking_hooks_to_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """정상 init 분기에서 ``Client(hide_inputs=mask_run_inputs, hide_outputs=mask_run_outputs)``
    호출 인자가 정확히 wired 됐는지 — LangSmith trace에 PII가 노출되는 회귀 차단
    핵심 가드(NFR-O2).
    """
    from app.core import observability

    monkeypatch.setattr(_settings, "langchain_tracing_v2", True)
    monkeypatch.setattr(_settings, "langsmith_api_key", "ls__test")

    fake_client = MagicMock(name="FakeLangSmithClient")
    fake_class = MagicMock(return_value=fake_client)
    monkeypatch.setattr(observability, "Client", fake_class)
    reset_langsmith_for_tests()

    init_langsmith()

    fake_class.assert_called_once()
    kwargs = fake_class.call_args.kwargs
    assert kwargs["api_key"] == "ls__test"
    assert kwargs["hide_inputs"] is mask_run_inputs
    assert kwargs["hide_outputs"] is mask_run_outputs


def test_langchain_tracer_class_importable() -> None:
    """CR P9 — vacuous ``assert callable`` 교체. LangGraph가 자동 부착하는
    ``LangChainTracer`` 클래스가 langchain-core SOT에서 import 가능한지 가드 —
    SDK upstream rename/이동을 즉시 감지(현 ``langsmith>=0.7.31,<0.9`` + langchain-core
    안정 buffer 하에서는 통과).
    """
    from langchain_core.tracers import LangChainTracer

    assert isinstance(LangChainTracer, type), (
        "LangChainTracer는 langchain-core 1.x SOT 클래스 — rename 시 본 가드가 "
        "ImportError로 즉시 실패해 wiring 패턴 점검 트리거."
    )
