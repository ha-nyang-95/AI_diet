"""Story 2.1 — ``/v1/meals`` 4 endpoint 통합 테스트 (AC #2-#5, #11).

22+ 케이스 (Story 1.5 21 케이스 패턴 정합):
- POST /v1/meals (AC2)        — 정상/ate_at 명시/동의 미통과/인증/빈 본문/2001자
- GET /v1/meals (AC3)         — user 격리/soft-deleted 제외/날짜 필터/인증/동의 무관/빈 결과
- PATCH /v1/meals/{id} (AC4)  — 정상/타 user/soft-deleted/없는 id/빈 body/동의 미통과
- DELETE /v1/meals/{id} (AC5) — 정상/이미 deleted/타 user/동의 미통과
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.consent import Consent
from app.db.models.meal import Meal
from app.db.models.user import User
from app.main import app
from tests.conftest import auth_headers

UserFactory = Callable[..., Awaitable[User]]
ConsentFactory = Callable[..., Awaitable[Consent]]


def _valid_meal_payload() -> dict[str, object]:
    return {"raw_text": "삼겹살 1인분, 김치찌개, 소주 2잔"}


async def _create_meal_for(
    user: User,
    *,
    raw_text: str = "테스트 식단",
    ate_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> Meal:
    """test DB에 meals row 직접 INSERT — API 통과 없이 fixture-style 생성."""
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        meal = Meal(
            user_id=user.id,
            raw_text=raw_text,
            **({"ate_at": ate_at} if ate_at is not None else {}),
            deleted_at=deleted_at,
        )
        session.add(meal)
        await session.commit()
        await session.refresh(meal)
        return meal


# --- POST /v1/meals (AC2) ---


async def test_post_meal_creates_returns_201(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals",
        json=_valid_meal_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body.keys()) == {
        "id",
        "user_id",
        "raw_text",
        "ate_at",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    assert body["raw_text"] == "삼겹살 1인분, 김치찌개, 소주 2잔"
    assert body["user_id"] == str(user.id)
    assert body["deleted_at"] is None
    assert body["ate_at"] is not None  # server_default(now()) fallback

    # DB row 직접 검증.
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(select(Meal).where(Meal.user_id == user.id))
        meals = result.scalars().all()
    assert len(meals) == 1
    assert meals[0].raw_text == "삼겹살 1인분, 김치찌개, 소주 2잔"
    assert meals[0].deleted_at is None


async def test_post_meal_with_explicit_ate_at_returns_201(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    explicit_ate_at = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)
    payload = {
        "raw_text": "어제 저녁 먹은 카레",
        "ate_at": explicit_ate_at.isoformat(),
    }
    response = await client.post(
        "/v1/meals",
        json=payload,
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # 서버 응답의 ate_at은 입력값과 동일한 시점이어야 함.
    assert datetime.fromisoformat(body["ate_at"]) == explicit_ate_at


async def test_post_meal_blocks_user_without_basic_consents_returns_403(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    user = await user_factory()
    response = await client.post(
        "/v1/meals",
        json=_valid_meal_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "consent.basic.missing"


async def test_post_meal_unauthenticated_returns_401(client: AsyncClient) -> None:
    response = await client.post("/v1/meals", json=_valid_meal_payload())
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.invalid"


async def test_post_meal_empty_raw_text_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    # 빈 문자열.
    response = await client.post(
        "/v1/meals",
        json={"raw_text": ""},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"

    # whitespace-only.
    response = await client.post(
        "/v1/meals",
        json={"raw_text": "   \n  "},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_post_meal_too_long_raw_text_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals",
        json={"raw_text": "가" * 2001},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_post_meal_extra_field_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """`extra="forbid"` 회귀 — silent unknown field 차단 (P6 / Review CR 2026-04-29)."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals",
        json={"raw_text": "테스트", "unknown_field": "x"},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_post_meal_naive_ate_at_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """naive datetime 거부 (P19 / D3 결정 — wire 명시성)."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals",
        # TZ suffix 없는 naive ISO datetime — Postgres timestamptz가 세션 TZ로 해석
        # → wire 모호성. 거부 mandate.
        json={"raw_text": "테스트", "ate_at": "2026-04-29T12:00:00"},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_post_meal_trims_raw_text_whitespace(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """raw_text 좌우 whitespace 정규화 (P1 — 모바일 zod.trim()과 wire 단일화)."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals",
        json={"raw_text": "  삼겹살 1인분  "},
        headers=auth_headers(user),
    )
    assert response.status_code == 201
    assert response.json()["raw_text"] == "삼겹살 1인분"


