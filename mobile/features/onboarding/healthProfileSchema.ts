/**
 * Story 1.5 — 건강 프로필 입력 폼 zod 스키마 + 도메인 const.
 *
 * SOT 동기 — 백엔드 ``api/app/domain/allergens.py:KOREAN_22_ALLERGENS`` 와 동일.
 * 22종 변경 시 (a) 백엔드 SOT 갱신 → (b) 본 const 갱신 → (c) Web
 * ``web/src/features/onboarding/healthProfileSchema.ts`` 갱신 → (d) 새 alembic
 * revision으로 ``users.allergies`` CHECK 제약 drop+recreate.
 *
 * 정의 순서는 식약처 표시기준 별표 PDF 순(우유 → 메밀 → … → 기타) — 본 순서 보존.
 */
import { z } from 'zod';

export const KOREAN_22_ALLERGENS = [
  '우유',
  '메밀',
  '땅콩',
  '대두',
  '밀',
  '고등어',
  '게',
  '새우',
  '돼지고기',
  '아황산류',
  '복숭아',
  '토마토',
  '호두',
  '닭고기',
  '난류(가금류)',
  '쇠고기',
  '오징어',
  '조개류(굴/전복/홍합 포함)',
  '잣',
  '아몬드',
  '잔류 우유 단백',
  '기타',
] as const;
export type KoreanAllergen = (typeof KOREAN_22_ALLERGENS)[number];

export const HEALTH_GOAL_VALUES = [
  'weight_loss',
  'muscle_gain',
  'maintenance',
  'diabetes_management',
] as const;
export type HealthGoal = (typeof HEALTH_GOAL_VALUES)[number];

export const ACTIVITY_LEVEL_VALUES = [
  'sedentary',
  'light',
  'moderate',
  'active',
  'very_active',
] as const;
export type ActivityLevel = (typeof ACTIVITY_LEVEL_VALUES)[number];

// 한국어 라벨 매핑 — UI 노출용. 백엔드는 enum 값(영문) 그대로 저장·반환.
// 향후 영문 UI 전환 시 본 dict만 i18n 사전으로 교체(Story 8 i18n).
export const HEALTH_GOAL_LABELS_KO: Record<HealthGoal, string> = {
  weight_loss: '체중 감량',
  muscle_gain: '근육 증가',
  maintenance: '유지',
  diabetes_management: '당뇨 관리',
};

export const ACTIVITY_LEVEL_LABELS_KO: Record<ActivityLevel, string> = {
  sedentary: '거의 안 함',
  light: '약한 운동',
  moderate: '보통 운동',
  active: '활발한 운동',
  very_active: '매우 활발',
};

// NFR-A4 색약 대응 — 색상 + 텍스트 라벨 동시 노출. 색상 토큰은 Sedentary(약함) →
// Very Active(강함) 순으로 그라데이션. 컴포넌트는 본 매핑 + 텍스트 라벨 둘 다 표시.
export const ACTIVITY_LEVEL_COLORS: Record<ActivityLevel, string> = {
  sedentary: '#9aa0a6',
  light: '#7cb305',
  moderate: '#52c41a',
  active: '#389e0d',
  very_active: '#1e7e34',
};

export const HEALTH_GOAL_COLORS: Record<HealthGoal, string> = {
  weight_loss: '#1a73e8',
  muscle_gain: '#fa8c16',
  maintenance: '#52c41a',
  diabetes_management: '#722ed1',
};

export const healthProfileSchema = z.object({
  age: z
    .number({ invalid_type_error: '나이를 입력해주세요' })
    .int('나이는 정수여야 합니다')
    .min(1, '나이는 1세 이상이어야 합니다')
    .max(150, '나이는 150세 이하여야 합니다'),
  weight_kg: z
    .number({ invalid_type_error: '체중을 입력해주세요' })
    .min(1.0, '체중은 1.0 kg 이상이어야 합니다')
    .max(500.0, '체중은 500.0 kg 이하여야 합니다')
    // 백엔드 ``Numeric(5,1)``의 silent rounding(70.55 → 70.6) 차단 — 1 자리만 허용.
    .multipleOf(0.1, '체중은 소수 첫째 자리까지 입력해 주세요'),
  height_cm: z
    .number({ invalid_type_error: '신장을 입력해주세요' })
    .int('신장은 정수여야 합니다')
    .min(50, '신장은 50 cm 이상이어야 합니다')
    .max(300, '신장은 300 cm 이하여야 합니다'),
  activity_level: z.enum(ACTIVITY_LEVEL_VALUES, {
    errorMap: () => ({ message: '활동 수준을 선택해주세요' }),
  }),
  health_goal: z.enum(HEALTH_GOAL_VALUES, {
    errorMap: () => ({ message: '건강 목표를 선택해주세요' }),
  }),
  // ``defaultValues: { allergies: [] }``로 초기화 — 폼 검증 시 빈 배열도 valid.
  // ``.default([])`` 미사용 사유: zod input 타입이 optional이 되어 react-hook-form
  // resolver의 TFieldValues와 mismatch 발생.
  // ``.max(22)`` — 도메인 상한 + DoS 차단 (백엔드 Field max_length=22와 일치).
  allergies: z.array(z.enum(KOREAN_22_ALLERGENS)).max(22, '알레르기는 최대 22종까지 선택할 수 있습니다'),
});

export type HealthProfileFormData = z.infer<typeof healthProfileSchema>;

export interface HealthProfileResponse {
  age: number | null;
  weight_kg: number | null;
  height_cm: number | null;
  activity_level: ActivityLevel | null;
  health_goal: HealthGoal | null;
  allergies: string[];
  profile_completed_at: string | null;
}
