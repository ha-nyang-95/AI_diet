"use client";

/**
 * Web 회원 탈퇴 폼 (Story 5.2 AC6).
 *
 * react-hook-form + zod (Story 4.4 / 5.1 SOT) — confirmation checkbox required + reason
 * textarea(maxLength=200, optional). 성공 시 ``window.location.href = "/login"`` 으로
 * 강제 redirect(쿠키 clear는 server 측 ``DELETE /me``가 ``clear_auth_cookies`` 재사용).
 *
 * destructive 버튼 스타일: ``bg-red-600 hover:bg-red-700`` — 사용자 시각 cue + 명시 라벨
 * *"탈퇴 확정"*. PIPA Art.35 정합으로 가드 X(미동의 사용자도 진입 가능).
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import { apiFetch } from "@/lib/api-fetch";

const accountDeleteSchema = z.object({
  reason: z.string().max(200, "사유는 200자 이하로 입력해 주세요").optional(),
  // confirmation checkbox required — 미체크 시 zod required 위반으로 submit 차단
  // (우발 클릭 방어).
  acknowledged: z.literal(true, {
    errorMap: () => ({ message: "30일 후 영구 파기됨을 확인해 주세요" }),
  }),
});

type AccountDeleteFormData = z.infer<typeof accountDeleteSchema>;

interface ProblemDetail {
  code?: string;
  detail?: string;
}

export function AccountDeleteForm() {
  const [error, setError] = useState<string | null>(null);

  const {
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<AccountDeleteFormData>({
    resolver: zodResolver(accountDeleteSchema),
    defaultValues: {
      reason: "",
      acknowledged: false as unknown as true,
    },
  });

  const onSubmit = handleSubmit(async (data) => {
    setError(null);
    const reasonTrimmed = (data.reason ?? "").trim();
    const body = reasonTrimmed.length > 0 ? { reason: reasonTrimmed } : {};
    try {
      const response = await apiFetch("/v1/users/me", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (response.status === 204) {
        // 쿠키 clear는 server 측 ``clear_auth_cookies``가 처리 — 클라이언트는 단순 redirect.
        // ``react-hooks/immutability``: ``window.location.assign``으로 교체(setter X).
        window.location.assign("/login");
        return;
      }
      let problem: ProblemDetail = {};
      try {
        problem = (await response.json()) as ProblemDetail;
      } catch {
        // RFC 7807 본문이 아니면 status code만 표면.
      }
      if (response.status === 400 && problem.code === "validation.error") {
        setError("입력 값을 확인해 주세요.");
        return;
      }
      if (response.status >= 500) {
        setError("일시적인 서버 오류로 탈퇴 처리에 실패했습니다. 잠시 후 다시 시도해 주세요.");
        return;
      }
      setError(problem.detail ?? `탈퇴 처리에 실패했습니다 (${response.status})`);
    } catch {
      setError("네트워크 오류로 탈퇴 처리에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }
  });

  return (
    <form className="space-y-5" onSubmit={onSubmit} aria-label="회원 탈퇴 폼">
      <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800">
        <p className="font-medium">탈퇴 시 30일 후 모든 데이터가 영구 파기됩니다.</p>
        <p className="mt-1">
          30일 내 같은 Google 계정으로 재로그인 시 안내가 표시됩니다. 복구를 원하시면
          고객문의로 연락해 주세요.
        </p>
      </div>

      <div>
        <label
          htmlFor="account-delete-reason"
          className="mb-1 block text-sm font-medium text-zinc-800"
        >
          탈퇴 사유 (선택, 200자 이내)
        </label>
        <Controller
          control={control}
          name="reason"
          render={({ field: { onChange, onBlur, value } }) => (
            <textarea
              id="account-delete-reason"
              className="w-full rounded border border-zinc-300 px-3 py-2 text-sm"
              rows={4}
              maxLength={200}
              placeholder="불편한 점이 있으셨다면 알려주세요 (선택)"
              onBlur={onBlur}
              onChange={(e) => onChange(e.target.value)}
              value={value ?? ""}
            />
          )}
        />
        {errors.reason && (
          <p className="mt-1 text-sm text-red-600">{errors.reason.message}</p>
        )}
      </div>

      <div>
        <label className="flex items-start gap-2 text-sm text-zinc-800">
          <Controller
            control={control}
            name="acknowledged"
            render={({ field: { onChange, value } }) => (
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 rounded border-zinc-300"
                checked={Boolean(value)}
                onChange={(e) => onChange(e.target.checked)}
                aria-label="30일 후 영구 파기 확인"
              />
            )}
          />
          <span>30일 후 모든 데이터가 영구 파기됨을 이해했습니다.</span>
        </label>
        {errors.acknowledged && (
          <p className="mt-1 text-sm text-red-600">{errors.acknowledged.message}</p>
        )}
      </div>

      {error && (
        <p
          role="alert"
          aria-live="polite"
          className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error}
        </p>
      )}

      <div className="flex gap-3">
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmitting ? "처리 중..." : "탈퇴 확정"}
        </button>
      </div>
    </form>
  );
}
