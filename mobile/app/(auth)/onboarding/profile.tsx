/**
 * Onboarding 5/5 — 건강 프로필 입력 (Story 1.5 AC1, AC7, AC8).
 *
 * 6 입력 필드: 나이 / 체중 / 신장 / 활동 수준(5종) / health_goal(4종) / 22종 알레르기.
 * react-hook-form + zod (``healthProfileSchema``) 검증. 성공 시 ``/(tabs)``로 redirect
 * — Story 1.6이 본 redirect를 가로채 ``automated-decision → tutorial → profile →
 * /(tabs)`` chain 마지막으로 끼워둠(``users.onboarded_at = now()``).
 *
 * 진입 가드(direct entry 안전망): basic 또는 AD 미통과 → 즉시 redirect.
 * 실제 사용자 흐름은 ``automated-decision`` 화면 submit success 후 본 화면으로 이동.
 */
import { zodResolver } from '@hookform/resolvers/zod';
import { Redirect } from 'expo-router';
import { useRef } from 'react';
import { Controller, useForm } from 'react-hook-form';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { useAuth } from '@/lib/auth';

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
  type KoreanAllergen,
} from '@/features/onboarding/healthProfileSchema';
import {
  ProfileSubmitError,
  useSubmitHealthProfile,
} from '@/features/onboarding/useHealthProfile';

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

export default function OnboardingProfile() {
  const { consentStatus } = useAuth();
  const submit = useSubmitHealthProfile();
  // double-tap 방지 — Story 1.3 P10 / Story 1.4 P5 패턴 정합.
  const inflightRef = useRef(false);

  const {
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<HealthProfileFormData>({
    resolver: zodResolver(healthProfileSchema),
    defaultValues: { allergies: [] },
  });

  // 진입 가드 — direct entry 안전망. 정상 흐름은 (tabs) 가드 또는 automated-decision
  // 성공 redirect로 도달.
  if (consentStatus && !consentStatus.basic_consents_complete) {
    return <Redirect href="/(auth)/onboarding/disclaimer" />;
  }
  if (consentStatus && !consentStatus.automated_decision_consent_complete) {
    return <Redirect href="/(auth)/onboarding/automated-decision" />;
  }

  if (submit.isSuccess) {
    // Story 1.6이 본 redirect 대상을 ``tutorial``로 가로채 chain 구성.
    return <Redirect href="/(tabs)" />;
  }

  const onSubmit = handleSubmit((data) => {
    if (inflightRef.current) return;
    inflightRef.current = true;
    submit.mutate(data, {
      onSettled: () => {
        inflightRef.current = false;
      },
    });
  });

  const isPending = submit.isPending || isSubmitting;
  const submitError = submit.isError
    ? extractSubmitErrorMessage(submit.error)
    : null;

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.title}>건강 프로필 입력</Text>
      <Text style={styles.caption}>
        나이·체중·신장·활동 수준·건강 목표·알레르기를 입력하면 분석 정확도가 높아집니다.
      </Text>

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
              onChangeText={(text) => onChange(text === '' ? undefined : Number(text))}
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
              onChangeText={(text) => onChange(text === '' ? undefined : Number(text))}
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
              onChangeText={(text) => onChange(text === '' ? undefined : Number(text))}
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
          render={({ field: { onChange, value } }) => {
            const current = value ?? [];
            return (
              <View style={styles.allergyGrid}>
                {KOREAN_22_ALLERGENS.map((allergen: KoreanAllergen) => {
                  const checked = current.includes(allergen);
                  const next = checked
                    ? current.filter((a) => a !== allergen)
                    : [...current, allergen];
                  return (
                    <Pressable
                      key={allergen}
                      onPress={() => onChange(next)}
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
            );
          }}
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
        accessibilityLabel="프로필 저장"
      >
        {isPending ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.submitButtonText}>프로필 저장</Text>
        )}
      </Pressable>
      {submitError && <Text style={styles.errorText}>{submitError}</Text>}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  // NFR-A3 폰트 200% 대응 — flexWrap + 수직 배치(라벨·입력 가로 배치 회피).
  container: {
    padding: 24,
    paddingTop: 56,
    paddingBottom: 48,
    backgroundColor: '#fff',
  },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 4 },
  caption: { fontSize: 13, color: '#666', marginBottom: 16 },
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
