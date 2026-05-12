# Secret 회전 SOP

> 운영자(hwan) + 외주 client 인수인계용 — 외부 SDK API key·secret을 분기 1회
> 회전하는 절차 SOT. 본 runbook은 회전 자체를 자동화하지 않으며 수동 절차를
> 명시한다(Story 8.5 자동화 polish는 별도).

## 0. 회전 대상 secret 일람

| 카테고리 | secret 이름 | 발급처 | 회전 주기 | 본 문서 단락 |
|---------|------------|-------|----------|------------|
| LLM | `OPENAI_API_KEY` | OpenAI Platform | 분기 1회 | §1 |
| LLM | `ANTHROPIC_API_KEY` | Anthropic Console | 분기 1회 | §2 |
| 옵저버빌리티 | `LANGSMITH_API_KEY` | LangSmith UI | 분기 1회 | §3 (Story 3.8) |
| Push | `EXPO_ACCESS_TOKEN` | EAS Console | 6개월 | §4 (Story 4.2) |
| OAuth | `GOOGLE_OAUTH_CLIENT_SECRET` | Google Console | 6개월 | §5 (Story 8.5) |
| 결제 | `TOSS_SECRET_KEY` | Toss Payments | 12개월 (Sandbox 무회전) | §6 (Story 6.1) |
| 모니터링 | `SENTRY_DSN` | Sentry UI | 12개월 | §7 (Story 8.5) |
| 스토리지 | `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | Cloudflare Dashboard | 6개월 | §8 (Story 8.5) |

§1 ~ §4는 현 시점 SOT(Story 3.8 §1-§3 + Story 4.2 §4). §5 ~ §8은 placeholder — Story
8.5 운영 polish 단계에서 채움.

---

## 1. OpenAI API key 회전 (Story 8.5)

OpenAI Platform에서 발급된 API key. `OPENAI_API_KEY` env가 LLM router(`call_openai_feedback`)
+ Vision OCR(`parse_meal_image`) + GitHub Actions `daily-cost-alert.yml` 3곳에서 사용. 분기
1회 회전.

### 1.1. 신규 key 발급

1. [OpenAI Platform](https://platform.openai.com) 운영자 계정으로 로그인.
2. `Dashboard` → `API keys` → `+ Create new secret key`.
3. key 이름: `balancenote-prod-2026-Q3` 등 *환경+분기* 명명.
4. permissions: *All* (LLM + Vision + Usage API 모두 호출). usage 전용 read-only key는 별도
   발급(GitHub Actions secret용 — `daily-cost-alert.yml` 정합).
5. 발급된 `sk-...` key를 *임시 보안 노트*에 복사(페이지 이탈 시 재조회 불가).

### 1.2. Render env vars 갱신 + 24h overlap

1. Render dashboard → `bn-api` service → `Environment` → `OPENAI_API_KEY` → 신규 key 붙여넣기 → `Save Changes`.
2. **자동 재배포 1~2분 대기** — `https://bn-api.onrender.com/healthz` 200 OK 확인.
3. **24h overlap** — OpenAI는 새 key 발급 시 기존 key 즉시 무효화하지 *않음*. 기존 key는 *수동 revoke*
   시점까지 유효 → in-flight request가 기존 key로 처리되어도 안전. 24h grace 동안 두 key 모두 valid.

### 1.3. 도착 검증

1. 분석 1회 호출 (Render bn-web에서 식단 분석 또는 cURL `POST /v1/analysis/stream`).
2. Sentry `balancenote-api` → breadcrumb에 `llm_router.openai.completion` 정상 로그 확인.
3. LangSmith dashboard → 신규 trace 도착 + `openai-` model 호출 정상.
4. GitHub Actions → `daily-cost-alert.yml` 수동 trigger → OpenAI Usage API 호출 성공 확인.

### 1.4. 기존 key revoke

1. §1.3 검증 통과 + 24h overlap 후 OpenAI Platform → `API keys` → 기존 key → ⋯ → `Revoke`.
2. revoke 직후 첫 호출에 `openai.AuthenticationError` 발생하지 않음을 5분간 Sentry 모니터링.

### 1.5. rollback (장애 시)

신규 key 적용 후 `401 Unauthorized` 또는 `openai.AuthenticationError` 다발 시:

