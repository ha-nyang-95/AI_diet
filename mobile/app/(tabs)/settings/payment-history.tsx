/**
 * Story 6.2 AC6 — 결제 이력 화면 (모바일).
 *
 * `GET /v1/payments/history?limit=20` 호출 결과를 ``<FlatList>`` 1페이지 표시. 무한
 * 스크롤은 본 스토리 미스코프 (Web은 *"더 보기"* 버튼으로 cursor pagination, 모바일은
 * Story 8.x polish forward).
 *
 * 진입 가드 ① — ``consentStatus === null`` → 스피너(bootstrap, Story 5.x 패턴 정합).
 * 진입 가드 ② (basic_consents) **미적용** — PIPA Art.35 정합(자기 결제 이력 조회는 동의
 *   철회와 독립). Story 5.3 ``data-export.tsx`` 패턴 1:1 정합.
 *
 * 영수증 link — ``receipt_url`` non-null + ``status='success'`` 시 *"영수증"* 버튼.
 * ``Linking.canOpenURL`` 가드 후 외부 브라우저로 진입 (Toss receipt URL 도메인).
 */
import { Stack, router } from 'expo-router';
import type React from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import {
  usePaymentHistoryQuery,
  type PaymentHistoryItemDto,
  type PaymentLogEventType,
  type PaymentLogStatus,
} from '@/features/settings/useSubscription';
import { useAuth } from '@/lib/auth';

const EVENT_TYPE_LABELS: Record<PaymentLogEventType, string> = {
  subscribe: '구독 신청',
  cancel: '구독 해지',
  renew: '자동 갱신',
  failed: '결제 실패',
  refund: '환불',
};

const STATUS_LABELS: Record<PaymentLogStatus, string> = {
  success: '완료',
  failed: '실패',
  pending: '진행중',
};

function _formatKstDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    return new Intl.DateTimeFormat('ko-KR', {
      timeZone: 'Asia/Seoul',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(d);
  } catch {
    return iso;
  }
}

async function openReceipt(url: string): Promise<void> {
  const supported = await Linking.canOpenURL(url);
  if (!supported) {
    Alert.alert('영수증 열기 실패', '영수증 페이지를 열 수 없습니다.');
    return;
  }
  await Linking.openURL(url);
}

function HistoryRow({ item }: { item: PaymentHistoryItemDto }): React.JSX.Element {
  const eventLabel = EVENT_TYPE_LABELS[item.event_type] ?? item.event_type;
  const statusLabel = STATUS_LABELS[item.status] ?? item.status;
  const statusStyle =
    item.status === 'success'
      ? styles.statusSuccess
      : item.status === 'failed'
        ? styles.statusFailed
        : styles.statusPending;
  const showReceipt = item.receipt_url !== null && item.status === 'success';

  return (
    <View style={styles.row}>
      <View style={styles.rowTop}>
        <View style={styles.rowLeft}>
          <Text style={styles.rowEventLabel}>{eventLabel}</Text>
          <Text style={styles.rowDate}>{_formatKstDateTime(item.occurred_at)}</Text>
        </View>
        <Text style={styles.rowAmount}>{item.amount_krw.toLocaleString('ko-KR')}원</Text>
      </View>
      <View style={styles.rowBottom}>
        <View style={[styles.statusBadge, statusStyle]}>
          <Text style={styles.statusText}>{statusLabel}</Text>
        </View>
        {showReceipt && item.receipt_url !== null ? (
          <Pressable
            style={styles.receiptButton}
            onPress={() => {
              void openReceipt(item.receipt_url as string);
            }}
            accessibilityRole="button"
            accessibilityLabel="영수증 열기"
          >
            <Text style={styles.receiptButtonText}>영수증</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

export default function PaymentHistoryScreen(): React.JSX.Element {
  const { consentStatus, user } = useAuth();
  const query = usePaymentHistoryQuery(user?.id ?? '');

  // 진입 가드 ① bootstrap. (basic_consents 가드 X — PIPA Art.35.)
  if (consentStatus === null) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: '결제 이력' }} />
        <ActivityIndicator />
      </View>
    );
  }

  // bootstrap 완료 후 user 부재 — query는 ``enabled=false``로 isPending 영구 stale.
  // 무한 스피너 방어 — 로그인 화면으로 redirect.
  if (!user) {
    router.replace('/(auth)/login');
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: '결제 이력' }} />
        <ActivityIndicator />
      </View>
    );
  }

  if (query.isPending) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: '결제 이력' }} />
        <ActivityIndicator />
      </View>
    );
  }

  if (query.isError) {
    return (
      <View style={styles.container}>
        <Stack.Screen options={{ title: '결제 이력' }} />
        <View style={styles.warningCard}>
          <Text style={styles.warningText}>
            결제 이력을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
          </Text>
        </View>
      </View>
    );
  }

  if (query.data.items.length === 0) {
    return (
      <View style={styles.container}>
        <Stack.Screen options={{ title: '결제 이력' }} />
        <View style={styles.emptyCard}>
          <Text style={styles.emptyText}>결제 이력이 없습니다.</Text>
          <Pressable
            style={styles.linkButton}
            onPress={() => router.push('/(tabs)/settings/subscription')}
            accessibilityRole="button"
            accessibilityLabel="구독 신청"
          >
            <Text style={styles.linkButtonText}>구독 신청</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: '결제 이력' }} />
      <FlatList
        data={query.data.items}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => <HistoryRow item={item} />}
        contentContainerStyle={styles.listContent}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  container: { flex: 1, backgroundColor: '#fff' },
  listContent: { padding: 16, paddingBottom: 48 },
  separator: { height: 12 },
  row: {
    backgroundColor: '#fff',
    borderColor: '#e0e0e0',
    borderWidth: 1,
    borderRadius: 8,
    padding: 14,
  },
  rowTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  rowLeft: { flex: 1, paddingRight: 12 },
  rowEventLabel: { fontSize: 15, fontWeight: '600', color: '#222' },
  rowDate: { fontSize: 12, color: '#5f6368', marginTop: 2 },
  rowAmount: { fontSize: 15, fontWeight: '600', color: '#222' },
  rowBottom: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 10,
  },
  statusBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  statusSuccess: { backgroundColor: '#e6f4ea' },
  statusFailed: { backgroundColor: '#fce8e6' },
  statusPending: { backgroundColor: '#f1f3f4' },
  statusText: { fontSize: 12, fontWeight: '500', color: '#222' },
  receiptButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: '#eef4ff',
  },
  receiptButtonText: { color: '#1a73e8', fontSize: 13, fontWeight: '500' },
  warningCard: {
    backgroundColor: '#fff4e5',
    borderColor: '#ffcc80',
    borderWidth: 1,
    borderRadius: 8,
    padding: 14,
    margin: 16,
  },
  warningText: { fontSize: 14, color: '#8a4b00', lineHeight: 20 },
  emptyCard: {
    padding: 24,
    margin: 16,
    backgroundColor: '#f5f7fa',
    borderRadius: 8,
    alignItems: 'center',
  },
  emptyText: { fontSize: 14, color: '#5f6368', marginBottom: 12 },
  linkButton: { paddingVertical: 8, paddingHorizontal: 16 },
  linkButtonText: { color: '#1a73e8', fontSize: 14, fontWeight: '500' },
});
