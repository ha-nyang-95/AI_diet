/**
 * Admin landing — Story 7.4 (FR36/FR38 wire 완료).
 */
import Link from "next/link";

export const metadata = {
  title: "관리자 대시보드 — BalanceNote",
};

export default function AdminDashboardPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold">관리자 대시보드</h2>
      <p className="text-sm text-zinc-600">
        사용자 검색·식단 이력·프로필 수정과 self-audit 활동 로그를 사용할 수 있습니다.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border p-4">
          <h3 className="font-medium">사용자 관리</h3>
          <p className="mt-1 text-sm text-zinc-500">FR36 — 사용자 검색·이력·프로필 수정</p>
          <Link
            href="/admin/users"
            className="mt-2 inline-block text-sm text-blue-600 hover:underline"
          >
            사용자 검색 →
          </Link>
        </div>
        <div className="rounded-lg border p-4">
          <h3 className="font-medium">감사 로그 (self-audit)</h3>
          <p className="mt-1 text-sm text-zinc-500">FR38 — 내 활동 audit 로그 조회</p>
          <Link
            href="/admin/audit-logs"
            className="mt-2 inline-block text-sm text-blue-600 hover:underline"
          >
            내 활동 로그 →
          </Link>
        </div>
      </div>
    </div>
  );
}
