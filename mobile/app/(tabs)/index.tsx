import { Redirect } from 'expo-router';

/**
 * (tabs) 그룹 진입 시 기본 화면 — Story 2.1에서 식단 화면으로 redirect.
 *
 * `(tabs)/_layout.tsx`에서 `<Tabs.Screen name="index" options={{ href: null }} />`로
 * 탭 바에서 hide. deeplink `/(tabs)`가 도달하면 본 redirect로 식단 화면 진입.
 * 향후 `welcome` 화면으로 확장 시 본 라우트 재사용.
 */
export default function TabsIndex() {
  const target = '/(tabs)/meals' as Parameters<typeof Redirect>[0]['href'];
  return <Redirect href={target} />;
}
