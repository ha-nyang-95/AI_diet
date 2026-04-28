"""`require_basic_consents` + `require_automated_decision_consent` Depends 단위 테스트
(Story 1.3 AC #11, #15 + Story 1.4 AC #14, #15).

본 스토리는 두 함수 모두 어떤 라우터에도 wire하지 않는다 — 단위 테스트로만 동작 검증
(Story 1.5+ / Epic 3 Story 3.x가 명시 wire 예정).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_automated_decision_consent, require_basic_consents
from app.core.exceptions import (
    AutomatedDecisionConsentMissingError,
    BasicConsentMissingError,
)
from app.db.models.consent import Consent
from app.db.models.user import User
from app.main import app

UserFactory = Callable[..., Awaitable[User]]
ConsentFactory = Callable[..., Awaitable[Consent]]


async def _call(user: User) -> User:
    """``require_basic_consents``를 직접 호출 — FastAPI Depends 우회 단위 테스트."""
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        return await require_basic_consents(db=session, user=user)


async def _call_ad(user: User) -> User:
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        return await require_automated_decision_consent(db=session, user=user)


@pytest.mark.asyncio
async def test_raises_when_no_consent_row(client, user_factory: UserFactory) -> None:
    user = await user_factory()
    with pytest.raises(BasicConsentMissingError):
        await _call(user)


@pytest.mark.asyncio
async def test_raises_when_disclaimer_missing(
    client, user_factory: UserFactory, consent_factory: ConsentFactory
) -> None:
    user = await user_factory()
    await consent_factory(user, disclaimer=False)
    with pytest.raises(BasicConsentMissingError):
        await _call(user)


@pytest.mark.asyncio
async def test_raises_when_terms_missing(
    client, user_factory: UserFactory, consent_factory: ConsentFactory
) -> None:
    user = await user_factory()
    await consent_factory(user, terms=False)
    with pytest.raises(BasicConsentMissingError):
        await _call(user)


@pytest.mark.asyncio
async def test_raises_when_sensitive_personal_info_missing(
    client, user_factory: UserFactory, consent_factory: ConsentFactory
) -> None:
    """PIPA 23조 별도 동의 회귀 차단 — sensitive_personal_info만 누락된 경우."""
    user = await user_factory()
    await consent_factory(user, sensitive=False)
    with pytest.raises(BasicConsentMissingError):
        await _call(user)


@pytest.mark.asyncio
async def test_raises_when_version_mismatch(
    client, user_factory: UserFactory, consent_factory: ConsentFactory
) -> None:
    user = await user_factory()
    await consent_factory(user, version="ko-1900-01-01")
    with pytest.raises(BasicConsentMissingError):
        await _call(user)


@pytest.mark.asyncio
async def test_passes_when_all_basic_consents_complete(
    client, user_factory: UserFactory, consent_factory: ConsentFactory
) -> None:
    user = await user_factory()
    await consent_factory(user)  # 기본 = 모든 항목 + 현 SOT 버전
    result = await _call(user)
    assert result.id == user.id


# ---------------------------------------------------------------------------
# Story 1.4 — require_automated_decision_consent (AC #14)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ad_raises_when_no_consent_row(client, user_factory: UserFactory) -> None:
    user = await user_factory()
    with pytest.raises(AutomatedDecisionConsentMissingError):
        await _call_ad(user)


@pytest.mark.asyncio
async def test_ad_raises_when_consent_at_null(
    client, user_factory: UserFactory, consent_factory: ConsentFactory
) -> None:
    """basic만 통과 + AD 미동의 사용자는 AD 게이트 차단."""
    user = await user_factory()
    await consent_factory(user)  # AD False 기본
    with pytest.raises(AutomatedDecisionConsentMissingError):
        await _call_ad(user)


@pytest.mark.asyncio
async def test_ad_raises_when_revoked(
    client, user_factory: UserFactory, consent_factory: ConsentFactory
) -> None:
    """동의 부여 후 철회한 사용자는 AD 게이트 차단(``revoked_at IS NOT NULL``)."""
    user = await user_factory()
    await consent_factory(user, automated_decision=True, automated_decision_revoked=True)
    with pytest.raises(AutomatedDecisionConsentMissingError):
        await _call_ad(user)


@pytest.mark.asyncio
async def test_ad_raises_when_version_mismatch(
    client, user_factory: UserFactory, consent_factory: ConsentFactory
) -> None:
    user = await user_factory()
    await consent_factory(
        user,
        automated_decision=True,
        automated_decision_version="ko-1900-01-01",
    )
    with pytest.raises(AutomatedDecisionConsentMissingError):
        await _call_ad(user)


@pytest.mark.asyncio
async def test_ad_passes_when_granted_and_unrevoked(
    client, user_factory: UserFactory, consent_factory: ConsentFactory
) -> None:
    """basic 미통과여도 AD 게이트 자체는 통과(*직교* 의무 결정 — AC4)."""
    user = await user_factory()
    await consent_factory(
        user,
        disclaimer=False,
        terms=False,
        privacy=False,
        sensitive=False,
        automated_decision=True,
    )
    result = await _call_ad(user)
    assert result.id == user.id
