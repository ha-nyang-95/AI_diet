"use client";

/**
 * Web 건강 프로필 입력 폼 (Story 1.5 AC11).
 *
 * react-hook-form + zod (``healthProfileSchema``) 검증. submitting state + inflightRef +
 * AbortController(Story 1.3·1.4 정합). 성공 시 ``router.refresh()`` + ``router.push()``
 * 둘 다 호출(RSC stale cache 회피, Story 1.4 CR P4 정합).
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";

import {
  ACTIVITY_LEVEL_LABELS_KO,
  ACTIVITY_LEVEL_VALUES,
  HEALTH_GOAL_LABELS_KO,
  HEALTH_GOAL_VALUES,
  KOREAN_22_ALLERGENS,
  healthProfileSchema,
  type ActivityLevel,
  type HealthGoal,
  type HealthProfileFormData,
  type KoreanAllergen,
} from "@/features/onboarding/healthProfileSchema";
import { apiFetch } from "@/lib/api-fetch";

interface ProblemDetail {
  code?: string;
  detail?: string;
}

function parseNumber(text: string): number | undefined {
  // 빈 입력 → undefined (zod required로 분기). paste 등으로 NaN 슬립 시도 차단.
  if (text === "") return undefined;
  const n = Number(text);
  return Number.isFinite(n) ? n : undefined;
}

export default function HealthProfileForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  const {
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<HealthProfileFormData>({
    resolver: zodResolver(healthProfileSchema),
    defaultValues: { allergies: [] },
  });

  // react-hook-form은 ``handleSubmit`` async 핸들러 진행 중 ``isSubmitting=true``를 자동
  // 유지하며 button[disabled]가 double-submit을 차단(별도 inflightRef 불필요).
  const onSubmit = handleSubmit(async (data) => {
    setError(null);
    try {
      const response = await apiFetch("/v1/users/me/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (response.ok) {
        // RSC `getServerSideUser` 캐시 무효화 — 누락 시 dashboard가 stale
        // profile_completed_at으로 다시 onboarding으로 redirect하는 loop 발생.
        router.refresh();
        router.push("/dashboard");
        return;
      }
      let problem: ProblemDetail = {};
      try {
        problem = (await response.json()) as ProblemDetail;
      } catch {
        // RFC 7807 본문이 아니면 status code만 표면.
      }
      if (response.status === 403 && problem.code === "consent.basic.missing") {
        setError("필수 동의가 누락되었습니다. 다시 동의 화면으로 이동합니다.");
        router.push("/onboarding/disclaimer");
        return;
      }
      if (response.status === 400 && problem.code === "validation.error") {
        setError("입력 값을 확인해 주세요.");
        return;
      }
      if (response.status >= 500) {
        setError("일시적인 서버 오류로 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.");
        return;
      }
      setError(problem.detail ?? `프로필 저장에 실패했습니다 (${response.status})`);
    } catch {
      setError("네트워크 오류로 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }
  });

  return (
    <form className="space-y-6" onSubmit={onSubmit}>
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
              aria-label="나이 (정수, 1에서 150 사이)"
            />
          )}
        />
        {errors.age && <p className="mt-1 text-sm text-red-600">{errors.age.message}</p>}
      </div>

      {/* 체중 */}
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-800">체중 (kg, 1.0~500.0)</label>
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
              aria-label="체중 (소수, 1.0에서 500.0 kg 사이)"
            />
          )}
        />
        {errors.weight_kg && (
          <p className="mt-1 text-sm text-red-600">{errors.weight_kg.message}</p>
        )}
      </div>

      {/* 신장 */}
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-800">신장 (cm, 50~300)</label>
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
              aria-label="신장 (정수, 50에서 300 cm 사이)"
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
                    }`}
                  >
                    <input
                      type="radio"
                      className="accent-blue-600"
                      checked={selected}
                      onChange={() => onChange(level)}
                    />
                    <span>{ACTIVITY_LEVEL_LABELS_KO[level]}</span>
                  </label>
                );
              })}
            </div>
          )}
        />
        {errors.activity_level && (
          <p className="mt-1 text-sm text-red-600">{errors.activity_level.message}</p>
        )}
      </fieldset>

      {/* health_goal */}
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
                    }`}
                  >
                    <input
                      type="radio"
                      className="accent-orange-600"
                      checked={selected}
                      onChange={() => onChange(goal)}
                    />
                    <span>{HEALTH_GOAL_LABELS_KO[goal]}</span>
                  </label>
                );
              })}
            </div>
          )}
        />
        {errors.health_goal && (
          <p className="mt-1 text-sm text-red-600">{errors.health_goal.message}</p>
        )}
      </fieldset>

      {/* 알레르기 */}
      <fieldset>
        <legend className="mb-1 block text-sm font-medium text-zinc-800">
          알레르기 (해당 없으면 비워두세요)
        </legend>
        <Controller
          control={control}
          name="allergies"
          render={({ field: { onChange, value } }) => {
            // ``next`` 계산은 onChange 안에서 — render 시 pre-compute하면 빠른 연속 클릭 시
            // 같은 render의 stale snapshot으로 두 토글이 서로 덮어써 선택 유실.
            return (
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
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={checked}
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
            );
          }}
        />
        {errors.allergies && (
          <p className="mt-1 text-sm text-red-600">{errors.allergies.message}</p>
        )}
      </fieldset>

      <button
        type="submit"
        className="w-full rounded bg-blue-600 py-3 text-sm font-semibold text-white disabled:opacity-40"
        disabled={isSubmitting}
      >
        {isSubmitting ? "저장 중…" : "프로필 저장"}
      </button>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </form>
  );
}
