# Mobile AGENTS.md — BalanceNote Mobile

## 컨텍스트 (루트 AGENTS.md 동일)

- 프로젝트: BalanceNote — AI 영양 분석 + 인용 피드백 (모바일 우선)
- Repo: 단일 repo + multi-folder, 워크스페이스 X
- BMad 산출물: `_bmad-output/`

## Mobile 특화

- **라우팅**: Expo Router (file-based) — `app/` 폴더가 라우트 트리
- **상태 관리**: TanStack Query (server) + useState/useReducer (client). Redux/Jotai/Recoil 금지
- **권한 흐름**: 표준 컴포넌트 위치 — `mobile/lib/permissions.ts` (헬퍼) + `features/onboarding/PermissionDeniedView.tsx` (재사용 UI). Story 2.2(카메라/사진 권한)에서 도입
- **폼**: 필요 시 `react-hook-form` + `zod` (Story 1.5에서 도입)
- **API 클라이언트**: `mobile/lib/api-client.ts` 자동 생성 — `pnpm gen:api` 호출

## 명령

```bash
pnpm install
pnpm start            # Expo dev menu
pnpm tsc --noEmit     # 타입체크 (CI 게이트)
pnpm gen:api          # OpenAPI 동기화
```

## Lock 파일

`pnpm-lock.yaml`만 사용. `package-lock.json`이 생성되면 즉시 삭제 (TS 측 패키지 매니저 통일).
