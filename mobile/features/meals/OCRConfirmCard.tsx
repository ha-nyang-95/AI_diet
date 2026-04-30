/**
 * Story 2.3 — OCR 확인·수정 카드 (FR15 + epic AC line 535-548 정합).
 *
 * Vision OCR 결과(`parsed_items`)를 사용자가 확인/수정/추가/삭제 후 *"확인 후 저장"*
 * CTA로 폼 본 흐름 진행. `lowConfidence=true` 시 forced confirmation UX —
 * *"확인 후 저장"* CTA 비활성 + 모든 항목 사용자 편집 후 자동 활성화 (또는 *"이대로 진행"*
 * 명시 클릭 후 활성화).
 *
 * 빈 items (`items.length === 0`) — *"음식이 인식되지 않았어요"* 메시지 + *"+ 항목 추가"*
 * + *"다시 촬영"* (확인 CTA 비활성). Vision이 음식 미인식 케이스 대응.
 *
 * 디자인 정합 (Story 2.1/2.2 패턴):
 * - 16-24 px padding, 16 px font, `accessibilityRole="button"` 모든 인터랙티브 요소.
 * - 폰트 스케일 200% 대응 (`flexShrink: 1` + wrap).
 * - 색약 대응 — 신뢰도 배지는 텍스트 (*92%*) + 색상 보조 (0.6 미만 빨간색 + ⚠ 이모지).
 *
 * 재사용성 — 본 컴포넌트는 *Story 2.3 OCR 한정* baseline. Epic 3 `ChatStreaming.tsx`의
 * 인용 카드(읽기 전용)와는 별개 (인용은 *읽기 전용*, OCR은 *편집 가능*).
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import type { ParsedMealItem } from './mealSchema';

const NEW_ITEM_CONFIDENCE = 1.0; // 사용자 직접 입력 항목 — 신뢰
const NAME_MAX_LENGTH = 50;
const QUANTITY_MAX_LENGTH = 30;
const LOW_CONFIDENCE_THRESHOLD = 0.6;

interface OCRConfirmCardProps {
  items: ParsedMealItem[];
  /** 백엔드가 계산한 low_confidence (items 비었거나 min(confidence) < 0.6). */
  lowConfidence: boolean;
  onChangeItems: (items: ParsedMealItem[]) => void;
  onConfirm: () => void;
  onRetake: () => void;
  /** 부모가 메일 저장 진행 중 — 모든 버튼 disable + ActivityIndicator. */
  isSubmitting: boolean;
}

