import { redirect } from "next/navigation";

import { getServerSideUser } from "@/lib/auth";

export default async function Home() {
  // 인증 상태 따라 이분기 — middleware가 매칭하지 않는 / 진입점.
  const user = await getServerSideUser();
  redirect(user ? "/dashboard" : "/login");
}
