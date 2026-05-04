/**
 * Story 3.7 — `MacroCard` 매크로 보조 카드 (AC11 / NFR-UX3).
 *
 * NFR-UX3 SOT — *단순 g/kcal 수치는 채팅 본문이 아닌 별도 데이터 카드(접힘 가능)*.
 * 디폴트 *접힘* 상태 — *"매크로 자세히 보기 ▾"* 헤더 → 탭 시 본문 expand.
 *
 * MealCard.tsx 패턴(`탄 ${carbohydrate_g}g · 단 ${protein_g}g · 지 ${fat_g}g · ${energy_kcal} kcal`)
 * 재사용 — 일관된 macros 표기.
 */
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { MealMacros } from './mealSchema';

interface MacroCardProps {
  macros: MealMacros;
}

export default function MacroCard({ macros }: MacroCardProps): React.ReactElement {
  const [expanded, setExpanded] = useState(false);
  const { carbohydrate_g, protein_g, fat_g, energy_kcal } = macros;

  return (
    <View style={styles.container}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={expanded ? '매크로 접기' : '매크로 자세히 보기'}
        onPress={() => setExpanded((prev) => !prev)}
        style={styles.header}
      >
        <Text style={styles.headerText}>
          {expanded ? '매크로 접기 ▴' : '매크로 자세히 보기 ▾'}
        </Text>
      </Pressable>
      {expanded ? (
        <View style={styles.body}>
          <Text style={styles.bodyText}>
            {`탄 ${carbohydrate_g}g · 단 ${protein_g}g · 지 ${fat_g}g · ${energy_kcal} kcal`}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#e0e0e0',
    overflow: 'hidden',
  },
  header: {
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  headerText: {
    fontSize: 14,
    color: '#666',
    fontWeight: '600',
    lineHeight: 20,
  },
  body: {
    paddingHorizontal: 16,
    paddingBottom: 12,
    borderTopWidth: 1,
    borderTopColor: '#f0f0f0',
    paddingTop: 8,
  },
  bodyText: {
    fontSize: 15,
    color: '#222',
    flexShrink: 1,
    flexWrap: 'wrap',
    lineHeight: 22,
  },
});
