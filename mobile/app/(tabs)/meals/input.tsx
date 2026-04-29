/**
 * Story 2.1 + 2.2 — 식단 입력/수정 화면 (POST + PATCH 통합 + 사진 첨부 흐름).
 *
 * `?meal_id=` 쿼리 파라미터로 분기:
 * - 미존재 → POST 모드 (신규). 헤더 *식단 입력*.
 * - 존재 → PATCH 모드. list 캐시(`['meals', ...]`)에서 prefill.
 *
 * 단일 GET endpoint(`/v1/meals/{meal_id}`) 미요구 — list 캐시 prefill로 충분.
 *
 * 에러 처리:
 * - 401: `authFetch` 인터셉터가 자동 처리 (refresh + redirect).
 * - 403 `consent.basic.missing` → onboarding/disclaimer redirect (Story 1.5 W8 정합).
 * - 400/422 → 폼 필드 에러 표시.
 * - 5xx / 네트워크 → Alert.
 *
 * Story 2.2 사진 첨부 orchestration:
 * - `useCameraPermission`/`useMediaLibraryPermission` (lib/permissions.ts).
 * - 권한 granted → `ImagePicker.launchCameraAsync`/`launchImageLibraryAsync`.
 * - 결과 → `uploadImageToR2(uri, mimeType, fileSize)` → state(`imageKey` + `imageLocalUri`) 갱신.
 * - 권한 denied → `PermissionDeniedView` inline render (form 대체).
 * - PATCH 모드 prefill: `editingMeal.image_url` 썸네일.
 * - *제거* 액션: `imageClearedExplicitly` state (PATCH 모드에서 `image_key=null` 명시 송신).
 * - 클라이언트 1차 가드: *raw_text 또는 image_key 최소 1* 미충족 시 Alert + early return.
 */
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, StyleSheet, View } from 'react-native';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import * as ImagePicker from 'expo-image-picker';

import { MealInputForm, type ImagePickKind } from '@/features/meals/MealInputForm';
import { PermissionDeniedView, type PermissionKind } from '@/features/meals/PermissionDeniedView';
import {
  MealImageUploadError,
  MealSubmitError,
  uploadImageToR2,
  useCreateMealMutation,
  useUpdateMealMutation,
} from '@/features/meals/api';
import type {
  MealCreateFormData,
  MealCreateRequest,
  MealImagePresignRequest,
  MealListResponse,
  MealResponse,
  MealUpdateRequest,
} from '@/features/meals/mealSchema';
import { useCameraPermission, useMediaLibraryPermission } from '@/lib/permissions';

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

const SUPPORTED_MIME: readonly MealImagePresignRequest['content_type'][] = [
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/heic',
  'image/heif',
];

function _normalizeMimeType(
  raw: string | undefined,
): MealImagePresignRequest['content_type'] | null {
  if (!raw) return null;
  // P6 — charset suffix(`; charset=binary` Android 일부 picker) 제거 + lowercase + 별칭.
  const cleaned = raw.split(';')[0].trim().toLowerCase();
  // image/jpg는 비표준 별칭 — image/jpeg로 정규화.
  const aliased = cleaned === 'image/jpg' ? 'image/jpeg' : cleaned;
  return (SUPPORTED_MIME as readonly string[]).includes(aliased)
    ? (aliased as MealImagePresignRequest['content_type'])
    : null;
}

// P6 — picker가 mimeType 미반환(iOS HEIC 일부 케이스)일 때 URI 확장자 fallback.
function _inferMimeFromUri(uri: string): string | undefined {
  const lower = uri.toLowerCase();
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.webp')) return 'image/webp';
  if (lower.endsWith('.heic')) return 'image/heic';
  if (lower.endsWith('.heif')) return 'image/heif';
  return undefined;
}

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

interface DeniedState {
  kind: PermissionKind;
  canAskAgain: boolean;
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
  const isPatchCacheMiss = isPatchMode && !editingMeal;

