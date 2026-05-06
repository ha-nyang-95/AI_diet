/**
 * Story 4.1 AC11 — 알림 설정 + push token 등록 wire format Zod 스키마 + typed error.
 *
 * Story 2.x `mealSchema.ts` 패턴 정합 — 백엔드 `NotificationSettingsResponse` /
 * `NotificationSettingsUpdate` / `PushTokenRegisterRequest` 1:1.
 */
import { z } from 'zod';

// `HH:MM` 24시간제 — 백엔드 `_NOTIFICATION_TIME_WIRE_RE` 정합.
const TIME_RE = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;
// Expo 표준 prefix — 백엔드 `_EXPO_TOKEN_RE` 정합.
const EXPO_TOKEN_RE = /^Expo(nent)?PushToken\[[A-Za-z0-9\-_]{16,}\]$/;

export const NotificationSettingsResponseSchema = z.object({
  notifications_enabled: z.boolean(),
  notification_time: z.string().regex(TIME_RE),
  notification_timezone: z.string(),
  has_push_token: z.boolean(),
});
export type NotificationSettings = z.infer<typeof NotificationSettingsResponseSchema>;

export const NotificationSettingsUpdateSchema = z
  .object({
    notifications_enabled: z.boolean().optional(),
    notification_time: z.string().regex(TIME_RE).optional(),
  })
  .strict();
export type NotificationSettingsUpdate = z.infer<typeof NotificationSettingsUpdateSchema>;

export const PushTokenRegisterRequestSchema = z
  .object({
    expo_push_token: z.string().regex(EXPO_TOKEN_RE),
    platform: z.enum(['ios', 'android', 'web']),
  })
  .strict();
export type PushTokenRegisterRequest = z.infer<typeof PushTokenRegisterRequestSchema>;

/**
 * `MealSubmitError` 패턴 정합 — typed status + code + detail.
 */
export class NotificationApiError extends Error {
  status: number;
  code?: string;
  detail?: string;

  constructor(status: number, code?: string, detail?: string) {
    super(detail ?? `notification request failed (${status})`);
    this.name = 'NotificationApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}