# --- GET /v1/meals (AC3) ---


async def test_get_meals_returns_user_only(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user_a = await user_factory()
    user_b = await user_factory()
    await consent_factory(user_a)
    await consent_factory(user_b)

    await _create_meal_for(user_a, raw_text="A의 식단")
    await _create_meal_for(user_b, raw_text="B의 식단")

    response = await client.get("/v1/meals", headers=auth_headers(user_a))
    assert response.status_code == 200
    body = response.json()
    raw_texts = [m["raw_text"] for m in body["meals"]]
    assert raw_texts == ["A의 식단"]
    assert all(m["user_id"] == str(user_a.id) for m in body["meals"])


async def test_get_meals_excludes_soft_deleted(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    active = await _create_meal_for(user, raw_text="살아있는 식단")
    await _create_meal_for(user, raw_text="삭제된 식단", deleted_at=datetime.now(UTC))

    response = await client.get("/v1/meals", headers=auth_headers(user))
    assert response.status_code == 200
    body = response.json()
    ids = [m["id"] for m in body["meals"]]
    assert ids == [str(active.id)]


async def test_get_meals_filter_by_date_range(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    # P7 — `datetime.now(UTC)`는 UTC 자정 근처 CI에서 flaky. 고정 reference로 결정성 확보.
    reference_now = datetime(2024, 6, 15, 12, 0, tzinfo=UTC)
    today = reference_now
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)

    await _create_meal_for(user, raw_text="오늘", ate_at=today)
    await _create_meal_for(user, raw_text="어제", ate_at=yesterday)
    await _create_meal_for(user, raw_text="이틀 전", ate_at=two_days_ago)

    # 어제 ~ 오늘만 (2건).
    response = await client.get(
        f"/v1/meals?from_date={yesterday.date().isoformat()}&to_date={today.date().isoformat()}",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    raw_texts = [m["raw_text"] for m in body["meals"]]
    assert "이틀 전" not in raw_texts
    assert {"오늘", "어제"} == set(raw_texts)


async def test_get_meals_from_after_to_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """`from_date > to_date` 거부 (P15 — typo/swap → silent empty list 회피)."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.get(
        "/v1/meals?from_date=2026-12-01&to_date=2026-11-01",
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "meals.query.invalid"


async def test_get_meals_cursor_not_supported_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """`cursor` 비-null 거부 (P18 / D2 결정 — silent 무시 → 무한 루프 footgun 차단)."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.get(
        "/v1/meals?cursor=anything",
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "meals.query.invalid"


async def test_get_meals_unauthenticated_returns_401(client: AsyncClient) -> None:
    response = await client.get("/v1/meals")
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.invalid"


async def test_get_meals_no_consent_required(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """동의 미통과 사용자도 자기 데이터 조회는 허용 — PIPA Art.35 회귀 차단."""
    user = await user_factory()
    # consent_factory 호출 X.

    response = await client.get("/v1/meals", headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json() == {"meals": [], "next_cursor": None}


async def test_get_meals_empty_returns_200_with_empty_list(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    response = await client.get("/v1/meals", headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json() == {"meals": [], "next_cursor": None}


# --- PATCH /v1/meals/{meal_id} (AC4) ---


async def test_patch_meal_updates_raw_text_returns_200(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)
    meal = await _create_meal_for(user, raw_text="수정 전")
    original_updated_at = meal.updated_at

    response = await client.patch(
        f"/v1/meals/{meal.id}",
        json={"raw_text": "수정 후"},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["raw_text"] == "수정 후"
    assert body["id"] == str(meal.id)
    # updated_at은 갱신되어야 함 (>= 원래 값 — clock 동일 tick에 같을 수 있어 ge 비교).
    assert datetime.fromisoformat(body["updated_at"]) >= original_updated_at


async def test_patch_meal_other_user_returns_404(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user_a = await user_factory()
    user_b = await user_factory()
    await consent_factory(user_a)
    await consent_factory(user_b)
    meal_a = await _create_meal_for(user_a, raw_text="A의 식단")

    response = await client.patch(
        f"/v1/meals/{meal_a.id}",
        json={"raw_text": "B가 수정 시도"},
        headers=auth_headers(user_b),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "meals.not_found"


async def test_patch_meal_soft_deleted_returns_404(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)
    deleted_meal = await _create_meal_for(
        user, raw_text="이미 삭제됨", deleted_at=datetime.now(UTC)
    )

    response = await client.patch(
        f"/v1/meals/{deleted_meal.id}",
        json={"raw_text": "복구 시도"},
        headers=auth_headers(user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "meals.not_found"


async def test_patch_meal_nonexistent_id_returns_404(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    fake_id = uuid.uuid4()
    response = await client.patch(
        f"/v1/meals/{fake_id}",
        json={"raw_text": "유령 meal 수정"},
        headers=auth_headers(user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "meals.not_found"


async def test_patch_meal_empty_body_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)
    meal = await _create_meal_for(user)

    response = await client.patch(
        f"/v1/meals/{meal.id}",
        json={},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_patch_meal_explicit_null_raw_text_acts_as_no_op(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """`raw_text=null`은 *필드 부재*와 동등 처리 — no-op (D4 결정 의도 박제 / P6)."""
    user = await user_factory()
    await consent_factory(user)
    meal = await _create_meal_for(user, raw_text="원래 텍스트")
    new_ate_at = datetime(2024, 6, 15, 12, 0, tzinfo=UTC)

    response = await client.patch(
        f"/v1/meals/{meal.id}",
        json={"raw_text": None, "ate_at": new_ate_at.isoformat()},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # raw_text는 미변경, ate_at만 갱신.
    assert body["raw_text"] == "원래 텍스트"
    assert datetime.fromisoformat(body["ate_at"]) == new_ate_at


async def test_patch_meal_naive_ate_at_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """PATCH도 naive datetime 거부 (P19 / D3 결정 정합)."""
    user = await user_factory()
    await consent_factory(user)
    meal = await _create_meal_for(user)

    response = await client.patch(
        f"/v1/meals/{meal.id}",
        json={"ate_at": "2026-04-29T12:00:00"},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_patch_meal_blocks_user_without_basic_consents_returns_403(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    user = await user_factory()
    meal = await _create_meal_for(user)

    response = await client.patch(
        f"/v1/meals/{meal.id}",
        json={"raw_text": "수정 시도"},
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "consent.basic.missing"


# --- DELETE /v1/meals/{meal_id} (AC5) ---


async def test_delete_meal_soft_deletes_returns_204(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)
    meal = await _create_meal_for(user)

    response = await client.delete(
        f"/v1/meals/{meal.id}",
        headers=auth_headers(user),
    )
    assert response.status_code == 204
    assert response.content == b""

    # DB 확인 — deleted_at NOT NULL 이지만 row 자체는 존재.
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(select(Meal).where(Meal.id == meal.id))
        row = result.scalar_one()
    assert row.deleted_at is not None

    # 후속 GET에서 제외 확인.
    response = await client.get("/v1/meals", headers=auth_headers(user))
    assert response.json()["meals"] == []


async def test_delete_meal_already_deleted_returns_404(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)
    deleted_meal = await _create_meal_for(user, deleted_at=datetime.now(UTC))

    response = await client.delete(
        f"/v1/meals/{deleted_meal.id}",
        headers=auth_headers(user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "meals.not_found"


async def test_delete_meal_other_user_returns_404(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user_a = await user_factory()
    user_b = await user_factory()
    await consent_factory(user_a)
    await consent_factory(user_b)
    meal_a = await _create_meal_for(user_a)

    response = await client.delete(
        f"/v1/meals/{meal_a.id}",
        headers=auth_headers(user_b),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "meals.not_found"


async def test_delete_meal_blocks_user_without_basic_consents_returns_403(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    user = await user_factory()
    meal = await _create_meal_for(user)

    response = await client.delete(
        f"/v1/meals/{meal.id}",
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "consent.basic.missing"
