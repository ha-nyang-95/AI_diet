/**
 * Story 2.1 — 식단 카드 컴포넌트.
 *
 * `raw_text`(첫 줄 + truncate) + `ate_at`(HH:mm 한국 시간) 표시. long-press 시
 * `onActionPress` 콜백 호출 — 부모가 ActionSheet/Alert을 띄움 (Platform 분기는 부모
 * 책임으로 — 카드는 *순수 표시*).
 *
 * 폰트 스케일 200% 대응 — `flexShrink: 1` + 텍스트 wrap. 색약 대응 — 텍스트만으로
 * 모든 정보 노출 (색상은 강조 보조).
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { MealResponse } from './mealSchema';

interface MealCardProps {
  meal: MealResponse;
  onActionPress: (meal: MealResponse) => void;
}

function formatHHmm(isoString: string): string {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return '';
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}

export function MealCard({ meal, onActionPress }: MealCardProps) {
  const a11yPreview = meal.raw_text.slice(0, 30);
  return (
    <Pressable
      style={styles.card}
      onLongPress={() => onActionPress(meal)}
      accessibilityRole="button"
      accessibilityLabel={`식단 카드: ${a11yPreview}`}
      accessibilityHint="길게 눌러 수정 또는 삭제"
    >
      <View style={styles.row}>
        <Text style={styles.time}>{formatHHmm(meal.ate_at)}</Text>
        <Text style={styles.text} numberOfLines={3}>
          {meal.raw_text}
        </Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    padding: 16,
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#e0e0e0',
    marginBottom: 12,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  time: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1a73e8',
    minWidth: 56,
  },
  text: {
    fontSize: 16,
    color: '#222',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 22,
  },
});
