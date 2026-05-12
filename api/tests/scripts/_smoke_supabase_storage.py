"""Story 8.5 — Supabase Storage 연결성 smoke test (수동 실행).

Render 배포 *전*에 dev에서 Supabase Storage 호출이 정상인지 검증 — 실제 API 호출 1회로:
1. _get_supabase_storage() lazy client 생성 (settings 환경변수 로드 확인)
2. create_presigned_upload(image/jpeg, 1234 bytes) 호출 → signed PUT URL 반환
3. resolve_public_url(image_key) 호출 → 1h signed download URL 반환
4. head_object_exists() 호출 — 미존재 path에서 False 정상 반환

실제 사진 PUT은 *수행 X* — bucket에 garbage 안 남김. URL 발급/구조 검증만.

실행:
  cd api && uv run python tests/scripts/_smoke_supabase_storage.py
"""

from __future__ import annotations

import asyncio
import uuid

from app.adapters import r2 as r2_adapter
from app.core.config import settings


async def main() -> None:
    print("=" * 70)
    print("Supabase Storage smoke test")
    print("=" * 70)
    print(f"STORAGE_PROVIDER:        {settings.storage_provider}")
    print(f"SUPABASE_URL:            {settings.supabase_url}")
    print(f"SUPABASE_STORAGE_BUCKET: {settings.supabase_storage_bucket}")
    sk = settings.supabase_service_key
    print(f"SUPABASE_SERVICE_KEY:    {sk[:20]}...{sk[-6:] if len(sk) > 26 else ''}")
    print()

    if settings.storage_provider != "supabase":
        print("⚠️  STORAGE_PROVIDER != 'supabase'. Skipping Supabase-specific tests.")
        return

    user_id = uuid.uuid4()
    print(f"Test user_id: {user_id}")
    print()

    # ----- Step 1: create_presigned_upload -----
    print("Step 1: create_presigned_upload(content_type='image/jpeg', length=1234)")
    try:
        presigned = await asyncio.to_thread(
            r2_adapter.create_presigned_upload,
            user_id,
            "image/jpeg",
            1234,
        )
        print(f"  ✅ image_key:    {presigned.image_key}")
        print(f"  ✅ upload_url:   {presigned.upload_url[:80]}...")
        print(f"  ✅ public_url:   {presigned.public_url[:80]}...")
        print(f"  ✅ expires_at:   {presigned.expires_at.isoformat()}")
        print(f"  ✅ content_type: {presigned.content_type}")
    except Exception as exc:
        print(f"  ❌ FAILED: {type(exc).__name__}: {exc}")
        raise

    print()

    # ----- Step 2: resolve_public_url for newly-created key -----
    print(f"Step 2: resolve_public_url({presigned.image_key})")
    try:
        url = await asyncio.to_thread(r2_adapter.resolve_public_url, presigned.image_key)
        if url:
            print(f"  ✅ signed download URL: {url[:80]}...")
        else:
            print("  ⚠️  resolve_public_url returned None")
    except Exception as exc:
        print(f"  ❌ FAILED: {type(exc).__name__}: {exc}")
        raise

    print()

    # ----- Step 3: head_object_exists for non-uploaded key (should return False) -----
    print(f"Step 3: head_object_exists({presigned.image_key}) — bucket에 PUT 안 했으니 False")
    try:
        exists = await asyncio.to_thread(r2_adapter.head_object_exists, presigned.image_key)
        if exists:
            print(f"  ⚠️  Returned True — 이전 테스트 잔존물? image_key: {presigned.image_key}")
        else:
            print("  ✅ Returned False (정상 — 아직 PUT 안 했으므로 미존재)")
    except Exception as exc:
        print(f"  ❌ FAILED: {type(exc).__name__}: {exc}")
        raise

    print()
    print("=" * 70)
    print("✅ Supabase Storage smoke test 통과 — Storage 분기 정상 동작.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
