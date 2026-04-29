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
 * 우리 앱의 신원과 다르다. 그대로 전달하면 Google이 `Error 400: invalid_request`로 차단
 * (README의 "Expo Go 개발 환경에서는 Web client ID를 모든 플랫폼에 사용" SOP 정합). 따라서
 * Expo Go 한정으로 webClientId만 전달해 expo-auth-session이 Web/Expo proxy 흐름으로
 * 진입하게 한다. 네이티브 EAS standalone 빌드에서는 세 ID 모두 전달(기존 동작 유지).
 *
 * `Constants.appOwnership`은 SDK 44+에서 deprecated — `executionEnvironment`가 modern API.
 * Expo Go 값은 `'storeClient'`(`ExecutionEnvironment.StoreClient` enum 정합).
 */
import Constants from 'expo-constants';
import * as Google from 'expo-auth-session/providers/google';
import { router } from 'expo-router';
import { Platform } from 'react-native';
import { useCallback, useState } from 'react';

import type { AuthUser } from '@/lib/auth';
import { useAuth } from '@/lib/auth';

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

export function useGoogleSignIn(nextPath?: string): UseGoogleSignInResult {
  const { signIn: setSession } = useAuth();
  const [isInProgress, setInProgress] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [request, , promptAsync] = Google.useAuthRequest({
    ...(IS_EXPO_GO
      ? {}
      : {
          iosClientId: process.env.EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_IOS,
          androidClientId: process.env.EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_ANDROID,
        }),
    webClientId: process.env.EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_WEB,
    scopes: ['openid', 'email', 'profile'],
  });

  const signIn = useCallback(async () => {
    if (!request) return;
    setInProgress(true);
    setError(null);
    try {
      const promptResult = await promptAsync();
      if (promptResult.type !== 'success') {
        if (promptResult.type === 'error') {
          setError(promptResult.error?.message ?? 'sign-in error');
        }
        return;
      }

      const code = promptResult.params.code;
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
      const platform = Platform.OS === 'web' ? 'web' : 'mobile';

      const response = await fetch(`${API_BASE_URL}/v1/auth/google`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform,
          code,
          redirect_uri: redirectUri,
          code_verifier: codeVerifier,
        }),
      });

      if (!response.ok) {
        // raw 응답 body는 PKCE/code echo 가능성으로 사용자 화면에 노출 금지 — status만.
        setError(`로그인에 실패했습니다 (${response.status})`);
        return;
      }

      const body = (await response.json()) as GoogleLoginResponseMobile;
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
  }, [request, promptAsync, setSession, nextPath]);

  return {
    signIn,
    isInProgress,
    error,
    isReady: request !== null && pickClientId() !== undefined,
  };
}
