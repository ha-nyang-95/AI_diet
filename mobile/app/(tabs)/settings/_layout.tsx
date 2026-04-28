import { Stack } from 'expo-router';

/**
 * Settings 화면 그룹 (Story 1.3 AC5/AC13).
 * 알림 / 프로필 수정 / 회원 탈퇴 / 데이터 내보내기 / 앱 정보 등은 후속 스토리(2.x, 4.1,
 * 5.x, Story 1.5)에서 메뉴 추가 — 본 스토리는 동의·디스클레이머·약관·개인정보 처리방침 +
 * 로그아웃만.
 */
export default function SettingsLayout() {
  return <Stack screenOptions={{ headerShown: true, headerBackTitle: '뒤로' }} />;
}
