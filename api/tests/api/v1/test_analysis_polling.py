"""Story 3.7 — GET /v1/analysis/{meal_id} polling 라우터 테스트 (Task 9.2).

8 케이스 — in_progress / done / clarify / error / 404 / soft-deleted / consent / header.
"""

from __future__ import annotations

import uuid
from typing import cast

import pytest
from httpx import AsyncClient

from tests.api.v1.conftest import (
    make_clarify_state,
    make_done_state,
    make_node_error_state,
)
from tests.conftest import UserFactory, auth_headers

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def _consented_user(user_factory: UserFactory, consent_factory):
    """basic만 wire — polling은 automated_decision 미요구(AC7)."""
    user = await user_factory(profile_completed=True)
    await consent_factory(user, automated_decision=False)
    return user


async def test_poll_in_progress_returns_202_with_retry_after(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """state empty + meal 존재 → 202 + status=in_progress + Retry-After 헤더."""
    meal = await meal_factory(_consented_user)
    mock_analysis_service.aget_state.return_value = cast(dict, {})

    response = await client.get(
        f"/v1/analysis/{meal.id}",
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 202
    assert response.headers.get("X-Stream-Mode") == "polling"
    assert response.headers.get("Retry-After") == "2"
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["phase"] == "queued"


async def test_poll_done_returns_200_with_result(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """state.feedback 정상 → 200 + status=done + result payload."""
    meal = await meal_factory(_consented_user)
    mock_analysis_service.aget_state.return_value = make_done_state(fit_score=85, fit_label="good")

    response = await client.get(
        f"/v1/analysis/{meal.id}",
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 200
    assert response.headers.get("X-Stream-Mode") == "polling"
    body = response.json()
    assert body["status"] == "done"
    assert body["result"]["final_fit_score"] == 85
    assert body["result"]["fit_score_label"] == "excellent"  # to_summary_label "good" → excellent.


async def test_poll_clarify_returns_200_with_options(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """state.needs_clarification → 200 + status=needs_clarification + options."""
    meal = await meal_factory(_consented_user)
    mock_analysis_service.aget_state.return_value = make_clarify_state()

    response = await client.get(
        f"/v1/analysis/{meal.id}",
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_clarification"
    assert len(body["options"]) == 2


async def test_poll_node_errors_returns_200_with_problem(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """state.node_errors → 200 + status=error + RFC 7807 problem."""
    meal = await meal_factory(_consented_user)
    mock_analysis_service.aget_state.return_value = make_node_error_state()

    response = await client.get(
        f"/v1/analysis/{meal.id}",
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["problem"]["code"] == "analysis.node.failed"
    assert body["problem"]["status"] == 503


async def test_poll_meal_not_found_returns_404(
    client: AsyncClient, mock_analysis_service, _consented_user
) -> None:
    """잘못된 meal_id → 404 + analysis.meal.not_found."""
    response = await client.get(
        f"/v1/analysis/{uuid.uuid4()}",
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "analysis.meal.not_found"


async def test_poll_soft_deleted_returns_404(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """soft-deleted meal → 404."""
    meal = await meal_factory(_consented_user, deleted=True)
    response = await client.get(
        f"/v1/analysis/{meal.id}",
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 404


async def test_poll_basic_consent_missing_returns_403(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """basic consent 부재 → 403."""
    user = await user_factory(profile_completed=True)
    response = await client.get(
        f"/v1/analysis/{uuid.uuid4()}",
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "consent.basic.missing"


async def test_poll_does_not_require_automated_decision_consent(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """automated_decision 미요구 — _consented_user는 automated_decision=False라도 polling 통과."""
    meal = await meal_factory(_consented_user)
    mock_analysis_service.aget_state.return_value = cast(dict, {})

    response = await client.get(
        f"/v1/analysis/{meal.id}",
        headers=auth_headers(_consented_user),
    )
    # 200/202 모두 통과 의미(403 X).
    assert response.status_code in (200, 202)
