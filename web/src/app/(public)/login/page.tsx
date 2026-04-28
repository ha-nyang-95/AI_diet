import Link from "next/link";

import { safeNext } from "@/lib/safe-next";

export const metadata = {
  title: "로그인 — BalanceNote",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const { next, error } = await searchParams;
  // open redirect 방어 — `next`가 same-origin 상대 경로일 때만 시작 URL에 포함.
  const validatedNext = safeNext(next, "");
  const startHref = validatedNext
    ? `/api/auth/google/start?next=${encodeURIComponent(validatedNext)}`
    : "/api/auth/google/start";

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <h1 className="text-3xl font-semibold tracking-tight">BalanceNote</h1>
      <p className="mt-2 text-sm text-zinc-500">Google 계정으로 시작하기</p>

      <Link
        href={startHref}
        className="mt-8 inline-flex items-center gap-2 rounded-md bg-blue-600 px-6 py-3 text-white shadow hover:bg-blue-700"
      >
        Google로 계속하기
      </Link>

      {error && (
        <p className="mt-4 text-sm text-red-600" role="alert">
          {error}
        </p>
      )}
    </main>
  );
}
