/**
 * Onboarding tutorial seen flag — AsyncStorage 단일 boolean (Story 1.6 AC2).
 *
 * 비-민감 client preference 전용 — 토큰은 ``secure-store.ts`` 책임 분리 정합
 * (``secure-store.ts:4`` "AsyncStorage / MMKV 평문 저장 금지" 주석은 NFR-S1 토큰
 * 보호 context에 한정). tutorial-seen은 boolean 표시 하나 → 평문 저장 적합.
 *
 * 키 ``bn:onboarding-tutorial-seen``: 프로젝트 namespace prefix(``bn:``) + 도메인
 * (``onboarding``) + 화면명(``tutorial``) + 의미(``seen``). user_id 별 분리 X —
 * 단일 디바이스 1 사용자 가정 + ``signOut`` 시 ``clearOnboardingState()`` 호출로
 * 격리(AC8 — 사용자 A 로그아웃 후 B 로그인 시 A의 seen 잔존이 B에게 전파 차단).
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

const TUTORIAL_SEEN_KEY = 'bn:onboarding-tutorial-seen';
const SEEN_VALUE = '1';

// AsyncStorage 실패는 정보 제공 화면 UX보다 결코 critical하지 않음. read 실패 시 false
// 반환(슬라이드 한 번 더 노출 — 사용자 영향 무 vs spinner 영구 정지의 차이) + write 실패는
// caller가 navigation을 우선 진행하도록 swallow. 토큰 store(secure-store.ts) 와 책임 분리.
export async function getTutorialSeen(): Promise<boolean> {
  try {
    const value = await AsyncStorage.getItem(TUTORIAL_SEEN_KEY);
    return value === SEEN_VALUE;
  } catch {
    return false;
  }
}

export async function setTutorialSeen(): Promise<void> {
  try {
    await AsyncStorage.setItem(TUTORIAL_SEEN_KEY, SEEN_VALUE);
  } catch {
    // swallow — 다음 진입 시 슬라이드 1회 더 노출에 그침. caller 내비 진행 보장.
  }
}

export async function clearOnboardingState(): Promise<void> {
  try {
    await AsyncStorage.removeItem(TUTORIAL_SEEN_KEY);
  } catch {
    // swallow — signOut 흐름에서 토큰 clear / 라우팅이 차단되면 안 됨.
  }
}
