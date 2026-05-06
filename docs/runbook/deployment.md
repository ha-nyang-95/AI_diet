# 배포 토폴로지 + 외주 인수 마이그레이션 SOP

**SOT 작성일**: 2026-05-05 (Story 3.9 AC3)
**대상 독자**: 운영자(hwan) / 외주 인수자(향후) / 클라이언트 SRE

---

## 1. 현행 토폴로지 (Railway + Cloudflare + R2)

```
┌──────────────┐
│ Mobile / Web │
└──────┬───────┘
       │ HTTPS (TLS 1.3)
       ▼
┌────────────────────────────────────────┐
│ Cloudflare                             │
│  • DNS (api.balancenote.com)           │
│  • WAF rule set                        │
│  • DDoS L7 mitigation                  │
│  • TLS termination                     │
│  • CF-Connecting-IP 헤더 첨부          │
└──────┬─────────────────────────────────┘
       │ HTTPS (Cloudflare → origin)
       ▼
┌────────────────────────────────────────┐
│ Railway                                │
│  • uvicorn (FastAPI lifespan)          │
│  • proxy_headers=True                  │
│  • forwarded_allow_ips=Cloudflare CIDR │
└──┬───────────┬───────────┬─────────────┘
   │           │           │
   ▼           ▼           ▼
┌──────────┐ ┌──────┐ ┌──────────────────┐
│ Postgres │ │Redis │ │ Cloudflare R2    │
│  + pgvec │ │      │ │ (image storage)  │
└──────────┘ └──────┘ └──────────────────┘
```

### 핵심 설계 선택

- **Cloudflare 프록시 in front**: WAF/DDoS/CDN 1차 방어 + 한국 사용자 PoP latency 단축.
  TLS는 Cloudflare가 종단 처리 — origin(Railway)은 HTTPS *origin pull* 정합.
- **`CF-Connecting-IP` 헤더 신뢰**: Cloudflare가 강제 첨부하는 원본 클라이언트 IP. 신뢰
  proxy 검증(`api/app/core/proxy.py:_is_trusted_proxy_ip`)으로 spoofing 차단.
- **uvicorn `proxy_headers`**: Railway → uvicorn 사설 IP forwarding 시 `X-Forwarded-For`
  로 원본 IP 노출. `forwarded_allow_ips`에 Cloudflare IPv4/IPv6 CIDR 22개 + private
  range 화이트리스트.
- **Railway-specific feature 회피**: pgvector container, Redis container 모두 Railway
  plugin이 아닌 standard Postgres + Redis로 구성 → Cloud Run / AWS ECS 마이그레이션
  시 그대로 swap 가능.

---

## 2. uvicorn 실행 시점 wire (Railway)

Railway 환경 변수:

```bash
# Railway dashboard → Service → Variables
PORT=8080
WEB_CONCURRENCY=2
```

`Procfile` 또는 Railway start command:

```bash
uv run uvicorn app.main:app \
  --host 0.0.0.0 \
  --port ${PORT} \
  --proxy-headers \
  --forwarded-allow-ips='*'
```

**`--forwarded-allow-ips='*'`** 의미: Railway가 자체 internal proxy로 연결하므로 모든
forwarded 헤더를 일단 trust. application-layer에서 `app.core.proxy.get_real_client_ip`
가 *Cloudflare CIDR + private IP*로 다시 필터링 → 두 단계 trust 모델.

---

## 3. Cloudflare WAF rule (`forwarded_allow_ips` 보강)

Cloudflare dashboard → Security → WAF → Custom Rules:

### Rule 1 — Web 전용 Same-origin Referer 강제 (W17 1.5)

```
(http.request.method eq "POST"
  and http.request.uri.path eq "/v1/users/me/profile"
  and (
    starts_with(http.user_agent, "Mozilla/")
    or http.user_agent contains "Chrome"
  )
  and http.referer ne "https://balancenote.com")
=> Block (403)
```

