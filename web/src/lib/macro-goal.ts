/**
 * Web 매크로 목표 server-only fetch + type SOT (Story 4.4).
 *
 * 백엔드 ``GET /v1/users/me/macro_goal`` SSR fetch + Pydantic ``MacroGoal``과 동일 wire
 * format. ``getServerSideMacroGoal`` 패턴은 Story 4.3 ``getServerSideWeeklyReport``
 * 정합 — 401/5xx 등 non-ok는 모두 ``null`` 반환(페이지가 redirect/fallback 결정).
 */
import "server-only";

import { cookies } from "next/headers";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

/**
 * 사용자 매크로 목표 — 5 partial 필드. 백엔드 ``MacroGoal`` Pydantic 모델 wire format.
 *
 * - ``daily_calorie_target_kcal``: 800-6000 kcal.
 * - ``protein_target_g_per_meal``: 5-200 g/meal.
 * - ``macro_ratio_*_pct``: 0-100. 3 필드 *all-or-none* + sum=100 (백엔드 Pydantic 가드).
 *
 * 미설정 필드는 응답에 *omit*(``model_dump(exclude_none=True)``).
 */
export interface MacroGoal {
  daily_calorie_target_kcal?: number;
  protein_target_g_per_meal?: number;
  macro_ratio_carb_pct?: number;
  macro_ratio_protein_pct?: number;
  macro_ratio_fat_pct?: number;
}

/**
 * 매크로 목표 SSR fetch.
 *
 * @returns ``MacroGoal`` 또는 401/5xx 시 ``null``. 빈 객체 ``{}``는 *미설정 사용자*
 *          정상 응답이며 ``MacroGoal`` 빈 값으로 변환.
 */
export async function getServerSideMacroGoal(): Promise<MacroGoal | null> {
  const store = await cookies();
  const access = store.get("bn_access")?.value;
  if (!access) return null;
  const response = await fetch(`${API_BASE_URL}/v1/users/me/macro_goal`, {
    headers: { Cookie: `bn_access=${access}` },
    cache: "no-store",
  });
  if (!response.ok) return null;
  return (await response.json()) as MacroGoal;
}
