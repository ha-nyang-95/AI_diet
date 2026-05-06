/**
 * Story 4.1 AC8 — 알림 권한 거부 시 표준 안내 컴포넌트 (Story 2.2 패턴 복제 + 분리).
 *
 * Story 2.2 `mobile/features/meals/PermissionDeniedView.tsx`의 `kind` prop 카탈로그 SOT가
 * `'camera' | 'mediaLibrary'` 2종 — 본 스토리에서 `'notifications'` 추가하지 않고 *별
 * 폴더 분리*로 결정 (yagni — kind 분기 X, 분리 폴더가 SOT 무결성 우수).
 *
 * 카메라/사진첩과 달리 알림은 *대체 경로 없음*(secondary fallback X) — `onFallbackPress`
 * prop은 호출 측이 *"나중에 설정"* 같은 명시 wire 시에만 노출. 미지정 시 secondary 버튼
 * 미렌더(Story 2.2 컴포넌트 패턴 정합).
 *
 * 카피 (PRD M4 정합):
 * - title: "알림 허용이 필요해요"
 * - retryDescription: "미기록 식단 알림을 받으려면 알림 권한이 필요해요."
 * - settingsDescription: "알림이 필요해요. 설정에서 허용하면 미기록 nudge가 동작합니다."
 *
 * 디자인 정합 (Story 2.2 표준 — centered, padding 16-24, 16px font, flexShrink: 1).
 */

import { Alert, Linking, Pressable, StyleSheet, Text, View } from 'react-native';

interface PermissionDeniedViewProps {
  /** false면 *설정 열기* CTA, true면 *다시 요청* CTA */
  canAskAgain: boolean;
  /** *다시 요청* 또는 *설정 열기* 버튼 콜백. canAskAgain=true일 때만 호출됨 */
  onRetryRequest?: () => void;
  /** secondary fallback 버튼 콜백 (예: *나중에 설정*). 미지정 시 secondary 버튼 미렌더 */
  onFallbackPress?: () => void;
  /** secondary fallback 버튼 라벨 — 미지정 시 default *나중에 설정* */
  fallbackLabel?: string;
}

const TITLE = '알림 허용이 필요해요';
const RETRY_DESCRIPTION = '미기록 식단 알림을 받으려면 알림 권한이 필요해요.';
const SETTINGS_DESCRIPTION =
  '알림이 필요해요. 설정에서 허용하면 미기록 nudge가 동작합니다.';
const DEFAULT_FALLBACK_LABEL = '나중에 설정';

export function PermissionDeniedView({
  canAskAgain,
  onRetryRequest,
  onFallbackPress,
  fallbackLabel,
}: PermissionDeniedViewProps) {
  const description = canAskAgain ? RETRY_DESCRIPTION : SETTINGS_DESCRIPTION;
  const primaryLabel = canAskAgain ? '다시 요청' : '설정 열기';
  const handlePrimary = canAskAgain
    ? onRetryRequest
    : () => {
        // OEM Android에서 settings deep link 부재 시 silent fail 회피 — Story 2.2 P13 정합.
        Linking.openSettings().catch(() => {
          Alert.alert(
            '설정을 열 수 없어요',
            '기기 설정 > 앱 권한에서 직접 허용해주세요.',
          );
        });
      };
  const secondaryLabel = fallbackLabel ?? DEFAULT_FALLBACK_LABEL;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{TITLE}</Text>
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
