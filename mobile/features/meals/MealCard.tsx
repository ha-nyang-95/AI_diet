/**
 * Story 2.1 (baseline) → Story 2.4 polish — 식단 카드 컴포넌트.
 *
 * Story 2.4 추가:
 * - 사진 썸네일(64x64, `expo-image` `cachePolicy="disk"`).
 * - parsed_items 부제 (DF15 해소 — `formatParsedItemsToInlineLabel`).
 * - `analysis_summary` 슬롯 — 매크로/피드백/fit_score 배지 (Epic 3 forward-compat).
 *   baseline은 항상 null → "AI 분석 대기" 회색 배지.
 * - fit_score 배지: 색상 + 숫자 + 텍스트 라벨 3중 표시 (NFR-A4 색약 대응).
 * - 카드 onPress 신규 (`onCardPress`) — 부모가 `[meal_id]`로 navigate. long-press는
 *   기존 `onActionPress` 그대로 (RN 표준 패턴: 탭=상세, long-press=액션 메뉴).
 * - W49 해소: `formatHHmm` `Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul' })`
 *   강제 — 디바이스 LA/도쿄 출장 시점에도 KST 표시.
 *
 * NFR-A3 폰트 스케일 200% 대응 — `flexShrink: 1` + 텍스트 wrap + 명시 lineHeight.
 * NFR-A4 색약 대응 — 색상 + 숫자 + 텍스트 라벨 3중 표시.
 */
import { Image } from 'expo-image';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { formatParsedItemsToInlineLabel } from './parsedItemsFormat';
import type { FitScoreLabel, MealMacros, MealResponse } from './mealSchema';

interface MealCardProps {
  meal: MealResponse;
  onCardPress: (meal: MealResponse) => void;
  onActionPress: (meal: MealResponse) => void;
}

const _hhmmKstFormatter = new Intl.DateTimeFormat('ko-KR', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'Asia/Seoul',
});

function formatHHmm(isoString: string): string {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return '';
  // Intl 출력은 환경별로 ":" 또는 "." 분리자, "오후 11:30" prefix 등이 들어올 수 있음.
  // 본 화면은 24시간 HH:mm만 필요 — formatToParts로 hour/minute만 명시 추출.
  const parts = _hhmmKstFormatter.formatToParts(date);
  const hour = parts.find((p) => p.type === 'hour')?.value ?? '00';
  const minute = parts.find((p) => p.type === 'minute')?.value ?? '00';
  return `${hour}:${minute}`;
}

const FIT_SCORE_COLORS: Record<FitScoreLabel, string> = {
  allergen_violation: '#d93025',
  low: '#e98000',
  moderate: '#f5b400',
  good: '#34a853',
  excellent: '#1a73e8',
};

const FIT_SCORE_LABELS_KO: Record<FitScoreLabel, string> = {
  allergen_violation: '알레르기 위반',
  low: '부족',
  moderate: '보통',
  good: '양호',
  excellent: '우수',
};

function formatMacrosLine(macros: MealMacros): string {
  const { carbohydrate_g, protein_g, fat_g, energy_kcal } = macros;
  if (carbohydrate_g === 0 && protein_g === 0 && fat_g === 0 && energy_kcal === 0) {
    return '매크로 정보 없음';
  }
  return `탄 ${carbohydrate_g}g · 단 ${protein_g}g · 지 ${fat_g}g · ${energy_kcal} kcal`;
}

