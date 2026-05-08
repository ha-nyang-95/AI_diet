"use client";

/**
 * Web 정기결제 신청 위젯 — Story 6.1 AC8.
 *
 * Toss Payments 공식 widget SDK + (a) 결제 위젯 패턴 (최초 1회 결제 confirm). 빌링키
 * 발급 + 자동 갱신은 Story 6.3 forward(`requestBillingAuth` API).
 *
 * 흐름:
 * 1. mount 시 ``loadPaymentWidget(clientKey, customerKey)`` 호출 → ``setWidget``.
 * 2. ``widget.renderPaymentMethods("#payment-method", { value: 9900 })`` + ``renderAgreement``.
 * 3. *"구독 신청"* 버튼 → ``orderId``/``idempotencyKey`` 생성(``crypto.randomUUID``) +
 *    localStorage에 idempotencyKey 저장 → ``widget.requestPayment(...)`` → Toss 결제
 *    화면 진입(브라우저 redirect).
 * 4. success/fail 라우트(``/account/subscribe/success`` / ``/account/subscribe/fail``)가
 *    callback 처리.
 *
 * 활성 구독 분기: mount 시 ``apiFetch("/v1/payments/subscription")`` GET — 200 응답이면
 * widget 렌더 X + *"중복 구독 불가"* 안내 (Story 6.2 cancel forward).
 *
 * App Store IAP 정합과 직교(본 컴포넌트는 Web 한정).
 */
import { useEffect, useRef, useState } from "react";
import {
  loadPaymentWidget,
  type PaymentWidgetInstance,
} from "@tosspayments/payment-widget-sdk";

import { apiFetch } from "@/lib/api-fetch";

const PLAN_PRICE_KRW = 9900;
// CR P6 — fallback 제거. 환경 변수 미설정 시 fail-closed (위젯 init에서 명시 에러). prod
// 환경에서 sandbox 키로 silent routing되는 운영 사고 차단.
const TOSS_CLIENT_KEY = process.env.NEXT_PUBLIC_TOSS_CLIENT_KEY ?? "";

// localStorage key — success 라우트에서 read 후 *delete*. 같은 mount 동안 retry 시
// 재사용 (Story 2.5 패턴 정합).
export const SUBSCRIBE_IDEMPOTENCY_STORAGE_KEY = "balancenote.subscribe.idempotency_key";

interface ActiveSubscription {
  id: string;
  status: "active" | "cancelled" | "expired";
  plan: "monthly";
  plan_price_krw: number;
  started_at: string;
  expires_at: string | null;
  provider: "toss" | "stripe";
}

interface SubscribeFormProps {
  /** 사용자 식별 — Toss customerKey + payload customerEmail. */
  userId: string;
  customerEmail?: string | null;
}

