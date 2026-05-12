# Incident Response Runbook

> 운영자(hwan) + 외주 client 인수인계용 — 외부 API 장애 / DB 다운 / LLM 비용 폭증 /
> 보안 침해 4 시나리오 대응 SOP. 본 runbook은 *3종 runbook(deployment / secret-rotation
> / incident-response) 중 마지막* (Story 8.5).
>
> **SOT 작성일**: 2026-05-12 (Story 8.5)
> **공통 1차 대응**: Sentry alert 수신 → 본 runbook 시나리오 매칭 → 단계별 진입.

---

## 0. 공통 1차 대응 체크리스트

신규 incident 발생 시(Sentry alert / Discord cost alert / 사용자 신고 등):

- [ ] **유형 분류** — §1 외부 API / §2 DB / §3 LLM 비용 / §4 보안 중 어느 시나리오인가?
- [ ] **영향 범위 측정** — 모든 사용자? 일부? 본인만? (Sentry `users affected`, `events/min`).
- [ ] **현 시점 mitigation 적용 여부 결정** (1차 대응 → 2차 안정화 → 3차 사후 검토 순).
- [ ] **사용자 영향 시 안내** (영업 데모 시점 발생 시 사전 안내 메시지 — §1.5 참조).

---

## 1. 외부 API 장애 (OpenAI / Anthropic / Google OAuth / Supabase / Render)

### 증상

- Sentry → `LLMRouterUnavailableError` / `MealOCRUnavailableError` / `InvalidIdTokenError` 폭증.
- `/healthz` 200이지만 분석 / OCR / 로그인이 사용자 측에서 timeout / 503.
- Render dashboard → `bn-api` Logs에 `httpx.ConnectError` / `openai.APIError` 다발.

### 상태 페이지

| 외부 의존성 | 상태 페이지 | 평균 회복 시간 |
|----------|----------|-------------|
| OpenAI | https://status.openai.com | 30분~2시간 |
| Google OAuth | https://www.google.com/appsstatus/dashboard/ | 30분~수시간 |
| Supabase | https://status.supabase.com | 1~6시간 |
| Render | https://status.render.com | 30분~3시간 |

> Story 8.5 갱신: Anthropic 의존성 제거로 OpenAI 단독 운영. OpenAI 장애 시 fallback LLM 없음
> → 분석 흐름 503(`LLMRouterExhaustedError`) + safe fallback 텍스트로 graceful 응답.

### 1.1. 1차 대응

1. 위 상태 페이지에서 *진행 중 incident* 여부 확인 → 외부 서비스 측 장애 확정 시 §1.2.
2. 외부 측 *정상*이라면 우리 측 설정 회귀(시크릿 만료 / DNS 갱신 / 코드 회귀) 가능성 → §1.3.
3. Discord에 *#operations* 채널 1차 알림: "외부 API 장애 — {OpenAI/Anthropic/...} 진행 중, 데모
   영향 가능. {expected_recovery_time}." (영업 시점 보호).

### 1.2. 2차 안정화 (graceful fallback 활성)

- **OpenAI 장애** (Story 8.5 갱신 — Anthropic fallback 제거) — LLM router는 tenacity 3회
  retry 후 `LLMRouterExhaustedError` 503 raise. `generate_feedback` 노드가 safe fallback
  텍스트("AI 서비스 일시 장애가 발생해 식사 분석을 마치지 못했습니다") 반환 → 사용자에게는
  graceful 응답. OCR Vision도 동일 OpenAI라 사진 분석 503 → 모바일에 "텍스트로 다시 입력해
  주세요" 안내.
  - 단순 식단 입력 + 매크로 합산 + 가이드라인 RAG 검색은 LLM 없이 정상 동작.
  - 데모 시점이면 §1.5 사전 안내 SOP 진입.
- **Google OAuth 장애** — 신규 가입/재로그인 차단. 기존 활성 세션(JWT)은 정상 → 활성 사용자
  영향 0. 사용자에게 안내 "로그인 일시 장애 — 잠시 후 재시도".
- **Supabase 장애** — DB 측 503. §2 시나리오로 진입.
- **Render 장애** — `.onrender.com` 자체 unreachable. 데모 시점이면 발표 일정 조정 또는 빠른
  복구 대기(Render Free는 SLA 없음 — 평균 30분~3시간 복구).

### 1.3. 우리 측 회귀 (외부는 정상인데 우리만 fail)

- 시크릿 만료 → `docs/runbook/secret-rotation.md` 해당 § 진입.
- 코드 회귀 → Render dashboard → `bn-api` → `Deploys` → 이전 정상 commit으로 `Rollback to this deploy`.
- DNS 회귀(도메인 추가한 경우 — 현 시점 `.onrender.com` 사용이라 N/A) → DNS provider dashboard.

