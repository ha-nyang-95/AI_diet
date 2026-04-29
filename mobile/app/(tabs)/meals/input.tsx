/**
 * Story 2.1 — 식단 입력/수정 화면 (POST + PATCH 통합).
 *
 * `?meal_id=` 쿼리 파라미터로 분기:
 * - 미존재 → POST 모드 (신규). 헤더 *식단 입력*.
 * - 존재 → PATCH 모드. list 캐시(`['meals', ...]`)에서 prefill.
 *
 * 단일 GET endpoint(`/v1/meals/{meal_id}`) 미요구 — list 캐시 prefill로 충분.
 * 향후 deeplink direct 진입 시 cache miss 처리는 Story 3.7(채팅) 또는 polish 시점.
 *
 * 에러 처리:
 * - 401: `authFetch` 인터셉터가 자동 처리 (refresh + redirect).
 * - 403 `consent.basic.missing` → onboarding/disclaimer redirect (Story 1.5 W8 정합).
 * - 400/422 → 폼 필드 에러 표시.
 * - 5xx / 네트워크 → Alert.
 */
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Alert, StyleSheet, View } from 'react-native';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';

import { MealInputForm } from '@/features/meals/MealInputForm';
import {
  MealSubmitError,
  useCreateMealMutation,
  useUpdateMealMutation,
} from '@/features/meals/api';
import type {
  MealCreateFormData,
  MealListResponse,
  MealResponse,
} from '@/features/meals/mealSchema';

function findMealInCache(
  queryClient: QueryClient,
  meal_id: string,
): MealResponse | null {
  // 모든 ['meals', ...] 캐시 entry를 순회 — 어떤 from_date/to_date 조합이든 적중하면
  // 그대로 prefill에 사용.
  const queries = queryClient.getQueriesData<MealListResponse>({ queryKey: ['meals'] });
  for (const [, data] of queries) {
    if (!data) continue;
    const found = data.meals.find((m) => m.id === meal_id);
    if (found) return found;
  }
  return null;
}

export default function MealInputScreen() {
  const { meal_id } = useLocalSearchParams<{ meal_id?: string }>();
  const queryClient = useQueryClient();
  const [serverError, setServerError] = useState<string | null>(null);

  const editingMeal = useMemo(
    () => (meal_id ? findMealInCache(queryClient, meal_id) : null),
    [meal_id, queryClient],
  );
  const isPatchMode = Boolean(meal_id);
  // P4 — PATCH 모드 + 캐시 미스 → 빈 폼이 *식단 수정* 헤더로 노출되어 사용자
  // 입력으로 원문 silent 덮어쓰기 위험. 1회 알림 후 list로 회귀.
  const isPatchCacheMiss = isPatchMode && !editingMeal;

  useEffect(() => {
    if (!isPatchCacheMiss) return;
    Alert.alert('식단을 찾을 수 없습니다', '목록으로 돌아갑니다.', [
      {
        text: '확인',
        onPress: () => {
          const target = '/(tabs)/meals' as Parameters<typeof router.replace>[0];
          router.replace(target);
        },
      },
    ]);
  }, [isPatchCacheMiss]);

  const createMutation = useCreateMealMutation();
  const updateMutation = useUpdateMealMutation();
  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  const headerTitle = isPatchMode ? '식단 수정' : '식단 입력';
  const submitLabel = isPatchMode ? '수정 저장' : '저장';

  const defaultValues: MealCreateFormData | undefined = editingMeal
    ? { raw_text: editingMeal.raw_text }
    : undefined;

  const handleSubmitError = (err: unknown) => {
    if (err instanceof MealSubmitError) {
      if (err.code === 'consent.basic.missing') {
        Alert.alert('동의가 필요합니다', '온보딩 화면으로 이동합니다.', [
          {
            text: '확인',
            onPress: () => {
              const target = '/(auth)/onboarding/disclaimer' as Parameters<
                typeof router.replace
              >[0];
              router.replace(target);
            },
          },
        ]);
        return;
      }
      if (err.status === 400 || err.status === 422) {
        setServerError(err.detail ?? '입력값을 확인해주세요');
        return;
      }
      Alert.alert('식단 저장 실패', err.detail ?? `오류가 발생했습니다 (${err.status})`);
      return;
    }
    Alert.alert('식단 저장 실패', '네트워크 오류가 발생했습니다. 다시 시도해주세요.');
  };

  const onSubmit = (data: MealCreateFormData) => {
    setServerError(null);
    if (isPatchMode && meal_id) {
      updateMutation.mutate(
        { meal_id, body: { raw_text: data.raw_text } },
        {
          onSuccess: () => {
            const target = '/(tabs)/meals' as Parameters<typeof router.replace>[0];
            router.replace(target);
          },
          onError: handleSubmitError,
        },
      );
    } else {
      createMutation.mutate(
        { raw_text: data.raw_text },
        {
          onSuccess: () => {
            const target = '/(tabs)/meals' as Parameters<typeof router.replace>[0];
            router.replace(target);
          },
          onError: handleSubmitError,
        },
      );
    }
  };

  // P4 — PATCH 캐시 미스 시 폼 렌더링 차단 (Alert 후 list로 replace됨).
  if (isPatchCacheMiss) {
    return (
      <View style={styles.container}>
        <Stack.Screen options={{ title: headerTitle }} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: headerTitle }} />
      <MealInputForm
        defaultValues={defaultValues}
        isSubmitting={isSubmitting}
        submitLabel={submitLabel}
        onSubmit={onSubmit}
        serverError={serverError}
        onClearServerError={() => setServerError(null)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
});
