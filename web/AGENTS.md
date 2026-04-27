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
- **UI**: Tailwind v4 starter 디폴트. shadcn/ui는 선택적 도입 (Story 4.3 시점에 결정)
- **차트**: recharts — Story 4.3에서 도입 (현재 미설치)
- **API 클라이언트**: `src/lib/api-client.ts` 자동 생성 — `pnpm gen:api`로 OpenAPI 동기화
- **폼**: 필요 시 `react-hook-form` + `zod` 도입 (현재 미설치)

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
