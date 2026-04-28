"""`/v1/legal/{type}` 라우터 테스트 (Story 1.3 AC #7, #15).

Public endpoint — 인증 무관. cookie 동봉 시에도 동일 응답이어야 한다.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.domain.legal_documents import CURRENT_VERSIONS

# research 3.4 디스클레이머 첫 60자 substring (한국어).
_DISCLAIMER_KO_OPENING = "본 서비스는 일반 건강관리(웰니스) 목적의 정보 제공"

# 영문 디스클레이머 substring.
_DISCLAIMER_EN_OPENING = "This service is provided for general wellness"


@pytest.mark.asyncio
async def test_legal_disclaimer_ko_returns_research_text(client: AsyncClient) -> None:
    response = await client.get("/v1/legal/disclaimer", params={"lang": "ko"})
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "disclaimer"
    assert body["lang"] == "ko"
    assert body["version"] == CURRENT_VERSIONS["disclaimer"]
    assert _DISCLAIMER_KO_OPENING in body["body"]
    assert body["title"]
    assert body["updated_at"]


@pytest.mark.asyncio
async def test_legal_disclaimer_en_returns_english_text(client: AsyncClient) -> None:
    response = await client.get("/v1/legal/disclaimer", params={"lang": "en"})
    assert response.status_code == 200
    body = response.json()
    assert body["lang"] == "en"
    assert _DISCLAIMER_EN_OPENING in body["body"]


@pytest.mark.asyncio
async def test_legal_invalid_lang_returns_400(client: AsyncClient) -> None:
    response = await client.get("/v1/legal/disclaimer", params={"lang": "fr"})
    # Pydantic Literal 검증 실패 → main.py validation_exception_handler가 400으로 매핑.
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_legal_invalid_doc_type_returns_400(client: AsyncClient) -> None:
    # path Literal 위반 — FastAPI가 422 → 400 매핑.
    response = await client.get("/v1/legal/invalid", params={"lang": "ko"})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_legal_does_not_require_auth(client: AsyncClient) -> None:
    """인증 없이도 200. ``current_user`` Depends 미적용 회귀 차단."""
    response = await client.get("/v1/legal/terms", params={"lang": "ko"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_legal_ignores_invalid_cookie(client: AsyncClient) -> None:
    """잘못된 ``bn_access`` cookie 동봉 시에도 동일 응답 — public endpoint 회귀 차단."""
    response = await client.get(
        "/v1/legal/privacy",
        params={"lang": "ko"},
        cookies={"bn_access": "completely-bogus-token"},
    )
    assert response.status_code == 200
    assert response.json()["type"] == "privacy"
