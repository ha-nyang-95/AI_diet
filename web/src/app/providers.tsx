"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { createQueryClient } from "@/lib/query-client";

/**
 * 클라이언트 컴포넌트 wrapper — TanStack Query Provider 등 client-only context를 root layout에서 분리.
 *
 * `useState` lazy init: SSR 시 매 요청마다 새 클라이언트가 생성되어 사용자 간 캐시 누수 차단.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => createQueryClient());
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
