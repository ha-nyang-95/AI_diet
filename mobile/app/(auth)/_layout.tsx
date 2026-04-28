import { Redirect, Stack } from 'expo-router';

import { useAuth } from '@/lib/auth';

/**
 * (auth) 그룹은 미인증 진입 라우트 — 이미 인증된 사용자가 deep-link로 접근하면 (tabs)로 redirect.
 * (대칭 가드: (tabs)/_layout이 미인증 → /(auth)/login redirect와 짝.)
 */
export default function AuthLayout() {
  const { isAuthed, isReady } = useAuth();
  if (!isReady) return null;
  if (isAuthed) return <Redirect href="/(tabs)" />;
  return <Stack screenOptions={{ headerShown: false }} />;
}