**중요 주의 (CR P20 — 2026-05-06)**: React Native / Expo 네이티브 클라이언트는 표준
``Referer`` 헤더를 발신하지 않으므로 단순 ``http.referer ne ...`` 조건은 모바일
트래픽도 일괄 차단된다. 위 룰은 *브라우저 UA prefix*로 web 트래픽만 게이팅 — 모바일은
JWT(Bearer) + httpOnly cookie 부재로 CSRF 표면 자체가 다르다(SameSite는 브라우저 정책).
운영 적용 전 staging에서 모바일 happy-path 1회 검증 의무.

CSRF 추가 가드 — httpOnly 쿠키 + SameSite=Lax는 1차 방어, Cloudflare WAF는 2차.

### Rule 2 — Known bad bot 차단 (DDoS 보강)

```
(cf.client.bot eq "true" and not cf.verified_bot eq "true")
=> Challenge (CAPTCHA)
```

---

## 4. 외주 인수 마이그레이션 가이드

### 4.1 Cloud Run / Google Cloud로 마이그레이션 시

**변경 필요 지점**:

| 영역 | Railway 패턴 | Cloud Run 패턴 |
|---|---|---|
| Secret 저장 | Railway env vars | GCP Secret Manager |
| DB connection | `DATABASE_URL` | `DATABASE_URL` + Cloud SQL Auth Proxy |
| Redis | Railway plugin | Memorystore for Redis |
| R2 | Cloudflare R2 (S3 API 호환) | Cloud Storage |
| Container build | Railway Nixpacks | `Dockerfile` + Artifact Registry |

**uvicorn `--forwarded-allow-ips`**: Cloud Run은 `X-Forwarded-For` 마지막 IP가 원본
이라 본 패턴이 다름 — `app/core/proxy.py`의 `get_real_client_ip`에 ``cloud_run_xff``
모드 추가 필요. 외주 인수 시 작성.

### 4.2 AWS ECS / Fargate로 마이그레이션 시

**변경 필요 지점**:

| 영역 | Railway 패턴 | AWS 패턴 |
|---|---|---|
| Load Balancer | Cloudflare → Railway | Cloudflare → ALB → ECS |
| Secret 저장 | Railway env vars | AWS Secrets Manager |
| DB | Railway Postgres | RDS PostgreSQL + pgvector extension |
| Redis | Railway plugin | ElastiCache Redis |
| R2 | Cloudflare R2 | S3 |

**ALB `X-Forwarded-For` 첫 IP가 원본** — Railway 패턴과 동일하게 동작 → `proxy.py`
변경 0건.

### 4.3 Cloudflare 자체를 제거하는 경우

`api/app/core/proxy.py`:
- `_CLOUDFLARE_IPV4`/`_CLOUDFLARE_IPV6` frozenset를 빈 set로 swap.
- `get_real_client_ip`가 자동으로 `request.client.host` raw fallback 의존.
- Cloudflare WAF rule(§3)을 ALB WAF / Cloud Armor로 이전.

---

## 5. Cloudflare IP range 갱신 SOP

분기 1회(=3개월) 운영자 작업. 별도 문서: [`cloudflare-ip-refresh.md`](./cloudflare-ip-refresh.md).

---

## 6. 결정 SOT

- **Story 3.9 AC1-3 결정** (2026-05-05) — `_bmad-output/implementation-artifacts/deferred-work.md`.
- **architecture.md** — `Infrastructure & Deployment` 섹션 (line 340-353) 참조.

---

## 7. 비상 연락처 / 회복 절차

(외주 인수 시 클라이언트가 채움)

- **DNS 장애**: Cloudflare dashboard → DNS → Records 확인 + `dig api.balancenote.com`.
- **TLS 인증서 만료**: Cloudflare 자동 갱신 — 만료 7일 전 알림 + dashboard SSL/TLS.
- **Origin 서버 down**: Railway dashboard → Service → Restart. 또는 Cloud Run / ECS
  health check 강제 재배포.
