/**
 * Story 2.1 — 식단 입력/수정 폼 (POST + PATCH 통합).
 *
 * `react-hook-form` + `zodResolver(mealCreateSchema)` (Story 1.5 패턴 정합). PATCH
 * 모드는 `defaultValues={{ raw_text: meal.raw_text }}`로 prefill.
 *
 * 본 컴포넌트는 *폼 표시*만 — 실제 mutation 호출 + navigation은 부모(`(tabs)/meals/
 * input.tsx`)가 담당. submit 중 disabled 처리 + zod field error 표시 책임만.
 */
import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { mealCreateSchema, type MealCreateFormData } from './mealSchema';

const RAW_TEXT_MAX_LENGTH = 2000;

interface MealInputFormProps {
  defaultValues?: MealCreateFormData;
  isSubmitting: boolean;
  submitLabel: string;
  onSubmit: (data: MealCreateFormData) => void | Promise<void>;
  /** API 에러를 raw_text 필드 에러로 표시할 때 사용. 비울 시 미표시. */
  serverError?: string | null;
  /** P14 — 입력 변경 시 stale `serverError`를 클리어하는 콜백. */
  onClearServerError?: () => void;
}

export function MealInputForm({
  defaultValues,
  isSubmitting,
  submitLabel,
  onSubmit,
  serverError,
  onClearServerError,
}: MealInputFormProps) {
  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<MealCreateFormData>({
    resolver: zodResolver(mealCreateSchema),
    defaultValues: defaultValues ?? { raw_text: '' },
  });

  const fieldErrorMessage = errors.raw_text?.message ?? serverError ?? null;

  return (
    // P13 — 작은 화면(iPhone SE 등)에서 키보드 올라올 때 submit 버튼 가림 방지.
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <Controller
        control={control}
        name="raw_text"
        render={({ field: { onChange, onBlur, value } }) => (
          <TextInput
            value={value}
            onChangeText={(text) => {
              onChange(text);
              // P14 — 사용자가 입력을 수정하면 stale server error 자동 클리어.
              if (serverError && onClearServerError) onClearServerError();
            }}
            onBlur={onBlur}
            multiline
            numberOfLines={6}
            // P12 — OS-level hard cap (paste 등으로 2000자 초과 시 즉시 차단,
            // submit 시점이 아닌 입력 시점에 사용자 인지).
            maxLength={RAW_TEXT_MAX_LENGTH}
            placeholder="예: 삼겹살 1인분, 김치찌개, 소주 2잔"
            style={[styles.input, fieldErrorMessage ? styles.inputError : null]}
            accessibilityLabel="식단 텍스트 입력"
            editable={!isSubmitting}
            textAlignVertical="top"
          />
        )}
      />
      {fieldErrorMessage ? (
        <Text style={styles.errorText} accessibilityRole="alert">
          {fieldErrorMessage}
        </Text>
      ) : null}

      <Pressable
        style={[styles.button, isSubmitting ? styles.buttonDisabled : null]}
        disabled={isSubmitting}
        onPress={handleSubmit(onSubmit)}
        accessibilityRole="button"
        accessibilityLabel={submitLabel}
      >
        <Text style={styles.buttonText}>{isSubmitting ? '저장 중…' : submitLabel}</Text>
      </Pressable>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 16,
    gap: 12,
  },
  input: {
    minHeight: 140,
    borderWidth: 1,
    borderColor: '#d0d0d0',
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    backgroundColor: '#fff',
    color: '#222',
  },
  inputError: {
    borderColor: '#d93025',
  },
  errorText: {
    color: '#d93025',
    fontSize: 14,
    flexShrink: 1,
    flexWrap: 'wrap',
  },
  button: {
    paddingVertical: 14,
    backgroundColor: '#1a73e8',
    borderRadius: 8,
    alignItems: 'center',
    marginTop: 8,
  },
  buttonDisabled: {
    backgroundColor: '#9aa0a6',
  },
  buttonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 16,
  },
});
