/**
 * Story 6.1 / 6.2 — 구독 신청 + 해지 + 결제 이력 진입 화면 (모바일).
 *
 * App Store IAP 정합 (prd.md:676) — 모바일은 *결제 위젯 미노출*. "구독 신청" 시
 * 외부 브라우저로 Web ``/account/subscribe`` 진입.
 *
 * Story 6.2 추가:
 * - 활성 카드에 *"구독 해지"* `Pressable` + Alert.alert 확인 + cancel mutation.
 * - cancelled-but-not-expired 분기 UI(*"해지됨"* 헤더 + *"이용 가능 종료일"* label +
 *   해지 버튼 미노출).
 * - *"결제 이력 보기"* link → `(tabs)/settings/payment-history`.
 *
 * 진입 가드 ① — ``consentStatus === null`` → 스피너(bootstrap, Story 5.x 패턴).
 * 진입 가드 ② — ``!basic_consents_complete`` → 동의 안내 + 동의 화면 link
 *   (require_basic_consents 1차 게이트). *해지 흐름은 가드 ② 무관* — PIPA Art.35 정합 +
 *   현실적으로 활성 구독자는 이미 동의 완료(가드 ②는 *신청* 진입에 필요).
 */
import { Stack, router } from 'expo-router';
import {
  ActivityIndicator,
  Alert,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import {
  getSubscribeWebUrl,
  useCancelSubscriptionMutation,
  useSubscriptionQuery,
  type SubscriptionDto,
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
  const query = useSubscriptionQuery(user?.id ?? '');
  const cancelMutation = useCancelSubscriptionMutation();

  // 진입 가드 ① bootstrap.
  if (consentStatus === null) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: '구독' }} />
        <ActivityIndicator />
      </View>
    );
  }

  // 진입 가드 ② basic_consents (결제 *신청* 경로 의무 — 해지 흐름은 무관하지만, 본 가드는
  // *신청* 진입 차단이라 활성 구독자는 가드 ② 통과 상태가 보장됨). 결제 *이력 조회*는
  // PIPA Art.35 정합으로 동의 철회와 독립 — link은 본 분기에서도 노출.
  if (!consentStatus.basic_consents_complete) {
    return (
      <ScrollView contentContainerStyle={styles.container}>
        <Stack.Screen options={{ title: '구독' }} />
        <Text style={styles.title}>구독</Text>
        <View style={styles.warningCard}>
          <Text style={styles.warningText}>구독 신청은 기본 동의 후 가능합니다.</Text>
        </View>
        <Pressable
          style={styles.primaryButton}
          onPress={() => router.push('/(tabs)/settings/disclaimer')}
          accessibilityRole="button"
        >
          <Text style={styles.primaryButtonText}>기본 동의로 이동</Text>
        </Pressable>
        <Pressable
          style={styles.linkButton}
          onPress={() => router.push('/(tabs)/settings/payment-history')}
          accessibilityRole="button"
          accessibilityLabel="결제 이력 보기"
        >
          <Text style={styles.linkButtonText}>결제 이력 보기</Text>
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

  const handleCancelPress = (subscription: SubscriptionDto) => {
    Alert.alert(
      '구독을 해지하시겠습니까?',
      `다음 결제일(${_formatKstDate(subscription.expires_at)})까지 모든 기능을 이용할 수 있습니다.`,
      [
        { text: '취소', style: 'cancel' },
        {
          text: '해지',
          style: 'destructive',
          onPress: () => {
            cancelMutation.mutate(undefined, {
              onError: (error) => {
                Alert.alert('해지 실패', error.detail ?? error.message);
              },
            });
          },
        },
      ],
    );
  };

  const goToHistory = () => {
    router.push('/(tabs)/settings/payment-history');
  };

  const renderActiveCard = (subscription: SubscriptionDto) => {
    const isCancelled = subscription.status === 'cancelled';
    const headerText = isCancelled ? '해지됨' : '활성 구독';
    const expiresLabel = isCancelled ? '이용 가능 종료일' : '다음 결제일';

    return (
      <>
        <View style={isCancelled ? styles.cancelledCard : styles.activeCard}>
          <Text style={isCancelled ? styles.cancelledTitle : styles.activeTitle}>
            {headerText}
          </Text>
          <View style={styles.activeRow}>
            <Text style={styles.activeLabel}>플랜</Text>
            <Text style={styles.activeValue}>
              월 {subscription.plan_price_krw.toLocaleString('ko-KR')}원
            </Text>
          </View>
          <View style={styles.activeRow}>
            <Text style={styles.activeLabel}>시작일</Text>
            <Text style={styles.activeValue}>{_formatKstDate(subscription.started_at)}</Text>
          </View>
          <View style={styles.activeRow}>
            <Text style={styles.activeLabel}>{expiresLabel}</Text>
            <Text style={styles.activeValue}>{_formatKstDate(subscription.expires_at)}</Text>
          </View>
          <View style={styles.activeRow}>
            <Text style={styles.activeLabel}>결제 수단</Text>
            <Text style={styles.activeValue}>
              {subscription.provider === 'toss' ? '토스페이먼츠' : 'Stripe'}
            </Text>
          </View>
        </View>

        {isCancelled ? null : (
          <Pressable
            style={[
              styles.dangerButton,
              cancelMutation.isPending && styles.buttonDisabled,
            ]}
            onPress={() => handleCancelPress(subscription)}
            disabled={cancelMutation.isPending}
            accessibilityRole="button"
            accessibilityLabel="구독 해지"
          >
            {cancelMutation.isPending ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.dangerButtonText}>구독 해지</Text>
            )}
          </Pressable>
        )}

        <Pressable
          style={styles.linkButton}
          onPress={goToHistory}
          accessibilityRole="button"
          accessibilityLabel="결제 이력 보기"
        >
          <Text style={styles.linkButtonText}>결제 이력 보기</Text>
        </Pressable>
      </>
    );
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

          <Pressable
            style={styles.linkButton}
            onPress={goToHistory}
            accessibilityRole="button"
            accessibilityLabel="결제 이력 보기"
          >
            <Text style={styles.linkButtonText}>결제 이력 보기</Text>
          </Pressable>
        </>
      ) : (
        renderActiveCard(query.data)
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
  cancelledCard: {
    backgroundColor: '#fafafa',
    borderColor: '#9aa0a6',
    borderWidth: 1,
    borderRadius: 8,
    padding: 16,
    marginBottom: 16,
  },
  cancelledTitle: { fontSize: 16, fontWeight: '700', color: '#5f6368', marginBottom: 12 },
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
  dangerButton: {
    backgroundColor: '#d93025',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
    marginBottom: 12,
  },
  dangerButtonText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  buttonDisabled: { opacity: 0.6 },
  linkButton: {
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
    marginBottom: 8,
  },
  linkButtonText: { color: '#1a73e8', fontSize: 14, fontWeight: '500' },
});
