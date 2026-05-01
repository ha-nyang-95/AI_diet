/**
 * Google OAuth 로그인 훅 (Story 1.2 / Epic 0 dev-loop fix).
 *
 * - expo-auth-session/providers/google + responseType=Code + PKCE auto.
 * - 성공 시 (a) 백엔드 `POST /v1/auth/google` 호출, (b) AuthProvider.signIn으로 토큰 저장,
 *   (c) `(tabs)`로 라우팅.
 *
 * Implicit flow / @react-native-google-signin 도입 절대 금지(architecture 위반).
 *
 * Expo Go 분기 (`Constants.executionEnvironment === 'storeClient'`): iOS/Android 네이티브
 * client ID는 패키지명/SHA-1로 매칭되는데 Expo Go의 컨테이너 앱(`host.exp.exponent`)은
 * 우리 앱의 신원과 다르다. 그대로 전달하면 Google이 `Error 400: invalid_request`로 차단.
 * 따라서 Expo Go에서는 platform-specific 슬롯에도 webClientId 값을 넣어 모든 요청을
 * "web" client_id로 일관 처리한다(host.exp.exponent ↔ native client_id 매칭 우회).
 *
 * Android dev/native build OAuth: Google이 받는 redirect_uri는 single-slash 포맷
 * (`com.googleusercontent.apps.<id>:/oauth2redirect`)만 허용하지만, Android URI canonicalization +
 * Expo Linking이 들어오는 응답을 host-style(`://oauth2redirect`)로 정규화한다. 라이브러리
 * `Google.useAuthRequest`는 한 redirectUri를 두 곳(요청 빌드 + listener startsWith)에 같이
 * 사용하므로 두 형태 동시 만족 불가 → Android는 `WebBrowser.openAuthSessionAsync`를 직접
 * 호출해 두 경로(authUrl ↔ listener prefix)를 분리한다. iOS/Web/Expo Go는 표준 promptAsync
 * 흐름 유지(해당 플랫폼에서는 미스매치가 발생하지 않음).
 *
 * `Constants.appOwnership`은 SDK 44+에서 deprecated — `executionEnvironment`가 modern API.
 * Expo Go 값은 `'storeClient'`(`ExecutionEnvironment.StoreClient` enum 정합).
 */
import Constants from 'expo-constants';
import * as Google from 'expo-auth-session/providers/google';
import { router } from 'expo-router';
import { Platform } from 'react-native';
import { useCallback, useState } from 'react';
import * as WebBrowser from 'expo-web-browser';

import type { AuthUser } from '@/lib/auth';
import { useAuth } from '@/lib/auth';

// OAuth redirect로 앱이 재포그라운드될 때 expo-auth-session이 promptAsync Promise를
// resolve할 수 있도록 deep link를 가로채는 핸들러를 모듈 로드 시점에 등록.
WebBrowser.maybeCompleteAuthSession();

const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

const IS_EXPO_GO = Constants.executionEnvironment === 'storeClient';

interface GoogleLoginResponseMobile {
  access_token: string;
  refresh_token: string;
  expires_in_seconds: number;
  user: AuthUser;
}

export interface UseGoogleSignInResult {
  signIn: () => Promise<void>;
  isInProgress: boolean;
  error: string | null;
  isReady: boolean;
}

function pickClientId(): string | undefined {
  if (IS_EXPO_GO) return process.env.EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_WEB;
  if (Platform.OS === 'ios') return process.env.EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_IOS;
  if (Platform.OS === 'android') {
    return process.env.EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_ANDROID;
  }
  return process.env.EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_WEB;
}

function reverseGoogleClientId(clientId: string): string {
  return `com.googleusercontent.apps.${clientId.replace(/\.apps\.googleusercontent\.com$/, '')}`;
}

