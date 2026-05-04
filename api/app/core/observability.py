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
#
# Story 3.8 CR DN-2 (옵션 b): ``feedback`` 키 *whole-dict redact*는 제거하고
# 그 자리에 ``text`` 키를 추가 — 영업 데모 보드에서 ``feedback.citations`` /
# ``feedback.macros`` / ``feedback.fit_score`` 가시성을 살리되, 자연어 ``text``
# 본문(사용자 PII가 인용될 수 있음)은 마스킹. ``text`` 키 단독 mask는 false-positive
# 위험이 낮다 — 현 LangGraph state(``parsed_items[*].name`` / ``citations[*].quote`` /
# ``clarification_options[*]: str``)에 ``text`` 키를 쓰는 nested dict 없음. 향후
# 신규 노드가 비-PII ``text`` 필드를 도입할 경우 ``text`` → 화이트리스트 재설계.
_LANGSMITH_EXTRA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "weight_kg",
        "height_cm",
        "allergies",
        "parsed_items",
        "food_items",
        "clarification_options",
        "feedback_text",
        # Story 3.8 CR DN-2 — ``feedback.text``의 자연어 본문 마스킹용. ``feedback``
        # dict 전체 redact를 제거하고 ``text`` 키 단독 매칭으로 전환 — citations /
        # macros / fit_score는 보드 노출 OK. 본 키는 LangGraph state ``feedback.text``
        # 외 ``text`` 키를 쓰는 nested dict가 없는 현 구조 전제 정합.
        "text",
        # Story 3.8 smoke v3 검증 — production 분석 흐름은 ``raw_text`` 키(Sentry
        # SOT)로 마스킹되지만, helper 함수가 ``meal_text`` 인자명으로 LangSmith
        # trace에 노출되면 raw 식단 본문이 보드에 그대로 표기됨(NFR-S5 위반).
        # ``raw_text``의 변형 키도 동일 redact — defense in depth 안전망.
        "meal_text",
    }
)
_LANGSMITH_MASKED_KEYS: Final[frozenset[str]] = _SENTRY_MASKED_KEYS | _LANGSMITH_EXTRA_KEYS
_MASK_PLACEHOLDER: Final[str] = "***"

# Story 3.8 CR P4 — pathological inputs(self-referential dict, 깊이 폭주 nested
# state)가 LangSmith ``hide_inputs`` hot-path에서 ``RecursionError``를 raise하면
# trace 자체가 drop된다. Cycle은 ``id(value)`` 추적, 깊이 32 초과는 placeholder
# 치환 + WARNING 로그(silent regress 방지).
_MAX_MASK_DEPTH: Final[int] = 32


# module-level singleton — lifespan startup에서 ``init_langsmith()`` 1회 할당.
_langsmith_client: Client | None = None

# Story 3.8 CR P8 — ``init_langsmith()``이 ``os.environ.setdefault``로 추가한 키를
# 추적해 ``reset_langsmith_for_tests()``에서 정리. pytest monkeypatch는 ``setenv``
# 만 자동 복구하지 종속 코드의 직접 ``os.environ`` 변경은 미복구 → 테스트 간 env
# 누수로 후속 테스트에서 misconfigured 분기 미발동 회귀.
_env_keys_set: list[str] = []


