/**
 * Story 2.5 — 오프라인 텍스트 식단 큐잉 + 자동 sync (FR16, W46 흡수).
 *
 * AsyncStorage FIFO 큐 + 100건 hard cap + module-level mutex(single-flight) +
 * 지수 backoff(1s/2s/4s + jitter ±20%) + per-user namespace + module-level
 * subscriber 패턴 (Story 1.6 ``tutorialState.ts`` / Story 2.4 ``query-persistence`` 정합).
 *
 * 핵심 결정:
 * - **storage**: AsyncStorage. MMKV 회피(신규 native 의존성 + JSI 빌드 회귀 risk —
 *   Growth 시점 재평가). 100건 cap에서 I/O 부담 미미.
 * - **per-user namespace**: ``bn:offline-queue:meal:<user_id>`` (Story 1.6
 *   ``bn:onboarding-tutorial-seen-<user_id>`` 패턴 정합). 다중 사용자 단일 디바이스 격리.
 * - **mutex**: module-level ``flushing: Promise<FlushResult> | null`` flag로 동시
 *   `flushQueue` 호출 차단 — 자동 flush + manual retry 동시 트리거 race 차단.
 * - **client_id**: UUID v4. 단일 책임 두 활용 (큐 식별자 + ``Idempotency-Key`` 헤더 값).
 * - **schema migration 가드**: deserialize 실패 시 빈 array 반환 + ``removeItem``
 *   silent reset (Story 8 polish 시점에 buster pattern 도입 — DF29 forward).
 * - **`useOfflineQueue` hook**: ``useState`` + ``subscribeQueue`` + ``getQueueSnapshot``
 *   통합. 큐 변경 시 re-render 트리거. TanStack Query 미사용 — 큐는 *클라이언트 단독
 *   상태*(server state X).
 *
 * 재시도 정책 (D4):
 * - 항목별 backoff — ``attempts=0`` 즉시, ``attempts=1`` 1s, ``attempts=2`` 2s,
 *   ``attempts=3`` 4s. ``attempts >= 3`` 후 ``last_error`` 갱신 + 큐 잔존(manual retry).
 * - jitter ±20% — `baseMs * (1 + (Math.random() * 0.4 - 0.2))`.
 * - **partial 실패 granular**: 항목별 backoff. transient (5xx/네트워크 에러) 시 flush
 *   *중단*(다음 항목 시도 X — 일관 backoff 의미 보존).
 * - **4xx (400/422)**: 영구 실패 — 큐에서 즉시 제거 + ``last_error`` 보존(UI 안내).
 * - **2xx (200/201)**: 큐에서 제거. 200은 idempotent replay(서버가 이미 처리).
 *
 * 사진 큐잉 OUT — 사진 입력은 R2 presigned URL + R2 PUT + Vision API 모두 *온라인 필수*.
 * PATCH/DELETE 큐잉 OUT — POST 흐름만(epic AC). PATCH/DELETE는 화면 단계에서 차단.
 *
 * Anti-pattern 회피:
 * - localStorage / SecureStore 큐 storage X (RN localStorage 부재 + SecureStore는 토큰 전용).
 * - zustand/jotai 큐 상태 X (단일 큐 상태에 over-engineering — module-level subscriber 충분).
 * - setInterval 주기적 flush X (배터리 + 네트워크 abuse — 이벤트 기반).
 * - Promise.all 동시 sync X (transient 에러 시 backoff 의미 손실 — 순차 FIFO).
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState } from 'react';

import type { ParsedMealItem } from '@/features/meals/mealSchema';

// --- 상수 -------------------------------------------------------------------

/**
 * 100건 hard cap — 디바이스 storage abuse + UX 혼란 차단. 초과 시 ``enqueueMealCreate``는
 * ``OfflineQueueFullError`` throw — 호출 측이 Alert 노출. Story 8 polish 시점에 동적
 * cap 검토 (DF31).
 */
export const OFFLINE_QUEUE_MAX_SIZE = 100;

/**
 * 지수 backoff — ``attempts=1`` 1s, ``attempts=2`` 2s, ``attempts=3`` 4s. AWS / GCP /
 * Stripe webhook 표준 패턴. 본 스토리 baseline은 3회 후 큐 잔존(manual retry — D4 정합).
 */
