/**
 * Onboarding 3/3 — 개인정보 처리방침 + 민감정보 별도 동의 (Story 1.3 AC1/AC3/AC13).
 *
 * PIPA 22조 별도 동의 의무 + 23조 민감정보 별도 동의 의무 — 단일 화면에서 *2개 별 체크박스*
 * (privacy + sensitive_personal_info)로 분리. 시각 강조: horizontal divider + 별 색상.
 *
 * 2 체크 모두 통과 시 `POST /v1/users/me/consents` 4 version 전송 → 성공 시 (tabs)로
 * Redirect. Story 1.6이 본 redirect를 가로채 automated-decision/tutorial/profile을 chain.
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
import { useSubmitConsents } from '@/features/onboarding/useConsents';

export default function OnboardingPrivacy() {
  const disclaimerDoc = useLegalDocument('disclaimer', 'ko');
  const termsDoc = useLegalDocument('terms', 'ko');
  const privacyDoc = useLegalDocument('privacy', 'ko');

  const [privacyAgreed, setPrivacyAgreed] = useState(false);
  const [sensitiveAgreed, setSensitiveAgreed] = useState(false);

  const submit = useSubmitConsents();

  const isLoading = disclaimerDoc.isLoading || termsDoc.isLoading || privacyDoc.isLoading;
  const isError = disclaimerDoc.isError || termsDoc.isError || privacyDoc.isError;

  if (isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }
  if (isError || !disclaimerDoc.data || !termsDoc.data || !privacyDoc.data) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>처리방침을 불러올 수 없습니다.</Text>
      </View>
    );
  }

  if (submit.isSuccess) {
    return <Redirect href="/(tabs)" />;
  }

  const canSubmit = privacyAgreed && sensitiveAgreed && !submit.isPending;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{privacyDoc.data.title}</Text>
      <ScrollView style={styles.scroll}>
        <Text style={styles.body}>{privacyDoc.data.body}</Text>
      </ScrollView>

      <Pressable
        style={styles.checkboxRow}
        onPress={() => setPrivacyAgreed((v) => !v)}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: privacyAgreed }}
      >
        <View style={[styles.checkbox, privacyAgreed && styles.checkboxOn]}>
          {privacyAgreed && <Text style={styles.checkboxMark}>✓</Text>}
        </View>
        <Text style={styles.checkboxLabel}>개인정보 처리방침에 동의합니다</Text>
      </Pressable>

      <View style={styles.divider} />

      <Text style={styles.sensitiveCaption}>
        민감정보 별도 동의 (PIPA 23조) — 별도 동의 항목입니다
      </Text>
      <Pressable
        style={styles.checkboxRow}
        onPress={() => setSensitiveAgreed((v) => !v)}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: sensitiveAgreed }}
      >
        <View
          style={[
            styles.checkbox,
            styles.sensitiveCheckbox,
            sensitiveAgreed && styles.sensitiveCheckboxOn,
          ]}
        >
          {sensitiveAgreed && <Text style={styles.checkboxMark}>✓</Text>}
        </View>
        <Text style={styles.checkboxLabel}>
          민감정보(체중·신장·알레르기·식사 기록) 처리에 별도 동의합니다
        </Text>
      </Pressable>

      <Pressable
        style={[styles.nextButton, !canSubmit && styles.nextButtonDisabled]}
        disabled={!canSubmit}
        onPress={() => {
          submit.mutate({
            disclaimer_version: disclaimerDoc.data!.version,
            terms_version: termsDoc.data!.version,
            privacy_version: privacyDoc.data!.version,
            sensitive_personal_info_version: privacyDoc.data!.version,
          });
        }}
        accessibilityRole="button"
        accessibilityLabel="동의 완료"
      >
        {submit.isPending ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.nextButtonText}>동의 완료</Text>
        )}
      </Pressable>
      {submit.isError && (
        <Text style={styles.error}>
          동의 저장 실패: {submit.error instanceof Error ? submit.error.message : ''}
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, paddingTop: 56, backgroundColor: '#fff' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 16 },
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
  // PIPA 23조 민감정보 별도 강조 — 별 색상.
  sensitiveCheckbox: { borderColor: '#b54708' },
  sensitiveCheckboxOn: { backgroundColor: '#b54708', borderColor: '#b54708' },
  checkboxMark: { color: '#fff', fontWeight: '700' },
  checkboxLabel: { fontSize: 14, color: '#222', flex: 1 },
  divider: { height: 1, backgroundColor: '#ddd', marginTop: 16, marginBottom: 4 },
  sensitiveCaption: { marginTop: 12, fontSize: 12, color: '#b54708', fontWeight: '600' },
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