### 1.4. 3차 사후 검토

- Sentry → 해당 incident 시간 윈도우의 event 분포 분석.
- `_bmad-output/implementation-artifacts/incidents/{YYYY-MM-DD}-{유형}.md` 작성(옵션) — 다음 분기
  retrospective 입력.
- 외부 측 *post-mortem*이 발행되면 본 runbook §1 표에 cross-link.

### 1.5. 영업 데모 시점 발생 시 사전 안내 SOP

데모 직전(1시간 전) 1회 검증:

- [ ] 5 상태 페이지 confirmed `Operational`.
- [ ] `https://bn-api.onrender.com/healthz` 200 (cold start 워밍업).
- [ ] `https://bn-web.onrender.com/login` 정상 렌더 + Google 로그인 흐름 dry-run 1회.
- [ ] 식단 1건 입력 + 분석 + 사진 OCR 1건 dry-run 통과.

상기 미통과 시 데모 일정 조정 또는 데모 발표 자료에 *"라이브 데모 일부는 사전 녹화"* 안내 추가.

---

## 2. DB 다운 (Supabase Postgres)

### 증상

- `/healthz` 503 + Sentry `OperationalError` / `asyncpg.exceptions.PostgresConnectionError` 폭증.
- 모든 API endpoint(분석 / 식단 / 인증)가 503 또는 timeout.
- Supabase Dashboard → 본 project → `Database` → 상태 표시.

### 2.1. 원인 분기 + 1차 대응

#### (a) Supabase Free **inactivity pause** (7일 무활동)

1. Supabase Dashboard → 해당 project → **Restore project** 버튼 → **1분 내 복구**.
2. `/healthz` 200 확인. asyncpg connection pool 자동 회복 (pool_pre_ping=True).

#### (b) Supabase 측 incident (status page에 표시)

1. https://status.supabase.com 진행 중 incident 확인 → 외부 incident 확정.
2. *대기* — Supabase는 평균 1~6시간 회복.
3. 영업 데모 시점이면 §1.5 SOP 진입.

#### (c) Free 500MB **quota 초과**

1. Supabase Dashboard → `Database` → `Reports` → DB size 확인.
2. 임시 read-only 모드 — Supabase가 quota 초과 시 *자동 read-only 강등* (운영자 별 작업 없음).
3. quota 정리 옵션:
   - **soft-deleted user purge** — Story 5.2 `soft_delete_purge.py` worker 수동 실행으로 30일 grace 만료 사용자 row hard-delete.
   - **분석 history 정리** — DB 측 retention policy 적용(현 시점 없음 — Story 8.4 forward).
   - **plan 업그레이드** — Supabase Free → Pro($25/월) — 8GB DB.
4. 정리 후 자동 read-only 해제(Supabase 측 자동 감지).

#### (d) Connection pool 고갈 (Render Free outbound 제한)

1. Render dashboard → `bn-api` → Logs → `connection pool exhausted` / `too many clients` 패턴.
2. Render dashboard → `bn-api` → **Manual Deploy** → 재배포 (pool 리셋).
3. 재발 시 SQLAlchemy `pool_size` / `max_overflow` 조정 검토(현 디폴트는 SQLAlchemy 자동).

### 2.2. rollback (destructive migration 회귀 시)

직전 PR 머지로 alembic destructive migration이 prod에 적용된 후 회귀 발생:

1. Render dashboard → `bn-api` → `Shell` (Free tier 미제공 → Paid tier 필요. Free에서는 GitHub
   Actions one-shot workflow로 대체).
2. `alembic downgrade -1` 수동 실행 → 1 step 이전 schema로 회귀.
3. 코드도 동일 시점으로 rollback (Render `Deploys` 탭).
4. *주의*: destructive migration(DROP COLUMN 등)은 *데이터 복구 불가* — Supabase Dashboard →
   `Database` → `Backups`에서 사전 백업 필수.

### 2.3. 3차 사후 검토

- DB 복구 후 데이터 무결성 확인(alembic version + 주요 row count).
- pause 발생 빈도 → 매주 GitHub Actions cron으로 `SELECT 1` 1회 ping 추가 검토(Story 8.5 OUT,
  forward).
- quota 초과 빈도 → Pro plan 업그레이드 검토.

---

## 3. LLM 비용 폭증 (daily-cost-alert 임계치 초과)

### 증상

