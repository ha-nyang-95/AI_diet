import { redirect } from "next/navigation";

import { getServerSideUser } from "@/lib/auth";
import { getServerSideConsents } from "@/lib/consents";

import { LogoutButton } from "./logout-button";

export const metadata = {
  title: "대시보드 — BalanceNote",
};

export default async function DashboardPage() {
  const user = await getServerSideUser();
  if (!user) {
    redirect("/login");
  }

  // Story 1.3 AC2 — 동의 미통과 사용자는 onboarding 강제. 인증 게이트(`current_user`)와
  // 분리된 동의 게이트로 처리(architecture line 311 정합).
  // Story 1.4 AC9 — 자동화 의사결정 동의도 별도 강제(PIPA 2026.03.15).
  // Story 1.5 AC11 — 건강 프로필 미입력 사용자는 onboarding/profile 강제.
  // 가드 순서: (1) !user → /login, (2) !basic → /disclaimer,
  // (3) !AD → /automated-decision, (4) !profile_completed_at → /onboarding/profile.
  const consents = await getServerSideConsents();
  if (!consents?.basic_consents_complete) {
    redirect("/onboarding/disclaimer");
  }
  if (!consents.automated_decision_consent_complete) {
    redirect("/onboarding/automated-decision");
  }
  if (!user.profile_completed_at) {
    redirect("/onboarding/profile");
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <h1 className="text-2xl font-semibold tracking-tight">
        안녕하세요, {user.display_name ?? user.email}
      </h1>
      <p className="mt-2 text-sm text-zinc-500">
        (Story 4.3에서 채워짐 — 주간 리포트 차트)
      </p>
      <LogoutButton />
    </main>
  );
}
