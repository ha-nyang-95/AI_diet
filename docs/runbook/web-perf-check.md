# Web 주간 리포트 NFR-P8 perf 측정 SOP — Story 4.3

NFR-P8: *Web 주간 리포트 7일 데이터 ≤ 1.5초* (prd.md L1037).

## 측정 대상

`/dashboard/weekly` 페이지 SSR fetch + recharts hydration까지의 총 LCP.

## SOP — Lighthouse Mobile

### 1) 로컬 dev 환경

```bash
# Terminal 1 — 백엔드
cd api && uv run uvicorn app.main:app --reload

# Terminal 2 — Web dev
cd web && pnpm dev
```

### 2) Lighthouse 실행

Chrome DevTools → Lighthouse 탭 → *Mode: Navigation*, *Device: Mobile*,
*Categories: Performance* → "Analyze page load".

또는 CLI:

```bash
pnpm dlx @lhci/cli@0.13.x autorun \
  --collect.url=http://localhost:3000/dashboard/weekly \
  --collect.numberOfRuns=3
```

### 3) 통과 기준

| 지표 | 목표 | 사유 |
|---|---|---|
| **Performance score** | ≥ 80 | NFR-P8 baseline |
| **LCP** (Largest Contentful Paint) | ≤ 2.0s | Lighthouse mobile baseline |
| **FCP** (First Contentful Paint) | ≤ 1.5s | NFR-P8 직접 매핑 |
| **TBT** (Total Blocking Time) | ≤ 300ms | recharts hydration 한도 |
| **CLS** (Cumulative Layout Shift) | ≤ 0.1 | 차트 영역 placeholder 정합 |

### 4) Cloudflare/Vercel 배포 환경 차이

- **로컬 dev**: HMR + dev mode JS는 production 대비 ~3× 무거움 → LCP 측정 부정확.
  `pnpm build && pnpm start`로 production build 후 측정 권장.
- **Cloudflare CDN**: 정적 리소스는 edge 캐시 → 첫 진입 후 LCP 0.5-1.0s 단축.
- **Vercel Edge runtime**: SSR fetch latency가 Railway origin RTT(~50-100ms)에 의존.

### 5) 회귀 검출

CR/QA 단계에서 본 SOP 1회 실행 + 결과를 PR comment에 기록. baseline 대비 *50% 이상*
score 하락 또는 LCP 0.5s 이상 증가 시 회귀 후보(차트 dynamic import / recharts tree-shaking
검토). bundle analyzer 도입은 Story 8.4 polish.

## 검증 명령 요약

```bash
# Production build 측정 (정확)
cd web && pnpm build && pnpm start &
sleep 5
chrome --headless --no-sandbox --disable-gpu \
  --enable-features=NetworkService \
  --print-to-pdf=lh.pdf \
  http://localhost:3000/dashboard/weekly
```

## 회귀 회피 가드

- **백엔드 query**: 단일 SQL LEFT JOIN 1회 (N+1 회피 SOT — Story 3.7 패턴 정합).
- **bundle size**: recharts ~95KB gzip 추가. 추가 차트 라이브러리 도입 시 본 가드 검토.
- **TanStack Query staleTime**: 60s default — 주간 리포트 staleness 적정.
- **차트 lazy load**: 본 스토리는 4 차트 동시 hydration 허용. 차트별 lazy(intersection
  observer)는 Story 8.4 polish forward.
