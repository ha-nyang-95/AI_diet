import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Story 8.5 AC9 — Render Node service에서 `.next/standalone/server.js` 단독 실행 모드.
  // standalone 산출물은 node_modules의 production-required 의존성만 포함 → 컨테이너 size ↓
  // (full node_modules vs 단일 minimal bundle). Render Free Node 빌드의 build cache + cold
  // start latency 정합.
  output: "standalone",
};

export default nextConfig;