const BACKOFF_BASE_MS = [0, 1000, 2000, 4000] as const;

/**
 * jitter ±20% — `baseMs * (1 + (Math.random() * 0.4 - 0.2))`. thundering herd 회피.
 */
const JITTER_RATIO = 0.2;

const STORAGE_KEY_PREFIX = 'bn:offline-queue:meal:';

// --- 타입 -------------------------------------------------------------------

export interface OfflineQueueItem {
  /**
   * UUID v4 — ``Idempotency-Key`` 헤더 송신값. 동시에 큐 식별자 + 클라이언트 list
   * optimistic 표시 키. 단일 UUID 두 책임 (Story 2.5 D3 — 유지보수 단순성).
   */
  client_id: string;
  /** 큐잉 시점 사용자 입력. trim 후 비공백 보장(input.tsx 책임). */
  raw_text: string;
  /**
   * ISO 8601 +09:00 송신 (TZ-aware). 미지정 시 큐잉 시점 KST `now` 자동 채움 —
   * 사용자가 큐잉한 시점이 식단 시점이라는 직관 정합.
   */
  ate_at?: string;
  /**
   * Story 2.3 schema sharing — 본 스토리 baseline은 *항상 null* (사진 큐잉 OUT).
   * 인터페이스 호환성만 유지.
   */
  parsed_items?: ParsedMealItem[] | null;
  /** 시도 횟수 (0-based). ``>= 3`` 후 ``last_error`` 갱신, 큐 잔존. */
  attempts: number;
  /** 마지막 sync 실패 메시지 (UI 표시 — *"오류 — 다시 시도"*). */
  last_error?: string;
  /** ISO 8601 — 마지막 시도 시각(다음 backoff 계산 input). */
  last_attempt_at?: string;
  /** ISO 8601 — 최초 큐잉 시각 (FIFO 정렬 키 + UI sub-text *"5분 전 입력"*). */
  enqueued_at: string;
}

export interface FlushResult {
  flushed_count: number;
  failed_permanent_count: number;
  remaining_count: number;
}

export class OfflineQueueFullError extends Error {
  constructor() {
    super('offline queue full (max 100 items)');
    this.name = 'OfflineQueueFullError';
  }
}

// --- subscriber 패턴 (module-level) -----------------------------------------

const subscribers = new Map<string, Set<() => void>>();

function _notifySubscribers(userId: string): void {
  const set = subscribers.get(userId);
  if (set) {
    for (const listener of set) listener();
  }
}

export function subscribeQueue(userId: string, listener: () => void): () => void {
  let set = subscribers.get(userId);
  if (!set) {
    set = new Set();
    subscribers.set(userId, set);
  }
  set.add(listener);
  return () => {
    const current = subscribers.get(userId);
    if (current) {
      current.delete(listener);
      if (current.size === 0) subscribers.delete(userId);
    }
  };
}

// --- storage I/O -----------------------------------------------------------

function _storageKey(userId: string): string {
  return `${STORAGE_KEY_PREFIX}${userId}`;
}

async function _readQueue(userId: string): Promise<OfflineQueueItem[]> {
  try {
    const raw = await AsyncStorage.getItem(_storageKey(userId));
    if (raw == null) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      // schema drift / corrupted — silent reset (DF29 forward).
      await AsyncStorage.removeItem(_storageKey(userId));
      return [];
    }
    return parsed as OfflineQueueItem[];
  } catch {
    // JSON.parse 실패 / AsyncStorage I/O 실패 — silent reset.
    try {
      await AsyncStorage.removeItem(_storageKey(userId));
    } catch {
      // swallow — read 실패 자체가 critical하지 않음 (다음 enqueue 호출에서 retry).
    }
    return [];
  }
}

async function _writeQueue(userId: string, queue: OfflineQueueItem[]): Promise<void> {
  await AsyncStorage.setItem(_storageKey(userId), JSON.stringify(queue));
}

// --- 공개 API --------------------------------------------------------------

/**
 * 큐 끝에 항목 추가. 100건 cap 초과 시 ``OfflineQueueFullError`` throw — 호출 측이
 * Alert 노출(*"오프라인 대기 항목이 너무 많아요(100+)"*).
 *
 * ``attempts=0`` + ``enqueued_at=now`` 자동 채움. ``ate_at`` 미지정 시 호출 측이
 * KST now 채워 송신 (input.tsx 책임).
 */
