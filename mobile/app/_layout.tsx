import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import * as Notifications from 'expo-notifications';
import { Stack, useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useEffect } from 'react';

import { AuthProvider, queryClient } from '@/lib/auth';
import {
  resolveDeepLinkTarget,
  setupGlobalPushHandler,
} from '@/lib/push';
import { persistOptions } from '@/lib/query-persistence';

// OAuth redirect deep-link이 cold-start로 도착했을 때 expo-auth-session이 promptAsync
// Promise를 resolve하도록 root에서 일찍 호출. (Expo Router의 "Unmatched Route" 회피 보조.)
WebBrowser.maybeCompleteAuthSession();

export default function RootLayout() {
  const router = useRouter();

  // Story 4.2 AC7 — push tap deep link wire.
  //
  // (1) `setupGlobalPushHandler`로 foreground 알림 노출 + tap listener 1회 등록.
  // (2) `useLastNotificationResponse` hook으로 cold-start 진입(앱 종료 상태에서 tap →
  //     앱 시작) 1회 처리. deps에 ``response?.notification.request.identifier``를 넣어
  //     동일 알림 중복 처리 차단. cold-start는 history 정합 위해 ``router.replace``.
  useEffect(() => {
    const cleanup = setupGlobalPushHandler({
      push: (href) => router.push(href as Parameters<typeof router.push>[0]),
      replace: (href) => router.replace(href as Parameters<typeof router.replace>[0]),
    });
    return cleanup;
  }, [router]);

  const lastResponse = Notifications.useLastNotificationResponse();
  useEffect(() => {
    const target = resolveDeepLinkTarget(lastResponse);
    if (!target) return;
    try {
      router.replace(target as Parameters<typeof router.replace>[0]);
    } catch (error) {
      console.warn('push.cold_start.navigate_failed', error);
    }
  }, [lastResponse?.notification.request.identifier, lastResponse, router]);

  return (
    <PersistQueryClientProvider client={queryClient} persistOptions={persistOptions}>
      <AuthProvider>
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="index" />
          <Stack.Screen name="(auth)" />
          <Stack.Screen name="(tabs)" />
        </Stack>
      </AuthProvider>
    </PersistQueryClientProvider>
  );
}
