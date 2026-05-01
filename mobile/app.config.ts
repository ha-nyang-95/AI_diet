/**
 * Expo dynamic config — Gemini PR #19 review (medium): `app.json`의 reverse-client scheme을
 * 환경변수에서 동적 도출해 Google client id 변경 / 환경별 분리 시 수동 동기화 부담 제거.
 *
 * EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_ANDROID이 비어있으면 reverse scheme은 빈 배열로 — 빌드는
 * 깨지지 않고 OAuth만 미동작 (사용자가 Android client_id를 채우는 시점부터 활성). 이렇게 두
 * 면 dev/staging/prod 별 .env에서 client id만 바꿔도 prebuild 결과(AndroidManifest)가
 * 자동 정합 → "수동 hardcode 누락" 회귀 차단.
 */
import type { ConfigContext, ExpoConfig } from "expo/config";

const PRIMARY_SCHEME = "mobile";

function reverseGoogleClientScheme(clientId: string | undefined): string | null {
  if (!clientId) return null;
  return `com.googleusercontent.apps.${clientId.replace(
    /\.apps\.googleusercontent\.com$/,
    "",
  )}`;
}

export default ({ config }: ConfigContext): ExpoConfig => {
  const reverseScheme = reverseGoogleClientScheme(
    process.env.EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID_ANDROID,
  );
  // Linking primary는 reverse-client scheme — Google → 우리 앱 redirect 도달 후 Linking이
  // URL을 변환하지 않게 한다. 미설정 시 mobile만으로 fallback (OAuth만 미동작, 화면은 정상).
  const scheme = reverseScheme ? [reverseScheme, PRIMARY_SCHEME] : [PRIMARY_SCHEME];

  return {
    ...config,
    name: "mobile",
    slug: "mobile",
    version: "1.0.0",
    orientation: "portrait",
    icon: "./assets/images/icon.png",
    scheme,
    userInterfaceStyle: "automatic",
    newArchEnabled: true,
    ios: {
      supportsTablet: true,
      bundleIdentifier: "com.balancenote.app",
    },
    android: {
      package: "com.balancenote.app",
      adaptiveIcon: {
        backgroundColor: "#E6F4FE",
        foregroundImage: "./assets/images/android-icon-foreground.png",
        backgroundImage: "./assets/images/android-icon-background.png",
        monochromeImage: "./assets/images/android-icon-monochrome.png",
      },
      edgeToEdgeEnabled: true,
      predictiveBackGestureEnabled: false,
    },
    web: {
      output: "static",
      favicon: "./assets/images/favicon.png",
    },
    plugins: [
      "expo-router",
      [
        "expo-splash-screen",
        {
          image: "./assets/images/splash-icon.png",
          imageWidth: 200,
          resizeMode: "contain",
          backgroundColor: "#ffffff",
          dark: {
            backgroundColor: "#000000",
          },
        },
      ],
      "expo-secure-store",
      "expo-web-browser",
      [
        "expo-image-picker",
        {
          photosPermission:
            "BalanceNote가 식단 사진을 선택할 사진첩 접근 권한이 필요합니다.",
          cameraPermission:
            "BalanceNote가 식단 사진을 촬영할 카메라 접근 권한이 필요합니다.",
          microphonePermission: false,
        },
      ],
    ],
    experiments: {
      typedRoutes: true,
      reactCompiler: true,
    },
  };
};
