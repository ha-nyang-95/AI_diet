"use client";

/**
 * `/account/subscribe/fail` — Toss 결제 실패 페이지 (Story 6.1 AC8).
 *
 * Toss fail callback URL — URL query에 ``code`` / ``message`` / ``orderId`` 포함(Toss
 * 표준). server에 호출 X (Toss 측 결제 미승인 → 우리 측 payment_log INSERT 불필요).
 *
 * 사용자에게 한국어 에러 메시지 노출 + *"다시 시도"* 버튼(/account/subscribe로 redirect).
 *
 * Story 8.5 AC9 — `useSearchParams()`는 prerender 단계에서 값이 없어 Next.js 16이
 * ``<Suspense>`` 강제. 본 페이지는 Toss callback이라 정적 prerender 불가 — Suspense 래퍼.
 */
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function SubscribeFailPage() {
  return (
    <Suspense fallback={<SubscribeFailFallback />}>
      <SubscribeFailInner />
    </Suspense>
  );
}

function SubscribeFailFallback() {
  return (
    <main className="mx-auto max-w-xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">결제 실패</h1>
      </header>
      <div className="rounded-md border border-zinc-200 bg-zinc-50 p-6 text-sm text-zinc-700">
        결제 결과를 처리하는 중입니다…
      </div>
    </main>
  );
}

function SubscribeFailInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const code = searchParams.get("code");
  const message = searchParams.get("message");

  return (
    <main className="mx-auto max-w-xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">결제 실패</h1>
      </header>

      <div
        role="alert"
        className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
      >
        <p className="font-medium">
          {message ?? "결제 처리 중 오류가 발생했습니다."}
        </p>
        {code ? (
          <p className="mt-1 text-xs text-red-600">오류 코드: {code}</p>
        ) : null}
      </div>

      <div className="mt-6 space-y-2">
        <button
          type="button"
          onClick={() => router.push("/account/subscribe")}
          className="w-full rounded-md bg-blue-600 px-4 py-3 text-sm font-medium text-white hover:bg-blue-700"
        >
          다시 시도
        </button>
        <button
          type="button"
          onClick={() => router.push("/dashboard/weekly")}
          className="w-full rounded-md bg-zinc-100 px-4 py-3 text-sm font-medium text-zinc-700 hover:bg-zinc-200"
        >
          홈으로
        </button>
      </div>
    </main>
  );
}
