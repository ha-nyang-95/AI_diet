/**
 * expo-router native-intent — OAuth redirect URL swallow.
 *
 * Custom Tabs가 Google OAuth redirect(`com.googleusercontent.apps.<id>:/oauth2redirect?code=…`)
 * 를 VIEW intent로 앱에 돌려보내면 두 리스너가 동시에 받는다:
 *  1) `expo-web-browser`의 `_waitForRedirectAsync` — `useGoogleSignIn`이 code 추출 →
 *     백엔드 교환 → `router.replace('/(tabs)')`로 마무리(정상 흐름).
 *  2) `expo-router`의 deep-link 라우터 — URL을 path로 파싱해 `/oauth2redirect`로 이동
 *     시도 → 라우트 미존재 → "Unmatched Route" 화면 노출.
 *
 * `redirectSystemPath`에서 reverse-client scheme(OAuth 전용)을 감지해 빈 문자열을
 * 반환하면 `expo-router`는 navigation을 스킵(linking.js의 `if (href) listener(href)`
 * 가드). `useGoogleSignIn` 흐름은 그대로 진행되어 정상 라우팅 완료.
 *
 * 일반 deep-link은 그대로 통과(인증된 사용자가 `mobile://(tabs)/meals/<id>` 등으로
 * 진입할 때 영향 없음).
 */
export function redirectSystemPath({ path }: { path: string; initial: boolean }): string {
  if (path && path.startsWith('com.googleusercontent.apps.')) {
    return '';
  }
  return path;
}