export function useGoogleSignIn(nextPath?: string): UseGoogleSignInResult {
  const { signIn: setSession } = useAuth();
  const [isInProgress, setInProgress] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const webClientId = process.env.EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_WEB;
  const androidClientId = process.env.EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_ANDROID;
  // single-slash form — Google에 전송할 정식 redirect_uri (Android client는 이 형식만 허용).
  const androidGoogleRedirectUri =
    !IS_EXPO_GO && Platform.OS === 'android' && androidClientId
      ? `${reverseGoogleClientId(androidClientId)}:/oauth2redirect`
      : undefined;

  const [request, , promptAsync] = Google.useAuthRequest({
    iosClientId: IS_EXPO_GO
      ? webClientId
      : process.env.EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_IOS,
    androidClientId: IS_EXPO_GO ? webClientId : androidClientId,
    webClientId,
    scopes: ['openid', 'email', 'profile'],
    // Android: single-slash로 명시 → request.url 안의 redirect_uri 파라미터가 single-slash로
    // 빌드된다 (Google이 수락). listener prefix는 signIn에서 별도(double-slash)로 사용.
    ...(androidGoogleRedirectUri ? { redirectUri: androidGoogleRedirectUri } : {}),
  });

  const exchangeWithBackend = useCallback(
    async (params: { code: string; redirectUri: string; codeVerifier: string }) => {
      const platform = Platform.OS === 'web' ? 'web' : 'mobile';
      const response = await fetch(`${API_BASE_URL}/v1/auth/google`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform,
          code: params.code,
          redirect_uri: params.redirectUri,
          code_verifier: params.codeVerifier,
        }),
      });
      if (!response.ok) {
        // raw 응답 body는 PKCE/code echo 가능성으로 사용자 화면에 노출 금지 — status만.
        throw new Error(`로그인에 실패했습니다 (${response.status})`);
      }
      return (await response.json()) as GoogleLoginResponseMobile;
    },
    [],
  );

  const signIn = useCallback(async () => {
    if (!request) return;
    setInProgress(true);
    setError(null);
    try {
      let code: string | null = null;
      let stateFromResponse: string | null = null;

      if (!IS_EXPO_GO && Platform.OS === 'android' && androidGoogleRedirectUri) {
        if (!request.url) {
          setError('OAuth URL이 빌드되지 않았습니다');
          return;
        }
        // request.url은 Google 수락 형식(single-slash) redirect_uri 포함.
        // listener prefix는 Linking이 그대로 전달하는 형식(같은 single-slash) 사용.
        const browserResult = await WebBrowser.openAuthSessionAsync(
          request.url,
          androidGoogleRedirectUri,
        );
        if (browserResult.type !== 'success') {
          // 'cancel' / 'dismiss' / 'locked' — 사용자가 닫음. 에러 표기 X.
          return;
        }
        const queryStart = browserResult.url.indexOf('?');
        if (queryStart === -1) {
          setError('OAuth 응답에 파라미터가 없습니다');
          return;
        }
        const params = new URLSearchParams(browserResult.url.slice(queryStart + 1));
        const errorParam = params.get('error');
        if (errorParam) {
          setError(`Google OAuth error: ${errorParam}`);
          return;
        }
        code = params.get('code');
        stateFromResponse = params.get('state');
        if (!code) {
          setError('missing authorization code');
          return;
        }
        if (stateFromResponse !== request.state) {
          // CSRF 방어 — state 불일치는 hard fail.
          setError('OAuth state 불일치');
          return;
        }
      } else {
        const promptResult = await promptAsync();
        if (promptResult.type !== 'success') {
          if (promptResult.type === 'error') {
            setError(promptResult.error?.message ?? 'sign-in error');
          }
          return;
        }
        code = promptResult.params.code ?? null;
        if (!code) {
          setError('missing authorization code');
          return;
        }
        // promptAsync 경로는 expo-auth-session이 state 검증을 내부 수행.
      }

      // 두 분기 모두에서 code를 채우고 누락 시 early-return 했으므로 여기서는 string 보장.
      // TS는 분기 경계에서 narrowing을 잃어 명시적 가드를 다시 둔다.
      if (!code) {
        setError('missing authorization code');
        return;
      }

      // PKCE auto: expo-auth-session이 codeVerifier/redirectUri를 채움. 누락은 설정 오류.
      const codeVerifier = request.codeVerifier;
      const redirectUri = request.redirectUri;
      if (!codeVerifier || !redirectUri) {
        setError('PKCE 또는 redirect_uri 설정이 누락되었습니다');
        return;
      }

      const body = await exchangeWithBackend({
        code,
        // 백엔드의 token endpoint 호출에는 Google이 받았던 그대로의 redirect_uri를 보내야
        // Google이 redirect_uri 일치 검증을 통과 → request.redirectUri (single-slash) 사용.
        redirectUri,
        codeVerifier,
      });

      await setSession({
        access: body.access_token,
        refresh: body.refresh_token,
        user: body.user,
      });
      // AC6 — next 경로가 있으면 그곳으로, 없으면 (tabs) 홈.
      // typedRoutes 적용 환경이라 string casting으로 우회.
      const target = (nextPath ? decodeURIComponent(nextPath) : '/(tabs)') as Parameters<
        typeof router.replace
      >[0];
      router.replace(target);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'unknown error');
    } finally {
      setInProgress(false);
    }
  }, [request, promptAsync, setSession, nextPath, androidClientId, androidGoogleRedirectUri, exchangeWithBackend]);

  return {
    signIn,
    isInProgress,
    error,
    isReady: request !== null && pickClientId() !== undefined,
  };
}
