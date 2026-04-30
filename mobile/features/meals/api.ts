/**
 * Story 2.1 + 2.2 + 2.3 — `/v1/meals` + `/v1/meals/images` TanStack Query hooks.
 *
 * - `useMealsQuery`              — `GET /v1/meals?from_date=&to_date=&limit=`
 * - `useCreateMealMutation`      — `POST /v1/meals`
 * - `useUpdateMealMutation`      — `PATCH /v1/meals/{meal_id}`
 * - `useDeleteMealMutation`      — `DELETE /v1/meals/{meal_id}`
 * - `useImagePresignMutation`    — `POST /v1/meals/images/presign` (Story 2.2)
 * - `uploadImageToR2`            — `presign + R2 PUT 2-step` async helper (Story 2.2)
 * - `useParseMealImageMutation`  — `POST /v1/meals/images/parse` (Story 2.3)
 * - `parseMealImage`             — async helper (Story 2.3)
 *
 * 모든 mutation은 성공 시 `['meals']` 무효화 — list 자동 refetch. optimistic update
 * 회피 (yagni — 실패 시 rollback 복잡, baseline은 단순; Story 8 polish 시점 도입).
 *
 * `MealSubmitError` 패턴은 Story 1.5 `ProfileSubmitError`와 1:1 정합 — typed status +
 * code + detail. `MealImageUploadError`는 R2 PUT 실패(network / timeout) 분기.
 *
 * Story 2.3 parse mutation은 read-only 분석 호출(meal 상태 변경 X) — `invalidateQueries`
 * 미적용. timeout은 백엔드 30초 hard cap에 위임 (모바일 별도 AbortController 도입은
 * Story 2.2 업로드 timeout과 *역할 분리* — 업로드는 사용자 stuck 차단, parse는 백엔드 신뢰).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { randomUUID } from 'expo-crypto';

import { authFetch } from '@/lib/auth';

import type {
  MealCreateRequest,
  MealImageParseRequest,
  MealImageParseResponse,
  MealImagePresignRequest,
  MealImagePresignResponse,
  MealListResponse,
  MealResponse,
  MealUpdateRequest,
  MealsListQuery,
} from './mealSchema';

// 모바일 4G 가정 — 10 MB 업로드 ≤ 25초. 30초 hard cap로 stuck upload 방지.
const R2_UPLOAD_TIMEOUT_MS = 30_000;

export class MealSubmitError extends Error {
  status: number;
  code?: string;
  detail?: string;

  constructor(status: number, code?: string, detail?: string) {
    super(detail ?? `meal request failed (${status})`);
    this.name = 'MealSubmitError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

/**
 * Story 2.2 — R2 PUT 직접 업로드 실패 (presign 단계는 `MealSubmitError`).
 *
 * `status`는 R2 응답 status, fetch reject 시 'network', AbortController 시 'timeout'.
 */
export class MealImageUploadError extends Error {
  status: number | 'timeout' | 'network';
  imageKey?: string;
  detail?: string;

  constructor(status: number | 'timeout' | 'network', imageKey?: string, detail?: string) {
    super(detail ?? `image upload failed (${status})`);
    this.name = 'MealImageUploadError';
    this.status = status;
    this.imageKey = imageKey;
    this.detail = detail;
  }
}

async function _parseProblem(
  response: Response,
): Promise<{ code?: string; detail?: string }> {
  try {
    const problem = (await response.json()) as { code?: string; detail?: string };
    return { code: problem.code, detail: problem.detail };
  } catch {
    return {};
  }
}

function buildMealsQueryString(params: MealsListQuery | undefined): string {
  if (!params) return '';
  const usp = new URLSearchParams();
  if (params.from_date) usp.set('from_date', params.from_date);
  if (params.to_date) usp.set('to_date', params.to_date);
  if (params.limit !== undefined) usp.set('limit', String(params.limit));
  const qs = usp.toString();
  return qs ? `?${qs}` : '';
}

async function fetchMeals(params: MealsListQuery | undefined): Promise<MealListResponse> {
  const response = await authFetch(`/v1/meals${buildMealsQueryString(params)}`);
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new MealSubmitError(response.status, problem.code, problem.detail);
  }
  return (await response.json()) as MealListResponse;
}

/**
 * Story 2.5 — `Idempotency-Key` 자동 첨부 (W46 흡수). UUID v4는 호출 측이 생성하거나
 * 미지정 시 기본 ``randomUUID()`` 1회 자동 생성. 서버 partial UNIQUE + 200 idempotent
 * replay로 앱 백그라운드/킬 mid-mutation 중복 POST 차단.
 *
 * `opts.idempotencyKey`가 명시되면 헤더 첨부, 미명시 시 자동 생성. 회귀 차단을 위해
 * 명시적 `null` 송신은 헤더 미첨부 (legacy fallback) — but 본 스토리 baseline에서는
 * 항상 자동 생성 (`useCreateMealMutation` 정합).
 */
