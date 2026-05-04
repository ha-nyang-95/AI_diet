/**
 * Story 2.4 — 식단 상세 placeholder 페이지 (AC5).
 *
 * Story 3.7 SSE 채팅 진입점 prep. 본 baseline은:
 * - 7일 캐시 client-side filter — 단건 endpoint 도입 회피 (yagni).
 * - meal 정보 (시간 / raw_text / 사진 / parsed_items) 풀 텍스트 표시.
 * - `analysis_summary === null` 시 "AI 분석은 Epic 3 통합 후 표시됩니다" placeholder.
 * - "AI에게 질문하기" CTA는 disabled — Story 3.7가 SSE wire 시점에 활성화.
 * - 액션 버튼: 수정 / 삭제 (long-press ActionSheet과 같은 동작 — destructive 표시).
 */
import { Image } from 'expo-image';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useQueryClient } from '@tanstack/react-query';

import ChatStreaming from '@/features/meals/ChatStreaming';
import { addDays, todayKst } from '@/features/meals/dateUtils';
import {
  MealSubmitError,
  useDeleteMealMutation,
  useMealsQuery,
} from '@/features/meals/api';
import type {
  FitScoreLabel,
  MealMacros,
  MealResponse,
} from '@/features/meals/mealSchema';
import { useOnlineStatus } from '@/lib/use-online-status';

const UUID_PATTERN = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

const _hhmmKstFormatter = new Intl.DateTimeFormat('ko-KR', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'Asia/Seoul',
});

