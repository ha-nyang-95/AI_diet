"use client";

/**
 * Admin self-audit 테이블 Client Component — Story 7.4 AC#4 (FR38).
 *
 * TanStack Query — initialData = SSR 첫 페이지 → "더 보기" cursor pagination.
 * 반응형: 모바일(`sm:hidden`) 카드 / 데스크톱(`hidden sm:block`) 테이블. action enum
 * 한국어 label 매핑(`ACTION_LABEL`). target_user_id 있으면 사용자 상세 페이지 링크.
 */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { adminApiFetch } from "@/lib/admin-api";
import type {
  AdminAuditLogAction,
  AdminAuditLogItem,
  AdminAuditLogListResponse,
} from "./types";

const ACTION_LABEL: Record<AdminAuditLogAction, string> = {
  user_search: "사용자 검색",
  user_profile_view: "프로필 조회",
  user_meal_history_view: "식단 이력 조회",
  user_feedback_history_view: "피드백 로그 조회",
  user_profile_edit: "프로필 수정",
  admin_meal_delete: "식단 삭제",
  user_pii_view: "PII 원문 보기",
};

function actionLabel(action: AdminAuditLogAction): string {
  return ACTION_LABEL[action] ?? action;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function targetCell(item: AdminAuditLogItem) {
  if (item.target_user_id) {
    return (
      <Link
        href={`/admin/users/${item.target_user_id}`}
        className="text-blue-600 hover:underline"
      >
        {item.target_user_id.slice(0, 8)}…
      </Link>
    );
  }
  if (item.target_resource_id) {
    return <span className="font-mono text-xs">{item.target_resource_id.slice(0, 8)}…</span>;
  }
  return <span className="text-zinc-400">—</span>;
}

function AuditCard({ item }: { item: AdminAuditLogItem }) {
  return (
    <li className="rounded-lg border border-zinc-200 p-4">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium">{actionLabel(item.action)}</span>
        <span className="text-xs text-zinc-500">{formatDateTime(item.occurred_at)}</span>
      </div>
      <p className="mt-1 text-xs text-zinc-600">
        <span className="font-medium">{item.method}</span> {item.path}
      </p>
      <div className="mt-2 flex items-center justify-between text-xs text-zinc-600">
        <span>대상: {targetCell(item)}</span>
        <span className="font-mono">{item.request_id.slice(0, 8)}</span>
      </div>
    </li>
  );
}

function AuditRow({ item }: { item: AdminAuditLogItem }) {
  return (
    <tr className="border-b last:border-b-0">
      <td className="px-3 py-2 whitespace-nowrap">{formatDateTime(item.occurred_at)}</td>
      <td className="px-3 py-2">{actionLabel(item.action)}</td>
      <td className="px-3 py-2">{targetCell(item)}</td>
      <td className="px-3 py-2 font-mono text-xs">
        <span className="font-medium">{item.method}</span> {item.path}
      </td>
      <td className="px-3 py-2 text-xs">{item.ip ?? "—"}</td>
      <td className="px-3 py-2 font-mono text-xs">{item.request_id.slice(0, 8)}</td>
    </tr>
  );
}

export function AuditLogTable({ initial }: { initial: AdminAuditLogListResponse }) {
  const [items, setItems] = useState<AdminAuditLogItem[]>(initial.items);
  const [cursor, setCursor] = useState<string | null>(initial.next_cursor);
  const [activeCursor, setActiveCursor] = useState<string | null>(null);
  // cursor-한정 dedup 가드 — TanStack Query refetch(StrictMode double-mount /
  // 재시도) 시 동일 cursor를 ``items``에 두 번 append하지 않도록 보존.
  const appliedCursorsRef = useRef<Set<string>>(new Set());

  const { isFetching, error, data, refetch } = useQuery<AdminAuditLogListResponse>({
    queryKey: ["admin", "audit-logs", activeCursor],
    queryFn: async () => {
      if (!activeCursor) {
        return { items: [], next_cursor: null };
      }
      const params = new URLSearchParams({
        actor_id: "me",
        limit: "50",
        cursor: activeCursor,
      });
      const response = await adminApiFetch(`/v1/admin/audit-logs?${params}`, {
        method: "GET",
      });
      if (!response.ok) {
        throw new Error(`fetch audit-logs failed: ${response.status}`);
      }
      return (await response.json()) as AdminAuditLogListResponse;
    },
    enabled: activeCursor !== null,
    // queryFn 순수화 — 부작용(append/cursor 갱신)은 ``useEffect``로 이동. 재실행
    // 위험을 함께 차단: refocus/reconnect re-fetch 비활성 + staleTime Infinity로
    // queryKey 안정성 유지(``items``에 *append* 패턴이라 SWR식 갱신이 의미 없음).
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: false,
    staleTime: Number.POSITIVE_INFINITY,
  });

  useEffect(() => {
    if (!data || !activeCursor) return;
    if (appliedCursorsRef.current.has(activeCursor)) return;
    appliedCursorsRef.current.add(activeCursor);
    setItems((prev) => [...prev, ...data.items]);
    setCursor(data.next_cursor);
  }, [data, activeCursor]);

  return (
    <div className="space-y-4">
      {items.length === 0 && !isFetching && (
        <p className="text-sm text-zinc-500">기록된 활동이 없습니다.</p>
      )}

      {items.length > 0 && (
        <>
          <ul className="space-y-2 sm:hidden" aria-label="감사 로그 모바일 카드 리스트">
            {items.map((item) => (
              <AuditCard key={item.audit_id} item={item} />
            ))}
          </ul>
          <div className="hidden sm:block overflow-x-auto">
            <table className="w-full border-collapse text-sm" aria-label="감사 로그 표">
              <thead>
                <tr className="border-b text-left text-zinc-600">
                  <th className="px-3 py-2 font-medium">시점</th>
                  <th className="px-3 py-2 font-medium">액션</th>
                  <th className="px-3 py-2 font-medium">대상</th>
                  <th className="px-3 py-2 font-medium">경로</th>
                  <th className="px-3 py-2 font-medium">IP</th>
                  <th className="px-3 py-2 font-medium">요청 ID</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <AuditRow key={item.audit_id} item={item} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {isFetching && <p className="text-sm text-zinc-500">불러오는 중…</p>}
      {error && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-red-600">감사 로그 불러오기 실패.</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded border border-red-300 px-3 py-1 text-sm text-red-700 hover:bg-red-50"
          >
            다시 시도
          </button>
        </div>
      )}

      {cursor && !isFetching && (
        <button
          type="button"
          onClick={() => setActiveCursor(cursor)}
          className="rounded border border-zinc-300 px-4 py-2 text-sm hover:bg-zinc-50"
        >
          더 보기
        </button>
      )}
    </div>
  );
}
