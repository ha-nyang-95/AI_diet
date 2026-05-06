/**
 * Story 4.1 AC10 — 알림 설정 화면.
 *
 * - Switch: 미기록 식단 알림 ON/OFF (`notifications_enabled`).
 *   ON 전환 시 권한 prompt + token 등록 (denied면 PermissionDeniedView 노출).
 * - 시간 선택: 시 단위 정수 picker + 분 단위 정수 picker (RN Modal 자체 구현 — 신규
 *   의존성 회피). MVP 기준 분 단위는 5분 간격(0/5/10/15/...) — 자유 입력은 Story 8.4
 *   polish forward.
 * - 권한 OFF 배너: `useNotificationPermission().status !== 'granted'` 시 화면 상단
 *   *"알림 허용 안 됨 — 설정 열기"* (`Linking.openSettings()` + OEM Android Alert fallback).
 */
import { Stack } from 'expo-router';
import { useState } from 'react';
import {
  Alert,
  Linking,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from 'react-native';

import { PermissionDeniedView } from '@/features/notifications/PermissionDeniedView';
import {
  useNotificationSettingsQuery,
  useRegisterPushTokenMutation,
  useUpdateNotificationSettingsMutation,
} from '@/features/notifications/api';
import { useNotificationPermission } from '@/lib/permissions';
import { registerForPushNotificationsAsync } from '@/lib/push';

const HOURS = Array.from({ length: 24 }, (_, i) => i);
const MINUTES = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55];

function formatTime(wire: string): string {
  // wire `"HH:MM"` → display `"오후 8:00"`.
  const [hh, mm] = wire.split(':').map(Number);
  const period = hh < 12 ? '오전' : '오후';
  const hour12 = hh === 0 ? 12 : hh > 12 ? hh - 12 : hh;
  return `${period} ${hour12}:${String(mm).padStart(2, '0')}`;
}

