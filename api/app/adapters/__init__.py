"""외부 시스템 어댑터 패키지 — Google OAuth, R2, MFDS, 결제 등.

원칙: 외부 통신 책임을 라우터·서비스에서 분리. 테스트 시 monkeypatch / respx로 stub.
"""
