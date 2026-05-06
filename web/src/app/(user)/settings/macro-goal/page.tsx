/**
 * `/settings/macro-goal` — 매크로 목표 입력 폼 (Story 4.4 AC4).
 *
 * Next.js 16 App Router Server Component. SSR fetch + 4 가드(Story 4.3 패턴 정합):
 *   1) !user → /api/auth/cleanup
 *   2) !basic_consents → /onboarding/disclaimer
 *   3) !automated_decision_consent → /onboarding/automated-decision
 *   4) !profile_completed_at → /onboarding/profile
 *
 * SSR로 기존 ``macro_goal``을 fetch해 client component MacroGoalForm prefill.
 */

import { redirect } from "next/navigation";

import { MacroGoalForm } from "@/features/settings/MacroGoalForm";
import { getServerSideUser } from "@/lib/auth";
import { getServerSideConsents } from "@/lib/consents";
import { getServerSideMacroGoal } from "@/lib/macro-goal";

export const metadata = {
  title: "매크로 목표 — BalanceNote",
};

export default async function MacroGoalSettingsPage() {
  const user = await getServerSideUser();
  if (!user) {
    redirect("/api/auth/cleanup");
  }
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

  const initial = await getServerSideMacroGoal();

  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          매크로/칼로리 목표 조정
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          설정 후 *다음 분석부터* 권장 표시에 반영됩니다. 미입력 항목은 기본
          권장(KDRIs)이 적용됩니다.
        </p>
      </header>
      <MacroGoalForm initial={initial} />
    </main>
  );
}
