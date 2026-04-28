/**
 * Story 1.5 — Web 건강 프로필 입력 폼 zod 스키마 + 도메인 const.
 *
 * SOT 동기 — 백엔드 ``api/app/domain/allergens.py:KOREAN_22_ALLERGENS`` 와 mobile
 * ``mobile/features/onboarding/healthProfileSchema.ts``가 동일. 22종 변경 시 세 위치
 * 모두 동시 갱신 + 새 alembic revision으로 ``ck_users_allergies_domain`` drop+recreate.
 */
import { z } from "zod";

export const KOREAN_22_ALLERGENS = [
  "우유",
  "메밀",
  "땅콩",
  "대두",
  "밀",
  "고등어",
  "게",
  "새우",
  "돼지고기",
  "아황산류",
  "복숭아",
  "토마토",
  "호두",
  "닭고기",
  "난류(가금류)",
  "쇠고기",
  "오징어",
  "조개류(굴/전복/홍합 포함)",
  "잣",
  "아몬드",
  "잔류 우유 단백",
  "기타",
] as const;
export type KoreanAllergen = (typeof KOREAN_22_ALLERGENS)[number];

export const HEALTH_GOAL_VALUES = [
  "weight_loss",
  "muscle_gain",
  "maintenance",
  "diabetes_management",
] as const;
export type HealthGoal = (typeof HEALTH_GOAL_VALUES)[number];

export const ACTIVITY_LEVEL_VALUES = [
  "sedentary",
  "light",
  "moderate",
  "active",
  "very_active",
] as const;
export type ActivityLevel = (typeof ACTIVITY_LEVEL_VALUES)[number];

export const HEALTH_GOAL_LABELS_KO: Record<HealthGoal, string> = {
  weight_loss: "체중 감량",
  muscle_gain: "근육 증가",
  maintenance: "유지",
  diabetes_management: "당뇨 관리",
};

export const ACTIVITY_LEVEL_LABELS_KO: Record<ActivityLevel, string> = {
  sedentary: "거의 안 함",
  light: "약한 운동",
  moderate: "보통 운동",
  active: "활발한 운동",
  very_active: "매우 활발",
};

export const healthProfileSchema = z.object({
  age: z
    .number({ invalid_type_error: "나이를 입력해주세요" })
    .int("나이는 정수여야 합니다")
    .min(1, "나이는 1세 이상이어야 합니다")
    .max(150, "나이는 150세 이하여야 합니다"),
  weight_kg: z
    .number({ invalid_type_error: "체중을 입력해주세요" })
    .min(1.0, "체중은 1.0 kg 이상이어야 합니다")
    .max(500.0, "체중은 500.0 kg 이하여야 합니다"),
  height_cm: z
    .number({ invalid_type_error: "신장을 입력해주세요" })
    .int("신장은 정수여야 합니다")
    .min(50, "신장은 50 cm 이상이어야 합니다")
    .max(300, "신장은 300 cm 이하여야 합니다"),
  activity_level: z.enum(ACTIVITY_LEVEL_VALUES, {
    errorMap: () => ({ message: "활동 수준을 선택해주세요" }),
  }),
  health_goal: z.enum(HEALTH_GOAL_VALUES, {
    errorMap: () => ({ message: "건강 목표를 선택해주세요" }),
  }),
  // ``defaultValues: { allergies: [] }``로 초기화 — react-hook-form resolver TFieldValues
  // mismatch 회피.
  allergies: z.array(z.enum(KOREAN_22_ALLERGENS)),
});

export type HealthProfileFormData = z.infer<typeof healthProfileSchema>;
