import { Stack } from 'expo-router';

/**
 * 식단 그룹 (Story 2.1) — list / 입력 화면을 stack 으로 묶음.
 *
 * `headerShown: true`로 상단 헤더 노출 — 입력 화면(`input.tsx`)이 push로 진입 시
 * 자동 *back* 버튼 제공. Story 2.4가 일별 기록 화면 polish 시 stack 깊이 증가
 * (날짜 picker, history 화면) 가능 — 본 스토리는 list/input 2 화면 baseline.
 */
export default function MealsLayout() {
  return <Stack screenOptions={{ headerShown: true, headerBackTitle: '뒤로' }} />;
}
