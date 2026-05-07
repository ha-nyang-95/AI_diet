"use client";

/**
 * Web 데이터 내보내기 폼 (Story 5.3 AC5).
 *
 * react-hook-form + zod (Story 4.4 / 5.1 / 5.2 SOT 패턴 정합) — format RadioGroup. 표준
 * web 다운로드 패턴: ``apiFetch`` GET → ``response.blob()`` → ``URL.createObjectURL`` →
 * 임시 anchor ``download`` click → ``URL.revokeObjectURL``. 추가 의존성 0.
 *
 * filename은 server ``Content-Disposition`` 헤더에서 추출(RFC 6266 ``filename*`` 우선,
 * ``filename`` fallback). 둘 다 부재 시 client-side 재구성(``balancenote_export_{date}.{ext}``).
 *
 * non-destructive 시각 cue — primary blue(``bg-blue-600``)로 ``account/delete``의 destructive
 * red와 의미 분리.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import { apiFetch } from "@/lib/api-fetch";

const dataExportSchema = z.object({
  format: z.enum(["json", "csv"]),
});

type DataExportFormData = z.infer<typeof dataExportSchema>;

interface ProblemDetail {
  code?: string;
  detail?: string;
}

/**
 * RFC 6266 정합 — ``filename*=UTF-8''<percent-encoded>`` 우선(국제화 대응) +
 * ``filename="..."`` fallback. 둘 다 부재 시 ``null`` 반환 → caller가 client-side 재구성.
 *
 * XSS 가드: server에서 filename은 ASCII 라틴 + 숫자 + dot/_-만 구성(``_mask_user_id``
 * + ``YYYY-MM-DD`` + ``.json|.csv``) — 임의 사용자 입력 X. 본 파서는 정규식으로 제한.
 */
export function extractFilenameFromContentDisposition(header: string | null): string | null {
  if (!header) return null;
  // filename*=UTF-8''<percent-encoded>
  const utf8Match = header.match(/filename\*\s*=\s*UTF-8''([^;\s]+)/i);
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      // percent-decoding 실패 시 fallback로 진행.
    }
  }
  // filename="..."
  const quotedMatch = header.match(/filename\s*=\s*"([^"]+)"/i);
  if (quotedMatch) {
    return quotedMatch[1];
  }
  // filename=...
  const bareMatch = header.match(/filename\s*=\s*([^;\s]+)/i);
  if (bareMatch) {
    return bareMatch[1];
  }
  return null;
}

function buildFallbackFilename(format: "json" | "csv"): string {
  const date = new Date().toISOString().slice(0, 10); // yyyy-mm-dd UTC
  return `balancenote_export_${date}.${format}`;
}

export function DataExportForm() {
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const {
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<DataExportFormData>({
    resolver: zodResolver(dataExportSchema),
    defaultValues: { format: "json" },
  });

  const onSubmit = handleSubmit(async (data) => {
    setError(null);
    setSuccess(null);
    try {
      const response = await apiFetch(`/v1/users/me/export?format=${data.format}`, {
        method: "GET",
      });
      if (!response.ok) {
        let problem: ProblemDetail = {};
        try {
          problem = (await response.json()) as ProblemDetail;
        } catch {
          // RFC 7807 본문이 아니면 status code만 표면.
        }
        if (response.status === 401) {
          setError("다운로드 권한이 없습니다. 다시 로그인해 주세요.");
          window.location.assign("/login");
          return;
        }
        if (response.status === 400 && problem.code === "validation.error") {
          setError("입력 값을 확인해 주세요.");
          return;
        }
        if (response.status >= 500) {
          setError("일시적인 서버 오류로 다운로드에 실패했습니다.");
          return;
        }
        setError(problem.detail ?? `다운로드에 실패했습니다 (${response.status})`);
        return;
      }

      // 다운로드 — Blob + URL.createObjectURL + 임시 anchor click 표준 패턴.
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const filename =
        extractFilenameFromContentDisposition(response.headers.get("Content-Disposition")) ??
        buildFallbackFilename(data.format);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      // Safari + Firefox 호환 — body에 append 후 click하고 즉시 제거.
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      // 브라우저 메모리 회수 — Safari/일부 모바일 환경에서 ``anchor.click()`` 직후 OS
      // save dialog가 mount되기 전에 revoke되면 다운로드가 0 byte로 잘림. 1.5s 지연으로
      // dialog 진입 보장(이후엔 OS가 blob 데이터를 own).
      setTimeout(() => URL.revokeObjectURL(url), 1500);
      setSuccess("다운로드가 시작되었습니다.");
    } catch {
      setError("네트워크 오류로 다운로드에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }
  });

  return (
    <form className="space-y-5" onSubmit={onSubmit} aria-label="데이터 내보내기 폼">
      <div className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
        <p>
          내 식단·분석·프로필을 JSON/CSV로 다운로드합니다. PIPA 정보주체 권리에 따라 audit
          기록 없이 처리됩니다.
        </p>
      </div>

      <fieldset className="space-y-3">
        <legend className="mb-1 block text-sm font-medium text-zinc-800">형식 선택</legend>
        <Controller
          control={control}
          name="format"
          render={({ field: { onChange, value } }) => (
            <div className="space-y-2" role="radiogroup">
              <label
                className={
                  "flex cursor-pointer items-start gap-3 rounded-md border p-3 text-sm " +
                  (value === "json"
                    ? "border-blue-500 bg-blue-50"
                    : "border-zinc-300 bg-white hover:bg-zinc-50")
                }
              >
                <input
                  type="radio"
                  name="format"
                  value="json"
                  checked={value === "json"}
                  onChange={() => onChange("json")}
                  className="mt-0.5 h-4 w-4 border-zinc-300"
                  aria-label="JSON 형식"
                />
                <span>
                  <span className="block font-semibold text-zinc-900">JSON</span>
                  <span className="block text-zinc-600">
                    표준 JSON — 외부 도구·스크립트 분석에 적합.
                  </span>
                </span>
              </label>
              <label
                className={
                  "flex cursor-pointer items-start gap-3 rounded-md border p-3 text-sm " +
                  (value === "csv"
                    ? "border-blue-500 bg-blue-50"
                    : "border-zinc-300 bg-white hover:bg-zinc-50")
                }
              >
                <input
                  type="radio"
                  name="format"
                  value="csv"
                  checked={value === "csv"}
                  onChange={() => onChange("csv")}
                  className="mt-0.5 h-4 w-4 border-zinc-300"
                  aria-label="CSV 형식"
                />
                <span>
                  <span className="block font-semibold text-zinc-900">CSV</span>
                  <span className="block text-zinc-600">
                    한국어 헤더 — Excel·Google Sheets 직접 열기.
                  </span>
                </span>
              </label>
            </div>
          )}
        />
        {errors.format && (
          <p className="mt-1 text-sm text-red-600">{errors.format.message}</p>
        )}
      </fieldset>

      {error && (
        <p
          role="alert"
          aria-live="polite"
          className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error}
        </p>
      )}
      {success && (
        <p
          role="status"
          aria-live="polite"
          className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700"
        >
          {success}
        </p>
      )}

      <div className="flex gap-3">
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmitting ? "데이터 준비 중..." : "내보내기 시작"}
        </button>
      </div>
    </form>
  );
}
