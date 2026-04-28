/**
 * Open redirect 방어 — `next` 쿼리/쿠키 값이 same-origin 상대 경로인지 검증.
 *
 * 거부: `null`/`undefined`/빈문자열/`/`로 시작 안 함/`//`로 시작(scheme-relative)/`/\` 변형/
 *       `\` (Windows path) 등.
 * 허용: `/dashboard`, `/(user)/settings?foo=bar` 등 same-origin 상대 경로만.
 */
export function safeNext(value: string | null | undefined, fallback = "/dashboard"): string {
  if (!value) return fallback;
  if (!value.startsWith("/")) return fallback;
  // `//evil.com` (scheme-relative URL) 거부
  if (value.startsWith("//") || value.startsWith("/\\")) return fallback;
  // 길이 제한 — 1KB 이상은 비정상 입력으로 간주
  if (value.length > 1024) return fallback;
  return value;
}
