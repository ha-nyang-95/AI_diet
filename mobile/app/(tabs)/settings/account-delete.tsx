/**
 * Story 5.2 AC5 — 회원 탈퇴 화면.
 *
 * 진입 가드 ①: ``consentStatus === null`` → 스피너(bootstrap, Story 5.1 패턴).
 *
 * 진입 가드 ② (basic_consents) **미적용** — PIPA Art.35 정보주체 권리(deps.py:202-206 정합)
 *   는 동의 철회와 독립된 권리. 미동의 사용자도 탈퇴 가능해야 권리 봉쇄 X. 탈퇴 자체가
 *   *동의 철회의 최종 형태*.
 *
 * Confirmation: React Native ``Alert.alert`` — 본문에 30일 grace + 영구 파기 안내. 사용자
 *   명시 *"탈퇴 확정"* / *"취소"* 2 버튼.
 *
 * 사유 입력(선택): ``<TextInput multiline maxLength={200}>`` — server-side ``Field(max_length=200)``
 *   1차 가드 정합. 빈 string은 서버에서 None normalize.
 *
 * Submit: ``useAccountDelete`` mutation → 성공 시 ``signOut()`` + ``router.replace("/(auth)/login")``.
 *   실패 시 ``Alert.alert``(다이얼로그는 사용자 명시 dismiss까지 보임 — 토스트 0ms 가시성
 *   회귀 X).
 */
import { useQueryClient } from '@tanstack/react-query';
import { Stack, router } from 'expo-router';
import { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { AccountDeleteError, useAccountDelete } from '@/features/settings/useAccountDelete';
import { useAuth } from '@/lib/auth';

const REASON_MAX_LENGTH = 200;

export default function AccountDeleteScreen() {
  const { consentStatus, signOut } = useAuth();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState('');
  const mutation = useAccountDelete();

  // 진입 가드 ①: bootstrap 미완료.
  if (consentStatus === null) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: '회원 탈퇴' }} />
        <ActivityIndicator />
      </View>
    );
  }

  const handleConfirm = () => {
    Alert.alert(
      '탈퇴 확인',
      '탈퇴 시 30일 후 모든 데이터가 영구 파기됩니다. 30일 내 같은 Google 계정으로 재로그인 시 안내됩니다.',
      [
        { text: '취소', style: 'cancel' },
        {
          text: '탈퇴 확정',
          style: 'destructive',
          onPress: () => {
            void submitDelete();
          },
        },
      ],
    );
  };

  const submitDelete = async () => {
    try {
      await mutation.mutateAsync({ reason: reason.trim() || null });
    } catch (err) {
      const message =
        err instanceof AccountDeleteError && err.detail
          ? err.detail
          : '탈퇴 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.';
      Alert.alert('탈퇴 실패', message);
      return;
    }
    // CR P8 — 성공 시 순서: signOut(로컬 토큰 클리어) → queryClient.clear()(이미 인증 끊긴
    // 상태에서 stale 쿼리 정리) → router.replace. clear()를 먼저 호출하면 활성 쿼리가
    // 401로 즉시 refetch되며 authFetch refresh race 발생.
    try {
      await signOut();
    } catch {
      // signOut 자체는 graceful — 라우팅이 절대 차단되지 않음(auth.tsx 패턴 정합).
    }
    queryClient.clear();
    router.replace('/(auth)/login');
  };

  const isSubmitting = mutation.isPending;

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Stack.Screen options={{ title: '회원 탈퇴' }} />
      <Text style={styles.title}>회원 탈퇴</Text>
      <Text style={styles.warning}>
        탈퇴 시 30일 후 모든 데이터가 영구 파기됩니다.{'\n'}
        30일 내 같은 Google 계정으로 재로그인 시 안내가 표시됩니다.
      </Text>

      <Text style={styles.label}>탈퇴 사유 (선택)</Text>
      <TextInput
        style={styles.textarea}
        multiline
        maxLength={REASON_MAX_LENGTH}
        placeholder="불편한 점이 있으셨다면 알려주세요 (선택)"
        placeholderTextColor="#9aa0a6"
        value={reason}
        onChangeText={setReason}
        editable={!isSubmitting}
        accessibilityLabel="탈퇴 사유 입력"
      />
      <Text style={styles.charCount}>
        {reason.length} / {REASON_MAX_LENGTH}
      </Text>

      <Pressable
        style={[styles.submitButton, isSubmitting && styles.submitButtonDisabled]}
        onPress={handleConfirm}
        disabled={isSubmitting}
        accessibilityRole="button"
        accessibilityLabel="회원 탈퇴 진행"
      >
        {isSubmitting ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.submitButtonText}>회원 탈퇴 진행</Text>
        )}
      </Pressable>

      <Pressable
        style={styles.cancelButton}
        onPress={() => router.back()}
        disabled={isSubmitting}
        accessibilityRole="button"
        accessibilityLabel="취소"
      >
        <Text style={styles.cancelButtonText}>취소</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  container: { padding: 24, paddingBottom: 48, backgroundColor: '#fff' },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 8 },
  warning: {
    fontSize: 14,
    color: '#b00020',
    backgroundColor: '#fde7ea',
    borderColor: '#f5c2c7',
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    marginBottom: 20,
    lineHeight: 20,
  },
  label: { fontSize: 14, color: '#444', marginBottom: 6 },
  textarea: {
    minHeight: 96,
    borderWidth: 1,
    borderColor: '#dadce0',
    borderRadius: 8,
    padding: 12,
    fontSize: 14,
    textAlignVertical: 'top',
    color: '#222',
  },
  charCount: {
    fontSize: 12,
    color: '#777',
    textAlign: 'right',
    marginTop: 4,
    marginBottom: 16,
  },
  submitButton: {
    backgroundColor: '#d93025',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
    marginBottom: 12,
  },
  submitButtonDisabled: { opacity: 0.6 },
  submitButtonText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  cancelButton: {
    backgroundColor: '#f1f3f4',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  cancelButtonText: { color: '#333', fontSize: 15, fontWeight: '500' },
});
