"use client";

/**
 * Story 6.2 AC7 — 결제 이력 표 (Web).
 *
 * `GET /v1/payments/history?limit=20&cursor=...`로 cursor pagination 흐름. 1페이지는
 * mount 시 자동 fetch, *"더 보기"* 버튼이 ``next_cursor != null``일 때 노출되고 클릭 시
 * 추가 page를 ``setItems((prev) => [...prev, ...new])``로 누적 표시.
 *
 * 영수증 link는 ``receipt_url != null && status === 'success'`` 시 외부 도메인(``target=
 * "_blank"`` + ``rel="noopener noreferrer"``)으로 진입.
 *
 * 빈 이력은 안내 카드 + ``/account/subscribe`` link.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api-fetch";

type PaymentEventType = "subscribe" | "cancel" | "renew" | "failed" | "refund";
type PaymentStatus = "success" | "failed" | "pending";

interface PaymentHistoryItem {
  id: string;
  event_type: PaymentEventType;
  status: PaymentStatus;
  amount_krw: number;
  occurred_at: string;
  provider: "toss" | "stripe";
  receipt_url: string | null;
}

interface PaymentHistoryResponse {
  items: PaymentHistoryItem[];
  next_cursor: string | null;
}

const EVENT_TYPE_LABELS: Record<PaymentEventType, string> = {
  subscribe: "구독 신청",
  cancel: "구독 해지",
  renew: "자동 갱신",
  failed: "결제 실패",
  refund: "환불",
};

const STATUS_LABELS: Record<PaymentStatus, string> = {
  success: "완료",
  failed: "실패",
  pending: "진행중",
};

const STATUS_BADGE_CLASS: Record<PaymentStatus, string> = {
  success: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  pending: "bg-zinc-100 text-zinc-700",
};

function _formatKstDateTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat("ko-KR", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

async function fetchHistoryPage(cursor: string | null): Promise<PaymentHistoryResponse> {
  const url =
    cursor === null
      ? "/v1/payments/history?limit=20"
      : `/v1/payments/history?limit=20&cursor=${encodeURIComponent(cursor)}`;
  const response = await apiFetch(url);
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const problem = (await response.json()) as { detail?: string };
      detail = problem.detail;
    } catch {
      // RFC 7807 본문 아니면 status만.
    }
    throw new Error(detail ?? `결제 이력 조회 실패 (${response.status})`);
  }
  return (await response.json()) as PaymentHistoryResponse;
}

export function PaymentHistoryTable() {
  const [items, setItems] = useState<PaymentHistoryItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await fetchHistoryPage(null);
        if (cancelled) return;
        setItems(data.items);
        setNextCursor(data.next_cursor);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "결제 이력 조회 실패");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLoadMore = async () => {
    if (nextCursor === null) return;
    setLoadingMore(true);
    setError(null);
    try {
      const data = await fetchHistoryPage(nextCursor);
      setItems((prev) => [...prev, ...data.items]);
      setNextCursor(data.next_cursor);
    } catch (err) {
      setError(err instanceof Error ? err.message : "결제 이력 조회 실패");
    } finally {
      setLoadingMore(false);
    }
  };

  if (loading) {
    return (
      <div className="rounded-md border border-zinc-200 bg-zinc-50 p-6 text-sm text-zinc-700">
        결제 이력을 불러오는 중입니다…
      </div>
    );
  }

  if (error !== null && items.length === 0) {
    return (
      <div
        role="alert"
        className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
      >
        {error}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="rounded-md border border-zinc-200 bg-zinc-50 p-6 text-sm text-zinc-700">
        <p>결제 이력이 없습니다.</p>
        <Link
          href="/account/subscribe"
          className="mt-3 inline-block text-blue-700 underline hover:text-blue-900"
        >
          구독 신청
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-md border border-zinc-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500">
            <tr>
              <th className="px-4 py-3">유형</th>
              <th className="px-4 py-3">시점</th>
              <th className="px-4 py-3 text-right">금액</th>
              <th className="px-4 py-3">영수증</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {items.map((item) => (
              <tr key={item.id}>
                <td className="px-4 py-3 align-top">
                  <div className="font-medium text-zinc-900">
                    {EVENT_TYPE_LABELS[item.event_type] ?? item.event_type}
                  </div>
                  <span
                    className={`mt-1 inline-block rounded-full px-2 py-0.5 text-xs ${
                      STATUS_BADGE_CLASS[item.status] ?? "bg-zinc-100 text-zinc-700"
                    }`}
                  >
                    {STATUS_LABELS[item.status] ?? item.status}
                  </span>
                </td>
                <td className="px-4 py-3 align-top text-zinc-700">
                  {_formatKstDateTime(item.occurred_at)}
                </td>
                <td className="px-4 py-3 align-top text-right font-medium text-zinc-900">
                  {item.amount_krw.toLocaleString("ko-KR")}원
                </td>
                <td className="px-4 py-3 align-top">
                  {item.receipt_url !== null && item.status === "success" ? (
                    <a
                      href={item.receipt_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-700 underline hover:text-blue-900"
                    >
                      영수증
                    </a>
                  ) : (
                    <span className="text-zinc-400">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {error !== null ? (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      ) : null}

      {nextCursor !== null ? (
        <button
          type="button"
          onClick={() => {
            void handleLoadMore();
          }}
          disabled={loadingMore}
          className="rounded-md border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-800 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loadingMore ? "불러오는 중…" : "더 보기"}
        </button>
      ) : null}
    </div>
  );
}
