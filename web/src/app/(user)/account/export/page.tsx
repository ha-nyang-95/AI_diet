/**
 * `/account/export` — 데이터 내보내기 페이지 (Story 5.3 AC5).
 *
 * Next.js 16 App Router Server Component. 1가드(PIPA Art.35 정합 — Story 5.2 ``/account/delete``
 * 패턴 1:1):
 *   1) !user → /api/auth/cleanup
 *   (basic_consents / automated_decision_consent / profile_completed_at 가드 *모두 미적용*
 *    — PIPA Art.35 정보주체 권리는 동의 철회와 독립. 미동의 사용자도 자기 데이터 다운로드
 *    권리 보존.)
 *
 * Path 분리: ``/account/*``는 *데이터 권리* namespace(delete + export). ``/settings/*``는
 * *변경* 흐름(profile/macro-goal). epics.md:817 spec literal *"Web `/account/export`"* 정합.
 */
import { redirect } from "next/navigation";

import { DataExportForm } from "@/features/settings/DataExportForm";
import { getServerSideUser } from "@/lib/auth";

export const metadata = {
  title: "데이터 내보내기 — BalanceNote",
};

export default async function AccountExportPage() {
  const user = await getServerSideUser();
  if (!user) {
    redirect("/api/auth/cleanup");
  }
  // PIPA Art.35 정합 — basic_consents/automated_decision_consent/profile_completed_at
  // 가드 모두 미적용. 어느 동의 단계든 export 가능.

  return (
    <main className="mx-auto max-w-xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          데이터 내보내기
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          내 식단·분석·프로필을 JSON 또는 CSV 파일로 다운로드합니다. PIPA 정보주체 권리
          (데이터 이전·열람권)에 따라 audit 기록 없이 처리됩니다.
        </p>
      </header>
      <DataExportForm />
    </main>
  );
}