- Discord webhook → daily-cost-alert에서 **warning** 또는 **critical** 알림 수신.
- GitHub Issue 자동 생성됨 (`🚨 Daily cost threshold exceeded`).
- Sentry → `vision_daily_cost_cap_reached` 또는 LLM router 비정상 호출 빈도 증가.

### 3.1. 1차 대응 (endpoint 식별)

1. Discord 알림 본문에서 OpenAI/Anthropic 분리 cost 확인 → 어느 provider가 폭증인가?
2. LangSmith Dashboard → `balancenote-prod` project → 어제(KST) trace 분포:
   * 호출 수 폭증한 endpoint(`/v1/analysis/stream` vs `/v1/meals/images/parse` 등) 식별.
   * 같은 사용자가 반복 호출? IP 분포가 좁은가? → §3.4 악성 사용자 분기.
3. Sentry → `breadcrumb.llm_router.*` 빈도 분포 → 모델별 호출 수 확인.

### 3.2. 2차 안정화 — cost cap 강화

Render dashboard → `bn-api` → `Environment` → 다음 env var 추가/조정 후 자동 재배포:

- `VISION_DAILY_COST_CAP_USD` (default 5.0) → **2.0**로 강화 → `parse_meal_image`이 cap 도달 시
  gpt-4o-mini 다운그레이드.
- `VISION_FALLBACK_COST_CAP_USD` (default 1.0) → 그대로 또는 더 강화.
- `LLM_ROUTER_TOTAL_BUDGET_SECONDS` (default 25) → 그대로(timeout 단축은 UX 영향).
- `RATE_LIMIT_LANGGRAPH` (in code) → slowapi 분석 endpoint per-IP 10/min → 5/min 임시 강화는
  코드 변경 필요 (Story 8.4 forward — 본 시점은 env 기반 cap만).

### 3.3. 2차 안정화 — LLM provider key 일시 회전 (극단)

악성 사용자가 leaked client에서 직접 LLM 호출하는 시나리오라면 다음 단계:

1. `secret-rotation.md` §1 (OpenAI) + §2 (Anthropic) 즉시 회전 — leak된 key 무효화.
2. 회전 중 LLM 분기 일시 503 → 사용자 영향 ~10분.

### 3.4. 악성 사용자 차단 (특정 user_id 식별 시)

1. Sentry / LangSmith에서 단일 user_id의 분석 호출 빈도 비정상 확인.
2. DB에서 해당 user를 deactivate (admin endpoint 또는 SQL):
   ```sql
   UPDATE users SET deleted_at = NOW() WHERE id = '...';
   ```
3. Story 5.2 soft-delete 정합 — 30일 grace 후 hard-delete. 즉시 차단이 필요하면 `deleted_at`
   설정 + JWT_SECRET_KEY 회전(전체 사용자 강제 logout — §4.3 참조).
4. IP rate limit — Render Free에는 WAF 없음 → Render 측 차단 불가. Cloudflare 재도입 또는
   `proxy.py` 측 inline block list 추가(Story 8.4 forward).

### 3.5. 3차 사후 검토

- 폭증 원인 분류 — 정상 사용 증가 / 악성 / 코드 회귀 / 모델 변경?
- 결과를 GitHub Issue 본문에 update + label 추가(`cost-spike:user`/`cost-spike:malicious` 등).
- 정기 cap 재조정 — 정상 사용 증가라면 `THRESHOLD_USD` env 상향.

---

## 4. 보안 침해 (시크릿 leak / DB 접근 의심)

### 증상

- 시크릿 leak 증거:
  - GitHub public commit에 `sk-...` / `whsec_*` / `OPENAI_API_KEY=...` 포함.
  - Discord/Slack에 raw key 노출 스크린샷.
  - Sentry breadcrumb / LangSmith trace에 raw secret 표시 (NFR-S5 마스킹 회귀 신호).
- DB 접근 의심 증거:
  - audit_logs (Story 7.3)에 비정상 admin 행위 빈도 → 외부 actor가 admin JWT 탈취 가능성.
  - Supabase Dashboard → `Database` → `Logs`에 비정상 IP 접속.

### 4.1. 1차 즉시 대응 (60분 내)

- [ ] **leaked secret 회전 즉시** — `secret-rotation.md` 해당 § (1/2/5/6/7/8) 진입.
- [ ] JWT 측 의심이면 **JWT_SECRET_KEY 회전** — Render env vars `JWT_SECRET_KEY` 신규 발급
  (`python -c "import secrets; print(secrets.token_urlsafe(32))"`) → 자동 재배포.
  - **전체 사용자 강제 logout** — 기존 JWT는 신규 secret으로 검증 실패 → 401 → 로그인 페이지 redirect.
