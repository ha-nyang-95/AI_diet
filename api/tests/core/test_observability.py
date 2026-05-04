"""Story 3.8 — `app.core.observability` 마스킹 hook + init 단위 검증 (AC1, AC2, AC7).

NFR-S5 마스킹 룰셋이 Sentry SOT(``app.core.sentry._MASKED_KEYS``)와 합집합인지 +
LangGraph state 신규 키(``weight_kg`` / ``allergies`` / ``feedback`` 등)가 빠짐없이
redact 되는지를 모두 가드. ``mask_run_inputs`` / ``mask_run_outputs``는 *원본 dict
미수정* + None/빈 dict graceful 처리 + list of dict 재귀 순회를 강제한다.

또한 ``init_langsmith()``의 3 분기(disabled / misconfigured / 정상 init)를 monkeypatch
+ structlog ``capture_logs`` 로 검증.
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import MagicMock

import pytest
import structlog
from structlog.testing import capture_logs

from app.core import observability as observability_module
from app.core.config import settings as _settings
from app.core.observability import (
    _LANGSMITH_MASKED_KEYS,
    _MASK_PLACEHOLDER,
    get_langsmith_client,
    init_langsmith,
    mask_run_inputs,
    mask_run_outputs,
    reset_langsmith_for_tests,
)
from app.core.sentry import _MASKED_KEYS as _SENTRY_MASKED_KEYS


@pytest.fixture(autouse=True)
def _reset_structlog_for_capture_logs() -> None:
    """``capture_logs()``는 ``cache_logger_on_first_use=True`` config로 한 번
    bind된 logger를 우회하지 못한다. ``test_main_lifespan.py``가 먼저 돌면 여기서
    ``app.core.observability.log``이 dev console renderer로 캐시된 채 ``capture_logs``
    의 LogCapture 처리기 교체를 무시 → 본 테스트의 event 단언 0건 회귀.

    Fix: 각 테스트 전에 ``structlog.reset_defaults()``로 cache 무효화 + 모듈 ``log``
    재바인딩. 본 fixture autouse라 테스트 함수에 인자 추가 불요.
    """
    structlog.reset_defaults()
    observability_module.log = structlog.get_logger(observability_module.__name__)


def test_mask_run_inputs_redacts_top_level_raw_text() -> None:
    """top-level ``raw_text`` 키 → ``"***"`` 치환(Sentry 키셋 합집합 정합)."""
    out = mask_run_inputs({"raw_text": "비밀 식단 텍스트"})
    assert out == {"raw_text": _MASK_PLACEHOLDER}


def test_mask_run_inputs_redacts_meal_text_alias() -> None:
    """Story 3.8 smoke v3 incident 회귀 가드 — ``meal_text``(``raw_text`` 변형 키)도 redact.

    production은 LangGraph state ``raw_text`` 키로만 박혀 마스킹되지만, 외부 helper /
    @traceable wrapping 함수가 ``meal_text`` 인자명을 쓰면 LangSmith trace inputs에
    raw 식단 본문이 노출됨 — 본 가드가 차단.
    """
    out = mask_run_inputs({"meal_text": "삼겹살 200g + 김치 + 쌀밥 1공기"})
    assert out == {"meal_text": _MASK_PLACEHOLDER}


def test_mask_run_inputs_redacts_nested_user_profile_fields() -> None:
    """nested ``user_profile.weight_kg`` / ``height_cm`` / ``allergies`` 모두 redact.

    LangGraph state ``UserProfileSnapshot``에 미포함된 ``name`` 같은 키는 통과 —
    keyset 매칭 정확성 가드(``_LANGSMITH_EXTRA_KEYS`` 외 키는 노출 OK).
    """
    out = mask_run_inputs(
        {
            "user_profile": {
                "weight_kg": 70,
                "height_cm": 175,
                "allergies": ["복숭아", "땅콩"],
                "name": "Hwan",
                "age": 30,
            }
        }
    )
    assert out == {
        "user_profile": {
            "weight_kg": _MASK_PLACEHOLDER,
            "height_cm": _MASK_PLACEHOLDER,
            "allergies": _MASK_PLACEHOLDER,
            "name": "Hwan",
            "age": 30,
        }
    }


def test_mask_run_inputs_redacts_parsed_items_array() -> None:
    """``parsed_items`` 키 dict 매칭 — 전체 list가 ``"***"``로 치환.

    LangGraph state ``parsed_items``는 list of FoodItem dict라 *키 매칭만으로*
    상위 redact가 되어야 하위 ``name`` / ``confidence`` 등 PII 식단 정보 동시
    차단(NFR-S5 conservative).
    """
    out = mask_run_inputs(
        {
            "parsed_items": [
                {"name": "삼겹살", "confidence": 0.9},
                {"name": "김치", "confidence": 0.95},
            ],
            "meal_id": "uuid-1234",
        }
    )
    assert out["parsed_items"] == _MASK_PLACEHOLDER
    assert out["meal_id"] == "uuid-1234"


def test_mask_run_inputs_redacts_feedback_dict() -> None:
    """``feedback`` 키 전체 dict redact — Dev Notes #3 D2 정합.

    ``feedback.text`` nested 필드를 부모 path 추적 없이 보호하기 위해 ``feedback``
    키 자체를 ``_LANGSMITH_MASKED_KEYS`` 등재. citation/macro 카드는 LangSmith
    보드에서 노출 손실되지만 영업 데모는 노드 latency·cost 중심이라 trade-off OK.
    """
    out = mask_run_inputs(
        {
            "feedback": {
                "text": "한국 식단 평가 본문...",
                "citations": [{"doc_id": "kdri-2020-1"}],
                "macros": {"protein_g": 30},
            }
        }
    )
    assert out == {"feedback": _MASK_PLACEHOLDER}


def test_mask_run_inputs_passes_non_pii_fields() -> None:
    """``meal_id`` / ``final_fit_score`` / ``phase`` 등 비-PII 키 통과 — LangSmith
    보드 가시성을 위해 노출되어야 하는 운영 필드(epic line 707 정합)."""
    inp = {
        "meal_id": "uuid-abcd",
        "user_id": "user-001",
        "final_fit_score": 62,
        "phase": "evaluate_fit",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = mask_run_inputs(inp)
    assert out == inp


def test_mask_run_inputs_does_not_mutate_original() -> None:
    """원본 dict 변경 없음 — LangSmith hook은 신규 dict를 반환해야 한다.

    side-effect 있는 마스킹은 콜백 호출자(LangSmith client SDK)가 원본 참조를
    이후 다른 hook(Sentry 등)에 그대로 넘길 때 *redacted view*가 leak 가능.
    sentry hook과 별 시그니처를 가지는 핵심 사유(observability.py docstring 정합).
    """
    original = {
        "raw_text": "비밀",
        "user_profile": {"weight_kg": 70},
        "parsed_items": [{"name": "삼겹살"}],
    }
    snapshot = copy.deepcopy(original)
    mask_run_inputs(original)
    assert original == snapshot


def test_mask_run_inputs_handles_empty_dict() -> None:
    """빈 dict 입력 → 빈 dict 반환 (graceful 가드)."""
    assert mask_run_inputs({}) == {}


def test_mask_run_inputs_handles_none_input() -> None:
    """``None`` 입력 → 빈 dict 반환 — LangSmith 콜백 시그니처 기대값 정합."""
    assert mask_run_inputs(None) == {}


def test_mask_run_inputs_handles_list_of_dicts_recursively() -> None:
    """``messages`` 키 dict 매칭 — 상위 redact(Sentry SOT 합집합 정합).

    LLM 호출 boundary 패턴(content / messages / system / user_prompt)은 sentry
    SOT에 이미 박힘 — 합집합으로 LangSmith hook도 동일 redact.
    """
    out = mask_run_inputs(
        {
            "messages": [
                {"role": "user", "content": "secret"},
                {"role": "assistant", "content": "leaked"},
            ]
        }
    )
    assert out == {"messages": _MASK_PLACEHOLDER}


def test_mask_run_outputs_uses_same_keyset() -> None:
    """``mask_run_outputs``는 ``mask_run_inputs``와 동일 키셋·동작."""
    payload: dict[str, Any] = {
        "feedback_text": "본문",
        "weight_kg": 70,
        "meal_id": "uuid-1",
    }
    out_in = mask_run_inputs(dict(payload))
    out_out = mask_run_outputs(dict(payload))
    assert out_in == out_out
    assert out_out == {
        "feedback_text": _MASK_PLACEHOLDER,
        "weight_kg": _MASK_PLACEHOLDER,
        "meal_id": "uuid-1",
    }


def test_masked_keys_includes_sentry_keyset() -> None:
    """``_LANGSMITH_MASKED_KEYS``는 Sentry SOT 키셋의 *상위 집합* — Sentry 측 키
    추가 시 LangSmith hook도 자동 redact(NFR-O2 1지점 SOT 정합).

    Sentry 키 제거 PR이 LangSmith에서도 자동 제거되는 결합도 — 본 가드가
    합집합 회귀를 잡는다(``test_observability_tracing.py`` 동작 가드와 분리).
    """
    assert _SENTRY_MASKED_KEYS <= _LANGSMITH_MASKED_KEYS
    # LangGraph state PII 추가 키 8건이 모두 포함됐는지(Dev Notes #2 D1).
    extras = {
        "weight_kg",
        "height_cm",
        "allergies",
        "parsed_items",
        "food_items",
        "clarification_options",
        "feedback_text",
        "feedback",
    }
    assert extras <= _LANGSMITH_MASKED_KEYS


def test_init_langsmith_disabled_when_tracing_v2_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``settings.langchain_tracing_v2 is False`` → ``None`` return + INFO 로그.

    로컬 dev 디폴트 흐름 — LangSmith 송신 0(NFR-O5).
    """
    monkeypatch.setattr(_settings, "langchain_tracing_v2", False)
    monkeypatch.setattr(_settings, "langsmith_api_key", "ls__present")
    reset_langsmith_for_tests()

    with capture_logs() as cap:
        client = init_langsmith()
    assert client is None
    assert get_langsmith_client() is None
    events = [entry.get("event") for entry in cap]
    assert "observability.langsmith.disabled" in events


