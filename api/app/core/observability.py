"""LangSmith 외부 옵저버빌리티 — Story 3.8 (NFR-O1, NFR-O2, NFR-O5).

NFR-O2 마스킹 룰셋은 ``app.core.sentry._MASKED_KEYS``를 ``import``해 *합집합*으로
재사용한다 — 1지점 SOT(architecture line 237). Sentry 측 키 변경 PR이
LangSmith hook에도 자동 반영된다(`tests/core/test_observability.py` 합집합 무결성
가드 정합).

LangGraph native tracing은 ``LANGCHAIN_TRACING_V2=true`` env 1개로 활성 — 본
모듈은 *Client 인스턴스 + 마스킹 hook* 만 제공한다(노드 wiring/그래프 변경 0,
D4 정합).
"""

from __future__ import annotations

import os
from typing import Any, Final

import structlog
from langsmith import Client

from app.core.config import settings
from app.core.sentry import _MASKED_KEYS as _SENTRY_MASKED_KEYS

log = structlog.get_logger(__name__)


# Sentry SOT(``app.core.sentry._MASKED_KEYS``) 외에 LangGraph state PII 키를 추가
# — 합집합으로 LangSmith trace inputs/outputs 양 hook에서 동일 redaction 적용.
# ``feedback`` 키는 dict 전체를 ``"***"``로 치환(``feedback.text`` nested 필드를
# 부모 path 추적 없이 보호 — Dev Notes #3 D2 정합).
_LANGSMITH_EXTRA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "weight_kg",
        "height_cm",
        "allergies",
        "parsed_items",
        "food_items",
        "clarification_options",
        "feedback_text",
        "feedback",
        # Story 3.8 smoke v3 검증 — production 분석 흐름은 ``raw_text`` 키(Sentry
        # SOT)로 마스킹되지만, helper 함수가 ``meal_text`` 인자명으로 LangSmith
        # trace에 노출되면 raw 식단 본문이 보드에 그대로 표기됨(NFR-S5 위반).
        # ``raw_text``의 변형 키도 동일 redact — defense in depth 안전망.
        "meal_text",
    }
)
_LANGSMITH_MASKED_KEYS: Final[frozenset[str]] = _SENTRY_MASKED_KEYS | _LANGSMITH_EXTRA_KEYS
_MASK_PLACEHOLDER: Final[str] = "***"


# module-level singleton — lifespan startup에서 ``init_langsmith()`` 1회 할당.
_langsmith_client: Client | None = None


