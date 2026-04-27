# AGENTS.md — AI_diet (BalanceNote) 외주 인수 컨텍스트

## 1줄 요약

**BalanceNote**: 한국 사용자의 식단 → AI 영양 분석(Self-RAG) → 인용 기반 피드백 → 주간 리포트.
모바일(Expo) + Web 리포트(Next.js) + FastAPI 백엔드 + LangGraph 에이전트.

## Repo 구조 결정 — 단일 repo + multi-folder, 워크스페이스 X

이 repo는 pnpm workspace / Turborepo / Nx **를 쓰지 않는다**.
사유: Python(api) ↔ TypeScript(mobile/web) 워크스페이스 통합이 불가능 — 반쪽짜리 monorepo는 안티패턴.

대신:

- 컴포넌트 경계 = 폴더 = Docker 컨테이너 (compose 1-cmd와 정합)
- TS 타입 공유는 OpenAPI 단일 출처 → `openapi-typescript` 자동 생성

## 폴더 = 컨테이너 매핑

| 폴더 | 역할 | 컨테이너 |
|------|------|---------|
| `api/` | FastAPI + LangGraph + Alembic | `api` |
| `web/` | Next.js 16 (App Router) — 주간 리포트·관리자 | (Vercel 배포; dev 시 로컬 pnpm dev) |
| `mobile/` | Expo SDK 54 — 식단 입력·피드백 | (EAS 배포; dev 시 Expo dev menu) |
| `docker/` | Dockerfile.api + postgres-init | — |
| `scripts/` | bootstrap_seed.py, gen_openapi_clients.sh | — |
| `_bmad-output/` | PRD, architecture, epics, stories (트래킹) | — |
| `docs/` | SOP, FAQ, runbook (Epic 8) | — |

## 핵심 단일 명령

```bash
docker compose up        # postgres + redis + api + seed 일괄 부팅
pnpm gen:api             # OpenAPI → web/src/lib/api-client.ts + mobile/lib/api-client.ts
```

OpenAPI 스키마가 변경되면 **반드시** `pnpm gen:api`를 실행하고 변경분을 커밋한다.
CI `openapi-diff` 잡이 git diff를 검증해 머지를 차단한다.

## BMad 산출물 위치

- PRD: `_bmad-output/planning-artifacts/prd.md`
- Architecture: `_bmad-output/planning-artifacts/architecture.md`
- Epics: `_bmad-output/planning-artifacts/epics.md`
- Stories: `_bmad-output/implementation-artifacts/{epic}-{story}-{slug}.md`
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`
