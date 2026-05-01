import { redirect } from "next/navigation";

import { getServerSideUser } from "@/lib/auth";

export default async function Home() {
  // 인증 상태 따라 이분기 — middleware가 매칭하지 않는 / 진입점.
  const user = await getServerSideUser();
  // user=null은 (a) 쿠키 부재 (b) backend 401(stale 쿠키) 둘 다 가능. cleanup route가
  // 두 케이스 모두 idempotent하게 처리(쿠키 폐기 + /login redirect) — middleware ping-pong 회피.
  redirect(user ? "/dashboard" : "/api/auth/cleanup");
}
