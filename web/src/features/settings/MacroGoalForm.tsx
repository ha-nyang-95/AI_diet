"use client";

/**
 * 매크로 목표 입력 폼 (Story 4.4 AC4) — react-hook-form + zod 첫 web 폼.
 *
 * - 5 number input + null 송신 = key 삭제 분기(빈 input은 ``null`` 변환).
 * - ratio all-or-none + sum=100 zod refine — 백엔드 Pydantic ``MacroGoal`` SOT 미러.
 * - 저장 성공 toast + 주간 리포트 링크 + Tab 순서 자연(NFR-A5).
 */

import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import {
  MacroGoalFetchError,
  useMacroGoalMutation,
  type MacroGoal,
  type MacroGoalPatchPayload,
} from "@/features/settings/api";

// nullable + 빈 입력은 null 변환. 백엔드 Pydantic ``MacroGoal`` Field range 미러.
const _nullableInt = (min: number, max: number) =>
  z
    .preprocess(
      (v) => (v === "" || v === null || v === undefined ? null : Number(v)),
      z.number().int().min(min).max(max).nullable(),
    )
    .transform((v) => (Number.isNaN(v as number) ? null : v));

const MacroGoalSchema = z
  .object({
    daily_calorie_target_kcal: _nullableInt(800, 6000),
    protein_target_g_per_meal: _nullableInt(5, 200),
    macro_ratio_carb_pct: _nullableInt(0, 100),
    macro_ratio_protein_pct: _nullableInt(0, 100),
    macro_ratio_fat_pct: _nullableInt(0, 100),
  })
  .refine(
    (data) => {
      const ratios = [
        data.macro_ratio_carb_pct,
        data.macro_ratio_protein_pct,
        data.macro_ratio_fat_pct,
      ];
      const setCount = ratios.filter((v) => v !== null).length;
      if (setCount === 0) return true;
      if (setCount !== 3) return false;
      return ratios.reduce<number>((acc, v) => acc + (v ?? 0), 0) === 100;
    },
    {
      message:
        "탄/단/지 비율은 셋 다 입력하거나 모두 비워두세요. 합은 100이어야 합니다.",
      path: ["macro_ratio_carb_pct"],
    },
  )
  .refine(
    (data) =>
      data.daily_calorie_target_kcal !== null ||
      data.protein_target_g_per_meal !== null ||
      data.macro_ratio_carb_pct !== null ||
      data.macro_ratio_protein_pct !== null ||
      data.macro_ratio_fat_pct !== null,
    {
      message: "최소 한 가지 항목을 입력하세요.",
      path: ["daily_calorie_target_kcal"],
    },
  );

type MacroGoalFormValues = z.infer<typeof MacroGoalSchema>;

export interface MacroGoalFormProps {
  initial: MacroGoal | null;
}

