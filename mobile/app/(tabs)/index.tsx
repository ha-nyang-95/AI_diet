import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useAuth } from '@/lib/auth';

/**
 * (tabs) 홈 — Story 2.1에서 식단 입력 화면으로 채워질 예정.
 * 로그아웃 / 디스클레이머 / 약관 / 개인정보 진입은 (tabs)/settings/index.tsx에서 일원화
 * (Story 1.3 AC13).
 */
export default function TabsHome() {
  const { user } = useAuth();
  return (
    <View style={styles.container}>
      <Text style={styles.title}>안녕하세요, {user?.display_name ?? user?.email}</Text>
      <Text style={styles.subtitle}>(Story 2.1에서 채워짐 — 식단 입력 화면)</Text>
      <Pressable
        style={styles.button}
        onPress={() => {
          const target = '/(tabs)/settings' as Parameters<typeof router.push>[0];
          router.push(target);
        }}
      >
        <Text style={styles.buttonText}>설정</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  title: {
    fontSize: 20,
    fontWeight: '600',
    marginBottom: 12,
  },
  subtitle: {
    color: '#666',
    marginBottom: 40,
  },
  button: {
    paddingHorizontal: 24,
    paddingVertical: 12,
    backgroundColor: '#eee',
    borderRadius: 6,
  },
  buttonText: {
    color: '#222',
    fontWeight: '500',
  },
});
