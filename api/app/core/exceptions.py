"""RFC 7807 Problem Details 응답 핸들러 placeholder.

Story 1.2+ 에서 채워진다:
- application/problem+json 응답
- 표준 필드: type, title, status, detail, instance, code(우리 확장)
- HTTPException → ProblemDetailResponse 변환
- ValidationError → 400 Problem Details
- 도메인 예외 계층(BalanceNoteError, AuthError, RateLimitError 등)
"""
