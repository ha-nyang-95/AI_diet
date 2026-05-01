import { redirect } from "next/navigation";

import { getServerSideUser } from "@/lib/auth";
import { getServerSideConsents } from "@/lib/consents";

import HealthProfileForm from "./HealthProfileForm";

export const metadata = {
  title: "건강 프로필 입력 — BalanceNote",
};

/**
 * Story 1.5 AC11 — 건강 프로필 입력 화면 (RSC + 가드 chain).
 *
 * 가드 순서: (1) 인증 → (2) basic 동의 → (3) AD 동의 → (4) 이미 입력 완료 시 dashboard.
 * Story 1.4 P12 패턴(중복 POST 회피) 정합 — 이미 입력된 사용자가 본 페이지 직접 진입 시
 * dashboard로 redirect.
 */
export default async function OnboardingProfilePage() {
  const user = await getServerSideUser();
  if (!user) redirect("/api/auth/cleanup");

  const consents = await getServerSideConsents();
  if (!consents?.basic_consents_complete) redirect("/onboarding/disclaimer");
  if (!consents.automated_decision_consent_complete) redirect("/onboarding/automated-decision");
  // 이미 프로필 입력 완료 사용자가 본 페이지 직접 진입 시 dashboard — 중복 POST 회피.
  // ``!user.profile_completed_at`` 으로 dashboard guard와 동일 식 — null/undefined 양쪽
  // 안전, 빈 문자열 같은 falsy non-null 값에 대한 redirect loop 차단.
  if (user.profile_completed_at) redirect("/dashboard");

  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="mb-2 text-2xl font-semibold tracking-tight">건강 프로필 입력</h1>
      <p className="mb-6 text-sm text-zinc-600">
        나이·체중·신장·활동 수준·건강 목표·알레르기를 입력하면 분석 정확도가 높아집니다.
      </p>
      <HealthProfileForm />
    </main>
  );
}
