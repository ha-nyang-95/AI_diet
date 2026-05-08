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

## 1. OpenAI API key 회전

(Story 8.5 polish 단계에서 채움 — 본 단락은 placeholder.)

---

## 2. Anthropic API key 회전

(Story 8.5 polish 단계에서 채움 — 본 단락은 placeholder.)

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

## 5. Google OAuth client secret 회전 (Story 8.5 polish 단계 채움)

(placeholder)

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

## 7-8. 기타 secret 회전 (Story 8.5 polish 단계 채움)

본 단락은 placeholder — Story 8.5 운영 polish 단계에서 Sentry / Cloudflare R2 회전
절차를 동일 패턴으로 채운다.

## 회전 캘린더 (Story 8.5에서 박힘)

분기 1회 자동 알림 cron — `docs/sop/`에 회전 SOP 캘린더가 박힌 후 본 단락에서
링크. 본 시점(Story 3.8)에서는 운영자 수동 캘린더 alert(`docs/observability/langsmith-dashboard.md`
§4 cross-link).
