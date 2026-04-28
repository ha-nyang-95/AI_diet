import { QueryClient } from "@tanstack/react-query";

/**
 * 클라이언트 컴포넌트에서 1회 인스턴스화해 사용.
 * SSR 시 매 요청마다 새 클라이언트가 생성되도록 layout/provider에서 lazy 초기화.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60 * 1000,
        retry: 1,
      },
    },
  });
}
