import { Stack } from 'expo-router';

/**
 * Onboarding 화면 그룹 (Story 1.3 AC1/AC13).
 * Story 1.6이 본 layout에 navigation guard를 추가해 4종 동의 → automated-decision →
 * tutorial → profile 흐름을 chain할 예정.
 */
export default function OnboardingLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
