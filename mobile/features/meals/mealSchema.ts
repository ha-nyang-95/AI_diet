/**
 * Story 2.1 + 2.2 + 2.3 — 식단 입력 폼 zod 스키마 + 응답 타입.
 *
 * 응답 타입(`MealResponse`/`MealListResponse`)은 본 스토리 baseline에서 수동 정의
 * — OpenAPI 재생성 후 `mobile/lib/api-client.ts`에서 자동 노출되면 그쪽 타입으로
 * 교체 가능. 본 파일의 타입은 wire format(`snake_case` JSON 그대로).
 *
 * Story 2.2:
 * - `MealResponse`에 `image_key`/`image_url` 2 필드 추가 (모두 nullable).
 * - `MealCreateRequest`/`MealUpdateRequest`에 `image_key?: string | null` 추가.
 * - zod schema는 `raw_text`만 검증 — *raw_text or image_key 최소 1* 검증은
 *   부모 컴포넌트(`input.tsx`)에서 inline (zod superRefine 회피 — schema 단순 유지).
 *
 * Story 2.3:
 * - `ParsedMealItem` interface — `name`/`quantity`/`confidence` (Vision OCR 단일 항목).
 * - `MealResponse`에 `parsed_items: ParsedMealItem[] | null` 1 필드 추가.
 * - `MealCreateRequest`/`MealUpdateRequest`에 `parsed_items?: ParsedMealItem[] | null` 추가.
 * - `MealImageParseRequest`/`MealImageParseResponse` — `POST /v1/meals/images/parse` wire.
 */
import { z } from 'zod';

export const mealCreateSchema = z.object({
  // Story 2.2 — Optional. 부모(`input.tsx`)에서 *raw_text or image_key 최소 1* 검증.
  raw_text: z
    .string()
    .trim()
    .max(2000, '식단 내용은 2000자 이하여야 합니다')
    .optional()
    .or(z.literal('')),
});

export type MealCreateFormData = z.infer<typeof mealCreateSchema>;

// --- Story 2.3 — Vision OCR 추출 단일 항목 ---

/**
 * Vision OCR 추출 단일 항목 (백엔드 `app.adapters.openai_adapter.ParsedMealItem` 정합).
 *
 * - `name`: 한국어 표준 음식명 (예: "짜장면"). 빈 문자열 거부 (백엔드 Pydantic min_length=1).
 * - `quantity`: 추정 양 ("1인분"/"4개"/"300g"). 빈 quantity 허용 ("바나나" 같은 항목).
 * - `confidence`: 0.0~1.0 신뢰도. 0.6 미만은 OCRConfirmCard `lowConfidence` 트리거.
 */
export interface ParsedMealItem {
  name: string;
  quantity: string;
  confidence: number;
}

export interface MealResponse {
  id: string;
  user_id: string;
  raw_text: string;
  ate_at: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  // Story 2.2 — R2 object key + 표시용 public CDN URL (둘 다 nullable, 항상 키 존재).
  image_key: string | null;
  image_url: string | null;
  // Story 2.3 — Vision OCR 결과 (jsonb). null = parse 미호출 / 텍스트-only / 사용자가 클리어.
  parsed_items: ParsedMealItem[] | null;
}

export interface MealListResponse {
  meals: MealResponse[];
  next_cursor: string | null;
}

export interface MealCreateRequest {
  raw_text?: string | null;
  ate_at?: string | null;
  // Story 2.2 — `meals/{user_id}/{uuid}.{ext}` (백엔드 ownership 검증).
  image_key?: string | null;
  // Story 2.3 — Vision OCR 결과. *image_key 부속 데이터*(parsed_items 단독 + image_key 부재 거부).
  parsed_items?: ParsedMealItem[] | null;
}

export interface MealUpdateRequest {
  raw_text?: string | null;
  ate_at?: string | null;
  // Story 2.2 — *명시 `null` = 클리어*, *키 부재 = no-op*.
  image_key?: string | null;
  // Story 2.3 — *명시 `null` = 클리어*, *키 부재 = no-op* (image_key 시맨틱 정합).
  parsed_items?: ParsedMealItem[] | null;
}

export interface MealsListQuery {
  from_date?: string;
  to_date?: string;
  limit?: number;
}

// --- Story 2.2 R2 presigned URL ---

export interface MealImagePresignRequest {
  content_type: 'image/jpeg' | 'image/png' | 'image/webp' | 'image/heic' | 'image/heif';
  content_length: number;
}

export interface MealImagePresignResponse {
  upload_url: string;
  image_key: string;
  public_url: string;
  expires_at: string;
  content_type: string;
}

// --- Story 2.3 — Vision OCR parse endpoint ---

export interface MealImageParseRequest {
  image_key: string;
}

export interface MealImageParseResponse {
  image_key: string;
  parsed_items: ParsedMealItem[];
  /** items 비었거나 min(confidence) < 0.6 — 모바일 forced confirmation UI 트리거. */
  low_confidence: boolean;
  model: string;
  latency_ms: number;
}
