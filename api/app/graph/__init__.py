"""LangGraph 분석 파이프라인 패키지 — Story 3.3.

`app.graph.state`는 SOT TypedDict + 노드 IO Pydantic 모델, `app.graph.pipeline`은
`compile_pipeline` 진입점. 외부에서는 `app.services.analysis_service`를 호출하고
본 패키지는 *그래프 내부 SOT*만 노출.
"""

from __future__ import annotations
