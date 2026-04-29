"""Story 2.2 — `app/adapters/r2.py` Cloudflare R2 presigned URL adapter 단위 테스트.

4+ 케이스 (AC12 명시 + Code Review 2026-04-29 보강):
- `test_create_presigned_upload_returns_pattern` — 정상 호출 시 image_key 형식 + expires_at 검증.
- `test_create_presigned_upload_unsupported_type_raises` — content_type whitelist 위반.
- `test_create_presigned_upload_oversize_raises` — content_length 10 MB 초과.
- `test_create_presigned_upload_unconfigured_raises` — settings env 미설정 시 503 fail-fast.
- `test_resolve_public_url_returns_none_when_unconfigured` (P3) — R2 미설정 시 None.
- `test_resolve_public_url_uses_r2_dev_fallback` (P3) — base_url 미설정시 r2.dev fallback.
- `test_head_object_exists_returns_true_on_2xx` (P21) — boto3 client mock head_object 성공.
- `test_head_object_exists_returns_false_on_404` (P21) — ClientError 404 mock.

boto3 `generate_presigned_url`은 *서명 계산만* (실제 R2 도달 X) — monkeypatch로
settings 환경변수 주입 후 호출 가능. `head_object`는 실제 R2 호출이라 boto3 client
자체를 monkeypatch.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.adapters import r2 as r2_adapter
from app.core.config import settings as _settings
from app.core.exceptions import R2NotConfiguredError, R2UploadValidationError


@pytest.fixture(autouse=True)
def _reset_r2_client_singleton() -> None:
    """매 테스트 전 boto3 client singleton 무효화 — settings monkeypatch 반영."""
    r2_adapter._reset_client_for_tests()


@pytest.fixture
def _r2_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """test settings에 R2 환경변수 5종 주입 — monkeypatch가 fixture 종료 시 자동 복원."""
    monkeypatch.setattr(_settings, "r2_account_id", "test-account-id")
    monkeypatch.setattr(_settings, "r2_access_key_id", "test-access-key")
    monkeypatch.setattr(_settings, "r2_secret_access_key", "test-secret-key")
    monkeypatch.setattr(_settings, "r2_bucket", "test-bucket")
    monkeypatch.setattr(_settings, "r2_public_base_url", "https://cdn.example.com")


def test_create_presigned_upload_returns_pattern(_r2_configured: None) -> None:
    """정상 호출 — image_key 형식 + 5필드 응답 + expires_at ~ 5분 후 검증."""
    user_id = uuid.uuid4()
    before = datetime.now(UTC)
    presigned = r2_adapter.create_presigned_upload(
        user_id=user_id,
        content_type="image/jpeg",
        content_length=1234,
    )
    after = datetime.now(UTC)

    # image_key 형식: meals/{user_id}/{uuid}.jpg
    pattern = rf"^meals/{user_id}/[0-9a-f-]{{36}}\.jpg$"
    assert re.match(pattern, presigned.image_key), presigned.image_key

    # public_url은 r2_public_base_url 기반.
    assert presigned.public_url == f"https://cdn.example.com/{presigned.image_key}"

    # upload_url은 boto3 서명 URL — endpoint + 서명 토큰 포함.
    assert "test-account-id.r2.cloudflarestorage.com" in presigned.upload_url
    assert "X-Amz-Signature=" in presigned.upload_url

    # expires_at ~ now + 5분 (window: 호출 전후 시간 사이 + 약간의 허용).
    expected_min = before + timedelta(seconds=290)
    expected_max = after + timedelta(seconds=310)
    assert expected_min <= presigned.expires_at <= expected_max

    # content_type echo.
    assert presigned.content_type == "image/jpeg"


def test_create_presigned_upload_unsupported_type_raises(_r2_configured: None) -> None:
    """content_type whitelist 위반 — `R2UploadValidationError` raise."""
    with pytest.raises(R2UploadValidationError) as excinfo:
        r2_adapter.create_presigned_upload(
            user_id=uuid.uuid4(),
            content_type="image/gif",
            content_length=1234,
        )
    assert "image/gif" in str(excinfo.value.detail or "")


def test_create_presigned_upload_oversize_raises(_r2_configured: None) -> None:
    """content_length 10 MB 초과 — `R2UploadValidationError` raise."""
    with pytest.raises(R2UploadValidationError):
        r2_adapter.create_presigned_upload(
            user_id=uuid.uuid4(),
            content_type="image/jpeg",
            content_length=11 * 1024 * 1024,
        )


def test_create_presigned_upload_unconfigured_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """settings env 미설정 시 — `R2NotConfiguredError` raise (503 fail-fast)."""
    # _r2_configured fixture 미적용 — defaults는 빈 문자열.
    monkeypatch.setattr(_settings, "r2_account_id", "")
    monkeypatch.setattr(_settings, "r2_access_key_id", "")
    monkeypatch.setattr(_settings, "r2_secret_access_key", "")
    monkeypatch.setattr(_settings, "r2_bucket", "")

    with pytest.raises(R2NotConfiguredError):
        r2_adapter.create_presigned_upload(
            user_id=uuid.uuid4(),
            content_type="image/jpeg",
            content_length=1234,
        )


# --- Code Review 2026-04-29 — P3/P21 회귀 테스트 -----------------------------------


def test_resolve_public_url_returns_none_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P3 — settings 모두 미설정 시 ``resolve_public_url``은 None 반환 (broken
    `https:///<key>` URL 차단)."""
    monkeypatch.setattr(_settings, "r2_public_base_url", "")
    monkeypatch.setattr(_settings, "r2_account_id", "")
    monkeypatch.setattr(_settings, "r2_bucket", "")

    assert r2_adapter.resolve_public_url("meals/foo/bar.jpg") is None


