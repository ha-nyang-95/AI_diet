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

export async function getTutorialSeen(): Promise<boolean> {
  const value = await AsyncStorage.getItem(TUTORIAL_SEEN_KEY);
  return value === SEEN_VALUE;
}

export async function setTutorialSeen(value: true): Promise<void> {
  // 인자는 ``true`` 리터럴 — false 저장은 ``clearOnboardingState()``로 일원화.
  void value;
  await AsyncStorage.setItem(TUTORIAL_SEEN_KEY, SEEN_VALUE);
}

export async function clearOnboardingState(): Promise<void> {
  await AsyncStorage.removeItem(TUTORIAL_SEEN_KEY);
}