def test_init_langsmith_misconfigured_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``tracing_v2=True`` + 빈 API key → WARNING + ``None`` return (config 모순 graceful)."""
    monkeypatch.setattr(_settings, "langchain_tracing_v2", True)
    monkeypatch.setattr(_settings, "langsmith_api_key", "")
    reset_langsmith_for_tests()

    with capture_logs() as cap:
        client = init_langsmith()
    assert client is None
    warning_events = [entry.get("event") for entry in cap if entry.get("log_level") == "warning"]
    assert "observability.langsmith.misconfigured" in warning_events


def test_init_langsmith_wires_global_client_for_native_tracing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``init_langsmith()`` 정상 분기 후 ``langsmith.run_trees._CLIENT`` +
    ``langsmith._internal._context._GLOBAL_CLIENT``에 우리 masked client가 박혀야
    한다. 두 변수가 비어있으면 LangChain native tracing이 *hide_inputs/outputs
    없는 default Client*를 자체 생성 → 마스킹 hook 우회 + raw PII 송신 회귀.

    Story 3.8 smoke verification에서 초기 fix(Client 인스턴스만 만들고 끝)는
    ``@traceable``이 별도 default client를 만들면서 마스킹 우회된 incident — 본
    가드가 그 회귀를 차단.
    """
    import langsmith._internal._context as ls_context
    import langsmith.run_trees as ls_run_trees

    from app.core import observability

    monkeypatch.setattr(_settings, "langchain_tracing_v2", True)
    monkeypatch.setattr(_settings, "langsmith_api_key", "ls__test")

    fake_client_instance = MagicMock(name="FakeMaskedClient")
    fake_client_class = MagicMock(return_value=fake_client_instance)
    monkeypatch.setattr(observability, "Client", fake_client_class)
    # 원본 값 보존 후 monkeypatch — 테스트 종료 시 fixture가 자동 복구.
    monkeypatch.setattr(ls_run_trees, "_CLIENT", None)
    monkeypatch.setattr(ls_context, "_GLOBAL_CLIENT", None)
    reset_langsmith_for_tests()

    init_langsmith()

    assert ls_run_trees._CLIENT is fake_client_instance, (
        "langsmith.run_trees._CLIENT was not patched — @traceable would create "
        "a fresh default Client without masking hooks"
    )
    assert ls_context._GLOBAL_CLIENT is fake_client_instance, (
        "langsmith._internal._context._GLOBAL_CLIENT was not patched — fallback "
        "init path could still create unmasked Client"
    )


