"use client";

/**
 * Admin 사용자 프로필 수정 폼 — Story 7.2 AC#8.
 *
 * Story 5.1 ``HealthProfileEditForm`` 패턴 정합 — ``healthProfileSchema``의 6 필드를
 * partial로 사용(admin은 마스킹된 값을 보므로 빈 입력 = 미변경 의미). 비-undefined 필드만
 * PATCH body에 포함(server는 ``HealthProfilePatchRequest`` partial 처리 + at-least-one
 * Pydantic 게이트).
 *
 * 마스킹된 필드(weight/height/allergies)는 UI에 plaintext 미노출 — 새 값을 *덮어쓰는*
 * 입력만 가능. 평문 노출(원문 보기 토글)은 Story 7.4 forward.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import {
  ACTIVITY_LEVEL_LABELS_KO,
  ACTIVITY_LEVEL_VALUES,
  HEALTH_GOAL_LABELS_KO,
  HEALTH_GOAL_VALUES,
  KOREAN_22_ALLERGENS,
  type ActivityLevel,
  type HealthGoal,
  type KoreanAllergen,
} from "@/features/onboarding/healthProfileSchema";
import type { AdminUserDetailResponse } from "@/features/admin/types";
import { adminApiFetch } from "@/lib/admin-api";

// 6 필드 모두 optional(partial) + admin 폼 컨텍스트 — 빈 입력 = 미변경.
const adminPatchSchema = z.object({
  age: z
    .number()
    .int("나이는 정수여야 합니다")
    .min(1)
    .max(150)
    .optional(),
  // ``multipleOf(0.1)``은 부동소수 정밀도로 70.1/70.3 등 false-reject 위험 →
  // backend ``Decimal(5,2)``가 정밀도 SOT, HTML ``step="0.1"``가 UX 가드. 폼 단에는
  // 범위만 강제.
  weight_kg: z.number().min(1.0).max(500.0).optional(),
  height_cm: z.number().int().min(50).max(300).optional(),
  activity_level: z.enum(ACTIVITY_LEVEL_VALUES).optional(),
  health_goal: z.enum(HEALTH_GOAL_VALUES).optional(),
  allergies: z.array(z.enum(KOREAN_22_ALLERGENS)).max(22).optional(),
});

type AdminPatchFormData = z.infer<typeof adminPatchSchema>;

interface ProblemDetail {
  code?: string;
  detail?: string;
}

interface Props {
  userId: string;
  initialDetail: AdminUserDetailResponse;
}

function parseNumber(text: string): number | undefined {
  if (text === "") return undefined;
  const n = Number(text);
  return Number.isFinite(n) ? n : undefined;
}

export function AdminProfileEditForm({ userId, initialDetail }: Props) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const {
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<AdminPatchFormData>({
    resolver: zodResolver(adminPatchSchema),
    defaultValues: {
      age: initialDetail.age ?? undefined,
      activity_level: (initialDetail.activity_level as ActivityLevel | null) ?? undefined,
      health_goal: (initialDetail.health_goal as HealthGoal | null) ?? undefined,
      // weight/height/allergies는 마스킹되어 plaintext 미노출 → 빈 상태로 시작.
    },
  });

  const onSubmit = handleSubmit(async (data) => {
    setError(null);
    setToast(null);
    // exclude_unset 의미를 흉내 — undefined 필드 제거.
    // ``allergies: []``는 *silent clear* 위험(admin은 마스킹 컨텍스트라 초기 빈 상태가
    // "미입력"이자 "전체 해제" 양의적). 폼 안내 문구 "비워두면 변경되지 않습니다" 정합 +
    // NFR-S2 식품 알레르기 안전 보호 — 빈 배열은 undefined로 흡수해 전송 안 함.
    const body: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(data)) {
      if (value === undefined) continue;
      if (key === "allergies" && Array.isArray(value) && value.length === 0) continue;
      body[key] = value;
    }
    if (Object.keys(body).length === 0) {
      setError("최소 하나의 필드를 변경해야 합니다.");
      return;
    }
    try {
      const response = await adminApiFetch(`/v1/admin/users/${userId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (response.ok) {
        await queryClient.invalidateQueries({
          queryKey: ["admin", "users", "detail", userId],
        });
        setToast("프로필이 갱신되었습니다.");
        return;
      }
      let problem: ProblemDetail = {};
      try {
        problem = (await response.json()) as ProblemDetail;
      } catch {
        // RFC 7807 본문이 아니면 status code만 표면.
      }
      if (response.status === 404 && problem.code === "admin.user.not_found") {
        setError("사용자를 찾을 수 없거나 이미 탈퇴된 상태입니다.");
        return;
      }
      if (response.status === 400 || response.status === 422) {
        setError("입력 값을 확인해 주세요.");
        return;
      }
      setError(problem.detail ?? `프로필 수정 실패 (${response.status})`);
    } catch {
      setError("네트워크 오류로 저장에 실패했습니다.");
    }
  });

  const isDeleted = initialDetail.deleted_at !== null;

  return (
    <form className="space-y-6" onSubmit={onSubmit} aria-label="관리자 프로필 수정 폼">
      <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
        체중·신장·알레르기는 마스킹된 상태입니다. 입력한 값으로 덮어쓰며, 비워두면 변경되지 않습니다.
      </p>

      {isDeleted && (
        <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          이 사용자는 탈퇴 진행 중이라 프로필 수정이 불가능합니다.
        </p>
      )}

      {/* 나이 */}
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-800">나이 (1~150)</label>
        <Controller
          control={control}
          name="age"
          render={({ field: { onChange, onBlur, value } }) => (
            <input
              type="number"
              inputMode="numeric"
              className="w-full rounded border border-zinc-300 px-3 py-2 text-sm"
              onBlur={onBlur}
              onChange={(e) => onChange(parseNumber(e.target.value))}
              value={value !== undefined ? String(value) : ""}
              aria-label="나이 (정수)"
              disabled={isDeleted}
            />
          )}
        />
        {errors.age && <p className="mt-1 text-sm text-red-600">{errors.age.message}</p>}
      </div>

      {/* 체중 */}
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-800">
          체중 (kg, 1.0~500.0) — {initialDetail.weight_kg_masked ?? "미입력"}
        </label>
        <Controller
          control={control}
          name="weight_kg"
          render={({ field: { onChange, onBlur, value } }) => (
            <input
              type="number"
              step="0.1"
              inputMode="decimal"
              className="w-full rounded border border-zinc-300 px-3 py-2 text-sm"
              onBlur={onBlur}
              onChange={(e) => onChange(parseNumber(e.target.value))}
              value={value !== undefined ? String(value) : ""}
              aria-label="체중"
              disabled={isDeleted}
            />
          )}
        />
        {errors.weight_kg && (
          <p className="mt-1 text-sm text-red-600">{errors.weight_kg.message}</p>
        )}
      </div>

      {/* 신장 */}
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-800">
          신장 (cm, 50~300) — {initialDetail.height_cm_masked ?? "미입력"}
        </label>
        <Controller
          control={control}
          name="height_cm"
          render={({ field: { onChange, onBlur, value } }) => (
            <input
              type="number"
              inputMode="numeric"
              className="w-full rounded border border-zinc-300 px-3 py-2 text-sm"
              onBlur={onBlur}
              onChange={(e) => onChange(parseNumber(e.target.value))}
              value={value !== undefined ? String(value) : ""}
              aria-label="신장"
              disabled={isDeleted}
            />
          )}
        />
        {errors.height_cm && (
          <p className="mt-1 text-sm text-red-600">{errors.height_cm.message}</p>
        )}
      </div>

      {/* 활동 수준 */}
      <fieldset>
        <legend className="mb-1 block text-sm font-medium text-zinc-800">활동 수준</legend>
        <Controller
          control={control}
          name="activity_level"
          render={({ field: { onChange, value } }) => (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {ACTIVITY_LEVEL_VALUES.map((level: ActivityLevel) => {
                const selected = value === level;
                return (
                  <label
                    key={level}
                    className={`flex cursor-pointer items-center gap-2 rounded border px-3 py-2 text-sm ${
                      selected
                        ? "border-blue-600 bg-blue-50 text-blue-800"
                        : "border-zinc-300 text-zinc-700"
                    } ${isDeleted ? "opacity-50" : ""}`}
                  >
                    <input
                      type="radio"
                      className="accent-blue-600"
                      checked={selected}
                      onChange={() => onChange(level)}
                      disabled={isDeleted}
                    />
                    <span>{ACTIVITY_LEVEL_LABELS_KO[level]}</span>
                  </label>
                );
              })}
            </div>
          )}
        />
      </fieldset>

      {/* 건강 목표 */}
      <fieldset>
        <legend className="mb-1 block text-sm font-medium text-zinc-800">건강 목표</legend>
        <Controller
          control={control}
          name="health_goal"
          render={({ field: { onChange, value } }) => (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {HEALTH_GOAL_VALUES.map((goal: HealthGoal) => {
                const selected = value === goal;
                return (
                  <label
                    key={goal}
                    className={`flex cursor-pointer items-center gap-2 rounded border px-3 py-2 text-sm ${
                      selected
                        ? "border-orange-600 bg-orange-50 text-orange-800"
                        : "border-zinc-300 text-zinc-700"
                    } ${isDeleted ? "opacity-50" : ""}`}
                  >
                    <input
                      type="radio"
                      className="accent-orange-600"
                      checked={selected}
                      onChange={() => onChange(goal)}
                      disabled={isDeleted}
                    />
                    <span>{HEALTH_GOAL_LABELS_KO[goal]}</span>
                  </label>
                );
              })}
            </div>
          )}
        />
      </fieldset>

      {/* 알레르기 */}
      <fieldset>
        <legend className="mb-1 block text-sm font-medium text-zinc-800">
          알레르기 — {initialDetail.allergies_count_masked ?? "미입력"}
        </legend>
        <Controller
          control={control}
          name="allergies"
          render={({ field: { onChange, value } }) => (
            <div className="flex flex-wrap gap-2">
              {KOREAN_22_ALLERGENS.map((allergen: KoreanAllergen) => {
                const current = value ?? [];
                const checked = current.includes(allergen);
                return (
                  <label
                    key={allergen}
                    className={`cursor-pointer rounded-full border px-3 py-1.5 text-xs ${
                      checked
                        ? "border-blue-600 bg-blue-600 text-white"
                        : "border-zinc-300 bg-zinc-50 text-zinc-700"
                    } ${isDeleted ? "opacity-50" : ""}`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={checked}
                      disabled={isDeleted}
                      onChange={() => {
                        const latest = value ?? [];
                        onChange(
                          latest.includes(allergen)
                            ? latest.filter((a) => a !== allergen)
                            : [...latest, allergen],
                        );
                      }}
                    />
                    {checked ? "✓ " : ""}
                    {allergen}
                  </label>
                );
              })}
            </div>
          )}
        />
      </fieldset>

      {error && (
        <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </p>
      )}
      {toast && (
        <p
          role="status"
          aria-live="polite"
          className="rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-800"
        >
          {toast}
        </p>
      )}

      <button
        type="submit"
        className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-zinc-300"
        disabled={isSubmitting || isDeleted}
      >
        {isSubmitting ? "저장 중…" : "프로필 저장"}
      </button>
    </form>
  );
}
