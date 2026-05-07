/**
 * Story 5.1 — 건강 프로필 폼 컴포넌트(onboarding + settings 양 화면 공유 SOT).
 *
 * Story 1.5 onboarding 폼 markup을 *추출*해 두 화면이 import — D2 결정 정합. 22종
 * 알레르기/styles는 한 지점만 갱신하면 양 화면 자동 동기.
 *
 * Props:
 * - ``initial: HealthProfileResponse | null`` — null이면 빈 폼(create), set이면 prefill(edit).
 * - ``mode: "create" | "edit"`` — submit handler/redirect target/labels 분기.
 *   create는 ``useSubmitHealthProfile``(POST), edit는 ``useUpdateHealthProfile``(PATCH).
 * - ``onSuccess?: (response) => void`` — onboarding의 ``markProfileCompleted`` 콜백 hook.
 *
 * Refactor scope 가드(Story 1.5 회귀 0건): onboarding 화면이 본 컴포넌트로 단순화돼도
 * (1) 폼 동작/검증 invariant (2) submit success → onSuccess → ``markProfileCompleted`` →
 * redirect chain (3) double-tap 방지 invariant 모두 보존.
 */
import { zodResolver } from '@hookform/resolvers/zod';
import { useRef } from 'react';
import { Controller, useForm } from 'react-hook-form';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import {
  ACTIVITY_LEVEL_COLORS,
  ACTIVITY_LEVEL_LABELS_KO,
  ACTIVITY_LEVEL_VALUES,
  HEALTH_GOAL_COLORS,
  HEALTH_GOAL_LABELS_KO,
  HEALTH_GOAL_VALUES,
  KOREAN_22_ALLERGENS,
  healthProfileSchema,
  type ActivityLevel,
  type HealthGoal,
  type HealthProfileFormData,
  type HealthProfileResponse,
  type KoreanAllergen,
} from '@/features/onboarding/healthProfileSchema';
import {
  ProfileSubmitError,
  useSubmitHealthProfile,
  useUpdateHealthProfile,
} from '@/features/onboarding/useHealthProfile';

export type HealthProfileEditFormMode = 'create' | 'edit';

interface HealthProfileEditFormProps {
  initial: HealthProfileResponse | null;
  mode: HealthProfileEditFormMode;
  onSuccess?: (response: HealthProfileResponse) => void;
  /** "create"일 때 버튼 라벨/A11y 분기. "edit"는 *프로필 저장*. 디폴트는 mode 기반 자동. */
  submitLabel?: string;
}

function extractSubmitErrorMessage(err: unknown): string {
  if (err instanceof ProfileSubmitError) {
    if (err.code === 'consent.basic.missing') {
      return '필수 동의가 누락되었습니다. 다시 동의 화면으로 이동합니다.';
    }
    if (err.code === 'validation.error') {
      return '입력 값을 확인해 주세요.';
    }
    if (err.status >= 500) {
      return '일시적인 서버 오류로 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.';
    }
    return err.detail ?? `프로필 저장 실패 (${err.status})`;
  }
  return '네트워크 오류로 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.';
}

function parseNumber(text: string): number | undefined {
  // 빈 입력 → undefined (zod required로 분기). paste 등으로 NaN 슬립 시도 차단.
  if (text === '') return undefined;
  const n = Number(text);
  return Number.isFinite(n) ? n : undefined;
}

function defaultValuesFor(initial: HealthProfileResponse | null): Partial<HealthProfileFormData> {
  // null이면 빈 폼(onboarding 진입). set이면 prefill(settings 진입). zod resolver는
  // ``allergies``가 array 형이어야 하므로 ``[]`` fallback 강제.
  if (initial === null) {
    return { allergies: [] };
  }
  return {
    age: initial.age ?? undefined,
    weight_kg: initial.weight_kg ?? undefined,
    height_cm: initial.height_cm ?? undefined,
    activity_level: initial.activity_level ?? undefined,
    health_goal: initial.health_goal ?? undefined,
    allergies: (initial.allergies ?? []) as KoreanAllergen[],
  };
}

