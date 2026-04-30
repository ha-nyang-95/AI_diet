/**
 * Story 2.5 — 오프라인 큐 항목 카드 (server-side row 미존재 상태 표시).
 *
 * `MealCard`와 분리 — *책임 분리* (Story 2.4 `MealCard` 회귀 차단 + 액션 셋이 다름:
 * 큐 카드는 *상세 진입 X / 수정 X / 삭제 X* — 대신 *"다시 시도"* / *"폐기"*만).
 *
 * Visual:
 * - 회색 배경 (`#f5f5f5` 또는 `#fafafa`) — server row와 시각적 구분.
 * - *"동기화 대기 중"* 배지 (`#fff3cd` 노란색).
 * - raw_text + 큐잉 시각 (분 전 / 시간 전 표시).
 * - `attempts >= 1` 시 *"N회 시도 실패"* 보조 텍스트.
 *
 * Actions:
 * - *"다시 시도"* — 부모가 `flushQueue` 강제 호출.
 * - *"폐기"* — 부모가 `removeQueueItem` 호출.
 *
 * NFR-A3 폰트 200% — `flexShrink + flexWrap + lineHeight` (Story 2.4 정합).
 * accessibility — `accessibilityRole="button"` + 명시 라벨.
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { OfflineQueueItem } from '@/lib/offline-queue';

interface OfflineMealCardProps {
  item: OfflineQueueItem;
  onRetry: (clientId: string) => void;
  onDiscard: (clientId: string) => void;
  isFlushing: boolean;
}

function _formatRelativeKo(iso: string): string {
  const enqueuedAt = new Date(iso).getTime();
  if (Number.isNaN(enqueuedAt)) return '';
  const diffMs = Date.now() - enqueuedAt;
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return '방금 전 입력';
  if (diffMin < 60) return `${diffMin}분 전 입력`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}시간 전 입력`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}일 전 입력`;
}

export function OfflineMealCard({
  item,
  onRetry,
  onDiscard,
  isFlushing,
}: OfflineMealCardProps) {
  const preview = item.raw_text.slice(0, 30);
  const enqueuedLabel = _formatRelativeKo(item.enqueued_at);
  const attemptsLabel = item.attempts >= 1 ? `${item.attempts}회 시도 실패` : null;
  const a11yLabel =
    `동기화 대기 식단: ${preview}${attemptsLabel ? `, ${attemptsLabel}` : ''}` +
    `, ${enqueuedLabel}`;

  return (
    <View
      style={styles.card}
      accessibilityRole="summary"
      accessibilityLabel={a11yLabel}
      accessibilityHint="다시 시도하거나 폐기할 수 있습니다"
    >
      <View style={styles.headerRow}>
        <View style={styles.badge} accessibilityLabel="동기화 대기">
          <Text style={styles.badgeText}>동기화 대기 중</Text>
        </View>
        <Text style={styles.timeText}>{enqueuedLabel}</Text>
      </View>
      <Text style={styles.rawText}>{item.raw_text}</Text>
      {attemptsLabel ? (
        <Text style={styles.errorText}>
          {attemptsLabel}
          {item.last_error ? ` — ${item.last_error}` : ''}
        </Text>
      ) : null}
      <View style={styles.actionsRow}>
        <Pressable
          style={[styles.actionButton, styles.retryButton]}
          onPress={() => onRetry(item.client_id)}
          disabled={isFlushing}
          accessibilityRole="button"
          accessibilityLabel="다시 시도"
          accessibilityState={{ disabled: isFlushing }}
        >
          <Text style={styles.retryButtonText}>다시 시도</Text>
        </Pressable>
        <Pressable
          style={styles.actionButton}
          onPress={() => onDiscard(item.client_id)}
          accessibilityRole="button"
          accessibilityLabel="폐기"
        >
          <Text style={styles.discardButtonText}>폐기</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#fafafa',
    borderRadius: 8,
    padding: 12,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#e0e0e0',
    gap: 8,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 8,
  },
  badge: {
    backgroundColor: '#fff3cd',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#ffe69c',
  },
  badgeText: {
    color: '#664d03',
    fontSize: 12,
    fontWeight: '600',
    lineHeight: 16,
  },
  timeText: {
    fontSize: 12,
    color: '#666',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 16,
  },
  rawText: {
    fontSize: 16,
    color: '#333',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 22,
  },
  errorText: {
    fontSize: 13,
    color: '#a94442',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 18,
  },
  actionsRow: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 4,
  },
  actionButton: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 6,
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#d0d0d0',
  },
  retryButton: {
    backgroundColor: '#1a73e8',
    borderColor: '#1a73e8',
  },
  retryButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 14,
    lineHeight: 18,
  },
  discardButtonText: {
    color: '#666',
    fontSize: 14,
    lineHeight: 18,
  },
});
