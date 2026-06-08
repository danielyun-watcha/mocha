"""TDD: build_system_prompt 가 deep-track 에 archive-first 카탈로그를 주입.

deep-track agent 가 'archive 우선, 범위 밖이면 BQ' 를 판단하려면 도메인 범위
카탈로그가 system prompt 에 있어야 한다. archive 미마운트 환경 대비
available_range 는 monkeypatch.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://x")  # main import-safe
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def fake_ranges(monkeypatch):
    import kpi
    from agents import query_writer as qw
    monkeypatch.setattr(kpi, "available_range",
                        lambda d: {"min": "2025-05-20", "max": "2026-06-07"})
    qw._ARCHIVE_CATALOG_CACHE = None
    return qw


@pytest.mark.parametrize("domain", ["watcha_main", "pedia", "adult"])
def test_prompt_includes_archive_catalog(fake_ranges, domain):
    import main
    p = main.build_system_prompt(domain)
    assert "Archive 데이터" in p, f"{domain}: archive 카탈로그 누락"
    assert "BQ" in p or "BigQuery" in p, f"{domain}: BQ fallback 안내 누락"