export default function NotificationsSettingsScreen() {
  const settingsQuery = useNotificationSettingsQuery();
  const updateMutation = useUpdateNotificationSettingsMutation();
  const registerMutation = useRegisterPushTokenMutation();
  const permission = useNotificationPermission();
  const [showTimePicker, setShowTimePicker] = useState(false);
  const [permissionDeniedModal, setPermissionDeniedModal] = useState(false);

  const settings = settingsQuery.data;

  const handleSwitchToggle = async (next: boolean) => {
    if (next) {
      // ON 전환 — 권한 prompt + token 등록 흐름.
      const { status, token } = await registerForPushNotificationsAsync();
      if (status !== 'granted') {
        // 권한 거부 — Switch는 OFF 유지, denied modal 노출.
        setPermissionDeniedModal(true);
        return;
      }
      // 권한 OK — 설정 ON 저장.
      await updateMutation.mutateAsync({ notifications_enabled: true });
      if (token) {
        try {
          await registerMutation.mutateAsync({
            expo_push_token: token,
            platform: 'ios', // dev 단순화 — 실제 platform 분기는 Story 8.4 polish (Platform.OS).
          });
        } catch {
          // graceful — UI는 *"알림 등록 실패 — 잠시 후 다시 시도"* (Story 8.4 polish 자동 retry).
        }
      }
    } else {
      // OFF 전환 — 단순 setting update (token은 보존; revoke는 logout flow에서).
      await updateMutation.mutateAsync({ notifications_enabled: false });
    }
  };

  const handleTimeSelect = async (hour: number, minute: number) => {
    const wire = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
    await updateMutation.mutateAsync({ notification_time: wire });
    setShowTimePicker(false);
  };

  const openSettings = () => {
    Linking.openSettings().catch(() => {
      Alert.alert(
        '설정을 열 수 없어요',
        '기기 설정 > 앱 권한에서 직접 허용해주세요.',
      );
    });
  };

  if (settingsQuery.isLoading) {
    return (
      <View style={styles.container}>
        <Stack.Screen options={{ title: '알림 설정' }} />
        <Text style={styles.loadingText}>불러오는 중...</Text>
      </View>
    );
  }

  if (!settings) {
    return (
      <View style={styles.container}>
        <Stack.Screen options={{ title: '알림 설정' }} />
        <Text style={styles.errorText}>설정을 불러올 수 없어요.</Text>
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: '알림 설정' }} />

      {permission.status !== 'granted' ? (
        <Pressable
          style={styles.permissionBanner}
          onPress={openSettings}
          accessibilityRole="button"
        >
          <Text style={styles.permissionBannerText}>
            알림 허용 안 됨 — 설정 열기
          </Text>
        </Pressable>
      ) : null}

      <View style={styles.row}>
        <Text style={styles.rowLabel}>미기록 식단 알림</Text>
        <Switch
          value={settings.notifications_enabled}
          onValueChange={(next) => {
            void handleSwitchToggle(next);
          }}
          accessibilityLabel="미기록 식단 알림 토글"
          disabled={updateMutation.isPending || registerMutation.isPending}
        />
      </View>

      <Pressable
        style={[styles.row, !settings.notifications_enabled && styles.rowDisabled]}
        onPress={() => {
          if (!settings.notifications_enabled) return;
          setShowTimePicker(true);
        }}
        accessibilityRole="button"
        accessibilityLabel="알림 시간 선택"
      >
        <Text style={styles.rowLabel}>알림 시간</Text>
        <Text style={styles.rowValue}>{formatTime(settings.notification_time)}</Text>
      </Pressable>

      <Modal
        visible={showTimePicker}
        transparent
        animationType="slide"
        onRequestClose={() => setShowTimePicker(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>알림 시간 선택</Text>
            <View style={styles.pickerRow}>
              <ScrollView style={styles.pickerColumn}>
                {HOURS.map((h) => (
                  <Pressable
                    key={h}
                    style={styles.pickerItem}
                    onPress={() => {
                      const [, mmStr] = settings.notification_time.split(':');
                      void handleTimeSelect(h, Number(mmStr));
                    }}
                  >
                    <Text style={styles.pickerItemText}>{String(h).padStart(2, '0')}시</Text>
                  </Pressable>
                ))}
              </ScrollView>
              <ScrollView style={styles.pickerColumn}>
                {MINUTES.map((m) => (
                  <Pressable
                    key={m}
                    style={styles.pickerItem}
                    onPress={() => {
                      const [hhStr] = settings.notification_time.split(':');
                      void handleTimeSelect(Number(hhStr), m);
                    }}
                  >
                    <Text style={styles.pickerItemText}>{String(m).padStart(2, '0')}분</Text>
                  </Pressable>
                ))}
              </ScrollView>
            </View>
            <Pressable
              style={styles.modalCloseButton}
              onPress={() => setShowTimePicker(false)}
            >
              <Text style={styles.modalCloseButtonText}>닫기</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      <Modal
        visible={permissionDeniedModal}
        transparent
        animationType="slide"
        onRequestClose={() => setPermissionDeniedModal(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <PermissionDeniedView
              canAskAgain={permission.canAskAgain}
              onRetryRequest={async () => {
                const status = await permission.request();
                if (status === 'granted') {
                  setPermissionDeniedModal(false);
                  await handleSwitchToggle(true);
                }
              }}
              onFallbackPress={() => setPermissionDeniedModal(false)}
              fallbackLabel="나중에"
            />
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  content: { paddingBottom: 24 },
  loadingText: { padding: 24, fontSize: 16, color: '#666' },
  errorText: { padding: 24, fontSize: 16, color: '#c00' },
  permissionBanner: {
    backgroundColor: '#fef3c7',
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#fcd34d',
  },
  permissionBannerText: {
    fontSize: 15,
    fontWeight: '600',
    color: '#78350f',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },
  rowDisabled: { opacity: 0.5 },
  rowLabel: { fontSize: 16, color: '#222' },
  rowValue: { fontSize: 15, color: '#666' },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'flex-end',
  },
  modalCard: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    paddingTop: 16,
    paddingBottom: 32,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '600',
    textAlign: 'center',
    marginBottom: 12,
  },
  pickerRow: {
    flexDirection: 'row',
    height: 240,
    borderTopWidth: 1,
    borderTopColor: '#eee',
  },
  pickerColumn: { flex: 1 },
  pickerItem: {
    paddingVertical: 12,
    alignItems: 'center',
    borderBottomWidth: 1,
    borderBottomColor: '#f5f5f5',
  },
  pickerItemText: { fontSize: 18, color: '#222' },
  modalCloseButton: {
    marginTop: 12,
    paddingVertical: 12,
    alignItems: 'center',
    backgroundColor: '#f5f5f5',
    marginHorizontal: 20,
    borderRadius: 8,
  },
  modalCloseButtonText: { fontSize: 16, fontWeight: '600', color: '#222' },
});
