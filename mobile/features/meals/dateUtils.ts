/**
 * Story 2.4 — KST 일자 헬퍼 (AC8). 날짜 picker + selectedDate state 정합 단일 지점.
 *
 * 모든 헬퍼는 `Asia/Seoul` TZ 강제 — 디바이스 로컬 TZ(LA/도쿄 출장 등) 의존 0.
 * `Intl.DateTimeFormat` (RN Hermes 표준 — Expo SDK 54+) 사용 — dayjs/date-fns 회피
 * (번들 사이즈 ↓).
 *
 * 다국가 지원은 Growth NFR-L4 — 본 스토리는 NFR-L2 한국어 1차 강제(D1 결정).
 */

const KST_TIME_ZONE = 'Asia/Seoul';

const _enCAFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: KST_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

const _koMonthDayFormatter = new Intl.DateTimeFormat('ko-KR', {
  timeZone: KST_TIME_ZONE,
  month: 'long',
  day: 'numeric',
});

/**
 * 현재 KST 시각의 자정 boundary `YYYY-MM-DD`를 반환.
 *
 * `en-CA` 로케일은 `YYYY-MM-DD` 포맷을 보장 (ISO 8601 호환). RN Hermes 정합.
 */
export function todayKst(): string {
  return _enCAFormatter.format(new Date());
}

/**
 * `YYYY-MM-DD` (KST 일자) + delta일을 더한 KST 일자 반환.
 *
 * KST 자정 boundary를 명시 ISO 문자열(`T00:00:00+09:00`)로 만들어 그 시점 기준으로
 * 일자 계산 — UTC offset 영향 0.
 */
export function addDays(date: string, delta: number): string {
  const base = new Date(`${date}T00:00:00+09:00`);
  base.setUTCDate(base.getUTCDate() + delta);
  return _enCAFormatter.format(base);
}

/**
 * `YYYY-MM-DD` (KST 일자) → 한국어 `"4월 30일"` 변환. 헤더 title용.
 */
export function formatDateKo(date: string): string {
  return _koMonthDayFormatter.format(new Date(`${date}T00:00:00+09:00`));
}

/**
 * `date`가 오늘(KST)인지 — 헤더 "오늘로 이동" 버튼 노출 분기에 활용.
 */
export function isToday(date: string): boolean {
  return date === todayKst();
}

/**
 * CR P11 — `meal.ate_at`(ISO 8601 with offset) → KST 자정 boundary 기준 `YYYY-MM-DD`.
 *
 * 7일 윈도우 fetch + selectedDate별 client-side filter에 사용. 백엔드 wire는 항상
 * `+09:00`/`Z` suffix 가정 — naive 입력은 디바이스 로컬 TZ로 해석되니 contract 신뢰.
 */
export function isoToKstDate(isoString: string): string {
  return _enCAFormatter.format(new Date(isoString));
}
