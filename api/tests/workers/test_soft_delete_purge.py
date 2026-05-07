"""Story 5.2 AC4/AC7/AC9 — ``app.workers.soft_delete_purge`` 단위 테스트.

7건+ 시나리오 — Real Postgres + monkeypatched R2 boto3 client:

1. 31일 경과 1건 + 미경과 1건 → eligible=1 / purged=1 / 미경과 보존 (+ CASCADE 검증).
2. R2 dump bucket 미설정 → dump skip + 운영 로그.
3. R2 dump bucket 설정 → ``put_object`` 호출 검증.
4. R2 meal images cleanup — ``meals/{user_id}/`` prefix list/delete 호출.
5. dump 실패 시 sweep 전체 미중단(per-user 격리).
6. ``register_purge_job`` — scheduler에 잡 등록 + CronTrigger hour=3.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.consent import Consent
from app.db.models.meal import Meal
from app.db.models.notification import Notification
from app.db.models.user import User
from app.main import app
from app.workers.soft_delete_purge import (
    PURGE_GRACE_DAYS,
    PURGE_JOB_ID,
    purge_expired_soft_deleted_users,
    register_purge_job,
)


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    _ = client
    return app.state.session_maker


async def _create_user(
    session_maker: async_sessionmaker,
    *,
    deleted_days_ago: int | None = None,
) -> User:
    """``deleted_days_ago=N``이면 ``deleted_at = now() - N일``로 set, None이면 활성."""
    async with session_maker() as session:
        user = User(
            google_sub=f"google-sub-{uuid.uuid4()}",
            email=f"{uuid.uuid4().hex}@example.com",
            email_verified=True,
            last_login_at=datetime.now(UTC),
        )
        if deleted_days_ago is not None:
            user.deleted_at = datetime.now(UTC) - timedelta(days=deleted_days_ago)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


def _make_fake_r2_module(
    *,
    list_response: dict[str, Any] | None = None,
    raise_on_put: bool = False,
) -> Any:
    """``app.adapters.r2`` 모듈처럼 ``_get_client()`` 반환하는 fake 어댑터.

    boto3 client는 sync MagicMock — list_objects_v2 / delete_objects / put_object 3 메서드.
    """
    fake_client = MagicMock()
    fake_client.list_objects_v2.return_value = list_response or {"Contents": []}
    fake_client.delete_objects.return_value = {"Deleted": []}
    if raise_on_put:
        fake_client.put_object.side_effect = RuntimeError("simulated R2 PUT failure")

    fake_module = MagicMock()
    fake_module._get_client.return_value = fake_client
    return fake_module


# --- AC4 1) 31일 경과 + 미경과 분기 + CASCADE 검증 -------------------------


async def test_purge_eligible_user_and_preserves_active(
    session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """31일 경과 사용자 1건 + 미경과(activate) 1건 → eligible=1 / purged=1.

    + CASCADE 검증: ``DELETE FROM users``가 ``consents`` / ``meals`` / ``notifications`` /
    ``refresh_tokens`` child rows를 자동 cascade(코드 변경 0건, FK level SOT).
    """
    monkeypatch.setattr("app.core.config.settings.r2_purge_dump_bucket", "")

    expired_user = await _create_user(session_maker, deleted_days_ago=31)
    active_user = await _create_user(session_maker, deleted_days_ago=None)

    # CASCADE 입력 — expired_user에 consents / meals / notifications row 생성.
    async with session_maker() as session:
        session.add(
            Consent(
                user_id=expired_user.id,
                disclaimer_acknowledged_at=datetime.now(UTC),
            )
        )
        meal = Meal(
            user_id=expired_user.id,
            raw_text="cascade test meal",
        )
        session.add(meal)
        from datetime import date as _date

        session.add(
            Notification(
                user_id=expired_user.id,
                kind="unrecorded_meal",
                kst_date=_date.today(),
            )
        )
        await session.commit()

    stats = await purge_expired_soft_deleted_users(session_maker, r2_adapter=None)
    assert stats["users_eligible_count"] == 1
    assert stats["users_purged_count"] == 1
    assert stats["errors_count"] == 0

    # expired_user 사라짐 + active_user 보존.
    async with session_maker() as session:
        result = await session.execute(
            select(User.id).where(User.id.in_([expired_user.id, active_user.id]))
        )
        remaining = [row[0] for row in result.all()]
        assert active_user.id in remaining
        assert expired_user.id not in remaining

        # CASCADE 검증 — consents / meals / notifications 모두 0건.
        for table_name in ("consents", "meals", "notifications"):
            cnt = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table_name} WHERE user_id = :uid"),
                    {"uid": expired_user.id},
                )
            ).scalar_one()
            assert cnt == 0, f"{table_name} cascade failed (count={cnt})"


# --- AC4 2) R2 dump bucket 미설정 → dump skip --------------------------------


async def test_purge_skips_dump_when_bucket_unset(
    session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``settings.r2_purge_dump_bucket`` 미설정 → put_object 호출 0건.

    *Why*: 운영 SOP — Cloudflare 콘솔 측 lifecycle policy 미수립 환경(dev/CI)에서 dump
    skip + worker는 정상 진행(NFR-R5/C6 graceful 정합).
    """
    monkeypatch.setattr("app.core.config.settings.r2_purge_dump_bucket", "")
    fake_r2 = _make_fake_r2_module()
    await _create_user(session_maker, deleted_days_ago=31)

    stats = await purge_expired_soft_deleted_users(session_maker, r2_adapter=fake_r2)
    assert stats["users_purged_count"] == 1
    assert stats["r2_dumps_count"] == 0
    fake_r2._get_client.return_value.put_object.assert_not_called()


