"use client";

/**
 * `/account/subscribe/success` — Toss 결제 완료 후 server confirm 페이지 (Story 6.1 AC8).
 *
 * Toss success callback URL — 클라이언트가 ``paymentKey`` / ``orderId`` / ``amount``를
 * URL query로 받음. 이 컴포넌트가 ``apiFetch("/v1/payments/subscribe", POST)``로 server
 * confirm 트리거.
 *
 * idempotencyKey 보존: ``SUBSCRIBE_IDEMPOTENCY_STORAGE_KEY`` localStorage에 보관된 키
 * (``SubscribeForm`` mount 시점 생성)를 read 후 ``Idempotency-Key`` 헤더로 전달. 사용 후
 * delete (재진입 시 새 키 — 새 결제 시도). localStorage 미보유 시(직접 URL 접근 등)
 * 헤더 없이 호출 — 첫 신청 흐름.
 */
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { apiFetch } from "@/lib/api-fetch";
import { SUBSCRIBE_IDEMPOTENCY_STORAGE_KEY } from "@/features/payments/SubscribeForm";

interface SubscribeResponse {
  subscription: {
    id: string;
    status: "active" | "cancelled" | "expired";
    plan: "monthly";
    plan_price_krw: number;
    started_at: string;
    expires_at: string | null;
    provider: "toss" | "stripe";
  };
  payment: {
    id: string;
    status: "success" | "failed" | "pending";
    amount_krw: number;
    occurred_at: string;
  };
}

interface ProblemDetail {
  code?: string;
  detail?: string;
}

type State =
  | { phase: "loading" }
  | { phase: "success"; data: SubscribeResponse }
  | { phase: "error"; message: string };

export default function SubscribeSuccessPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    const paymentKey = searchParams.get("paymentKey");
    const orderId = searchParams.get("orderId");
    const amountRaw = searchParams.get("amount");

    void (async () => {
      if (!paymentKey || !orderId || !amountRaw) {
        setState({
          phase: "error",
          message: "결제 정보가 누락되었습니다. 다시 시도해 주세요.",
        });
        return;
      }

      const amount = Number(amountRaw);
      if (Number.isNaN(amount)) {
        setState({
          phase: "error",
          message: "결제 금액 정보가 잘못되었습니다.",
        });
        return;
      }

      let idempotencyKey: string | null = null;
      try {
        idempotencyKey = localStorage.getItem(SUBSCRIBE_IDEMPOTENCY_STORAGE_KEY);
      } catch {
        // localStorage 비활성 — 헤더 없이 호출.
      }

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (idempotencyKey) {
        headers["Idempotency-Key"] = idempotencyKey;
      }

      try {
        const response = await apiFetch("/v1/payments/subscribe", {
          method: "POST",
          headers,
          body: JSON.stringify({ paymentKey, orderId, amount }),
        });

        if (response.ok) {
          const body = (await response.json()) as SubscribeResponse;
          // 사용 후 delete — 다음 결제 시도는 새 키.
          try {
            localStorage.removeItem(SUBSCRIBE_IDEMPOTENCY_STORAGE_KEY);
          } catch {
            // ignore
          }
          setState({ phase: "success", data: body });
          return;
        }

        let problem: ProblemDetail = {};
        try {
          problem = (await response.json()) as ProblemDetail;
        } catch {
          // RFC 7807 본문 아니면 status만 사용.
        }
        setState({
          phase: "error",
          message:
            problem.detail ?? `결제 확인에 실패했습니다 (${response.status})`,
        });
      } catch {
        setState({
          phase: "error",
          message: "네트워크 오류로 결제 확인에 실패했습니다.",
        });
      }
    })();
  }, [searchParams]);

  return (
    <main className="mx-auto max-w-xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">결제 결과</h1>
      </header>

      {state.phase === "loading" ? (
        <div className="rounded-md border border-zinc-200 bg-zinc-50 p-6 text-sm text-zinc-700">
          결제 결과를 처리하는 중입니다…
        </div>
      ) : null}

      {state.phase === "success" ? (
        <div className="space-y-4">
          <div className="rounded-md border border-green-200 bg-green-50 p-4 text-sm text-green-800">
            <p className="font-medium">구독이 시작되었습니다.</p>
            <p className="mt-1">
              월 {state.data.subscription.plan_price_krw.toLocaleString("ko-KR")}원 정기결제가
              활성화되었습니다.
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt className="text-zinc-600">시작일</dt>
            <dd className="text-zinc-900">
              {new Date(state.data.subscription.started_at).toLocaleDateString("ko-KR")}
            </dd>
            <dt className="text-zinc-600">다음 결제일</dt>
            <dd className="text-zinc-900">
              {state.data.subscription.expires_at !== null
                ? new Date(state.data.subscription.expires_at).toLocaleDateString("ko-KR")
                : "-"}
            </dd>
          </dl>
          <button
            type="button"
            onClick={() => router.push("/dashboard/weekly")}
            className="w-full rounded-md bg-blue-600 px-4 py-3 text-sm font-medium text-white hover:bg-blue-700"
          >
            홈으로
          </button>
        </div>
      ) : null}

      {state.phase === "error" ? (
        <div className="space-y-4">
          <div
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
          >
            <p className="font-medium">결제 확인 실패</p>
            <p className="mt-1">{state.message}</p>
          </div>
          <button
            type="button"
            onClick={() => router.push("/account/subscribe")}
            className="w-full rounded-md bg-blue-600 px-4 py-3 text-sm font-medium text-white hover:bg-blue-700"
          >
            다시 시도
          </button>
        </div>
      ) : null}
    </main>
  );
}
