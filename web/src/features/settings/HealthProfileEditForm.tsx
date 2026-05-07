"use client";

/**
 * Web 건강 프로필 수정 폼 (Story 5.1 AC5).
 *
 * Story 1.5 ``HealthProfileForm``(onboarding 빈 폼)과 *별 컴포넌트* — D2 결정 정합:
 * Server vs Client 경계 + props 인터페이스 차이로 markup 중복 허용. *schema/labels/
 * constants는 단일 SOT*(``features/onboarding/healthProfileSchema.ts``).
 *
 * - ``initial: HealthProfileResponse`` props prefill — SSR fetch 결과를 ``defaultValues``로.
 * - ``apiFetch`` PATCH 호출 + RFC 7807 분기 + 저장 toast 3초 + ``router.refresh()``로
 *   RSC stale cache 무효화(Story 1.4 CR P4 정합).
 * - ``healthProfileSchema`` 그대로 import — 폼은 prefill된 6 필드를 *전체 송신*(PATCH는
 *   partial endpoint이지만 폼 UX는 일관성을 위해 전체 송신).
 */
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
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
  type HealthProfileResponse,
  type KoreanAllergen,
} from "@/features/onboarding/healthProfileSchema";
import { apiFetch } from "@/lib/api-fetch";

interface ProblemDetail {
  code?: string;
  detail?: string;
}

interface HealthProfileEditFormProps {
  initial: HealthProfileResponse;
}

function parseNumber(text: string): number | undefined {
  if (text === "") return undefined;
  const n = Number(text);
  return Number.isFinite(n) ? n : undefined;
}

function defaultValuesFor(initial: HealthProfileResponse): Partial<HealthProfileFormData> {
  return {
    age: initial.age ?? undefined,
    weight_kg: initial.weight_kg ?? undefined,
    height_cm: initial.height_cm ?? undefined,
    activity_level: initial.activity_level ?? undefined,
    health_goal: initial.health_goal ?? undefined,
    allergies: (initial.allergies ?? []) as KoreanAllergen[],
  };
}

export function HealthProfileEditForm({ initial }: HealthProfileEditFormProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const {
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<HealthProfileFormData>({
    resolver: zodResolver(healthProfileSchema),
    defaultValues: defaultValuesFor(initial),
  });

  useEffect(() => {
    return () => {
      if (toastTimerRef.current !== null) {
        clearTimeout(toastTimerRef.current);
        toastTimerRef.current = null;
      }
    };
  }, []);

  // react-hooks/refs는 *render-time* ref 접근을 차단하나 handleSubmit 콜백은 submit
  // 시점에만 실행 → false positive. 토스트 타이머 cleanup 정합 유지(MacroGoalForm SOT).
  // eslint-disable-next-line react-hooks/refs
  const onSubmit = handleSubmit(async (data) => {
    setError(null);
    setToastMessage(null);
    if (toastTimerRef.current !== null) {
      clearTimeout(toastTimerRef.current);
      toastTimerRef.current = null;
    }
    try {
      const response = await apiFetch("/v1/users/me/profile", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (response.ok) {
        // RSC ``getServerSideHealthProfile`` 캐시 무효화 — 다음 진입 시 fresh prefill.
        // 페이지는 유지(사용자가 추가 수정 가능 — onboarding flow의 ``router.push``와 분리).
        router.refresh();
        setToastMessage("프로필이 저장되었습니다. 다음 분석부터 반영됩니다.");
        toastTimerRef.current = setTimeout(() => {
          setToastMessage(null);
          toastTimerRef.current = null;
        }, 3000);
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
    <form className="space-y-6" onSubmit={onSubmit} aria-label="건강 프로필 수정 폼">
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
        <label className="mb-1 block text-sm font-medium text-zinc-800">
          체중 (kg, 1.0~500.0)
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
        <label className="mb-1 block text-sm font-medium text-zinc-800">
          신장 (cm, 50~300)
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
          )}
        />
        {errors.allergies && (
          <p className="mt-1 text-sm text-red-600">{errors.allergies.message}</p>
        )}
      </fieldset>

      {error ? (
        <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </p>
      ) : null}

      <div className="flex items-center justify-between gap-3">
        <button
          type="submit"
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          disabled={isSubmitting}
        >
          {isSubmitting ? "저장 중…" : "프로필 저장"}
        </button>
        <Link
          href="/dashboard"
          className="text-sm text-blue-600 underline-offset-4 hover:underline"
        >
          대시보드로 돌아가기
        </Link>
      </div>

      {toastMessage ? (
        <div
          role="status"
          aria-live="polite"
          className="rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-800"
        >
          {toastMessage}
        </div>
      ) : null}
    </form>
  );
}
