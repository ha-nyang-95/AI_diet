/**
 * Settings → 자동화 의사결정 동의 풀텍스트 + 부여/철회 (Story 1.4 AC8).
 *
 * 동의 부여 사용자 → *동의 철회* 버튼 (빨간색) + Confirm 다이얼로그.
 * 미동의/철회 사용자 → *동의 다시 부여* 버튼 (파란색) — 본 화면에서 즉시 grant.
 *
 * 철회 시 분석 기능(Epic 3)이 비활성화되며 회원 탈퇴와 무관함을 1줄 안내.
 */
import { Stack } from 'expo-router';
import { useRef } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { useLegalDocument } from '@/features/legal/useLegalDocument';
import {
  ConsentSubmitError,
  useGrantAutomatedDecisionConsent,
  useRevokeAutomatedDecisionConsent,
} from '@/features/onboarding/useConsents';
import { useAuth } from '@/lib/auth';

function extractMessage(err: unknown): string {
  if (err instanceof ConsentSubmitError) {
    if (err.code === 'consent.automated_decision.version_mismatch') {
      return '동의서가 갱신되었습니다. 화면을 다시 열어 최신 텍스트로 동의해 주세요.';
    }
    if (err.code === 'consent.automated_decision.not_granted') {
      return '이미 미동의 상태입니다. 화면을 새로 고쳐 주세요.';
    }
    if (err.status >= 500) {
      return '일시적인 서버 오류 — 잠시 후 다시 시도해 주세요.';
    }
    return err.detail ?? `처리 실패 (${err.status})`;
  }
  return '네트워크 오류로 처리에 실패했습니다.';
}

export default function SettingsAutomatedDecision() {
  const { consentStatus } = useAuth();
  const doc = useLegalDocument('automated-decision', 'ko');
  const grant = useGrantAutomatedDecisionConsent();
  const revoke = useRevokeAutomatedDecisionConsent();

  // double-tap 차단 — Story 1.3 P10 패턴 정합.
  const inflightRef = useRef(false);

  if (doc.isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }
  if (doc.isError || !doc.data) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>동의서를 불러올 수 없습니다.</Text>
      </View>
    );
  }

  const granted = consentStatus?.automated_decision_consent_complete ?? false;
  const consentAt = consentStatus?.automated_decision_consent_at;
  const revokedAt = consentStatus?.automated_decision_revoked_at;
  const isPending = grant.isPending || revoke.isPending;

  const onGrant = () => {
    if (inflightRef.current) return;
    inflightRef.current = true;
    grant.mutate(
      { automated_decision_version: doc.data!.version },
      {
        onSettled: () => {
          inflightRef.current = false;
        },
      },
    );
  };

  const onRevoke = () => {
    if (inflightRef.current) return;
    Alert.alert(
      '동의 철회',
      '동의 철회 시 분석 기능 사용 불가 — 진행하시겠습니까?',
      [
        { text: '취소', style: 'cancel' },
        {
          text: '철회',
          style: 'destructive',
          onPress: () => {
            inflightRef.current = true;
            revoke.mutate(undefined, {
              onSettled: () => {
                inflightRef.current = false;
              },
            });
          },
        },
      ],
    );
  };

  const error = grant.isError
    ? extractMessage(grant.error)
    : revoke.isError
      ? extractMessage(revoke.error)
      : null;

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Stack.Screen options={{ title: doc.data.title }} />
      <Text style={styles.body}>{doc.data.body}</Text>

      <View style={styles.statusBlock}>
        <Text style={styles.statusLabel}>현재 상태</Text>
        {granted ? (
          <Text style={styles.statusValueOk}>동의 부여됨{consentAt ? ` · ${consentAt.slice(0, 10)}` : ''}</Text>
        ) : revokedAt ? (
          <Text style={styles.statusValueOff}>철회됨 · {revokedAt.slice(0, 10)}</Text>
        ) : (
          <Text style={styles.statusValueOff}>미동의</Text>
        )}
      </View>

      <Text style={styles.notice}>
        동의 철회 시 영양 분석(Epic 3) 기능이 차단됩니다 — 회원 탈퇴와 무관합니다.
      </Text>

      {granted ? (
        <Pressable
          style={[styles.buttonDanger, isPending && styles.buttonDisabled]}
          disabled={isPending}
          onPress={onRevoke}
          accessibilityRole="button"
          accessibilityLabel="자동화 의사결정 동의 철회"
        >
          {revoke.isPending ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.buttonText}>동의 철회</Text>
          )}
        </Pressable>
      ) : (
        <Pressable
          style={[styles.buttonPrimary, isPending && styles.buttonDisabled]}
          disabled={isPending}
          onPress={onGrant}
          accessibilityRole="button"
          accessibilityLabel="자동화 의사결정 동의 다시 부여"
        >
          {grant.isPending ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.buttonText}>동의 다시 부여</Text>
          )}
        </Pressable>
      )}

      {error && <Text style={styles.error}>{error}</Text>}
      <Text style={styles.updated}>최근 갱신일: {doc.data.updated_at.slice(0, 10)}</Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 20, paddingBottom: 40, backgroundColor: '#fff' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  body: { fontSize: 14, lineHeight: 22, color: '#222' },
  statusBlock: {
    marginTop: 20,
    padding: 12,
    borderRadius: 8,
    backgroundColor: '#f4f6f8',
  },
  statusLabel: { fontSize: 12, color: '#666', marginBottom: 4 },
  statusValueOk: { fontSize: 15, color: '#1a73e8', fontWeight: '600' },
  statusValueOff: { fontSize: 15, color: '#b54708', fontWeight: '600' },
  notice: { marginTop: 12, fontSize: 12, color: '#5a3a17', lineHeight: 18 },
  buttonPrimary: {
    marginTop: 20,
    backgroundColor: '#1a73e8',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  buttonDanger: {
    marginTop: 20,
    backgroundColor: '#c0392b',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  buttonDisabled: { opacity: 0.4 },
  buttonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  error: { marginTop: 12, color: '#d33', fontSize: 13 },
  updated: { marginTop: 24, fontSize: 12, color: '#888' },
});