1. 기존 key가 *revoke 전*이라면 Render env vars에서 기존 key로 즉시 복구 → 자동 재배포.
2. 기존 key revoke 완료된 상태라면 OpenAI Platform에서 *재 발급* → §1.2-§1.3 재실행.
3. 회복 불가 시 `OPENAI_API_KEY=`(빈 값)으로 강등 — `LLMRouterUnavailableError(503)` 응답 +
   Anthropic 단일 LLM으로 graceful fallback 동작(NFR-I3 정합).

### 1.6. 변경 트리거

- 운영자 퇴사 / 권한 변경.
- key leak 의심 (Sentry capture에 raw key 노출 / GitHub commit / Discord leak 등).
- 3개월 정기 회전 (캘린더).
- OpenAI 측 정책 변경(GPT-5 권한 분리 등).

---

## 2. Anthropic API key 회전 (Story 8.5)

Anthropic Console에서 발급된 API key. `ANTHROPIC_API_KEY` env가 LLM router 보조 SDK
(`call_claude_feedback`) 1곳에서 사용. GitHub Actions `daily-cost-alert.yml`은 별도
`ANTHROPIC_ADMIN_API_KEY` 사용(usage 조회 admin scope). 분기 1회 회전.

### 2.1. 신규 key 발급

1. [Anthropic Console](https://console.anthropic.com) 운영자 계정으로 로그인.
2. `Settings` → `API Keys` → `+ Create Key`.
3. key 이름: `balancenote-prod-2026-Q3` 등 *환경+분기* 명명. workspace: 본 가맹점.
4. 발급된 `sk-ant-...` key를 *임시 보안 노트*에 복사.

### 2.2. Render env vars 갱신 + 24h overlap

1. Render dashboard → `bn-api` service → `Environment` → `ANTHROPIC_API_KEY` → 신규 key 붙여넣기 → `Save Changes`.
2. **자동 재배포 1~2분 대기** — `/healthz` 200 OK 확인.
3. **24h overlap** — Anthropic은 새 key 발급 시 기존 key 즉시 무효화하지 않음. revoke 시점까지 둘 다 valid.

### 2.3. 도착 검증

1. 분석 1회 호출 (Claude fallback 분기 발동 시나리오 — OpenAI quota 임시 차단 또는 Anthropic
   model 명시 호출).
2. Sentry breadcrumb에 `llm_router.anthropic.completion` 정상 로그 확인.
3. LangSmith dashboard → `claude-` model trace 도착 확인.

### 2.4. 기존 key revoke

1. §2.3 검증 통과 + 24h overlap 후 Anthropic Console → `API Keys` → 기존 key → `Disable`.
2. 5분간 Sentry 모니터링 — `anthropic.AuthenticationError` 0건 확인.

### 2.5. rollback (장애 시)

신규 key 적용 후 `401 Unauthorized` 다발 시:

1. 기존 key가 disable 전이라면 Render env vars 복구 → 자동 재배포.
2. disable 완료 시 Anthropic Console에서 재 발급 → §2.2-§2.3 재실행.
3. 회복 불가 시 `ANTHROPIC_API_KEY=`(빈 값)으로 강등 — Anthropic fallback 단락 + OpenAI
   primary 단독 가동(LLM router 양 손실은 `LLMRouterExhaustedError(503)`).

### 2.6. 변경 트리거

- 운영자 퇴사 / 권한 변경.
- key leak 의심.
- 3개월 정기 회전.
- Anthropic 측 정책 변경(Claude 4.x prompt caching 권한 분리 등).

---

## 3. LangSmith API key 회전 (Story 3.8 AC11)

LangSmith 트레이스 송신 + dataset 관리에 사용되는 API key. 분기 1회 회전.

### 3.1. 신규 key 발급

1. [LangSmith UI](https://smith.langchain.com) 운영자 계정으로 로그인.
2. `Settings` → `API Keys` → `+ Create API Key`.
3. key 이름: `balancenote-prod-2026-Q3` 등 *환경+분기* 명명.
4. 발급된 key를 *임시 보안 노트*에 복사(이후 페이지 이탈 시 재조회 불가).

### 3.2. Railway secrets 갱신

1. [Railway Dashboard](https://railway.app) → BalanceNote 프로젝트 → 환경 선택
   (staging 또는 prod).
2. `Variables` 탭 → `LANGSMITH_API_KEY` 항목 → 신규 key 붙여넣기 → `Update`.
3. 자동 재배포 트리거 — 1-2분 대기 후 `https://<service>.railway.app/healthz`
   200 OK 확인.

### 3.3. trace 도착 검증

1. `LANGCHAIN_TRACING_V2=true` + 신규 key 적용된 환경에서 분석 1회 호출
   (`POST /v1/analysis/stream` curl 또는 mobile/web에서 임의 식단 분석).
2. LangSmith 보드 → 해당 환경 프로젝트(`balancenote-staging` / `balancenote-prod`)
   → `Runs` 탭 → 직전 1분 내 신규 trace 도착 확인.
3. trace inputs/outputs에 `"***"` 마스킹이 정상 동작함을 시각 확인
   (NFR-O2 — `docs/observability/langsmith-dashboard.md` §3 정합).

### 3.4. 기존 key revoke

1. 신규 key 적용 + trace 도착 확인 후 *24h grace* 대기 — in-flight request /
   batched send queue가 기존 key로 송신 중일 수 있음.
2. 24h 후 LangSmith UI → `Settings` → `API Keys` → 기존 key → `Revoke`.

### 3.5. rollback 절차

신규 key 적용 후 trace 미도착 또는 `401 Unauthorized` startup 로그 발생 시:

1. LangSmith UI → 기존 key가 *아직 revoke되지 않았다면*(grace 기간 내) 즉시
   Railway secrets에서 기존 key로 복구.
2. 기존 key revoke 완료된 상태라면, 새 key를 *즉시 재발급*하고 §3.2-§3.3
   다시 실행.
3. 24h 안에 회복 불가 시 `LANGCHAIN_TRACING_V2=false`로 임시 강등 — 분석
   기능은 정상 동작 + LangSmith 송신만 차단(NFR-O5 graceful 정합).

### 3.6. 보드 가이드 cross-link

회전 후 운영자 + 외주 client에게 알릴 보드 URL:
[docs/observability/langsmith-dashboard.md](../observability/langsmith-dashboard.md).

---

## 4. EXPO_ACCESS_TOKEN 회전 (Story 4.2 AC10)

EAS Console에서 발급되는 access token으로 `app/adapters/expo_push.py`이 Expo Push API
호출 시 `Authorization: Bearer ...` 헤더에 사용. EAS Console *enhanced security mode*
활성 시 필수 — 6개월 1회 회전.

### 4.1. 신규 token 발급

1. [EAS Console](https://expo.dev/accounts/<account>/settings/access-tokens) 운영자 계정으로 로그인.
2. `Settings` → `Access Tokens` → `Generate Token`.
3. token 이름: `balancenote-prod-2026-Q4` 등 *환경+분기* 명명. scope는 *Push Notifications*.
4. 발급된 token을 *임시 보안 노트*에 복사(이후 페이지 이탈 시 재조회 불가).

### 4.2. Railway secrets 갱신 + 24h overlap

1. [Railway Dashboard](https://railway.app) → BalanceNote 프로젝트 → 환경 선택
   (staging 또는 prod).
2. `Variables` 탭 → `EXPO_ACCESS_TOKEN` 항목 → 신규 token 붙여넣기 → `Update`.
3. 자동 재배포 트리거 — 1-2분 대기 후 `https://<service>.railway.app/healthz`
   200 OK 확인.
4. **24h overlap 운영** — 구 token revoke 전에 in-flight cron sweep이 기존 token으로 send
   진행 중일 수 있음. cron은 30분 주기라 24h는 충분한 grace.

### 4.3. send 도착 검증

신규 token 적용 후 다음 cron sweep tick(최대 30분 대기) 또는 직접 호출(SOP §8.3):

```
[info] nudge.sweep.start
[info] nudge.sweep.eligible user_count=N
[info] nudge.sent user_id=u_... ticket_id=...
```

`ticket.status="ok"` 응답 확인 — `Authorization` 헤더가 신규 token으로 정상 통과.

### 4.4. 기존 token revoke

1. §4.3 검증 통과 + 24h overlap 후 EAS Console → `Access Tokens` → 기존 token → `Revoke`.
2. revoke 직후 cron 한 cycle 추가 모니터링 — `nudge.skipped reason=adapter_error:ExpoPushAuthError`
   발생 시 즉시 §4.5 rollback.

### 4.5. rollback 절차

신규 token 적용 후 `ExpoPushAuthError`(401) 발생 시:

1. EAS Console → 기존 token이 *아직 revoke되지 않았다면*(overlap 기간 내) 즉시
   Railway secrets에서 기존 token으로 복구.
2. 기존 token revoke 완료된 상태라면, 새 token *즉시 재발급* + §4.2-§4.3 다시 실행.
3. 24h 안에 회복 불가 시 `EXPO_ACCESS_TOKEN=`(빈 문자열)로 강등 — Expo SDK 자체 무인증
   모드는 *enhanced security mode 비활성*된 프로젝트에서만 동작. enhanced mode 활성 prod는
   nudge 발송 자체가 차단됨 — 사용자 영향(NFR-R 정합) 검토 후 결정.

### 4.6. 변경 트리거

- 운영자 퇴사/권한 변경
- token leak 의심
- 6개월 정기 회전 (캘린더)

---

## 5. Google OAuth client secret 회전 (Story 8.5)

Google Cloud Console의 OAuth 2.0 Web client secret. `GOOGLE_OAUTH_CLIENT_SECRET` env가 `bn-api` +
`bn-web` Render service 양쪽에서 사용. 6개월 1회 회전(또는 leak 의심 시 즉시).

### 5.1. 신규 secret 발급

1. [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → 사용자 인증 정보.
2. Web 클라이언트 — `balancenote-web`(client_id `559604985813-fi8mfivn1fhjgq9a9ehdh5l8qp5iivpk.apps.googleusercontent.com`)
   클릭.
3. **+ 새 시크릿 만들기** → 신규 secret 생성. 기존 secret은 *7일 grace 동안 동시 유효*
   (Google 정책 — 회전 중 OAuth 끊김 0초 보장).
4. 발급된 secret을 *임시 보안 노트*에 복사. 페이지 이탈 후 재조회 가능(*old + new* 둘 다 dashboard에 표시).

### 5.2. Render env vars 갱신 (2 service 동시)

1. Render dashboard → `bn-api` service → `Environment` → `GOOGLE_OAUTH_CLIENT_SECRET` → 신규 secret 붙여넣기 → `Save Changes`.
2. Render dashboard → `bn-web` service → 동일 — `GOOGLE_OAUTH_CLIENT_SECRET` 신규 secret 주입.
3. **양 service 자동 재배포 동시 진행** — 5분 대기 후 두 service 모두 정상 부팅 확인.

### 5.3. 로그인 흐름 검증

1. `https://bn-web.onrender.com/login` → Google 로그인 버튼 클릭 → 신규 secret으로 OAuth flow 완료.
2. Sentry → `auth.google.id_token_invalid` 0건 확인 (5분 모니터링).
3. `redirect_uri`는 secret 회전과 *무관* — 회전 후 추가 작업 없음.

### 5.4. 기존 secret revoke

1. §5.3 검증 통과 + 7일 grace 후 (또는 leak 의심 시 즉시) Google Console → 클라이언트 → 기존 secret → ⋯ → `삭제`.
2. revoke 직후 첫 로그인 흐름 1회 추가 검증.

### 5.5. rollback (장애 시)

신규 secret 적용 후 OAuth invalid_client 다발 시:

1. 기존 secret이 *grace 기간 내*면 Render env vars 양 service에서 기존 secret으로 복구 → 자동 재배포.
2. grace 만료 시 Google Console에서 새 secret 재 발급 → §5.2-§5.3 재실행.
3. 회복 불가 시(드물지만 OAuth Console 자체 장애) `secret-rotation.md` §incident-response.md
   §1 외부 API 장애 SOP 진입.

### 5.6. 변경 트리거

- 운영자 퇴사 / 권한 변경.
- secret leak 의심 (GitHub commit / Discord / Slack leak 등).
- 6개월 정기 회전.

---

## 6. TOSS_SECRET_KEY 회전 (Story 6.1)

운영 prod ``TOSS_SECRET_KEY`` 회전 5단계. sandbox(``test_sk_...``)는 회전 무관 — Toss
콘솔에서 같은 키 영구 사용. prod(``live_sk_...``)는 운영자 퇴사·token leak 의심 시점에
즉시 회전.

### 6.1. 신규 secret 발급

1. Toss 개발자 콘솔(https://developers.tosspayments.com) → *내 개발 정보* → 본 가맹점 선택.
2. *시크릿 키 재발급* 버튼 클릭 → 신규 ``live_sk_<...>`` 생성. 기존 키는 *7일 grace
   동안 동시 유효*(Toss 정책 — 운영 중단 회피).
3. 신규 키를 *비밀번호 매니저* 또는 *Railway secrets* 임시 슬롯(``TOSS_SECRET_KEY_NEW``)에
   복사 — 평문 저장 금지.

### 6.2. 겹침 deploy

Railway secrets에 *2개 키 동시 등록*:

```
TOSS_SECRET_KEY=<old key>          # 기존
TOSS_SECRET_KEY_NEW=<new live_sk>  # 신규 (deploy 검증용)
```

API 컨테이너는 ``TOSS_SECRET_KEY``만 읽으므로 본 단계에서는 *현 동작 영향 0건*.

### 6.3. dry-run 결제 검증

테스트 사용자 계정 1건으로 sandbox-equivalent 결제 시도(prod 결제 흐름이 sandbox 카드를
거부하므로, 외주 운영자가 *최소 금액*인 100원 임시 플랜 등록 후 실 카드 결제 → 즉시
환불 흐름).

검증 후 staging 환경에서 ``TOSS_SECRET_KEY`` ← ``TOSS_SECRET_KEY_NEW`` 갱신 + API
재배포 → 정상 결제 1건 → ``payment_logs.status='success'`` row 확인.

### 6.4. prod 갱신 + 구 키 revoke

1. Railway prod 환경 변수 ``TOSS_SECRET_KEY`` ← ``TOSS_SECRET_KEY_NEW`` 갱신.
2. ``TOSS_SECRET_KEY_NEW`` Railway env에서 삭제(slot 정리).
3. API 컨테이너 재배포 — `app/adapters/toss.py` lazy 어댑터가 신규 키로 첫 호출.
4. Toss 개발자 콘솔에서 *기존 시크릿 키 만료* 처리 — 7일 grace 단축.

### 6.5. rollback (장애 시)

신규 키로 결제가 실패하는 경우(``payments.toss.secret_key_missing`` 503 또는 ``payments.
provider.unavailable`` 502 다발):

1. Railway prod ``TOSS_SECRET_KEY`` ← *구 키* 즉시 복원(7일 grace 내 가능).
2. API 재배포 → 회복.
3. Toss 콘솔에서 *기존 키 만료 취소* 또는 *재 재발급*으로 새 신규 키 생성 후 재시도.

### 6.6. 변경 트리거

- 운영자 퇴사/권한 변경
- secret_key leak 의심 (Sentry capture에서 raw key 노출 등)
- 12개월 정기 회전 (캘린더)
- Toss 측 정책 변경 또는 가맹점 ID 변경

---

## 7. TOSS_WEBHOOK_SECRET_KEY 회전 5단계 (Story 6.3)

Toss webhook 시그니처 검증에 사용되는 ``TOSS_WEBHOOK_SECRET_KEY``는 ``TOSS_SECRET_KEY``와
**별 키**(콘솔에서 별도 발급, ``whsec_*`` / ``wsk_*`` prefix). 회전 순서는 confirm secret
회전과 유사하나 dual-secret 동시 검증은 *Story 8.4 hardening forward* — 본 baseline은
*current secret 단일* 운영이라 회전 시 *짧은 down*(~수 초)이 발생할 수 있음. Toss 측
retry(1분 backoff)가 자연 회복.

### 7.1. 신규 secret 발급

1. Toss 콘솔 *"개발자 도구 > Webhook > 시그니처 키"* 메뉴에서 *"새 키 발급"* 클릭.
2. 발급된 ``whsec_*`` 신규 키를 안전한 노트(1Password 등)에 임시 저장.
3. 구 secret은 일정 기간(7일 grace) 유효 — 회전 중 webhook이 즉시 끊기지 않도록 *겹침* 보장.

### 7.2. 신규 환경 변수 추가 (겹침 deploy)

1. Railway/staging 환경 변수에 ``TOSS_WEBHOOK_SECRET_KEY_NEW`` 신설(임시 slot).
2. API 컨테이너 재배포 후 Toss 콘솔 *"테스트 webhook"* 1건 dry-run — sentry breadcrumb +
   ``payment_logs.event_type='renew'`` row INSERT 확인.

### 7.3. prod 갱신 + 컨테이너 재배포

1. Railway prod ``TOSS_WEBHOOK_SECRET_KEY`` ← ``TOSS_WEBHOOK_SECRET_KEY_NEW`` 값 복사.
2. ``TOSS_WEBHOOK_SECRET_KEY_NEW`` Railway env에서 삭제(slot 정리).
3. API 컨테이너 재배포 — ``app/api/v1/payments.py:handle_payment_webhook`` lazy 어댑터가
   신규 키로 첫 검증.
4. Toss 콘솔에서 *테스트 webhook* 1건 발송 → ``payments.webhook.processed`` info log 확인.

### 7.4. 구 secret revoke

1. Toss 콘솔에서 *기존 webhook secret 만료* 처리.
2. 1시간 후 sentry ``payments.webhook.signature_invalid`` warning 0건 확인(구 secret으로
   여전히 도착하는 webhook이 없음을 검증).

### 7.5. rollback (장애 시)

신규 키로 webhook이 401 다발하는 경우(``payments.webhook.signature_invalid`` sentry 폭증):

1. Railway prod ``TOSS_WEBHOOK_SECRET_KEY`` ← *구 키* 즉시 복원(7일 grace 내 가능).
2. API 재배포 → 회복.
3. Toss 콘솔에서 *신규 키 발급 취소* 또는 *재 재발급*으로 새 신규 키 생성 후 재시도.

> **Story 8.4 forward** — *dual-secret 동시 검증*(``TOSS_WEBHOOK_SECRET_KEY`` +
> ``TOSS_WEBHOOK_SECRET_KEY_PREVIOUS``) 옵션을 추가하면 회전 중 down 0초 가능. 본 스토리
> baseline은 단일 secret + Toss retry로 자연 회복(*MVP 운영 부담 ↓*).

---

## 8. Sentry DSN + Supabase Service Key 회전 (Story 8.5)

### 8.1. Sentry DSN 회전

Sentry는 `SENTRY_DSN` (backend `balancenote-api` project) + `NEXT_PUBLIC_SENTRY_DSN`
(frontend `balancenote-web` project — Story 8.4 wiring forward) 2개. 12개월 1회 또는
leak 의심 시 회전. DSN은 *고객 사용자가 보지 못하는 서버 식별자*라 secret-equivalent.

1. [Sentry Dashboard](https://sentry.io) → 해당 project (`balancenote-api` 또는 `balancenote-web`)
   → `Settings` → `Client Keys (DSN)` → `+ Generate New Key`.
2. 신규 DSN 복사 후 Render dashboard → 해당 service → `Environment` → 변수 → 신규 값 → `Save Changes`.
3. 자동 재배포 1~2분 대기. 의도적 에러 1건 발생시켜 신규 DSN으로 event 도착 확인.
4. 기존 key는 grace 기간(Sentry는 즉시 비활성 안 함) — 24h 후 `Settings` → `Client Keys` → 기존 → `Revoke`.

#### rollback

기존 key 미 revoke 상태라면 Render env vars에서 즉시 기존 DSN 복원. revoke 완료 시 §8.1.1
재실행. 회복 불가 시 `SENTRY_DSN=`(빈 값) 강등 — `sentry.init()`이 graceful skip (sentry.py:128).

### 8.2. Supabase Service Key 회전

`SUPABASE_SERVICE_KEY` env는 Storage Adapter(`r2.py` Supabase 분기) + 향후 Supabase 직접
호출에서 사용. service_role 권한이라 *leak 시 DB·Storage 전체 RW 가능* — 최고 보안 등급.
6개월 1회 또는 leak 의심 시 즉시 회전.

1. Supabase Dashboard → 본 프로젝트 → `Settings` → `API` → `service_role` 키 → `Reset`.
2. **주의**: Supabase는 service key를 *즉시 무효화*하고 신규 발급 → grace 0초. 회전 직전에
   Render env vars에 신규 key를 *미리 입력 + Save Changes* 후 자동 재배포 완료를 *확인한 뒤*
   Supabase에서 reset.
3. 또는 Render env vars의 기존 key를 빈 값으로 두지 *않고*, Reset 직후 신규 key로 즉시 갱신
   (downtime ~1분 — 신규 배포 + 첫 호출까지).
4. 검증: `POST /v1/meals/images/presign` 호출 1회 → Sentry `storage.supabase.signed_upload_created`
   info log 정상 도착.

#### rollback

Supabase Service Key는 *과거 값으로 복구 불가능* — reset 후 옛 키는 영구 무효. 신규 key로
재배포만이 회복 경로. 만약 reset 직후 prod에서 storage 호출이 일제히 실패하면 즉시 Render env에
신규 key가 정확히 입력됐는지 확인(타이핑 실수, 줄바꿈 포함 여부 검증).

### 8.3. 변경 트리거

- 운영자 퇴사 / 권한 변경.
- key/DSN leak 의심.
- Sentry: 12개월 정기 회전.
- Supabase: 6개월 정기 회전 (서버 권한 key — 더 자주).

---

## 9. 회전 캘린더 (Story 8.5)

분기별 회전 SOP 모음 — 운영자 수동 캘린더 alert 또는 GitHub Actions cron(별도 workflow,
Story 8.5 OUT) 트리거.

| 회전 주기 | secret | 다음 회전 (예) | 단락 |
|----------|-------|--------------|------|
| **분기 (3개월)** | `OPENAI_API_KEY` | 2026-08-12, 2026-11-12, 2027-02-12... | §1 |
| **분기 (3개월)** | `ANTHROPIC_API_KEY` | 2026-08-12, 2026-11-12... | §2 |
| **분기 (3개월)** | `LANGSMITH_API_KEY` | 2026-08-12, 2026-11-12... | §3 |
| **6개월** | `EXPO_ACCESS_TOKEN` | 2026-11-12 | §4 |
| **6개월** | `GOOGLE_OAUTH_CLIENT_SECRET` | 2026-11-12 | §5 |
| **12개월** | `TOSS_SECRET_KEY` (prod live) | 2027-05-12 (sandbox 무회전) | §6 |
| **12개월** | `TOSS_WEBHOOK_SECRET_KEY` (prod live) | 2027-05-12 (sandbox 무회전) | §7 |
| **12개월** | `SENTRY_DSN` (backend + web) | 2027-05-12 | §8.1 |
| **6개월** | `SUPABASE_SERVICE_KEY` | 2026-11-12 | §8.2 |
| **분기 (3개월)** | `JWT_SECRET_KEY` (prod) | 2026-08-12 — 사용자 전체 강제 logout 동반 | (별도 SOP) |
| **분기 (3개월)** | `DISCORD_COST_WEBHOOK_URL` | 2026-08-12 — leak 시 즉시 | (별도 SOP) |

### 9.1. 회전 발생 시 공통 checklist

- [ ] 신규 secret 발급 (해당 § 1.1 / 2.1 / 5.1 / 8.x.1).
- [ ] Render env vars 갱신 + 자동 재배포 검증 (`/healthz` 200).
- [ ] 도착 검증 (Sentry breadcrumb / LangSmith trace / Toss webhook log 등).
- [ ] 기존 secret revoke (해당 § 1.4 / 2.4 / 5.4 / 8.x.1).
- [ ] 본 캘린더의 "다음 회전" 컬럼 갱신.
- [ ] 변경 이력을 `_bmad-output/implementation-artifacts/secret-rotation-log.md` (옵션)에 추가.

### 9.2. 알림 자동화 (Story 8.5 OUT — Story 8.4 polish forward)

분기 1회 자동 알림 cron(별도 GitHub Actions workflow + Discord webhook)은 Story 8.4 polish 단계
forward. 본 시점은 운영자 수동 캘린더 alert + 본 §9 회전 표를 1순위 SOT로 운영.