  // Story 2.2 — 사진 첨부 state.
  const [imageKey, setImageKey] = useState<string | null>(editingMeal?.image_key ?? null);
  const [imageLocalUri, setImageLocalUri] = useState<string | null>(
    editingMeal?.image_url ?? null,
  );
  // PATCH 모드에서만 의미 — *제거* 액션 후 PATCH 시 `image_key=null` 명시 송신 분기.
  const [imageClearedExplicitly, setImageClearedExplicitly] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [deniedState, setDeniedState] = useState<DeniedState | null>(null);

  const cameraPermission = useCameraPermission();
  const mediaLibraryPermission = useMediaLibraryPermission();

  // P8 — unmount 시 in-flight upload 결과의 setState 차단 (React stale-state 경고 방지).
  const isMountedRef = useRef(true);
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

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

  const handlePickImage = async (kind: ImagePickKind) => {
    setDeniedState(null);
    const permissionState = kind === 'camera' ? cameraPermission : mediaLibraryPermission;
    const permKind: PermissionKind = kind === 'camera' ? 'camera' : 'mediaLibrary';

    // 첫 입력이면 prompt — granted/denied/undetermined 분기.
    let status = permissionState.status;
    if (status !== 'granted') {
      // canAskAgain=false면 prompt가 즉시 denied 반환 — `PermissionDeniedView`로 분기.
      if (!permissionState.canAskAgain) {
        setDeniedState({ kind: permKind, canAskAgain: false });
        return;
      }
      status = await permissionState.request();
    }
    if (status !== 'granted') {
      setDeniedState({ kind: permKind, canAskAgain: permissionState.canAskAgain });
      return;
    }

    // 권한 OK — picker 호출.
    let result: ImagePicker.ImagePickerResult;
    try {
      result =
        kind === 'camera'
          ? await ImagePicker.launchCameraAsync({
              mediaTypes: ['images'],
              allowsEditing: false,
              quality: 0.8,
            })
          : await ImagePicker.launchImageLibraryAsync({
              mediaTypes: ['images'],
              allowsMultipleSelection: false,
              quality: 0.8,
            });
    } catch {
      Alert.alert('사진 선택 실패', '잠시 후 다시 시도해주세요.');
      return;
    }
    if (result.canceled || result.assets.length === 0) return;

    const asset = result.assets[0];
    // P6 — mimeType 누락 시 URI 확장자 fallback (iOS HEIC 일부 케이스 cover).
    const rawMime = asset.mimeType ?? _inferMimeFromUri(asset.uri);
    const mime = _normalizeMimeType(rawMime);
    if (!mime) {
      Alert.alert(
        '지원하지 않는 형식',
        'JPEG/PNG/WEBP/HEIC/HEIF 형식의 이미지만 사용할 수 있어요.',
      );
      return;
    }

    // P23 (D4 결정) — fileSize 미반환/0 시 차단하지 않고 blob 측정으로 fallback.
    // Android Q+ 일부 picker가 HEIC/대용량 파일에서 fileSize를 반환하지 않는 케이스
    // 사용자 차단 회피. blob 측정 비용은 한 번 fetch (uploadImageToR2 내부에서 다시
    // fetch — RN 0.81 기준 redundant 호출이지만 캐시되어 비용 미미).
    let declaredSize = asset.fileSize ?? 0;
    if (declaredSize < 1) {
      try {
        const probe = await fetch(asset.uri);
        const probeBlob = await probe.blob();
        declaredSize = probeBlob.size;
      } catch {
        Alert.alert('업로드 실패', '이미지를 불러올 수 없어요. 다시 시도해주세요.');
        return;
      }
    }
    if (declaredSize < 1) {
      Alert.alert('업로드 실패', '0 byte 이미지는 업로드할 수 없어요.');
      return;
    }
    if (declaredSize > MAX_UPLOAD_BYTES) {
      Alert.alert('이미지가 너무 커요', '10 MB 이하의 이미지를 사용해주세요.');
      return;
    }

    setIsUploading(true);
    try {
      const uploaded = await uploadImageToR2(asset.uri, mime, declaredSize);
      // P8 — unmount 후 도달 시 setState 호출 회피 (React stale-state 경고 + memory leak).
      if (!isMountedRef.current) return;
      setImageKey(uploaded.image_key);
      setImageLocalUri(asset.uri);
      setImageClearedExplicitly(false);
    } catch (err) {
      if (!isMountedRef.current) return;
      if (err instanceof MealImageUploadError) {
        const reason =
          err.status === 'timeout'
            ? '업로드 시간이 초과되었어요. 다시 시도해주세요.'
            : err.status === 'network'
              ? '네트워크 오류로 업로드에 실패했어요. 다시 시도해주세요.'
              : `업로드 실패 (${err.status})`;
        Alert.alert('이미지 업로드 실패', reason);
      } else if (err instanceof MealSubmitError) {
        // presign 단계 실패 (consent.basic.missing 등은 handleSubmitError에서 일관 처리).
        handleSubmitError(err);
      } else {
        Alert.alert('이미지 업로드 실패', '잠시 후 다시 시도해주세요.');
      }
    } finally {
      if (isMountedRef.current) {
        setIsUploading(false);
      }
    }
  };

