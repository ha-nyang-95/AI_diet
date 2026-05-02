"""Story 3.3 — `psycopg[binary,pool]` 직접 의존성 + `langgraph-checkpoint-postgres>=3.0`
승격 검증 (AC10).

import 가능 + version metadata 검증으로 외주 인수 시 dependency tree drift 차단.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md

from packaging.version import Version


def test_psycopg_importable() -> None:
    psycopg = importlib.import_module("psycopg")
    assert psycopg is not None


def test_psycopg_pool_importable() -> None:
    psycopg_pool = importlib.import_module("psycopg_pool")
    assert hasattr(psycopg_pool, "AsyncConnectionPool")


def test_psycopg_version_at_least_3_2() -> None:
    assert Version(md.version("psycopg")) >= Version("3.2")


def test_psycopg_pool_version_at_least_3_2() -> None:
    assert Version(md.version("psycopg-pool")) >= Version("3.2")


def test_langgraph_checkpoint_postgres_version_at_least_3_0() -> None:
    assert Version(md.version("langgraph-checkpoint-postgres")) >= Version("3.0")


def test_async_postgres_saver_importable() -> None:
    """`AsyncPostgresSaver`는 langgraph-checkpoint-postgres 3.x 표준 import 경로."""
    mod = importlib.import_module("langgraph.checkpoint.postgres.aio")
    assert hasattr(mod, "AsyncPostgresSaver")
