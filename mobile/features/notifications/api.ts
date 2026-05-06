/**
 * Story 4.1 AC11 — `/v1/notifications/*` TanStack Query hooks.
 *
 * 4 hook:
 * - `useNotificationSettingsQuery()` — `GET /v1/notifications/settings`
 * - `useUpdateNotificationSettingsMutation()` — `PATCH /v1/notifications/settings`
 * - `useRegisterPushTokenMutation()` — `POST /v1/notifications/devices`
 * - `useRevokePushTokenMutation()` — `DELETE /v1/notifications/devices`
 *
 * 모든 mutation은 성공 시 `['notifications', 'settings']` 무효화 (`has_push_token` /
 * `notifications_enabled` / `notification_time` 갱신을 화면이 즉시 반영).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { authFetch } from '@/lib/auth';

import {
  NotificationApiError,
  NotificationSettingsResponseSchema,
  type NotificationSettings,
  type NotificationSettingsUpdate,
  type PushTokenRegisterRequest,
} from './notificationSchema';

const QUERY_KEY = ['notifications', 'settings'] as const;

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

async function fetchSettings(): Promise<NotificationSettings> {
  const response = await authFetch('/v1/notifications/settings');
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new NotificationApiError(response.status, problem.code, problem.detail);
  }
  const raw = await response.json();
  return NotificationSettingsResponseSchema.parse(raw);
}

async function patchSettings(
  body: NotificationSettingsUpdate,
): Promise<NotificationSettings> {
  const response = await authFetch('/v1/notifications/settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new NotificationApiError(response.status, problem.code, problem.detail);
  }
  const raw = await response.json();
  return NotificationSettingsResponseSchema.parse(raw);
}

async function postDevice(body: PushTokenRegisterRequest): Promise<void> {
  const response = await authFetch('/v1/notifications/devices', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new NotificationApiError(response.status, problem.code, problem.detail);
  }
}

async function deleteDevice(): Promise<void> {
  const response = await authFetch('/v1/notifications/devices', {
    method: 'DELETE',
  });
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new NotificationApiError(response.status, problem.code, problem.detail);
  }
}

export function useNotificationSettingsQuery() {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: fetchSettings,
    // staleTime: 0 — 사용자 변경 즉시 반영 (Switch 토글, TimePicker 변경).
    staleTime: 0,
  });
}

export function useUpdateNotificationSettingsMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: patchSettings,
    onSuccess: (data) => {
      // 서버 응답을 cache에 즉시 박아 화면 동기화 (refetch 한 round-trip 절약).
      queryClient.setQueryData(QUERY_KEY, data);
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

export function useRegisterPushTokenMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: postDevice,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

export function useRevokePushTokenMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteDevice,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}
