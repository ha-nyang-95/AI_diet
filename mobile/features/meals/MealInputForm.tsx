/**
 * Story 2.1 + 2.2 — 식단 입력/수정 폼 (POST + PATCH 통합).
 *
 * `react-hook-form` + `zodResolver(mealCreateSchema)` (Story 1.5 패턴 정합). PATCH
 * 모드는 `defaultValues={{ raw_text: meal.raw_text }}`로 prefill.
 *
 * 본 컴포넌트는 *폼 표시*만 — 실제 mutation 호출 + navigation은 부모(`(tabs)/meals/
 * input.tsx`)가 담당. submit 중 disabled 처리 + zod field error 표시 책임만.
 *
 * Story 2.2 — 사진 첨부 UI (카메라/갤러리 버튼 + 썸네일 + 변경/제거):
 * - 부모가 *권한 + presign + R2 PUT* orchestration — Form은 *표시 + onPick 콜백*만.
 * - `isUploading=true` 시 카메라/갤러리 버튼 disable + spinner. 텍스트 입력 + 제출은
 *   disable X (병렬 가능).
 * - *raw_text or image_key 최소 1* 검증은 부모(input.tsx) inline (zod superRefine
 *   회피 — schema 단순 유지).
 * - 권한 거부 시 `PermissionDeniedView` 노출은 부모 책임 — Form은 callback만 받음.
 */
import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';
import {
  ActivityIndicator,
  Image,
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

export type ImagePickKind = 'camera' | 'gallery';

interface MealInputFormProps {
  defaultValues?: MealCreateFormData;
  isSubmitting: boolean;
  submitLabel: string;
  onSubmit: (data: MealCreateFormData) => void | Promise<void>;
  /** API 에러를 raw_text 필드 에러로 표시할 때 사용. 비울 시 미표시. */
  serverError?: string | null;
  /** P14 — 입력 변경 시 stale `serverError`를 클리어하는 콜백. */
  onClearServerError?: () => void;
  /** Story 2.2 — 첨부된 이미지 R2 키 (서버 저장값). */
  imageKey?: string | null;
  /** Story 2.2 — 썸네일 표시용 URI (로컬 또는 public_url). */
  imageLocalUri?: string | null;
  /** Story 2.2 — 카메라/갤러리 버튼 onPress. 부모가 권한 + 업로드 처리. */
  onPickImage?: (kind: ImagePickKind) => void | Promise<void>;
  /** Story 2.2 — 사진 제거 onPress. */
  onClearImage?: () => void;
  /** Story 2.2 — R2 업로드 진행 중. 카메라/갤러리 버튼 disable + spinner. */
  isUploading?: boolean;
}

export function MealInputForm({
  defaultValues,
  isSubmitting,
  submitLabel,
  onSubmit,
  serverError,
  onClearServerError,
  imageKey,
  imageLocalUri,
  onPickImage,
  onClearImage,
  isUploading = false,
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
  const showImageActions = Boolean(onPickImage); // 부모가 사진 흐름 활성화한 경우만 노출.
  const hasAttachment = Boolean(imageKey || imageLocalUri);

  return (
    // P13 — 작은 화면(iPhone SE 등)에서 키보드 올라올 때 submit 버튼 가림 방지.
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      {showImageActions ? (
        <View style={styles.imageSection}>
          {hasAttachment ? (
            <View style={styles.thumbnailRow}>
              {isUploading ? (
                <View style={styles.thumbnailPlaceholder}>
                  <ActivityIndicator />
                  <Text style={styles.uploadingText}>업로드 중…</Text>
                </View>
              ) : imageLocalUri ? (
                <Image
                  source={{ uri: imageLocalUri }}
                  style={styles.thumbnail}
                  accessibilityLabel="첨부된 식단 사진"
                />
              ) : (
                <View style={styles.thumbnailPlaceholder}>
                  <Text style={styles.uploadingText}>이미지</Text>
                </View>
              )}
              <View style={styles.thumbnailActions}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="사진 변경"
                  disabled={isUploading || isSubmitting}
                  onPress={() => onPickImage?.('gallery')}
                  style={({ pressed }) => [
                    styles.smallButton,
                    (isUploading || isSubmitting) && styles.buttonDisabled,
                    pressed && styles.pressed,
                  ]}
                >
                  <Text style={styles.smallButtonText}>변경</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="사진 제거"
                  disabled={isUploading || isSubmitting}
                  onPress={onClearImage}
                  style={({ pressed }) => [
                    styles.smallButton,
                    styles.removeButton,
                    (isUploading || isSubmitting) && styles.buttonDisabled,
                    pressed && styles.pressed,
                  ]}
                >
                  <Text style={[styles.smallButtonText, styles.removeButtonText]}>제거</Text>
                </Pressable>
              </View>
            </View>
          ) : (
            <View style={styles.pickRow}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="카메라로 촬영"
                disabled={isUploading || isSubmitting}
                onPress={() => onPickImage?.('camera')}
                style={({ pressed }) => [
                  styles.pickButton,
                  (isUploading || isSubmitting) && styles.buttonDisabled,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={styles.pickButtonText}>📷 카메라</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="갤러리에서 선택"
                disabled={isUploading || isSubmitting}
                onPress={() => onPickImage?.('gallery')}
                style={({ pressed }) => [
                  styles.pickButton,
                  (isUploading || isSubmitting) && styles.buttonDisabled,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={styles.pickButtonText}>🖼 갤러리</Text>
              </Pressable>
            </View>
          )}
          {isUploading ? (
            <Text style={styles.uploadingHint} accessibilityLiveRegion="polite">
              사진을 업로드하고 있어요…
            </Text>
          ) : null}
        </View>
      ) : null}

      <Controller
        control={control}
        name="raw_text"
        render={({ field: { onChange, onBlur, value } }) => (
          <TextInput
            value={value ?? ''}
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
            placeholder="예: 삼겹살 1인분, 김치찌개, 소주 2잔 (사진만 첨부도 가능)"
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
  imageSection: {
    gap: 8,
  },
  pickRow: {
    flexDirection: 'row',
    gap: 8,
  },
  pickButton: {
    flex: 1,
    paddingVertical: 14,
    borderWidth: 1,
    borderColor: '#1a73e8',
    borderRadius: 8,
    alignItems: 'center',
    backgroundColor: '#fff',
  },
  pickButtonText: {
    color: '#1a73e8',
    fontSize: 16,
    fontWeight: '600',
  },
  thumbnailRow: {
    flexDirection: 'row',
    gap: 12,
    alignItems: 'center',
  },
  thumbnail: {
    width: 100,
    height: 100,
    borderRadius: 8,
    backgroundColor: '#e0e0e0',
  },
  thumbnailPlaceholder: {
    width: 100,
    height: 100,
    borderRadius: 8,
    backgroundColor: '#e0e0e0',
    alignItems: 'center',
    justifyContent: 'center',
  },
  uploadingText: {
    fontSize: 12,
    color: '#5f6368',
    marginTop: 4,
  },
  uploadingHint: {
    fontSize: 13,
    color: '#5f6368',
  },
  thumbnailActions: {
    flex: 1,
    gap: 8,
  },
  smallButton: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    backgroundColor: '#1a73e8',
    borderRadius: 6,
    alignItems: 'center',
  },
  smallButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  removeButton: {
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#d93025',
  },
  removeButtonText: {
    color: '#d93025',
  },
  pressed: {
    opacity: 0.7,
  },
});
