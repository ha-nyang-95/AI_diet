/**
 * `/settings/profile` — 건강 프로필 수정 폼 (Story 5.1 AC5).
 *
 * Next.js 16 App Router Server Component. SSR fetch + 4 가드(Story 4.4 매크로 목표
 * 페이지 SOT 1:1 정합):
 *   1) !user → /api/auth/cleanup
 *   2) !basic_consents → /onboarding/disclaimer
 *   3) !automated_decision_consent → /onboarding/automated-decision
 *   4) !profile_completed_at → /onboarding/profile (미입력 사용자는 *최초 입력* 강제)
 *
 * SSR로 기존 ``health profile``을 fetch해 client component prefill.
 */

import { redirect } from "next/navigation";

import { HealthProfileEditForm } from "@/features/settings/HealthProfileEditForm";
import { getServerSideUser } from "@/lib/auth";
import { getServerSideConsents } from "@/lib/consents";
import { getServerSideHealthProfile } from "@/lib/health-profile";

export const metadata = {
  title: "건강 프로필 수정 — BalanceNote",
};

export default async function HealthProfileSettingsPage() {
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

  const initial = await getServerSideHealthProfile();
  if (!initial) {
    // 401/5xx fallback — 비정상 상태에서 폼을 prefill 없이 mount하면 zod required 오류
    // 발화. global error boundary로 위임(Story 4.3/4.4 정합).
    throw new Error("Failed to load health profile for prefill");
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          건강 프로필 수정
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          나이·체중·신장·활동 수준·건강 목표·알레르기를 수정하면 *다음 분석부터*
          반영됩니다.
        </p>
      </header>
      <HealthProfileEditForm initial={initial} />
    </main>
  );
}
