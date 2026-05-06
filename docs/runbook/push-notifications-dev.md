# Push Notifications — Dev SOP (Story 4.1)

**Audience**: 모바일 개발자.
**Purpose**: Expo push 알림 token을 dev에서 발급·검증하기 위한 단계별 절차.
**Last updated**: 2026-05-06 (Story 4.1).

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

서버 측 send는 Story 4.2에서 APScheduler cron + Python `exponent_server_sdk`로 일별 발송 (본 Story 4.1 OUT — token 등록까지만).

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

## See also

- `docs/runbook/deployment.md` §4 — 배포 시 EAS credentials 검증.
- Story 4.2 (APScheduler nudge 미기록 푸시) — 본 token을 소비해 일별 push 발송.
- Story 8.5 클라우드 배포 hardening runbook — APNs 키 / FCM v1 prod 검증 절차.
