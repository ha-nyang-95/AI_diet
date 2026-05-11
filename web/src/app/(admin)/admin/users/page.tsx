/**
 * Admin 사용자 검색 페이지 — Story 7.2 AC#7 (FR36).
 *
 * 반응형: 모바일 360px (검색 폼 + 카드 리스트) → 데스크톱 1440px+ (검색 폼 + 테이블).
 * 검색 결과는 마스킹된 이메일 + UUID prefix + 가입일 + soft-deleted 표시.
 * Server Component shell + Client Component(`UserSearchClient`) 패턴.
 */
import type { Metadata } from "next";

import { UserSearchClient } from "@/features/admin/UserSearchClient";

export const metadata: Metadata = {
  title: "사용자 검색 — 관리자",
};

export default function AdminUsersPage() {
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold">사용자 검색</h2>
        <p className="mt-1 text-sm text-zinc-600">
          이메일 또는 사용자 ID 일부를 입력하세요. 결과는 마스킹된 형태로 표시됩니다.
        </p>
      </header>
      <UserSearchClient />
    </div>
  );
}