- [ ] **leaked GitHub commit 발견** → `git push --force-with-lease`로 commit 제거 +
  `gh secret set GITHUB_TOKEN` 회전. GitHub Support 이메일(`support@github.com`)에 cache invalidation 요청.
- [ ] Sentry / LangSmith 보드의 raw secret 노출 → NFR-S5 마스킹 회귀 — 즉시 `app/core/sentry.py`
  `_MASKED_KEYS` 또는 `observability.py` `_LANGSMITH_MASKED_KEYS` 추가 후 hotfix 배포.

### 4.2. 2차 안정화 — audit log 검토

1. Story 7.3 audit_logs 테이블 (`audit_logs.action_type` / `audit_logs.actor_id` / `audit_logs.target_user_id`)
   에서 침해 시점 ±1시간 review:
   ```sql
   SELECT * FROM audit_logs
   WHERE created_at BETWEEN '<incident_start>' AND '<incident_end>'
   ORDER BY created_at DESC;
   ```
2. 비정상 admin 행위(`admin.user.delete` / `admin.user.patch_profile` 등) 빈도 분석.
3. 침해된 admin 계정 identified → 해당 admin role revoke + 비밀번호 강제 회전.

### 4.3. 3차 — PIPA 신고 의무 (72h 이내)

**PIPA 2026.03.15 개정 — 개인정보 침해 발생 시 72시간 이내 정보보호위원회 신고 의무**.

- 침해 대상 사용자 수 + 노출 정보 항목 분류:
  - **민감정보** (건강 프로필 — weight_kg / height_cm / allergies): *반드시 신고*.
  - **식별정보** (email / google_sub / display_name): *반드시 신고*.
  - **분석 결과** (식단 / parsed_items / feedback): PIPA 정의 *민감정보 추론 가능* → 신고 권장.
- 신고 채널: https://www.privacy.go.kr → 신고/상담 → 개인정보 침해 신고.
- 신고 양식 항목: 침해 일시 / 침해 원인 / 영향 사용자 수 / 노출 항목 / 우리 측 대응(secret 회전,
  사용자 강제 logout 등).
- *모든 영향 사용자에게 개별 통지 의무* — 등록된 email로 한국어 알림 발송(이메일 service는 운영
  forward — 현 시점은 운영자 수동 발송).

### 4.4. 사후 — 코드/SOP 보강

- leaked secret 회전 후 *왜 leak되었는가* 원인 분석:
  - GitHub Actions 실수 — workflow에 `echo $SECRET` 출력 회피 SOP 추가.
  - Sentry/LangSmith 회귀 — `_MASKED_KEYS` 보강 + 단위 테스트 추가.
  - 운영자 실수 — Discord/Slack에 paste 시 1Password copy-mask 권장.
- audit_logs 정합성 검증 — Story 7.3 cascade chain이 의도대로 동작했는지 (admin → target user dependency).
- 본 incident를 `_bmad-output/implementation-artifacts/incidents/{YYYY-MM-DD}-security.md`에 기록.

---

## 5. 비상 연락처 / 회복 자료

### 5.1. 외부 서비스 support

| 서비스 | support 채널 | 회복 자료 |
|-------|------------|----------|
| OpenAI | https://help.openai.com / support@openai.com | https://platform.openai.com/docs |
| Google OAuth | https://cloud.google.com/support | https://developers.google.com/identity/protocols/oauth2 |
| Supabase | https://supabase.com/support | https://supabase.com/docs |
| Render | https://render.com/help | https://render.com/docs |
| Toss Payments | https://docs.tosspayments.com → 문의하기 | https://docs.tosspayments.com |
| Sentry | https://sentry.io/support/ | https://docs.sentry.io |
| LangSmith | https://docs.smith.langchain.com → Community | https://docs.smith.langchain.com |

### 5.2. 운영자 / 클라이언트 연락처

- **운영자 (hwan)**: `<운영자 연락처 placeholder — 외주 인수 시 클라이언트가 채움>`
- **개인정보보호위원회** (PIPA 신고): https://www.privacy.go.kr / 국번없이 182
- **KISA 사이버 침해 신고센터**: https://www.boho.or.kr / 국번없이 118
- **GitHub Support** (commit secret 제거 요청): https://support.github.com → "Remove sensitive
  data" 카테고리

### 5.3. 인수 시점 갱신 checklist (외주 인수자가 작성)

- [ ] 본인 연락처 placeholder 갱신.
- [ ] 본인 GitHub username + Render dashboard 권한 추가.
- [ ] Supabase project owner 권한 이전.
- [ ] 회전 캘린더 (`secret-rotation.md` §9) 본인 명의로 인계.
