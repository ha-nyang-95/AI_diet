"""Story 8.5 AC8 — `app/adapters/r2.py` Supabase Storage 분기 단위 테스트.

R2와 동일한 외부 시그니처(``create_presigned_upload`` / ``head_object_exists`` /
``resolve_public_url``) + 동일한 검증 정책(content_type whitelist / content_length /
unconfigured raise)을 Supabase 분기에서도 보장한다 — 호출처(`meals_images.py`) 변경 0.

R2 분기 회귀는 `tests/test_r2_adapter.py`에서 별 fixture(STORAGE_PROVIDER=r2 강제)로 검증.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.adapters import r2 as r2_adapter
from app.core.config import settings as _settings
from app.core.exceptions import (
    R2UploadValidationError,
    StorageNotConfiguredError,
    SupabaseStorageNotConfiguredError,
)


@pytest.fixture(autouse=True)
def _reset_client_singleton() -> None:
    """매 테스트 전 storage3/boto3 client singleton 무효화 — settings monkeypatch 반영."""
    r2_adapter._reset_client_for_tests()


@pytest.fixture
def _supabase_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """test settings에 Supabase Storage env 3종 + STORAGE_PROVIDER=supabase 주입."""
    monkeypatch.setattr(_settings, "storage_provider", "supabase")
    monkeypatch.setattr(_settings, "supabase_url", "https://test-proj.supabase.co")
    monkeypatch.setattr(_settings, "supabase_service_key", "test-service-role-key")
    monkeypatch.setattr(_settings, "supabase_storage_bucket", "meals")


class _StubBucket:
    """storage3 ``StorageBucketAPI`` stub — 호출 응답을 fixture가 주입."""

    def __init__(
        self,
        *,
        signed_upload_response: dict[str, Any] | None = None,
        signed_url_response: dict[str, Any] | None = None,
        list_response: list[dict[str, Any]] | Exception | None = None,
    ) -> None:
        self._signed_upload = signed_upload_response or {
            "signedURL": "/storage/v1/object/upload/sign/meals/foo.jpg?token=abc",
            "token": "abc",
        }
        self._signed_url = signed_url_response or {
            "signedURL": "https://test-proj.supabase.co/storage/v1/object/sign/meals/foo.jpg?token=zzz"
        }
        self._list = list_response if list_response is not None else []
        self.calls: list[tuple[str, tuple, dict]] = []

    def create_signed_upload_url(self, path: str) -> dict[str, Any]:
        self.calls.append(("create_signed_upload_url", (path,), {}))
        return self._signed_upload

    def create_signed_url(self, path: str, expires_in: int) -> dict[str, Any]:
        self.calls.append(("create_signed_url", (path, expires_in), {}))
        return self._signed_url

    def list(self, path: str = "", options: dict[str, Any] | None = None) -> Any:
        self.calls.append(("list", (path,), options or {}))
        if isinstance(self._list, Exception):
            raise self._list
        return self._list


class _StubStorage:
    """storage3 client stub — ``from_(bucket)``이 단일 ``_StubBucket`` 반환."""

    def __init__(self, bucket: _StubBucket) -> None:
        self._bucket = bucket
        self.from_calls: list[str] = []

    def from_(self, bucket_name: str) -> _StubBucket:
        self.from_calls.append(bucket_name)
        return self._bucket


# --- create_presigned_upload (Supabase) ---------------------------------------


def test_supabase_create_presigned_upload_returns_pattern(
    monkeypatch: pytest.MonkeyPatch,
    _supabase_configured: None,
) -> None:
    """정상 호출 — image_key 형식 + 5필드 응답 + Supabase signed URL 정규화 검증."""
    stub_bucket = _StubBucket(
        signed_upload_response={
            "signedURL": "/storage/v1/object/upload/sign/meals/anything?token=xyz",
            "token": "xyz",
        },
        signed_url_response={
            "signedURL": "https://test-proj.supabase.co/storage/v1/object/sign/meals/something?token=read"
        },
    )
    stub_storage = _StubStorage(stub_bucket)
    monkeypatch.setattr(r2_adapter, "_get_supabase_storage", lambda: stub_storage)

    user_id = uuid.uuid4()
    before = datetime.now(UTC)
    presigned = r2_adapter.create_presigned_upload(
        user_id=user_id,
        content_type="image/jpeg",
        content_length=1234,
    )
    after = datetime.now(UTC)

    pattern = rf"^meals/{user_id}/[0-9a-f-]{{36}}\.jpg$"
    assert re.match(pattern, presigned.image_key), presigned.image_key

    # 상대 경로 signedURL은 supabase_url로 절대화.
    assert presigned.upload_url.startswith("https://test-proj.supabase.co/")
    assert "token=xyz" in presigned.upload_url

    # public_url은 1h signed download URL.
    assert "test-proj.supabase.co" in presigned.public_url
    assert "token=read" in presigned.public_url

    expected_min = before + timedelta(seconds=290)
    expected_max = after + timedelta(seconds=310)
    assert expected_min <= presigned.expires_at <= expected_max

    assert presigned.content_type == "image/jpeg"
    # bucket SDK 호출 1회 + signed_url 1회 = total 2 from_().
    assert stub_storage.from_calls == ["meals", "meals"]


def test_supabase_create_presigned_upload_absolute_url_passthrough(
    monkeypatch: pytest.MonkeyPatch,
    _supabase_configured: None,
) -> None:
    """이미 절대 URL을 반환하는 storage3 버전에 대해 추가 정규화 없이 그대로 forward."""
    stub_bucket = _StubBucket(
        signed_upload_response={
            "signedUrl": "https://other.example.com/foo?token=zzz",
            "token": "zzz",
        }
    )
    monkeypatch.setattr(r2_adapter, "_get_supabase_storage", lambda: _StubStorage(stub_bucket))

    presigned = r2_adapter.create_presigned_upload(
        user_id=uuid.uuid4(),
        content_type="image/png",
        content_length=4096,
    )
    assert presigned.upload_url == "https://other.example.com/foo?token=zzz"


def test_supabase_unsupported_content_type_raises(
    monkeypatch: pytest.MonkeyPatch,
    _supabase_configured: None,
) -> None:
    """content_type whitelist 위반 — Supabase 분기에서도 R2와 동일한 R2UploadValidationError."""
    stub_storage = _StubStorage(_StubBucket())
    monkeypatch.setattr(r2_adapter, "_get_supabase_storage", lambda: stub_storage)
    with pytest.raises(R2UploadValidationError) as excinfo:
        r2_adapter.create_presigned_upload(
            user_id=uuid.uuid4(),
            content_type="image/gif",
            content_length=1234,
        )
    assert "image/gif" in str(excinfo.value.detail or "")
    # 검증은 client init 전 — Stub은 호출되지 않아야 함.
    assert stub_storage.from_calls == []


def test_supabase_oversize_raises(
    monkeypatch: pytest.MonkeyPatch,
    _supabase_configured: None,
) -> None:
    """content_length 10 MB 초과 — Supabase 분기에서도 R2UploadValidationError."""
    monkeypatch.setattr(r2_adapter, "_get_supabase_storage", lambda: _StubStorage(_StubBucket()))
    with pytest.raises(R2UploadValidationError):
        r2_adapter.create_presigned_upload(
            user_id=uuid.uuid4(),
            content_type="image/jpeg",
            content_length=11 * 1024 * 1024,
        )


def test_supabase_underweight_raises(
    monkeypatch: pytest.MonkeyPatch,
    _supabase_configured: None,
) -> None:
    """content_length 0 / 음수 — 동일하게 R2UploadValidationError."""
    monkeypatch.setattr(r2_adapter, "_get_supabase_storage", lambda: _StubStorage(_StubBucket()))
    with pytest.raises(R2UploadValidationError):
        r2_adapter.create_presigned_upload(
            user_id=uuid.uuid4(),
            content_type="image/jpeg",
            content_length=0,
        )


def test_supabase_unconfigured_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """settings env 미설정 시 ``SupabaseStorageNotConfiguredError`` raise (503 fail-fast)."""
    monkeypatch.setattr(_settings, "storage_provider", "supabase")
    monkeypatch.setattr(_settings, "supabase_url", "")
    monkeypatch.setattr(_settings, "supabase_service_key", "")
    monkeypatch.setattr(_settings, "supabase_storage_bucket", "")

    with pytest.raises(SupabaseStorageNotConfiguredError):
        r2_adapter.create_presigned_upload(
            user_id=uuid.uuid4(),
            content_type="image/jpeg",
            content_length=1234,
        )


def test_supabase_unconfigured_caught_by_parent_class(monkeypatch: pytest.MonkeyPatch) -> None:
    """parent ``StorageNotConfiguredError``로도 catch 가능 — 호출처 일원화 정합."""
    monkeypatch.setattr(_settings, "storage_provider", "supabase")
    monkeypatch.setattr(_settings, "supabase_url", "")

    with pytest.raises(StorageNotConfiguredError):
        r2_adapter.create_presigned_upload(
            user_id=uuid.uuid4(),
            content_type="image/jpeg",
            content_length=1234,
        )


# --- resolve_public_url (Supabase) --------------------------------------------


def test_supabase_resolve_public_url_returns_signed(
    monkeypatch: pytest.MonkeyPatch,
    _supabase_configured: None,
) -> None:
    """1h signed download URL 반환 — bucket private + Vision OCR 5분 이상 여유."""
    stub_bucket = _StubBucket(
        signed_url_response={
            "signedURL": "https://test-proj.supabase.co/storage/v1/object/sign/meals/foo.jpg?token=z"
        }
    )
    monkeypatch.setattr(r2_adapter, "_get_supabase_storage", lambda: _StubStorage(stub_bucket))

    url = r2_adapter.resolve_public_url("meals/foo.jpg")
    assert url == ("https://test-proj.supabase.co/storage/v1/object/sign/meals/foo.jpg?token=z")
    # 1h 만료 검증.
    assert stub_bucket.calls == [("create_signed_url", ("meals/foo.jpg", 3600), {})]


def test_supabase_resolve_public_url_returns_none_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """unconfigured 환경(dev/CI에 Supabase 미설정)에서 None 반환 — broken URL 차단."""
    monkeypatch.setattr(_settings, "storage_provider", "supabase")
    monkeypatch.setattr(_settings, "supabase_url", "")
    monkeypatch.setattr(_settings, "supabase_service_key", "")

    assert r2_adapter.resolve_public_url("meals/foo.jpg") is None


# --- head_object_exists (Supabase) --------------------------------------------


def test_supabase_head_object_exists_returns_true_when_match(
    monkeypatch: pytest.MonkeyPatch,
    _supabase_configured: None,
) -> None:
    """list 결과에 image_key의 filename 매칭 시 True."""
    stub_bucket = _StubBucket(
        list_response=[{"name": "abc.jpg", "id": "..."}, {"name": "other.jpg"}]
    )
    monkeypatch.setattr(r2_adapter, "_get_supabase_storage", lambda: _StubStorage(stub_bucket))

    assert r2_adapter.head_object_exists("meals/user-1/abc.jpg") is True
    # prefix + search 옵션 검증.
    assert stub_bucket.calls[-1][0] == "list"
    assert stub_bucket.calls[-1][1] == ("meals/user-1",)
    assert stub_bucket.calls[-1][2].get("search") == "abc.jpg"


def test_supabase_head_object_exists_returns_false_when_empty(
    monkeypatch: pytest.MonkeyPatch,
    _supabase_configured: None,
) -> None:
    """list 결과 0건 또는 미매칭 시 False."""
    stub_bucket = _StubBucket(list_response=[])
    monkeypatch.setattr(r2_adapter, "_get_supabase_storage", lambda: _StubStorage(stub_bucket))

    assert r2_adapter.head_object_exists("meals/user-1/missing.jpg") is False


def test_supabase_head_object_exists_returns_false_when_name_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    _supabase_configured: None,
) -> None:
    """list 결과에 *유사* 이름은 있지만 정확 매칭 없을 때 False (substring leak 차단)."""
    stub_bucket = _StubBucket(
        list_response=[{"name": "abc.jpeg"}, {"name": "_abc.jpg"}]  # 정확 매칭 없음
    )
    monkeypatch.setattr(r2_adapter, "_get_supabase_storage", lambda: _StubStorage(stub_bucket))

    assert r2_adapter.head_object_exists("meals/user-1/abc.jpg") is False


# --- Provider 분기 정합 -------------------------------------------------------


def test_storage_provider_supabase_uses_supabase_branch(
    monkeypatch: pytest.MonkeyPatch,
    _supabase_configured: None,
) -> None:
    """STORAGE_PROVIDER=supabase일 때 ``_get_supabase_storage``만 호출되고 boto3는 미호출."""
    sup_calls: list[int] = []

    def _supabase_factory() -> Any:
        sup_calls.append(1)
        return _StubStorage(_StubBucket())

    def _r2_factory_should_not_be_called() -> Any:
        pytest.fail("_get_r2_client should NOT be called when storage_provider=supabase")

    monkeypatch.setattr(r2_adapter, "_get_supabase_storage", _supabase_factory)
    monkeypatch.setattr(r2_adapter, "_get_r2_client", _r2_factory_should_not_be_called)

    r2_adapter.create_presigned_upload(
        user_id=uuid.uuid4(),
        content_type="image/webp",
        content_length=2048,
    )
    # ``create_presigned_upload`` 본체 1회 + 내부 ``resolve_public_url`` 1회 = 2회.
    # 핵심은 r2 분기가 호출되지 않았음을 ``_r2_factory_should_not_be_called``로 검증.
    assert len(sup_calls) >= 1


def test_storage_provider_r2_default_does_not_call_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STORAGE_PROVIDER 미설정(default=r2) — Supabase 분기 미호출 회귀 가드."""
    monkeypatch.setattr(_settings, "storage_provider", "r2")

    def _supabase_factory_should_not_be_called() -> Any:
        pytest.fail("_get_supabase_storage should NOT be called when storage_provider=r2")

    monkeypatch.setattr(r2_adapter, "_get_supabase_storage", _supabase_factory_should_not_be_called)
    # default r2 분기에서는 unconfigured → R2NotConfiguredError raise되며 Supabase 미호출 검증.
    monkeypatch.setattr(_settings, "r2_account_id", "")
    monkeypatch.setattr(_settings, "r2_access_key_id", "")
    monkeypatch.setattr(_settings, "r2_secret_access_key", "")
    monkeypatch.setattr(_settings, "r2_bucket", "")

    from app.core.exceptions import R2NotConfiguredError  # noqa: PLC0415

    with pytest.raises(R2NotConfiguredError):
        r2_adapter.create_presigned_upload(
            user_id=uuid.uuid4(),
            content_type="image/jpeg",
            content_length=1234,
        )
