/**
 * Admin layout — Story 7.1 AC#6 (server-side defense-in-depth guard).
 *
 * middleware는 *라우팅 차단*을 담당, layout은 *2차 로컬 검증* (JWT exp/role/iss decode).
 * 보호된 admin endpoint 실 호출 시 백엔드 ``current_admin``이 *3차 진짜 검증* (서명 + DB role).
 */
import type { ReactNode } from "react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { evaluateAdminCookie } from "@/lib/admin-auth";

export const metadata = {
  title: "관리자 — BalanceNote",
};

export default async function AdminLayout({
  children,
}: {
  children: ReactNode;
}) {
  const cookieStore = await cookies();
  const adminToken = cookieStore.get("bn_admin_access")?.value;
  const result = evaluateAdminCookie(adminToken);

  if (result.kind === "missing") {
    redirect("/admin/login");
  }
  if (result.kind === "expired") {
    redirect("/admin/login?error=expired");
  }
  if (result.kind === "forbidden") {
    redirect("/admin/login?error=forbidden");
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b px-6 py-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold">관리자 — BalanceNote</h1>
        {/* Story 7.1 CR — POST form (GET 링크는 prefetch/CSRF로 우발 logout 위험). */}
        <form action="/api/auth/admin/logout" method="POST">
          <button
            type="submit"
            className="text-sm text-blue-600 hover:underline bg-transparent border-0 p-0 cursor-pointer"
          >
            관리자 로그아웃
          </button>
        </form>
      </header>
      <main className="flex-1 p-6">{children}</main>
    </div>
  );
}
