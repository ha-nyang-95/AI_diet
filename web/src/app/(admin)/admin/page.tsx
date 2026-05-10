/**
 * Admin landing — Story 7.1 AC#6 placeholder + 7.2/7.4 forward links.
 *
 * 본 스토리는 ``/admin/users``/``/admin/audit-logs``를 신설하지 X (7.2/7.4 forward).
 * middleware/layout은 ``/admin`` prefix 모두 가드하지만 라우트 자체 부재 시 Next.js 404
 * — expected (사용자에게 forward 안내).
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
        Story 7.2에서 사용자 검색·식단 이력·프로필 수정이 추가됩니다.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border p-4">
          <h3 className="font-medium">사용자 관리</h3>
          <p className="mt-1 text-sm text-zinc-500">FR36 — 7.2에서 추가</p>
          <Link
            href="/admin/users"
            className="mt-2 inline-block text-sm text-blue-600 hover:underline"
          >
            사용자 검색 →
          </Link>
        </div>
        <div className="rounded-lg border p-4">
          <h3 className="font-medium">감사 로그 (self-audit)</h3>
          <p className="mt-1 text-sm text-zinc-500">FR38 — 7.4에서 추가</p>
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
