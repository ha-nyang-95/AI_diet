/**
 * 법적 문서(`/v1/legal/{type}?lang=ko`) fetch 훅 — TanStack Query (Story 1.3 AC5/AC7).
 *
 * Public endpoint — Authorization 헤더 동봉 X (`fetch` raw 호출, `authFetch` 사용 금지).
 * 24h staleTime 캐시 — 텍스트 변경 빈도가 낮음.
 */
import { useQuery } from '@tanstack/react-query';

const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

// Story 1.4 — Literal 확장(URL/SOT 키 hyphen 통일).
export type LegalDocType = 'disclaimer' | 'terms' | 'privacy' | 'automated-decision';
export type LegalLang = 'ko' | 'en';

export interface LegalDocumentResponse {
  type: LegalDocType;
  lang: LegalLang;
  version: string;
  title: string;
  body: string;
  updated_at: string;
}

const DAY_MS = 24 * 60 * 60 * 1000;

async function fetchLegalDocument(
  type: LegalDocType,
  lang: LegalLang,
): Promise<LegalDocumentResponse> {
  const response = await fetch(
    `${API_BASE_URL}/v1/legal/${type}?lang=${lang}`,
    { headers: { 'Content-Type': 'application/json' } },
  );
  if (!response.ok) {
    throw new Error(`legal document fetch failed (${response.status})`);
  }
  return (await response.json()) as LegalDocumentResponse;
}

export function useLegalDocument(type: LegalDocType, lang: LegalLang = 'ko') {
  return useQuery({
    queryKey: ['legal', type, lang],
    queryFn: () => fetchLegalDocument(type, lang),
    staleTime: DAY_MS,
    gcTime: DAY_MS,
  });
}
