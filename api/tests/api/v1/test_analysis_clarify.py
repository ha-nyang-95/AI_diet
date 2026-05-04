"""Story 3.7 — POST /v1/analysis/clarify resume 라우터 테스트 (Task 9.3).

6 케이스 — happy path / 빈 selected_value / 81자 / meal 미존재 / 게이트 / 재발 clarify.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.api.v1.conftest import (
    make_clarify_state,
    make_done_state,
    parse_sse_text,
)
from tests.conftest import UserFactory, auth_headers

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _fast_chunking(monkeypatch):
    monkeypatch.setattr(settings, "analysis_token_chunk_interval_ms", 0)


@pytest.fixture
async def _consented_user(user_factory: UserFactory, consent_factory):
    user = await user_factory(profile_completed=True)
    await consent_factory(user, automated_decision=True)
    return user


async def test_clarify_happy_path_emits_done(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """aresume 정상 결과 → SSE done 1회."""
    meal = await meal_factory(_consented_user)
    mock_analysis_service.aresume.return_value = make_done_state(used_llm="gpt-4o-mini")

    response = await client.post(
        "/v1/analysis/clarify",
        json={"meal_id": str(meal.id), "selected_value": "연어 포케 1인분"},
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 200
    assert response.headers.get("X-Stream-Mode") == "sse"
    events = parse_sse_text(response.text)
    names = [e[0] for e in events]
    assert names.count("done") == 1
    # aresume이 정확한 인자로 호출됐는지 검증.
    mock_analysis_service.aresume.assert_awaited_once()
    call_kwargs = mock_analysis_service.aresume.await_args.kwargs
    assert call_kwargs["thread_id"] == f"meal:{meal.id}"
    assert call_kwargs["user_input"] == {"selected_value": "연어 포케 1인분"}


async def test_clarify_empty_selected_value_returns_422(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """빈 selected_value(min_length=1 위반) → 400 (Pydantic ValidationError)."""
    meal = await meal_factory(_consented_user)
    response = await client.post(
        "/v1/analysis/clarify",
        json={"meal_id": str(meal.id), "selected_value": ""},
        headers=auth_headers(_consented_user),
    )
    # Pydantic min_length=1 위반은 main.py 글로벌 핸들러가 400으로 매핑.
    assert response.status_code == 400


async def test_clarify_oversized_selected_value_returns_422(
    client: AsyncClient, _consented_user, meal_factory
) -> None:
    """max_length=80 초과 → 400 (Pydantic ValidationError)."""
    meal = await meal_factory(_consented_user)
    response = await client.post(
        "/v1/analysis/clarify",
        json={"meal_id": str(meal.id), "selected_value": "가" * 81},
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 400


async def test_clarify_meal_not_found_returns_404(
    client: AsyncClient, mock_analysis_service, _consented_user
) -> None:
    """잘못된 meal_id → 404."""
    response = await client.post(
        "/v1/analysis/clarify",
        json={"meal_id": str(uuid.uuid4()), "selected_value": "테스트"},
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "analysis.meal.not_found"


async def test_clarify_automated_decision_consent_required(
    client: AsyncClient, user_factory: UserFactory, consent_factory, meal_factory
) -> None:
    """clarify는 automated_decision 강제 — 미부여 시 403."""
    user = await user_factory(profile_completed=True)
    await consent_factory(user, automated_decision=False)
    meal = await meal_factory(user)
    response = await client.post(
        "/v1/analysis/clarify",
        json={"meal_id": str(meal.id), "selected_value": "테스트"},
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "consent.automated_decision.missing"


async def test_clarify_recurring_clarify_emits_clarify_again(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """aresume 후 needs_clarification 재발 → event: clarify 다시 emit(라우터 단순 재진입)."""
    meal = await meal_factory(_consented_user)
    mock_analysis_service.aresume.return_value = make_clarify_state()

    response = await client.post(
        "/v1/analysis/clarify",
        json={"meal_id": str(meal.id), "selected_value": "포케"},
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 200
    events = parse_sse_text(response.text)
    names = [e[0] for e in events]
    assert names.count("clarify") == 1
    assert "done" not in names
