/**
 * Story 2.3 — Vision OCR `ParsedMealItem[]` → 한국어 한 줄 raw_text 변환 헬퍼.
 *
 * 예: `[{"name":"짜장면","quantity":"1인분"}, {"name":"군만두","quantity":"4개"}]`
 * → `"짜장면 1인분, 군만두 4개"`.
 *
 * 빈 quantity는 양 표시 생략 ("바나나" 처럼). 빈 items는 빈 문자열 — 부모 컴포넌트가
 * "인식 결과 없음" 분기 처리.
 *
 * 백엔드 `_format_parsed_items_to_raw_text`(api/app/api/v1/meals.py)와 *동일 변환* —
 * 클라이언트가 raw_text 안 보내고 parsed_items만 보낸 케이스에서도 wire 단일화 보장.
 */
import type { ParsedMealItem } from './mealSchema';

export function formatParsedItemsToRawText(items: ParsedMealItem[]): string {
  return items
    .map((item) => `${item.name} ${item.quantity}`.trimEnd())
    .join(', ');
}