export function SubscribeForm({ userId, customerEmail }: SubscribeFormProps) {
  const [widget, setWidget] = useState<PaymentWidgetInstance | null>(null);
  const [active, setActive] = useState<ActiveSubscription | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);
  // CR P9 — 같은 mount 동안 idempotencyKey 불변(retry 시 재사용 — Story 2.5 패턴).
  // useEffect 후 세팅 X — 첫 렌더부터 안정 값 보유(StrictMode double-mount + fast click
  // race 차단).
  const idempotencyKeyRef = useRef<string>(crypto.randomUUID());

  // 1) active 구독 1차 조회 — 200이면 widget 렌더 X + 안내만.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await apiFetch("/v1/payments/subscription");
        if (cancelled) return;
        if (response.ok) {
          const body = (await response.json()) as ActiveSubscription;
          setActive(body);
        } else if (response.status === 401) {
          // CR P10 — 세션 만료 시 결제 진행 차단 + 로그인 유도.
          setError("로그인이 만료되었습니다. 다시 로그인 후 결제를 시도해 주세요.");
          return;
        } else if (response.status !== 404) {
          // 404는 *활성 구독 없음* — 정상 진입. 그 외 5xx 등은 결제 차단 안전망.
          setError(`구독 상태 조회 실패 (${response.status})`);
        }
      } catch {
        // 네트워크 오류는 widget 렌더 진입(낙관적) — 실제 결제 호출 시점에 503으로 노출.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 2) widget mount — active 분기 통과 후만 진행.
  useEffect(() => {
    if (loading) return;
    if (active !== null) return; // 활성 구독 — widget 렌더 X.
    if (TOSS_CLIENT_KEY === "") {
      // CR P6 — 환경 변수 누락 시 fail-closed.
      setError("결제 설정 오류가 발생했습니다. 관리자에게 문의해 주세요.");
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        const customerKey = `customer-${userId}`;
        const w = await loadPaymentWidget(TOSS_CLIENT_KEY, customerKey);
        if (cancelled) return;
        w.renderPaymentMethods("#payment-method", { value: PLAN_PRICE_KRW });
        w.renderAgreement("#agreement");
        setWidget(w);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "결제 위젯 로딩 실패",
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loading, active, userId]);

  const handleSubscribe = async () => {
    if (widget === null) return;
    setError(null);
    setSubmitting(true);
    // CR P11 — try/finally로 submitting 상태 복구 보장. ``widget.requestPayment``가
    // 정상 redirect되면 페이지가 unmount되어 submitting 복구 무관. 팝업 차단/SDK silent
    // failure로 redirect 미발생 시 submitting=true 영구 stuck 차단.
    try {
      const orderId = crypto.randomUUID();
      const idempotencyKey = idempotencyKeyRef.current;

      // localStorage에 저장 — success 라우트에서 read 후 사용.
      try {
        localStorage.setItem(SUBSCRIBE_IDEMPOTENCY_STORAGE_KEY, idempotencyKey);
      } catch {
        // localStorage 비활성(privacy mode 등) — success 라우트는 헤더 없이 호출
        // (첫 신청 — replay 분기 미진입). 502 retry 시점에 새 키로 시도.
      }

      const baseUrl = window.location.origin;
      await widget.requestPayment({
        orderId,
        orderName: "BalanceNote 월간 구독",
        successUrl: `${baseUrl}/account/subscribe/success`,
        failUrl: `${baseUrl}/account/subscribe/fail`,
        customerEmail: customerEmail ?? undefined,
      });
      // Toss 결제 화면이 열리고 브라우저 redirect됨 — 본 함수 이후는 도달 X(redirect
      // 시 finally도 실행되지 않음).
    } catch (err) {
      setError(err instanceof Error ? err.message : "결제 요청 실패");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="rounded-md border border-zinc-200 bg-zinc-50 p-6 text-sm text-zinc-700">
        구독 정보를 불러오는 중입니다…
      </div>
    );
  }

  if (active !== null) {
    return (
      <div className="space-y-4">
        <div className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
          <p className="font-medium">활성 구독이 있습니다.</p>
          <p className="mt-1">
            중복 구독은 신청할 수 없습니다. 구독 해지는 다음 업데이트에서 가능합니다.
          </p>
        </div>
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <dt className="text-zinc-600">플랜</dt>
          <dd className="text-zinc-900">월 {active.plan_price_krw.toLocaleString("ko-KR")}원</dd>
          <dt className="text-zinc-600">시작일</dt>
          <dd className="text-zinc-900">{new Date(active.started_at).toLocaleDateString("ko-KR")}</dd>
          <dt className="text-zinc-600">다음 결제일</dt>
          <dd className="text-zinc-900">
            {active.expires_at !== null
              ? new Date(active.expires_at).toLocaleDateString("ko-KR")
              : "-"}
          </dd>
        </dl>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-zinc-200 bg-white p-4 text-sm text-zinc-800">
        <p className="text-base font-medium">정기결제 1플랜</p>
        <p className="mt-1 text-2xl font-semibold">
          월 {PLAN_PRICE_KRW.toLocaleString("ko-KR")}원
        </p>
        <p className="mt-2 text-xs text-zinc-500">
          매월 자동으로 결제되며, 언제든 해지할 수 있습니다.
        </p>
      </div>

      {/* Toss widget 마운트 영역 */}
      <div id="payment-method" />
      <div id="agreement" />

      {error !== null ? (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => {
          void handleSubscribe();
        }}
        disabled={widget === null || submitting}
        className="w-full rounded-md bg-blue-600 px-4 py-3 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
        aria-label="월 9,900원 정기결제 신청"
      >
        {submitting
          ? "결제 진행 중…"
          : `월 ${PLAN_PRICE_KRW.toLocaleString("ko-KR")}원 구독 신청`}
      </button>
    </div>
  );
}
