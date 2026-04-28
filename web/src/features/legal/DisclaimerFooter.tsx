/**
 * 1줄 디스클레이머 푸터 — Web Server Component (Story 1.3 AC4 / FR11).
 *
 * 사용처:
 * - Web (public)/legal/disclaimer/page.tsx 풀텍스트 푸터
 * - Story 4.3 (Web 주간 리포트 차트) 분석 카드 푸터
 *
 * Tailwind v4 토큰 (text-xs / text-zinc-500). 텍스트는 컴포넌트 내부 const.
 */

const DISCLAIMER_TEXT = "건강 목표 부합도 점수 — 의학적 진단이 아닙니다.";

export default function DisclaimerFooter() {
  return (
    <p className="text-xs text-zinc-500 text-center mt-4">{DISCLAIMER_TEXT}</p>
  );
}
