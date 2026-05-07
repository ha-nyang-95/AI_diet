import { Stack } from 'expo-router';

/**
 * Settings 화면 그룹 (Story 1.3 AC5/AC13 + Story 5.1 프로필 수정).
 *
 * 개별 screens는 file-based routing으로 자동 등록 — 인라인 ``<Stack.Screen options>``
 * 으로 화면별 title을 설정. Story 5.1에서 ``profile`` screen을 명시 등록(인라인 title
 * 정합 + 미래 typed routes 안정성). Story 5.2에서 ``account-delete``, Story 5.3에서
 * ``data-export`` 추가.
 */
export default function SettingsLayout() {
  return (
    <Stack screenOptions={{ headerShown: true, headerBackTitle: '뒤로' }}>
      <Stack.Screen name="profile" options={{ title: '프로필 수정' }} />
      <Stack.Screen name="data-export" options={{ title: '데이터 내보내기' }} />
      <Stack.Screen name="subscription" options={{ title: '구독' }} />
      <Stack.Screen name="account-delete" options={{ title: '회원 탈퇴' }} />
    </Stack>
  );
}
