import { notFound, redirect } from "next/navigation";

import { fetchLegalDocument } from "@/lib/legal-fetch";
import { getServerSideUser } from "@/lib/auth";
import { getServerSideConsents } from "@/lib/consents";

import OnboardingForm from "./OnboardingForm";

export const metadata = {
  title: "동의 — BalanceNote",
};

export default async function OnboardingDisclaimerPage() {
  const user = await getServerSideUser();
  if (!user) redirect("/api/auth/cleanup");

  // 이미 동의 완료한 사용자가 페이지 직접 진입 시 dashboard로 — 중복 POST 회피.
  const consents = await getServerSideConsents();
  if (consents?.basic_consents_complete) redirect("/dashboard");

  const [disclaimer, terms, privacy] = await Promise.all([
    fetchLegalDocument("disclaimer", "ko"),
    fetchLegalDocument("terms", "ko"),
    fetchLegalDocument("privacy", "ko"),
  ]);
  if (!disclaimer || !terms || !privacy) notFound();

  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="text-2xl font-semibold tracking-tight mb-4">서비스 이용 동의</h1>
      <p className="text-sm text-zinc-600 mb-6">
        의료기기 미분류 + PIPA 민감정보 별도 동의 의무에 따라 4종 동의가 필요합니다.
      </p>
      <OnboardingForm
        disclaimer={{
          title: disclaimer.title,
          body: disclaimer.body,
          version: disclaimer.version,
        }}
        terms={{ title: terms.title, body: terms.body, version: terms.version }}
        privacy={{ title: privacy.title, body: privacy.body, version: privacy.version }}
      />
    </main>
  );
}
