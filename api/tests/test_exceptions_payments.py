"""Story 6.1 — payments 예외 catalog code/status/title invariants 회귀.

``PaymentError`` 계층 7+ 서브클래스 ClassVar 단언 + ``to_problem(instance=...)`` 응답
dict shape 검증.

상기 ClassVar들이 다른 catalog 변경(``meals.*`` / ``llm_router.*`` 등)으로 의도치 않게
오염되지 않도록 회귀 가드.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import (
    NoActiveSubscriptionError,
    PaymentAmountInvalidError,
    PaymentConfirmFailedError,
    PaymentError,
    PaymentHistoryCursorInvalidError,
    PaymentIdempotencyKeyInvalidError,
    PaymentProviderError,
    PaymentProviderPayloadInvalidError,
    PaymentProviderRejectedError,
    PaymentProviderUnavailableError,
    SubscriptionAlreadyActiveError,
    SubscriptionAlreadyCancelledError,
    TossSecretKeyMissingError,
)


@pytest.mark.parametrize(
    ("exc_cls", "expected_status", "expected_code"),
    [
        (PaymentIdempotencyKeyInvalidError, 400, "payments.idempotency_key.invalid"),
        (PaymentAmountInvalidError, 400, "payments.amount.invalid"),
        (PaymentConfirmFailedError, 400, "payments.confirm_failed"),
        (SubscriptionAlreadyActiveError, 409, "payments.subscription.already_active"),
        (SubscriptionAlreadyCancelledError, 409, "payments.subscription.already_cancelled"),
        (PaymentHistoryCursorInvalidError, 400, "payments.history.cursor.invalid"),
        (NoActiveSubscriptionError, 404, "payments.subscription.not_found"),
        (PaymentProviderRejectedError, 400, "payments.provider.rejected"),
        (PaymentProviderUnavailableError, 502, "payments.provider.unavailable"),
        (PaymentProviderPayloadInvalidError, 502, "payments.provider.payload_invalid"),
        (TossSecretKeyMissingError, 503, "payments.toss.secret_key_missing"),
    ],
)
def test_payment_exception_status_code_invariants(
    exc_cls: type[PaymentError],
    expected_status: int,
    expected_code: str,
) -> None:
    """ClassVar status/code 기록 invariant — RFC 7807 매핑 SOT."""
    instance = exc_cls("test-detail")
    assert instance.status == expected_status
    assert instance.code == expected_code
    assert instance.title  # title 빈 문자열 차단(direct-raise 방어).


def test_payment_confirm_failed_to_problem_uses_payment_failed_type_url() -> None:
    """``PaymentConfirmFailedError.to_problem`` — epics.md:842 ``type=payment-failed``
    URL 정합 (hyphen 표기). RFC 7807 ``type`` 필드는 다른 코드와 다르게 카탈로그 URL이
    명시되어 클라이언트가 *결제 실패 분기*를 ``code`` 또는 ``type`` 둘 다로 인식 가능.
    """
    exc = PaymentConfirmFailedError("카드 한도 초과")
    problem = exc.to_problem(instance="/v1/payments/subscribe")
    assert problem.type == "https://balancenote.app/errors/payments-confirm-failed"
    assert problem.code == "payments.confirm_failed"
    assert problem.status == 400
    assert problem.detail == "카드 한도 초과"
    assert problem.instance == "/v1/payments/subscribe"


def test_payment_provider_base_default_status_502() -> None:
    """``PaymentProviderError`` base는 502 default — ``LLMRouterError`` 패턴 정합
    (*upstream provider 장애*는 RFC 9110 §15.6.3 502 정합).
    """
    instance = PaymentProviderError("provider boundary error")
    assert instance.status == 502
    assert instance.code == "payments.provider.error"


def test_subscription_already_cancelled_to_problem_shape() -> None:
    """Story 6.2 AC3 — ``SubscriptionAlreadyCancelledError.to_problem`` RFC 7807 dict shape."""
    exc = SubscriptionAlreadyCancelledError("이미 해지되었습니다")
    problem = exc.to_problem(instance="/v1/payments/cancel")
    assert problem.status == 409
    assert problem.code == "payments.subscription.already_cancelled"
    assert problem.title == "Subscription already cancelled"
    assert problem.detail == "이미 해지되었습니다"
    assert problem.instance == "/v1/payments/cancel"


def test_payment_history_cursor_invalid_to_problem_shape() -> None:
    """Story 6.2 AC4 — ``PaymentHistoryCursorInvalidError.to_problem`` RFC 7807 dict shape."""
    exc = PaymentHistoryCursorInvalidError("cursor format invalid")
    problem = exc.to_problem(instance="/v1/payments/history")
    assert problem.status == 400
    assert problem.code == "payments.history.cursor.invalid"
    assert problem.title == "Pagination cursor invalid"
    assert problem.detail == "cursor format invalid"
    assert problem.instance == "/v1/payments/history"
