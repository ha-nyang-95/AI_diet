/**
 * Settings 메뉴 (Story 1.3 AC5/AC13).
 *
 * 본 스토리는 (1) 디스클레이머, (2) 약관, (3) 개인정보 처리방침, (4) 로그아웃 4개만.
 * Story 1.5 (프로필 수정), Story 4.1 (알림), Story 5.x (탈퇴/내보내기) 등이 후속 추가.
 */
import { Stack, router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useAuth } from '@/lib/auth';

interface MenuItem {
  label: string;
  onPress: () => void;
}

export default function SettingsIndex() {
  const { signOut } = useAuth();

  // typed routes 등록 전(.expo/types/router.d.ts 재생성 트리거 전)이라 string casting으로 우회.
  type PushTarget = Parameters<typeof router.push>[0];
  const navigateTo = (path: string) => router.push(path as PushTarget);
  const items: MenuItem[] = [
    {
      label: '프로필 수정',
      onPress: () => navigateTo('/(tabs)/settings/profile'),
    },
    {
      label: '알림',
      onPress: () => navigateTo('/(tabs)/settings/notifications'),
    },
    {
      label: '디스클레이머',
      onPress: () => navigateTo('/(tabs)/settings/disclaimer'),
    },
    {
      label: '약관',
      onPress: () => navigateTo('/(tabs)/settings/terms'),
    },
    {
      label: '개인정보 처리방침',
      onPress: () => navigateTo('/(tabs)/settings/privacy'),
    },
    {
      label: '자동화 의사결정 동의',
      onPress: () => navigateTo('/(tabs)/settings/automated-decision'),
    },
    {
      label: '로그아웃',
      onPress: () => {
        void signOut();
      },
    },
    {
      // Story 5.2 — 마지막 항목 배치 사유: 로그아웃은 일상 액션, 탈퇴는 *되돌리기 어려운*
      // 액션이라 UX 정합으로 *마지막 항목*에 배치(이탈 시점 사용자가 의도 확인 1단계).
      // 다이얼로그 confirmation으로 의도 확인 충분 — destructive 색상은 화면 측 styles.
      label: '회원 탈퇴',
      onPress: () => navigateTo('/(tabs)/settings/account-delete'),
    },
  ];

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: '설정' }} />
      {items.map((item) => (
        <Pressable
          key={item.label}
          style={styles.row}
          onPress={item.onPress}
          accessibilityRole="button"
        >
          <Text style={styles.rowLabel}>{item.label}</Text>
          <Text style={styles.rowArrow}>›</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },
  rowLabel: { fontSize: 16, color: '#222' },
  rowArrow: { fontSize: 20, color: '#999' },
});