def test_init_langsmith_creates_singleton_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """정상 init → ``Client`` instance 반환 + ``get_langsmith_client()`` 동일 instance.

    monkeypatch로 ``langsmith.Client``를 mock 처리 — 실 API 호출 회피.
    """
    from app.core import observability

    monkeypatch.setattr(_settings, "langchain_tracing_v2", True)
    monkeypatch.setattr(_settings, "langsmith_api_key", "ls__test")
    monkeypatch.setattr(_settings, "langsmith_project", "balancenote-test")

    fake_client_instance = MagicMock(name="FakeLangSmithClient")
    fake_client_class = MagicMock(return_value=fake_client_instance)
    monkeypatch.setattr(observability, "Client", fake_client_class)
    reset_langsmith_for_tests()

    with capture_logs() as cap:
        client = init_langsmith()

    # `Client(api_key=..., hide_inputs=mask_run_inputs, hide_outputs=mask_run_outputs)`
    # 인자 검증 — 마스킹 hook 콜백이 정확히 wired 됐는지 가드.
    fake_client_class.assert_called_once_with(
        api_key="ls__test",
        hide_inputs=mask_run_inputs,
        hide_outputs=mask_run_outputs,
    )
    assert client is fake_client_instance
    assert get_langsmith_client() is fake_client_instance
    info_events = [entry.get("event") for entry in cap if entry.get("log_level") == "info"]
    assert "observability.langsmith.initialized" in info_events


