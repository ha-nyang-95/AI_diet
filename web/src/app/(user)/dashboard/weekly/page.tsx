/**
 * `/dashboard/weekly` — 주간 리포트 4종 차트 (Story 4.3).
 *
 * Next.js 16 App Router Server Component. SSR fetch + 4 가드(Story 1.2 패턴 정합):
 *   1) !user → /api/auth/cleanup
 *   2) !basic_consents → /onboarding/disclaimer
 *   3) !automated_decision_consent → /onboarding/automated-decision
 *   4) !profile_completed_at → /onboarding/profile
 *
 * KST 7일 윈도우 [today - 6일, today]를 ``computeWeeklyWindowKst()``로 계산해 백엔드
 * ``GET /v1/reports/weekly`` SSR fetch. 응답을 client component ``WeeklyReport``에
 * props로 forward.
 */

import { redirect } from "next/navigation";

import { WeeklyReport } from "@/features/reports/WeeklyReport";
import { getServerSideUser } from "@/lib/auth";
import { getServerSideConsents } from "@/lib/consents";
import { computeWeeklyWindowKst, getServerSideWeeklyReport } from "@/lib/reports";

export const metadata = {
  title: "주간 리포트 — BalanceNote",
};

interface UserHealthProfile {
  allergies: string[] | null;
}

/**
 * Story 4.3 CR P10 — 401은 redirect로 명시(silently `[]` 차단), 그 외 non-ok는
 * `null` 반환해 UI가 "fetch 실패"와 "알레르기 미설정"을 구분.
 */
async function fetchUserAllergies(): Promise<readonly string[] | null> {
  // ``/v1/users/me/profile`` GET — 인증만, 동의 게이트 X (PIPA Art.35 정합).
  const { cookies } = await import("next/headers");
  const store = await cookies();
  const access = store.get("bn_access")?.value;
  if (!access) {
    redirect("/api/auth/cleanup");
  }
  const apiBase = process.env.API_BASE_URL ?? "http://localhost:8000";
  const response = await fetch(`${apiBase}/v1/users/me/profile`, {
    headers: { Cookie: `bn_access=${access}` },
    cache: "no-store",
  });
  if (response.status === 401) {
    redirect("/api/auth/cleanup");
  }
  if (!response.ok) return null;
  const profile = (await response.json()) as UserHealthProfile;
  return profile.allergies ?? [];
}

export default async function WeeklyReportPage() {
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

  const { from_date, to_date } = computeWeeklyWindowKst();
  const [report, userAllergies] = await Promise.all([
    getServerSideWeeklyReport(from_date, to_date),
    fetchUserAllergies(),
  ]);

  if (report === null) {
    // ``getServerSideWeeklyReport``가 non-ok 시 null 반환(getServerSideUser 패턴 정합).
    // 페이지 측에서 빈 화면 fallback 결정 — error boundary 회피.
    return (
      <main className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          주간 리포트
        </h1>
        <p className="mt-3 text-sm text-slate-500">
          리포트를 불러올 수 없습니다 — 잠시 후 다시 시도해주세요.
        </p>
      </main>
    );
  }

  return <WeeklyReport report={report} userAllergies={userAllergies} />;
}
