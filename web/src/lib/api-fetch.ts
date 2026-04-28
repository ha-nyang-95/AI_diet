/**
 * 클라이언트 컴포넌트용 fetch 래퍼 (Story 1.2 AC#4).
 *
 * - `credentials: "include"` 강제 — httpOnly 쿠키 자동 첨부.
 * - 401 → `POST /v1/auth/refresh` 1회 → 재시도. 실패 시 `/login`으로 라우팅.
 * - 무한 루프 차단: refresh 자체 호출 / 재시도 호출은 인터셉터 우회 옵션.
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const REFRESH_PATH = "/v1/auth/refresh";

let refreshInFlight: Promise<boolean> | null = null;

async function performRefresh(): Promise<boolean> {
  const response = await fetch(`${API_BASE_URL}${REFRESH_PATH}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return response.ok;
}

export async function apiFetch(
  input: string,
  init: RequestInit & { _isRetry?: boolean; _skipRefresh?: boolean } = {},
): Promise<Response> {
  const url = input.startsWith("http") ? input : `${API_BASE_URL}${input}`;
  const response = await fetch(url, {
    ...init,
    credentials: "include",
  });

  if (response.status !== 401 || init._isRetry || init._skipRefresh) {
    return response;
  }

  refreshInFlight ??= performRefresh().finally(() => {
    refreshInFlight = null;
  });
  const ok = await refreshInFlight;
  if (!ok) {
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    return response;
  }

  return apiFetch(input, { ...init, _isRetry: true });
}
