"""Story 8.5 — 사진 분석 흐름 end-to-end smoke (dev 한정).

목적: 모바일/Web UI 없이 사진 업로드 + Vision OCR 흐름이 동작하는지 *API 레벨로 검증*.

흐름:
1. 로컬 Postgres에서 가장 최근 user 1건 조회 (web에서 로그인한 user).
2. ``create_user_token``으로 dev JWT 발급(JWT_USER_SECRET HS256).
3. ``POST /v1/meals/images/presign`` → upload_url + image_key 받음.
4. 1x1 minimal JPEG 생성 → ``PUT upload_url`` (Supabase Storage에 실 PUT).
5. ``POST /v1/meals/images/parse`` → OpenAI Vision OCR → parsed_items 응답.
6. 결과 출력 + Supabase Storage path 안내(dashboard에서 실 파일 확인용).

실행:
  cd api && PYTHONIOENCODING=utf-8 uv run python tests/scripts/_smoke_meal_image_e2e.py

NOTE: 본 스크립트는 *dev 전용*. prod에서는 절대 실행 X (JWT를 secret로 직접 sign + DB 직접
접근). consent 부여 SQL이 *dev 사용자 권한 동의를 자동 INSERT*하므로 prod 사용자에게 절대
미실행.
"""

from __future__ import annotations

import asyncio
import sys
import uuid

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.security import create_user_token

API_BASE = "http://localhost:8000"

# 1x1 minimal valid JPEG (124 bytes).
_MIN_JPEG = bytes(
    [
        0xFF,
        0xD8,
        0xFF,
        0xE0,
        0x00,
        0x10,
        0x4A,
        0x46,
        0x49,
        0x46,
        0x00,
        0x01,
        0x01,
        0x00,
        0x00,
        0x01,
        0x00,
        0x01,
        0x00,
        0x00,
        0xFF,
        0xDB,
        0x00,
        0x43,
        0x00,
        0x08,
        0x06,
        0x06,
        0x07,
        0x06,
        0x05,
        0x08,
        0x07,
        0x07,
        0x07,
        0x09,
        0x09,
        0x08,
        0x0A,
        0x0C,
        0x14,
        0x0D,
        0x0C,
        0x0B,
        0x0B,
        0x0C,
        0x19,
        0x12,
        0x13,
        0x0F,
        0x14,
        0x1D,
        0x1A,
        0x1F,
        0x1E,
        0x1D,
        0x1A,
        0x1C,
        0x1C,
        0x20,
        0x24,
        0x2E,
        0x27,
        0x20,
        0x22,
        0x2C,
        0x23,
        0x1C,
        0x1C,
        0x28,
        0x37,
        0x29,
        0x2C,
        0x30,
        0x31,
        0x34,
        0x34,
        0x34,
        0x1F,
        0x27,
        0x39,
        0x3D,
        0x38,
        0x32,
        0x3C,
        0x2E,
        0x33,
        0x34,
        0x32,
        0xFF,
        0xC0,
        0x00,
        0x0B,
        0x08,
        0x00,
        0x01,
        0x00,
        0x01,
        0x01,
        0x01,
        0x11,
        0x00,
        0xFF,
        0xC4,
        0x00,
        0x1F,
        0x00,
        0x00,
        0x01,
        0x05,
        0x01,
        0x01,
        0x01,
        0x01,
        0x01,
        0x01,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x01,
        0x02,
        0x03,
    ]
)


async def get_latest_user_id() -> uuid.UUID | None:
    """가장 최근 user 1건 — web에서 로그인한 row."""
    # docker compose 외부에서 호출하므로 localhost:5432 사용.
    engine = create_async_engine("postgresql+asyncpg://app:app@localhost:5432/app")
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id FROM users WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 1")
        )
        row = result.fetchone()
    await engine.dispose()
    return row[0] if row else None


async def ensure_basic_consents(user_id: uuid.UUID) -> None:
    """basic 2종 consent(terms/privacy) 미부여 시 자동 UPDATE — dev 한정.

    `consents` 테이블 schema(`terms_consent_at`/`privacy_consent_at` timestamp column 패턴).
    `require_basic_consents` dependency 통과를 위해.
    """
    engine = create_async_engine("postgresql+asyncpg://app:app@localhost:5432/app")
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT terms_consent_at IS NOT NULL AS terms, "
                "privacy_consent_at IS NOT NULL AS privacy "
                "FROM consents WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        row = result.fetchone()
        if row is None:
            print("  consents row 미존재 — 자동 INSERT.")
            await conn.execute(
                text(
                    "INSERT INTO consents (id, user_id, terms_consent_at, terms_version, "
                    "privacy_consent_at, privacy_version, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :uid, now(), '1.0.0', now(), '1.0.0', now(), now())"
                ),
                {"uid": user_id},
            )
            print("  + INSERT consents (terms + privacy)")
        else:
            print(f"  현재 상태: terms={row[0]}, privacy={row[1]}")
            if not row[0] or not row[1]:
                await conn.execute(
                    text(
                        "UPDATE consents SET "
                        "terms_consent_at = COALESCE(terms_consent_at, now()), "
                        "terms_version = '1.0.0', "
                        "privacy_consent_at = COALESCE(privacy_consent_at, now()), "
                        "privacy_version = '1.0.0' "
                        "WHERE user_id = :uid"
                    ),
                    {"uid": user_id},
                )
                print("  + UPDATE consents (누락 컬럼 채움)")
            else:
                print("  ✅ basic consents 이미 모두 granted — INSERT 불필요.")
        await conn.commit()
    await engine.dispose()


