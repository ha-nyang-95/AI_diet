/**
 * `GET /v1/legal/{type}?lang=ko|en` — 법적 문서 풀텍스트 server-only fetch (Story 1.3 AC7).
 *
 * Public endpoint: ``headers: {}`` 명시로 cookie 동봉 안 함 — 백엔드 회귀 차단 정합.
 * 24h ISR 캐시(`next: { revalidate: 86400 }`).
 *
 * `import "server-only"` — 클라이언트가 import 시 빌드 에러로 차단(Story 1.2 W1 정합).
 * `"use server"` 디렉티브는 사용 금지 — Server Action 변환은 본 모듈 의도 아님.
 */
import "server-only";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export type LegalDocType = "disclaimer" | "terms" | "privacy";
export type LegalLang = "ko" | "en";

export interface LegalDocumentResponse {
  type: LegalDocType;
  lang: LegalLang;
  version: string;
  title: string;
  body: string;
  updated_at: string;
}

export async function fetchLegalDocument(
  type: LegalDocType,
  lang: LegalLang = "ko",
): Promise<LegalDocumentResponse | null> {
  const response = await fetch(`${API_BASE_URL}/v1/legal/${type}?lang=${lang}`, {
    headers: {},
    next: { revalidate: 86400 },
  });
  if (!response.ok) return null;
  return (await response.json()) as LegalDocumentResponse;
}
