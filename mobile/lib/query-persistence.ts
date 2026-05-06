/**
 * Story 2.4 — TanStack Query AsyncStorage persister 설정 (NFR-R4).
 *
 * 7일 로컬 캐시(NFR-R4: *"DB 다운 시 모바일 로컬 캐시(7일치)에서 읽기 전용 표시"*)를
 * 위해 ``@tanstack/query-async-storage-persister`` + ``@tanstack/react-query-persist-client``
 * wire. ``meals`` queryKey만 persist (보안: 토큰/프로필 캐시 persist X — 디바이스
 * 분실 시 stale 데이터 leak 차단).
 *
 * 호출 측은 ``PersistQueryClientProvider``를 ``_layout.tsx``에서 사용. 본 모듈은
 * persister + persistOptions을 export 하기만 함.
 *
 * --- Story 3.9 AC19 — buster bump SOP (DF21 정착) ---
 *
 * **persist schema(MealResponse / AnalysisSummary 등) 변경 시 ``buster`` bump 의무.**
 *
 * 변경 트리거 매트릭스:
 * - ``MealResponse`` 필드 추가/제거/타입 변경.
 * - ``MealAnalysisSummary`` 필드 추가/제거/타입 변경 (Story 3.x analysis_summary wire 등).
 * - ``MealMacros`` 필드 추가/제거/타입 변경 (Story 3.9 AC17 ``le=10000`` 같은 가드 추가).
 * - ``parsed_items`` jsonb shape 변경.
 *
 * **bump 절차**: ``buster: 'v1'`` → ``'v2'`` → ``'v3'`` 순차 증가. 코드 리뷰 게이트:
 * 위 트리거 PR 시 본 파일 diff에 buster 갱신 누락 확인 → 갱신 안 됐으면 reject.
 *
 * **Story 2.4 baseline**: ``v1``. Story 3.x에서 analysis_summary 실제 wire 시 v2 bump
 * 예정(현 시점은 forward-compat 슬롯이라 wire X — Story 3.7 SSE done payload가 별도
 * 영속화 경로). 운영 부팅 시 stale 캐시 형식 mismatch 회귀 차단.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import type { PersistQueryClientProviderProps } from '@tanstack/react-query-persist-client';

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

export const queryPersister = createAsyncStoragePersister({
  storage: AsyncStorage,
  key: 'bn-rq-cache',
  // 1초 단위 disk write 묶음 — I/O 부담 ↓.
  throttleTime: 1000,
});

export const persistOptions: PersistQueryClientProviderProps['persistOptions'] = {
  persister: queryPersister,
  // NFR-R4 — 마지막 7일 표시 정합.
  maxAge: SEVEN_DAYS_MS,
  // Story 2.4 baseline schema 식별자. analysis_summary 실제 wire 시 'v2' bump.
  buster: 'v1',
  dehydrateOptions: {
    // 보안: ``meals`` queryKey만 persist. auth/profile 캐시는 토큰 만료 후 stale
    // 데이터 노출 차단을 위해 persist X.
    shouldDehydrateQuery: (query) => query.queryKey[0] === 'meals',
  },
};
