"use client";

/**
 * Web onboarding 4-체크박스 폼 (Story 1.3 AC14).
 *
 * 영업 데모 lock-in 회피용 minimal UI — 모바일 미설치 사용자가 dead-end에 빠지지 않도록.
 * PIPA 22조 별도 동의 + 23조 민감정보 별도 동의 의무 — 4 체크박스 시각 분리,
 * sensitive_personal_info는 horizontal divider + 별 색상 강조.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";

import { apiFetch } from "@/lib/api-fetch";

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

  const allChecked = acks.disclaimer && acks.terms && acks.privacy && acks.sensitive;

  async function handleSubmit() {
    setError(null);
    setSubmitting(true);
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
      });
      if (!response.ok) {
        setError(`동의 저장에 실패했습니다 (${response.status})`);
        return;
      }
      router.push("/dashboard");
    } finally {
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
