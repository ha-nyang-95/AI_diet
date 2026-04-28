import { notFound, redirect } from "next/navigation";

import { fetchLegalDocument } from "@/lib/legal-fetch";
import { getServerSideUser } from "@/lib/auth";
import { getServerSideConsents } from "@/lib/consents";

import OnboardingForm from "./OnboardingForm";

export const metadata = {
  title: "자동화 의사결정 동의 — BalanceNote",
};

export default async function OnboardingAutomatedDecisionPage() {
  const user = await getServerSideUser();
  if (!user) redirect("/login");

  // basic 4종 미통과 사용자는 disclaimer로 강제(흐름 강제, Story 1.4 AC9).
  const consents = await getServerSideConsents();
  if (!consents?.basic_consents_complete) redirect("/onboarding/disclaimer");
  // 이미 AD 동의 완료한 사용자가 페이지 직접 진입 시 dashboard로 — 중복 POST 회피.
  if (consents.automated_decision_consent_complete) redirect("/dashboard");

  const doc = await fetchLegalDocument("automated-decision", "ko");
  if (!doc) notFound();

  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="text-2xl font-semibold tracking-tight mb-2">자동화 의사결정 동의</h1>
      <p className="text-xs font-semibold text-orange-700 mb-6">
        별도 동의 항목입니다 (PIPA 2026.03.15)
      </p>
      <OnboardingForm
        title={doc.title}
        body={doc.body}
        version={doc.version}
      />
    </main>
  );
}
