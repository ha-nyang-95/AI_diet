/**
 * Onboarding 4/4 — 자동화 의사결정 동의 (Story 1.4 AC1/AC7).
 *
 * PIPA 2026.03.15 자동화 의사결정 별도 동의 — 5섹션 풀텍스트(처리 항목·이용 목적·
 * 보관 기간·제3자 제공·LLM 외부 처리) + 1 체크박스. 본 화면 진입은 (tabs) 가드가
 * `consentStatus.basic_consents_complete=false`이면 차단해 disclaimer로 redirect 한다.
 *
 * 성공 시 `/(tabs)`로 Redirect — Story 1.6이 본 redirect를 가로채 `tutorial → profile`
 * chain.
 */
import { Redirect } from 'expo-router';
import { useState } from 'react';
import {
  ActivityIndicator,
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
} from '@/features/onboarding/useConsents';

function extractSubmitErrorMessage(err: unknown): string {
  if (err instanceof ConsentSubmitError) {
    if (err.code === 'consent.automated_decision.version_mismatch') {
      return '동의서가 갱신되었습니다. 화면을 다시 열어 최신 텍스트로 동의해 주세요.';
    }
    if (err.status >= 500) {
      return '일시적인 서버 오류로 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.';
    }
    return err.detail ?? `동의 저장 실패 (${err.status})`;
  }
  return '네트워크 오류로 동의 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.';
}

export default function OnboardingAutomatedDecision() {
  const doc = useLegalDocument('automated-decision', 'ko');
  const [agreed, setAgreed] = useState(false);
  const grant = useGrantAutomatedDecisionConsent();

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

  if (grant.isSuccess) {
    // Story 1.5 — AD 동의 완료 후 건강 프로필 입력으로 이동. Story 1.6이 본 redirect를
    // 가로채 ``automated-decision → tutorial → profile → /(tabs)`` chain의 한 구간으로
    // 끼움. typedRoutes 갱신 전이라 cast로 우회.
    const target = '/(auth)/onboarding/profile' as Parameters<typeof Redirect>[0]['href'];
    return <Redirect href={target} />;
  }

  const canSubmit = agreed && !grant.isPending;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{doc.data.title}</Text>
      <Text style={styles.caption}>별도 동의 항목입니다 (PIPA 2026.03.15)</Text>
      <ScrollView style={styles.scroll}>
        <Text style={styles.body}>{doc.data.body}</Text>
      </ScrollView>

      <Pressable
        style={styles.checkboxRow}
        onPress={() => setAgreed((v) => !v)}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: agreed }}
      >
        <View style={[styles.checkbox, agreed && styles.checkboxOn]}>
          {agreed && <Text style={styles.checkboxMark}>✓</Text>}
        </View>
        <Text style={styles.checkboxLabel}>
          위 자동화된 의사결정 처리에 별도 동의합니다 (PIPA 2026.03.15)
        </Text>
      </Pressable>

      <Pressable
        style={[styles.nextButton, !canSubmit && styles.nextButtonDisabled]}
        disabled={!canSubmit}
        onPress={() => {
          grant.mutate({ automated_decision_version: doc.data!.version });
        }}
        accessibilityRole="button"
        accessibilityLabel="동의 완료"
      >
        {grant.isPending ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.nextButtonText}>동의 완료</Text>
        )}
      </Pressable>
      {grant.isError && (
        <Text style={styles.error}>{extractSubmitErrorMessage(grant.error)}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, paddingTop: 56, backgroundColor: '#fff' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 4 },
  caption: { fontSize: 12, color: '#b54708', fontWeight: '600', marginBottom: 12 },
  scroll: { flex: 1 },
  body: { fontSize: 14, lineHeight: 22, color: '#222' },
  checkboxRow: { flexDirection: 'row', alignItems: 'center', marginTop: 12 },
  checkbox: {
    width: 24,
    height: 24,
    borderWidth: 1,
    borderColor: '#888',
    borderRadius: 4,
    marginRight: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxOn: { backgroundColor: '#1a73e8', borderColor: '#1a73e8' },
  checkboxMark: { color: '#fff', fontWeight: '700' },
  checkboxLabel: { fontSize: 14, color: '#222', flex: 1 },
  nextButton: {
    marginTop: 16,
    backgroundColor: '#1a73e8',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  nextButtonDisabled: { opacity: 0.4 },
  nextButtonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  error: { marginTop: 12, color: '#d33', fontSize: 13 },
});
