/**
 * Admin 로그인 placeholder (Story 1.2 AC#3 가드 대상 페이지).
 *
 * 실제 admin 교환(`/v1/auth/admin/exchange`) UI는 Story 7(관리자)에서 구현.
 * 본 페이지는 middleware redirect 대상 404 회피를 위한 최소 스텁.
 */
import Link from "next/link";

export const metadata = {
  title: "관리자 로그인 — BalanceNote",
};

export default function AdminLoginPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <h1 className="text-2xl font-semibold tracking-tight">관리자 로그인</h1>
      <p className="mt-2 text-sm text-zinc-500">
        (Story 7에서 채워짐 — 일반 사용자 로그인 후 admin 교환 흐름)
      </p>
      <Link href="/login" className="mt-8 text-sm text-blue-600 hover:underline">
        일반 사용자 로그인으로 이동
      </Link>
    </main>
  );
}
