/**
 * Story 2.2 — 권한 거부 시 표준 안내 컴포넌트.
 *
 * `kind` prop으로 카메라/사진첩 분기. `canAskAgain`이 true면 *다시 요청* 버튼 + fallback,
 * false면 *설정 열기* 버튼(`Linking.openSettings()`) + fallback.
 *
 * Story 4.1 알림 권한도 동일 props로 재사용 가능 — `kind`에 `'notifications'` 추가만으로
 * 메시지/CTA 카탈로그 1지점 collation. 본 스토리 baseline은 `'camera' | 'mediaLibrary'`
 * 2종 한정 (forward props는 추가 안 함 — yagni).
 *
 * 디자인 정합 (Story 1.5 빈 화면 / Story 2.1 *오류 — 다시 시도* 패턴):
 * - centered, 16-24 px padding, 16 px font.
 * - primary CTA(다시 요청 / 설정 열기) + secondary fallback.
 * - 폰트 스케일 200% 대응(`flexShrink: 1` + wrap).
 * - `accessibilityRole="button"` 모든 CTA.
 */

import { Alert, Linking, Pressable, StyleSheet, Text, View } from 'react-native';

export type PermissionKind = 'camera' | 'mediaLibrary';

interface PermissionDeniedViewProps {
  /** 어떤 권한이 거부되었는지 — 메시지/CTA 분기 */
  kind: PermissionKind;
  /** false면 *설정 열기* CTA, true면 *다시 요청* CTA */
  canAskAgain: boolean;
  /** *다시 요청* 또는 *설정 열기* 버튼 콜백. canAskAgain=true일 때만 호출됨 */
  onRetryRequest?: () => void;
  /** secondary fallback 버튼 콜백 (예: 카메라 거부 시 *갤러리 선택*) */
  onFallbackPress?: () => void;
  /** secondary fallback 버튼 라벨 — 미지정 시 kind 별 default */
  fallbackLabel?: string;
}

interface KindCopy {
  title: string;
  retryDescription: string;
  settingsDescription: string;
  defaultFallbackLabel: string;
}

const COPY: Record<PermissionKind, KindCopy> = {
  camera: {
    title: '카메라 사용 권한이 필요해요',
    retryDescription: '식단 사진을 촬영하려면 카메라 접근 권한이 필요해요.',
    settingsDescription: '카메라가 필요해요. 설정에서 허용하면 사진 촬영이 가능합니다.',
    defaultFallbackLabel: '갤러리에서 선택',
  },
  mediaLibrary: {
    title: '사진첩 접근 권한이 필요해요',
    retryDescription: '식단 사진을 선택하려면 사진첩 접근 권한이 필요해요.',
    settingsDescription:
      '사진첩이 필요해요. 설정에서 허용하면 갤러리에서 사진 선택이 가능합니다.',
    defaultFallbackLabel: '카메라로 촬영',
  },
};

export function PermissionDeniedView({
  kind,
  canAskAgain,
  onRetryRequest,
  onFallbackPress,
  fallbackLabel,
}: PermissionDeniedViewProps) {
  const copy = COPY[kind];
  const description = canAskAgain ? copy.retryDescription : copy.settingsDescription;
  const primaryLabel = canAskAgain ? '다시 요청' : '설정 열기';
  const handlePrimary = canAskAgain
    ? onRetryRequest
    : () => {
        // RN 표준 API — iOS/Android 양쪽 표준. P13 fix — OEM Android에서 settings deep
        // link 부재 시 silent fail이 아니라 사용자에게 안내 (catch + Alert).
        Linking.openSettings().catch(() => {
          Alert.alert(
            '설정을 열 수 없어요',
            '기기 설정 > 앱 권한에서 직접 허용해주세요.',
          );
        });
      };
  const secondaryLabel = fallbackLabel ?? copy.defaultFallbackLabel;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{copy.title}</Text>
      <Text style={styles.description}>{description}</Text>
      {handlePrimary ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={primaryLabel}
          onPress={handlePrimary}
          style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed]}
        >
          <Text style={styles.primaryButtonText}>{primaryLabel}</Text>
        </Pressable>
      ) : null}
      {onFallbackPress ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={secondaryLabel}
          onPress={onFallbackPress}
          style={({ pressed }) => [styles.secondaryButton, pressed && styles.pressed]}
        >
          <Text style={styles.secondaryButtonText}>{secondaryLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingVertical: 24,
    paddingHorizontal: 16,
    alignItems: 'center',
    gap: 12,
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1a1a1a',
    textAlign: 'center',
    flexShrink: 1,
  },
  description: {
    fontSize: 16,
    lineHeight: 22,
    color: '#4a4a4a',
    textAlign: 'center',
    flexShrink: 1,
  },
  primaryButton: {
    marginTop: 8,
    paddingVertical: 12,
    paddingHorizontal: 24,
    backgroundColor: '#0a7ea4',
    borderRadius: 8,
    minWidth: 160,
    alignItems: 'center',
  },
  primaryButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  secondaryButton: {
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderWidth: 1,
    borderColor: '#0a7ea4',
    borderRadius: 8,
    minWidth: 160,
    alignItems: 'center',
  },
  secondaryButtonText: {
    color: '#0a7ea4',
    fontSize: 16,
    fontWeight: '600',
  },
  pressed: {
    opacity: 0.7,
  },
});
