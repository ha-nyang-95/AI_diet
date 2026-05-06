-- BalanceNote 테스트 격리 — dev `app` DB와 분리된 테스트 전용 DB.
--
-- conftest.py의 autouse `_truncate_user_tables` fixture가 매 테스트마다 users/meals/
-- consents/refresh_tokens를 TRUNCATE하므로 dev DB와 같이 쓰면 dev에서 입력한 사용자·
-- 식단·동의 기록이 전부 소실됨(현 conftest.py의 ``settings.database_url_test`` 가드와
-- 짝). 본 init 스크립트는 postgres 컨테이너의 *첫 부팅* 시 1회 자동 실행
-- (/docker-entrypoint-initdb.d).
--
-- 기존 볼륨이 이미 초기화된 환경(이 PR 머지 전부터 운영 중인 dev)에서는 본 SQL이 자동
-- 실행되지 않으므로 1회 수동 적용 필요:
--   docker exec balancenote-postgres psql -U app -d app \
--     -f /docker-entrypoint-initdb.d/02-create-test-db.sql
-- 또는 동등한 SQL을 psql로 직접 실행.
--
-- pgvector / lg_checkpoints는 01-pgvector.sql과 동일 패턴 — test DB도 동일 의존성을 갖는다.
CREATE DATABASE app_test;

\connect app_test

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS lg_checkpoints;
