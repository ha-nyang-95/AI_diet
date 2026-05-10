# SOP 05 — Admin role promotion / demotion

## 1. 언제 사용하는가

- 외주 인수 후 클라이언트가 자기 admin 사용자 부여 시점.
- 운영 중 임시 admin 권한 부여 또는 권한 박탈 필요 시.
- *대량 일괄 promote*, *UI에서 직접 promote*는 본 SOP scope 외 (Growth, Story 8 hardening forward).

## 2. 사전 조건

- `.env` 또는 `api/.env`에 `DATABASE_URL` 설정 — 대상 환경(prod/staging/dev)을 정확히 가리킬 것.
- `uv` 설치 (`api/pyproject.toml`의 SOT — 동일 venv 재사용).
- 대상 사용자가 *이미 Google OAuth로 회원가입 완료* 상태(`users.google_sub` row 존재).

## 3. 실행 절차

1. **사용자 가입 확인** — 대상 사용자가 BalanceNote 앱(또는 Web)에서 Google 로그인을 1회 통과해 `users` 테이블에 row가 생성됐는지 확인.
2. **email 식별** — 사용자에게 본인의 Google 계정 email을 받아 정확히 매칭(`users.email`).
3. **CLI 실행**:

   ```bash
   uv run python scripts/promote_admin.py --email user@example.com
   ```

   - confirm prompt에 `y` 입력 → role flip 수행.
   - `--yes` 옵션 추가 시 prompt 생략 (CI/automation 정합).
4. **결과 확인** — CLI 출력 예시:

   ```
   사용자 user@example.com 현재 role: 'user'
   'admin'로 flip하시겠습니까? [y/N]: y
   사용자 user@example.com role: 'user' → 'admin'
   ```

## 4. 검증

- DB 직접 확인:

  ```bash
  psql -c "SELECT id, email, role FROM users WHERE email='user@example.com'"
  ```

- 또는 admin JWT 발급 후 `GET /v1/auth/admin/whoami` 호출:
  - `POST /v1/auth/admin/exchange` (user JWT 첨부) → admin JWT 발급.
  - `GET /v1/auth/admin/whoami` (admin JWT 첨부) → 200 + `role: "admin"` 응답이면 성공.

## 5. 권한 박탈 (admin → user)

- `--demote` flag로 즉시 박탈:

  ```bash
  uv run python scripts/promote_admin.py --email user@example.com --demote --yes
  ```

- DB row만 SOT — 박탈 즉시 반영(JWT는 여전히 valid 형식이지만 `current_admin`의 *DB role 재확인* 분기에서 403 차단). 이미 발급된 admin JWT는 `bn_admin_access` 쿠키 만료(8시간) 또는 사용자가 `/api/auth/admin/logout`을 호출하기 전까지는 형식상 잔존.

## 6. Audit trail forward (Story 7.3)

본 CLI는 현재 audit_logs row를 INSERT *하지 않음*. Story 7.3에서 `audit_logs` 테이블 + `audit_admin_action` dep 도입 후, 본 CLI도 `actor_id="cli"` + `action="admin_role_flip"` + `target_user_id=...` row를 INSERT하도록 확장 예정. 본 SOP도 그 시점에 갱신.

## 7. 대체 흐름 — psql 직접 UPDATE (권장 X)

본 CLI 실행이 불가능한 환경(예: SQL-only restricted 운영자 권한)의 fallback:

```sql
BEGIN;
UPDATE users SET role='admin' WHERE email='user@example.com';
SELECT id, email, role FROM users WHERE email='user@example.com';
COMMIT;
```

단, *권장 X* — CLI는 (a) 트랜잭션 wrap, (b) deleted_at 필터, (c) 같은 role 멱등 분기, (d) prod/staging non-tty fail-fast 가드를 모두 포함하지만 직접 SQL은 위 4 가드 누락. 운영 사고 위험이 더 큼.

## 8. 환경별 안전 가드

- `dev`/`ci`/`test`: confirm prompt 디폴트 활성화. `--yes`로 skip 가능.
- `prod`/`staging`: `--yes` *미지정* + non-tty(자동화 컨텍스트) 감지 시 *exit code 3* + stderr 한국어 안내 — *실수 자동 실행 차단*.
- 대상 사용자가 `deleted_at IS NOT NULL` (탈퇴 진행 중)이면 미발견 분기로 흘러 *role flip 거부*. PIPA 30일 grace 기간 보호 정합.
