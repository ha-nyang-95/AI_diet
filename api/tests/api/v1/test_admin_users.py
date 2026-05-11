"""Story 7.2 — ``app/api/v1/admin.py`` 6 endpoint 통합 테스트.

테스트 케이스 분포 (총 45):
- AC1 검색 (12): email/UUID prefix + 마스킹 + cursor + escape + 권한 가드
- AC2 상세 (8): 마스킹 PII + 미존재 + soft-deleted + 알레르기 등
- AC3 식단 이력 (7): soft-deleted 포함 + raw_text length-only + analysis join
- AC4 피드백 로그 (5): 9 필드 + feedback_text 부재 + cursor
- AC5 프로필 수정 (8): partial + invariant + soft-deleted 거부
- AC6 식단 삭제 (5): soft delete + enumeration 차단

회귀 가드: Story 7.1 ``test_admin_auth_baseline.py`` 10 케이스 + Story 1.2 admin auth
5 케이스 + Story 5.1 patch_health_profile 베이스라인 + Story 2.1 delete_meal 베이스라인
모두 별 파일 owner 그대로 유지(본 파일은 *admin.py business action* owner).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import update as sa_update

from app.core.security import create_admin_token, create_user_token
from app.db.models.meal import Meal
from app.db.models.meal_analysis import MealAnalysis
from app.db.models.user import User
from app.main import app
from tests.conftest import UserFactory


def _admin_headers(admin: User) -> dict[str, str]:
    """admin JWT를 Authorization 헤더로 직조."""
    token = create_admin_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


# --- meal/meal_analysis 직접 INSERT helpers (test-only) -----------------


async def _insert_meal(
    *,
    user_id: uuid.UUID,
    raw_text: str = "짜장면 1인분",
    ate_at: datetime | None = None,
    deleted_at: datetime | None = None,
    image_key: str | None = None,
    parsed_items: list[dict] | None = None,
) -> Meal:
    session_maker = app.state.session_maker
    async with session_maker() as session:
        meal = Meal(
            user_id=user_id,
            raw_text=raw_text,
            ate_at=ate_at if ate_at is not None else datetime.now(UTC),
            deleted_at=deleted_at,
            image_key=image_key,
            parsed_items=parsed_items,
        )
        session.add(meal)
        await session.commit()
        await session.refresh(meal)
        return meal


async def _insert_meal_analysis(
    *,
    meal: Meal,
    fit_score: int = 75,
    fit_score_label: str = "good",
    fit_reason: str = "ok",
    feedback_summary: str = "균형 잡힌 한 끼입니다.",
    feedback_text: str = "전반적으로 좋습니다.",
    used_llm: str = "gpt-4o-mini",
    created_at: datetime | None = None,
) -> MealAnalysis:
    session_maker = app.state.session_maker
    async with session_maker() as session:
        analysis = MealAnalysis(
            meal_id=meal.id,
            user_id=meal.user_id,
            fit_score=fit_score,
            fit_score_label=fit_score_label,
            fit_reason=fit_reason,
            carbohydrate_g=Decimal("60.0"),
            protein_g=Decimal("15.0"),
            fat_g=Decimal("10.0"),
            energy_kcal=400,
            feedback_text=feedback_text,
            feedback_summary=feedback_summary,
            citations=[],
            used_llm=used_llm,
        )
        if created_at is not None:
            analysis.created_at = created_at
            analysis.updated_at = created_at
        session.add(analysis)
        await session.commit()
        await session.refresh(analysis)
        return analysis


@pytest_asyncio.fixture
async def admin_user(user_factory: UserFactory) -> User:
    return await user_factory(role="admin", email="admin.search@example.com")


# ============================================================================
# AC1 — GET /v1/admin/users (사용자 검색) — 12 cases
# ============================================================================


async def test_search_email_prefix_returns_masked(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    """admin JWT + ``?q=user`` → 200 + ``email_masked`` + plaintext 비포함."""
    target = await user_factory(email="user.alpha@example.com")
    response = await client.get(
        "/v1/admin/users", params={"q": "user"}, headers=_admin_headers(admin_user)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    found = next((u for u in body["users"] if u["user_id"] == str(target.id)), None)
    assert found is not None
    assert found["email_masked"] == "u***@example.com"
    assert "user.alpha" not in response.text


async def test_search_user_id_prefix_matches(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    """``?q={uuid_first_8}`` → 해당 사용자 hit."""
    target = await user_factory(email="other.beta@example.com")
    prefix = target.id.hex[:8]
    response = await client.get(
        "/v1/admin/users", params={"q": prefix}, headers=_admin_headers(admin_user)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert any(u["user_id"] == str(target.id) for u in body["users"])


async def test_search_user_id_prefix_uppercase_is_case_insensitive(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    """대문자 UUID prefix(``?q=ABCD1234``)도 hit — Postgres ``uuid::text``는 소문자라
    cast 비교에 lower-cased pattern 사용 회귀 가드 (CR R3).
    """
    target = await user_factory(email="upper.uuid@example.com")
    prefix_upper = target.id.hex[:8].upper()
    response = await client.get(
        "/v1/admin/users", params={"q": prefix_upper}, headers=_admin_headers(admin_user)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert any(u["user_id"] == str(target.id) for u in body["users"]), (
        f"대문자 prefix {prefix_upper}로 hit 실패 — uuid::text lower-cased pattern 회귀"
    )


async def test_search_excludes_no_match(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    """``?q=zzzzzzzz`` → 빈 list + null next_cursor."""
    await user_factory(email="user.alpha@example.com")
    response = await client.get(
        "/v1/admin/users",
        params={"q": "nomatchprefix0xy"},
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["users"] == []
    assert body["next_cursor"] is None


async def test_search_includes_soft_deleted_users(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    """soft-deleted 사용자도 hit + ``deleted_at`` 노출."""
    target = await user_factory(email="user.gone@example.com", deleted=True)
    response = await client.get(
        "/v1/admin/users", params={"q": "user.gone"}, headers=_admin_headers(admin_user)
    )
    assert response.status_code == 200
    body = response.json()
    found = next((u for u in body["users"] if u["user_id"] == str(target.id)), None)
    assert found is not None
    assert found["deleted_at"] is not None


async def test_search_pagination_cursor_round_trip(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    """limit=2 + 3 사용자 → 첫 페이지 2건 + cursor → 두 번째 페이지 1건."""
    for i in range(3):
        await user_factory(email=f"user.page{i}@example.com")
    response1 = await client.get(
        "/v1/admin/users",
        params={"q": "user.page", "limit": 2},
        headers=_admin_headers(admin_user),
    )
    assert response1.status_code == 200
    page1 = response1.json()
    assert len(page1["users"]) == 2
    assert page1["next_cursor"] is not None

    response2 = await client.get(
        "/v1/admin/users",
        params={"q": "user.page", "limit": 2, "cursor": page1["next_cursor"]},
        headers=_admin_headers(admin_user),
    )
    assert response2.status_code == 200
    page2 = response2.json()
    assert len(page2["users"]) >= 1
    # 정렬 일관성 — 첫 페이지 2건과 두 번째 페이지 user_id가 disjoint.
    page1_ids = {u["user_id"] for u in page1["users"]}
    page2_ids = {u["user_id"] for u in page2["users"]}
    assert page1_ids.isdisjoint(page2_ids)


async def test_search_cursor_invalid_returns_400(client: AsyncClient, admin_user: User) -> None:
    """``?cursor=garbage`` → 400 ``code=admin.cursor.invalid``."""
    response = await client.get(
        "/v1/admin/users",
        params={"q": "user", "cursor": "###not-a-cursor###"},
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "admin.cursor.invalid"


async def test_search_q_with_percent_wildcard_escaped(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    """``?q=%user`` → 리터럴 매칭(다른 사용자 hit 없음)."""
    await user_factory(email="user.alpha@example.com")
    response = await client.get(
        "/v1/admin/users",
        params={"q": "%user"},
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 200
    body = response.json()
    # ``%user``는 literal string 그대로 매칭 — email/UUID prefix 어느 것도 시작 X.
    assert body["users"] == []


async def test_search_q_with_underscore_wildcard_escaped(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    """``?q=u_ser`` → 리터럴 매칭."""
    await user_factory(email="user.alpha@example.com")
    response = await client.get(
        "/v1/admin/users",
        params={"q": "u_ser"},
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 200
    body = response.json()
    # ``u_ser`` literal로 시작하는 email/UUID 없음 → 빈 결과.
    assert body["users"] == []


async def test_search_limit_max_100_clamped(client: AsyncClient, admin_user: User) -> None:
    """``?limit=101`` → 422 (Pydantic Query ``le=100``)."""
    response = await client.get(
        "/v1/admin/users",
        params={"q": "user", "limit": 101},
        headers=_admin_headers(admin_user),
    )
    assert response.status_code in (400, 422)


async def test_search_q_min_length_1_required(client: AsyncClient, admin_user: User) -> None:
    """``?q=`` → 422 (Pydantic ``min_length=1``)."""
    response = await client.get(
        "/v1/admin/users", params={"q": ""}, headers=_admin_headers(admin_user)
    )
    assert response.status_code in (400, 422)


async def test_search_blocked_for_non_admin_user_role(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """user JWT 보유 사용자 → 401/403 (admin endpoint는 admin JWT 의무)."""
    user = await user_factory(role="user")
    user_token = create_user_token(user.id, role="user", platform="mobile")
    response = await client.get(
        "/v1/admin/users",
        params={"q": "user"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    # user JWT은 issuer=user, admin endpoint는 admin issuer 검증 → 401 issuer mismatch.
    assert response.status_code in (401, 403)


async def test_search_blocked_when_token_missing(client: AsyncClient) -> None:
    """Authorization + 쿠키 모두 부재 → 401 ``code=auth.access_token.invalid``."""
    response = await client.get("/v1/admin/users", params={"q": "user"})
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.invalid"


# ============================================================================
# AC2 — GET /v1/admin/users/{user_id} (사용자 상세) — 8 cases
# ============================================================================


async def test_get_user_detail_returns_masked_pii_for_active_user(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(
        email="detail.user@example.com",
        profile_completed=True,
        weight_kg=Decimal("65.5"),
        height_cm=170,
        allergies=["우유", "메밀"],
    )
    response = await client.get(f"/v1/admin/users/{target.id}", headers=_admin_headers(admin_user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email_masked"] == "d***@example.com"
    assert body["weight_kg_masked"] == "**kg"
    assert body["height_cm_masked"] == "**cm"
    assert body["allergies_count_masked"] == "*** 2건 등록"
    # plaintext 비포함 verify
    assert "65.5" not in response.text
    assert "우유" not in response.text
    # 알림 3 필드 — spec line 175-178 (Story 4.1 컬럼 SOT, DB nullable=False+server_default)
    # 회귀 가드: AdminUserDetailResponse 응답 shape에 알림 설정이 포함되어야 함.
    assert body["notifications_enabled"] is True  # DB default
    assert body["notification_time"] == "20:00:00"  # DB server_default '20:00:00'
    assert body["notification_timezone"] == "Asia/Seoul"  # DB server_default


async def test_get_user_detail_returns_soft_deleted_user_with_deletion_metadata(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="gone@example.com", deleted=True)
    # deletion_reason set
    session_maker = app.state.session_maker
    async with session_maker() as session:
        await session.execute(
            sa_update(User).where(User.id == target.id).values(deletion_reason="사용자 요청")
        )
        await session.commit()

    response = await client.get(f"/v1/admin/users/{target.id}", headers=_admin_headers(admin_user))
    assert response.status_code == 200
    body = response.json()
    assert body["deleted_at"] is not None
    assert body["deletion_reason"] == "사용자 요청"


async def test_get_user_detail_user_not_found_returns_404(
    client: AsyncClient, admin_user: User
) -> None:
    response = await client.get(
        f"/v1/admin/users/{uuid.uuid4()}", headers=_admin_headers(admin_user)
    )
    assert response.status_code == 404
    assert response.json()["code"] == "admin.user.not_found"


async def test_get_user_detail_health_profile_unset_returns_null_masked(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="empty@example.com", profile_completed=False)
    response = await client.get(f"/v1/admin/users/{target.id}", headers=_admin_headers(admin_user))
    assert response.status_code == 200
    body = response.json()
    assert body["weight_kg_masked"] is None
    assert body["height_cm_masked"] is None
    assert body["allergies_count_masked"] is None
    assert body["profile_completed_at"] is None


async def test_get_user_detail_allergies_empty_list_shows_count_zero(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(
        email="empty.allergies@example.com", profile_completed=True, allergies=[]
    )
    response = await client.get(f"/v1/admin/users/{target.id}", headers=_admin_headers(admin_user))
    assert response.status_code == 200
    assert response.json()["allergies_count_masked"] == "*** 등록 없음"


async def test_get_user_detail_allergies_3_items_shows_count_3(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(
        email="three.allergies@example.com",
        profile_completed=True,
        allergies=["우유", "메밀", "땅콩"],
    )
    response = await client.get(f"/v1/admin/users/{target.id}", headers=_admin_headers(admin_user))
    assert response.status_code == 200
    body = response.json()
    assert body["allergies_count_masked"] == "*** 3건 등록"
    assert "우유" not in response.text
    assert "메밀" not in response.text
    assert "땅콩" not in response.text


async def test_get_user_detail_blocked_for_non_admin_user_role(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory(role="user")
    user_token = create_user_token(user.id, role="user", platform="mobile")
    response = await client.get(
        f"/v1/admin/users/{user.id}", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert response.status_code in (401, 403)


async def test_get_user_detail_invalid_uuid_returns_422(
    client: AsyncClient, admin_user: User
) -> None:
    response = await client.get("/v1/admin/users/not-a-uuid", headers=_admin_headers(admin_user))
    assert response.status_code in (400, 422)


# ============================================================================
# AC3 — GET /v1/admin/users/{user_id}/meals (식단 이력) — 7 cases
# ============================================================================


async def test_list_user_meals_returns_active_with_analysis_summary(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="ml.user@example.com")
    meal = await _insert_meal(user_id=target.id, raw_text="비빔밥 1인분")
    await _insert_meal_analysis(meal=meal, fit_score=82, fit_score_label="good")
    response = await client.get(
        f"/v1/admin/users/{target.id}/meals", headers=_admin_headers(admin_user)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["meals"]) == 1
    item = body["meals"][0]
    assert item["meal_id"] == str(meal.id)
    assert item["analysis_summary"] is not None
    assert item["analysis_summary"]["fit_score"] == 82
    assert item["analysis_summary"]["fit_score_label"] == "good"


async def test_list_user_meals_includes_soft_deleted(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="sd.user@example.com")
    meal = await _insert_meal(user_id=target.id, raw_text="라면", deleted_at=datetime.now(UTC))
    response = await client.get(
        f"/v1/admin/users/{target.id}/meals", headers=_admin_headers(admin_user)
    )
    assert response.status_code == 200
    body = response.json()
    found = next((m for m in body["meals"] if m["meal_id"] == str(meal.id)), None)
    assert found is not None
    assert found["deleted_at"] is not None


async def test_list_user_meals_raw_text_length_only_no_plaintext(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="rt.user@example.com")
    secret_text = "짜장면 1인분"
    await _insert_meal(user_id=target.id, raw_text=secret_text)
    response = await client.get(
        f"/v1/admin/users/{target.id}/meals", headers=_admin_headers(admin_user)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meals"][0]["raw_text_length"] == len(secret_text)
    assert "짜장면" not in response.text


async def test_list_user_meals_image_url_resolved(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="img.user@example.com")
    meal = await _insert_meal(user_id=target.id, image_key=f"meals/{target.id}/abc.jpg")
    response = await client.get(
        f"/v1/admin/users/{target.id}/meals", headers=_admin_headers(admin_user)
    )
    assert response.status_code == 200
    body = response.json()
    item = next((m for m in body["meals"] if m["meal_id"] == str(meal.id)), None)
    assert item is not None
    # R2 미설정 시 None, 설정 시 valid URL — 어느 쪽이든 string이거나 None.
    assert item["image_url"] is None or item["image_url"].startswith(("http://", "https://"))


async def test_list_user_meals_no_analysis_returns_null_summary(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="na.user@example.com")
    await _insert_meal(user_id=target.id, raw_text="간단한 식사")
    response = await client.get(
        f"/v1/admin/users/{target.id}/meals", headers=_admin_headers(admin_user)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meals"][0]["analysis_summary"] is None


async def test_list_user_meals_user_not_found_returns_404(
    client: AsyncClient, admin_user: User
) -> None:
    response = await client.get(
        f"/v1/admin/users/{uuid.uuid4()}/meals", headers=_admin_headers(admin_user)
    )
    assert response.status_code == 404
    assert response.json()["code"] == "admin.user.not_found"


async def test_list_user_meals_pagination_cursor_round_trip(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="pag.user@example.com")
    base = datetime.now(UTC)
    for i in range(3):
        await _insert_meal(
            user_id=target.id,
            raw_text=f"meal-{i}",
            ate_at=base - timedelta(hours=i),
        )
    response1 = await client.get(
        f"/v1/admin/users/{target.id}/meals",
        params={"limit": 2},
        headers=_admin_headers(admin_user),
    )
    assert response1.status_code == 200
    page1 = response1.json()
    assert len(page1["meals"]) == 2
    assert page1["next_cursor"] is not None

    response2 = await client.get(
        f"/v1/admin/users/{target.id}/meals",
        params={"limit": 2, "cursor": page1["next_cursor"]},
        headers=_admin_headers(admin_user),
    )
    assert response2.status_code == 200
    page2 = response2.json()
    p1_ids = {m["meal_id"] for m in page1["meals"]}
    p2_ids = {m["meal_id"] for m in page2["meals"]}
    assert p1_ids.isdisjoint(p2_ids)
    assert len(page2["meals"]) >= 1


# ============================================================================
# AC4 — GET /v1/admin/users/{user_id}/meal-analyses (피드백 로그) — 5 cases
# ============================================================================


async def test_list_user_meal_analyses_returns_summary_with_fit_score(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="ma.user@example.com")
    meal = await _insert_meal(user_id=target.id)
    analysis = await _insert_meal_analysis(meal=meal, fit_score=88, fit_score_label="excellent")
    response = await client.get(
        f"/v1/admin/users/{target.id}/meal-analyses",
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["meal_analysis_id"] == str(analysis.id)
    assert item["meal_id"] == str(meal.id)
    assert item["fit_score"] == 88
    assert item["fit_score_label"] == "excellent"
    assert item["used_llm"] == "gpt-4o-mini"


async def test_list_user_meal_analyses_excludes_feedback_text_full_body(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    """feedback_text 전체 본문은 list endpoint에서 노출 X (extra=forbid + 응답 모델 미정의)."""
    target = await user_factory(email="ex.user@example.com")
    meal = await _insert_meal(user_id=target.id)
    secret_full = "이 식단의 자세한 분석 본문 — 사용자만 보는 데이터."
    await _insert_meal_analysis(meal=meal, feedback_text=secret_full)
    response = await client.get(
        f"/v1/admin/users/{target.id}/meal-analyses",
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert "feedback_text" not in item
    # full body가 응답에 leak되지 않음.
    assert secret_full not in response.text


async def test_list_user_meal_analyses_user_not_found_returns_404(
    client: AsyncClient, admin_user: User
) -> None:
    response = await client.get(
        f"/v1/admin/users/{uuid.uuid4()}/meal-analyses",
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "admin.user.not_found"


async def test_list_user_meal_analyses_empty_list_for_user_with_no_analyses(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="zero@example.com")
    response = await client.get(
        f"/v1/admin/users/{target.id}/meal-analyses",
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


async def test_list_user_meal_analyses_pagination_cursor_round_trip(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="ma.pag@example.com")
    base = datetime.now(UTC)
    for i in range(3):
        meal = await _insert_meal(user_id=target.id, raw_text=f"meal-{i}")
        await _insert_meal_analysis(meal=meal, created_at=base - timedelta(hours=i))
    response1 = await client.get(
        f"/v1/admin/users/{target.id}/meal-analyses",
        params={"limit": 2},
        headers=_admin_headers(admin_user),
    )
    assert response1.status_code == 200
    page1 = response1.json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    response2 = await client.get(
        f"/v1/admin/users/{target.id}/meal-analyses",
        params={"limit": 2, "cursor": page1["next_cursor"]},
        headers=_admin_headers(admin_user),
    )
    assert response2.status_code == 200
    page2 = response2.json()
    p1 = {i["meal_analysis_id"] for i in page1["items"]}
    p2 = {i["meal_analysis_id"] for i in page2["items"]}
    assert p1.isdisjoint(p2)


# ============================================================================
# AC5 — PATCH /v1/admin/users/{user_id} (관리자 프로필 수정) — 8 cases
# ============================================================================


async def test_patch_user_profile_partial_fields_returns_masked_response(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="patch.user@example.com", profile_completed=True)
    response = await client.patch(
        f"/v1/admin/users/{target.id}",
        json={"weight_kg": 72.0, "allergies": ["우유"]},
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["weight_kg_masked"] == "**kg"
    assert body["allergies_count_masked"] == "*** 1건 등록"
    assert "72.0" not in response.text
    assert "우유" not in response.text


async def test_patch_user_profile_at_least_one_required(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="empty.patch@example.com", profile_completed=True)
    response = await client.patch(
        f"/v1/admin/users/{target.id}", json={}, headers=_admin_headers(admin_user)
    )
    assert response.status_code in (400, 422)


async def test_patch_user_profile_invalid_allergen_returns_400(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="bad.allergen@example.com", profile_completed=True)
    response = await client.patch(
        f"/v1/admin/users/{target.id}",
        json={"allergies": ["존재안함알레르기"]},
        headers=_admin_headers(admin_user),
    )
    assert response.status_code in (400, 422)


async def test_patch_user_profile_weight_2_decimal_rejected(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="prec.user@example.com", profile_completed=True)
    response = await client.patch(
        f"/v1/admin/users/{target.id}",
        json={"weight_kg": 70.55},
        headers=_admin_headers(admin_user),
    )
    assert response.status_code in (400, 422)


async def test_patch_user_profile_user_not_found_returns_404(
    client: AsyncClient, admin_user: User
) -> None:
    response = await client.patch(
        f"/v1/admin/users/{uuid.uuid4()}",
        json={"age": 25},
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "admin.user.not_found"


async def test_patch_user_profile_soft_deleted_user_returns_404(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="sd.patch@example.com", deleted=True)
    response = await client.patch(
        f"/v1/admin/users/{target.id}",
        json={"age": 25},
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "admin.user.not_found"


async def test_patch_user_profile_sets_profile_updated_at_preserves_completed_at(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    """admin PATCH 후 ``profile_updated_at`` set + ``profile_completed_at`` 보존."""
    target = await user_factory(email="invariant@example.com", profile_completed=True)
    completed_before = target.profile_completed_at

    response = await client.patch(
        f"/v1/admin/users/{target.id}",
        json={"age": 31},
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["profile_updated_at"] is not None
    assert body["profile_completed_at"] is not None
    # invariant — profile_completed_at 미변경.
    parsed = datetime.fromisoformat(body["profile_completed_at"].replace("Z", "+00:00"))
    assert completed_before is not None
    # 비교는 second 단위로 (DB / Python clock skew tolerance).
    assert abs((parsed - completed_before).total_seconds()) < 2


async def test_patch_user_profile_blocked_for_non_admin(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory(role="user")
    user_token = create_user_token(user.id, role="user", platform="mobile")
    response = await client.patch(
        f"/v1/admin/users/{user.id}",
        json={"age": 25},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code in (401, 403)


# ============================================================================
# AC6 — DELETE /v1/admin/users/{user_id}/meals/{meal_id} — 5 cases
# ============================================================================


async def test_delete_user_meal_active_returns_204_sets_deleted_at(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="del.user@example.com")
    meal = await _insert_meal(user_id=target.id, raw_text="삭제할 식단")
    response = await client.delete(
        f"/v1/admin/users/{target.id}/meals/{meal.id}",
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 204

    # DB 검증 — deleted_at IS NOT NULL.
    session_maker = app.state.session_maker
    from sqlalchemy import select as sa_select

    async with session_maker() as session:
        result = await session.execute(sa_select(Meal).where(Meal.id == meal.id))
        deleted_meal = result.scalar_one()
        assert deleted_meal.deleted_at is not None


async def test_delete_user_meal_already_soft_deleted_returns_404(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="del2@example.com")
    meal = await _insert_meal(
        user_id=target.id, raw_text="이미 삭제됨", deleted_at=datetime.now(UTC)
    )
    response = await client.delete(
        f"/v1/admin/users/{target.id}/meals/{meal.id}",
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "meals.not_found"


async def test_delete_user_meal_wrong_user_owner_returns_404(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    """다른 사용자 소유 meal → 404 (enumeration 차단 — soft-deleted와 동일 응답)."""
    user_a = await user_factory(email="ua@example.com")
    user_b = await user_factory(email="ub@example.com")
    meal = await _insert_meal(user_id=user_a.id, raw_text="A의 식단")
    response = await client.delete(
        f"/v1/admin/users/{user_b.id}/meals/{meal.id}",
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 404


async def test_delete_user_meal_meal_not_found_returns_404(
    client: AsyncClient, user_factory: UserFactory, admin_user: User
) -> None:
    target = await user_factory(email="ghost@example.com")
    response = await client.delete(
        f"/v1/admin/users/{target.id}/meals/{uuid.uuid4()}",
        headers=_admin_headers(admin_user),
    )
    assert response.status_code == 404


async def test_delete_user_meal_blocked_for_non_admin(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory(role="user")
    user_token = create_user_token(user.id, role="user", platform="mobile")
    response = await client.delete(
        f"/v1/admin/users/{user.id}/meals/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code in (401, 403)