export function MealCard({ meal, onCardPress, onActionPress }: MealCardProps) {
  const time = formatHHmm(meal.ate_at);
  const a11yPreview = meal.raw_text.slice(0, 30);
  const parsedSubtitle = formatParsedItemsToInlineLabel(meal.parsed_items);
  const summary = meal.analysis_summary;

  const a11yScorePart = summary
    ? `, 적합도 ${summary.fit_score} ${FIT_SCORE_LABELS_KO[summary.fit_score_label]}`
    : ', 적합도 분석 대기';

  return (
    <Pressable
      style={styles.card}
      onPress={() => onCardPress(meal)}
      onLongPress={() => onActionPress(meal)}
      accessibilityRole="button"
      accessibilityLabel={`식단 카드: ${a11yPreview} ${time}${a11yScorePart}`}
      accessibilityHint="탭하여 상세 보기 / 길게 눌러 수정 또는 삭제"
    >
      {/* 헤더 row — 시간 + fit_score 배지 + 액션 버튼 */}
      <View style={styles.headerRow}>
        <Text style={styles.time}>{time}</Text>
        <View style={styles.headerRight}>
          {summary !== null ? (
            <View
              style={[
                styles.fitScoreBadge,
                { backgroundColor: FIT_SCORE_COLORS[summary.fit_score_label] },
              ]}
              accessibilityLabel={`적합도 점수 ${summary.fit_score}, ${FIT_SCORE_LABELS_KO[summary.fit_score_label]}`}
            >
              <Text style={styles.fitScoreNumber}>{summary.fit_score}</Text>
              <Text style={styles.fitScoreLabel}>
                {FIT_SCORE_LABELS_KO[summary.fit_score_label]}
              </Text>
            </View>
          ) : (
            <View style={styles.placeholderBadge}>
              <Text style={styles.placeholderText}>AI 분석 대기</Text>
            </View>
          )}
          <Pressable
            onPress={() => onActionPress(meal)}
            hitSlop={12}
            accessibilityRole="button"
            accessibilityLabel="액션 메뉴"
            style={styles.actionButton}
          >
            <Text style={styles.actionButtonText}>⋮</Text>
          </Pressable>
        </View>
      </View>

      {/* 사진 썸네일 (image_url 있을 때만) */}
      {meal.image_url ? (
        <Image
          source={{ uri: meal.image_url }}
          style={styles.thumbnail}
          contentFit="cover"
          transition={200}
          cachePolicy="disk"
          accessibilityIgnoresInvertColors
        />
      ) : null}

      {/* 본문 row */}
      <Text style={styles.text} numberOfLines={3}>
        {meal.raw_text}
      </Text>

      {/* parsed_items 부제 (DF15 해소) */}
      {parsedSubtitle !== null ? (
        <Text style={styles.parsedSubtitle} numberOfLines={1}>
          {parsedSubtitle}
        </Text>
      ) : null}

      {/* 매크로 row + 피드백 row (analysis_summary !== null) */}
      {summary !== null ? (
        <>
          <Text style={styles.macros} numberOfLines={1}>
            {formatMacrosLine(summary.macros)}
          </Text>
          <Text style={styles.feedback} numberOfLines={1}>
            {summary.feedback_summary}
          </Text>
        </>
      ) : null}
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
    gap: 8,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flexShrink: 1,
    flexWrap: 'wrap',
    justifyContent: 'flex-end',
  },
  time: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1a73e8',
    minWidth: 56,
    lineHeight: 20,
  },
  fitScoreBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
    gap: 6,
    flexShrink: 1,
    flexWrap: 'wrap',
  },
  fitScoreNumber: {
    fontSize: 13,
    fontWeight: '700',
    color: '#fff',
    lineHeight: 16,
  },
  fitScoreLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#fff',
    lineHeight: 16,
    flexShrink: 1,
    flexWrap: 'wrap',
  },
  placeholderBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
    backgroundColor: '#f0f0f0',
    flexShrink: 1,
  },
  placeholderText: {
    fontSize: 12,
    color: '#888',
    fontWeight: '500',
    lineHeight: 16,
    flexShrink: 1,
    flexWrap: 'wrap',
  },
  actionButton: {
    paddingHorizontal: 4,
    paddingVertical: 2,
  },
  actionButtonText: {
    fontSize: 18,
    color: '#666',
    lineHeight: 20,
  },
  thumbnail: {
    width: 64,
    height: 64,
    borderRadius: 4,
    backgroundColor: '#f0f0f0',
  },
  text: {
    fontSize: 16,
    color: '#222',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 22,
  },
  parsedSubtitle: {
    fontSize: 13,
    color: '#666',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 18,
  },
  macros: {
    fontSize: 13,
    color: '#444',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 18,
  },
  feedback: {
    fontSize: 13,
    color: '#222',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 18,
  },
});
