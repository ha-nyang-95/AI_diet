/**
 * 1줄 디스클레이머 푸터 (Story 1.3 AC4 / FR11).
 *
 * 사용처:
 * - 모바일 (tabs)/settings/disclaimer.tsx 풀텍스트 화면 푸터
 * - Story 3.7 (모바일 SSE 채팅 UI) 분석 응답 카드 푸터
 *
 * 텍스트는 컴포넌트 내부 const — 국제화 dictionary 분리는 NFR-L1 한국어 1차 정합으로
 * deferred(Epic 8 polish).
 */
import { StyleSheet, Text } from 'react-native';

const DISCLAIMER_TEXT = '건강 목표 부합도 점수 — 의학적 진단이 아닙니다.';

export default function DisclaimerFooter() {
  return <Text style={styles.text}>{DISCLAIMER_TEXT}</Text>;
}

const styles = StyleSheet.create({
  text: {
    fontSize: 12,
    color: '#666',
    textAlign: 'center',
    marginTop: 16,
  },
});
