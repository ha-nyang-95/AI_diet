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
import { useCallback, useState } from 'react';
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
import {
  MealSubmitError,
  useDeleteMealMutation,
  useMealsQuery,
} from '@/features/meals/api';
import { addDays, formatDateKo, isToday, todayKst } from '@/features/meals/dateUtils';
import type { MealResponse } from '@/features/meals/mealSchema';
import { useOnlineStatus } from '@/lib/use-online-status';

export default function MealsListScreen() {
  const [selectedDate, setSelectedDate] = useState<string>(() => todayKst());
  const { data, isPending, isError, refetch, isRefetching } = useMealsQuery({
    from_date: selectedDate,
    to_date: selectedDate,
  });
  const deleteMutation = useDeleteMealMutation();
  const queryClient = useQueryClient();
  const { isOnline, isInternetReachable } = useOnlineStatus();
  const isOffline = !isOnline || isInternetReachable === false;
  const today = isToday(selectedDate);

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
                accessibilityRole="button"
                accessibilityLabel="다음 일자"
                hitSlop={12}
                style={styles.headerButton}
              >
                <Text style={styles.headerArrowText}>{'>'}</Text>
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
      ) : data && data.meals.length === 0 ? (
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
          data={data?.meals ?? []}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => (
            <MealCard
              meal={item}
              onCardPress={handleCardPress}
              onActionPress={handleActionPress}
            />
          )}
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
  headerArrowText: {
    fontSize: 22,
    color: '#1a73e8',
    fontWeight: '600',
    lineHeight: 26,
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
});
