/**
 * Story 2.5 — 오프라인 텍스트 식단 큐잉 + 자동 sync (FR16, W46 흡수).
 *
 * AsyncStorage FIFO 큐 + 100건 hard cap + per-userId 직렬화 mutex(write + flush
 * single-flight) + 지수 backoff(1s/2s + jitter ±20%) + per-user namespace +
 * module-level subscriber 패턴 (Story 1.6 ``tutorialState.ts`` / Story 2.4
 * ``query-persistence`` 정합).
 *
 * 핵심 결정:
 * - **storage**: AsyncStorage. MMKV 회피(신규 native 의존성 + JSI 빌드 회귀 risk —
 *   Growth 시점 재평가). 100건 cap에서 I/O 부담 미미.
 * - **per-user namespace**: ``bn:offline-queue:meal:<user_id>`` (Story 1.6
 *   ``bn:onboarding-tutorial-seen-<user_id>`` 패턴 정합). 다중 사용자 단일 디바이스 격리.
 * - **per-userId 직렬화**: AsyncStorage R-M-W race 차단을 위해 모든 큐 mutation을
 *   `_userLocks: Map<string, Promise<void>>` 기반 chain으로 직렬화. flush single-flight도
 *   userId별 키로 격리(cross-user lock leak 차단 — CR P1).
 * - **client_id**: UUID v4. 단일 책임 두 활용 (큐 식별자 + ``Idempotency-Key`` 헤더 값).
 *   enqueue 시점에 클라이언트 v4 형식 검증(서버 regex와 동일) — 비-v4 silent drop 차단(CR P9).
 * - **빈 userId 가드**: enqueue/flush 진입점에서 empty string 거부 — `bn:offline-queue:meal:`
 *   rogue namespace 방지 (CR P10).
 * - **schema migration 가드**: deserialize 실패 또는 item shape 위반 시 빈 array 반환 +
 *   ``removeItem`` silent reset (DF45 forward, CR P14 부분 적용).
 * - **`useOfflineQueue` hook**: ``useState`` + ``subscribeQueue`` + ``getQueueSnapshot``
 *   통합. 큐 변경 시 re-render 트리거. TanStack Query 미사용 — 큐는 *클라이언트 단독
 *   상태*(server state X).
 *
 * 재시도 정책 (D4 + CR P8 정정 — 3회 send cap):
 * - 항목별 backoff — ``attempts=0`` 즉시, ``attempts=1`` 1s, ``attempts=2`` 2s.
 *   ``attempts >= 3`` 후 ``last_error`` 갱신 + 큐 잔존(stuck — manual retry는 reset 후 재시도).
 * - jitter ±20% — `baseMs * (1 + (Math.random() * 0.4 - 0.2))`.
 * - **partial 실패 granular**: 항목별 backoff. transient (5xx/429/네트워크 에러) 시 flush
 *   *중단*(다음 항목 시도 X — 일관 backoff 의미 보존).
 * - **4xx (400/422)**: 영구 실패 — 큐에서 즉시 제거 + ``last_error`` 마스킹 후 보존(NFR-S5
 *   raw_text 마스킹 — CR P13).
 * - **401**: flush 즉시 abort (`authFetch` redirect 도달 가정 위반 시 영구 손실 차단 — CR P6).
 * - **429**: transient(잔존 + backoff — CR P6).
 * - **2xx (200/201)**: 큐에서 제거. 200은 idempotent replay(서버가 이미 처리).
 *
 * Manual retry (CR P16 — D4 literal 충족, DF46 closed):
 * - `resetAttempts(userId, clientId?)` — clientId 미지정 시 큐 전체 항목의 attempts=0.
 *   사용자 *"다시 시도"* 시 호출 → `flushQueue` 진입 → stuck 항목도 재시도 가능.
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
 * cap 검토 (DF47).
 */
export const OFFLINE_QUEUE_MAX_SIZE = 100;

