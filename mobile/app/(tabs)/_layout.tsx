import { Redirect, Tabs, usePathname } from 'expo-router';

import { useAuth } from '@/lib/auth';

/**
 * (tabs) 그룹은 보호 라우트 — 인증 + 동의 게이트 두 단계 통과 시에만 진입.
 *
 * Story 1.2: 인증 게이트(`isAuthed`).
 * Story 1.3 AC2: 4종 동의 게이트(`consentStatus.basic_consents_complete`) — 미동의 시
 * `(auth)/onboarding/disclaimer`로 redirect, 진입 시도한 경로는 `?next=` 쿼리로 보존.
 *
 * `consentStatus`는 AuthProvider bootstrap에서 `GET /v1/users/me/consents` 1회 fetch로
 * 채워진다. signIn 직후엔 null — null인 동안에는 동의 게이트를 통과시키지 않고 onboarding
 * 진입(신규 사용자가 default flow). 한 번 fetch된 후 false인 사용자도 onboarding 진입.
 */
export default function TabsLayout() {
  const { isAuthed, isReady, consentStatus } = useAuth();
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

  return <Tabs screenOptions={{ headerShown: false }} />;
}
