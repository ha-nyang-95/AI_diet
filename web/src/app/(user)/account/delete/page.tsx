/**
 * `/account/delete` — 회원 탈퇴 페이지 (Story 5.2 AC6).
 *
 * Next.js 16 App Router Server Component. 1가드(PIPA Art.35 정합 — Story 5.1과 분리):
 *   1) !user → /api/auth/cleanup
 *   (basic_consents / automated_decision_consent / profile_completed_at 가드 미적용 —
 *    PIPA Art.35 정보주체 권리는 동의 철회와 독립. 미동의 사용자도 탈퇴 가능해야 권리
 *    봉쇄 X.)
 *
 * Path 분리: ``/settings/profile``과 *별 namespace*. settings는 *프로필/매크로 목표*
 * 같은 *변경* 흐름이고 탈퇴는 *되돌리기 어려운* 액션이라 별 path로 격리(우발 진입 차단).
 */
import { redirect } from "next/navigation";

import { AccountDeleteForm } from "@/features/settings/AccountDeleteForm";
import { getServerSideUser } from "@/lib/auth";

export const metadata = {
  title: "회원 탈퇴 — BalanceNote",
};

export default async function AccountDeletePage() {
  const user = await getServerSideUser();
  if (!user) {
    redirect("/api/auth/cleanup");
  }
  // PIPA Art.35 정합 — basic_consents/automated_decision_consent/profile_completed_at
  // 가드 모두 미적용. 어느 동의 단계든 탈퇴 가능.

  return (
    <main className="mx-auto max-w-xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">회원 탈퇴</h1>
        <p className="mt-1 text-sm text-slate-600">
          탈퇴 시 30일 후 모든 데이터가 영구 파기됩니다. 30일 내 같은 Google 계정으로
          재로그인 시 안내됩니다.
        </p>
      </header>
      <AccountDeleteForm />
    </main>
  );
}