def _mask_recursive(value: Any) -> Any:
    """dict/list 재귀 순회 + ``_LANGSMITH_MASKED_KEYS`` value를 ``"***"``로 치환.

    ``app.core.sentry._mask_dict`` 패턴 정합(list of dict 처리 포함). LangSmith
    hook은 신규 dict를 *반환*해야 하므로(원본 미수정) sentry 측 in-place 변형
    분기와 시그니처가 다르다 — 별 모듈 재구현.
    """
    if isinstance(value, dict):
        return {
            k: _MASK_PLACEHOLDER if k in _LANGSMITH_MASKED_KEYS else _mask_recursive(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_mask_recursive(item) for item in value]
    return value


def mask_run_inputs(inputs: dict[str, Any] | None) -> dict[str, Any]:
    """LangSmith ``Client(hide_inputs=...)`` 콜백 — 송신 직전 inputs 마스킹.

    ``None`` 입력은 빈 dict 반환(LangSmith 콜백 시그니처 기대값 정합). 비-dict
    입력은 그대로 통과 — LangSmith 내부적으로 dict만 hook에 넘기지만 안전망.
    원본 dict는 *변경하지 않는다*(side-effect 0 — sentry hook과 다른 시그니처).
    """
    if inputs is None:
        return {}
    if not isinstance(inputs, dict):
        # LangSmith 콜백은 dict만 넘기지만, SDK 내부 변경에 대비한 안전망.
        return inputs
    masked = _mask_recursive(inputs)
    # ``_mask_recursive``가 dict 입력에는 dict를 반환하지만 ``Any`` 시그니처라
    # mypy narrowing이 안 됨 — 명시 cast.
    assert isinstance(masked, dict)
    return masked


def mask_run_outputs(outputs: dict[str, Any] | None) -> dict[str, Any]:
    """LangSmith ``Client(hide_outputs=...)`` 콜백 — 송신 직전 outputs 마스킹.

    ``mask_run_inputs``와 동일 키셋·동작. 별 시그니처는 LangSmith client 콜백
    명명 정합(inputs/outputs hook 분리).
    """
    return mask_run_inputs(outputs)


def init_langsmith() -> Client | None:
    """LangSmith Client 싱글턴 초기화 — lifespan startup에서 1회 호출.

    분기:
    - ``settings.langchain_tracing_v2 is False`` → log INFO + ``None`` return
      (graceful skip — 로컬 dev 디폴트, NFR-O5 LangSmith 송신 0 보장).
    - ``True`` + ``langsmith_api_key == ""`` → log WARNING + ``None`` return
      (config 모순이지만 부팅 통과 — 어차피 PII 송신 X이라 라우터 503 회피).
    - 정상 → ``Client(hide_inputs=mask_run_inputs, hide_outputs=mask_run_outputs)``
      module 변수 할당 + return.

    LangGraph native tracing은 본 함수와 *독립* — env ``LANGCHAIN_TRACING_V2``를
    langchain-core가 직접 인식해 자동 부착(D4 정합).
    """
    global _langsmith_client
    if not settings.langchain_tracing_v2:
        log.info("observability.langsmith.disabled", reason="tracing_v2_false")
        _langsmith_client = None
        return None
    if not settings.langsmith_api_key:
        log.warning("observability.langsmith.misconfigured", reason="missing_api_key")
        _langsmith_client = None
        return None
    # LangChain native tracing(`@traceable` / LangGraph 자동 트레이싱)은 *기본 Client*를
    # 별도 생성하면서 ``os.environ['LANGSMITH_API_KEY']``를 직접 읽는다 — pydantic-settings
    # 가 ``.env`` → Settings 객체로만 로드하는 dev 경로에서는 시스템 env에 키가 없어
    # 401 Unauthorized 회귀. Railway secrets prod/staging은 이미 systemd env 주입이라
    # ``setdefault``로 no-op. ``setdefault``를 쓰는 이유 — *외부 환경변수가 우선*해야
    # 다중 환경 운영 시점에 .env override가 의도치 않게 prod 값 덮지 않음.
    os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    _langsmith_client = Client(
        api_key=settings.langsmith_api_key,
        hide_inputs=mask_run_inputs,
        hide_outputs=mask_run_outputs,
    )
    # LangChain native tracing(`@traceable` / LangGraph) + LangSmith ``run_trees``의
    # ``get_cached_client()``는 process-wide 모듈 변수 ``langsmith.run_trees._CLIENT`` /
    # ``langsmith._internal._context._GLOBAL_CLIENT``를 우선 참조한다. 본 변수를 비워둔
    # 채 두면 SDK가 *hide_inputs/hide_outputs 없는 default Client*를 자체 생성 → 마스킹
    # hook 우회 + raw PII 노출 회귀(Story 3.8 smoke test 검증). 우리 masked client를
    # 두 변수에 직접 주입해 모든 tracing 경로가 동일 hook을 통과하도록 강제.
    import langsmith._internal._context as _ls_context  # noqa: PLC0415
    import langsmith.run_trees as _ls_run_trees  # noqa: PLC0415

    _ls_context._GLOBAL_CLIENT = _langsmith_client
    _ls_run_trees._CLIENT = _langsmith_client

    log.info(
        "observability.langsmith.initialized",
        project=settings.langsmith_project,
    )
    return _langsmith_client


def get_langsmith_client() -> Client | None:
    """싱글턴 접근자 — 테스트 monkeypatch + script 재사용 정합."""
    return _langsmith_client


def reset_langsmith_for_tests() -> None:
    """테스트 격리용 — module 변수 None 강제(monkeypatch fallback)."""
    global _langsmith_client
    _langsmith_client = None
