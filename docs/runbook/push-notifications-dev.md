# Push Notifications — Dev SOP (Story 4.1 / Story 4.2)

**Audience**: 모바일 / 백엔드 개발자.
**Purpose**: Expo push 알림 token을 dev에서 발급·검증 + 백엔드 cron sweep 검증.
**Last updated**: 2026-05-06 (Story 4.2 — APScheduler nudge cron + 딥링크 wire 추가).

---

## 1. Expo Go 한계 (SDK 53+)

Expo SDK 53부터 **Expo Go에서는 remote push token 발급이 불가**합니다 — `Notifications.getExpoPushTokenAsync()` 호출 시 token이 발급되지 않습니다(서버 측에서 Expo Go의 push token을 취소했기 때문).

`mobile/lib/push.ts:registerForPushNotificationsAsync`는 `Constants.appOwnership === 'expo'` 분기로 token 발급을 skip하고 `console.warn` 출력 — 앱은 정상 동작하지만 *실 token 발급은 EAS dev build 또는 standalone build에서만* 가능.

dev 권한 prompt / Switch 토글 / 설정 화면 UI는 Expo Go에서도 정상 검증 가능합니다(UI 흐름만 검증 시 EAS build 무필요).

---

## 2. EAS dev build 절차 (실 token 발급)

### 2.1 환경변수 준비

`mobile/.env` 또는 EAS Console secret에 다음 추가:

```
EXPO_PUBLIC_EAS_PROJECT_ID=<eas-project-uuid>
```

