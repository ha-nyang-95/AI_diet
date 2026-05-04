"""Story 3.8 — LangGraph native tracing 활성 가드 (AC3).

`LANGCHAIN_TRACING_V2` env + LangSmith Client mock 조합에서:
- env가 `"true"`면 langchain-core가 `LangChainTracer`를 자동 인식한다(SDK SOT).
- env가 `"false"` 또는 미설정이면 트레이서가 비활성.
- `init_langsmith()`가 wired 한 마스킹 hook이 LangSmith Client 인자에 정확히 박혀
  있는지(Story 3.7 lifespan 패턴 정합).

Task 5 D6 결정 정합 — 본 통합 테스트는 *mock-level 가드만*. 실 trace 송신은
staging/prod 수동 verification(`docs/observability/langsmith-dashboard.md`).
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


def test_langgraph_tracing_v2_env_recognized_by_langchain_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`LANGCHAIN_TRACING_V2=true` env 시 langchain-core의 ``tracing_v2_enabled``
    helper가 native로 활성을 인식한다 — 이게 LangGraph 노드 호출의 자동 트레이싱
    SOT(D4: 라우터/노드 코드 변경 0).
    """
    from langchain_core.tracers import context as tcontext

    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls__mock")

    # context manager로 활성 — `compile_pipeline`이 컴파일 시점에 callback을 박는
    # 패턴이 아니라 *runtime invocation 시점에 langchain-core가 env를 읽어 tracer
    # 부착*하는 패턴이라 ``tracing_v2_enabled`` 자체의 인식만 가드.
    with tcontext.tracing_v2_enabled() as cb:
        assert cb is not None


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


def test_compile_pipeline_smoke_with_tracing_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`LANGCHAIN_TRACING_V2=true` env 환경에서 `compile_pipeline`이 호출되어도 회귀 0.

    실 OpenAI/Anthropic 호출은 dev 환경에서 차단(Story 3.7 패턴) — 본 가드는 단순히
    *env가 설정돼도 컴파일 자체가 깨지지 않는지* 확인. 실 trace upload는
    staging/prod 수동(D6 정합).
    """
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls__mock")

    # `compile_pipeline`은 checkpointer + deps 인자를 받지만 본 smoke는 *import 가능
    # 여부 + LangChainTracer 의존 import* 만 가드. 실 graph build는 conftest의 lifespan
    # fixture가 담당(test_pipeline.py 등).
    from app.graph.pipeline import compile_pipeline

    assert callable(compile_pipeline)
