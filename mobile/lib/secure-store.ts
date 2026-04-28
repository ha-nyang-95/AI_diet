/**
 * expo-secure-store 래퍼 — iOS Keychain / Android Keystore 기반 토큰 저장.
 *
 * 절대 사용 금지: AsyncStorage / MMKV (평문 저장 — NFR-S1 위반).
 * 옵션은 WHEN_UNLOCKED — WHEN_UNLOCKED_THIS_DEVICE_ONLY는 백업 복원 시 토큰 유실 → UX 저하.
 */
import * as SecureStore from 'expo-secure-store';

const ACCESS_KEY = 'bn_access';
const REFRESH_KEY = 'bn_refresh';

const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED,
};

export async function setAccessToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(ACCESS_KEY, token, OPTIONS);
}

export async function getAccessToken(): Promise<string | null> {
  return SecureStore.getItemAsync(ACCESS_KEY, OPTIONS);
}

export async function setRefreshToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(REFRESH_KEY, token, OPTIONS);
}

export async function getRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(REFRESH_KEY, OPTIONS);
}

export async function clearAuth(): Promise<void> {
  // allSettled — 한 키 삭제가 실패해도 나머지는 시도해 stale token 잔존 방지.
  await Promise.allSettled([
    SecureStore.deleteItemAsync(ACCESS_KEY, OPTIONS),
    SecureStore.deleteItemAsync(REFRESH_KEY, OPTIONS),
  ]);
}