/**
 * 지수 backoff — ``attempts=1`` 1s, ``attempts=2`` 2s. 총 3회 송신(attempts=0/1/2)
 * 후 ``attempts=3`` 도달 시 stuck. AWS / GCP / Stripe webhook 표준 패턴.
 */
const BACKOFF_BASE_MS = [0, 1000, 2000] as const;

/** 총 send 시도 cap — `BACKOFF_BASE_MS.length`와 동기. attempts ≥ MAX_ATTEMPTS 시 stuck. */
const MAX_ATTEMPTS = BACKOFF_BASE_MS.length;

/**
 * jitter ±20% — `baseMs * (1 + (Math.random() * 0.4 - 0.2))`. thundering herd 회피.
 */
const JITTER_RATIO = 0.2;

const STORAGE_KEY_PREFIX = 'bn:offline-queue:meal:';

/**
 * UUID v4 형식 — 백엔드 `_IDEMPOTENCY_KEY_PATTERN`(api/app/api/v1/meals.py:117)과 동일.
 * 클라이언트 enqueue 전에 검증 — 비-v4 randomUUID() 결과의 silent permanent drop 차단(CR P9).
 */
const UUID_V4_REGEX =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$/;

/** `last_error` 영속/UI 노출 시 길이 cap (NFR-S5 raw_text echo 마스킹 — CR P13). */
const LAST_ERROR_MAX_LEN = 80;

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
  /**
   * post-send count — `enqueueMealCreate`에서 0으로 시작하고 매 송신 *후* +1. 첫 송신
   * 후 1, 두 번째 송신 후 2, 세 번째 송신 후 3 → stuck. UI 라벨 *"N회 시도 실패"*는
   * 직관 정합(`attempts === 3` 시 *"3회 시도 실패"*).
   */
  attempts: number;
  /** 마지막 sync 실패 메시지 — 길이 cap 후 영속(NFR-S5 raw_text 마스킹 — CR P13). */
  last_error?: string;
  /** ISO 8601 — 마지막 시도 시각(다음 backoff 계산 input). */
  last_attempt_at?: string;
  /** ISO 8601 — 최초 큐잉 시각 (FIFO 정렬 키 + UI sub-text *"5분 전 입력"*). */
  enqueued_at: string;
}

export interface FlushResult {
  flushed_count: number;
  failed_permanent_count: number;
  /** CR P11 — 4xx로 큐에서 제거된 항목들의 raw_text 발췌(앞 20자). */
  failed_permanent_excerpts: string[];
  /** CR P15 — attempts ≥ MAX_ATTEMPTS로 stuck 상태인 항목 수 (UI manual retry 안내). */
  stuck_count: number;
  remaining_count: number;
  /** CR P6 — 401 등으로 flush 자체 abort된 케이스 (UI silent — `authFetch`가 redirect 처리). */
  aborted_unauthorized: boolean;
}

export class OfflineQueueFullError extends Error {
  constructor() {
    super('offline queue full (max 100 items)');
    this.name = 'OfflineQueueFullError';
  }
}

export class OfflineQueueInvalidUserError extends Error {
  constructor() {
    super('offline queue requires non-empty userId');
    this.name = 'OfflineQueueInvalidUserError';
  }
}