export function MacroGoalForm({ initial }: MacroGoalFormProps) {
  const initialValues: MacroGoalFormValues = {
    daily_calorie_target_kcal: initial?.daily_calorie_target_kcal ?? null,
    protein_target_g_per_meal: initial?.protein_target_g_per_meal ?? null,
    macro_ratio_carb_pct: initial?.macro_ratio_carb_pct ?? null,
    macro_ratio_protein_pct: initial?.macro_ratio_protein_pct ?? null,
    macro_ratio_fat_pct: initial?.macro_ratio_fat_pct ?? null,
  };

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<MacroGoalFormValues>({
    // zod 4 미사용 — react-hook-form resolvers v5는 zod 3.x SOT(`zodResolver`).
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(MacroGoalSchema as any),
    defaultValues: initialValues,
  });

  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const mutation = useMacroGoalMutation();

  const onSubmit = handleSubmit(async (data) => {
    setServerError(null);
    setToastMessage(null);
    try {
      const payload: MacroGoalPatchPayload = {
        daily_calorie_target_kcal: data.daily_calorie_target_kcal,
        protein_target_g_per_meal: data.protein_target_g_per_meal,
        macro_ratio_carb_pct: data.macro_ratio_carb_pct,
        macro_ratio_protein_pct: data.macro_ratio_protein_pct,
        macro_ratio_fat_pct: data.macro_ratio_fat_pct,
      };
      await mutation.mutateAsync(payload);
      setToastMessage("매크로 목표가 저장되었습니다. 다음 분석부터 반영됩니다.");
      // 3초 후 자동 close.
      setTimeout(() => setToastMessage(null), 3000);
    } catch (err) {
      if (err instanceof MacroGoalFetchError && err.bodyCode) {
        setServerError(err.message);
      } else {
        setServerError("저장에 실패했습니다 — 잠시 후 다시 시도해주세요.");
      }
    }
  });

  const fieldClass =
    "mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
  const labelClass = "block text-sm font-medium text-slate-900";
  const descClass = "mt-1 text-xs text-slate-500";
  const errorClass = "mt-1 text-xs text-red-600";

  return (
    <form
      noValidate
      className="space-y-6"
      onSubmit={onSubmit}
      aria-label="매크로 목표 입력 폼"
    >
      <div>
        <label htmlFor="daily_calorie_target_kcal" className={labelClass}>
          하루 칼로리 목표 (kcal)
        </label>
        <input
          id="daily_calorie_target_kcal"
          type="number"
          inputMode="numeric"
          placeholder="미설정"
          className={fieldClass}
          {...register("daily_calorie_target_kcal")}
        />
        <p className={descClass}>800 ~ 6000 kcal 범위</p>
        {errors.daily_calorie_target_kcal ? (
          <p className={errorClass}>
            {errors.daily_calorie_target_kcal.message}
          </p>
        ) : null}
      </div>

      <div>
        <label htmlFor="protein_target_g_per_meal" className={labelClass}>
          매끼 단백질 목표 (g)
        </label>
        <input
          id="protein_target_g_per_meal"
          type="number"
          inputMode="numeric"
          placeholder="미설정"
          className={fieldClass}
          {...register("protein_target_g_per_meal")}
        />
        <p className={descClass}>5 ~ 200 g 범위</p>
        {errors.protein_target_g_per_meal ? (
          <p className={errorClass}>
            {errors.protein_target_g_per_meal.message}
          </p>
        ) : null}
      </div>

      <fieldset className="rounded-md border border-slate-200 p-4">
        <legend className="px-1 text-sm font-medium text-slate-700">
          탄/단/지 비율 (셋 다 입력 또는 모두 비움, 합 100)
        </legend>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label htmlFor="macro_ratio_carb_pct" className={labelClass}>
              탄수화물 (%)
            </label>
            <input
              id="macro_ratio_carb_pct"
              type="number"
              inputMode="numeric"
              placeholder="미설정"
              className={fieldClass}
              {...register("macro_ratio_carb_pct")}
            />
          </div>
          <div>
            <label htmlFor="macro_ratio_protein_pct" className={labelClass}>
              단백질 (%)
            </label>
            <input
              id="macro_ratio_protein_pct"
              type="number"
              inputMode="numeric"
              placeholder="미설정"
              className={fieldClass}
              {...register("macro_ratio_protein_pct")}
            />
          </div>
          <div>
            <label htmlFor="macro_ratio_fat_pct" className={labelClass}>
              지방 (%)
            </label>
            <input
              id="macro_ratio_fat_pct"
              type="number"
              inputMode="numeric"
              placeholder="미설정"
              className={fieldClass}
              {...register("macro_ratio_fat_pct")}
            />
          </div>
        </div>
        {errors.macro_ratio_carb_pct ? (
          <p className={errorClass}>{errors.macro_ratio_carb_pct.message}</p>
        ) : null}
      </fieldset>

      {serverError ? (
        <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {serverError}
        </p>
      ) : null}

      <div className="flex items-center justify-between gap-3">
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {mutation.isPending ? "저장 중…" : "저장"}
        </button>
        <Link
          href="/dashboard/weekly"
          className="text-sm text-blue-600 underline-offset-4 hover:underline"
        >
          주간 리포트로 돌아가기
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
