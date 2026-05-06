/**
 * Story 4.1 — Expo push 알림 token 등록·해제 + Android 채널 + AsyncStorage 캐시.
 *
 * 4 export:
 * - `registerForPushNotificationsAsync()` — token 발급 흐름 (simulator/granted/denied/
 *   projectId 누락 graceful).
 * - `unregisterPushTokenAsync()` — AsyncStorage clear + 백엔드 DELETE /v1/notifications/devices.
 * - `setupNotificationTapListener(callback)` — push tap 응답 listener 등록 (Story 4.2 deep
 *   link wire forward — 본 스토리는 골격만).
 * - `getLastNotificationResponse()` — cold start 시 push tap 진입 검증 (Story 4.2 forward).
 *
 * **Expo Go 한계 (SDK 53+)**: remote push token 발급 불가 → `Constants.appOwnership === 'expo'`
 * 분기 시 token 발급 skip + console.warn. EAS dev build / standalone에서만 실 token. 자세한
 * SOP는 docs/runbook/push-notifications-dev.md.
 *
 * **graceful 분기**: token 발급 실패(network / projectId 누락 / OS API 거부) 시 throw X —
 * `{ status, token: null }` return + console.warn. 모바일 UI는 *"알림 등록 실패 — 잠시 후
 * 다시 시도"* 분기 (자동 retry는 Story 8.4 polish forward).
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { authFetch } from './auth';

// AsyncStorage key — token 중복 register 회피 + signOut clear 시 일괄 wipe.
const PUSH_TOKEN_STORAGE_KEY = '@balancenote/push_token';

// Story 4.1 AC12 — first-time prompt flag (Story 1.6 `tutorial-seen` 패턴 정합).
// CR P4 — `(tabs)/_layout.tsx` + `auth.tsx` 양 callsite의 SOT를 본 모듈로 통합 — key 변경
// 시 한 곳만 수정하면 prompt suppression 정합 유지.
export const PUSH_PROMPTED_STORAGE_KEY = '@balancenote/push_prompted';

const ANDROID_CHANNEL_ID = 'default';

export type PermissionStatus = Notifications.PermissionStatus;

/** 백엔드 `POST /v1/notifications/devices` body의 `platform` Literal 정합. */
export type DevicePlatform = 'ios' | 'android' | 'web';

/**
 * 현 OS를 백엔드 `platform` Literal로 변환.
 *
 * CR P2 — 기존 코드는 `platform: 'ios'` 하드코드라 Android/Web 사용자도 모두 iOS로
 * 등록되어 백엔드 수신 데이터 오염. `Platform.OS`는 ``ios | android | web | windows |
 * macos`` 이지만 backend Literal은 3종 — windows/macos는 모바일 push 미지원이므로 web
 * 으로 폴백.
 */
export function resolveDevicePlatform(): DevicePlatform {
  if (Platform.OS === 'android') return 'android';
  if (Platform.OS === 'ios') return 'ios';
  return 'web';
}

export interface RegisterResult {
  /** OS 권한 상태 — 모바일 UI가 'denied' 시 PermissionDeniedView 노출. */
  status: PermissionStatus;
  /** Expo push token. simulator / projectId 누락 / 권한 거부 시 null. */
  token: string | null;
}

let _channelInitialized = false;

async function _ensureAndroidChannel(): Promise<void> {
  if (Platform.OS !== 'android') return;
  if (_channelInitialized) return;
  try {
    await Notifications.setNotificationChannelAsync(ANDROID_CHANNEL_ID, {
      name: '미기록 알림',
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: '#0a7ea4',
    });
    _channelInitialized = true;
  } catch (error) {
    console.warn('push.android_channel.setup_failed', error);
  }
}

