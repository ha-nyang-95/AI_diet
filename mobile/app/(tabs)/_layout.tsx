import { Ionicons } from '@expo/vector-icons';
import { Redirect, Tabs, usePathname } from 'expo-router';

import { useAuth } from '@/lib/auth';

/**
 * (tabs) 그룹은 보호 라우트 — 인증 + 동의 + 프로필 게이트 4단계 통과 시에만 진입.
 *
 * Story 1.2: 인증 게이트(`isAuthed`).
 * Story 1.3 AC2: 4종 동의 게이트(`consentStatus.basic_consents_complete`) — 미동의 시
 * `(auth)/onboarding/disclaimer`로 redirect, 진입 시도한 경로는 `?next=` 쿼리로 보존.
 * Story 1.4 AC8: 자동화 의사결정 게이트(`automated_decision_consent_complete`) —
 * 미동의 시 `(auth)/onboarding/automated-decision`으로 redirect.
 * Story 1.5 AC9: 건강 프로필 게이트(`user.profile_completed_at`) — 미입력 시
 * `(auth)/onboarding/profile`로 redirect.
 *
 * 가드 *순서*가 중요 — 상위 단계 미통과 사용자가 하위 화면으로 우선 라우팅되면
 * 하위 검증이 실패한다. (1) 인증 → (2) basic → (3) AD → (4) profile.
 *
 * `consentStatus`는 AuthProvider bootstrap에서 `GET /v1/users/me/consents` 1회 fetch로
 * 채워진다. `user.profile_completed_at`은 `GET /v1/users/me` 응답으로 동시에 채워진다.
 * signIn 직후엔 둘 다 null — null인 동안에는 게이트를 통과시키지 않고 onboarding
 * 진입(신규 사용자가 default flow).
 */
export default function TabsLayout() {
  const { isAuthed, isReady, consentStatus, user } = useAuth();
  const pathname = usePathname();

  if (!isReady) return null;
  if (!isAuthed) {
    const next = encodeURIComponent(pathname || '/(tabs)');
    return <Redirect href={`/(auth)/login?next=${next}`} />;
  }
  if (!consentStatus?.basic_consents_complete) {
    const next = encodeURIComponent(pathname || '/(tabs)');
    const target = `/(auth)/onboarding/disclaimer?next=${next}` as Parameters<
      typeof Redirect
    >[0]['href'];
    return <Redirect href={target} />;
  }
  // Settings 의 자동화 의사결정 화면(`/settings/automated-decision`)은 본 가드를 우회.
  // revoke 직후 `automated_decision_consent_complete=false` 가 되더라도 settings 화면에
  // 머물며 *동의 다시 부여* 흐름을 진행해야 한다.
  if (
    !consentStatus.automated_decision_consent_complete &&
    !pathname.startsWith('/settings/automated-decision')
  ) {
    const next = encodeURIComponent(pathname || '/(tabs)');
    const target = `/(auth)/onboarding/automated-decision?next=${next}` as Parameters<
      typeof Redirect
    >[0]['href'];
    return <Redirect href={target} />;
  }
  // Story 1.6 — 4번째 가드 redirect target = tutorial(tutorial이 자체 seen flag로 분기).
  // tutorial 화면이 AsyncStorage tutorial-seen flag로 first-time vs resume 분기 →
  // seen=true이면 즉시 /profile로 push, seen=false이면 3 슬라이드 노출.
  // Story 5.1이 도입할 *프로필 수정* 화면(/settings/profile)은 본 가드를 우회해야 함 —
  // 향후 같은 settings 우회 패턴 적용.
  if (!user?.profile_completed_at) {
    const next = encodeURIComponent(pathname || '/(tabs)');
    const target = `/(auth)/onboarding/tutorial?next=${next}` as Parameters<
      typeof Redirect
    >[0]['href'];
    return <Redirect href={target} />;
  }

  return (
    <Tabs screenOptions={{ headerShown: false }}>
      {/*
       * P9 — index 라우트는 *redirect-only*: `(tabs)/index.tsx`의 `<Redirect>`가
       * deeplink `/(tabs)` 진입 시 안전성을 보존하고, 본 `href: null`이 탭 바에서만
       * 항목을 hide. 둘 다 의도된 직교 책임 (deeplink 안전성 vs 탭 바 노출).
       */}
      <Tabs.Screen name="index" options={{ href: null }} />
      <Tabs.Screen
        name="meals"
        options={{
          title: '식단',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="restaurant" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: '설정',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="settings" color={color} size={size} />
          ),
        }}
      />
    </Tabs>
  );
}
