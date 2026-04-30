/**
 * Story 2.1 (baseline) → Story 2.4 polish — 일별 식단 기록 화면.
 *
 * Story 2.4 추가:
 * - `selectedDate` state — 날짜 picker(prev/next/today). KST 강제 (W49 정합).
 * - 헤더 prev/next/today 버튼 + 동적 title("오늘 식단" / "4월 30일 식단").
 * - 카드 onPress → `[meal_id]` 상세 (탭 = 상세, long-press = 액션 — RN 표준 패턴).
 * - 네트워크 상태 배너 — `useOnlineStatus()` (NFR-R4 7일 캐시 정합).
 * - 빈 화면 분기 — 오늘 시 CTA 노출, 다른 일자 시 CTA 미노출.
 * - 시간순 ASC 정렬은 백엔드 ORDER BY 분기(D2) — 클라이언트 정렬 0.
 */
import { Stack, router } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
// CR Gemini #1 (HIGH) — query window가 mount 시점 1회 고정되면 (a) 자정 cross 시 stale,
// (b) 내일 catch-up 식단 누락. 매 렌더 직접 계산 + to_date를 tomorrow까지 확장.
import {
  ActionSheetIOS,
  ActivityIndicator,
  Alert,
  FlatList,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useQueryClient } from '@tanstack/react-query';

import { MealCard } from '@/features/meals/MealCard';
import { OfflineMealCard } from '@/features/meals/OfflineMealCard';
import {
  MealSubmitError,
  useDeleteMealMutation,
  useMealsQuery,
} from '@/features/meals/api';
import {
  addDays,
  formatDateKo,
  isToday,
  isoToKstDate,
  todayKst,
} from '@/features/meals/dateUtils';
import type { MealResponse } from '@/features/meals/mealSchema';
import { useAuth, authFetch } from '@/lib/auth';
import {
  flushQueue,
  removeQueueItem,
  useOfflineQueue,
  type OfflineQueueItem,
} from '@/lib/offline-queue';
import { useOnlineStatus } from '@/lib/use-online-status';

