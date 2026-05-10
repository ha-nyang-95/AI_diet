/**
 * Admin 로그인 — Story 7.1 AC#5 (실 OAuth chain UI).
 *
 * 분기:
 * - ``bn_access`` 쿠키 부재 → Google OAuth chain start (``/api/auth/google/start?next=
 *   /admin/login?next=<original>``) 버튼.
 * - ``bn_access`` 쿠키 보유 → ``/api/auth/admin/exchange?next=<original>`` 1-click 진입 버튼.
 *
 * chain 단축 거부: ``after_admin_exchange=1`` 같은 자동 chain flag 미사용 — 관리자 권한 진입은
 * *명시 액션*이라야 (Story 1.2 SOT 정합).
 */
import Link from "next/link";
import { cookies } from "next/headers";

import { safeNext } from "@/lib/safe-next";

export const metadata = {
  title: "관리자 로그인 — BalanceNote",
};

const ERROR_MESSAGES: Record<string, string> = {
  login_first: "먼저 일반 로그인이 필요합니다.",
  role_required: "이 계정에는 관리자 권한이 없습니다. 관리자에게 문의하세요.",
  exchange_failed: "관리자 인증 교환에 실패했습니다. 다시 시도해 주세요.",
  cookie_not_issued:
    "관리자 쿠키 발급에 실패했습니다. 도메인 설정을 확인하세요.",
  expired: "관리자 세션이 만료되었습니다 (8시간). 다시 로그인해 주세요.",
  forbidden: "관리자 권한이 필요한 페이지입니다.",
};

export default async function AdminLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const { next, error } = await searchParams;
  const validatedNext = safeNext(next, "/admin");

  const cookieStore = await cookies();
  const isLoggedIn = Boolean(cookieStore.get("bn_access")?.value);

  const errorMessage = error
    ? ERROR_MESSAGES[error] ?? "알 수 없는 오류"
    : null;

  if (isLoggedIn) {
    // Story 7.1 CR — POST form (GET 링크는 prefetch/SafeLinks/CSRF로 우발 exchange 위험).
    const exchangeAction = `/api/auth/admin/exchange?next=${encodeURIComponent(
      validatedNext,
    )}`;
    return (
      <main className="flex min-h-screen flex-col items-center justify-center p-8">
        <h1 className="text-2xl font-semibold tracking-tight">관리자 로그인</h1>
        <p className="mt-2 text-sm text-zinc-500">
          일반 로그인된 상태입니다. 관리자 권한으로 진입하시겠습니까?
        </p>
        {errorMessage && (
          <p className="mt-4 text-sm text-red-600" role="alert">
            {errorMessage}
          </p>
        )}
        <form action={exchangeAction} method="POST" className="mt-8">
          <button
            type="submit"
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-6 py-3 text-white shadow hover:bg-blue-700"
          >
            관리자 권한으로 진입
          </button>
        </form>
        <Link
          href="/dashboard"
          className="mt-4 text-sm text-blue-600 hover:underline"
        >
          일반 대시보드로 돌아가기
        </Link>
      </main>
    );
  }

  // 미로그인 — Google OAuth chain start (next=/admin/login chain 후 admin exchange).
  const startHref = `/api/auth/google/start?next=${encodeURIComponent(
    `/admin/login?next=${validatedNext}`,
  )}`;
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <h1 className="text-2xl font-semibold tracking-tight">관리자 로그인</h1>
      <p className="mt-2 text-sm text-zinc-500">
        관리자 계정으로 시작하기 (별 secret + 8시간 만료 + refresh 미지원)
      </p>
      {errorMessage && (
        <p className="mt-4 text-sm text-red-600" role="alert">
          {errorMessage}
        </p>
      )}
      <Link
        href={startHref}
        className="mt-8 inline-flex items-center gap-2 rounded-md bg-blue-600 px-6 py-3 text-white shadow hover:bg-blue-700"
      >
        Google로 계속하기
      </Link>
    </main>
  );
}