export function HealthProfileEditForm({
  initial,
  mode,
  onSuccess,
  submitLabel,
}: HealthProfileEditFormProps) {
  const submit = useSubmitHealthProfile();
  const update = useUpdateHealthProfile();
  // double-tap 방지 — Story 1.3 P10 / Story 1.4 P5 패턴 정합.
  const inflightRef = useRef(false);

  const {
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<HealthProfileFormData>({
    resolver: zodResolver(healthProfileSchema),
    defaultValues: defaultValuesFor(initial),
  });

  const mutation = mode === 'create' ? submit : update;
  const buttonLabel = submitLabel ?? '프로필 저장';

  const onSubmit = handleSubmit((data) => {
    if (inflightRef.current) return;
    inflightRef.current = true;
    mutation.mutate(data, {
      onSuccess: (response) => {
        onSuccess?.(response);
      },
      onSettled: () => {
        inflightRef.current = false;
      },
    });
  });

  const isPending = mutation.isPending || isSubmitting;
  const submitError = mutation.isError ? extractSubmitErrorMessage(mutation.error) : null;

  return (
    <View>
      {/* 나이 */}
      <View style={styles.field}>
        <Text style={styles.label}>나이 (1~150)</Text>
        <Controller
          control={control}
          name="age"
          render={({ field: { onChange, onBlur, value } }) => (
            <TextInput
              style={styles.input}
              keyboardType="number-pad"
              onBlur={onBlur}
              onChangeText={(text) => onChange(parseNumber(text))}
              value={value !== undefined ? String(value) : ''}
              accessibilityLabel="나이 (정수, 1에서 150 사이)"
              accessibilityRole="text"
            />
          )}
        />
        {errors.age && <Text style={styles.errorText}>{errors.age.message}</Text>}
      </View>

      {/* 체중 */}
      <View style={styles.field}>
        <Text style={styles.label}>체중 (kg, 1.0~500.0)</Text>
        <Controller
          control={control}
          name="weight_kg"
          render={({ field: { onChange, onBlur, value } }) => (
            <TextInput
              style={styles.input}
              keyboardType="decimal-pad"
              onBlur={onBlur}
              onChangeText={(text) => onChange(parseNumber(text))}
              value={value !== undefined ? String(value) : ''}
              accessibilityLabel="체중 (소수, 1.0에서 500.0 kg 사이)"
              accessibilityRole="text"
            />
          )}
        />
        {errors.weight_kg && <Text style={styles.errorText}>{errors.weight_kg.message}</Text>}
      </View>

      {/* 신장 */}
      <View style={styles.field}>
        <Text style={styles.label}>신장 (cm, 50~300)</Text>
        <Controller
          control={control}
          name="height_cm"
          render={({ field: { onChange, onBlur, value } }) => (
            <TextInput
              style={styles.input}
              keyboardType="number-pad"
              onBlur={onBlur}
              onChangeText={(text) => onChange(parseNumber(text))}
              value={value !== undefined ? String(value) : ''}
              accessibilityLabel="신장 (정수, 50에서 300 cm 사이)"
              accessibilityRole="text"
            />
          )}
        />
        {errors.height_cm && <Text style={styles.errorText}>{errors.height_cm.message}</Text>}
      </View>

      {/* 활동 수준 */}
      <View style={styles.field}>
        <Text style={styles.label}>활동 수준</Text>
        <Controller
          control={control}
          name="activity_level"
          render={({ field: { onChange, value } }) => (
            <View style={styles.segmentColumn}>
              {ACTIVITY_LEVEL_VALUES.map((level: ActivityLevel) => {
                const selected = value === level;
                return (
                  <Pressable
                    key={level}
                    onPress={() => onChange(level)}
                    accessibilityRole="radio"
                    accessibilityState={{ selected }}
                    accessibilityLabel={`활동 수준 — ${ACTIVITY_LEVEL_LABELS_KO[level]}`}
                    style={[
                      styles.segmentItem,
                      selected && {
                        borderColor: ACTIVITY_LEVEL_COLORS[level],
                        backgroundColor: ACTIVITY_LEVEL_COLORS[level] + '20',
                      },
                    ]}
                  >
                    <View
                      style={[
                        styles.segmentSwatch,
                        { backgroundColor: ACTIVITY_LEVEL_COLORS[level] },
                      ]}
                    />
                    <Text style={styles.segmentText}>{ACTIVITY_LEVEL_LABELS_KO[level]}</Text>
                  </Pressable>
                );
              })}
            </View>
          )}
        />
        {errors.activity_level && (
          <Text style={styles.errorText}>{errors.activity_level.message}</Text>
        )}
      </View>

      {/* health_goal */}
      <View style={styles.field}>
        <Text style={styles.label}>건강 목표</Text>
        <Controller
          control={control}
          name="health_goal"
          render={({ field: { onChange, value } }) => (
            <View style={styles.segmentColumn}>
              {HEALTH_GOAL_VALUES.map((goal: HealthGoal) => {
                const selected = value === goal;
                return (
                  <Pressable
                    key={goal}
                    onPress={() => onChange(goal)}
                    accessibilityRole="radio"
                    accessibilityState={{ selected }}
                    accessibilityLabel={`건강 목표 — ${HEALTH_GOAL_LABELS_KO[goal]}`}
                    style={[
                      styles.segmentItem,
                      selected && {
                        borderColor: HEALTH_GOAL_COLORS[goal],
                        backgroundColor: HEALTH_GOAL_COLORS[goal] + '20',
                      },
                    ]}
                  >
                    <View
                      style={[
                        styles.segmentSwatch,
                        { backgroundColor: HEALTH_GOAL_COLORS[goal] },
                      ]}
                    />
                    <Text style={styles.segmentText}>{HEALTH_GOAL_LABELS_KO[goal]}</Text>
                  </Pressable>
                );
              })}
            </View>
          )}
        />
        {errors.health_goal && (
          <Text style={styles.errorText}>{errors.health_goal.message}</Text>
        )}
      </View>

      {/* 알레르기 */}
      <View style={styles.field}>
        <Text style={styles.label}>알레르기 (해당 없으면 비워두세요)</Text>
        <Controller
          control={control}
          name="allergies"
          render={({ field: { onChange, value } }) => (
            <View style={styles.allergyGrid}>
              {KOREAN_22_ALLERGENS.map((allergen: KoreanAllergen) => {
                const current = value ?? [];
                const checked = current.includes(allergen);
                return (
                  <Pressable
                    key={allergen}
                    onPress={() => {
                      const latest = value ?? [];
                      onChange(
                        latest.includes(allergen)
                          ? latest.filter((a) => a !== allergen)
                          : [...latest, allergen],
                      );
                    }}
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked }}
                    accessibilityLabel={`알레르기 — ${allergen}`}
                    style={[styles.allergyChip, checked && styles.allergyChipOn]}
                  >
                    <Text
                      style={[
                        styles.allergyChipText,
                        checked && styles.allergyChipTextOn,
                      ]}
                    >
                      {checked ? '✓ ' : ''}
                      {allergen}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          )}
        />
        {errors.allergies && (
          <Text style={styles.errorText}>{errors.allergies.message}</Text>
        )}
      </View>

      <Pressable
        style={[styles.submitButton, isPending && styles.submitButtonDisabled]}
        disabled={isPending}
        onPress={onSubmit}
        accessibilityRole="button"
        accessibilityLabel={buttonLabel}
      >
        {isPending ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.submitButtonText}>{buttonLabel}</Text>
        )}
      </Pressable>
      {submitError && <Text style={styles.errorText}>{submitError}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  field: { marginBottom: 16 },
  label: { fontSize: 14, fontWeight: '600', marginBottom: 6, color: '#222' },
  input: {
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 6,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
    color: '#222',
  },
  segmentColumn: {
    flexDirection: 'column',
    flexWrap: 'wrap',
  },
  segmentItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: '#ddd',
    borderRadius: 6,
    marginBottom: 6,
  },
  segmentSwatch: {
    width: 14,
    height: 14,
    borderRadius: 7,
    marginRight: 10,
  },
  segmentText: { fontSize: 15, color: '#222', flexShrink: 1 },
  allergyGrid: { flexDirection: 'row', flexWrap: 'wrap' },
  allergyChip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    margin: 4,
    borderWidth: 1,
    borderColor: '#bbb',
    borderRadius: 16,
    backgroundColor: '#fafafa',
  },
  allergyChipOn: {
    backgroundColor: '#1a73e8',
    borderColor: '#1a73e8',
  },
  allergyChipText: { fontSize: 13, color: '#222' },
  allergyChipTextOn: { color: '#fff', fontWeight: '600' },
  submitButton: {
    marginTop: 12,
    backgroundColor: '#1a73e8',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  submitButtonDisabled: { opacity: 0.4 },
  submitButtonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  errorText: { marginTop: 6, color: '#d33', fontSize: 13 },
});
