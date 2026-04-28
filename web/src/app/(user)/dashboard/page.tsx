import { redirect } from "next/navigation";

import { getServerSideUser } from "@/lib/auth";

import { LogoutButton } from "./logout-button";

export const metadata = {
  title: "대시보드 — BalanceNote",
};

export default async function DashboardPage() {
  const user = await getServerSideUser();
  if (!user) {
    redirect("/login");
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <h1 className="text-2xl font-semibold tracking-tight">
        안녕하세요, {user.display_name ?? user.email}
      </h1>
      <p className="mt-2 text-sm text-zinc-500">
        (Story 4.3에서 채워짐 — 주간 리포트 차트)
      </p>
      <LogoutButton />
    </main>
  );
}