def test_reset_langsmith_for_tests_clears_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``reset_langsmith_for_tests()`` 호출 후 module 변수 None 강제."""
    from app.core import observability

    monkeypatch.setattr(_settings, "langchain_tracing_v2", True)
    monkeypatch.setattr(_settings, "langsmith_api_key", "ls__test")

    fake_client_instance = MagicMock(name="FakeLangSmithClient")
    fake_client_class = MagicMock(return_value=fake_client_instance)
    monkeypatch.setattr(observability, "Client", fake_client_class)
    reset_langsmith_for_tests()

    assert init_langsmith() is fake_client_instance
    assert get_langsmith_client() is fake_client_instance
    reset_langsmith_for_tests()
    assert get_langsmith_client() is None


def test_mask_run_inputs_passes_unknown_scalar_payload() -> None:
    """비-dict 입력(int/str/list) 그대로 통과 — LangSmith SDK 시그니처 변동 안전망."""
    # dict[str, Any] 시그니처지만 SDK 내부에서 list/None을 넘기는 경우 graceful.
    assert mask_run_inputs(None) == {}


def test_log_emits_initialized_event_with_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``observability.langsmith.initialized`` 이벤트에 ``project`` 메타데이터 포함.

    LangSmith 보드 다중 환경(dev/staging/prod) 분기 운영 시 startup 로그로
    어느 프로젝트가 active인지 즉시 식별 가능해야 함(architecture line 240 정합).
    """
    from app.core import observability

    monkeypatch.setattr(_settings, "langchain_tracing_v2", True)
    monkeypatch.setattr(_settings, "langsmith_api_key", "ls__test")
    monkeypatch.setattr(_settings, "langsmith_project", "balancenote-staging")
    monkeypatch.setattr(observability, "Client", MagicMock())
    reset_langsmith_for_tests()

    structlog.configure(
        processors=[structlog.testing.LogCapture()],
    )
    with capture_logs() as cap:
        init_langsmith()
    init_entries = [
        entry for entry in cap if entry.get("event") == "observability.langsmith.initialized"
    ]
    assert init_entries, f"missing initialized event: {cap}"
    assert init_entries[0].get("project") == "balancenote-staging"
