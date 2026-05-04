"""Story 3.7 — POST /v1/analysis/stream SSE 라우터 테스트 (Task 9.1).

12 케이스 — happy path / 게이트 / 소유권 / checkpointer / clarify / node_errors /
rate limit / 빈 raw_text / 한국어 분할.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.main import app
from tests.api.v1.conftest import (
    make_clarify_state,
    make_done_state,
    make_node_error_state,
    parse_sse_text,
)
from tests.conftest import UserFactory, auth_headers

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _fast_chunking(monkeypatch):
    """SSE chunk interval을 0ms로 강제 — 테스트 속도 ↑(실 streaming 의미는 동일).

    테스트는 happy path 합산 wall-time이 ≤ 1초여야 — 30ms × N chunk가 누적되면 느려짐.
    """
    monkeypatch.setattr(settings, "analysis_token_chunk_interval_ms", 0)


@pytest.fixture
async def _consented_user(user_factory: UserFactory, consent_factory):
    user = await user_factory(profile_completed=True)
    await consent_factory(user, automated_decision=True)
    return user


async def test_stream_happy_path_emits_full_sequence(
    client: AsyncClient, mock_analysis_service, meal_factory, _consented_user
) -> None:
    """progress(1) → token(N≥1) → citation(N≥0) → done(1) 순차 emit."""
    meal = await meal_factory(_consented_user)
    mock_analysis_service.run.return_value = make_done_state(
        feedback_text="오늘 식단 평가 결과 단백질이 부족합니다.",
        used_llm="gpt-4o-mini",
    )

    response = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(meal.id)},
        headers=auth_headers(_consented_user),
    )

    assert response.status_code == 200
    assert response.headers.get("X-Stream-Mode") == "sse"
    events = parse_sse_text(response.text)
    event_names = [e[0] for e in events]
    assert event_names[0] == "progress"
    assert "token" in event_names
    assert "done" in event_names
    # done 정확히 1회.
    assert event_names.count("done") == 1
    assert event_names.count("clarify") == 0
    # done은 마지막 event.
    assert event_names[-1] == "done"
    # done payload 검증.
    done_payload = next(e[1] for e in events if e[0] == "done")
    assert done_payload["meal_id"] == str(meal.id)
    assert done_payload["used_llm"] == "gpt-4o-mini"


async def test_stream_basic_consent_missing_returns_403(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """basic consent 부재 → 403 + consent.basic.missing."""
    user = await user_factory(profile_completed=True)
    response = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(uuid.uuid4())},
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "consent.basic.missing"


async def test_stream_automated_decision_consent_missing_returns_403(
    client: AsyncClient, user_factory: UserFactory, consent_factory
) -> None:
    """automated_decision consent 부재 → 403 + consent.automated_decision.missing."""
    user = await user_factory(profile_completed=True)
    await consent_factory(user, automated_decision=False)
    response = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(uuid.uuid4())},
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "consent.automated_decision.missing"


async def test_stream_meal_not_found_returns_404(
    client: AsyncClient, mock_analysis_service, _consented_user
) -> None:
    """잘못된 meal_id → 404 + analysis.meal.not_found."""
    response = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(uuid.uuid4())},
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "analysis.meal.not_found"


async def test_stream_other_users_meal_returns_404(
    client: AsyncClient,
    mock_analysis_service,
    user_factory: UserFactory,
    consent_factory,
    meal_factory,
) -> None:
    """다른 user의 meal_id → 404(enumeration 차단 — meal 존재 사실 leak X)."""
    owner = await user_factory(profile_completed=True)
    await consent_factory(owner, automated_decision=True)
    intruder = await user_factory(profile_completed=True)
    await consent_factory(intruder, automated_decision=True)
    meal = await meal_factory(owner)
    response = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(meal.id)},
        headers=auth_headers(intruder),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "analysis.meal.not_found"


async def test_stream_soft_deleted_meal_returns_404(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """soft-deleted meal → 404 일원화."""
    meal = await meal_factory(_consented_user, deleted=True)
    response = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(meal.id)},
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 404


async def test_stream_checkpointer_unavailable_returns_503(
    client: AsyncClient, _consented_user, meal_factory
) -> None:
    """app.state.analysis_service is None → 503 + analysis.checkpointer.unavailable."""
    original = app.state.analysis_service
    app.state.analysis_service = None
    try:
        meal = await meal_factory(_consented_user)
        response = await client.post(
            "/v1/analysis/stream",
            json={"meal_id": str(meal.id)},
            headers=auth_headers(_consented_user),
        )
        assert response.status_code == 503
        assert response.json()["code"] == "analysis.checkpointer.unavailable"
    finally:
        app.state.analysis_service = original


async def test_stream_needs_clarification_emits_clarify_only(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """state.needs_clarification → SSE clarify 정확히 1회 + done 미발생."""
    meal = await meal_factory(_consented_user)
    mock_analysis_service.run.return_value = make_clarify_state()

    response = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(meal.id)},
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 200
    events = parse_sse_text(response.text)
    names = [e[0] for e in events]
    assert names.count("clarify") == 1
    assert "done" not in names
    clarify_payload = next(e[1] for e in events if e[0] == "clarify")
    assert len(clarify_payload["options"]) == 2


async def test_stream_node_errors_emits_error(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """node_errors + feedback 부재 → SSE error 정확히 1회."""
    meal = await meal_factory(_consented_user)
    mock_analysis_service.run.return_value = make_node_error_state()

    response = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(meal.id)},
        headers=auth_headers(_consented_user),
    )
    events = parse_sse_text(response.text)
    names = [e[0] for e in events]
    assert names.count("error") == 1
    assert "done" not in names
    error_payload = next(e[1] for e in events if e[0] == "error")
    assert error_payload["code"] == "analysis.node.failed"


async def test_stream_korean_text_chunks_safely(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """한국어 본문 — token chunks 합치면 원본 동일(NFC 정규화 round-trip 가드)."""
    meal = await meal_factory(_consented_user)
    feedback_text = "한국어 식단 분석 — 단백질 부족 + 탄수화물 균형 양호"
    mock_analysis_service.run.return_value = make_done_state(feedback_text=feedback_text)

    response = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(meal.id)},
        headers=auth_headers(_consented_user),
    )
    events = parse_sse_text(response.text)
    token_chunks = [e[1]["delta"] for e in events if e[0] == "token"]
    assert "".join(token_chunks) == feedback_text


async def test_stream_persists_meal_analysis_row(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """happy path — meal_analyses row INSERT 검증 + 두 번째 호출 UPDATE(row count 1 유지)."""
    from sqlalchemy import select

    from app.db.models.meal_analysis import MealAnalysis

    meal = await meal_factory(_consented_user)
    mock_analysis_service.run.return_value = make_done_state(fit_score=72)

    # 1차 호출 — INSERT.
    r1 = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(meal.id)},
        headers=auth_headers(_consented_user),
    )
    assert r1.status_code == 200

    async with app.state.session_maker() as session:
        rows = (
            (await session.execute(select(MealAnalysis).where(MealAnalysis.meal_id == meal.id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    first_updated_at = rows[0].updated_at
    assert rows[0].fit_score == 72

    # 2차 호출 — UPSERT(UPDATE 분기), row count 1 유지.
    mock_analysis_service.run.return_value = make_done_state(fit_score=85, fit_label="good")
    r2 = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(meal.id)},
        headers=auth_headers(_consented_user),
    )
    assert r2.status_code == 200

    async with app.state.session_maker() as session:
        rows = (
            (await session.execute(select(MealAnalysis).where(MealAnalysis.meal_id == meal.id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].fit_score == 85
    # updated_at 갱신 검증.
    assert rows[0].updated_at >= first_updated_at


async def test_stream_extra_field_rejected(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """body extra field 송신 → 400 (Pydantic extra='forbid' 1차 게이트)."""
    meal = await meal_factory(_consented_user)
    response = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(meal.id), "extra_field": "x"},
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 400


# CR Wave 1 D7 — Task 9.1 명시 12 케이스 중 누락 2건 보강.


async def test_stream_rate_limit_exceeded_returns_429(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory, monkeypatch
) -> None:
    """11번째 호출에서 429 + analysis.rate_limit.exceeded (RATE_LIMIT_LANGGRAPH=10/min).

    Redis 미설정 환경(test default)에서 hand-rolled 카운터를 *직접 mocking*해 11회째
    incr=11을 강제 — 실제 Redis 의존 회피.
    """
    from app.api.v1 import analysis as analysis_module

    call_count = {"n": 0}

    async def _mock_redis_incr(request, *, prefix, limit):
        call_count["n"] += 1
        if call_count["n"] > limit:
            from app.core.exceptions import AnalysisRateLimitExceededError

            raise AnalysisRateLimitExceededError(
                "분석 요청이 너무 많아요. 1분 후 다시 시도해주세요"
            )

    monkeypatch.setattr(analysis_module, "_redis_fixed_window_incr", _mock_redis_incr)

    meal = await meal_factory(_consented_user)
    mock_analysis_service.run.return_value = make_done_state(used_llm="gpt-4o-mini")

    # 1-10번째: 통과(429 미발생).
    for _ in range(10):
        r = await client.post(
            "/v1/analysis/stream",
            json={"meal_id": str(meal.id)},
            headers=auth_headers(_consented_user),
        )
        assert r.status_code == 200, f"call {_ + 1}: {r.status_code}"

    # 11번째: 429.
    response = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(meal.id)},
        headers=auth_headers(_consented_user),
    )
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "analysis.rate_limit.exceeded"


async def test_stream_empty_raw_text_emits_done_normally(
    client: AsyncClient, mock_analysis_service, _consented_user, meal_factory
) -> None:
    """빈 raw_text meal — mock state 정상 → token chunk 0건 + done 정상 emit (graceful)."""
    meal = await meal_factory(_consented_user, raw_text="")
    # feedback_text는 정상이라 token chunk는 일부 emit. raw_text 빈 것은 service.run
    # 입력이며 mock이 결과 state를 결정함 — 입력의 빈 값이 SSE 흐름을 깨지 않는지 검증.
    mock_analysis_service.run.return_value = make_done_state(
        feedback_text="입력이 비어있어요. 식단을 더 구체적으로 알려주세요.",
        used_llm="gpt-4o-mini",
    )

    response = await client.post(
        "/v1/analysis/stream",
        json={"meal_id": str(meal.id)},
        headers=auth_headers(_consented_user),
    )

    assert response.status_code == 200
    events = parse_sse_text(response.text)
    event_names = [e[0] for e in events]
    assert event_names[0] == "progress"
    assert event_names.count("done") == 1
    assert event_names[-1] == "done"
