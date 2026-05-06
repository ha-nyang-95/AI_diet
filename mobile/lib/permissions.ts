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
import * as Notifications from 'expo-notifications';
import { useCallback, useEffect, useState } from 'react';

export type PermissionStatus = 'granted' | 'denied' | 'undetermined';

export interface PermissionHookResult {
  /** 현재 권한 상태. `undetermined`면 prompt 미진행 상태. */
  status: PermissionStatus;
  /** prompt 호출. 사용자 응답 후 새 status 반환. */
  request: () => Promise<PermissionStatus>;
  /** false면 prompt 호출이 즉시 denied 반환 — `Linking.openSettings()` 유도. */
  canAskAgain: boolean;
}

function _normalizeStatus(status: ImagePicker.PermissionStatus | string): PermissionStatus {
  // P18 — iOS 14+ Limited Photo Library Access를 granted로 매핑. expo-image-picker는
  // limited 모드에서도 picker가 정상 동작(사용자가 허용한 사진 부분집합 노출). enum에는
  // LIMITED가 없어 string 비교(`'limited'`)로 처리. denied로 매핑하면 사용자가 "다시 요청"
  // 버튼만 보이고 picker는 영원히 사용 불가 → UX stuck. granted 매핑이 expo의 의도.
  //
  // Story 4.1 — iOS `'provisional'` 상태(조용한 알림 자동 허용)도 `'granted'`로 매핑
  // (PRD M4 정합 — 권한 거부와 동치 X). expo-notifications status에서만 발생 (Android는
  // `'provisional'` 미존재 — 통과).
  if (status === 'granted' || status === 'limited' || status === 'provisional') return 'granted';
  if (status === 'denied') return 'denied';
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
    // P17 — permission이 null(hook 미해결 첫 frame)이면 status='undetermined' + canAskAgain=true.
    // 이 상태로 `request()` 호출 시 expo-image-picker가 내부적으로 첫 권한 fetch를 강제하므로
    // 안전(race window 0). 'undetermined' 매핑은 *첫 prompt 미진행 상태*와 동일 시맨틱.
    status: permission == null ? 'undetermined' : _normalizeStatus(permission.status),
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
    // P17 — permission이 null(hook 미해결 첫 frame)이면 status='undetermined' + canAskAgain=true.
    // 이 상태로 `request()` 호출 시 expo-image-picker가 내부적으로 첫 권한 fetch를 강제하므로
    // 안전(race window 0). 'undetermined' 매핑은 *첫 prompt 미진행 상태*와 동일 시맨틱.
    status: permission == null ? 'undetermined' : _normalizeStatus(permission.status),
    request,
    canAskAgain: permission?.canAskAgain ?? true,
  };
}

/**
 * Story 4.1 — 알림 권한 hook. `expo-notifications`의 `getPermissionsAsync` /
 * `requestPermissionsAsync` wrap.
 *
 * iOS 분기:
 * - 첫 prompt에서 `requestPermissionsAsync({ ios: { allowAlert, allowBadge, allowSound } })`
 *   호출 — critical alert 미요청 (App Store 정책 정합 PRD M6).
 * - `'provisional'` 상태(조용한 알림 자동 허용)는 `_normalizeStatus`가 `'granted'`로 매핑.
 * - 첫 prompt 후 거부 시 `canAskAgain=false` → `Linking.openSettings()`만 액션 가능.
 *
 * Android 분기:
 * - API 33+ (POST_NOTIFICATIONS runtime permission) — 동일 흐름.
 * - `'provisional'` 미존재 — 분기 무영향.
 */
export function useNotificationPermission(): PermissionHookResult {
  const [permission, setPermission] = useState<Notifications.NotificationPermissionsStatus | null>(
    null,
  );

  // 마운트 시 1회 status fetch. Story 2.2 패턴 (image-picker는 hook 자체가 fetch — 본
  // hook은 expo-notifications의 raw API를 wrap이라 mount effect로 1차 fetch).
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const result = await Notifications.getPermissionsAsync();
        if (!cancelled) setPermission(result);
      } catch {
        // graceful — null 상태 유지 (status='undetermined' 매핑).
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const request = useCallback(async (): Promise<PermissionStatus> => {
    try {
      const result = await Notifications.requestPermissionsAsync({
        ios: { allowAlert: true, allowBadge: true, allowSound: true },
      });
      setPermission(result);
      return _normalizeStatus(result.status);
    } catch {
      return 'undetermined';
    }
  }, []);

  return {
    status: permission == null ? 'undetermined' : _normalizeStatus(permission.status),
    request,
    canAskAgain: permission?.canAskAgain ?? true,
  };
}
