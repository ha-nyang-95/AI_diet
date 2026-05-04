"""Story 3.8 — 외부 SDK 보안 패치 회귀 가드 (AC4).

silent downgrade 방지 — `langsmith>=0.7.31`(GHSA-rr7j-v2q5-chgv: redaction
pipeline `events` 배열 누락 → token-level streaming raw token leak) 등 보안
픽스가 박힌 버전이 lock 되돌려질 때 단위 테스트로 잡는다.
"""

from __future__ import annotations

import langsmith


def _parse_semver(version: str) -> tuple[int, int, int]:
    """`"0.7.31"` / `"0.8.0"` / `"1.0.0rc1"` 등 PEP 440 prefix를 majorminor.patch로 정규화.

    pre-release suffix(`rc1`, `b2`, `+local.1`)는 무시 — 본 가드는 *주요 패치 라인*만
    검증(0.7.31 이상이면 통과). dev wheel(`0.8.0.dev3`)도 동일 처리.
    """
    head = version.split("+", 1)[0]
    parts: list[int] = []
    for token in head.split(".")[:3]:
        # numeric prefix만 추출 ("31rc1" → 31).
        digits = ""
        for char in token:
            if char.isdigit():
                digits += char
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def test_langsmith_at_or_above_security_patch() -> None:
    """`langsmith>=0.7.31` 강제 — GHSA-rr7j-v2q5-chgv 패치 미만 차단."""
    minimum = (0, 7, 31)
    actual = _parse_semver(langsmith.__version__)
    assert actual >= minimum, (
        f"langsmith {langsmith.__version__} < 0.7.31 — GHSA-rr7j-v2q5-chgv "
        "(events array PII leak) 미패치. pyproject.toml + uv.lock 점검."
    )


def test_parse_semver_handles_prerelease_suffix() -> None:
    """`_parse_semver` 자체 가드 — pre-release / dev / local 표기 안전 처리."""
    assert _parse_semver("0.7.31") == (0, 7, 31)
    assert _parse_semver("0.8.0") == (0, 8, 0)
    assert _parse_semver("1.0.0rc1") == (1, 0, 0)
    assert _parse_semver("0.8.0.dev3") == (0, 8, 0)
    assert _parse_semver("0.7.31+local.1") == (0, 7, 31)
