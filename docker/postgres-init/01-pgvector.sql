-- BalanceNote DB 초기화
-- (postgres 컨테이너 첫 부팅 시 1회 자동 실행 — /docker-entrypoint-initdb.d)

-- pgvector extension (Self-RAG 임베딩 저장용)
CREATE EXTENSION IF NOT EXISTS vector;

-- LangGraph AsyncPostgresSaver checkpoint 스키마
-- 테이블은 LangGraph .setup()이 생성 (Story 3.3) — Alembic 추적 외부
CREATE SCHEMA IF NOT EXISTS lg_checkpoints;
