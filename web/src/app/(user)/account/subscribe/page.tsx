/**
 * `/account/subscribe` — 구독 신청 페이지 (Story 6.1 AC8).
 *
 * Next.js 16 App Router Server Component. 2가드 (Story 5.x `/account/delete` 1가드 +
 * 결제 흐름이라 basic_consents 추가):
 *   1) !user → /api/auth/cleanup
 *   2) !basic_consents_complete → /onboarding/consent (require_basic_consents 정합)
 *
 * Path 분리: ``/settings/subscription`` 없음 — 결제 흐름은 별 namespace로 격리(우발 진입
 * 차단 + Story 6.2 cancel/history도 같은 ``/account/`` 그룹으로 forward).
 */
import { redirect } from "next/navigation";

import { SubscribeForm } from "@/features/payments/SubscribeForm";
import { getServerSideUser } from "@/lib/auth";
import { getServerSideConsents } from "@/lib/consents";

export const metadata = {
  title: "구독 신청 — BalanceNote",
};

export default async function SubscribePage() {
  const user = await getServerSideUser();
  if (!user) {
    redirect("/api/auth/cleanup");
  }

  const consents = await getServerSideConsents();
  if (!consents?.basic_consents_complete) {
    redirect("/onboarding/consent");
  }

  return (
    <main className="mx-auto max-w-xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">구독 신청</h1>
        <p className="mt-1 text-sm text-slate-600">
          정기결제 1플랜(월 9,900원)을 신청합니다. Toss 결제 화면에서 카드 정보를 입력해
          주세요.
        </p>
      </header>
      <SubscribeForm userId={user.id} customerEmail={user.email} />
    </main>
  );
}