def test_resolve_public_url_uses_r2_dev_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """P3 — base_url 미설정 + account/bucket 있을 때 `*.r2.dev` fallback."""
    monkeypatch.setattr(_settings, "r2_public_base_url", "")
    monkeypatch.setattr(_settings, "r2_account_id", "acc-x")
    monkeypatch.setattr(_settings, "r2_bucket", "buc-y")

    assert r2_adapter.resolve_public_url("meals/foo/bar.jpg") == (
        "https://acc-x.r2.dev/buc-y/meals/foo/bar.jpg"
    )


class _StubClient:
    """boto3 S3 client stub — head_object 응답을 fixture가 주입."""

    def __init__(self, *, head_response: Any = None, head_error: Exception | None = None) -> None:
        self._head_response = head_response
        self._head_error = head_error

    def head_object(self, *, Bucket: str, Key: str) -> Any:
        if self._head_error is not None:
            raise self._head_error
        return self._head_response or {"ContentLength": 1234}


def test_head_object_exists_returns_true_on_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    """P21 — head_object가 2xx 반환 시 True (객체 존재)."""
    stub = _StubClient(head_response={"ContentLength": 1234})
    monkeypatch.setattr(r2_adapter, "_get_client", lambda: stub)
    monkeypatch.setattr(_settings, "r2_bucket", "test-bucket")

    assert r2_adapter.head_object_exists("meals/foo/bar.jpg") is True


def test_head_object_exists_returns_false_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """P21 — head_object가 404 ClientError 반환 시 False (객체 미존재)."""
    error = ClientError(
        error_response={"Error": {"Code": "404", "Message": "Not Found"}},
        operation_name="HeadObject",
    )
    stub = _StubClient(head_error=error)
    monkeypatch.setattr(r2_adapter, "_get_client", lambda: stub)
    monkeypatch.setattr(_settings, "r2_bucket", "test-bucket")

    assert r2_adapter.head_object_exists("meals/foo/bar.jpg") is False


def test_head_object_exists_propagates_unknown_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """P21 — 5xx 등 미분류 ClientError는 raise (글로벌 핸들러가 500 변환)."""
    error = ClientError(
        error_response={"Error": {"Code": "InternalError", "Message": "Server Error"}},
        operation_name="HeadObject",
    )
    stub = _StubClient(head_error=error)
    monkeypatch.setattr(r2_adapter, "_get_client", lambda: stub)
    monkeypatch.setattr(_settings, "r2_bucket", "test-bucket")

    with pytest.raises(ClientError):
        r2_adapter.head_object_exists("meals/foo/bar.jpg")
