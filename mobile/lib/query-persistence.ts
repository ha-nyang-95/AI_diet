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
 * Schema migration: ``buster: 'v1'`` (Story 2.4 schema 안정). Story 3.x에서
 * ``analysis_summary`` 실제 wire 시 ``'v2'``로 bump → persist 캐시 자동 invalidate.
 * (deferred-work DF21 — buster bump SOP를 README + 코드 리뷰 게이트에 명시.)
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
