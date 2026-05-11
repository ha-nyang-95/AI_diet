"use client";

/**
 * 사용자 PII 원문 보기 토글 — Story 7.4 AC#5 (FR39).
 *
 * 토글 ON 시 ``POST /v1/admin/users/{userId}/pii-reveal`` 호출 → plaintext PII 응답
 * 클라이언트 state 보존 + 5분 비활동 자동 복원(DOM event activity tracking + 1초
 * interval timer). 토글 OFF → 즉시 마스킹 복귀 + plaintext state 폐기.
 *
 * server-side reveal session(Redis TTL)은 Story 8 forward (외주 클라이언트 다중 admin
 * tamper resistance 요구 시점). 본 컴포넌트는 *MVP 1인 owner* 신뢰 모델 — bypass의
 * actual harm은 *자기 데이터를 자기가 더 오래 보는 것*(거버넌스 위반 0).
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { adminApiFetch } from "@/lib/admin-api";
import type { AdminUserPiiRevealResponse } from "./types";

const PII_REVEAL_TTL_MS = 5 * 60 * 1000;
const ACTIVITY_DEBOUNCE_MS = 500;
const COUNTDOWN_INTERVAL_MS = 1_000;
const ACTIVITY_EVENTS = ["mousemove", "keydown", "click", "touchstart"] as const;

type RevealStatus = "masked" | "loading" | "revealed";

interface RevealState {
  status: RevealStatus;
  plaintext: AdminUserPiiRevealResponse | null;
  expiresAt: number | null;
}

const INITIAL: RevealState = { status: "masked", plaintext: null, expiresAt: null };

function formatRemaining(ms: number): string {
  const safe = Math.max(0, ms);
  const totalSeconds = Math.ceil(safe / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function PlaintextPanel({ plaintext }: { plaintext: AdminUserPiiRevealResponse }) {
  return (
    <dl className="grid gap-x-6 gap-y-1 rounded-md border border-zinc-200 bg-white p-3 text-sm sm:grid-cols-2">
      <div className="flex items-baseline justify-between border-b border-zinc-100 py-2">
        <dt className="text-zinc-500">이메일</dt>
        <dd className="text-zinc-800">{plaintext.email}</dd>
      </div>
      <div className="flex items-baseline justify-between border-b border-zinc-100 py-2">
        <dt className="text-zinc-500">나이</dt>
        <dd className="text-zinc-800">{plaintext.age ?? "—"}</dd>
      </div>
      <div className="flex items-baseline justify-between border-b border-zinc-100 py-2">
        <dt className="text-zinc-500">체중 (kg)</dt>
        <dd className="text-zinc-800">
          {plaintext.weight_kg !== null ? `${plaintext.weight_kg.toFixed(1)}` : "—"}
        </dd>
      </div>
      <div className="flex items-baseline justify-between border-b border-zinc-100 py-2">
        <dt className="text-zinc-500">신장 (cm)</dt>
        <dd className="text-zinc-800">{plaintext.height_cm ?? "—"}</dd>
      </div>
      <div className="col-span-2 flex items-baseline justify-between border-b border-zinc-100 py-2">
        <dt className="text-zinc-500">알레르기</dt>
        <dd className="text-zinc-800">
          {plaintext.allergies === null
            ? "—"
            : plaintext.allergies.length === 0
              ? "등록 없음"
              : plaintext.allergies.join(", ")}
        </dd>
      </div>
    </dl>
  );
}

export function UserPiiToggle({ userId }: { userId: string }) {
  const [reveal, setReveal] = useState<RevealState>(INITIAL);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState<number>(() => Date.now());
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleReveal = useCallback(async () => {
    const confirmed = window.confirm(
      "사용자 개인정보(이메일·체중·신장·알레르기) 원문을 표시합니다. 5분 후 자동 복원됩니다. 계속하시겠습니까?",
    );
    if (!confirmed) return;
    setError(null);
    setReveal({ status: "loading", plaintext: null, expiresAt: null });
    try {
      const response = await adminApiFetch(`/v1/admin/users/${userId}/pii-reveal`, {
        method: "POST",
      });
      if (!response.ok) {
        setError("원문 보기 실패. 잠시 후 다시 시도하세요.");
        setReveal(INITIAL);
        return;
      }
      const plaintext = (await response.json()) as AdminUserPiiRevealResponse;
      setReveal({
        status: "revealed",
        plaintext,
        expiresAt: Date.now() + PII_REVEAL_TTL_MS,
      });
    } catch {
      setError("원문 보기 실패. 잠시 후 다시 시도하세요.");
      setReveal(INITIAL);
    }
  }, [userId]);

  const handleMask = useCallback(() => {
    setReveal(INITIAL);
    setError(null);
  }, []);

  // 활동 추적 — revealed 동안만 listener attach.
  useEffect(() => {
    if (reveal.status !== "revealed") return;

    const handler = () => {
      if (debounceRef.current) return; // debounce window 활성 중
      debounceRef.current = setTimeout(() => {
        debounceRef.current = null;
        setReveal((prev) =>
          prev.status === "revealed"
            ? { ...prev, expiresAt: Date.now() + PII_REVEAL_TTL_MS }
            : prev,
        );
      }, ACTIVITY_DEBOUNCE_MS);
    };

    for (const evt of ACTIVITY_EVENTS) {
      document.addEventListener(evt, handler, { passive: true });
    }
    return () => {
      for (const evt of ACTIVITY_EVENTS) {
        document.removeEventListener(evt, handler);
      }
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
    };
  }, [reveal.status]);

  // 1초 interval — expiresAt 만료 시 마스킹 복귀 + UX 카운트다운.
  useEffect(() => {
    if (reveal.status !== "revealed" || reveal.expiresAt === null) return;
    const interval = setInterval(() => {
      const tick = Date.now();
      setNow(tick);
      if (tick >= (reveal.expiresAt ?? 0)) {
        setReveal(INITIAL);
      }
    }, COUNTDOWN_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [reveal.status, reveal.expiresAt]);

  const remainingMs =
    reveal.status === "revealed" && reveal.expiresAt !== null
      ? reveal.expiresAt - now
      : 0;

  return (
    <section className="rounded-md border border-blue-200 bg-blue-50/40 p-3 space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-zinc-700">
          개인정보 원문 보기 (이메일·체중·신장·알레르기)
        </p>
        {reveal.status === "masked" && (
          <button
            type="button"
            onClick={handleReveal}
            className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            원문 보기 OFF
          </button>
        )}
        {reveal.status === "loading" && (
          <button
            type="button"
            disabled
            className="rounded bg-zinc-300 px-3 py-1.5 text-sm font-medium text-white"
          >
            불러오는 중…
          </button>
        )}
        {reveal.status === "revealed" && (
          <button
            type="button"
            onClick={handleMask}
            className="rounded border border-blue-600 bg-white px-3 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-50"
          >
            원문 보기 ON (자동 복원: {formatRemaining(remainingMs)} 후)
          </button>
        )}
      </div>
      {error && (
        <p className="text-sm text-red-600" role="status">
          {error}
        </p>
      )}
      {reveal.status === "revealed" && reveal.plaintext && (
        <PlaintextPanel plaintext={reveal.plaintext} />
      )}
    </section>
  );
}
