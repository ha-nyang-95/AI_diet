import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { Stack } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';

import { AuthProvider, queryClient } from '@/lib/auth';
import { persistOptions } from '@/lib/query-persistence';

// OAuth redirect deep-link이 cold-start로 도착했을 때 expo-auth-session이 promptAsync
// Promise를 resolve하도록 root에서 일찍 호출. (Expo Router의 "Unmatched Route" 회피 보조.)
WebBrowser.maybeCompleteAuthSession();

export default function RootLayout() {
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
