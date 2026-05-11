"use client";

/**
 * Admin 사용자 상세 통합 Client — Story 7.2 AC#8.
 *
 * 탭 layout(프로필 / 식단 / 피드백) — 단순 ``useState`` 기반 toggle (shadcn/ui Tabs는
 * Story 8.4 polish forward). 각 sub-component가 자체 ``useQuery`` fetch.
 */
import Link from "next/link";
import { useState } from "react";

import { AdminProfileEditForm } from "@/features/admin/AdminProfileEditForm";
import { UserMealAnalysesTable } from "@/features/admin/UserMealAnalysesTable";
import { UserMealsTable } from "@/features/admin/UserMealsTable";
import type { AdminUserDetailResponse } from "@/features/admin/types";

type Tab = "profile" | "meals" | "analyses";

interface Props {
  userId: string;
  initialDetail: AdminUserDetailResponse;
}

function MetadataRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-zinc-100 py-2 text-sm">
      <span className="text-zinc-500">{label}</span>
      <span className="text-zinc-800">{value}</span>
    </div>
  );
}

function formatDateOrDash(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ko-KR");
}

export function UserDetailClient({ userId, initialDetail }: Props) {
  const [tab, setTab] = useState<Tab>("profile");

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Link
            href="/admin/users"
            className="text-sm text-blue-600 hover:underline"
          >
            ← 사용자 검색
          </Link>
          <h2 className="mt-1 text-2xl font-semibold">{initialDetail.email_masked}</h2>
          <p className="text-sm text-zinc-500 font-mono">{initialDetail.user_id}</p>
        </div>
        <div className="flex flex-col items-end gap-1 text-sm text-zinc-600">
          <span>역할: {initialDetail.role}</span>
          {initialDetail.deleted_at && (
            <span className="rounded bg-red-100 px-2 py-1 text-xs text-red-700">
              탈퇴 진행중 ({formatDateOrDash(initialDetail.deleted_at)})
            </span>
          )}
        </div>
      </header>

      <section className="rounded-lg border border-zinc-200 p-4">
        <h3 className="mb-2 text-sm font-medium text-zinc-700">메타데이터</h3>
        <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
          <MetadataRow label="가입일" value={formatDateOrDash(initialDetail.created_at)} />
          <MetadataRow
            label="최근 로그인"
            value={formatDateOrDash(initialDetail.last_login_at)}
          />
          <MetadataRow
            label="온보딩 완료"
            value={formatDateOrDash(initialDetail.onboarded_at)}
          />
          <MetadataRow
            label="프로필 마지막 수정"
            value={formatDateOrDash(initialDetail.profile_updated_at)}
          />
          {initialDetail.deletion_reason && (
            <MetadataRow label="탈퇴 사유" value={initialDetail.deletion_reason} />
          )}
        </div>
      </section>

      <nav className="flex gap-2 border-b border-zinc-200" aria-label="사용자 상세 탭">
        {(
          [
            ["profile", "프로필"],
            ["meals", "식단 이력"],
            ["analyses", "피드백 로그"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              tab === id
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-zinc-500 hover:text-zinc-800"
            }`}
            aria-current={tab === id ? "page" : undefined}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === "profile" && (
        <AdminProfileEditForm userId={userId} initialDetail={initialDetail} />
      )}
      {tab === "meals" && <UserMealsTable userId={userId} />}
      {tab === "analyses" && <UserMealAnalysesTable userId={userId} />}
    </div>
  );
}
