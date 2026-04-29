/**
 * Story 2.1 — 식단 *오늘 식단* baseline 화면.
 *
 * `useMealsQuery({ from_date: today, to_date: today })`로 오늘 식단만 fetch — 7일
 * history / 날짜 picker는 Story 2.4 책임.
 *
 * 카드 long-press → ActionSheet (`Platform.OS === 'ios'`이면 `ActionSheetIOS`,
 * 아니면 `Alert.alert` fallback) — 외부 라이브러리 회피 (Story 1.6 react-native-
 * swiper 회피 패턴 정합). 수정 / 삭제 / 취소 3 액션.
 */
import { Stack, router } from 'expo-router';
import { useCallback } from 'react';
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
import type { MealResponse } from '@/features/meals/mealSchema';

function todayDateString(): string {
  // YYYY-MM-DD — 한국 시간(UTC+9) 기준 오늘. 클라이언트 로컬 타임존이 KST라면 toISO
  // 직접 사용 가능; 사용자 디바이스 타임존을 신뢰 (architecture line 478 정합).
  const now = new Date();
  const yyyy = String(now.getFullYear()).padStart(4, '0');
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

export default function MealsListScreen() {
  const today = todayDateString();
  const { data, isPending, isError, refetch, isRefetching } = useMealsQuery({
    from_date: today,
    to_date: today,
  });
  const deleteMutation = useDeleteMealMutation();
  const queryClient = useQueryClient();

  const handleAddPress = useCallback(() => {
    const target = '/(tabs)/meals/input' as Parameters<typeof router.push>[0];
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
    [handleEdit, handleDelete],
  );

  return (
    <View style={styles.container}>
      <Stack.Screen
        options={{
          title: '오늘 식단',
          headerRight: () => (
            <Pressable
              onPress={handleAddPress}
              accessibilityRole="button"
              accessibilityLabel="식단 입력"
              hitSlop={12}
              style={styles.headerButton}
            >
              <Text style={styles.headerButtonText}>＋</Text>
            </Pressable>
          ),
        }}
      />

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
          <Text style={styles.emptyText}>오늘 기록 없음 — 첫 식단을 입력하세요</Text>
          <Pressable
            style={styles.ctaButton}
            onPress={handleAddPress}
            accessibilityRole="button"
            accessibilityLabel="식단 입력"
          >
            <Text style={styles.ctaButtonText}>식단 입력</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={data?.meals ?? []}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => (
            <MealCard meal={item} onActionPress={handleActionPress} />
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
  },
  errorTitle: {
    fontSize: 16,
    color: '#d93025',
    textAlign: 'center',
    flexShrink: 1,
    flexWrap: 'wrap',
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
  headerButtonText: {
    fontSize: 28,
    color: '#1a73e8',
    fontWeight: '600',
  },
});
