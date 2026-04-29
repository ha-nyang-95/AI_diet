/**
 * Story 2.1 — 식단 입력 폼 zod 스키마 + 응답 타입.
 *
 * 응답 타입(`MealResponse`/`MealListResponse`)은 본 스토리 baseline에서 수동 정의
 * — Task 6의 OpenAPI 재생성 후 `mobile/lib/api-client.ts`에서 자동 노출되면 그쪽
 * 타입으로 교체 가능. 본 파일의 타입은 wire format(`snake_case` JSON 그대로).
 */
import { z } from 'zod';

export const mealCreateSchema = z.object({
  raw_text: z
    .string()
    .trim()
    .min(1, '식단 내용을 입력해주세요')
    .max(2000, '식단 내용은 2000자 이하여야 합니다'),
});

export type MealCreateFormData = z.infer<typeof mealCreateSchema>;

export interface MealResponse {
  id: string;
  user_id: string;
  raw_text: string;
  ate_at: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface MealListResponse {
  meals: MealResponse[];
  next_cursor: string | null;
}

export interface MealCreateRequest {
  raw_text: string;
  ate_at?: string | null;
}

export interface MealUpdateRequest {
  raw_text?: string | null;
  ate_at?: string | null;
}

export interface MealsListQuery {
  from_date?: string;
  to_date?: string;
  limit?: number;
}