export default function MealsListScreen() {
  const [selectedDate, setSelectedDate] = useState<string>(() => todayKst());
  // CR P11 — 7일 윈도우 fetch + client-side filter (D1 옵션 b 채택). queryKey 통일
  // (`[meal_id].tsx`와 캐시 공유) → 오프라인 prev/next 시 7일 모두 cache hit (NFR-R4
  // 일자 무관 보장). 백엔드 ASC 정렬 + selectedDate별 filter는 시간순 ASC 그대로 유지
  // (AC4 정합). 한 번 fetch로 여러 일자 navigation 무비용.
  //
  // CR Gemini #1 — useMemo([])로 1회 고정 시 자정 cross 시 stale + 내일 catch-up 누락.
  // 매 렌더 직접 계산 (todayKst은 Intl.DateTimeFormat 1회 호출로 cheap, queryKey는
  // TanStack Query가 deep-equal hash라 동일 값일 때 refetch 없음). to_date를 *내일까지*
  // 확장 — AC4 "내일까지 허용" + 사용자가 내일 catch-up 식단 입력 시 표시 정합.
  const todayDate = todayKst();
  const sevenDaysAgo = addDays(todayDate, -7);
  const tomorrowDate = addDays(todayDate, 1);
  const { data, isPending, isError, refetch, isRefetching } = useMealsQuery({
    from_date: sevenDaysAgo,
    to_date: tomorrowDate,
  });
  const filteredMeals = useMemo(
    () =>
      (data?.meals ?? []).filter(
        (m) => isoToKstDate(m.ate_at) === selectedDate,
      ),
    [data?.meals, selectedDate],
  );
  // P4 — 다음 일자 버튼 disable 분기 (selectedDate >= 내일 — 모레 이상 navigate 차단).
  const isNextDisabled = selectedDate >= tomorrowDate;
  const deleteMutation = useDeleteMealMutation();
  const queryClient = useQueryClient();
  const { isOnline, isInternetReachable } = useOnlineStatus();
  const isOffline = !isOnline || isInternetReachable === false;
  const today = isToday(selectedDate);

  // Story 2.5 — 오프라인 큐 + 자동 flush.
  const { user } = useAuth();
  const userId = user?.id ?? '';
  const queueItems = useOfflineQueue(userId);
  const queueSize = queueItems.length;
  const [isFlushing, setIsFlushing] = useState(false);
  // `useOnlineStatus` 변경 detect용 prev ref. 첫 렌더(prev=undefined) + current=true 분기는
  // 의도적 — 앱 cold start 시 잔존 큐가 있으면 자동 sync (D6 정합).
  const prevOnlineRef = useRef<boolean | undefined>(undefined);

  const triggerFlush = useCallback(async () => {
    if (!userId || isFlushing) return;
    setIsFlushing(true);
    try {
      const result = await flushQueue(userId, authFetch);
      if (result.flushed_count > 0) {
        // 서버 row가 list에 들어가도록 refetch.
        void queryClient.invalidateQueries({ queryKey: ['meals'] });
      }
      if (result.failed_permanent_count > 0) {
        Alert.alert(
          '식단을 동기화할 수 없어요',
          '입력 오류로 일부 식단이 거부되어 폐기되었습니다. 다시 입력해주세요.',
        );
      }
    } catch {
      // flush 자체 실패는 silent (transient — 다음 트리거에서 재시도).
    } finally {
      setIsFlushing(false);
    }
  }, [userId, isFlushing, queryClient]);

  useEffect(() => {
    const prev = prevOnlineRef.current;
    prevOnlineRef.current = isOnline;
    // offline → online 전이 또는 첫 렌더(undefined → true) 시 flush 자동 호출.
    if (isOnline && prev !== true && queueSize > 0) {
      void triggerFlush();
    }
  }, [isOnline, queueSize, triggerFlush]);

  const handleQueueRetry = useCallback(
    (_clientId: string) => {
      if (!isOnline) {
        Alert.alert(
          '오프라인 상태',
          '온라인 시 자동으로 동기화됩니다.',
        );
        return;
      }
      void triggerFlush();
    },
    [isOnline, triggerFlush],
  );

  const handleQueueDiscard = useCallback(
    (clientId: string) => {
      Alert.alert(
        '큐 항목 폐기',
        '이 식단을 폐기하시겠습니까? 동기화되지 않은 입력은 영구 손실됩니다.',
        [
          { text: '취소', style: 'cancel' },
          {
            text: '폐기',
            style: 'destructive',
            onPress: () => {
              if (!userId) return;
              void removeQueueItem(userId, clientId);
            },
          },
        ],
        { cancelable: true },
      );
    },
    [userId],
  );

  // 오늘 일자에서만 큐 카드 노출 — 다른 일자는 server row 위주(epic AC line 573 정합).
  const showQueueCards = today && queueSize > 0;

  const handleAddPress = useCallback(() => {
    const target = '/(tabs)/meals/input' as Parameters<typeof router.push>[0];
    router.push(target);
  }, []);

  const handlePrevDay = useCallback(() => {
    setSelectedDate((prev) => addDays(prev, -1));
  }, []);

  const handleNextDay = useCallback(() => {
    setSelectedDate((prev) => addDays(prev, 1));
  }, []);

  const handleGoToday = useCallback(() => {
    setSelectedDate(todayKst());
  }, []);

  const handleCardPress = useCallback((meal: MealResponse) => {
    const target = `/(tabs)/meals/${meal.id}` as Parameters<typeof router.push>[0];
    router.push(target);
  }, []);

  const handleEdit = useCallback((meal: MealResponse) => {
    const target = `/(tabs)/meals/input?meal_id=${meal.id}` as Parameters<
      typeof router.push
    >[0];
    router.push(target);
  }, []);

  const handleDeleteConfirmed = useCallback(
    (meal: MealResponse) => {
      // P2 — 더블탭 가드: 진행 중인 삭제 mutation이 있으면 추가 호출 무시
      // (RN Alert는 native dedupe 부재 → 같은 식단에 대한 중복 DELETE 차단).
      if (deleteMutation.isPending) return;
      deleteMutation.mutate(meal.id, {
        onError: (err: unknown) => {
          // P3 — 404 `meals.not_found`는 retry/race로 *이미 삭제된* 상태 →
          // 사용자 시점에서 *성공* 동등. invalidate만 하고 silent (Alert 생략).
          if (
            err instanceof MealSubmitError &&
            err.status === 404 &&
            err.code === 'meals.not_found'
          ) {
            void queryClient.invalidateQueries({ queryKey: ['meals'] });
            return;
          }
          const message =
            err instanceof MealSubmitError
              ? `삭제 실패 — ${err.detail ?? `(${err.status})`}`
              : '삭제 실패 — 다시 시도해주세요';
          Alert.alert('식단 삭제', message);
        },
      });
    },
    [deleteMutation, queryClient],
  );

  const handleDelete = useCallback(
    (meal: MealResponse) => {
      Alert.alert(
        '식단 삭제',
        '이 식단을 삭제하시겠습니까?',
        [
          { text: '취소', style: 'cancel' },
          {
            text: '삭제',
            style: 'destructive',
            onPress: () => handleDeleteConfirmed(meal),
          },
        ],
        { cancelable: true },
      );
    },
    [handleDeleteConfirmed],
  );

  const handleActionPress = useCallback(
    (meal: MealResponse) => {
      // 오프라인 상태에서는 수정/삭제 미제공 — Story 8 polish에서 disabled visual.
      if (isOffline) {
        Alert.alert('오프라인', '온라인 시 가능합니다.');
        return;
      }
      if (Platform.OS === 'ios') {
        ActionSheetIOS.showActionSheetWithOptions(
          {
            options: ['취소', '수정', '삭제'],
            cancelButtonIndex: 0,
            destructiveButtonIndex: 2,
          },
          (buttonIndex) => {
            if (buttonIndex === 1) handleEdit(meal);
            else if (buttonIndex === 2) handleDelete(meal);
          },
        );
      } else {
        Alert.alert(
          '식단 옵션',
          undefined,
          [
            { text: '취소', style: 'cancel' },
            { text: '수정', onPress: () => handleEdit(meal) },
            { text: '삭제', style: 'destructive', onPress: () => handleDelete(meal) },
          ],
          { cancelable: true },
        );
      }
    },
    [handleEdit, handleDelete, isOffline],
  );

  const headerTitle = today ? '오늘 식단' : `${formatDateKo(selectedDate)} 식단`;

  return (
    <View style={styles.container}>
      <Stack.Screen
        options={{
          title: headerTitle,
          headerLeft: () => (
            <Pressable
              onPress={handlePrevDay}
              accessibilityRole="button"
              accessibilityLabel="전 일자"
              hitSlop={12}
              style={styles.headerButton}
            >
              <Text style={styles.headerArrowText}>{'<'}</Text>
            </Pressable>
          ),
          headerRight: () => (
            <View style={styles.headerRightRow}>
              <Pressable
                onPress={handleNextDay}
                disabled={isNextDisabled}
                accessibilityRole="button"
                accessibilityLabel="다음 일자"
                accessibilityState={{ disabled: isNextDisabled }}
                hitSlop={12}
                style={[
                  styles.headerButton,
                  isNextDisabled ? styles.headerButtonDisabled : null,
                ]}
              >
                <Text
                  style={[
                    styles.headerArrowText,
                    isNextDisabled ? styles.headerArrowTextDisabled : null,
                  ]}
                >
                  {'>'}
                </Text>
              </Pressable>
              {!today ? (
                <Pressable
                  onPress={handleGoToday}
                  accessibilityRole="button"
                  accessibilityLabel="오늘로 이동"
                  hitSlop={12}
                  style={styles.todayButton}
                >
                  <Text style={styles.todayButtonText}>오늘로</Text>
                </Pressable>
              ) : null}
              <Pressable
                onPress={handleAddPress}
                accessibilityRole="button"
                accessibilityLabel="식단 입력"
                hitSlop={12}
                style={styles.headerButton}
              >
                <Text style={styles.headerButtonText}>＋</Text>
              </Pressable>
            </View>
          ),
        }}
      />

      {isOffline ? (
        <View
          style={styles.offlineBanner}
          accessibilityLiveRegion="polite"
          accessibilityLabel="오프라인 — 마지막 7일 기록 표시 중"
        >
          <Text style={styles.offlineBannerText}>
            오프라인 — 마지막 7일 기록 표시 중
          </Text>
        </View>
      ) : null}

      {/* Story 2.5 — 동기화 대기 배지 (헤더 영역 아래 별 row). 큐 size > 0 시 노출. */}
      {queueSize > 0 ? (
        <View
          style={styles.queueBanner}
          accessibilityLiveRegion="polite"
          accessibilityLabel={`동기화 대기 ${queueSize}건`}
        >
          <Text style={styles.queueBannerText}>
            {`동기화 대기 ${queueSize}건${isFlushing ? ' — 동기화 중' : ''}`}
          </Text>
        </View>
      ) : null}

      {isPending ? (
        <View style={styles.centered}>
          <ActivityIndicator />
        </View>
      ) : isError ? (
        <View style={styles.centered}>
          <Text style={styles.errorTitle}>오류 — 식단을 불러올 수 없습니다</Text>
          <Pressable
            style={styles.retryButton}
            onPress={() => refetch()}
            accessibilityRole="button"
            accessibilityLabel="다시 시도"
          >
            <Text style={styles.retryButtonText}>다시 시도</Text>
          </Pressable>
        </View>
      ) : filteredMeals.length === 0 && !showQueueCards ? (
        <View style={styles.centered}>
          {today ? (
            <>
              <Text style={styles.emptyText}>
                오늘 기록 없음 — 첫 식단을 입력하세요
              </Text>
              <Pressable
                style={styles.ctaButton}
                onPress={handleAddPress}
                accessibilityRole="button"
                accessibilityLabel="식단 입력"
              >
                <Text style={styles.ctaButtonText}>식단 입력</Text>
              </Pressable>
            </>
          ) : (
            <Text style={styles.emptyText}>{`${formatDateKo(selectedDate)} 기록 없음`}</Text>
          )}
        </View>
      ) : (
        <FlatList
          data={[
            ...(showQueueCards
              ? queueItems.map((q) => ({ kind: 'queue' as const, item: q }))
              : []),
            ...filteredMeals.map((m) => ({ kind: 'server' as const, item: m })),
          ]}
          keyExtractor={(entry) =>
            entry.kind === 'queue' ? `queue:${entry.item.client_id}` : entry.item.id
          }
          renderItem={({ item: entry }) =>
            entry.kind === 'queue' ? (
              <OfflineMealCard
                item={entry.item as OfflineQueueItem}
                onRetry={handleQueueRetry}
                onDiscard={handleQueueDiscard}
                isFlushing={isFlushing}
              />
            ) : (
              <MealCard
                meal={entry.item as MealResponse}
                onCardPress={handleCardPress}
                onActionPress={handleActionPress}
              />
            )
          }
          contentContainerStyle={styles.listContent}
          refreshing={isRefetching}
          onRefresh={refetch}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 16,
  },
  emptyText: {
    fontSize: 16,
    color: '#666',
    textAlign: 'center',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 22,
  },
  errorTitle: {
    fontSize: 16,
    color: '#d93025',
    textAlign: 'center',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 22,
  },
  retryButton: {
    paddingHorizontal: 20,
    paddingVertical: 10,
    backgroundColor: '#1a73e8',
    borderRadius: 8,
  },
  retryButtonText: {
    color: '#fff',
    fontWeight: '600',
  },
  ctaButton: {
    paddingHorizontal: 24,
    paddingVertical: 12,
    backgroundColor: '#1a73e8',
    borderRadius: 8,
  },
  ctaButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 16,
  },
  listContent: {
    padding: 16,
  },
  headerButton: {
    paddingHorizontal: 12,
    paddingVertical: 4,
  },
  headerButtonDisabled: {
    opacity: 0.4,
  },
  headerArrowText: {
    fontSize: 22,
    color: '#1a73e8',
    fontWeight: '600',
    lineHeight: 26,
  },
  headerArrowTextDisabled: {
    color: '#999',
  },
  headerButtonText: {
    fontSize: 28,
    color: '#1a73e8',
    fontWeight: '600',
    lineHeight: 32,
  },
  headerRightRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  todayButton: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    backgroundColor: '#e8f0fe',
  },
  todayButtonText: {
    color: '#1a73e8',
    fontWeight: '600',
    fontSize: 13,
    lineHeight: 16,
  },
  offlineBanner: {
    backgroundColor: '#fff3cd',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#ffe69c',
  },
  offlineBannerText: {
    color: '#664d03',
    fontSize: 13,
    fontWeight: '500',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 18,
  },
  queueBanner: {
    backgroundColor: '#fef3c7',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#fde68a',
  },
  queueBannerText: {
    color: '#92400e',
    fontSize: 13,
    fontWeight: '600',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 18,
  },
});