  const handleClearImage = () => {
    setImageKey(null);
    setImageLocalUri(null);
    if (isPatchMode) {
      setImageClearedExplicitly(true);
    }
  };

  const onSubmit = (data: MealCreateFormData) => {
    setServerError(null);
    const trimmedRawText = (data.raw_text ?? '').trim();
    const hasRawText = trimmedRawText.length > 0;
    const hasImage = Boolean(imageKey);

    // 클라이언트 1차 가드 — *raw_text 또는 image_key 최소 1*. (서버 2차 게이트)
    if (!hasRawText && !hasImage && !(isPatchMode && imageClearedExplicitly)) {
      Alert.alert(
        '입력이 필요해요',
        '식단 내용을 입력하거나 사진을 첨부해주세요.',
      );
      return;
    }

    if (isPatchMode && meal_id) {
      const body: MealUpdateRequest = {};
      if (hasRawText) body.raw_text = trimmedRawText;
      if (imageClearedExplicitly) {
        // 명시 null 클리어 (D4와 다른 시맨틱 — image_key는 nullable + null 명시 의미 있음).
        body.image_key = null;
      } else if (imageKey) {
        body.image_key = imageKey;
      }
      updateMutation.mutate(
        { meal_id, body },
        {
          onSuccess: () => {
            const target = '/(tabs)/meals' as Parameters<typeof router.replace>[0];
            router.replace(target);
          },
          onError: handleSubmitError,
        },
      );
    } else {
      const body: MealCreateRequest = {};
      if (hasRawText) body.raw_text = trimmedRawText;
      if (imageKey) body.image_key = imageKey;
      createMutation.mutate(body, {
        onSuccess: () => {
          const target = '/(tabs)/meals' as Parameters<typeof router.replace>[0];
          router.replace(target);
        },
        onError: handleSubmitError,
      });
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
      {deniedState ? (
        <PermissionDeniedView
          kind={deniedState.kind}
          canAskAgain={deniedState.canAskAgain}
          onRetryRequest={() =>
            void handlePickImage(deniedState.kind === 'camera' ? 'camera' : 'gallery')
          }
          onFallbackPress={() =>
            void handlePickImage(deniedState.kind === 'camera' ? 'gallery' : 'camera')
          }
        />
      ) : null}
      <MealInputForm
        defaultValues={defaultValues}
        isSubmitting={isSubmitting}
        submitLabel={submitLabel}
        onSubmit={onSubmit}
        serverError={serverError}
        onClearServerError={() => setServerError(null)}
        imageKey={imageKey}
        imageLocalUri={imageLocalUri}
        onPickImage={(kind) => void handlePickImage(kind)}
        onClearImage={handleClearImage}
        isUploading={isUploading}
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
