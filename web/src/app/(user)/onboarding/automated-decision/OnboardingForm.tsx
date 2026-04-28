"use client";

/**
 * Web 자동화 의사결정 동의 폼 (Story 1.4 AC9).
 *
 * 영업 데모 lock-in 회피용 minimal UI — 모바일 미설치 사용자도 본 별 동의를 부여 가능.
 * 5섹션 풀텍스트 + 1 체크박스 + *동의 완료* + AbortController/inflightRef 패턴
 * (Story 1.3 정합).
 */
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { apiFetch } from "@/lib/api-fetch";

interface ProblemDetail {
  code?: string;
  detail?: string;
  title?: string;
}

export interface OnboardingFormProps {
  title: string;
  body: string;
  version: string;
}

export default function OnboardingForm({ title, body, version }: OnboardingFormProps) {
  const router = useRouter();
  const [agreed, setAgreed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inflightRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  async function handleSubmit() {
    if (inflightRef.current) return;
    inflightRef.current = true;
    setError(null);
    setSubmitting(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await apiFetch("/v1/users/me/consents/automated-decision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ automated_decision_version: version }),
        signal: controller.signal,
      });
      if (response.ok) {
        // RSC `getServerSideConsents` 캐시 무효화 — 누락 시 `/dashboard` 가 stale
        // consents 로 다시 onboarding 으로 redirect 하는 loop 발생.
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
      if (
        response.status === 409 &&
        problem.code === "consent.automated_decision.version_mismatch"
      ) {
        setError(
          "동의서가 갱신되었습니다. 페이지를 새로 고침해 최신 텍스트로 다시 동의해 주세요.",
        );
        return;
      }
      if (response.status >= 500) {
        setError("일시적인 서버 오류로 동의 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.");
        return;
      }
      setError(problem.detail ?? `동의 저장에 실패했습니다 (${response.status})`);
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      setError("네트워크 오류로 동의 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      inflightRef.current = false;
      abortRef.current = null;
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <details open className="rounded border border-zinc-200 p-3">
        <summary className="cursor-pointer text-sm font-medium text-zinc-700">
          {title} (펼쳐서 풀텍스트 보기)
        </summary>
        <article className="mt-2 max-h-[480px] overflow-auto whitespace-pre-line text-xs leading-6 text-zinc-700">
          {body}
        </article>
      </details>

      <label className="flex items-start gap-2 cursor-pointer">
        <input
          type="checkbox"
          className="mt-1 accent-blue-600"
          checked={agreed}
          onChange={() => setAgreed((v) => !v)}
        />
        <span className="text-sm text-zinc-800">
          위 자동화된 의사결정 처리에 별도 동의합니다 (PIPA 2026.03.15)
        </span>
      </label>

      <button
        type="button"
        className="w-full rounded bg-blue-600 py-3 text-white font-semibold disabled:opacity-40"
        disabled={!agreed || submitting}
        onClick={() => void handleSubmit()}
      >
        {submitting ? "저장 중…" : "동의 완료"}
      </button>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </div>
  );
}
