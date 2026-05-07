# Web AGENTS.md — BalanceNote Web

## 컨텍스트 (루트 AGENTS.md 동일)

- 프로젝트: BalanceNote — AI 영양 분석 + 인용 피드백 + 주간 리포트
- Repo: 단일 repo + multi-folder, 워크스페이스 X
- 컴포넌트 경계 = 폴더 = 컨테이너
- BMad 산출물: `_bmad-output/` (PRD, architecture, epics, stories)

## Web 특화

- **역할**: 주간 리포트 + 관리자 페이지 (모바일은 `mobile/`)
- **상태 관리**: TanStack Query (server) + useState/useReducer (client)
- **Auth**: 백엔드 JWT를 httpOnly 쿠키로 직접 교환 — `next-auth` 사용 금지
- **UI**: Tailwind v4 starter 디폴트. shadcn/ui 미도입 — Story 4.3 시점 결정(raw Tailwind + recharts 충분, bundle size 최소화)
- **차트**: recharts — Story 4.3 도입 완료 (`src/features/reports/`). 신규 차트 추가 시 동일 패턴 강제 — `<details><summary>데이터 표 보기</summary><table>` 접힘 fallback + `aria-label` (NFR-A5 키보드 + 스크린리더 정합), `useSyncExternalStore`로 SSR-mounted gating(ResponsiveContainer SSR-Hydration mismatch 회피).
- **API 클라이언트**: `src/lib/api-client.ts` 자동 생성 — `pnpm gen:api`로 OpenAPI 동기화
- **폼**: `react-hook-form` + `zod` 도입 완료 (Story 4.4 매크로 목표 폼이 첫 사용처). 이후 신규 web 폼은 동일 패턴 강제 — `zodResolver` + Korean inline error + ratio/sum 같은 cross-field 검증은 `.refine()` SOT.

## 명령

```bash
pnpm install
pnpm dev          # http://localhost:3000
pnpm tsc --noEmit # 타입체크 (CI 게이트)
pnpm gen:api      # OpenAPI → src/lib/api-client.ts
```

## ⚠️ Next.js 16 주의

이 프로젝트는 Next.js 16 — App Router + Turbopack 디폴트 + React 19. App Router only.
Pages Router 사용 금지. server actions / metadata API 등 신규 패턴 우선.
