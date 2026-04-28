"use client";

import { useState } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * Web logout 트리거 (Story 1.2 AC#5).
 *
 * 백엔드 `POST /v1/auth/logout` 호출 — `credentials: "include"`로 httpOnly 쿠키 자동 첨부.
 * 백엔드가 `Set-Cookie: bn_*=; Max-Age=0`로 expire한 후, 클라이언트는 `/login`으로 라우팅.
 */
export function LogoutButton() {
  const [pending, setPending] = useState(false);

  async function handleLogout() {
    setPending(true);
    try {
      await fetch(`${API_BASE_URL}/v1/auth/logout`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
    } catch {
      // ignore — 백엔드 도달 실패해도 로컬 라우팅은 진행.
    }
    // location.href로 navigation — 쿠키 변경 반영 + RSC re-render 강제.
    window.location.href = "/login";
  }

  return (
    <button
      type="button"
      onClick={handleLogout}
      disabled={pending}
      className="mt-8 inline-flex items-center gap-2 rounded-md border border-zinc-300 bg-white px-4 py-2 text-sm text-zinc-700 hover:bg-zinc-50 disabled:opacity-50"
    >
      {pending ? "로그아웃 중..." : "로그아웃"}
    </button>
  );
}
