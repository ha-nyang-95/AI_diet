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
 *
 * Story 5.1 — 폼 markup은 ``mobile/features/settings/HealthProfileEditForm`` SOT로
 * 추출(D2 결정 정합). 본 화면은 진입 가드 + redirect chain + ``markProfileCompleted``
 * callback hook만 책임.
 */
import { Redirect, router } from 'expo-router';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';

import { HealthProfileEditForm } from '@/features/settings/HealthProfileEditForm';
import { useAuth } from '@/lib/auth';

export default function OnboardingProfile() {
  const { consentStatus, markProfileCompleted } = useAuth();

  // bootstrap 미완료 (consentStatus null) — 가드 분기 전에 spinner. direct entry로
  // consent fetch 완료 전에 form이 노출되어 사용자가 submit하면 백엔드 403 발사 후
  // 가드가 뒤늦게 발사되는 race 차단.
  if (consentStatus === null) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }
  // 진입 가드 — direct entry 안전망. 정상 흐름은 (tabs) 가드 또는 automated-decision
  // 성공 redirect로 도달.
  if (!consentStatus.basic_consents_complete) {
    return <Redirect href="/(auth)/onboarding/disclaimer" />;
  }
  if (!consentStatus.automated_decision_consent_complete) {
    return <Redirect href="/(auth)/onboarding/automated-decision" />;
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.title}>건강 프로필 입력</Text>
      <Text style={styles.caption}>
        나이·체중·신장·활동 수준·건강 목표·알레르기를 입력하면 분석 정확도가 높아집니다.
      </Text>

      <HealthProfileEditForm
        initial={null}
        mode="create"
        onSuccess={(response) => {
          // 4번째 가드 stale-cache loop 차단 — user state를 동기 갱신해 (tabs) 가드가
          // 다음 render에서 즉시 통과하도록. Story 1.6이 본 redirect 대상을
          // ``tutorial``로 가로채 chain 구성.
          if (response.profile_completed_at) {
            markProfileCompleted(response.profile_completed_at);
          }
          router.replace('/(tabs)');
        }}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  // NFR-A3 폰트 200% 대응 — flexWrap + 수직 배치(라벨·입력 가로 배치 회피).
  container: {
    padding: 24,
    paddingTop: 56,
    paddingBottom: 48,
    backgroundColor: '#fff',
  },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 4 },
  caption: { fontSize: 13, color: '#666', marginBottom: 16 },
});
