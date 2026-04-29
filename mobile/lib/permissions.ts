/**
 * Story 2.2 — 카메라 / 사진첩 권한 wrapper hooks.
 *
 * `expo-image-picker`의 표준 hooks(`useCameraPermissions` / `useMediaLibraryPermissions`)을
 * 1지점 wrap — (a) 향후 expo-permissions deprecation 대응 단순화, (b) 컴포넌트 테스트
 * 시 단일 모듈 모킹, (c) 권한 흐름 변경 시 단일 변경 지점.
 *
 * 권한 요청 시점은 *첫 사진 입력 시점*에 한정 — 앱 진입 시 prompt 금지(UX 표준 + iOS
 * App Store 정책 정합).
 *
 * iOS / Android 차이 (RN 표준 동작 — 본 wrapper는 status / canAskAgain 그대로 노출):
 * - iOS: 첫 prompt 후 *Don't Allow* 선택 → `canAskAgain=false` (사용자가 설정 앱에서
 *   직접 변경해야 함). prompt 호출은 즉시 denied 반환.
 * - Android (API 23+): runtime permission. 사용자가 *Don't Allow* → `canAskAgain=true`
 *   (다시 요청 가능). *Don't ask again* 체크 후 *Don't Allow*는 `canAskAgain=false`.
 * - 공통: `canAskAgain=false`이면 prompt가 의미 없음 → `Linking.openSettings()` deep
 *   link만 액션 가능 (`PermissionDeniedView` 처리).
 */

import * as ImagePicker from 'expo-image-picker';

export type PermissionStatus = 'granted' | 'denied' | 'undetermined';

export interface PermissionHookResult {
  /** 현재 권한 상태. `undetermined`면 prompt 미진행 상태. */
  status: PermissionStatus;
  /** prompt 호출. 사용자 응답 후 새 status 반환. */
  request: () => Promise<PermissionStatus>;
  /** false면 prompt 호출이 즉시 denied 반환 — `Linking.openSettings()` 유도. */
  canAskAgain: boolean;
}

function _normalizeStatus(status: ImagePicker.PermissionStatus): PermissionStatus {
  if (status === ImagePicker.PermissionStatus.GRANTED) return 'granted';
  if (status === ImagePicker.PermissionStatus.DENIED) return 'denied';
  return 'undetermined';
}

/**
 * 카메라 권한 hook — `expo-image-picker.useCameraPermissions` wrap.
 */
export function useCameraPermission(): PermissionHookResult {
  const [permission, requestPermission] = ImagePicker.useCameraPermissions();

  const request = async (): Promise<PermissionStatus> => {
    const result = await requestPermission();
    return _normalizeStatus(result.status);
  };

  return {
    status: permission ? _normalizeStatus(permission.status) : 'undetermined',
    request,
    canAskAgain: permission?.canAskAgain ?? true,
  };
}

/**
 * 사진첩 권한 hook — `expo-image-picker.useMediaLibraryPermissions` wrap.
 */
export function useMediaLibraryPermission(): PermissionHookResult {
  const [permission, requestPermission] = ImagePicker.useMediaLibraryPermissions();

  const request = async (): Promise<PermissionStatus> => {
    const result = await requestPermission();
    return _normalizeStatus(result.status);
  };

  return {
    status: permission ? _normalizeStatus(permission.status) : 'undetermined',
    request,
    canAskAgain: permission?.canAskAgain ?? true,
  };
}
