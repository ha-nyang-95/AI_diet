"""Story 4.2 — APScheduler in-process worker SOT.

`scheduler.py`이 ``AsyncIOScheduler`` SOT, `nudge_scheduler.py`가 미기록 sweep cron
잡을 등록. lifespan 5번째 자원으로 wire(`app/main.py`).
"""
