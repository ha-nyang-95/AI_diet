#!/usr/bin/env bash
# OpenAPI 스키마에서 web + mobile TS 클라이언트 자동 생성
# 사용법:
#   1) 백엔드 가동 중일 때:   ./scripts/gen_openapi_clients.sh
#   2) 백엔드 가동 없이(스키마 dump from import):  IN_PROCESS=1 ./scripts/gen_openapi_clients.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA="${ROOT}/.tmp-openapi.json"
mkdir -p "${ROOT}/.tmp-cache"

# 중간 산출물 정리는 정상·이상 종료 모두에서 보장.
trap 'rm -f "${SCHEMA}"' EXIT INT TERM

API_BASE="${API_BASE_URL:-http://localhost:8000}"
IN_PROCESS="${IN_PROCESS:-0}"

if [[ "${IN_PROCESS}" == "1" ]]; then
  echo "[gen:api] in-process schema dump (uv run)"
  ( cd "${ROOT}/api" && uv run python -c "import json; from app.main import app; print(json.dumps(app.openapi()))" > "${SCHEMA}" )
else
  echo "[gen:api] HTTP fetch from ${API_BASE}/openapi.json"
  curl -fsS "${API_BASE}/openapi.json" -o "${SCHEMA}"
fi

WEB_OUT="${ROOT}/web/src/lib/api-client.ts"
MOBILE_OUT="${ROOT}/mobile/lib/api-client.ts"

mkdir -p "$(dirname "${WEB_OUT}")"
mkdir -p "$(dirname "${MOBILE_OUT}")"

echo "[gen:api] regenerating ${WEB_OUT}"
( cd "${ROOT}/web" && pnpm exec openapi-typescript "${SCHEMA}" -o "${WEB_OUT}" )

echo "[gen:api] regenerating ${MOBILE_OUT}"
( cd "${ROOT}/mobile" && pnpm exec openapi-typescript "${SCHEMA}" -o "${MOBILE_OUT}" )

echo "[gen:api] done. 생성된 파일을 git에 커밋하세요 (CI openapi-diff 게이트 통과)."