export class OfflineQueueInvalidClientIdError extends Error {
  constructor() {
    super('offline queue client_id must be UUID v4');
    this.name = 'OfflineQueueInvalidClientIdError';
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

// --- 직렬화 mutex (per-userId, CR P2) --------------------------------------

const _userLocks = new Map<string, Promise<unknown>>();

/**
 * Per-userId 직렬화 — 모든 R-M-W AsyncStorage mutation을 chain으로 직렬화.
 * enqueue / persistItemUpdate / removeItem 동시 호출 시 last-write-wins 손실 차단.
 * 결과 자체는 throw 가능 — caller에 surface (chain은 다음 호출이 reject를 swallow).
 */
async function _withUserLock<T>(userId: string, fn: () => Promise<T>): Promise<T> {
  const prev = _userLocks.get(userId) ?? Promise.resolve();
  // 이전 작업의 throw는 chain에서 swallow — 다음 mutation 진입 보장.
  const next = prev.catch(() => undefined).then(fn);
  _userLocks.set(userId, next);
  try {
    return await next;
  } finally {
    // 가장 최근 promise만 cleanup (race로 더 새 mutation이 등록된 경우 보존).
    if (_userLocks.get(userId) === next) {
      _userLocks.delete(userId);
    }
  }
}

// --- storage I/O -----------------------------------------------------------

function _storageKey(userId: string): string {
  return `${STORAGE_KEY_PREFIX}${userId}`;
}

function _isValidQueueItem(value: unknown): value is OfflineQueueItem {
  if (typeof value !== 'object' || value === null) return false;
  const item = value as Record<string, unknown>;
  if (typeof item.client_id !== 'string' || !UUID_V4_REGEX.test(item.client_id)) {
    return false;
  }
  if (typeof item.raw_text !== 'string' || item.raw_text.length === 0) return false;
  if (typeof item.attempts !== 'number' || !Number.isFinite(item.attempts)) return false;
  if (typeof item.enqueued_at !== 'string') return false;
  return true;
}

async function _readQueue(userId: string): Promise<OfflineQueueItem[]> {
  try {
    const raw = await AsyncStorage.getItem(_storageKey(userId));
    if (raw == null) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      // schema drift / corrupted — silent reset (DF45 forward).
      await AsyncStorage.removeItem(_storageKey(userId));
      return [];
    }
    // CR P14 — 각 item shape 검증. 위반 항목은 silent drop (POST에 undefined 송신
    // → 400 → 영구 drop 회귀 차단). 모든 항목 위반 시 빈 array.
    const valid: OfflineQueueItem[] = [];
    let hasInvalid = false;
    for (const candidate of parsed) {
      if (_isValidQueueItem(candidate)) {
        valid.push(candidate);
      } else {
        hasInvalid = true;
      }
    }
    if (hasInvalid) {
      // 일부 항목 폐기 — 디스크에 정합 큐 재기록(다음 mutation에서 일관성 유지).
      try {
        await AsyncStorage.setItem(_storageKey(userId), JSON.stringify(valid));
      } catch {
        // setItem 실패는 surface 하지 않음 (read-side로 valid 반환은 그대로 가능).
      }
    }
    return valid;
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

function _truncateError(message: string): string {
  // CR P13 — NFR-S5 마스킹: 길이 cap + 줄바꿈/제어문자 제거. raw_text echo 차단의 1차 layer.
  // (서버 detail 자체에 raw_text 발췌가 포함될 수 있으나 길이 cap으로 노출 표면 축소.)
  const cleaned = message.replace(/[\r\n\t]+/g, ' ').trim();
  if (cleaned.length <= LAST_ERROR_MAX_LEN) return cleaned;
  return `${cleaned.slice(0, LAST_ERROR_MAX_LEN - 1)}…`;
}

// --- 공개 API --------------------------------------------------------------

/**
 * 큐 끝에 항목 추가. 100건 cap 초과 시 ``OfflineQueueFullError`` throw — 호출 측이
 * Alert 노출(*"오프라인 대기 항목이 너무 많아요(100+)"*). 빈 userId / 비-UUID v4
 * client_id는 즉시 throw — silent permanent drop 회귀 차단(CR P9, P10).
 *
 * ``attempts=0`` + ``enqueued_at=now`` 자동 채움. ``ate_at`` 미지정 시 호출 측이
 * KST `+09:00` now 채워 송신 (input.tsx 책임 — D3 정합).
 */
export async function enqueueMealCreate(
  userId: string,
  item: Omit<OfflineQueueItem, 'attempts' | 'enqueued_at'>,
): Promise<void> {
  if (!userId) throw new OfflineQueueInvalidUserError();
  if (!UUID_V4_REGEX.test(item.client_id)) {
    throw new OfflineQueueInvalidClientIdError();
  }
  await _withUserLock(userId, async () => {
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
  });
  _notifySubscribers(userId);
}

/**
 * UI 표시용 read-only snapshot. clone 반환 — 호출 측 mutation 차단.
 * 빈 userId 호출은 빈 array 반환 (로그인 전 호출 케이스).
 */
export async function getQueueSnapshot(userId: string): Promise<OfflineQueueItem[]> {
  if (!userId) return [];
  const queue = await _readQueue(userId);
  return queue.map((item) => ({ ...item }));
}

/**
 * 항목 제거 (manual *"폐기"* 또는 4xx 영구 실패 처리). 알 수 없는 client_id는 no-op.
 */
export async function removeQueueItem(userId: string, clientId: string): Promise<void> {
  if (!userId) return;
  let mutated = false;
  await _withUserLock(userId, async () => {
    const queue = await _readQueue(userId);
    const filtered = queue.filter((item) => item.client_id !== clientId);
    if (filtered.length !== queue.length) {
      await _writeQueue(userId, filtered);
      mutated = true;
    }
  });
  if (mutated) _notifySubscribers(userId);
}

/**
 * Manual retry 시 큐 항목들의 ``attempts``를 0으로 reset (CR P16 — D4 literal, DF46 closed).
 *
 * - `clientId` 미지정 → 큐 전체 항목 reset.
 * - `clientId` 지정 → 해당 항목만 reset.
 * - `last_error`도 동시 클리어 (UI에서 *"오류"* 표시 제거).
 *
 * stuck(`attempts >= MAX_ATTEMPTS`) 항목이 manual retry로 다시 송신 가능해진다 —
 * D4 literal 충족.
 */
export async function resetAttempts(userId: string, clientId?: string): Promise<void> {
  if (!userId) return;
  let mutated = false;
  await _withUserLock(userId, async () => {
    const queue = await _readQueue(userId);
    let dirty = false;
    const next = queue.map((item) => {
      if (clientId !== undefined && item.client_id !== clientId) return item;
      if (item.attempts === 0 && item.last_error === undefined) return item;
      dirty = true;
      const reset: OfflineQueueItem = { ...item, attempts: 0 };
      delete reset.last_error;
      delete reset.last_attempt_at;
      return reset;
    });
    if (dirty) {
      await _writeQueue(userId, next);
      mutated = true;
    }
  });
  if (mutated) _notifySubscribers(userId);
}

// --- flush -----------------------------------------------------------------

/** Per-userId flush single-flight (CR P1 — module-global lock cross-user leak 차단). */
const flushingByUser = new Map<string, Promise<FlushResult>>();

type AuthFetch = (input: string, init?: RequestInit) => Promise<Response>;

function _backoffMs(attempts: number): number {
  const idx = Math.min(attempts, BACKOFF_BASE_MS.length - 1);
  const base = BACKOFF_BASE_MS[idx];
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
  await _withUserLock(userId, async () => {
    const queue = await _readQueue(userId);
    const idx = queue.findIndex((item) => item.client_id === clientId);
    if (idx === -1) return;
    queue[idx] = { ...queue[idx], ...patch };
    await _writeQueue(userId, queue);
  });
}

async function _removeItemSilent(userId: string, clientId: string): Promise<void> {
  await _withUserLock(userId, async () => {
    const queue = await _readQueue(userId);
    const filtered = queue.filter((item) => item.client_id !== clientId);
    if (filtered.length !== queue.length) {
      await _writeQueue(userId, filtered);
    }
  });
}

async function _flushOnce(userId: string, authFetch: AuthFetch): Promise<FlushResult> {
  let result: FlushResult = {
    flushed_count: 0,
    failed_permanent_count: 0,
    failed_permanent_excerpts: [],
    stuck_count: 0,
    remaining_count: 0,
    aborted_unauthorized: false,
  };

  // FIFO — head부터 처리. 매 항목 시도 후 큐 재조회 (외부 enqueue 추가 가능 — 하지만
  // 본 스토리 baseline은 단일 user 단일 flush — 큐 변경은 사실상 없음).
  // CR W1 forward (DF54): 진행 가드(stuck/break/persist) + per-userId mutex로 외부 enqueue
  // race도 직렬화되므로 무한 루프 위험 없음. 이론적 storage 부패는 _readQueue silent reset.
  while (true) {
    const queue = await _readQueue(userId);
    if (queue.length === 0) break;
    const item = queue[0];

    // CR P8 — 3회 send cap (`attempts >= MAX_ATTEMPTS` stuck — flush 중단, manual retry는
    // `resetAttempts`로 attempts=0 후 재진입).
    if (item.attempts >= MAX_ATTEMPTS) {
      result = {
        ...result,
        stuck_count: result.stuck_count + 1,
        remaining_count: queue.length,
      };
      break;
    }

    // backoff before retry — attempts=0 즉시, attempts>=1은 backoff.
    if (item.attempts >= 1) {
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
      const errMsg = _truncateError(err instanceof Error ? err.message : 'network error');
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

    // CR P6 — 4xx 분기 세분화: 401 abort, 429 transient, 400/422 영구 drop.
    if (response.status === 401) {
      // `authFetch` redirect 도달 X 가정 위반 케이스 — flush 즉시 abort, 큐 잔존
      // (사용자 재로그인 후 자동 flush로 재시도 가능). attempts++는 그대로 영속.
      const remaining = await _readQueue(userId);
      result = {
        ...result,
        aborted_unauthorized: true,
        remaining_count: remaining.length,
      };
      break;
    }

    if (response.status === 429) {
      // rate limit — transient. 잔존 + flush 중단(다음 항목 시도 X — backoff 의미 보존).
      const errMsg = await _extractErrorMessage(response);
      await _persistItemUpdate(userId, item.client_id, { last_error: errMsg });
      const remaining = await _readQueue(userId);
      result = { ...result, remaining_count: remaining.length };
      break;
    }

    if (response.status === 400 || response.status === 422) {
      // 영구 실패 — 큐 즉시 제거 + last_error 보존 + raw_text 발췌 수집.
      const errMsg = await _extractErrorMessage(response);
      await _persistItemUpdate(userId, item.client_id, { last_error: errMsg });
      await _removeItemSilent(userId, item.client_id);
      result = {
        ...result,
        failed_permanent_count: result.failed_permanent_count + 1,
        failed_permanent_excerpts: [
          ...result.failed_permanent_excerpts,
          item.raw_text.slice(0, 20),
        ],
      };
      _notifySubscribers(userId);
      continue;
    }

    // 5xx 또는 기타 — transient. last_error 갱신 + flush 중단 (다음 항목 시도 X).
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
    return _truncateError(problem.detail ?? problem.code ?? `HTTP ${response.status}`);
  } catch {
    return `HTTP ${response.status}`;
  }
}

/**
 * 큐를 head부터 순차 sync. per-userId mutex(single-flight) — 진행 중 호출은 같은
 * promise 반환. cross-user lock leak 차단(CR P1 — userId별 분리).
 *
 * 호출 시점:
 * - ``useOnlineStatus`` offline → online 전이 시 자동 (``(tabs)/meals/index.tsx``).
 * - 사용자 *"다시 시도"* manual retry (`resetAttempts` 후 호출).
 *
 * 큐 size 0 + 호출은 no-op (logger silent — UX 정합).
 * 빈 userId 호출은 즉시 reject — silent drop 차단(CR P10).
 */
export async function flushQueue(userId: string, authFetch: AuthFetch): Promise<FlushResult> {
  if (!userId) throw new OfflineQueueInvalidUserError();
  const inFlight = flushingByUser.get(userId);
  if (inFlight) return inFlight;
  const promise = (async () => {
    try {
      return await _flushOnce(userId, authFetch);
    } finally {
      flushingByUser.delete(userId);
    }
  })();
  flushingByUser.set(userId, promise);
  return promise;
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
