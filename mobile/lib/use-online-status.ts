/**
 * Story 2.4 — `@react-native-community/netinfo` subscription helper (AC6).
 *
 * 오프라인 detection 단일 지점. 호출 측은 ``isOnline``/``isInternetReachable`` 두
 * 플래그 활용 — 일별 기록 화면 *"오프라인 — 마지막 7일 기록 표시 중"* 배너 분기 등.
 *
 * ``isInternetReachable``은 일부 플랫폼에서 ``null``일 수 있음(미초기화 상태) — 호출 측이
 * ``false`` 명시적 체크로 사용.
 */
import NetInfo from '@react-native-community/netinfo';
import { useEffect, useState } from 'react';

export interface OnlineStatus {
  isOnline: boolean;
  isInternetReachable: boolean | null;
}

export function useOnlineStatus(): OnlineStatus {
  const [status, setStatus] = useState<OnlineStatus>({
    isOnline: true,
    isInternetReachable: null,
  });

  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener((state) => {
      setStatus({
        isOnline: state.isConnected === true,
        isInternetReachable: state.isInternetReachable,
      });
    });
    return unsubscribe;
  }, []);

  return status;
}
