# Cloudflare IP range 갱신 SOP

**SOT 작성일**: 2026-05-05 (Story 3.9 AC3)
**갱신 주기**: 분기 1회(3개월)
**책임자**: 운영자(hwan) → 외주 인수 후 클라이언트 SRE

---

## 1. 왜 갱신이 필요한가

`api/app/core/proxy.py`의 `_CLOUDFLARE_IPV4` / `_CLOUDFLARE_IPV6` frozenset는 **정적
캡처**다. Cloudflare가 신규 IP block을 추가하거나 기존 block을 retire하면 우리 trust
list가 stale → 일부 trusted proxy 요청이 *raw fallback* 분기로 떨어져 IP attribution
정확도 저하.

PIPA audit / refresh_token IP 추적 / SSE rate limit 모두 IP가 정확해야 보호 효과 발휘.

---

## 2. 갱신 절차 (5단계)

### Step 1: Cloudflare 공식 SOT fetch

```bash
curl -s https://www.cloudflare.com/ips-v4 > /tmp/cf-ipv4.txt
curl -s https://www.cloudflare.com/ips-v6 > /tmp/cf-ipv6.txt

# 갯수 확인 — 2026-05 기준 IPv4 15개, IPv6 7개
wc -l /tmp/cf-ipv4.txt /tmp/cf-ipv6.txt
```

### Step 2: 차이 확인

```bash
diff <(grep -oP '"\K[^"]+(?=")' api/app/core/proxy.py | grep -E '^\d+\.|^[0-9a-f]+:' | sort) \
     <(cat /tmp/cf-ipv4.txt /tmp/cf-ipv6.txt | sort)
```

차이가 0이면 갱신 불요. 차이가 있으면 Step 3.

### Step 3: 코드 갱신

`api/app/core/proxy.py:_CLOUDFLARE_IPV4` 와 `_CLOUDFLARE_IPV6` frozenset entry 갱신.
주석에 `(2026-05 캡처, 분기 1회 갱신)` → `(2026-08 캡처, 분기 1회 갱신)` 으로 시점 표기.

### Step 4: 테스트

```bash
cd api && uv run pytest tests/core/test_proxy.py -v
```

`test_cloudflare_ipv4_set_size` 회귀 가드가 갯수 변화 시 fail — frozenset 갯수 단언
값을 새 갯수로 갱신. 신규 entry가 합법적인지 확인 후만 커밋.

### Step 5: 커밋 + PR

```bash
git checkout -b chore/cloudflare-ip-refresh-2026-08
git add api/app/core/proxy.py api/tests/core/test_proxy.py
git commit -m "chore(proxy): refresh Cloudflare IP ranges (2026-08 capture)"
git push origin chore/cloudflare-ip-refresh-2026-08
gh pr create --title "chore: refresh Cloudflare IP ranges (2026-08)"
```

---

## 3. 자동화 옵션 (Story 8.4 polish 후속)

Story 8.4 운영 polish 시점에 GitHub Actions cron으로 자동화 검토:

```yaml
# .github/workflows/cloudflare-ip-refresh.yml
name: Cloudflare IP refresh check
on:
  schedule:
    - cron: "0 0 1 */3 *"  # 매 분기 1일 KST 09:00
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          curl -s https://www.cloudflare.com/ips-v4 > /tmp/cf-ipv4.txt
          curl -s https://www.cloudflare.com/ips-v6 > /tmp/cf-ipv6.txt
          # diff 확인 후 자동 PR 생성
```

자동 PR 생성은 신규 IP가 *합법*인지 운영자가 1회 검수 필요 — 완전 자동 merge는 회피.

---

## 4. 결정 SOT

- **Story 3.9 AC1, AC3 결정** (2026-05-05) — Cloudflare IP는 분기 1회 수동 갱신.
- **Cloudflare 공식**: https://www.cloudflare.com/ips/