export async function enqueueMealCreate(
  userId: string,
  item: Omit<OfflineQueueItem, 'attempts' | 'enqueued_at'>,
): Promise<void> {
  const queue = await _readQueue(userId);
  if (queue.length >= OFFLINE_QUEUE_MAX_SIZE) {
    throw new OfflineQueueFullError();
  }
  const newItem: OfflineQueueItem = {
    ...item,
    attempts: 0,
    enqueued_at: new Date().toISOString(),
  };
  queue.push(newItem);
  await _writeQueue(userId, queue);
  _notifySubscribers(userId);
}

/**
 * UI 표시용 read-only snapshot. clone 반환 — 호출 측 mutation 차단.
 */
export async function getQueueSnapshot(userId: string): Promise<OfflineQueueItem[]> {
  const queue = await _readQueue(userId);
  return queue.map((item) => ({ ...item }));
}

/**
 * 항목 제거 (manual *"폐기"* 또는 4xx 영구 실패 처리). 알 수 없는 client_id는 no-op.
 */
export async function removeQueueItem(userId: string, clientId: string): Promise<void> {
  const queue = await _readQueue(userId);
  const filtered = queue.filter((item) => item.client_id !== clientId);
  if (filtered.length !== queue.length) {
    await _writeQueue(userId, filtered);
    _notifySubscribers(userId);
  }
}

// --- flush -----------------------------------------------------------------

let flushing: Promise<FlushResult> | null = null;

type AuthFetch = (input: string, init?: RequestInit) => Promise<Response>;

function _backoffMs(attempts: number): number {
  const base = BACKOFF_BASE_MS[Math.min(attempts, BACKOFF_BASE_MS.length - 1)];
  if (base === 0) return 0;
  const jitter = base * (Math.random() * (JITTER_RATIO * 2) - JITTER_RATIO);
  return Math.max(0, Math.round(base + jitter));
}

