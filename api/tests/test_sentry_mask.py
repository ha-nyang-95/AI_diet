"""Story 3.6 — `app.core.sentry.mask_event` 마스킹 anchor 단위 검증 (Task 13.2)."""

from __future__ import annotations

from typing import Any

from app.core.sentry import mask_event


def test_mask_event_redacts_prompt_and_raw_text() -> None:
    """`extra` 안의 prompt / raw_text key value를 ``"***"`` 치환."""
    event: Any = {"extra": {"prompt": "secret-prompt", "raw_text": "secret-meal", "safe": "ok"}}
    out: Any = mask_event(event, {})
    assert out is not None
    assert out["extra"]["prompt"] == "***"
    assert out["extra"]["raw_text"] == "***"
    assert out["extra"]["safe"] == "ok"


def test_mask_event_redacts_response_text_in_contexts() -> None:
    """`contexts.*` 내부 dict의 response_text key 마스킹."""
    event: Any = {
        "contexts": {
            "llm": {"response_text": "leaked", "model": "gpt-4o-mini"},
            "request": {"method": "POST"},
        }
    }
    out: Any = mask_event(event, {})
    assert out is not None
    assert out["contexts"]["llm"]["response_text"] == "***"
    assert out["contexts"]["llm"]["model"] == "gpt-4o-mini"
    assert out["contexts"]["request"]["method"] == "POST"


def test_mask_event_passes_through_when_no_sensitive_keys() -> None:
    """민감 key 부재 시 event 무변경."""
    event: Any = {
        "extra": {"meal_id": "abc", "fit_score": 80},
        "contexts": {"app": {"version": "1.0"}},
    }
    out: Any = mask_event(event, {})
    assert out["extra"]["meal_id"] == "abc"
    assert out["extra"]["fit_score"] == 80
    assert out["contexts"]["app"]["version"] == "1.0"


def test_mask_event_handles_capture_message_payload() -> None:
    """router의 ``capture_message("dual_llm_router.exhausted", ...)`` 같은
    message-only event도 안전 통과(extra/contexts 부재 graceful)."""
    event: Any = {
        "message": "dual_llm_router.exhausted",
        "level": "error",
        "tags": {"component": "llm_router"},
    }
    out: Any = mask_event(event, {})
    assert out is not None
    assert out["message"] == "dual_llm_router.exhausted"
    assert out["tags"]["component"] == "llm_router"
