"use client";

/**
 * Admin 사용자 검색 Client Component — Story 7.2 AC#7.
 *
 * TanStack Query + 반응형(`sm:` breakpoint) 카드/테이블 분기 + 검색 폼.
 * 빈 결과 / 로딩 / 에러 inline 단순 표시(Story 8.4 polish forward).
 */
import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { adminApiFetch } from "@/lib/admin-api";

interface AdminUserListItem {
  user_id: string;
  email_masked: string;
  role: "user" | "admin";
  created_at: string;
  deleted_at: string | null;
  profile_completed_at: string | null;
  onboarded_at: string | null;
}

interface AdminUserSearchResponse {
  users: AdminUserListItem[];
  next_cursor: string | null;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function statusLabel(user: AdminUserListItem): string {
  if (user.deleted_at) return "탈퇴 진행중";
  if (user.profile_completed_at) return "활성";
  return "온보딩 미완료";
}

function UserCard({ user }: { user: AdminUserListItem }) {
  return (
    <li className="rounded-lg border border-zinc-200 p-4">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium">{user.email_masked}</span>
        <span className="text-xs text-zinc-500">{user.role}</span>
      </div>
      <p className="mt-1 font-mono text-xs text-zinc-400">{user.user_id.slice(0, 8)}…</p>
      <div className="mt-2 flex items-center justify-between text-xs text-zinc-600">
        <span>가입 {formatDate(user.created_at)}</span>
        <span>{statusLabel(user)}</span>
      </div>
      <Link
        href={`/admin/users/${user.user_id}`}
        className="mt-2 inline-block text-sm text-blue-600 hover:underline"
      >
        상세 보기 →
      </Link>
    </li>
  );
}

function UserRow({ user }: { user: AdminUserListItem }) {
  return (
    <tr className="border-b last:border-b-0">
      <td className="px-3 py-2">
        <Link
          href={`/admin/users/${user.user_id}`}
          className="text-blue-600 hover:underline"
        >
          {user.email_masked}
        </Link>
      </td>
      <td className="px-3 py-2 font-mono text-xs">{user.user_id.slice(0, 8)}…</td>
      <td className="px-3 py-2">{user.role}</td>
      <td className="px-3 py-2">{formatDate(user.created_at)}</td>
      <td className="px-3 py-2">{statusLabel(user)}</td>
    </tr>
  );
}

export function UserSearchClient() {
  const [searchTerm, setSearchTerm] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");

  const { data, isLoading, error } = useQuery<AdminUserSearchResponse>({
    queryKey: ["admin", "users", "search", submittedQuery],
    queryFn: async () => {
      const params = new URLSearchParams({ q: submittedQuery, limit: "50" });
      const response = await adminApiFetch(`/v1/admin/users?${params}`, { method: "GET" });
      if (!response.ok) {
        throw new Error(`search failed: ${response.status}`);
      }
      return (await response.json()) as AdminUserSearchResponse;
    },
    enabled: submittedQuery.length > 0,
    staleTime: 30_000,
  });

  return (
    <div className="space-y-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setSubmittedQuery(searchTerm.trim());
        }}
        className="flex flex-col gap-2 sm:flex-row sm:items-center"
        aria-label="사용자 검색 폼"
      >
        <input
          type="search"
          placeholder="이메일 또는 사용자 ID (UUID prefix)"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          maxLength={100}
          className="flex-1 rounded border border-zinc-300 px-3 py-2 text-sm"
          aria-label="검색어"
        />
        <button
          type="submit"
          disabled={searchTerm.trim().length === 0}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:bg-zinc-300"
        >
          검색
        </button>
      </form>

      {isLoading && <p className="text-sm text-zinc-500">검색 중…</p>}
      {error && (
        <p className="text-sm text-red-600">검색 실패. 다시 시도해 주세요.</p>
      )}
      {data && data.users.length === 0 && submittedQuery.length > 0 && (
        <p className="text-sm text-zinc-500">검색 결과 없음</p>
      )}
      {data && data.users.length > 0 && (
        <>
          <ul className="space-y-2 sm:hidden" aria-label="모바일 카드 리스트">
            {data.users.map((u) => (
              <UserCard key={u.user_id} user={u} />
            ))}
          </ul>
          <div className="hidden sm:block overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b text-left text-zinc-600">
                  <th className="px-3 py-2 font-medium">이메일</th>
                  <th className="px-3 py-2 font-medium">사용자 ID</th>
                  <th className="px-3 py-2 font-medium">역할</th>
                  <th className="px-3 py-2 font-medium">가입일</th>
                  <th className="px-3 py-2 font-medium">상태</th>
                </tr>
              </thead>
              <tbody>
                {data.users.map((u) => (
                  <UserRow key={u.user_id} user={u} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
