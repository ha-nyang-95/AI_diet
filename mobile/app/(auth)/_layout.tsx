import { Redirect, Stack, usePathname } from 'expo-router';

import { useAuth } from '@/lib/auth';

/**
 * (auth) 그룹은 미인증 진입 라우트 + onboarding 흐름.
 * 가드 정책:
 * - 미인증 사용자: 자유롭게 진입(login).
 * - 인증된 사용자가 `/(auth)/login`으로 deep-link: (tabs)로 redirect (대칭 가드:
 *   (tabs)/_layout이 미인증 → /(auth)/login redirect와 짝).
 * - 인증된 사용자가 `/(auth)/onboarding/*`로 진입: **허용해야 함** — (tabs)/_layout이
 *   consent/profile 미완료 시 onboarding으로 redirect하기 때문에, onboarding을 무조건
 *   (tabs)로 되돌리면 두 가드가 ping-pong하며 React "Maximum update depth exceeded".
 */
export default function AuthLayout() {
  const { isAuthed, isReady } = useAuth();
  const pathname = usePathname();
  if (!isReady) return null;
  if (isAuthed && pathname === '/login') {
    return <Redirect href="/(tabs)" />;
  }
  return <Stack screenOptions={{ headerShown: false }} />;
}
