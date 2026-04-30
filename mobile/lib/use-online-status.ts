/**
 * Story 2.4 — `@react-native-community/netinfo` subscription helper (AC6).
 *
 * 오프라인 detection 단일 지점. 호출 측은 ``isOnline``/``isInternetReachable`` 두
 * 플래그 활용 — 일별 기록 화면 *"오프라인 — 마지막 7일 기록 표시 중"* 배너 분기 등.
 *
 * ``isInternetReachable``은 일부 플랫폼에서 ``null``일 수 있음(미초기화 상태) — 호출 측이
 * ``false`` 명시적 체크로 사용.
 *
 * CR P6 — 콜드 부팅 시점 false positive online 차단 — `NetInfo.fetch()` 1회 동기화 후
 * `addEventListener`로 후속 변경 구독. 첫 이벤트 전(수백 ms ~ 수 초) "비행기 모드"가
 * "온라인"으로 표시되는 회귀 차단.
 */
import NetInfo, { type NetInfoState } from '@react-native-community/netinfo';
import { useEffect, useState } from 'react';

export interface OnlineStatus {
  isOnline: boolean;
  isInternetReachable: boolean | null;
}

function _stateToStatus(state: NetInfoState): OnlineStatus {
  // `isConnected`/`isInternetReachable` 초기 `null`은 *unknown* — 첫 fetch 결과 도착 전
  // 깜빡임 차단을 위해 unknown은 online으로 가정 (`!== false`). 명시적 false만 offline.
  return {
    isOnline: state.isConnected !== false,
    isInternetReachable: state.isInternetReachable,
  };
}

export function useOnlineStatus(): OnlineStatus {
  const [status, setStatus] = useState<OnlineStatus>({
    isOnline: true,
    isInternetReachable: null,
  });

  useEffect(() => {
    let isCancelled = false;
    // CR P6 — 콜드 부팅 시점 동기 fetch로 초기 상태 sync (이벤트 emit 전 false positive 차단).
    void NetInfo.fetch().then((state) => {
      if (!isCancelled) setStatus(_stateToStatus(state));
    });
    const unsubscribe = NetInfo.addEventListener((state) => {
      setStatus(_stateToStatus(state));
    });
    return () => {
      isCancelled = true;
      unsubscribe();
    };
  }, []);

  return status;
}