def _mask_recursive(
    value: Any,
    *,
    _seen: set[int] | None = None,
    _depth: int = 0,
) -> Any:
    """dict/list/tuple 재귀 순회 + ``_LANGSMITH_MASKED_KEYS`` value를 ``"***"``로 치환.

    ``app.core.sentry._mask_dict`` 패턴 정합(list of dict 처리 포함). LangSmith
    hook은 신규 dict를 *반환*해야 하므로(원본 미수정) sentry 측 in-place 변형
    분기와 시그니처가 다르다 — 별 모듈 재구현.

    Cycle/depth 가드(P4): pathological inputs로 인한 RecursionError는 hot-path
    예외 → trace drop. ``_seen`` set으로 cycle 탐지, ``_MAX_MASK_DEPTH`` 초과는
    placeholder + WARNING 로그.
    """
    if _depth > _MAX_MASK_DEPTH:
        log.warning("observability.mask.depth_exceeded", depth=_depth)
        return _MASK_PLACEHOLDER

    if isinstance(value, dict | list | tuple):
        if _seen is None:
            _seen = set()
        marker = id(value)
        if marker in _seen:
            return _MASK_PLACEHOLDER
        _seen.add(marker)
    else:
        return value

    if isinstance(value, dict):
        return {
            k: (
                _MASK_PLACEHOLDER
                if isinstance(k, str) and k in _LANGSMITH_MASKED_KEYS
                else _mask_recursive(v, _seen=_seen, _depth=_depth + 1)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_mask_recursive(item, _seen=_seen, _depth=_depth + 1) for item in value]
    # tuple — masked 결과는 list로 반환(LangSmith JSON 직렬화 정합 + 신규 객체 보장).
    return [_mask_recursive(item, _seen=_seen, _depth=_depth + 1) for item in value]


def mask_run_inputs(inputs: Any) -> Any:
    """LangSmith ``Client(hide_inputs=...)`` 콜백 — 송신 직전 inputs 마스킹.

    ``None`` 입력은 빈 dict 반환(LangSmith 콜백 시그니처 기대값 정합). list /
    tuple top-level은 재귀 순회(SDK 변경에 대비한 안전망 — P3). 비-collection 스칼라
    값은 그대로 통과(마스킹 대상 키 컨텍스트가 없어 mask placeholder가 부적절).
    원본 dict는 *변경하지 않는다*(side-effect 0 — sentry hook과 다른 시그니처).
    """
    if inputs is None:
        return {}
    if isinstance(inputs, dict | list | tuple):
        return _mask_recursive(inputs)
    # int/str/float/bytes 등 스칼라 — LangSmith 보드에 표기되어도 PII 컨텍스트 부재.
    return inputs


def mask_run_outputs(outputs: Any) -> Any:
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

    Story 3.8 CR P2 — private SDK 변수(``langsmith.run_trees._CLIENT`` /
    ``langsmith._internal._context._GLOBAL_CLIENT``) 주입은 LangSmith SDK 0.8.x
    내부 구조 의존. 미래 minor bump가 attr를 제거하면 ``ImportError``/
    ``AttributeError`` raise되며 lifespan blanket-except에 잡히지만 *부분 init*
    상태(Client만 생성, globals 미주입)로 남으면 마스킹 hook 우회 회귀.
    Inner failure 시 ``_langsmith_client = None`` 명시 리셋 + 키 cleanup.
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
    for env_key, env_val in (
        ("LANGSMITH_API_KEY", settings.langsmith_api_key),
        ("LANGSMITH_PROJECT", settings.langsmith_project),
    ):
        if env_key not in os.environ:
            os.environ[env_key] = env_val
            _env_keys_set.append(env_key)

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
    #
    # P2 — private path 의존이라 SDK 미래 bump가 ``ImportError``/``AttributeError``로
    # 깨질 수 있다. 본 func은 lifespan blanket-except에 잡히지만, *Client는 생성됐는데
    # globals만 미주입* 부분 성공 상태가 가장 위험(default Client가 raw PII 송신).
    # 실패 시 ``_langsmith_client = None``으로 명시 리셋 — DN-5(``main.py``)의
    # ``LANGCHAIN_TRACING_V2=false`` 강제 분기와 결합해 fail-closed 보장.
    try:
        import langsmith._internal._context as _ls_context  # noqa: PLC0415
        import langsmith.run_trees as _ls_run_trees  # noqa: PLC0415

        _ls_context._GLOBAL_CLIENT = _langsmith_client
        _ls_run_trees._CLIENT = _langsmith_client
    except (ImportError, AttributeError) as exc:
        log.warning(
            "observability.langsmith.global_client_wiring_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        # 부분 성공 상태 차단 — Client 인스턴스 폐기 + singleton 리셋.
        _langsmith_client = None
        _cleanup_env_keys()
        return None

    log.info(
        "observability.langsmith.initialized",
        project=settings.langsmith_project,
    )
    return _langsmith_client


def get_langsmith_client() -> Client | None:
    """싱글턴 접근자 — 테스트 monkeypatch + script 재사용 정합."""
    return _langsmith_client


def _cleanup_env_keys() -> None:
    """``init_langsmith()``이 추가한 env 키를 제거 — 테스트 격리 + 부분-실패 cleanup."""
    while _env_keys_set:
        key = _env_keys_set.pop()
        os.environ.pop(key, None)


def reset_langsmith_for_tests() -> None:
    """테스트 격리용 — module 변수 None 강제 + env 키 cleanup(P8)."""
    global _langsmith_client
    _langsmith_client = None
    _cleanup_env_keys()