# --- AC4 3) R2 dump bucket 설정 → put_object 호출 ---------------------------


async def test_purge_uploads_dump_when_bucket_configured(
    session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """bucket 설정 → ``put_object`` 1회 호출 + Bucket/Key/JSON body 검증."""
    monkeypatch.setattr(
        "app.core.config.settings.r2_purge_dump_bucket",
        "balancenote-purge-dumps",
    )
    fake_r2 = _make_fake_r2_module()
    expired_user = await _create_user(session_maker, deleted_days_ago=31)

    stats = await purge_expired_soft_deleted_users(session_maker, r2_adapter=fake_r2)
    assert stats["users_purged_count"] == 1
    assert stats["r2_dumps_count"] == 1

    fake_client = fake_r2._get_client.return_value
    fake_client.put_object.assert_called_once()
    call_kwargs = fake_client.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "balancenote-purge-dumps"
    assert call_kwargs["Key"].startswith(f"purge-dumps/{expired_user.id}/")
    assert call_kwargs["Key"].endswith(".json")
    assert call_kwargs["ContentType"].startswith("application/json")


# --- AC4 4) R2 meal images cleanup -----------------------------------------


async def test_purge_cleans_user_meal_images(
    session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``meals/{user_id}/`` prefix list_objects_v2 + delete_objects 1패스 호출."""
    monkeypatch.setattr("app.core.config.settings.r2_purge_dump_bucket", "")
    expired_user = await _create_user(session_maker, deleted_days_ago=31)

    list_response = {
        "Contents": [
            {"Key": f"meals/{expired_user.id}/image-1.jpg"},
            {"Key": f"meals/{expired_user.id}/image-2.png"},
        ],
        "IsTruncated": False,
    }
    fake_r2 = _make_fake_r2_module(list_response=list_response)

    stats = await purge_expired_soft_deleted_users(session_maker, r2_adapter=fake_r2)
    assert stats["r2_images_cleaned_count"] == 2

    fake_client = fake_r2._get_client.return_value
    list_kwargs = fake_client.list_objects_v2.call_args.kwargs
    assert list_kwargs["Prefix"] == f"meals/{expired_user.id}/"

    delete_kwargs = fake_client.delete_objects.call_args.kwargs
    assert len(delete_kwargs["Delete"]["Objects"]) == 2


# --- AC4 5) per-user 격리 — dump 실패가 다른 사용자 sweep 미중단 ------------


async def test_purge_dump_failure_does_not_block_hard_delete(
    session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR D1 — dump 실패해도 cleanup + DB hard DELETE 진행 (PIPA Art.21 30일 mandate).

    *Why*: dump bucket 영구 misconfig 시 grace 만료 사용자가 영원히 soft-deleted 잔존하면
    PIPA 즉시 삭제 의무 위반. dump 실패는 stats[dump_errors_count]에 기록 + sentry capture로
    운영자 즉시 인지하지만, hard DELETE는 차단하지 않음.
    """
    monkeypatch.setattr(
        "app.core.config.settings.r2_purge_dump_bucket",
        "balancenote-purge-dumps",
    )
    fake_r2 = _make_fake_r2_module(raise_on_put=True)

    user1 = await _create_user(session_maker, deleted_days_ago=31)
    user2 = await _create_user(session_maker, deleted_days_ago=32)

    stats = await purge_expired_soft_deleted_users(session_maker, r2_adapter=fake_r2)
    assert stats["users_eligible_count"] == 2
    # CR D1 — dump 실패 2건 + DB hard DELETE 2건 모두 진행. PIPA mandate 우선.
    assert stats["dump_errors_count"] == 2
    assert stats["users_purged_count"] == 2
    # outer except는 미진입 — dump 실패는 inner try로 isolated.
    assert stats["errors_count"] == 0

    # 두 사용자 row 모두 hard delete 완료(soft-deleted 잔존 X).
    async with session_maker() as session:
        remaining = (
            (await session.execute(select(User.id).where(User.id.in_([user1.id, user2.id]))))
            .scalars()
            .all()
        )
        assert len(remaining) == 0


# --- AC4 6) register_purge_job — scheduler 등록 ----------------------------


def test_register_purge_job_adds_cron_hour_3() -> None:
    """``register_purge_job`` 호출 후 ``scheduler.get_job(PURGE_JOB_ID)`` 존재 +
    CronTrigger hour=3 + minute=0.

    *Why*: lifespan 등록 회귀 가드 — 잡 ID 변경 또는 trigger 시각 변경 시 본 테스트 fail.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    register_purge_job(scheduler, session_maker=None, r2_adapter=None)
    job = scheduler.get_job(PURGE_JOB_ID)
    assert job is not None
    trigger = job.trigger
    # CronTrigger fields는 dict-like — hour=3 / minute=0 SOT 검증.
    field_map = {f.name: str(f) for f in trigger.fields}
    assert field_map["hour"] == "3"
    assert field_map["minute"] == "0"


# --- AC4 7) PURGE_GRACE_DAYS 상수 SOT --------------------------------------


def test_purge_grace_days_constant_is_30() -> None:
    """``PURGE_GRACE_DAYS = 30`` SOT — epics.md:798 + architecture.md:351 정합.

    *Why*: 본 상수가 ``auth.py`` raise site에서 ``purge_at = deleted_at + timedelta(
    days=PURGE_GRACE_DAYS)``로 import — 변경 시 한국어 detail 안내 일자도 자동 변경.
    cross-module SOT 가드.
    """
    assert PURGE_GRACE_DAYS == 30


# --- Story 4.2 회귀 가드: nudge sweep eligible_count = 0 -------------------


@pytest.mark.asyncio
async def test_nudge_sweep_excludes_soft_deleted_users(
    session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 5.2 AC7 — soft-deleted 사용자는 nudge sweep eligible 미진입.

    *Why*: Story 4.2 ``_build_eligible_users_query``의 ``u.deleted_at IS NULL`` 필터(line 89)
    회귀 가드 — 변경 0건 invariant. soft-deleted 사용자가 활성 상태 push 받지 않음.
    """
    from datetime import time as _time
    from unittest.mock import AsyncMock
    from zoneinfo import ZoneInfo

    from exponent_server_sdk import PushTicket

    import app.workers.nudge_scheduler as nudge_module
    from app.adapters import expo_push
    from app.workers.nudge_scheduler import sweep_unrecorded_meals

    _KST = ZoneInfo("Asia/Seoul")

    # Fix `datetime.now(KST)` — 20:30 KST + 적격 시간(notification_time=19:30 → +30min=20:00).
    fixed_now = datetime(2026, 5, 6, 20, 30, 0, tzinfo=_KST)

    class _FakeDatetime:
        @staticmethod
        def now(tz: Any = None) -> datetime:
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(nudge_module, "datetime", _FakeDatetime)
    monkeypatch.setattr(
        expo_push,
        "send_nudge",
        AsyncMock(
            return_value=PushTicket(
                push_message=None, status="ok", message="", details=None, id="t-stub"
            )
        ),
    )

    # soft-deleted 사용자 — 적격 조건 모두 충족(notification 시간/token 활성)이지만
    # ``deleted_at IS NOT NULL``로 인해 sweep query 미진입.
    async with session_maker() as session:
        from sqlalchemy import update as _update

        from app.db.models.user import User as _User

        u = _User(
            google_sub=f"google-sub-{uuid.uuid4()}",
            email=f"{uuid.uuid4().hex}@example.com",
            email_verified=True,
            last_login_at=datetime.now(UTC),
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        await session.execute(
            _update(_User)
            .where(_User.id == u.id)
            .values(
                notification_time=_time(19, 30),
                notifications_enabled=True,
                expo_push_token="ExponentPushToken[soft-deleted]",
                deleted_at=datetime.now(UTC),  # ← key invariant.
            )
        )
        await session.commit()

    stats = await sweep_unrecorded_meals(session_maker)
    assert stats["users_eligible_count"] == 0, (
        "Story 4.2 회귀 — soft-deleted 사용자가 nudge sweep eligible에 진입했음. "
        "_build_eligible_users_query의 u.deleted_at IS NULL 필터를 점검하세요."
    )