EAS projectId는 `expo init` 또는 `eas project:init` 시 자동 발급. 기존 프로젝트는 [EAS Console](https://expo.dev/accounts/<account>/projects)에서 확인.

### 2.2 dev build

```
cd mobile
eas build --profile development --platform ios
# 또는
eas build --profile development --platform android
```

빌드 완료 후 발급된 `.ipa` / `.apk`를 device에 설치 → `expo start --dev-client`로 dev server 연결.

### 2.3 권한 prompt 확인

앱 첫 진입 시 OS 알림 권한 prompt 자동 노출(AC12 first-time prompt 흐름). 허용 시 `app/(tabs)/_layout.tsx`의 useEffect가 자동으로 backend POST `/v1/notifications/devices` 호출 → DB `users.expo_push_token` set.

---

## 3. iOS 설정

### 3.1 Info.plist (Expo가 자동 처리)

`expo-notifications` plugin이 자동으로 다음을 prebuild에 주입:

- `NSUserNotificationUsageDescription` (사용자 친화 문자열은 Expo default)

별도 plist override는 영업 자료 시점(Story 8.6)에 추가.

### 3.2 aps-environment entitlement

iOS는 push 발송을 위해 entitlement 필요. EAS dev build는 자동 처리되지만, prod 배포 시 Apple Developer Console에서 **APNs 키** 등록 + EAS Console `eas credentials`로 업로드 필요(Story 8.5 클라우드 hardening runbook 정합).

---

## 4. Android FCM v1 credentials

Android는 FCM v1 API를 통해 push 발송 — Firebase Console 프로젝트 + service account JSON 필요.

```
eas credentials -p android
# → "Push Notifications: FCM V1" → "Set up a Firebase Service Account Key"
```

Firebase Console에서 발급한 `service-account-key.json`을 EAS에 업로드 → 자동으로 푸시 send 시 사용. dev build는 sandbox 모드로 자동 동작.

---

## 5. 실 push 발송 dev 검증

token 발급 확인 후 [Expo Push Notifications Tool](https://expo.dev/notifications)에서 즉시 검증 가능.

1. token을 form에 붙여넣기.
2. Title / Body 입력.
3. **Send a Notification** 클릭.
4. device에 push 도달 — tap → 앱 진입 또는 background에서 알림 표시.

서버 측 send는 **Story 4.2에서 도입됨** — `app/workers/nudge_scheduler.py` cron이 매 30분 KST sweep + Expo push send. 자세한 dev 검증 절차는 §8 *Cron sweep dev 검증* 참조.

---

## 6. 권한 거부 후 회복 SOP

사용자가 첫 prompt에서 *"Don't Allow"* 선택 후 회복하려면:

1. **iOS**: 설정 앱 > BalanceNote > 알림 > **알림 허용** ON.
2. **Android API 33+**: 설정 앱 > 앱 > BalanceNote > 알림 > **모든 알림 허용** ON.
3. 앱 재진입 → `(tabs)/settings/notifications` 화면 → Switch ON 또는 *"다시 요청"* 버튼 (`canAskAgain=false`인 경우 *"설정 열기"* 버튼만 노출).

OEM Android에서 `Linking.openSettings()` deep link가 silent fail하는 경우 `PermissionDeniedView`의 catch 핸들러가 사용자에게 *"기기 설정 > 앱 권한에서 직접 허용해주세요"* Alert 노출(Story 2.2 P13 패턴 정합).

---

## 7. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `console.warn: push.expo_go_skip` | Expo Go에서 token 발급 시도 | EAS dev build 사용 |
| `console.warn: push.project_id_missing` | `EXPO_PUBLIC_EAS_PROJECT_ID` 미설정 | `.env` 또는 EAS Console에 추가 |
| `console.warn: push.token.fetch_failed` | network / EAS API 일시 장애 | retry 또는 EAS service status 확인 |
| `400 notification.token.invalid` | backend POST `/devices` body의 token이 Expo prefix 위반 | `mobile/lib/push.ts`의 token 발급 흐름 확인 (raw token이 `ExponentPushToken[…]` 형식인지) |
| Switch ON 후 Switch OFF (UI 자동 회귀) | OS 권한 거부 → `registerForPushNotificationsAsync` `status='denied'` → 상위 mutation 미진행 | 정상 동작 — `PermissionDeniedView` modal로 사용자 안내 |

---

## 8. Cron sweep dev 검증 (Story 4.2)

서버 측 `app/workers/nudge_scheduler.py` cron이 매 30분 KST sweep — *알림 ON + 권한 OK + 알림 시간 + 30분 경과 + 당일 식단 미입력* 사용자에게 push 발송. dev에서 자연 cron(30분 대기)이 부담스러우면 직접 호출로 검증.

### 8.1 환경변수

```
EXPO_ACCESS_TOKEN=                   # EAS Console > Access Tokens (없으면 빈 문자열도 dev OK — Expo SDK 자체 무인증 모드 허용)
ENVIRONMENT=dev                      # ci/test는 cron 자동 disable (`app/workers/scheduler.py` SOT)
```

prod에서 EAS *enhanced security mode* 활성 시 token 필수 — 401 응답 시 `ExpoPushAuthError` raise + Sentry alert. 키 회전: `docs/runbook/secret-rotation.md` §4 참조.

### 8.2 사용자 fixture 셋업

dev DB에 다음 조건 사용자 1건:

```sql
UPDATE users
SET notifications_enabled = true,
    notification_time = '20:00:00',          -- cron이 20:30 cycle에서 매칭(notification_time + 30min = 20:30)
    expo_push_token = 'ExponentPushToken[<EAS dev build에서 발급한 실 token>]'
WHERE id = '<your-user-id>';

DELETE FROM meals
WHERE user_id = '<your-user-id>'
  AND ate_at AT TIME ZONE 'Asia/Seoul' >= CURRENT_DATE;
```

당일 식단 0건 + 동일 날 동일 kind ``notifications`` 행 미존재 보장.

### 8.3 sweep 직접 호출

```python
# api/scripts/run_nudge_sweep_once.py (없으면 임시 작성 — 운영자용 SOP)
import asyncio

from app.main import app
from app.workers.nudge_scheduler import sweep_unrecorded_meals

async def main() -> None:
    async with app.router.lifespan_context(app):
        stats = await sweep_unrecorded_meals(app.state.session_maker)
        print(stats)

asyncio.run(main())
```

또는 Python REPL에서 동일 호출. 출력 stats:

```
{
  "users_eligible_count": 1,
  "nudges_sent_count": 1,
  "device_not_registered_count": 0,
  "transient_error_count": 0,
}
```

### 8.4 자연 cron 검증

`uv run uvicorn app.main:app`로 dev server 시작 → 30분 단위 cron이 자동 fire(`apscheduler --debug`로 backgrounnd 잡 trace 가능). lifespan log:

```
[info] scheduler.started timezone=Asia/Seoul
[info] nudge.job.registered job_id=nudge_sweep_unrecorded_meals
[info] nudge.sweep.start now_kst=2026-05-06T20:30:00+09:00
[info] nudge.sweep.eligible user_count=1
[info] nudge.sent user_id=u_abc12345 ticket_id=...
```

### 8.5 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `nudge.sweep.eligible user_count=0` | sweep query 미매칭 | 8.2 fixture 재확인 — `notification_time + 30min`이 sweep cycle 윈도우에 포함되는지 |
| `nudge.skipped reason=device_not_registered` | EAS가 token revoke (앱 삭제 등) | 정상 — `expo_push_token` NULL set + 다음 cycle 자동 제외 |
| `nudge.skipped reason=adapter_error:ExpoPushAuthError` | EAS access token 만료 | `docs/runbook/secret-rotation.md` §4 회전 SOP |
| `scheduler.start.disabled_for_environment` | environment in {ci,test} | 정상 — pytest 격리 정합 |

---

## See also

- `docs/runbook/deployment.md` §4 — 배포 시 EAS credentials 검증.
- `docs/runbook/secret-rotation.md` §4 — `EXPO_ACCESS_TOKEN` 회전 5단계.
- Story 8.5 클라우드 배포 hardening runbook — APNs 키 / FCM v1 prod 검증 절차.