async function createMeal(
  body: MealCreateRequest,
  opts?: { idempotencyKey?: string | null },
): Promise<MealResponse> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (opts?.idempotencyKey != null) {
    headers['Idempotency-Key'] = opts.idempotencyKey;
  }
  const response = await authFetch('/v1/meals', {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new MealSubmitError(response.status, problem.code, problem.detail);
  }
  return (await response.json()) as MealResponse;
}

async function updateMeal(args: {
  meal_id: string;
  body: MealUpdateRequest;
}): Promise<MealResponse> {
  const response = await authFetch(`/v1/meals/${args.meal_id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args.body),
  });
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new MealSubmitError(response.status, problem.code, problem.detail);
  }
  return (await response.json()) as MealResponse;
}

async function deleteMeal(meal_id: string): Promise<void> {
  const response = await authFetch(`/v1/meals/${meal_id}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new MealSubmitError(response.status, problem.code, problem.detail);
  }
  // 204 No Content — body 없음.
}

// --- Story 2.2 R2 presigned URL + 직접 업로드 ---

async function requestPresignedUpload(
  body: MealImagePresignRequest,
): Promise<MealImagePresignResponse> {
  const response = await authFetch('/v1/meals/images/presign', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new MealSubmitError(response.status, problem.code, problem.detail);
  }
  return (await response.json()) as MealImagePresignResponse;
}

/**
 * Story 2.2 — file URI를 R2에 직접 PUT (백엔드 proxy 회피, Railway egress 비용/메모리
 * 폭발 방지). 2-step:
 * 1. `POST /v1/meals/images/presign` → upload_url + image_key + public_url 수신.
 * 2. RN `fetch(upload_url, { method: 'PUT', body: blob })` → R2 직접 PUT.
 *
 * 30초 timeout(`AbortController`) — 모바일 4G 가정. 초과 시 `MealImageUploadError("timeout")`.
 *
 * 호출자(`(tabs)/meals/input.tsx`)는 반환된 `image_key`를 `MealCreateRequest.image_key`로
 * 전달. `public_url`은 썸네일 표시용 (R2 public read).
 *
 * P5 — 현재는 RN `fetch(uri).blob()` 패턴 유지(10 MB 한도 + RN 0.81 안정). expo-file-system
 * `uploadAsync` BINARY_CONTENT 모드로 streaming 전환은 Story 8 polish (DF3 — 의존성 추가
 * scope creep 회피). 본 함수는 *full-buffer PUT* 가정 — heap 50 MB 정도 여유 필요.
 *
 * P7 — `controller.signal.aborted` 체크로 RN AbortError name 변종(`AbortError` vs
 * `DOMException`) 호환성 보강. clearTimeout은 finally 단일 위치(중복 호출 방지).
 *
 * P21 — 백엔드 POST/PATCH `/v1/meals`에 `head_object` HEAD-check 도입(D1) → 본 함수 호출
 * 후 image_key가 R2에 실제 PUT됐는지 서버가 검증. 즉 PUT 실패 시 클라이언트는 본 함수에서
 * `MealImageUploadError`로 차단되거나(직접), 서버 attach 단계에서 `meals.image.not_uploaded`
 * 400으로 차단(간접 — race 케이스 cover).
 */
export async function uploadImageToR2(
  uri: string,
  contentType: MealImagePresignRequest['content_type'],
  contentLength: number,
): Promise<{ image_key: string; public_url: string }> {
  // Step 1 — presign (백엔드 인증·동의·검증 게이트 통과).
  const presigned = await requestPresignedUpload({
    content_type: contentType,
    content_length: contentLength,
  });

  // Step 2 — file URI → blob → R2 PUT.
  // RN `fetch(uri).blob()`는 file URI를 Blob으로 변환 가능 (HEIC/HEIF 포함 raw bytes 보존).
  const fileResponse = await fetch(uri);
  const blob = await fileResponse.blob();

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), R2_UPLOAD_TIMEOUT_MS);

  let putResponse: Response;
  try {
    putResponse = await fetch(presigned.upload_url, {
      method: 'PUT',
      headers: { 'Content-Type': contentType },
      body: blob,
      signal: controller.signal,
    });
  } catch (err) {
    // P7 — `controller.signal.aborted` 체크가 RN AbortError name 변종 호환에 안전
    // (Error name이 `AbortError` 또는 `DOMException`로 다름). clearTimeout은 finally에 단일.
    if (controller.signal.aborted) {
      throw new MealImageUploadError('timeout', presigned.image_key, '업로드 시간 초과');
    }
    throw new MealImageUploadError(
      'network',
      presigned.image_key,
      err instanceof Error ? err.message : 'network error',
    );
  } finally {
    clearTimeout(timeoutId);
  }

  if (!putResponse.ok) {
    throw new MealImageUploadError(
      putResponse.status,
      presigned.image_key,
      `R2 PUT failed (${putResponse.status})`,
    );
  }

  return {
    image_key: presigned.image_key,
    public_url: presigned.public_url,
  };
}

