/**
 * Settings → 약관 풀텍스트 재열람 (Story 1.3 AC5).
 */
import { Stack } from 'expo-router';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';

import { useLegalDocument } from '@/features/legal/useLegalDocument';

export default function SettingsTerms() {
  const { data, isLoading, isError } = useLegalDocument('terms', 'ko');

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
        <Text style={styles.error}>약관을 불러올 수 없습니다.</Text>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Stack.Screen options={{ title: data.title }} />
      <Text style={styles.body}>{data.body}</Text>
      <Text style={styles.updated}>최근 갱신일: {data.updated_at.slice(0, 10)}</Text>
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
