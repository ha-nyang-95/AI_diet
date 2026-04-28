/**
 * Settings → 디스클레이머 풀텍스트 재열람 (Story 1.3 AC5).
 * 푸터에 `<DisclaimerFooter />` 표시 (AC4 사용처 1건).
 */
import { Stack } from 'expo-router';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';

import DisclaimerFooter from '@/features/legal/DisclaimerFooter';
import { useLegalDocument } from '@/features/legal/useLegalDocument';

export default function SettingsDisclaimer() {
  const { data, isLoading, isError } = useLegalDocument('disclaimer', 'ko');

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
    <ScrollView contentContainerStyle={styles.container}>
      <Stack.Screen options={{ title: data.title }} />
      <Text style={styles.body}>{data.body}</Text>
      <Text style={styles.updated}>최근 갱신일: {data.updated_at.slice(0, 10)}</Text>
      <DisclaimerFooter />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 20, paddingBottom: 40, backgroundColor: '#fff' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  body: { fontSize: 14, lineHeight: 22, color: '#222' },
  updated: { marginTop: 24, fontSize: 12, color: '#888' },
  error: { color: '#d33', fontSize: 14 },
});
