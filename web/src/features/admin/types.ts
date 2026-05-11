/**
 * Admin Web 컴포넌트 공유 타입 — Story 7.2 AC#8.
 *
 * `pnpm gen:api`로 자동 생성되는 OpenAPI 클라이언트 타입과 *별도 정의* — admin 라우터는
 * 본 스토리에서 신설(이전 baseline 미존재). 향후 Story 8.4 polish에서 OpenAPI 생성 타입
 * 으로 대체 가능(현재는 명시 interface 정합 + Server Component prop typing 단순성).
 */

export interface AdminUserDetailResponse {
  user_id: string;
  email_masked: string;
  display_name: string | null;
  picture_url: string | null;
  role: "user" | "admin";
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
  deleted_at: string | null;
  deletion_reason: string | null;
  onboarded_at: string | null;
  profile_completed_at: string | null;
  profile_updated_at: string | null;
  age: number | null;
  weight_kg_masked: string | null;
  height_cm_masked: string | null;
  activity_level: string | null;
  health_goal: string | null;
  allergies_count_masked: string | null;
  macro_goal: Record<string, number> | null;
  notifications_enabled: boolean;
  notification_time: string;
  notification_timezone: string;
}

export interface AdminMealAnalysisInline {
  fit_score: number;
  fit_score_label: "allergen_violation" | "low" | "moderate" | "good" | "excellent";
  feedback_summary: string;
  used_llm: "gpt-4o-mini" | "claude" | "stub";
}

export interface AdminMealItem {
  meal_id: string;
  raw_text_length: number;
  ate_at: string;
  created_at: string;
  deleted_at: string | null;
  image_url: string | null;
  parsed_items_count: number | null;
  analysis_summary: AdminMealAnalysisInline | null;
}

export interface AdminMealListResponse {
  meals: AdminMealItem[];
  next_cursor: string | null;
}

export interface AdminMealAnalysisItem {
  meal_analysis_id: string;
  meal_id: string;
  fit_score: number;
  fit_score_label: "allergen_violation" | "low" | "moderate" | "good" | "excellent";
  fit_reason: "ok" | "allergen_violation" | "incomplete_data";
  feedback_summary: string;
  used_llm: "gpt-4o-mini" | "claude" | "stub";
  created_at: string;
  updated_at: string;
}

export interface AdminMealAnalysisListResponse {
  analyses: AdminMealAnalysisItem[];
  next_cursor: string | null;
}