function formatHHmm(isoString: string): string {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return '';
  const parts = _hhmmKstFormatter.formatToParts(date);
  const hour = parts.find((p) => p.type === 'hour')?.value ?? '00';
  const minute = parts.find((p) => p.type === 'minute')?.value ?? '00';
  return `${hour}:${minute}`;
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

function MacrosBlock({ macros }: { macros: MealMacros }) {
  const { carbohydrate_g, protein_g, fat_g, energy_kcal } = macros;
  const allZero =
    carbohydrate_g === 0 && protein_g === 0 && fat_g === 0 && energy_kcal === 0;
  return (
    <View style={styles.detailBlock}>
      <Text style={styles.sectionTitle}>매크로</Text>
      {allZero ? (
        <Text style={styles.bodyText}>매크로 정보 없음</Text>
      ) : (
        <Text style={styles.bodyText}>{`탄 ${carbohydrate_g}g · 단 ${protein_g}g · 지 ${fat_g}g · ${energy_kcal} kcal`}</Text>
      )}
    </View>
  );
}

export default function MealDetailScreen() {
  const params = useLocalSearchParams<{ meal_id: string }>();
  const mealId = params.meal_id;
  const isValidUuid = typeof mealId === 'string' && UUID_PATTERN.test(mealId);

  const queryClient = useQueryClient();
  const deleteMutation = useDeleteMealMutation();
  // CR Gemini #3 (MEDIUM) — NFR-R4 read-only 정합: 오프라인 시 수정/삭제 차단.
  // index.tsx와 동일 hook 재사용으로 disable 분기 일관성.
  const { isOnline, isInternetReachable } = useOnlineStatus();
  const isOffline = !isOnline || isInternetReachable === false;
  // Story 3.7 — "AI 분석 시작" CTA → ChatStreaming 마운트 trigger. 한 번 시작하면
  // unmount되어도 redo는 reset()이 책임(`<ChatStreaming/>` 내부 hook).
  const [analysisStarted, setAnalysisStarted] = useState<boolean>(false);

  // 7일 윈도우 fetch + client-side filter (단건 endpoint 도입 회피 — yagni).
  // CR Gemini #2 (HIGH) — useMemo([])로 1회 고정 시 자정 cross stale + 내일 catch-up
  // 식단 누락. 매 렌더 직접 계산 + to_date를 *내일까지* 확장 (index.tsx와 정합).
  const today = todayKst();
  const sevenDaysAgo = addDays(today, -7);
  const tomorrow = addDays(today, 1);
  const { data, isPending, isError, refetch } = useMealsQuery({
    from_date: sevenDaysAgo,
    to_date: tomorrow,
  });

  const meal: MealResponse | undefined = useMemo(
    () => (isValidUuid ? data?.meals.find((m) => m.id === mealId) : undefined),
    [data?.meals, isValidUuid, mealId],
  );

  const handleEdit = useCallback(() => {
    if (!meal) return;
    // CR Gemini #3 — 오프라인 시 read-only (NFR-R4 정합 + index ActionSheet과 동일 흐름).
    if (isOffline) {
      Alert.alert('오프라인', '온라인 시 가능합니다.');
      return;
    }
    const target = `/(tabs)/meals/input?meal_id=${meal.id}` as Parameters<
      typeof router.push
    >[0];
    router.push(target);
  }, [meal, isOffline]);

  const handleDeleteConfirmed = useCallback(() => {
    if (!meal || deleteMutation.isPending) return;
    deleteMutation.mutate(meal.id, {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: ['meals'] });
        router.back();
      },
      onError: (err: unknown) => {
        // 404 race — 이미 삭제된 상태 → 사용자 시점 성공 동등.
        if (
          err instanceof MealSubmitError &&
          err.status === 404 &&
          err.code === 'meals.not_found'
        ) {
          void queryClient.invalidateQueries({ queryKey: ['meals'] });
          router.back();
          return;
        }
        const message =
          err instanceof MealSubmitError
            ? `삭제 실패 — ${err.detail ?? `(${err.status})`}`
            : '삭제 실패 — 다시 시도해주세요';
        Alert.alert('식단 삭제', message);
      },
    });
  }, [deleteMutation, meal, queryClient]);

  const handleDelete = useCallback(() => {
    if (!meal) return;
    // CR Gemini #3 — 오프라인 차단 (NFR-R4).
    if (isOffline) {
      Alert.alert('오프라인', '온라인 시 가능합니다.');
      return;
    }
    Alert.alert(
      '식단 삭제',
      '이 식단을 삭제하시겠습니까?',
      [
        { text: '취소', style: 'cancel' },
        { text: '삭제', style: 'destructive', onPress: handleDeleteConfirmed },
      ],
      { cancelable: true },
    );
  }, [handleDeleteConfirmed, meal, isOffline]);

  // 1) 잘못된 UUID — 즉시 에러 화면.
  if (!isValidUuid) {
    return (
      <View style={styles.centered}>
        <Stack.Screen options={{ title: '식단 상세' }} />
        <Text style={styles.errorTitle}>잘못된 접근입니다</Text>
        <Pressable
          onPress={() => router.replace('/(tabs)/meals')}
          accessibilityRole="button"
          accessibilityLabel="이전으로"
          style={styles.actionButton}
        >
          <Text style={styles.actionButtonText}>이전으로</Text>
        </Pressable>
      </View>
    );
  }

  if (isPending) {
    return (
      <View style={styles.centered}>
        <Stack.Screen options={{ title: '식단 상세' }} />
        <ActivityIndicator />
      </View>
    );
  }

  if (isError) {
    return (
      <View style={styles.centered}>
        <Stack.Screen options={{ title: '식단 상세' }} />
        <Text style={styles.errorTitle}>오류 — 식단을 불러올 수 없습니다</Text>
        <Pressable
          onPress={() => refetch()}
          accessibilityRole="button"
          accessibilityLabel="다시 시도"
          style={styles.actionButton}
        >
          <Text style={styles.actionButtonText}>다시 시도</Text>
        </Pressable>
      </View>
    );
  }

  // 7일 캐시 miss — Epic 3 SSE 또는 Story 8 단건 endpoint에서 보강 (DF18/DF26).
  if (!meal) {
    return (
      <View style={styles.centered}>
        <Stack.Screen options={{ title: '식단 상세' }} />
        <Text style={styles.errorTitle}>
          식단 정보를 불러올 수 없습니다 — 일별 기록에서 다시 시도해주세요
        </Text>
        <Pressable
          onPress={() => router.back()}
          accessibilityRole="button"
          accessibilityLabel="이전으로"
          style={styles.actionButton}
        >
          <Text style={styles.actionButtonText}>이전으로</Text>
        </Pressable>
      </View>
    );
  }

  const summary = meal.analysis_summary;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      accessibilityLabel="식단 상세 화면"
    >
      <Stack.Screen options={{ title: '식단 상세' }} />

      {/* 시간 + raw_text */}
      <View style={styles.headerBlock}>
        <Text style={styles.timeText}>{formatHHmm(meal.ate_at)}</Text>
        <Text style={styles.rawText} accessibilityLabel={`식단 내용: ${meal.raw_text}`}>
          {meal.raw_text}
        </Text>
      </View>

      {/* 사진 (있으면 full width 16:9 max 320px) */}
      {meal.image_url ? (
        <Image
          source={{ uri: meal.image_url }}
          style={styles.image}
          contentFit="contain"
          transition={300}
          cachePolicy="disk"
          accessibilityIgnoresInvertColors
        />
      ) : null}

      {/* parsed_items */}
      {meal.parsed_items && meal.parsed_items.length > 0 ? (
        <View style={styles.detailBlock}>
          <Text style={styles.sectionTitle}>인식 결과</Text>
          {meal.parsed_items.map((item, idx) => {
            // CR P8 — confidence가 null/undefined 시 NaN% 회귀 차단. 백엔드 contract는
            // float이지만 OpenAPI 클라이언트 타입 / 캐시 corruption에 대한 방어 layer.
            const confidencePct = (((item.confidence ?? 0) * 100) | 0).toString();
            return (
              <Text style={styles.bodyText} key={`${item.name}-${idx}`}>
                {`${item.name} · ${item.quantity || '-'} · ${confidencePct}%`}
              </Text>
            );
          })}
        </View>
      ) : null}

      {/* AI 분석 섹션 — Story 3.7 D5 IN: meal_analyses JOIN 결과 즉시 표시 */}
      {summary !== null ? (
        <>
          <MacrosBlock macros={summary.macros} />
          <View style={styles.detailBlock}>
            <Text style={styles.sectionTitle}>피드백</Text>
            <Text style={styles.bodyText}>{summary.feedback_summary}</Text>
          </View>
          <View style={styles.detailBlock}>
            <Text style={styles.sectionTitle}>적합도 점수</Text>
            <View
              style={[
                styles.fitScoreBadge,
                { backgroundColor: FIT_SCORE_COLORS[summary.fit_score_label] },
              ]}
            >
              <Text style={styles.fitScoreNumber}>{summary.fit_score}</Text>
              <Text style={styles.fitScoreLabel}>
                {FIT_SCORE_LABELS_KO[summary.fit_score_label]}
              </Text>
            </View>
          </View>
        </>
      ) : analysisStarted ? (
        // Story 3.7 — ChatStreaming SSE UI inline 마운트 (CTA 탭 후).
        <View style={styles.chatStreamingBlock}>
          <ChatStreaming
            mealId={meal.id}
            isOnline={!isOffline}
            onAnalysisDone={() => {
              void queryClient.invalidateQueries({ queryKey: ['meals'] });
            }}
          />
        </View>
      ) : (
        // Story 3.7 — "AI 분석 시작" CTA. 오프라인 시 disabled 가드.
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={
            isOffline ? 'AI 분석 시작 — 오프라인' : 'AI 분석 시작'
          }
          accessibilityState={{ disabled: isOffline }}
          disabled={isOffline}
          onPress={() => {
            if (isOffline) return;
            setAnalysisStarted(true);
          }}
          style={[styles.askButton, isOffline && styles.askButtonDisabled]}
        >
          <Text style={styles.askButtonText}>
            {isOffline ? 'AI 분석 시작 (오프라인 — 온라인 시 가능)' : 'AI 분석 시작'}
          </Text>
        </Pressable>
      )}

      {/* 액션 버튼 — CR Gemini #3 정합: 오프라인 시 visual disabled (NFR-R4 read-only). */}
      <View style={styles.actionRow}>
        <Pressable
          onPress={handleEdit}
          disabled={deleteMutation.isPending || isOffline}
          accessibilityRole="button"
          accessibilityLabel="수정"
          accessibilityState={{ disabled: deleteMutation.isPending || isOffline }}
          style={[
            styles.actionButton,
            styles.actionButtonSecondary,
            deleteMutation.isPending || isOffline ? styles.actionButtonDisabled : null,
          ]}
        >
          <Text style={styles.actionButtonText}>수정</Text>
        </Pressable>
        {/* CR P7 — 삭제 in-flight 시 UI disable로 연타 차단(`handleDeleteConfirmed`의
            isPending 가드는 이미 있으나 Alert 재표시는 별도 — 버튼 자체 disabled로 UX 정합). */}
        <Pressable
          onPress={handleDelete}
          disabled={deleteMutation.isPending || isOffline}
          accessibilityRole="button"
          accessibilityLabel="삭제"
          accessibilityState={{ disabled: deleteMutation.isPending || isOffline }}
          style={[
            styles.actionButton,
            styles.actionButtonDestructive,
            deleteMutation.isPending || isOffline ? styles.actionButtonDisabled : null,
          ]}
        >
          <Text style={styles.actionButtonDestructiveText}>
            {deleteMutation.isPending ? '삭제 중…' : '삭제'}
          </Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  content: {
    padding: 16,
    gap: 16,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 16,
    backgroundColor: '#f5f5f5',
  },
  errorTitle: {
    fontSize: 16,
    color: '#d93025',
    textAlign: 'center',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 22,
  },
  headerBlock: {
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#e0e0e0',
    padding: 16,
    gap: 8,
  },
  timeText: {
    fontSize: 16,
    color: '#1a73e8',
    fontWeight: '600',
    lineHeight: 22,
  },
  rawText: {
    fontSize: 16,
    color: '#222',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 24,
  },
  image: {
    width: '100%',
    aspectRatio: 16 / 9,
    maxHeight: 320,
    borderRadius: 8,
    backgroundColor: '#f0f0f0',
  },
  detailBlock: {
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#e0e0e0',
    padding: 16,
    gap: 8,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: '#666',
    lineHeight: 20,
  },
  bodyText: {
    fontSize: 15,
    color: '#222',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 22,
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
  placeholderBlock: {
    backgroundColor: '#f0f0f0',
    borderRadius: 8,
    padding: 16,
  },
  placeholderText: {
    fontSize: 14,
    color: '#888',
    fontWeight: '500',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 20,
  },
  chatStreamingBlock: {
    minHeight: 240,
    backgroundColor: '#f9fafb',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#e0e0e0',
    overflow: 'hidden',
  },
  askButton: {
    backgroundColor: '#1a73e8',
    borderRadius: 8,
    paddingHorizontal: 20,
    paddingVertical: 14,
    alignItems: 'center',
  },
  askButtonDisabled: {
    backgroundColor: '#a4c2f4',
    opacity: 0.7,
  },
  askButtonText: {
    fontSize: 16,
    color: '#fff',
    fontWeight: '700',
    lineHeight: 22,
    flexShrink: 1,
    flexWrap: 'wrap',
    textAlign: 'center',
  },
  actionRow: {
    flexDirection: 'row',
    gap: 12,
  },
  actionButton: {
    flex: 1,
    paddingHorizontal: 20,
    paddingVertical: 12,
    backgroundColor: '#1a73e8',
    borderRadius: 8,
    alignItems: 'center',
  },
  actionButtonSecondary: {
    backgroundColor: '#1a73e8',
  },
  actionButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 16,
    lineHeight: 22,
  },
  actionButtonDestructive: {
    backgroundColor: '#d93025',
  },
  actionButtonDisabled: {
    opacity: 0.5,
  },
  actionButtonDestructiveText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 16,
    lineHeight: 22,
  },
});
