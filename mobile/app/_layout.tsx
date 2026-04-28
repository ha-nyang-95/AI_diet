import { QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';

import { AuthProvider, queryClient } from '@/lib/auth';

export default function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="index" />
          <Stack.Screen name="(auth)" />
          <Stack.Screen name="(tabs)" />
        </Stack>
      </AuthProvider>
    </QueryClientProvider>
  );
}
