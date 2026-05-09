/**
 * `/account/subscribe/history` — 결제 이력 페이지 (Story 6.2 AC7).
 *
 * Next.js 16 App Router Server Component. 1가드 (Story 5.x ``/account/delete`` 패턴 정합):
 *   1) !user → /api/auth/cleanup
 *
 * basic_consents 가드 **미적용** — PIPA Art.35 정합(자기 결제 이력 조회는 동의 철회와
 * 독립). Story 5.3 데이터 내보내기 패턴 정합.
 *
 * Path: ``/account/subscribe/history`` — 같은 ``/account/`` 그룹으로 cancel/history forward.
 */
import { redirect } from "next/navigation";

import { PaymentHistoryTable } from "@/features/payments/PaymentHistoryTable";
import { getServerSideUser } from "@/lib/auth";

export const metadata = {
  title: "결제 이력 — BalanceNote",
};

export default async function PaymentHistoryPage() {
  const user = await getServerSideUser();
  if (!user) {
    redirect("/api/auth/cleanup");
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">결제 이력</h1>
        <p className="mt-1 text-sm text-slate-600">
          최근 결제 시점과 영수증을 확인할 수 있습니다.
        </p>
      </header>
      <PaymentHistoryTable />
    </main>
  );
}
