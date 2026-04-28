/**
 * Onboarding 1/3 — 디스클레이머 acknowledge (Story 1.3 AC1/AC13).
 *
 * 풀텍스트 ScrollView + 단일 체크 박스 + 다음 버튼. 미체크 시 다음 버튼 disabled.
 * 풀텍스트는 backend `GET /v1/legal/disclaimer?lang=ko` SOT (research 3.4 정합).
 */
import { router } from 'expo-router';
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

export default function OnboardingDisclaimer() {
  const { data, isLoading, isError } = useLegalDocument('disclaimer', 'ko');
  const [acknowledged, setAcknowledged] = useState(false);

  if (isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }
  if (isError || !data) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>디스클레이머를 불러올 수 없습니다.</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{data.title}</Text>
      <ScrollView style={styles.scroll}>
        <Text style={styles.body}>{data.body}</Text>
      </ScrollView>

      <Pressable
        style={styles.checkboxRow}
        onPress={() => setAcknowledged((v) => !v)}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: acknowledged }}
      >
        <View style={[styles.checkbox, acknowledged && styles.checkboxOn]}>
          {acknowledged && <Text style={styles.checkboxMark}>✓</Text>}
        </View>
        <Text style={styles.checkboxLabel}>위 디스클레이머를 확인했습니다</Text>
      </Pressable>

      <Pressable
        style={[styles.nextButton, !acknowledged && styles.nextButtonDisabled]}
        disabled={!acknowledged}
        onPress={() => router.push('/(auth)/onboarding/terms')}
        accessibilityRole="button"
        accessibilityLabel="다음으로"
      >
        <Text style={styles.nextButtonText}>다음으로</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, paddingTop: 56, backgroundColor: '#fff' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 16 },
  scroll: { flex: 1 },
  body: { fontSize: 14, lineHeight: 22, color: '#222' },
  checkboxRow: { flexDirection: 'row', alignItems: 'center', marginTop: 16 },
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
  error: { color: '#d33', fontSize: 14 },
});
