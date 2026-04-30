/**
 * Story 2.1 + 2.2 + 2.3 — 식단 입력/수정 화면 (POST + PATCH + 사진 첨부 + OCR Vision 흐름).
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
 *
 * Story 2.3 OCR Vision orchestration:
 * - `uploadImageToR2` 성공 직후 `parseMealImage(image_key)` 자동 호출 (effect chain).
 * - 결과 `parsed_items` + `low_confidence` → `OCRConfirmCard` inline render (form 대체).
 * - `onConfirm` → `confirmedRawText = formatParsedItemsToRawText(parsedItems)` 갱신 +
 *   `ocrConfirmed=true` → `MealInputForm` 재마운트(key 변경) — `defaultValues.raw_text` 갱신.
 * - `onRetake` → 사진 + parsedItems 전체 클리어 (form 초기 상태).
 * - 503 (Vision 장애) → Alert "사진 인식 일시 장애 — 텍스트로 다시 입력해주세요" +
 *   parsedItems=null + 사용자가 raw_text 직접 입력 가능 (NFR-I3 graceful degradation).
 * - PATCH 모드 prefill: `editingMeal.parsed_items` 보유 시 `parsedItems` + `ocrConfirmed=true`
 *   초기화 (이미 확인된 상태 — 사용자가 다시 분석 누르면 재 parse).
 * - `onSubmit` body: `parsed_items = parsedItems` (POST/PATCH 둘 다, ocrConfirmed=true 시).
 */
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { randomUUID } from 'expo-crypto';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, StyleSheet, View } from 'react-native';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import * as ImagePicker from 'expo-image-picker';

