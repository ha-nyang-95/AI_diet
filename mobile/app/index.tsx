import { Redirect } from 'expo-router';
import { ActivityIndicator, View } from 'react-native';

import { useAuth } from '@/lib/auth';

export default function Index() {
  const { isAuthed, isReady } = useAuth();
  if (!isReady) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator />
      </View>
    );
  }
  // 진입 경로(/) 자체는 next 보존 대상이 아님 — 직접 (tabs) 또는 login으로.
  return <Redirect href={isAuthed ? '/(tabs)' : '/(auth)/login'} />;
}
