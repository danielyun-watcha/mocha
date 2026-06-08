"""TDD: query_writer.describe_archive — archive-first 카탈로그.

archive 범위 조회(kpi.available_range)는 monkeypatch 로 격리 → archive
미마운트 환경에서도 실행 (CI 안전). 캐싱·내용·refresh 동작을 명세.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents import query_writer as qw


@pytest.fixture
def fake_ranges(monkeypatch):
    """kpi.available_range 를 고정값으로 — 실제 archive 불필요."""
    ranges = {
        "galaxy": {"min": "2025-05-20", "max": "2026-06-07"},
        "mars":   {"min": "2025-05-14", "max": "2026-05-14"},
        "adult":  {"min": "2024-08-25", "max": "2026-06-07"},
    }
    import kpi
    monkeypatch.setattr(kpi, "available_range", lambda d: ranges[d])
    # 캐시 초기화 (다른 테스트 영향 제거)
    qw._ARCHIVE_CATALOG_CACHE = None
    return ranges


def test_lists_all_domains(fake_ranges):
    out = qw.describe_archive(refresh=True)
    for dom in ("galaxy", "mars", "adult"):
        assert dom in out, f"{dom} 누락"


def test_shows_ranges(fake_ranges):
    out = qw.describe_archive(refresh=True)
    # 각 도메인 범위가 카탈로그에 들어가야 함
    assert "2026-06-07" in out      # galaxy/adult max
    assert "2026-05-14" in out      # mars max (stale)
    assert "2024-08-25" in out      # adult min


def test_mentions_archive_first_and_bq_fallback(fake_ranges):
    out = qw.describe_archive(refresh=True)
    assert "archive" in out.lower()
    assert "BQ" in out or "BigQuery" in out


def test_caches_result(fake_ranges, monkeypatch):
    out1 = qw.describe_archive(refresh=True)
    # 캐시 후 available_range 가 바뀌어도 refresh 없으면 옛 결과
    import kpi
    monkeypatch.setattr(kpi, "available_range",
                        lambda d: {"min": "1999-01-01", "max": "1999-12-31"})
    out2 = qw.describe_archive()                 # 캐시 hit
    assert out2 == out1
    assert "1999" not in out2
    out3 = qw.describe_archive(refresh=True)      # 강제 재계산
    assert "1999" in out3


def test_range_lookup_failure_no_crash(monkeypatch):
    """available_range 가 예외 던져도 카탈로그는 생성 (graceful)."""
    import kpi
    def boom(d):
        raise RuntimeError("archive unmounted")
    monkeypatch.setattr(kpi, "available_range", boom)
    qw._ARCHIVE_CATALOG_CACHE = None
    out = qw.describe_archive(refresh=True)
    assert "galaxy" in out  # 도메인은 여전히 나열
    assert "조회 실패" in out