import { MealInputForm, type ImagePickKind } from '@/features/meals/MealInputForm';
import { OCRConfirmCard } from '@/features/meals/OCRConfirmCard';
import { PermissionDeniedView, type PermissionKind } from '@/features/meals/PermissionDeniedView';
import {
  MealImageUploadError,
  MealSubmitError,
  parseMealImage,
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
  ParsedMealItem,
} from '@/features/meals/mealSchema';
import { nowKstIso } from '@/features/meals/dateUtils';
import { formatParsedItemsToRawText } from '@/features/meals/parsedItemsFormat';
import { useAuth } from '@/lib/auth';
import {
  enqueueMealCreate,
  OfflineQueueFullError,
  OFFLINE_QUEUE_MAX_SIZE,
} from '@/lib/offline-queue';
import { useCameraPermission, useMediaLibraryPermission } from '@/lib/permissions';
import { useOnlineStatus } from '@/lib/use-online-status';

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
  // Story 2.5 — 오프라인 분기 + 큐잉 + 사진/PATCH 차단을 위한 상태.
  const { isOnline } = useOnlineStatus();
  const { user } = useAuth();

  const editingMeal = useMemo(
    () => (meal_id ? findMealInCache(queryClient, meal_id) : null),
    [meal_id, queryClient],
  );
  const isPatchMode = Boolean(meal_id);
  const isPatchCacheMiss = isPatchMode && !editingMeal;

  // Story 2.5 — PATCH 모드 진입 시 오프라인이면 즉시 차단(편집 자체는 *온라인 필수*).
  // 본 스토리 baseline은 *진입 차단*만 — PATCH 큐잉은 Story 8 polish (DF43).
  // CR P5 — ref guard로 *진입당 1회*만 fire (이전 구현은 매 render 시 Alert 스택 + back 과다 pop).
  const patchOfflineGuardFiredRef = useRef(false);
  useEffect(() => {
    if (!isPatchMode || isPatchCacheMiss) return;
    if (isOnline) {
      // 온라인 복귀 시 다시 가드 reset(같은 화면에서 토글 케이스).
      patchOfflineGuardFiredRef.current = false;
      return;
    }
    if (patchOfflineGuardFiredRef.current) return;
    patchOfflineGuardFiredRef.current = true;
    Alert.alert(
      '오프라인 상태',
      '오프라인에서는 식단 수정/삭제가 불가합니다. 온라인 시 다시 시도해주세요.',
      [
        {
          text: '확인',
          onPress: () => {
            router.back();
          },
        },
      ],
    );
  }, [isPatchMode, isPatchCacheMiss, isOnline]);

  // Story 2.2 — 사진 첨부 state.
  const [imageKey, setImageKey] = useState<string | null>(editingMeal?.image_key ?? null);
  const [imageLocalUri, setImageLocalUri] = useState<string | null>(
    editingMeal?.image_url ?? null,
  );
  // PATCH 모드에서만 의미 — *제거* 액션 후 PATCH 시 `image_key=null` 명시 송신 분기.
  const [imageClearedExplicitly, setImageClearedExplicitly] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [deniedState, setDeniedState] = useState<DeniedState | null>(null);

  // Story 2.3 — OCR Vision state.
  const [parsedItems, setParsedItems] = useState<ParsedMealItem[] | null>(
    editingMeal?.parsed_items ?? null,
  );
  const [lowConfidence, setLowConfidence] = useState<boolean>(false);
  const [isParsing, setIsParsing] = useState<boolean>(false);
  // PATCH 모드 prefill 시 이미 확인된 상태로 시작. POST 모드는 false (사용자 확인 필요).
  const [ocrConfirmed, setOcrConfirmed] = useState<boolean>(
    Boolean(editingMeal?.parsed_items),
  );
  // OCRConfirmCard `onConfirm` 시 form raw_text를 갱신할 때 form 재마운트 트리거 + 새 default.
  const [confirmedRawText, setConfirmedRawText] = useState<string | null>(null);
  // PATCH 모드에서만 — *parsed_items 명시 클리어* (재촬영 또는 사용자 명시 클리어).
  const [parsedItemsClearedExplicitly, setParsedItemsClearedExplicitly] = useState(false);

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

  // Story 2.3 — `confirmedRawText`는 OCR 확인 후 form 자동 prefill용. 사용자는 form에서
  // 추가 편집 가능 (마지막 수정값 우선). MealInputForm은 `defaultValues`를 mount 시점에만
  // 읽으므로 `key`로 재마운트 트리거 (`useForm` reset 회피 — props drilling 단순).
  const defaultValues: MealCreateFormData | undefined =
    confirmedRawText !== null
      ? { raw_text: confirmedRawText }
      : editingMeal
        ? { raw_text: editingMeal.raw_text }
        : undefined;
  const formKey = confirmedRawText !== null ? `confirmed:${confirmedRawText}` : 'initial';

  // Story 2.3 — OCRConfirmCard 노출 조건: parsedItems 있고, 사용자 확인 전, parse 진행 중 X.
  const showOcrConfirmCard =
    parsedItems !== null && !ocrConfirmed && !isParsing && imageKey !== null;

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
    // Story 2.5 — 사진 입력 오프라인 차단 (epic AC line 576). 권한 prompt 진입 차단으로
    // UX 명료성 (사용자가 권한 거부 흐름과 오프라인 흐름 혼동 회피).
    if (!isOnline) {
      Alert.alert(
        '오프라인 상태',
        '사진은 온라인에서 처리 가능 — 텍스트로 입력하거나 온라인 시 다시 시도해주세요.',
        [{ text: '확인' }],
      );
      return;
    }
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
    let uploadedKey: string | null = null;
    try {
      const uploaded = await uploadImageToR2(asset.uri, mime, declaredSize);
      // P8 — unmount 후 도달 시 setState 호출 회피 (React stale-state 경고 + memory leak).
      if (!isMountedRef.current) return;
      uploadedKey = uploaded.image_key;
      setImageKey(uploaded.image_key);
      setImageLocalUri(asset.uri);
      setImageClearedExplicitly(false);
      // Story 2.3 — 이전 분석 결과 클리어 (새 사진은 새 분석).
      setParsedItems(null);
      setLowConfidence(false);
      setOcrConfirmed(false);
      setParsedItemsClearedExplicitly(false);
      setConfirmedRawText(null);
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

    // Story 2.3 — 업로드 성공 후 자동 parse 호출 (chain).
    if (!uploadedKey || !isMountedRef.current) return;
    setIsParsing(true);
    try {
      const result = await parseMealImage(uploadedKey);
      if (!isMountedRef.current) return;
      setParsedItems(result.parsed_items);
      setLowConfidence(result.low_confidence);
    } catch (err) {
      if (!isMountedRef.current) return;
      // NFR-I3 graceful degradation — 503/502 모두 동일 alert + raw_text 직접 입력 fallback.
      const isOcrError =
        err instanceof MealSubmitError && (err.status === 503 || err.status === 502);
      if (isOcrError) {
        Alert.alert(
          '사진 인식 일시 장애',
          '텍스트로 다시 입력해주세요. (사진은 그대로 유지)',
        );
      } else if (err instanceof MealSubmitError) {
        // 401/403/400 등은 일반 핸들러로.
        handleSubmitError(err);
      } else {
        Alert.alert('사진 인식 실패', '잠시 후 다시 시도해주세요.');
      }
      setParsedItems(null);
      setLowConfidence(false);
    } finally {
      if (isMountedRef.current) {
        setIsParsing(false);
      }
    }
  };

  const handleClearImage = () => {
    setImageKey(null);
    setImageLocalUri(null);
    setParsedItems(null);
    setLowConfidence(false);
    setOcrConfirmed(false);
    setConfirmedRawText(null);
    if (isPatchMode) {
      setImageClearedExplicitly(true);
      setParsedItemsClearedExplicitly(true);
    }
  };

  // Story 2.3 — OCRConfirmCard 콜백 ----------------------------------------

  const handleConfirmOCR = () => {
    if (!parsedItems) return;
    // form `raw_text` 자동 갱신 — 사용자는 이후 form에서 추가 편집 가능.
    setConfirmedRawText(formatParsedItemsToRawText(parsedItems));
    setOcrConfirmed(true);
  };

  const handleRetakePhoto = () => {
    setImageKey(null);
    setImageLocalUri(null);
    setParsedItems(null);
    setLowConfidence(false);
    setOcrConfirmed(false);
    setConfirmedRawText(null);
    if (isPatchMode) {
      setImageClearedExplicitly(true);
      setParsedItemsClearedExplicitly(true);
    }
  };

  const handleChangeParsedItems = (items: ParsedMealItem[]) => {
    setParsedItems(items);
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

    // Story 2.5 — POST 모드 + 오프라인 분기. PATCH 모드는 진입 시 차단(useEffect)되므로 분기 X.
    if (!isPatchMode && !isOnline) {
      // 사진 첨부된 상태에서 오프라인 저장 시도는 차단 (사진 큐잉 OUT — epic AC line 576).
      if (hasImage || (ocrConfirmed && parsedItems)) {
        Alert.alert(
          '오프라인 상태',
          '오프라인에서는 사진 입력을 저장할 수 없어요. 텍스트만 입력하거나 온라인 시 다시 시도해주세요.',
        );
        return;
      }
      if (!user) {
        // 정상 흐름에서는 도달 불가(인증 가드 통과 가정) — 방어 로깅 + 안내.
        Alert.alert('오류', '사용자 정보를 불러오지 못했어요. 다시 로그인해주세요.');
        return;
      }
      // 텍스트-only → 큐잉. ate_at은 큐잉 시점 KST(현재 시각) 자동 채움 — 사용자가 큐잉한
      // 시점이 식단 시점이라는 직관 정합 (서버 fallback은 *flush 시점*이라 의미 differs).
      void (async () => {
        try {
          await enqueueMealCreate(user.id, {
            client_id: randomUUID(),
            raw_text: trimmedRawText,
            // CR P7 — D3 정합: KST `+09:00` offset 명시 (`toISOString()` 사용 시 `Z` UTC).
            ate_at: nowKstIso(),
            parsed_items: null,
          });
          Alert.alert(
            '오프라인 — 동기화 대기',
            '온라인 복귀 시 자동으로 동기화됩니다.',
            [
              {
                text: '확인',
                onPress: () => {
                  const target = '/(tabs)/meals' as Parameters<typeof router.replace>[0];
                  router.replace(target);
                },
              },
            ],
          );
        } catch (err) {
          if (err instanceof OfflineQueueFullError) {
            Alert.alert(
              '오프라인 대기 항목이 너무 많아요',
              `대기 항목이 ${OFFLINE_QUEUE_MAX_SIZE}건을 초과했습니다. 온라인 복귀 후 동기화한 뒤 다시 시도해주세요.`,
            );
          } else {
            Alert.alert('오프라인 큐잉 실패', '잠시 후 다시 시도해주세요.');
          }
        }
      })();
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
      // Story 2.3 — parsed_items 분기.
      if (parsedItemsClearedExplicitly) {
        body.parsed_items = null;
      } else if (ocrConfirmed && parsedItems) {
        body.parsed_items = parsedItems;
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
      // Story 2.3 — POST 시 parsed_items 첨부 (OCR 확인된 케이스만).
      if (ocrConfirmed && parsedItems) body.parsed_items = parsedItems;
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
      {showOcrConfirmCard && parsedItems ? (
        <OCRConfirmCard
          items={parsedItems}
          lowConfidence={lowConfidence}
          onChangeItems={handleChangeParsedItems}
          onConfirm={handleConfirmOCR}
          onRetake={handleRetakePhoto}
          isSubmitting={isSubmitting}
        />
      ) : (
        <MealInputForm
          key={formKey}
          defaultValues={defaultValues}
          isSubmitting={isSubmitting || isParsing}
          submitLabel={submitLabel}
          onSubmit={onSubmit}
          serverError={serverError}
          onClearServerError={() => setServerError(null)}
          imageKey={imageKey}
          imageLocalUri={imageLocalUri}
          onPickImage={(kind) => void handlePickImage(kind)}
          onClearImage={handleClearImage}
          isUploading={isUploading || isParsing}
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
});
