/**
 * Story 3.7 — `ChatStreaming` 모바일 SSE 채팅 UI (AC9 / AC11 / AC12).
 *
 * 흐름(phase):
 * - `connecting` / `streaming` / `polling` — 본문 누적 + 진행 안내(ActivityIndicator).
 * - `clarify` — chip 리스트 노출(state.clarificationOptions.map → Pressable).
 * - `done` — 본문 + FitScoreBadge + MacroCard(접힘) + DisclaimerFooter.
 * - `error` — 안내 메시지 + Retry 버튼(reset() 호출).
 *
 * NFR:
 * - NFR-UX1 — Coaching 톤 본문 우선(state.text). 매크로는 접힘 보조 카드(MacroCard).
 * - NFR-UX3 — 단순 g/kcal는 본문이 아닌 데이터 카드.
 * - NFR-A3 — 폰트 스케일 200% 대응(flexShrink + lineHeight 명시).
 * - NFR-S5 — meal_id만 raw, 본문 raw 출력 X(structlog 등가 console 가드).
 * - NFR-R4 — 오프라인 시 컴포넌트 진입 자체 차단(부모 책임).
 *
 * FR11 — DisclaimerFooter는 *분석 결과 카드*에만 노출(`done` phase). clarify/error에는 X.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import DisclaimerFooter from '@/features/legal/DisclaimerFooter';

import MacroCard from './MacroCard';
import { useMealAnalysisStream } from './useMealAnalysisStream';
import type { FitScoreLabel } from './mealSchema';

interface ChatStreamingProps {
  mealId: string;
  isOnline: boolean;
  onAnalysisDone?: () => void;
}

const FIT_SCORE_COLORS: Record<FitScoreLabel, string> = {
  allergen_violation: '#d93025',
  low: '#e98000',
  moderate: '#f5b400',
  good: '#34a853',
  excellent: '#1a73e8',
};

const FIT_SCORE_LABELS_KO: Record<FitScoreLabel, string> = {
  allergen_violation: '알레르기 위반',
  low: '부족',
  moderate: '보통',
  good: '양호',
  excellent: '우수',
};

export default function ChatStreaming({
  mealId,
  isOnline,
  onAnalysisDone,
}: ChatStreamingProps): React.ReactElement {
  const { state, reset, submitClarification } = useMealAnalysisStream(mealId);
  const scrollRef = useRef<ScrollView | null>(null);
  const doneNotifiedRef = useRef<boolean>(false);
  // CR Wave 1 #22 — clarify chip 다중 탭 race 차단(첫 탭 즉시 다른 chip disable).
  const [clarifySubmitting, setClarifySubmitting] = useState(false);

  // done 진입 시 부모 invalidate callback 1회 호출.
  useEffect(() => {
    if (state.phase === 'done' && !doneNotifiedRef.current) {
      doneNotifiedRef.current = true;
      onAnalysisDone?.();
    }
  }, [state.phase, onAnalysisDone]);

  // 본문 갱신 시 자동 bottom scroll.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollToEnd({ animated: true });
    }
  }, [state.text, state.phase]);

  // CR Wave 1 #22 — phase가 clarify에서 벗어나면 submitting flag 초기화(re-clarify 가능).
  useEffect(() => {
    if (state.phase !== 'clarify') {
      setClarifySubmitting(false);
    }
  }, [state.phase]);

  // CR Wave 1 #21 — Retry 시 doneNotifiedRef 초기화(다음 done 시 부모 invalidate 재호출).
  const handleRetry = useCallback(() => {
    doneNotifiedRef.current = false;
    reset();
  }, [reset]);

  const handleClarify = useCallback(
    (value: string) => {
      if (clarifySubmitting) return;
      setClarifySubmitting(true);
      void submitClarification(value);
    },
    [clarifySubmitting, submitClarification],
  );

  if (!isOnline) {
    // NFR-R4 — 오프라인 시 진입 차단(부모가 가드, 본 fallback은 defensive).
    return (
      <View style={styles.offlineBlock}>
        <Text style={styles.offlineText}>오프라인 — 온라인 시 분석 가능</Text>
      </View>
    );
  }

  return (
    <ScrollView
      ref={scrollRef}
      onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}
      style={styles.container}
      contentContainerStyle={styles.content}
      accessibilityLabel="AI 분석 채팅"
    >
      {/* 본문 텍스트 — token 누적 stream */}
      {state.text ? (
        <View style={styles.bodyBlock}>
          <Text style={styles.bodyText}>{state.text}</Text>
        </View>
      ) : null}

      {/* 진행 중 안내 */}
      {(state.phase === 'connecting' ||
        state.phase === 'streaming' ||
        state.phase === 'polling') ? (
        <View style={styles.progressBlock}>
          <ActivityIndicator />
          <Text style={styles.progressText}>
            {state.mode === 'polling' ? 'AI 분석 중… (재연결)' : 'AI 분석 중…'}
          </Text>
        </View>
      ) : null}

      {/* clarify chips */}
      {state.phase === 'clarify' && state.clarificationOptions.length > 0 ? (
        <View style={styles.clarifyBlock}>
          <Text style={styles.clarifyTitle}>어떤 음식인가요?</Text>
          {state.clarificationOptions.map((opt) => (
            <Pressable
              key={opt.value}
              accessibilityRole="button"
              accessibilityLabel={opt.label}
              accessibilityState={{ disabled: clarifySubmitting }}
              disabled={clarifySubmitting}
              onPress={() => handleClarify(opt.value)}
              style={[styles.chip, clarifySubmitting && styles.chipDisabled]}
            >
              <Text style={styles.chipText}>{opt.label}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      {/* done 결과 카드 */}
      {state.phase === 'done' && state.result ? (
        <View style={styles.doneBlock}>
          <View
            style={[
              styles.fitScoreBadge,
              {
                backgroundColor:
                  FIT_SCORE_COLORS[state.result.fit_score_label] ?? '#888',
              },
            ]}
          >
            <Text style={styles.fitScoreNumber}>{state.result.final_fit_score}</Text>
            <Text style={styles.fitScoreLabel}>
              {FIT_SCORE_LABELS_KO[state.result.fit_score_label] ?? '점수'}
            </Text>
          </View>
          <MacroCard macros={state.result.macros} />
          <DisclaimerFooter />
        </View>
      ) : null}

      {/* error 분기 */}
      {state.phase === 'error' ? (
        <View style={styles.errorBlock}>
          <Text style={styles.errorText}>분석에 실패했어요 — 다시 시도</Text>
          {state.error?.detail ? (
            <Text style={styles.errorDetail}>{state.error.detail}</Text>
          ) : null}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="다시 시도"
            onPress={handleRetry}
            style={styles.retryButton}
          >
            <Text style={styles.retryButtonText}>다시 시도</Text>
          </Pressable>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    padding: 16,
    gap: 12,
  },
  bodyBlock: {
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#e0e0e0',
    padding: 16,
  },
  bodyText: {
    fontSize: 15,
    color: '#222',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 22,
  },
  progressBlock: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  progressText: {
    fontSize: 14,
    color: '#666',
    flexShrink: 1,
    lineHeight: 20,
  },
  clarifyBlock: {
    gap: 8,
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#e0e0e0',
    padding: 16,
  },
  clarifyTitle: {
    fontSize: 14,
    color: '#666',
    fontWeight: '700',
    lineHeight: 20,
  },
  chip: {
    backgroundColor: '#f0f7ff',
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: '#bcd4f5',
  },
  chipDisabled: {
    opacity: 0.5,
  },
  chipText: {
    fontSize: 15,
    color: '#1a73e8',
    fontWeight: '600',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 22,
  },
  doneBlock: {
    gap: 12,
  },
  fitScoreBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 14,
    gap: 8,
    alignSelf: 'flex-start',
    flexShrink: 1,
    flexWrap: 'wrap',
  },
  fitScoreNumber: {
    fontSize: 16,
    fontWeight: '700',
    color: '#fff',
    lineHeight: 20,
  },
  fitScoreLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#fff',
    lineHeight: 20,
  },
  errorBlock: {
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#f5cdc7',
    padding: 16,
    gap: 8,
  },
  errorText: {
    fontSize: 16,
    color: '#d93025',
    fontWeight: '600',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 22,
  },
  errorDetail: {
    fontSize: 13,
    color: '#666',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 18,
  },
  retryButton: {
    backgroundColor: '#1a73e8',
    borderRadius: 8,
    paddingHorizontal: 20,
    paddingVertical: 12,
    alignItems: 'center',
  },
  retryButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
    lineHeight: 22,
  },
  offlineBlock: {
    backgroundColor: '#f0f0f0',
    borderRadius: 8,
    padding: 16,
    margin: 16,
  },
  offlineText: {
    fontSize: 14,
    color: '#888',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 20,
  },
});
