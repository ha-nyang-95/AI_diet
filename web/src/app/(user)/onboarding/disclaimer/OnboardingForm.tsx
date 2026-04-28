"use client";

/**
 * Web onboarding 4-체크박스 폼 (Story 1.3 AC14).
 *
 * 영업 데모 lock-in 회피용 minimal UI — 모바일 미설치 사용자가 dead-end에 빠지지 않도록.
 * PIPA 22조 별도 동의 + 23조 민감정보 별도 동의 의무 — 4 체크박스 시각 분리,
 * sensitive_personal_info는 horizontal divider + 별 색상 강조.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { apiFetch } from "@/lib/api-fetch";

interface ProblemDetail {
  code?: string;
  detail?: string;
  title?: string;
}

interface DocSummary {
  title: string;
  body: string;
  version: string;
}

export interface OnboardingFormProps {
  disclaimer: DocSummary;
  terms: DocSummary;
  privacy: DocSummary;
}

export default function OnboardingForm({ disclaimer, terms, privacy }: OnboardingFormProps) {
  const router = useRouter();
  const [acks, setAcks] = useState({
    disclaimer: false,
    terms: false,
    privacy: false,
    sensitive: false,
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // double-click 방지용 — submitting state는 React 렌더 타이밍 의존이라 ref로 즉시 차단.
  const inflightRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    // 언마운트 시 in-flight 요청 abort — setState on unmounted 경고 차단.
    return () => abortRef.current?.abort();
  }, []);

  const allChecked = acks.disclaimer && acks.terms && acks.privacy && acks.sensitive;

  async function handleSubmit() {
    if (inflightRef.current) return;
    inflightRef.current = true;
    setError(null);
    setSubmitting(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await apiFetch("/v1/users/me/consents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          disclaimer_version: disclaimer.version,
          terms_version: terms.version,
          privacy_version: privacy.version,
          sensitive_personal_info_version: privacy.version,
        }),
        signal: controller.signal,
      });
      if (response.ok) {
        router.push("/dashboard");
        return;
      }
      let problem: ProblemDetail = {};
      try {
        problem = (await response.json()) as ProblemDetail;
      } catch {
        // RFC 7807 본문이 아니면 status code만 표면.
      }
      if (response.status === 409 && problem.code === "consent.version_mismatch") {
        setError("약관이 갱신되었습니다. 페이지를 새로 고침해 최신 텍스트로 다시 동의해 주세요.");
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
      <ConsentItem
        label="위 디스클레이머를 확인했습니다"
        title={disclaimer.title}
        body={disclaimer.body}
        checked={acks.disclaimer}
        onToggle={() => setAcks((s) => ({ ...s, disclaimer: !s.disclaimer }))}
      />
      <ConsentItem
        label="약관에 동의합니다"
        title={terms.title}
        body={terms.body}
        checked={acks.terms}
        onToggle={() => setAcks((s) => ({ ...s, terms: !s.terms }))}
      />
      <ConsentItem
        label="개인정보 처리방침에 동의합니다"
        title={privacy.title}
        body={privacy.body}
        checked={acks.privacy}
        onToggle={() => setAcks((s) => ({ ...s, privacy: !s.privacy }))}
      />

      <hr className="border-orange-200" />

      <div className="rounded border border-orange-300 bg-orange-50 p-4">
        <p className="text-xs font-semibold text-orange-700 mb-2">
          민감정보 별도 동의 (PIPA 23조)
        </p>
        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            className="mt-1 accent-orange-600"
            checked={acks.sensitive}
            onChange={() => setAcks((s) => ({ ...s, sensitive: !s.sensitive }))}
          />
          <span className="text-sm text-zinc-800">
            민감정보(체중·신장·알레르기·식사 기록) 처리에 별도 동의합니다
          </span>
        </label>
      </div>

      <button
        type="button"
        className="w-full rounded bg-blue-600 py-3 text-white font-semibold disabled:opacity-40"
        disabled={!allChecked || submitting}
        onClick={() => void handleSubmit()}
      >
        {submitting ? "저장 중…" : "동의 완료"}
      </button>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </div>
  );
}

interface ConsentItemProps {
  label: string;
  title: string;
  body: string;
  checked: boolean;
  onToggle: () => void;
}

function ConsentItem({ label, title, body, checked, onToggle }: ConsentItemProps) {
  return (
    <div>
      <details className="mb-2">
        <summary className="cursor-pointer text-sm font-medium text-zinc-700">
          {title} (펼쳐서 풀텍스트 보기)
        </summary>
        <article className="mt-2 max-h-64 overflow-auto whitespace-pre-line rounded border border-zinc-200 p-3 text-xs leading-6 text-zinc-700">
          {body}
        </article>
      </details>
      <label className="flex items-start gap-2 cursor-pointer">
        <input
          type="checkbox"
          className="mt-1 accent-blue-600"
          checked={checked}
          onChange={onToggle}
        />
        <span className="text-sm text-zinc-800">{label}</span>
      </label>
    </div>
  );
}
