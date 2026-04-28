import { Redirect, Tabs, usePathname } from 'expo-router';

import { useAuth } from '@/lib/auth';

/**
 * (tabs) 그룹은 보호 라우트 — 인증 상태 확인 후 미인증 시 /(auth)/login 으로 redirect.
 * AC6 정합: 진입 시도한 보호 경로를 `?next=` 쿼리로 보존해 로그인 후 복귀 가능.
 * Story 2.1+에서 실제 탭(식단·기록·분석 등) 추가.
 */
export default function TabsLayout() {
  const { isAuthed, isReady } = useAuth();
  const pathname = usePathname();

  if (!isReady) return null;
  if (!isAuthed) {
    const next = encodeURIComponent(pathname || '/(tabs)');
    return <Redirect href={`/(auth)/login?next=${next}`} />;
  }

  return <Tabs screenOptions={{ headerShown: false }} />;
}
