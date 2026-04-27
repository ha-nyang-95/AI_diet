"""인증·인가 placeholder.

Story 1.2 (Google OAuth + JWT)에서 채워진다:
- create_user_token(user_id, ...) -> str  (HS256, JWT_USER_SECRET, JWT_USER_ISSUER)
- create_admin_token(admin_id, ...) -> str  (HS256, JWT_ADMIN_SECRET, JWT_ADMIN_ISSUER)
- verify_user_token / verify_admin_token (FastAPI Depends 패턴)
- httpOnly 쿠키 교환 헬퍼 (next-auth 회피, 백엔드 직접 발행)
"""
