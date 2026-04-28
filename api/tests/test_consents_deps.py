"""`require_basic_consents` Depends 단위 테스트 (Story 1.3 AC #11, #15).

5+ 케이스: row 없음 / disclaimer-only 누락 / terms-only 누락 / sensitive-only 누락
(PIPA 23조 회귀 차단) / version mismatch / 모두 OK.

본 스토리는 `require_basic_consents`를 어떤 라우터에도 wire하지 않는다 — 단위 테스트로만
동작 검증한다(Story 1.5+가 명시 wire 예정).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.deps import require_basic_consents
from app.core.exceptions import BasicConsentMissingError
from app.db.models.consent import Consent
from app.db.models.user import User
from app.main import app

UserFactory = Callable[..., Awaitable[User]]
ConsentFactory = Callable[..., Awaitable[Consent]]


async def _call(user: User) -> User:
    """``require_basic_consents``를 직접 호출 — FastAPI Depends 우회 단위 테스트."""
    session_maker: async_sessionmaker = app.state.session_maker
    async with session_maker() as session:
        return await require_basic_consents(db=session, user=user)


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
