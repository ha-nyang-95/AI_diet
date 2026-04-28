import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useAuth } from '@/lib/auth';

export default function TabsHome() {
  const { user, signOut } = useAuth();
  return (
    <View style={styles.container}>
      <Text style={styles.title}>안녕하세요, {user?.display_name ?? user?.email}</Text>
      <Text style={styles.subtitle}>(Story 2.1에서 채워짐 — 식단 입력 화면)</Text>
      <Pressable style={styles.button} onPress={signOut}>
        <Text style={styles.buttonText}>로그아웃</Text>
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
