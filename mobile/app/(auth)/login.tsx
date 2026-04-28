import { useLocalSearchParams } from 'expo-router';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { useGoogleSignIn } from '@/features/auth/useGoogleSignIn';

export default function LoginScreen() {
  // AC6 — 보호 라우트가 redirect 시 보존한 next 경로(있으면 로그인 성공 후 복귀).
  const { next } = useLocalSearchParams<{ next?: string }>();
  const { signIn, isInProgress, error, isReady } = useGoogleSignIn(next);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>BalanceNote</Text>
      <Text style={styles.subtitle}>Google 계정으로 시작하기</Text>

      <Pressable
        style={[styles.button, (!isReady || isInProgress) && styles.buttonDisabled]}
        onPress={signIn}
        disabled={!isReady || isInProgress}
        accessibilityRole="button"
        accessibilityLabel="Google로 계속하기"
        accessibilityHint="Google 로그인 화면을 엽니다"
      >
        {isInProgress ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.buttonText}>Google로 계속하기</Text>
        )}
      </Pressable>

      {!isReady && (
        <Text style={styles.hint}>
          Google OAuth Client ID가 .env에 설정되지 않았습니다.
        </Text>
      )}
      {error && <Text style={styles.error}>{error}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
    backgroundColor: '#fff',
  },
  title: {
    fontSize: 32,
    fontWeight: '700',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: '#666',
    marginBottom: 48,
  },
  button: {
    backgroundColor: '#1a73e8',
    paddingVertical: 14,
    paddingHorizontal: 32,
    borderRadius: 8,
    minWidth: 240,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  hint: {
    marginTop: 16,
    color: '#888',
    fontSize: 12,
    textAlign: 'center',
  },
  error: {
    marginTop: 16,
    color: '#d33',
    textAlign: 'center',
  },
});