export function useMealsQuery(params?: MealsListQuery) {
  return useQuery({
    // params를 query key에 직접 spread하지 않고 직렬화 가능한 plain object로 forward.
    queryKey: ['meals', params ?? {}],
    queryFn: () => fetchMeals(params),
  });
}

/**
 * Story 2.5 — `useCreateMealMutation`은 매 mutate 호출 시 ``randomUUID()``로
 * Idempotency-Key 자동 생성 + 헤더 첨부 (W46 흡수). 호출 측은 변경 X — 단순 `mutate(body)`.
 * 같은 mutate 재호출은 매번 새 UUID — *키 == 한 번* 시맨틱 (Stripe/Toss 정합).
 *
 * 오프라인 큐잉은 hook 외부 책임 — `(tabs)/meals/input.tsx`가 `useOnlineStatus`
 * `!isOnline` 시 `enqueueMealCreate(...)` 직접 호출. hook은 *온라인 가정*.
 */
export function useCreateMealMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: MealCreateRequest) => createMeal(body, { idempotencyKey: randomUUID() }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['meals'] });
    },
  });
}

export function useUpdateMealMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateMeal,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['meals'] });
    },
  });
}

export function useDeleteMealMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteMeal,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['meals'] });
    },
  });
}

/**
 * Story 2.2 — `POST /v1/meals/images/presign` mutation.
 *
 * 본 스토리 baseline에서는 `uploadImageToR2`가 inline `requestPresignedUpload`를 호출해
 * 직접 사용 X. forward-compat hook export — Story 4.1 알림 설정 또는 W43 디버그 polish
 * 시점에 활용 가능 (예: 진행률 표시 + cancel 버튼).
 */
export function useImagePresignMutation() {
  return useMutation({
    mutationFn: requestPresignedUpload,
  });
}

// --- Story 2.3 — Vision OCR parse ---

/**
 * Story 2.3 — `POST /v1/meals/images/parse` 단일 호출 helper.
 *
 * 부모 컴포넌트가 R2 업로드 성공 후 `image_key`로 호출 → `parsed_items` + `low_confidence`
 * 수신. 결과는 `OCRConfirmCard`로 forward + 사용자 확인 후 `MealCreateRequest.parsed_items`
 * 첨부.
 *
 * 에러 분기:
 * - 401 — `authFetch`가 자동 처리.
 * - 401/403/400 → `MealSubmitError` throw — 부모가 처리(`consent.basic.missing` 등).
 * - 503 (`meals.image.ocr_unavailable` / `meals.image.r2_unconfigured` /
 *   `meals.image.ocr_image_url_missing`) → `MealSubmitError(503)` throw — 부모가
 *   "사진 인식 일시 장애 — 텍스트로 다시 입력해주세요" Alert (NFR-I3 graceful degradation).
 * - 502 (`meals.image.ocr_payload_invalid`) → 동일 alert + Sentry 자동 capture (Story 8).
 *
 * timeout: 백엔드 30초 hard cap에 위임 — 모바일은 별도 AbortController 미도입.
 */
export async function parseMealImage(image_key: string): Promise<MealImageParseResponse> {
  const body: MealImageParseRequest = { image_key };
  const response = await authFetch('/v1/meals/images/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new MealSubmitError(response.status, problem.code, problem.detail);
  }
  return (await response.json()) as MealImageParseResponse;
}

/**
 * Story 2.3 — `POST /v1/meals/images/parse` mutation hook.
 *
 * `useMutation`을 활용한 ergonomic wrapper — `isPending` 표시(`isParsing`)를 부모가
 * spinner UI로 활용. parse는 *read-only 분석*이라 `invalidateQueries` 미적용 (meal
 * 상태 변경 X).
 */
export function useParseMealImageMutation() {
  return useMutation({
    mutationFn: parseMealImage,
  });
}