function _delay(ms: number): Promise<void> {
  if (ms <= 0) return Promise.resolve();
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function _persistItemUpdate(
  userId: string,
  clientId: string,
  patch: Partial<OfflineQueueItem>,
): Promise<void> {
  const queue = await _readQueue(userId);
  const idx = queue.findIndex((item) => item.client_id === clientId);
  if (idx === -1) return;
  queue[idx] = { ...queue[idx], ...patch };
  await _writeQueue(userId, queue);
}

async function _removeItemSilent(userId: string, clientId: string): Promise<void> {
  const queue = await _readQueue(userId);
  const filtered = queue.filter((item) => item.client_id !== clientId);
  if (filtered.length !== queue.length) {
    await _writeQueue(userId, filtered);
  }
}

async function _flushOnce(userId: string, authFetch: AuthFetch): Promise<FlushResult> {
  let result: FlushResult = {
    flushed_count: 0,
    failed_permanent_count: 0,
    remaining_count: 0,
  };

  // FIFO — head부터 처리. 매 항목 시도 후 큐 재조회 (외부 enqueue 추가 가능 — 하지만
  // 본 스토리 baseline은 단일 user 단일 flush — 큐 변경은 사실상 없음).
  while (true) {
    const queue = await _readQueue(userId);
    if (queue.length === 0) break;
    const item = queue[0];

    // backoff before retry — attempts=0 즉시, attempts>=1은 backoff.
    if (item.attempts >= 1) {
      if (item.attempts >= BACKOFF_BASE_MS.length) {
        // 3회 후 더 시도 X — 큐 잔존 + flush 중단 (manual retry는 사용자 명시 액션).
        result = { ...result, remaining_count: queue.length };
        break;
      }
      await _delay(_backoffMs(item.attempts));
    }

    // 시도 직전 attempts++ + last_attempt_at 갱신 (디스크 persist).
    const newAttempts = item.attempts + 1;
    await _persistItemUpdate(userId, item.client_id, {
      attempts: newAttempts,
      last_attempt_at: new Date().toISOString(),
    });

    // POST /v1/meals — Idempotency-Key 첨부.
    let response: Response;
    try {
      const body: Record<string, unknown> = { raw_text: item.raw_text };
      if (item.ate_at !== undefined) body.ate_at = item.ate_at;
      if (item.parsed_items !== undefined && item.parsed_items !== null) {
        body.parsed_items = item.parsed_items;
      }
      response = await authFetch('/v1/meals', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': item.client_id,
        },
        body: JSON.stringify(body),
      });
    } catch (err) {
      // 네트워크 에러 — transient. last_error 갱신 + flush 중단 (다음 항목 시도 X).
      const errMsg = err instanceof Error ? err.message : 'network error';
      await _persistItemUpdate(userId, item.client_id, { last_error: errMsg });
      const remaining = await _readQueue(userId);
      result = { ...result, remaining_count: remaining.length };
      break;
    }

    if (response.status >= 200 && response.status < 300) {
      // 2xx — 성공. 큐에서 제거 (200 idempotent replay 포함).
      await _removeItemSilent(userId, item.client_id);
      result = { ...result, flushed_count: result.flushed_count + 1 };
      _notifySubscribers(userId);
      continue;
    }

    if (response.status >= 400 && response.status < 500) {
      // 4xx — 영구 실패. 큐 즉시 제거 + last_error 보존 (UI 안내).
      const errMsg = await _extractErrorMessage(response);
      await _persistItemUpdate(userId, item.client_id, { last_error: errMsg });
      await _removeItemSilent(userId, item.client_id);
      result = {
        ...result,
        failed_permanent_count: result.failed_permanent_count + 1,
      };
      _notifySubscribers(userId);
      continue;
    }

    // 5xx — transient. last_error 갱신 + flush 중단 (다음 항목 시도 X — backoff 의미 보존).
    const errMsg = await _extractErrorMessage(response);
    await _persistItemUpdate(userId, item.client_id, { last_error: errMsg });
    const remaining = await _readQueue(userId);
    result = { ...result, remaining_count: remaining.length };
    break;
  }

  if (result.remaining_count === 0) {
    const finalQueue = await _readQueue(userId);
    result = { ...result, remaining_count: finalQueue.length };
  }

  _notifySubscribers(userId);
  return result;
}

async function _extractErrorMessage(response: Response): Promise<string> {
  try {
    const problem = (await response.json()) as { code?: string; detail?: string };
    return problem.detail ?? problem.code ?? `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

/**
 * 큐를 head부터 순차 sync. mutex(single-flight) — 진행 중 호출은 같은 promise 반환.
 *
 * 호출 시점:
 * - ``useOnlineStatus`` offline → online 전이 시 자동 (``(tabs)/meals/index.tsx``).
 * - 사용자 *"다시 시도"* manual retry.
 *
 * 큐 size 0 + 호출은 no-op (logger silent — UX 정합).
 */
export async function flushQueue(userId: string, authFetch: AuthFetch): Promise<FlushResult> {
  if (flushing) return flushing;
  flushing = (async () => {
    try {
      return await _flushOnce(userId, authFetch);
    } finally {
      flushing = null;
    }
  })();
  return flushing;
}

// --- React hook ------------------------------------------------------------

/**
 * 큐 snapshot 구독 hook — 큐 변경 시 re-render 트리거.
 *
 * mount 시 fetch + ``subscribeQueue`` 등록 → 변경 감지 시 fetch 재호출. unmount 시
 * unsubscribe. AsyncStorage I/O 실패는 빈 array fallback (silent — UX 정합).
 *
 * ``userId``가 빈 문자열일 때(로그인 전)는 빈 array 반환 + subscribe 미등록.
 */
export function useOfflineQueue(userId: string): OfflineQueueItem[] {
  const [queue, setQueue] = useState<OfflineQueueItem[]>([]);

  useEffect(() => {
    if (!userId) {
      setQueue([]);
      return;
    }
    let isCancelled = false;
    const refresh = (): void => {
      void getQueueSnapshot(userId).then((snapshot) => {
        if (!isCancelled) setQueue(snapshot);
      });
    };
    refresh();
    const unsubscribe = subscribeQueue(userId, refresh);
    return () => {
      isCancelled = true;
      unsubscribe();
    };
  }, [userId]);

  return queue;
}