function _resolveProjectId(): string | null {
  // EAS Build 시점 자동 주입 — `expo.extra.eas.projectId` 또는 `easConfig.projectId`.
  // dev에서는 EAS Console에서 발급한 projectId를 app.config.ts에 명시(현재는 미설정 —
  // dev runbook 참조).
  const fromExpoConfig =
    (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas
      ?.projectId ?? null;
  const fromEasConfig =
    (Constants as unknown as { easConfig?: { projectId?: string } }).easConfig
      ?.projectId ?? null;
  return fromExpoConfig ?? fromEasConfig ?? null;
}

/**
 * push token 등록 흐름 — graceful (절대 throw X).
 *
 * 1. simulator / web → `{ status: 'granted', token: null }` 즉시 return.
 * 2. Android 채널 setup.
 * 3. 권한 status 확인 → `'undetermined'`이면 prompt, `'denied'`이면 `{ status: 'denied',
 *    token: null }` return (UI는 PermissionDeniedView).
 * 4. Expo Go(SDK 53+) → token 발급 skip + warn (EAS dev build에서만 실 token).
 * 5. projectId 추출 → 없으면 warn + `{ status: 'granted', token: null }`.
 * 6. `Notifications.getExpoPushTokenAsync({ projectId })` 호출.
 * 7. AsyncStorage 캐시 + return.
 */
export async function registerForPushNotificationsAsync(): Promise<RegisterResult> {
  // (1) simulator / web — Expo push token API는 physical device only.
  if (!Device.isDevice) {
    return { status: Notifications.PermissionStatus.GRANTED, token: null };
  }

  // (2) Android 채널 — 권한 prompt 전에 채널 register 권장 (channel 부재 시 첫 알림 silent).
  await _ensureAndroidChannel();

  // (3) 권한 status.
  const existing = await Notifications.getPermissionsAsync();
  let status: PermissionStatus = existing.status;
  if (status === Notifications.PermissionStatus.UNDETERMINED) {
    const requested = await Notifications.requestPermissionsAsync({
      ios: { allowAlert: true, allowBadge: true, allowSound: true },
    });
    status = requested.status;
  }
  if (status !== Notifications.PermissionStatus.GRANTED) {
    return { status, token: null };
  }

  // (4) Expo Go (SDK 53+) — remote push token 발급 불가.
  if (Constants.appOwnership === 'expo') {
    console.warn(
      'push.expo_go_skip',
      'Expo Go does not support remote push tokens (SDK 53+). Use EAS dev build.',
    );
    return { status, token: null };
  }

  // (5) projectId 추출.
  const projectId = _resolveProjectId();
  if (!projectId) {
    console.warn(
      'push.project_id_missing',
      'EXPO_PUBLIC_EAS_PROJECT_ID 환경변수 또는 EAS Console projectId 필요.',
    );
    return { status, token: null };
  }

  // (6) Expo push token 발급.
  try {
    const result = await Notifications.getExpoPushTokenAsync({ projectId });
    const token = result.data;
    // (7) AsyncStorage 캐시 (best-effort — 실패해도 token 자체는 반환).
    try {
      await AsyncStorage.setItem(PUSH_TOKEN_STORAGE_KEY, token);
    } catch (storageError) {
      console.warn('push.cache.failed', storageError);
    }
    return { status, token };
  } catch (error) {
    console.warn('push.token.fetch_failed', error);
    return { status, token: null };
  }
}

/**
 * token 해제 — AsyncStorage clear + 백엔드 DELETE /v1/notifications/devices.
 *
 * graceful: 백엔드 호출 실패해도 AsyncStorage clear는 무조건 진행 (사용자 logout 의도 보존).
 * Story 4.1 AC13 — signOut flow에서 호출.
 */
export async function unregisterPushTokenAsync(): Promise<void> {
  try {
    await AsyncStorage.removeItem(PUSH_TOKEN_STORAGE_KEY);
  } catch (error) {
    console.warn('push.cache.clear_failed', error);
  }
  try {
    await authFetch('/v1/notifications/devices', { method: 'DELETE' });
  } catch (error) {
    console.warn('push.revoke.network_failed', error);
  }
}

/**
 * push tap 응답 listener 등록 — return 함수로 unsubscribe.
 *
 * Story 4.2가 deep link wire(`(tabs)/meals/input` redirect 등) — 본 스토리는 listener
 * 골격만 노출. 호출 측이 useEffect cleanup으로 unsubscribe.
 */
export function setupNotificationTapListener(
  callback: (response: Notifications.NotificationResponse) => void,
): () => void {
  const subscription = Notifications.addNotificationResponseReceivedListener(callback);
  return () => subscription.remove();
}

/**
 * cold start 시 push tap 진입 검증 — `getLastNotificationResponse()` thin wrap.
 *
 * Story 4.2가 사용 — 본 스토리는 골격만 노출.
 */
export function getLastNotificationResponse():
  | Notifications.NotificationResponse
  | null {
  return Notifications.getLastNotificationResponse() ?? null;
}
