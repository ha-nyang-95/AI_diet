/**
 * Story 3.7 — `useMealAnalysisStream` SSE + polling fallback orchestrator hook (AC10).
 *
 * 흐름:
 * 1. 마운트 시 `react-native-sse` `EventSource`로 `POST /v1/analysis/stream` 연결.
 * 2. 6 이벤트 핸들러(progress/token/citation/clarify/done/error) 등록.
 * 3. SSE connection error + (done/clarify/error 미수신) → 1.5초 후 polling 강등.
 * 4. polling: `setInterval(1500)` + `GET /v1/analysis/{meal_id}` envelope 분기.
 *    - status=done → state.phase='done' + result.
 *    - status=needs_clarification → state.phase='clarify' + options.
 *    - status=error → state.phase='error' + problem.
 *    - status=in_progress → 다음 interval 대기. 30회(45초) 이후 timeout.
 * 5. cleanup: useEffect return → eventSource.close() + clearInterval(멱등).
 *
 * `submitClarification(value)`:
 * - `POST /v1/analysis/clarify` (SSE 응답) — 동일 EventSource 핸들러 재사용.
 * - state.text='' / phase='streaming'으로 reset 후 새 SSE 흐름 진입.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import EventSource from 'react-native-sse';

import { authFetch, API_BASE_URL } from '@/lib/auth';
import { getAccessToken } from '@/lib/secure-store';

import type { FitScoreLabel, MealMacros } from './mealSchema';

type StreamPhase =
  | 'connecting'
  | 'streaming'
  | 'clarify'
  | 'done'
  | 'error'
  | 'polling';
type StreamMode = 'sse' | 'polling';

export interface ClarificationOption {
  label: string;
  value: string;
}

export interface AnalysisDoneResult {
  meal_id: string;
  final_fit_score: number;
  fit_score_label: FitScoreLabel;
  macros: MealMacros;
  feedback_text: string;
  citations_count: number;
  used_llm: 'gpt-4o-mini' | 'claude' | 'stub';
}

export interface CitationItem {
  index: number;
  source: string;
  doc_title: string;
  published_year: number | null;
}

export interface AnalysisProblem {
  type?: string;
  title: string;
  status: number;
  detail?: string | null;
  instance?: string | null;
  code: string;
}

export interface StreamState {
  phase: StreamPhase;
  text: string;
  citations: CitationItem[];
  clarificationOptions: ClarificationOption[];
  result: AnalysisDoneResult | null;
  error: AnalysisProblem | null;
  mode: StreamMode;
}

interface UseMealAnalysisStreamReturn {
  state: StreamState;
  reset: () => void;
  submitClarification: (value: string) => Promise<void>;
}

const POLLING_INTERVAL_MS = 1500;
const POLLING_MAX_ATTEMPTS = 30;
const POLLING_FALLBACK_DELAY_MS = 1500;
// CR Wave 1 #19 — 연속 5xx 5회 시 error phase로 bail (30회 cap 도달 전 빠른 실패).
const POLLING_MAX_5XX_STREAK = 5;
// CR Wave 1 #20 — SSE 첫 progress 후 30s 무이벤트 시 polling 강등(idle timeout).
const SSE_INACTIVITY_TIMEOUT_MS = 30000;
// SSE 핸들러는 connection error를 retry 형식 raw event 또는 `error` event로 모두 받을 수
// 있어 양쪽 분기 처리.
const TERMINAL_PHASES: ReadonlyArray<StreamPhase> = ['done', 'clarify', 'error'];

const _initialState = (): StreamState => ({
  phase: 'connecting',
  text: '',
  citations: [],
  clarificationOptions: [],
  result: null,
  error: null,
  mode: 'sse',
});

export function useMealAnalysisStream(mealId: string): UseMealAnalysisStreamReturn {
  const [state, setState] = useState<StreamState>(_initialState);

  // 진행 중 자원 — useRef로 stable 보유(setState로 trigger re-render 회피).
  const eventSourceRef = useRef<EventSource | null>(null);
  const pollingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // CR Wave 1 #20 — SSE inactivity timer (첫 이벤트 후 30s 무신호 → polling 강등).
  const inactivityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollingAttemptsRef = useRef<number>(0);
  // CR Wave 1 #19 — 연속 5xx 카운터.
  const polling5xxStreakRef = useRef<number>(0);
  // CR Wave 1 #17 — `_pollOnce` AbortController로 mealId prop 변경 시 stale fetch 차단.
  const pollAbortRef = useRef<AbortController | null>(null);
  // 동시 마운트/재진입 시 stale closure 차단 — phase가 terminal에 도달하면 후속 callback no-op.
  const terminalReachedRef = useRef<boolean>(false);

  const _stopPolling = useCallback(() => {
    if (pollingTimerRef.current !== null) {
      clearInterval(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }
  }, []);

  const _stopFallbackTimer = useCallback(() => {
    if (fallbackTimerRef.current !== null) {
      clearTimeout(fallbackTimerRef.current);
      fallbackTimerRef.current = null;
    }
  }, []);

  const _stopInactivityTimer = useCallback(() => {
    if (inactivityTimerRef.current !== null) {
      clearTimeout(inactivityTimerRef.current);
      inactivityTimerRef.current = null;
    }
  }, []);

  const _abortPoll = useCallback(() => {
    if (pollAbortRef.current !== null) {
      pollAbortRef.current.abort();
      pollAbortRef.current = null;
    }
  }, []);

  const _closeEventSource = useCallback(() => {
    if (eventSourceRef.current !== null) {
      try {
        eventSourceRef.current.close();
      } catch {
        // no-op — 이중 close 멱등.
      }
      eventSourceRef.current = null;
    }
  }, []);

  const _markTerminal = useCallback(
    (next: Partial<StreamState>) => {
      terminalReachedRef.current = true;
      _closeEventSource();
      _stopPolling();
      _stopFallbackTimer();
      _stopInactivityTimer();
      _abortPoll();
      setState((prev) => ({ ...prev, ...next }));
    },
    [_closeEventSource, _stopPolling, _stopFallbackTimer, _stopInactivityTimer, _abortPoll],
  );

  const _pollOnce = useCallback(async () => {
    if (terminalReachedRef.current) return;
    pollingAttemptsRef.current += 1;
    if (pollingAttemptsRef.current > POLLING_MAX_ATTEMPTS) {
      _markTerminal({
        phase: 'error',
        error: {
          title: 'Polling timeout',
          status: 504,
          code: 'analysis.polling.timeout',
          detail: '분석이 평소보다 오래 걸려요. 잠시 후 다시 시도해주세요',
        },
      });
      return;
    }
    // CR Wave 1 #17 — AbortController per-call. 이전 in-flight fetch는 cleanup이 abort.
    const controller = new AbortController();
    pollAbortRef.current = controller;

    let response: Response;
    try {
      response = await authFetch(`/v1/analysis/${mealId}`, { signal: controller.signal });
    } catch (err) {
      // AbortError(unmount/mealId 변경)는 silent — 그 외 일시 장애도 다음 tick 재시도.
      if (controller.signal.aborted) return;
      // 네트워크 일시 장애 — 다음 interval에서 재시도(타임아웃 cap이 가드).
      return;
    }
    if (controller.signal.aborted) return;

    let body: Record<string, unknown> = {};
    try {
      body = (await response.json()) as Record<string, unknown>;
    } catch {
      return;
    }
    if (controller.signal.aborted) return;

    // CR Wave 1 #19 — 연속 5xx 카운터(persistent server error 시 빠른 실패).
    if (response.status >= 500) {
      polling5xxStreakRef.current += 1;
      if (polling5xxStreakRef.current >= POLLING_MAX_5XX_STREAK) {
        _markTerminal({
          phase: 'error',
          error: {
            title: 'Polling server error',
            status: response.status,
            code: (body.code as string) ?? 'analysis.polling.server_error',
            detail: '서버에서 분석 결과를 가져올 수 없어요. 잠시 후 다시 시도해주세요',
          },
        });
        return;
      }
      return; // 다음 tick 재시도.
    }
    polling5xxStreakRef.current = 0;

    const status = body.status as string | undefined;
    if (response.ok && status === 'done') {
      const result = body.result as AnalysisDoneResult;
      _markTerminal({
        phase: 'done',
        text: result.feedback_text,
        result,
      });
      return;
    }
    if (response.ok && status === 'needs_clarification') {
      const options = (body.options as ClarificationOption[]) ?? [];
      _markTerminal({ phase: 'clarify', clarificationOptions: options });
      return;
    }
    if (response.ok && status === 'error') {
      _markTerminal({
        phase: 'error',
        error: (body.problem as AnalysisProblem) ?? null,
      });
      return;
    }
    // 202 in_progress 또는 4xx 분기 — in_progress는 다음 tick 대기.
    // CR Wave 1 #18 — 401은 authFetch가 1회 자동 refresh + retry 후에도 도달 시. 여기까지
    // 오면 refresh 실패라 더 polling해도 무의미 → terminal error.
    if (response.status === 401) {
      _markTerminal({
        phase: 'error',
        error: {
          title: 'Authentication required',
          status: 401,
          code: 'auth.expired',
          detail: '로그인이 만료되었어요. 다시 로그인해주세요',
        },
      });
      return;
    }
    if (response.status === 404 || response.status === 403 || response.status === 429) {
      _markTerminal({
        phase: 'error',
        error: {
          title: 'Polling failed',
          status: response.status,
          code: (body.code as string) ?? 'analysis.unknown',
          detail: (body.detail as string | undefined) ?? null,
        },
      });
    }
  }, [mealId, _markTerminal]);

  const _startPolling = useCallback(() => {
    if (terminalReachedRef.current) return;
    if (pollingTimerRef.current !== null) return;
    setState((prev) => ({ ...prev, phase: 'polling', mode: 'polling' }));
    pollingAttemptsRef.current = 0;
    void _pollOnce();
    pollingTimerRef.current = setInterval(() => {
      void _pollOnce();
    }, POLLING_INTERVAL_MS);
  }, [_pollOnce]);

  const _scheduleFallback = useCallback(() => {
    if (terminalReachedRef.current) return;
    if (fallbackTimerRef.current !== null) return;
    fallbackTimerRef.current = setTimeout(() => {
      fallbackTimerRef.current = null;
      if (!terminalReachedRef.current) {
        _startPolling();
      }
    }, POLLING_FALLBACK_DELAY_MS);
  }, [_startPolling]);

  const _resetInactivityTimer = useCallback(() => {
    if (terminalReachedRef.current) return;
    if (inactivityTimerRef.current !== null) {
      clearTimeout(inactivityTimerRef.current);
    }
    inactivityTimerRef.current = setTimeout(() => {
      inactivityTimerRef.current = null;
      // CR Wave 1 #20 — SSE inactivity → polling 강등.
      if (!terminalReachedRef.current) {
        _scheduleFallback();
      }
    }, SSE_INACTIVITY_TIMEOUT_MS);
  }, [_scheduleFallback]);

  const _openEventSource = useCallback(
    async (clarifyValue: string | null) => {
      // CR Wave 1 #16 — `getAccessToken()` await 도중 unmount/mealId 변경 race 가드.
      // terminal 도달했으면 EventSource 생성 자체를 skip(zombie network connection 차단).
      const access = await getAccessToken();
      if (terminalReachedRef.current) return;

      const baseUrl = API_BASE_URL.replace(/\/$/, ''); // CR Wave 1 #23 — trailing slash 정규화.
      const url = clarifyValue !== null
        ? `${baseUrl}/v1/analysis/clarify`
        : `${baseUrl}/v1/analysis/stream`;
      const body =
        clarifyValue !== null
          ? JSON.stringify({ meal_id: mealId, selected_value: clarifyValue })
          : JSON.stringify({ meal_id: mealId });

      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      };
      if (access) headers.Authorization = `Bearer ${access}`;

      // react-native-sse — POST + body + Authorization 지원(architecture R2 mitigation).
      // 제네릭 type union — 백엔드 6 이벤트 타입 + 빌트인 'error'.
      type AnalysisCustomEvents =
        | 'progress'
        | 'token'
        | 'citation'
        | 'clarify'
        | 'done';
      const es = new EventSource<AnalysisCustomEvents>(url, {
        method: 'POST',
        headers,
        body,
      });

      // 한 번 더 가드 — EventSource 생성 직후 즉시 close되었는지 체크.
      if (terminalReachedRef.current) {
        try {
          es.close();
        } catch {
          // ignore
        }
        return;
      }

      eventSourceRef.current = es as unknown as EventSource;
      _resetInactivityTimer();

      es.addEventListener('progress', (event: { data?: string | null }) => {
        // progress는 phase 신호용 — text/result 변경 X. UI는 phase=='streaming'으로 전환.
        _resetInactivityTimer();
        try {
          if (event.data) JSON.parse(event.data);
        } catch {
          // ignore parse errors — best-effort phase 신호.
        }
        setState((prev) =>
          prev.phase === 'connecting' ? { ...prev, phase: 'streaming' } : prev,
        );
      });

      es.addEventListener('token', (event: { data?: string | null }) => {
        _resetInactivityTimer();
        if (!event.data) return;
        try {
          const parsed = JSON.parse(event.data) as { delta?: string };
          if (typeof parsed.delta === 'string') {
            setState((prev) => ({ ...prev, text: prev.text + (parsed.delta ?? '') }));
          }
        } catch {
          // skip malformed token — UX cosmetic 영향만.
        }
      });

      es.addEventListener('citation', (event: { data?: string | null }) => {
        _resetInactivityTimer();
        if (!event.data) return;
        try {
          const parsed = JSON.parse(event.data) as CitationItem;
          setState((prev) => ({ ...prev, citations: [...prev.citations, parsed] }));
        } catch {
          // skip malformed citation.
        }
      });

      es.addEventListener('clarify', (event: { data?: string | null }) => {
        if (!event.data) {
          _markTerminal({ phase: 'clarify', clarificationOptions: [] });
          return;
        }
        try {
          const parsed = JSON.parse(event.data) as { options?: ClarificationOption[] };
          _markTerminal({
            phase: 'clarify',
            clarificationOptions: parsed.options ?? [],
          });
        } catch {
          _markTerminal({ phase: 'clarify', clarificationOptions: [] });
        }
      });

      es.addEventListener('done', (event: { data?: string | null }) => {
        if (!event.data) {
          _markTerminal({ phase: 'error', error: { title: 'Empty done', status: 500, code: 'analysis.unexpected' } });
          return;
        }
        try {
          const parsed = JSON.parse(event.data) as AnalysisDoneResult;
          _markTerminal({ phase: 'done', result: parsed });
        } catch {
          _markTerminal({
            phase: 'error',
            error: { title: 'Malformed done', status: 500, code: 'analysis.unexpected' },
          });
        }
      });

      es.addEventListener('error', (event: { data?: string | null; type?: string }) => {
        // server-emitted ``event: error`` (RFC 7807 problem) vs connection error 분기.
        // server-emitted는 data 본문 보유, connection error는 data 없음(react-native-sse 패턴).
        if (event.data) {
          try {
            const problem = JSON.parse(event.data) as AnalysisProblem;
            _markTerminal({ phase: 'error', error: problem });
            return;
          } catch {
            // fall through to connection-error 분기.
          }
        }
        // connection error — terminal 미도달 시 polling 강등.
        if (!terminalReachedRef.current) {
          _scheduleFallback();
        }
      });
    },
    [mealId, _markTerminal, _scheduleFallback, _resetInactivityTimer],
  );

  // 마운트 시 SSE 진입(meal_id 변경 시 재진입).
  useEffect(() => {
    terminalReachedRef.current = false;
    polling5xxStreakRef.current = 0;
    setState(_initialState);
    void _openEventSource(null);
    return () => {
      terminalReachedRef.current = true;
      _closeEventSource();
      _stopPolling();
      _stopFallbackTimer();
      _stopInactivityTimer();
      _abortPoll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- _openEventSource는 mealId만 의존.
  }, [mealId]);

  const reset = useCallback(() => {
    terminalReachedRef.current = false;
    _closeEventSource();
    _stopPolling();
    _stopFallbackTimer();
    _stopInactivityTimer();
    _abortPoll();
    pollingAttemptsRef.current = 0;
    polling5xxStreakRef.current = 0;
    setState(_initialState);
    void _openEventSource(null);
  }, [
    _closeEventSource,
    _stopPolling,
    _stopFallbackTimer,
    _stopInactivityTimer,
    _abortPoll,
    _openEventSource,
  ]);

  const submitClarification = useCallback(
    async (value: string) => {
      // 새 SSE 흐름 — 이전 자원 정리 + state reset.
      terminalReachedRef.current = false;
      _closeEventSource();
      _stopPolling();
      _stopFallbackTimer();
      _stopInactivityTimer();
      _abortPoll();
      pollingAttemptsRef.current = 0;
      polling5xxStreakRef.current = 0;
      setState({
        ..._initialState(),
        phase: 'streaming',
      });
      await _openEventSource(value);
    },
    [
      _closeEventSource,
      _stopPolling,
      _stopFallbackTimer,
      _stopInactivityTimer,
      _abortPoll,
      _openEventSource,
    ],
  );

  return { state, reset, submitClarification };
}
