/**
 * Story 5.3 AC4 — 데이터 내보내기 화면.
 *
 * 진입 가드 ①: ``consentStatus === null`` → 스피너(bootstrap, Story 5.1/5.2 패턴 정합).
 *
 * 진입 가드 ② (basic_consents) **미적용** — PIPA Art.35 정보주체 권리(deps.py:202-206 정합)
 *   는 동의 철회와 독립된 권리. 미동의 사용자도 자기 데이터 다운로드 권리 보존.
 *
 * UI:
 * - 안내 카드 — PIPA 정합 + audit 미기록 명시.
 * - 형식 선택 — JSON/CSV 2개 Pressable RadioButton-style + 각 라벨/설명.
 * - "내보내기 시작" Pressable submit 버튼 + ``isPending`` 시 ``ActivityIndicator``.
 * - 성공 시 OS share sheet이 ``useDataExport`` 안에서 자동 노출.
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
  View,
} from 'react-native';

import {
  type DataExportFormat,
  DataExportError,
  useDataExport,
} from '@/features/settings/useDataExport';
import { useAuth } from '@/lib/auth';

export default function DataExportScreen() {
  const { consentStatus } = useAuth();
  const _queryClient = useQueryClient();
  const [format, setFormat] = useState<DataExportFormat>('json');
  const mutation = useDataExport();

  // 진입 가드 ①: bootstrap 미완료.
  if (consentStatus === null) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: '데이터 내보내기' }} />
        <ActivityIndicator />
      </View>
    );
  }

  const handleSubmit = async () => {
    try {
      await mutation.mutateAsync({ format });
    } catch (err) {
      const message =
        err instanceof DataExportError && err.detail
          ? err.detail
          : '다운로드 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.';
      Alert.alert('내보내기 실패', message);
    }
  };

  const isSubmitting = mutation.isPending;

  // unused queryClient placeholder — 일관성을 위해 import 유지(Story 5.2 정합) 후 _ prefix.
  void _queryClient;

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Stack.Screen options={{ title: '데이터 내보내기' }} />
      <Text style={styles.title}>데이터 내보내기</Text>
      <View style={styles.infoCard}>
        <Text style={styles.infoText}>
          내 식단·분석 결과·프로필을 JSON 또는 CSV 파일로 다운로드할 수 있습니다.{'\n'}
          PIPA 정보주체 권리(데이터 이전·열람권)에 따라 audit 기록 없이 처리됩니다.
        </Text>
      </View>

      <Text style={styles.sectionLabel}>형식 선택</Text>
      <View style={styles.formatGroup}>
        <FormatOption
          value="json"
          selected={format === 'json'}
          title="JSON"
          description="표준 JSON — 외부 도구·스크립트 분석에 적합"
          onSelect={setFormat}
          disabled={isSubmitting}
        />
        <FormatOption
          value="csv"
          selected={format === 'csv'}
          title="CSV"
          description="한국어 헤더 — Excel·Google Sheets 직접 열기"
          onSelect={setFormat}
          disabled={isSubmitting}
        />
      </View>

      <Pressable
        style={[styles.submitButton, isSubmitting && styles.submitButtonDisabled]}
        onPress={() => {
          void handleSubmit();
        }}
        disabled={isSubmitting}
        accessibilityRole="button"
        accessibilityLabel="데이터 내보내기 시작"
      >
        {isSubmitting ? (
          <View style={styles.submitInline}>
            <ActivityIndicator color="#fff" />
            <Text style={styles.submitButtonText}>데이터 준비 중</Text>
          </View>
        ) : (
          <Text style={styles.submitButtonText}>내보내기 시작</Text>
        )}
      </Pressable>

      <Pressable
        style={styles.cancelButton}
        onPress={() => router.back()}
        disabled={isSubmitting}
        accessibilityRole="button"
        accessibilityLabel="뒤로"
      >
        <Text style={styles.cancelButtonText}>뒤로</Text>
      </Pressable>
    </ScrollView>
  );
}

interface FormatOptionProps {
  value: DataExportFormat;
  selected: boolean;
  title: string;
  description: string;
  disabled: boolean;
  onSelect: (value: DataExportFormat) => void;
}

function FormatOption({
  value,
  selected,
  title,
  description,
  disabled,
  onSelect,
}: FormatOptionProps) {
  return (
    <Pressable
      style={[styles.formatOption, selected && styles.formatOptionSelected]}
      onPress={() => onSelect(value)}
      disabled={disabled}
      accessibilityRole="radio"
      accessibilityState={{ selected, disabled }}
      accessibilityLabel={`${title} 형식`}
    >
      <View style={styles.formatHeader}>
        <View style={[styles.radio, selected && styles.radioSelected]}>
          {selected ? <View style={styles.radioInner} /> : null}
        </View>
        <Text style={styles.formatTitle}>{title}</Text>
      </View>
      <Text style={styles.formatDescription}>{description}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  container: { padding: 24, paddingBottom: 48, backgroundColor: '#fff' },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 12 },
  infoCard: {
    backgroundColor: '#eef4ff',
    borderColor: '#c5d8ff',
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    marginBottom: 24,
  },
  infoText: { fontSize: 14, color: '#1f3a8a', lineHeight: 20 },
  sectionLabel: { fontSize: 14, color: '#444', marginBottom: 8, fontWeight: '600' },
  formatGroup: { gap: 12, marginBottom: 24 },
  formatOption: {
    borderWidth: 1,
    borderColor: '#dadce0',
    borderRadius: 8,
    padding: 14,
  },
  formatOptionSelected: {
    borderColor: '#1a73e8',
    backgroundColor: '#f0f7ff',
  },
  formatHeader: { flexDirection: 'row', alignItems: 'center', marginBottom: 6 },
  radio: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 2,
    borderColor: '#9aa0a6',
    marginRight: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  radioSelected: { borderColor: '#1a73e8' },
  radioInner: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#1a73e8' },
  formatTitle: { fontSize: 16, fontWeight: '600', color: '#222' },
  formatDescription: { fontSize: 13, color: '#5f6368', marginLeft: 28 },
  submitButton: {
    backgroundColor: '#1a73e8',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
    marginBottom: 12,
  },
  submitButtonDisabled: { opacity: 0.6 },
  submitButtonText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  submitInline: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  cancelButton: {
    backgroundColor: '#f1f3f4',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  cancelButtonText: { color: '#333', fontSize: 15, fontWeight: '500' },
});
