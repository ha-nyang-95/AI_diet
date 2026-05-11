/**
 * Admin 사용자 상세 페이지 — Story 7.2 AC#8 (FR36).
 *
 * Server Component shell — `cookies()`로 admin token 추출 + SSR fetch + initialDetail
 * Client Component prefill. cross-origin server-side fetch는 cookie 미첨부 → Authorization
 * 헤더 forward 패턴(Story 4.3 baseline 정합).
 *
 * 미존재 user_id → Next.js 404. 401(admin token 부재/만료) → /admin/login redirect.
 */
import type { Metadata } from "next";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";

import type { AdminUserDetailResponse } from "@/features/admin/types";
import { UserDetailClient } from "@/features/admin/UserDetailClient";

export const metadata: Metadata = { title: "사용자 상세 — 관리자" };

async function fetchUserDetail(userId: string): Promise<AdminUserDetailResponse | null> {
  const cookieStore = await cookies();
  const adminToken = cookieStore.get("bn_admin_access")?.value;
  if (!adminToken) return null;
  const apiBase = process.env.API_BASE_URL ?? "http://localhost:8000";
  const response = await fetch(`${apiBase}/v1/admin/users/${userId}`, {
    headers: { Authorization: `Bearer ${adminToken}` },
    cache: "no-store",
  });
  if (response.status === 404) return null;
  if (response.status === 401 || response.status === 403) {
    // SSR 흐름에서 throw + Next.js error 화면 회피 — 토큰 만료/박탈 모두 admin login 재진입.
    redirect("/admin/login?error=expired");
  }
  if (!response.ok) {
    throw new Error(`fetch failed: ${response.status}`);
  }
  return (await response.json()) as AdminUserDetailResponse;
}

export default async function AdminUserDetailPage({
  params,
}: {
  params: Promise<{ user_id: string }>;
}) {
  const { user_id: userId } = await params;
  const detail = await fetchUserDetail(userId);
  if (!detail) {
    notFound();
  }
  return <UserDetailClient userId={userId} initialDetail={detail} />;
}
