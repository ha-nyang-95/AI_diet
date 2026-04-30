"""Story 2.1 — ``/v1/meals`` 4 endpoint 통합 테스트 (AC #2-#5, #11).

22+ 케이스 (Story 1.5 21 케이스 패턴 정합) + Story 2.2 image_key 8 케이스:
- POST /v1/meals (AC2)        — 정상/ate_at 명시/동의 미통과/인증/빈 본문/2001자
- GET /v1/meals (AC3)         — user 격리/soft-deleted 제외/날짜 필터/인증/동의 무관/빈 결과
- PATCH /v1/meals/{id} (AC4)  — 정상/타 user/soft-deleted/없는 id/빈 body/동의 미통과
- DELETE /v1/meals/{id} (AC5) — 정상/이미 deleted/타 user/동의 미통과
- Story 2.2 image_key (AC12)  — 사진-only/raw_text+image_key/foreign 거부/no-input 거부/
                                 image_url derive/null when no key/explicit null clear PATCH/
                                 PATCH foreign 거부
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters import r2 as r2_adapter
from app.core.config import settings as _settings
from app.db.models.consent import Consent
from app.db.models.meal import Meal
from app.db.models.user import User
from app.main import app
from tests.conftest import auth_headers


@pytest.fixture
def _r2_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """test settings에 R2 환경변수 5종 + boto3 client singleton 무효화 (P11 fix —
    test_meals_images_router.py 패턴 정합).

    P21 — `head_object_exists`는 기본 *True* mock(객체 존재 가정). 미존재 시나리오는
    별도 테스트에서 monkeypatch override.
    """
    monkeypatch.setattr(_settings, "r2_account_id", "test-account-id")
    monkeypatch.setattr(_settings, "r2_access_key_id", "test-access-key")
    monkeypatch.setattr(_settings, "r2_secret_access_key", "test-secret-key")
    monkeypatch.setattr(_settings, "r2_bucket", "test-bucket")
    monkeypatch.setattr(_settings, "r2_public_base_url", "https://cdn.example.com")
    r2_adapter._reset_client_for_tests()
    monkeypatch.setattr(r2_adapter, "head_object_exists", lambda image_key: True)


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
    image_key: str | None = None,
    parsed_items: list[dict[str, object]] | None = None,
) -> Meal:
    """test DB에 meals row 직접 INSERT — API 통과 없이 fixture-style 생성.

    Story 2.3: ``parsed_items`` 옵션 인자 추가 (default None) — 회귀 차단 + Story 2.3
    parsed_items 흐름 fixture 지원.
    """
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        meal = Meal(
            user_id=user.id,
            raw_text=raw_text,
            **({"ate_at": ate_at} if ate_at is not None else {}),
            deleted_at=deleted_at,
            image_key=image_key,
            parsed_items=parsed_items,
        )
        session.add(meal)
        await session.commit()
        await session.refresh(meal)
        return meal


# Story 2.2 — image_key는 `meals/{user_id}/{uuid}.{ext}` 형식. 테스트는 임의 UUID로.
_TEST_IMAGE_EXT = "jpg"


def _image_key_for(user: User, ext: str = _TEST_IMAGE_EXT) -> str:
    """user-scoped 유효한 image_key (테스트용) — `meals/{user_id}/{random_uuid}.{ext}`."""
    return f"meals/{user.id}/{uuid.uuid4()}.{ext}"


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
    # Story 2.4 — 11 필드 (Story 2.3 10 + analysis_summary forward-compat 슬롯).
    assert set(body.keys()) == {
        "id",
        "user_id",
        "raw_text",
        "ate_at",
        "created_at",
        "updated_at",
        "deleted_at",
        "image_key",
        "image_url",
        "parsed_items",
        "analysis_summary",
    }
    assert body["raw_text"] == "삼겹살 1인분, 김치찌개, 소주 2잔"
    assert body["user_id"] == str(user.id)
    assert body["deleted_at"] is None
    assert body["ate_at"] is not None  # server_default(now()) fallback
    # 텍스트-only 입력 — image_key/image_url/parsed_items는 None.
    assert body["image_key"] is None
    assert body["image_url"] is None
    assert body["parsed_items"] is None
    # Story 2.4 — analysis_summary는 항상 None (Story 3.x에서 meal_analyses JOIN 책임).
    assert body["analysis_summary"] is None

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


async def test_list_meals_kst_boundary_includes_pre_dawn_korean_time(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """W50 회귀 차단 핵심 — KST 0-9시 식단(UTC 전날)이 KST 일자 조회에 포함.

    Story 2.4 (D1 결정): 날짜 필터를 ``Asia/Seoul`` TZ 자정 boundary로 해석. ``ate_at
    = 2026-04-30T03:00:00+09:00`` (UTC ``2026-04-29T18:00:00Z``)이 ``from_date=
    2026-04-30`` 쿼리에 포함되어야 함. baseline 동작은 *제외*(W50 결함).
    """
    user = await user_factory()
    await consent_factory(user)

    kst = ZoneInfo("Asia/Seoul")
    pre_dawn_kst = datetime(2026, 4, 30, 3, 0, tzinfo=kst)
    await _create_meal_for(user, raw_text="새벽 식단", ate_at=pre_dawn_kst)

    response = await client.get(
        "/v1/meals?from_date=2026-04-30&to_date=2026-04-30",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    raw_texts = [m["raw_text"] for m in body["meals"]]
    assert "새벽 식단" in raw_texts


async def test_list_meals_kst_boundary_excludes_next_day_pre_dawn(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """다음날 KST 0-9시 식단은 *제외* 단언 — to_date upper boundary 검증."""
    user = await user_factory()
    await consent_factory(user)

    kst = ZoneInfo("Asia/Seoul")
    next_day_pre_dawn_kst = datetime(2026, 5, 1, 1, 0, tzinfo=kst)
    await _create_meal_for(user, raw_text="다음날 새벽", ate_at=next_day_pre_dawn_kst)

    response = await client.get(
        "/v1/meals?from_date=2026-04-30&to_date=2026-04-30",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    raw_texts = [m["raw_text"] for m in body["meals"]]
    assert "다음날 새벽" not in raw_texts
    # CR P9 — 필터가 끊겨 0건이어도 `not in` 단언이 통과하는 false positive 차단.
    # 본 테스트는 *해당 일자 식단을 1건 생성*하지 않았으므로 결과 0건이 정확.
    assert len(body["meals"]) == 0


async def test_list_meals_from_date_only_kst_lower_bound(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """``from_date`` 단독 — KST 자정 이상만 포함."""
    user = await user_factory()
    await consent_factory(user)

    kst = ZoneInfo("Asia/Seoul")
    before = datetime(2026, 4, 29, 23, 30, tzinfo=kst)  # KST 23:30 — from 이전 일자
    after = datetime(2026, 4, 30, 0, 30, tzinfo=kst)  # KST 00:30 — from 일자
    await _create_meal_for(user, raw_text="전날 23시반", ate_at=before)
    await _create_meal_for(user, raw_text="당일 0시반", ate_at=after)

    response = await client.get(
        "/v1/meals?from_date=2026-04-30",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    raw_texts = [m["raw_text"] for m in response.json()["meals"]]
    assert "전날 23시반" not in raw_texts
    assert "당일 0시반" in raw_texts


async def test_list_meals_to_date_only_kst_upper_bound_inclusive(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """``to_date`` 단독 — to_date 일자 KST 자정 자체는 포함, 다음날 KST 자정 미만."""
    user = await user_factory()
    await consent_factory(user)

    kst = ZoneInfo("Asia/Seoul")
    same_day_late = datetime(2026, 4, 30, 23, 59, tzinfo=kst)
    next_day_early = datetime(2026, 5, 1, 0, 30, tzinfo=kst)
    await _create_meal_for(user, raw_text="당일 23시 59분", ate_at=same_day_late)
    await _create_meal_for(user, raw_text="다음날 0시 30분", ate_at=next_day_early)

    response = await client.get(
        "/v1/meals?to_date=2026-04-30",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    raw_texts = [m["raw_text"] for m in response.json()["meals"]]
    assert "당일 23시 59분" in raw_texts
    assert "다음날 0시 30분" not in raw_texts


async def test_list_meals_no_date_filter_returns_desc_order(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """D2 결정 — 날짜 필터 미적용 시 ate_at DESC (최근 식단 우선)."""
    user = await user_factory()
    await consent_factory(user)

    kst = ZoneInfo("Asia/Seoul")
    earlier = datetime(2026, 4, 30, 8, 0, tzinfo=kst)
    later = datetime(2026, 4, 30, 19, 0, tzinfo=kst)
    await _create_meal_for(user, raw_text="아침", ate_at=earlier)
    await _create_meal_for(user, raw_text="저녁", ate_at=later)

    response = await client.get("/v1/meals", headers=auth_headers(user))
    assert response.status_code == 200
    raw_texts = [m["raw_text"] for m in response.json()["meals"]]
    assert raw_texts == ["저녁", "아침"]  # DESC


async def test_list_meals_with_date_filter_returns_asc_order(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """D2 결정 — 날짜 필터 활성 시 ate_at ASC (시간순 — 아침→저녁)."""
    user = await user_factory()
    await consent_factory(user)

    kst = ZoneInfo("Asia/Seoul")
    morning = datetime(2026, 4, 30, 8, 0, tzinfo=kst)
    evening = datetime(2026, 4, 30, 19, 0, tzinfo=kst)
    await _create_meal_for(user, raw_text="아침", ate_at=morning)
    await _create_meal_for(user, raw_text="저녁", ate_at=evening)

    response = await client.get(
        "/v1/meals?from_date=2026-04-30&to_date=2026-04-30",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    raw_texts = [m["raw_text"] for m in response.json()["meals"]]
    assert raw_texts == ["아침", "저녁"]  # ASC


async def test_list_meals_response_includes_analysis_summary_null(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """Story 2.4 — 응답에 ``analysis_summary: null`` 키 항상 노출 (스키마 안정성)."""
    user = await user_factory()
    await consent_factory(user)
    await _create_meal_for(user, raw_text="분석 슬롯 테스트")

    response = await client.get("/v1/meals", headers=auth_headers(user))
    assert response.status_code == 200
    meals = response.json()["meals"]
    assert len(meals) == 1
    assert "analysis_summary" in meals[0]
    assert meals[0]["analysis_summary"] is None


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


# --- Story 2.2 image_key 흐름 (AC4 / AC5 / AC12) ---------------------------------


async def test_post_meal_with_image_key_only_creates_with_placeholder(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
) -> None:
    """사진-only 입력 — `raw_text`는 자동 placeholder, `image_key` 저장.
    P10/P11 fix — `_r2_configured` 공통 fixture로 R2 설정 단일화 (typing object 제거).
    """
    user = await user_factory()
    await consent_factory(user)
    image_key = _image_key_for(user)

    response = await client.post(
        "/v1/meals",
        json={"image_key": image_key},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["raw_text"] == "(사진 입력)"
    assert body["image_key"] == image_key
    assert body["image_url"] is not None and image_key in body["image_url"]


async def test_post_meal_with_image_key_and_raw_text_stores_both(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
) -> None:
    user = await user_factory()
    await consent_factory(user)
    image_key = _image_key_for(user)

    response = await client.post(
        "/v1/meals",
        json={"raw_text": "삼겹살 + 사진", "image_key": image_key},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["raw_text"] == "삼겹살 + 사진"  # placeholder 미덮어씀
    assert body["image_key"] == image_key


async def test_post_meal_foreign_image_key_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """다른 사용자 prefix image_key 첨부 거부 — cross-user 도용 차단."""
    user_a = await user_factory()
    user_b = await user_factory()
    await consent_factory(user_a)

    foreign_key = _image_key_for(user_b)  # user_b의 prefix지만 user_a가 송신.

    response = await client.post(
        "/v1/meals",
        json={"image_key": foreign_key},
        headers=auth_headers(user_a),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "meals.image.foreign_key_rejected"


async def test_post_meal_no_raw_text_no_image_key_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """둘 다 None 거부 — 빈 식단 row 차단."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals",
        json={},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_meal_response_image_url_null_when_no_image_key(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals",
        json={"raw_text": "텍스트만"},
        headers=auth_headers(user),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["image_key"] is None
    assert body["image_url"] is None


async def test_patch_meal_can_clear_image_key_with_explicit_null(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """PATCH `{"image_key": null}` → DB image_key NULL + 응답 image_url null.
    raw_text는 unchanged (D4 시맨틱 — placeholder 잔존).
    """
    user = await user_factory()
    await consent_factory(user)
    image_key = _image_key_for(user)
    meal = await _create_meal_for(user, raw_text="(사진 입력)", image_key=image_key)

    response = await client.patch(
        f"/v1/meals/{meal.id}",
        json={"image_key": None},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["image_key"] is None
    assert body["image_url"] is None
    # raw_text는 미변경 (placeholder 잔존 — UI에서 갱신).
    assert body["raw_text"] == "(사진 입력)"

    # DB 직접 검증.
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(select(Meal).where(Meal.id == meal.id))
        row = result.scalar_one()
    assert row.image_key is None


async def test_patch_meal_replaces_image_key(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
) -> None:
    """PATCH로 새 image_key 명시 송신 → 갱신."""
    user = await user_factory()
    await consent_factory(user)
    old_key = _image_key_for(user)
    new_key = _image_key_for(user)
    meal = await _create_meal_for(user, image_key=old_key)

    response = await client.patch(
        f"/v1/meals/{meal.id}",
        json={"image_key": new_key},
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    assert response.json()["image_key"] == new_key


async def test_patch_meal_foreign_image_key_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """PATCH로 타 사용자 prefix image_key 송신 — 거부."""
    user_a = await user_factory()
    user_b = await user_factory()
    await consent_factory(user_a)
    meal = await _create_meal_for(user_a)
    foreign_key = _image_key_for(user_b)

    response = await client.patch(
        f"/v1/meals/{meal.id}",
        json={"image_key": foreign_key},
        headers=auth_headers(user_a),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "meals.image.foreign_key_rejected"


# --- Code Review (2026-04-29) — P4/P20b/P21 회귀 테스트 ----------------------------


async def test_meal_response_includes_image_url_when_image_key_set(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
) -> None:
    """P4 — AC12 명시 테스트. `image_url`이 정확히 `f"{r2_public_base_url}/{image_key}"`.

    `_r2_configured` fixture가 `r2_public_base_url="https://cdn.example.com"` 설정 →
    `image_url == "https://cdn.example.com/{image_key}"` *exact-equality* 검증.
    기존 `test_post_meal_with_image_key_only_creates_with_placeholder`는 substring
    `image_key in image_url`만 검증해 derivation 공식 검증이 누락됐던 갭 메움.
    """
    user = await user_factory()
    await consent_factory(user)
    image_key = _image_key_for(user)

    response = await client.post(
        "/v1/meals",
        json={"image_key": image_key},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["image_url"] == f"https://cdn.example.com/{image_key}"


async def test_post_meal_image_key_with_traversal_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """P20b — `..` traversal 차단. Pydantic regex(P2)가 1차 게이트로 reject.

    `meals/<self>/../<other>/x.jpg` 형태는 prefix 검사만으로는 통과하지만 regex는
    UUID 형식 + 단일 slash만 허용 → `validation.error`로 차단(ownership reject 전 단계).
    """
    user_a = await user_factory()
    user_b = await user_factory()
    await consent_factory(user_a)

    traversal_key = f"meals/{user_a.id}/../{user_b.id}/{uuid.uuid4()}.jpg"

    response = await client.post(
        "/v1/meals",
        json={"image_key": traversal_key},
        headers=auth_headers(user_a),
    )
    # Pydantic pattern fail → 400 + validation.error.
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_post_meal_image_key_invalid_format_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """P20b — 빈 문자열·잘못된 ext·malformed 키는 Pydantic regex로 reject."""
    user = await user_factory()
    await consent_factory(user)

    invalid_keys = [
        "",  # 빈 문자열
        "meals/x/y.jpg",  # UUID 아님
        f"meals/{user.id}/{uuid.uuid4()}.gif",  # ext whitelist 위반
        f"meals/{user.id}/{uuid.uuid4()}.jpg/extra",  # 추가 segment
        f"meals/{user.id}//{uuid.uuid4()}.jpg",  # duplicate slash
    ]

    for bad_key in invalid_keys:
        response = await client.post(
            "/v1/meals",
            json={"image_key": bad_key},
            headers=auth_headers(user),
        )
        assert response.status_code == 400, (
            f"expected 400 for key={bad_key!r}, got {response.status_code}"
        )
        assert response.json()["code"] == "validation.error", f"unexpected code for key={bad_key!r}"


async def test_post_meal_unuploaded_image_key_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P21 — `head_object_exists` False 시 `meals.image.not_uploaded` 400.

    클라이언트가 presign 발급 후 PUT 미수행하고 image_key를 attach 시도하는 시나리오 —
    R2 storage abuse + 깨진 image_url 방어.
    """
    # _r2_configured는 head_object_exists를 True mock — 본 테스트는 False로 override.
    monkeypatch.setattr(r2_adapter, "head_object_exists", lambda image_key: False)

    user = await user_factory()
    await consent_factory(user)
    image_key = _image_key_for(user)

    response = await client.post(
        "/v1/meals",
        json={"image_key": image_key},
        headers=auth_headers(user),
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "meals.image.not_uploaded"


# --- Story 2.3 parsed_items 흐름 (AC4 / AC11) -----------------------------------


def _parsed_items_payload() -> list[dict[str, object]]:
    """전형적인 OCR 결과 — 두 항목, 모두 high confidence."""
    return [
        {"name": "짜장면", "quantity": "1인분", "confidence": 0.92},
        {"name": "군만두", "quantity": "4개", "confidence": 0.88},
    ]


async def test_post_meal_with_parsed_items_creates_with_text_overwrite(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
) -> None:
    """클라이언트가 raw_text + image_key + parsed_items 동시 송신 — raw_text 우선."""
    user = await user_factory()
    await consent_factory(user)
    image_key = _image_key_for(user)
    parsed_items = _parsed_items_payload()

    response = await client.post(
        "/v1/meals",
        json={
            "raw_text": "짜장면 1인분, 군만두 4개",
            "image_key": image_key,
            "parsed_items": parsed_items,
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["raw_text"] == "짜장면 1인분, 군만두 4개"
    assert body["parsed_items"] == parsed_items
    assert body["image_key"] == image_key


async def test_post_meal_with_image_key_and_parsed_items_no_raw_text_uses_server_format(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
) -> None:
    """DF2 자연 해소 — raw_text 미송신 + parsed_items 송신 시 서버 fallback 변환.

    ``(사진 입력)`` placeholder 진입 차단 + 클라이언트-서버 변환 룰 단일화.
    """
    user = await user_factory()
    await consent_factory(user)
    image_key = _image_key_for(user)
    parsed_items = _parsed_items_payload()

    response = await client.post(
        "/v1/meals",
        json={
            "image_key": image_key,
            "parsed_items": parsed_items,
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # 서버 fallback 변환 — `name quantity` 형식, ", " join.
    assert body["raw_text"] == "짜장면 1인분, 군만두 4개"
    # placeholder `(사진 입력)`은 진입하지 않아야 함 (DF2 자연 해소 검증).
    assert body["raw_text"] != "(사진 입력)"
    assert body["parsed_items"] == parsed_items


async def test_post_meal_parsed_items_only_no_image_key_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """parsed_items 단독 + image_key 부재 — 의미 없음 (Pydantic _at_least_one_input)."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals",
        json={"parsed_items": _parsed_items_payload()},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_post_meal_parsed_items_max_length_20_enforced(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
    _r2_configured: None,
) -> None:
    """parsed_items 21개 — Pydantic max_length 1차 게이트."""
    user = await user_factory()
    await consent_factory(user)
    image_key = _image_key_for(user)
    items_21 = [{"name": f"항목{i}", "quantity": "1개", "confidence": 0.9} for i in range(21)]

    response = await client.post(
        "/v1/meals",
        json={"image_key": image_key, "parsed_items": items_21},
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"


async def test_patch_meal_can_clear_parsed_items_with_explicit_null(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """PATCH ``parsed_items=null`` — DB ``parsed_items=NULL`` + 응답 ``parsed_items=null``.

    image_key 시맨틱 정합 (D4와 다른 시맨틱 — explicit null = 클리어).
    """
    user = await user_factory()
    await consent_factory(user)
    parsed_items = _parsed_items_payload()
    meal = await _create_meal_for(user, parsed_items=parsed_items)

    response = await client.patch(
        f"/v1/meals/{meal.id}",
        json={"parsed_items": None},
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    assert response.json()["parsed_items"] is None

    # DB 직접 검증.
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(select(Meal).where(Meal.id == meal.id))
        refreshed = result.scalar_one()
    assert refreshed.parsed_items is None


async def test_meal_response_includes_parsed_items_when_set(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """기존 row의 parsed_items가 응답에 list[dict] 그대로 forward (fixture 직접 INSERT)."""
    user = await user_factory()
    await consent_factory(user)
    parsed_items = _parsed_items_payload()
    await _create_meal_for(user, parsed_items=parsed_items)

    response = await client.get("/v1/meals", headers=auth_headers(user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["meals"]) == 1
    assert body["meals"][0]["parsed_items"] == parsed_items


# --- Story 2.5 — POST /v1/meals Idempotency-Key 처리 (W46 흡수) ---------------


def _new_idempotency_key() -> str:
    """UUID v4 — 라우터의 ``_IDEMPOTENCY_KEY_PATTERN`` 통과 보장."""
    return str(uuid.uuid4())


async def test_post_meal_with_idempotency_key_first_time_returns_201_with_key_persisted(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """첫 송신 → 201 + DB row의 ``idempotency_key`` 저장 단언."""
    user = await user_factory()
    await consent_factory(user)
    key = _new_idempotency_key()

    response = await client.post(
        "/v1/meals",
        json=_valid_meal_payload(),
        headers={**auth_headers(user), "Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # 응답 wire에는 idempotency_key 노출 X (Story 2.5 D1 — 클라이언트 입력 echo 회피).
    assert "idempotency_key" not in body

    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(select(Meal).where(Meal.user_id == user.id))
        meals = result.scalars().all()
    assert len(meals) == 1
    assert meals[0].idempotency_key == key


async def test_post_meal_with_idempotency_key_duplicate_returns_200_same_row(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """같은 헤더 두 번 송신 → 두 응답 모두 같은 ``meal.id`` + 두 번째는 200 (W46 closed 단언)."""
    user = await user_factory()
    await consent_factory(user)
    key = _new_idempotency_key()
    headers = {**auth_headers(user), "Idempotency-Key": key}

    first = await client.post("/v1/meals", json=_valid_meal_payload(), headers=headers)
    assert first.status_code == 201, first.text
    first_body = first.json()

    second = await client.post("/v1/meals", json=_valid_meal_payload(), headers=headers)
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["id"] == first_body["id"]

    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(select(Meal).where(Meal.user_id == user.id))
        meals = result.scalars().all()
    assert len(meals) == 1


async def test_post_meal_without_idempotency_key_creates_new_row(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """헤더 미송신 → 201 + ``idempotency_key IS NULL`` (회귀 차단)."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals",
        json=_valid_meal_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text

    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(select(Meal).where(Meal.user_id == user.id))
        meal = result.scalar_one()
    assert meal.idempotency_key is None


async def test_post_meal_with_idempotency_key_invalid_uuid_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """``Idempotency-Key: not-a-uuid`` → 400 + code ``meals.idempotency_key.invalid``."""
    user = await user_factory()
    await consent_factory(user)

    response = await client.post(
        "/v1/meals",
        json=_valid_meal_payload(),
        headers={**auth_headers(user), "Idempotency-Key": "not-a-uuid"},
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "meals.idempotency_key.invalid"


async def test_post_meal_with_idempotency_key_invalid_v4_format_returns_400(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """UUID v1 형식 → 400 (`v4` 강제 — 13번째 nibble은 4여야 함)."""
    user = await user_factory()
    await consent_factory(user)
    # UUID v1 sample (13번째 nibble = '1'). v4 regex `4[0-9a-fA-F]{3}` 미일치.
    uuid_v1 = "c232ab00-9414-11ec-b909-0242ac120002"

    response = await client.post(
        "/v1/meals",
        json=_valid_meal_payload(),
        headers={**auth_headers(user), "Idempotency-Key": uuid_v1},
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "meals.idempotency_key.invalid"


async def test_post_meal_with_idempotency_key_different_users_isolated(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """사용자 A의 키를 B가 송신 → B의 user_id 정합 row 신규 생성 (200 X)."""
    user_a = await user_factory()
    user_b = await user_factory()
    await consent_factory(user_a)
    await consent_factory(user_b)
    key = _new_idempotency_key()

    first = await client.post(
        "/v1/meals",
        json=_valid_meal_payload(),
        headers={**auth_headers(user_a), "Idempotency-Key": key},
    )
    assert first.status_code == 201, first.text
    first_body = first.json()

    second = await client.post(
        "/v1/meals",
        json=_valid_meal_payload(),
        headers={**auth_headers(user_b), "Idempotency-Key": key},
    )
    # B는 별 row 신규 생성 — 201 (200 X).
    assert second.status_code == 201, second.text
    second_body = second.json()
    assert second_body["id"] != first_body["id"]
    assert second_body["user_id"] == str(user_b.id)


async def test_post_meal_with_idempotency_key_conflicts_with_deleted_returns_409(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """A가 key X로 식단 생성 → soft delete → 같은 key X로 재 POST → 409 +
    code ``meals.idempotency_key.conflict_deleted``."""
    user = await user_factory()
    await consent_factory(user)
    key = _new_idempotency_key()
    headers = {**auth_headers(user), "Idempotency-Key": key}

    first = await client.post("/v1/meals", json=_valid_meal_payload(), headers=headers)
    assert first.status_code == 201, first.text
    meal_id = first.json()["id"]

    delete_resp = await client.delete(f"/v1/meals/{meal_id}", headers=auth_headers(user))
    assert delete_resp.status_code == 204

    second = await client.post("/v1/meals", json=_valid_meal_payload(), headers=headers)
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "meals.idempotency_key.conflict_deleted"


async def test_post_meal_with_idempotency_key_race_simulated_two_inserts_same_key(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """동시 2 POST 같은 key → 둘 다 같은 ``meal.id`` (1 INSERT, 1 race-loser → replay)."""
    import asyncio as _asyncio

    user = await user_factory()
    await consent_factory(user)
    key = _new_idempotency_key()
    headers = {**auth_headers(user), "Idempotency-Key": key}

    first, second = await _asyncio.gather(
        client.post("/v1/meals", json=_valid_meal_payload(), headers=headers),
        client.post("/v1/meals", json=_valid_meal_payload(), headers=headers),
    )
    statuses = sorted([first.status_code, second.status_code])
    # CR P4 — race-loser는 IntegrityError → replay SELECT 200, race-winner는 INSERT 201.
    # 두 응답 모두 200(둘 다 SELECT-only)이면 INSERT 미발생 — 잘못된 구현이라 거부.
    # 단일 정상 outcome: 정확히 1건 201 + 1건 200.
    assert statuses == [200, 201], (
        f"race must produce exactly one INSERT (201) + one replay (200), got {statuses}"
    )
    assert first.json()["id"] == second.json()["id"]

    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(select(Meal).where(Meal.user_id == user.id))
        meals = result.scalars().all()
    assert len(meals) == 1


async def test_post_meal_idempotency_key_idempotent_replay_does_not_change_raw_text(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """같은 key + 다른 raw_text 두 번째 POST → 두 응답 모두 첫 raw_text (body diff 무시)."""
    user = await user_factory()
    await consent_factory(user)
    key = _new_idempotency_key()
    headers = {**auth_headers(user), "Idempotency-Key": key}

    first = await client.post("/v1/meals", json={"raw_text": "원본 식단 A"}, headers=headers)
    assert first.status_code == 201, first.text
    first_body = first.json()
    assert first_body["raw_text"] == "원본 식단 A"

    second = await client.post("/v1/meals", json={"raw_text": "다른 식단 B"}, headers=headers)
    assert second.status_code == 200, second.text
    # Stripe/Toss 표준 — 키 == 한 번 시맨틱 (body dedup X). 첫 raw_text 그대로 replay.
    assert second.json()["raw_text"] == "원본 식단 A"


async def test_patch_meal_with_idempotency_key_header_ignored(
    client: AsyncClient,
    user_factory: UserFactory,
    consent_factory: ConsentFactory,
) -> None:
    """PATCH에 ``Idempotency-Key`` 송신 — 헤더 무시 + 정상 처리 (회귀 0건)."""
    user = await user_factory()
    await consent_factory(user)
    meal = await _create_meal_for(user, raw_text="기존")

    response = await client.patch(
        f"/v1/meals/{meal.id}",
        json={"raw_text": "수정"},
        headers={**auth_headers(user), "Idempotency-Key": _new_idempotency_key()},
    )
    assert response.status_code == 200, response.text
    assert response.json()["raw_text"] == "수정"
