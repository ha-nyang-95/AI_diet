/**
 * Story 6.1 AC7 — 구독 신청 화면 (모바일).
 *
 * App Store IAP 정합 (prd.md:676) — 모바일은 *결제 위젯 미노출*. 사용자가 "구독 신청"
 * 버튼을 누르면 ``Linking.openURL(getSubscribeWebUrl())``로 외부 브라우저에 Web
 * ``/account/subscribe`` 페이지를 노출한다. 안내 문구로 *"App Store 정책에 따라 결제는
 * 외부 브라우저에서 진행됩니다."* 명시.
 *
 * 진입 가드 ① — ``consentStatus === null`` → 스피너(bootstrap, Story 5.x 패턴 정합).
 * 진입 가드 ② — ``!basic_consents_complete`` → 동의 안내 + 동의 화면 link
 *   (``require_basic_consents`` 1차 게이트 정합).
 *
 * UI 분기:
 * - ``isPending`` → ``ActivityIndicator``.
 * - ``data === null`` (404) → 미신청 카드 + *"월 9,900원 정기결제 신청"* 버튼.
 * - ``data !== null`` (active) → 활성 구독 카드 + *"해지는 다음 업데이트"* placeholder.
 */
import { Stack, router } from 'expo-router';
import { Alert, Linking, ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import {
  getSubscribeWebUrl,
  useSubscriptionQuery,
} from '@/features/settings/useSubscription';
import { useAuth } from '@/lib/auth';

const PLAN_PRICE_KRW = 9900;

function _formatKstDate(iso: string | null): string {
  if (iso === null) {
    return '-';
  }
  try {
    const d = new Date(iso);
    return new Intl.DateTimeFormat('ko-KR', {
      timeZone: 'Asia/Seoul',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(d);
  } catch {
    return iso;
  }
}

export default function SubscriptionScreen() {
  const { consentStatus, user } = useAuth();
  // CR P14 — userId를 query key에 포함해 계정 전환 cache leak 차단. user 미로딩 시 빈
  // 문자열 → ``enabled: false``로 fetch skip(useSubscriptionQuery 내부에서 가드).
  const query = useSubscriptionQuery(user?.id ?? '');

  // 진입 가드 ① bootstrap.
  if (consentStatus === null) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: '구독' }} />
        <ActivityIndicator />
      </View>
    );
  }

  // 진입 가드 ② basic_consents (결제는 자기 데이터 작성 → require_basic_consents 정합).
  if (!consentStatus.basic_consents_complete) {
    return (
      <ScrollView contentContainerStyle={styles.container}>
        <Stack.Screen options={{ title: '구독' }} />
        <Text style={styles.title}>구독</Text>
        <View style={styles.warningCard}>
          <Text style={styles.warningText}>
            구독 신청은 기본 동의 후 가능합니다.
          </Text>
        </View>
        <Pressable
          style={styles.primaryButton}
          onPress={() => router.push('/(tabs)/settings/disclaimer')}
          accessibilityRole="button"
        >
          <Text style={styles.primaryButtonText}>기본 동의로 이동</Text>
        </Pressable>
      </ScrollView>
    );
  }

  const handleSubscribePress = async () => {
    const url = getSubscribeWebUrl();
    const supported = await Linking.canOpenURL(url);
    if (!supported) {
      Alert.alert(
        '브라우저 열기 실패',
        '결제 화면을 열 수 없습니다. 잠시 후 다시 시도해 주세요.',
      );
      return;
    }
    await Linking.openURL(url);
  };

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Stack.Screen options={{ title: '구독' }} />
      <Text style={styles.title}>구독</Text>

      {query.isPending ? (
        <View style={styles.center}>
          <ActivityIndicator />
        </View>
      ) : query.isError ? (
        <View style={styles.warningCard}>
          <Text style={styles.warningText}>
            구독 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
          </Text>
        </View>
      ) : query.data === null ? (
        <>
          <View style={styles.infoCard}>
            <Text style={styles.infoTitle}>정기결제 1플랜</Text>
            <Text style={styles.infoPrice}>
              월 {PLAN_PRICE_KRW.toLocaleString('ko-KR')}원
            </Text>
            <Text style={styles.infoText}>
              매월 자동으로 결제되며, 언제든 해지할 수 있습니다.
            </Text>
            <Text style={styles.infoNote}>
              App Store 정책에 따라 결제는 외부 브라우저에서 진행됩니다.
            </Text>
          </View>

          <Pressable
            style={styles.primaryButton}
            onPress={() => {
              void handleSubscribePress();
            }}
            accessibilityRole="button"
            accessibilityLabel="월 9,900원 정기결제 신청"
          >
            <Text style={styles.primaryButtonText}>
              월 {PLAN_PRICE_KRW.toLocaleString('ko-KR')}원 정기결제 신청
            </Text>
          </Pressable>
        </>
      ) : (
        <>
          <View style={styles.activeCard}>
            <Text style={styles.activeTitle}>활성 구독</Text>
            <View style={styles.activeRow}>
              <Text style={styles.activeLabel}>플랜</Text>
              <Text style={styles.activeValue}>
                월 {query.data.plan_price_krw.toLocaleString('ko-KR')}원
              </Text>
            </View>
            <View style={styles.activeRow}>
              <Text style={styles.activeLabel}>시작일</Text>
              <Text style={styles.activeValue}>
                {_formatKstDate(query.data.started_at)}
              </Text>
            </View>
            <View style={styles.activeRow}>
              <Text style={styles.activeLabel}>다음 결제일</Text>
              <Text style={styles.activeValue}>
                {_formatKstDate(query.data.expires_at)}
              </Text>
            </View>
            <View style={styles.activeRow}>
              <Text style={styles.activeLabel}>결제 수단</Text>
              <Text style={styles.activeValue}>
                {query.data.provider === 'toss' ? '토스페이먼츠' : 'Stripe'}
              </Text>
            </View>
          </View>

          <View style={styles.infoCard}>
            <Text style={styles.infoText}>
              구독 해지는 다음 업데이트에서 가능합니다.
            </Text>
          </View>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  container: { padding: 24, paddingBottom: 48, backgroundColor: '#fff' },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 16 },
  infoCard: {
    backgroundColor: '#eef4ff',
    borderColor: '#c5d8ff',
    borderWidth: 1,
    borderRadius: 8,
    padding: 16,
    marginBottom: 16,
  },
  infoTitle: { fontSize: 16, fontWeight: '600', color: '#1f3a8a', marginBottom: 4 },
  infoPrice: { fontSize: 24, fontWeight: '700', color: '#1f3a8a', marginBottom: 8 },
  infoText: { fontSize: 14, color: '#1f3a8a', lineHeight: 20 },
  infoNote: { fontSize: 12, color: '#3b5bbd', marginTop: 8, fontStyle: 'italic' },
  warningCard: {
    backgroundColor: '#fff4e5',
    borderColor: '#ffcc80',
    borderWidth: 1,
    borderRadius: 8,
    padding: 14,
    marginBottom: 16,
  },
  warningText: { fontSize: 14, color: '#8a4b00', lineHeight: 20 },
  activeCard: {
    backgroundColor: '#fff',
    borderColor: '#1a73e8',
    borderWidth: 1,
    borderRadius: 8,
    padding: 16,
    marginBottom: 16,
  },
  activeTitle: { fontSize: 16, fontWeight: '700', color: '#1a73e8', marginBottom: 12 },
  activeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 6,
  },
  activeLabel: { fontSize: 14, color: '#5f6368' },
  activeValue: { fontSize: 14, color: '#222', fontWeight: '500' },
  primaryButton: {
    backgroundColor: '#1a73e8',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
    marginBottom: 12,
  },
  primaryButtonText: { color: '#fff', fontSize: 15, fontWeight: '600' },
});