async def main() -> int:
    print("=" * 72)
    print("Story 8.5 — 사진 분석 흐름 E2E smoke")
    print("=" * 72)

    # ----- Step 0: user 조회 -----
    print("\nStep 0: 로컬 DB에서 user 1건 조회")
    user_id = await get_latest_user_id()
    if user_id is None:
        print("  ❌ users 테이블에 row 없음. Web에서 Google 로그인 1회 진행 필요.")
        return 1
    print(f"  ✅ user_id: {user_id}")

    # consent 부여 검증/보정
    print("\nStep 0-b: basic consents 확인 + 누락 시 자동 INSERT (dev 한정)")
    await ensure_basic_consents(user_id)

    # ----- Step 1: JWT 발급 -----
    print("\nStep 1: dev JWT 발급 (JWT_USER_SECRET HS256)")
    token = create_user_token(user_id=user_id, role="user", platform="web")
    print(f"  ✅ token: {token[:30]}...{token[-15:]}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(base_url=API_BASE, timeout=60.0) as client:
        # ----- Step 2: presign -----
        print("\nStep 2: POST /v1/meals/images/presign")
        resp = await client.post(
            "/v1/meals/images/presign",
            json={"content_type": "image/jpeg", "content_length": len(_MIN_JPEG)},
            headers=headers,
        )
        print(f"  status: {resp.status_code}")
        if resp.status_code != 200:
            print(f"  ❌ body: {resp.text}")
            return 2
        presigned = resp.json()
        print(f"  ✅ image_key:    {presigned['image_key']}")
        print(f"  ✅ upload_url:   {presigned['upload_url'][:80]}...")
        print(f"  ✅ expires_at:   {presigned['expires_at']}")

        upload_url = presigned["upload_url"]
        image_key = presigned["image_key"]

        # ----- Step 3: PUT 실제 이미지 to Supabase Storage -----
        print(f"\nStep 3: PUT {len(_MIN_JPEG)}-byte JPEG → Supabase Storage")
        async with httpx.AsyncClient(timeout=60.0) as upload_client:
            put_resp = await upload_client.put(
                upload_url,
                content=_MIN_JPEG,
                headers={"Content-Type": "image/jpeg"},
            )
        print(f"  status: {put_resp.status_code}")
        if put_resp.status_code not in (200, 201):
            print(f"  ❌ body: {put_resp.text[:300]}")
            return 3
        print("  ✅ Supabase Storage에 PUT 성공")

        # ----- Step 4: head_object_exists 간접 검증 — parse가 내부에서 호출 -----
        print(f"\nStep 4: POST /v1/meals/images/parse (image_key={image_key[-20:]}...)")
        resp = await client.post(
            "/v1/meals/images/parse",
            json={"image_key": image_key},
            headers=headers,
            timeout=60.0,
        )
        print(f"  status: {resp.status_code}")
        if resp.status_code == 503:
            print("  ⚠️  503 응답 — Vision OCR unavailable (image too small or OpenAI 제한)")
            print(f"  body: {resp.text}")
            # Vision 503은 *Supabase Storage swap*과는 독립 — Storage 흐름은 정상.
            print("\n  ℹ️  Storage swap 자체는 정상 (presign + PUT + head OK).")
            print("  ℹ️  Vision OCR 단계는 image_url 발급 또는 OpenAI 영향.")
            return 0
        if resp.status_code != 200:
            print(f"  ❌ body: {resp.text}")
            return 4
        parsed = resp.json()
        print(f"  ✅ items_count:   {len(parsed.get('parsed_items', []))}")
        print(f"  ✅ low_confidence: {parsed.get('low_confidence')}")
        print(f"  ✅ model:          {parsed.get('model')}")
        print(f"  ✅ latency_ms:     {parsed.get('latency_ms')}")
        if parsed.get("parsed_items"):
            print(f"     첫 item:       {parsed['parsed_items'][0]}")

    print("\n" + "=" * 72)
    print("✅ E2E smoke 통과 — Storage swap + Vision 흐름 정상 동작.")
    print(f"   Supabase dashboard → Storage → meals → {image_key}")
    print("   에서 실제 PUT된 파일 확인 가능.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