export function OCRConfirmCard({
  items,
  lowConfidence,
  onChangeItems,
  onConfirm,
  onRetake,
  isSubmitting,
}: OCRConfirmCardProps) {
  // 초기 items snapshot 비교로 *"사용자가 모든 항목 편집했는가"* detection.
  const initialItemsRef = useRef<string>(JSON.stringify(items));
  const [forceProceed, setForceProceed] = useState(false);

  useEffect(() => {
    // 부모가 새 items로 reset (재 parse 호출 등)할 때 snapshot 갱신.
    if (items.length === 0) {
      initialItemsRef.current = JSON.stringify(items);
      setForceProceed(false);
    }
  }, [items]);

  const allItemsEdited = useMemo(() => {
    if (items.length === 0) return false;
    const initial = JSON.parse(initialItemsRef.current) as ParsedMealItem[];
    if (initial.length === 0) return true; // 모두 사용자 추가
    if (initial.length !== items.length) return true; // 항목 추가/삭제 발생
    // 모든 항목의 name 또는 quantity가 변경됐는지.
    return items.every((item, idx) => {
      const orig = initial[idx];
      if (!orig) return true;
      return item.name !== orig.name || item.quantity !== orig.quantity;
    });
  }, [items]);

  const isEmpty = items.length === 0;
  // forced confirmation: lowConfidence + 빈 items 아님 + 모든 항목 미편집 + forceProceed 미클릭
  // → CTA 비활성. 빈 items은 별도 메시지 + 확인 CTA 자동 비활성 (의미 없음).
  const confirmDisabled =
    isSubmitting ||
    isEmpty ||
    (lowConfidence && !allItemsEdited && !forceProceed);

  const handleAddItem = () => {
    onChangeItems([
      ...items,
      { name: '', quantity: '', confidence: NEW_ITEM_CONFIDENCE },
    ]);
  };

  const handleDeleteItem = (idx: number) => {
    onChangeItems(items.filter((_, i) => i !== idx));
  };

  const handleEditName = (idx: number, value: string) => {
    onChangeItems(
      items.map((item, i) =>
        i === idx ? { ...item, name: value.slice(0, NAME_MAX_LENGTH) } : item,
      ),
    );
  };

  const handleEditQuantity = (idx: number, value: string) => {
    onChangeItems(
      items.map((item, i) =>
        i === idx ? { ...item, quantity: value.slice(0, QUANTITY_MAX_LENGTH) } : item,
      ),
    );
  };

  return (
    <View style={styles.container} accessibilityLabel="OCR 인식 결과 확인 카드">
      <Text style={styles.title}>인식된 음식을 확인해주세요</Text>
      <Text style={styles.subtitle}>맞으신가요?</Text>

      {lowConfidence ? (
        <Text style={styles.lowConfidenceBadge} accessibilityLabel="인식 불확실 안내">
          ⚠ 인식이 불확실해요 — 직접 수정해주세요
        </Text>
      ) : null}

      {isEmpty ? (
        <Text style={styles.emptyMessage}>
          음식이 인식되지 않았어요. 직접 입력하거나 다시 촬영해주세요.
        </Text>
      ) : (
        <View style={styles.itemList}>
          {items.map((item, idx) => {
            const confidencePct = Math.round(item.confidence * 100);
            const isLowItem = item.confidence < LOW_CONFIDENCE_THRESHOLD;
            return (
              <View key={idx} style={styles.itemRow}>
                <View style={styles.itemFields}>
                  <TextInput
                    style={styles.nameInput}
                    value={item.name}
                    onChangeText={(value) => handleEditName(idx, value)}
                    maxLength={NAME_MAX_LENGTH}
                    placeholder="음식명"
                    accessibilityLabel={`음식명 ${idx + 1}`}
                    editable={!isSubmitting}
                  />
                  <TextInput
                    style={styles.quantityInput}
                    value={item.quantity}
                    onChangeText={(value) => handleEditQuantity(idx, value)}
                    maxLength={QUANTITY_MAX_LENGTH}
                    placeholder="양"
                    accessibilityLabel={`양 ${idx + 1}`}
                    editable={!isSubmitting}
                  />
                </View>
                <Text
                  style={[
                    styles.confidenceBadge,
                    isLowItem && styles.confidenceBadgeLow,
                  ]}
                  accessibilityLabel={`신뢰도 ${confidencePct}%`}
                >
                  {isLowItem ? '⚠ ' : ''}
                  {confidencePct}%
                </Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`${idx + 1}번 항목 삭제`}
                  onPress={() => handleDeleteItem(idx)}
                  disabled={isSubmitting}
                  style={({ pressed }) => [
                    styles.deleteButton,
                    pressed && styles.pressed,
                  ]}
                >
                  <Text style={styles.deleteButtonText}>삭제</Text>
                </Pressable>
              </View>
            );
          })}
        </View>
      )}

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="항목 추가"
        onPress={handleAddItem}
        disabled={isSubmitting}
        style={({ pressed }) => [styles.addButton, pressed && styles.pressed]}
      >
        <Text style={styles.addButtonText}>+ 항목 추가</Text>
      </Pressable>

      {lowConfidence && !isEmpty && !allItemsEdited && !forceProceed ? (
        <View style={styles.forcedConfirmRow}>
          <Text style={styles.forcedConfirmHint}>각 항목을 검토해주세요</Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="이대로 진행"
            onPress={() => setForceProceed(true)}
            disabled={isSubmitting}
            style={({ pressed }) => [
              styles.secondaryButton,
              pressed && styles.pressed,
            ]}
          >
            <Text style={styles.secondaryButtonText}>이대로 진행</Text>
          </Pressable>
        </View>
      ) : null}

      <View style={styles.ctaRow}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="다시 촬영"
          onPress={onRetake}
          disabled={isSubmitting}
          style={({ pressed }) => [
            styles.secondaryButton,
            styles.ctaButton,
            pressed && styles.pressed,
          ]}
        >
          <Text style={styles.secondaryButtonText}>다시 촬영</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="확인 후 저장"
          onPress={onConfirm}
          disabled={confirmDisabled}
          style={({ pressed }) => [
            styles.primaryButton,
            styles.ctaButton,
            confirmDisabled && styles.disabledButton,
            pressed && styles.pressed,
          ]}
        >
          {isSubmitting ? (
            <ActivityIndicator color="#ffffff" />
          ) : (
            <Text style={styles.primaryButtonText}>확인 후 저장</Text>
          )}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingVertical: 16,
    paddingHorizontal: 16,
    backgroundColor: '#f9f9f9',
    borderRadius: 12,
    gap: 12,
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1a1a1a',
    flexShrink: 1,
  },
  subtitle: {
    fontSize: 14,
    color: '#666666',
    flexShrink: 1,
  },
  lowConfidenceBadge: {
    fontSize: 14,
    color: '#a05a00',
    backgroundColor: '#fff8e1',
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 6,
    flexShrink: 1,
  },
  emptyMessage: {
    fontSize: 16,
    color: '#4a4a4a',
    textAlign: 'center',
    paddingVertical: 16,
    flexShrink: 1,
  },
  itemList: {
    gap: 8,
  },
  itemRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 8,
    flexWrap: 'wrap',
  },
  itemFields: {
    flexDirection: 'row',
    gap: 8,
    flex: 1,
    minWidth: 200,
  },
  nameInput: {
    flex: 2,
    minHeight: 40,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: '#cccccc',
    borderRadius: 6,
    fontSize: 16,
    backgroundColor: '#ffffff',
  },
  quantityInput: {
    flex: 1,
    minHeight: 40,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: '#cccccc',
    borderRadius: 6,
    fontSize: 16,
    backgroundColor: '#ffffff',
  },
  confidenceBadge: {
    fontSize: 14,
    color: '#2a8033',
    fontWeight: '600',
    minWidth: 56,
    textAlign: 'center',
  },
  confidenceBadgeLow: {
    color: '#c62828',
  },
  deleteButton: {
    paddingVertical: 6,
    paddingHorizontal: 10,
  },
  deleteButtonText: {
    color: '#c62828',
    fontSize: 14,
    fontWeight: '500',
  },
  addButton: {
    alignSelf: 'flex-start',
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: '#0a7ea4',
  },
  addButtonText: {
    color: '#0a7ea4',
    fontSize: 14,
    fontWeight: '600',
  },
  forcedConfirmRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    flexWrap: 'wrap',
  },
  forcedConfirmHint: {
    fontSize: 14,
    color: '#a05a00',
    flexShrink: 1,
  },
  ctaRow: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 8,
    flexWrap: 'wrap',
  },
  ctaButton: {
    flex: 1,
    minWidth: 130,
  },
  primaryButton: {
    paddingVertical: 12,
    paddingHorizontal: 20,
    backgroundColor: '#0a7ea4',
    borderRadius: 8,
    alignItems: 'center',
  },
  primaryButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  secondaryButton: {
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderWidth: 1,
    borderColor: '#0a7ea4',
    borderRadius: 8,
    alignItems: 'center',
  },
  secondaryButtonText: {
    color: '#0a7ea4',
    fontSize: 16,
    fontWeight: '600',
  },
  disabledButton: {
    backgroundColor: '#cccccc',
    opacity: 0.6,
  },
  pressed: {
    opacity: 0.7,
  },
});
