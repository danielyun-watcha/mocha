"""TDD: archive root 해석 — env > content-marker 후보 > legacy fallback.

단순 exists() 는 빈 마운트(jupyterhub NFS 에 /mnt/ml-archive 가 raw data 없이
존재)를 잘못 잡을 수 있어 marker(도메인 디렉토리) 까지 확인한다.
순수 로직 — tmp_path 로 격리.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from data_sources._archive_root import _resolve_archive_root


def test_env_wins(tmp_path):
    # ARCHIVE_DIR 지정 시 marker 무관 그대로
    assert _resolve_archive_root(env_val=str(tmp_path)) == tmp_path


def test_picks_candidate_with_marker(tmp_path):
    real = tmp_path / "archive"; (real / "rec_galaxy").mkdir(parents=True)
    empty = tmp_path / "mnt"; empty.mkdir()
    got = _resolve_archive_root(env_val="", candidates=[real, empty])
    assert got == real


def test_skips_empty_mount_picks_second(tmp_path):
    # 첫 후보가 존재하지만 marker 없음(빈 마운트) → 두번째(marker 있음) 선택
    empty = tmp_path / "archive"; empty.mkdir()           # 존재만, marker X
    real = tmp_path / "mnt"; (real / "tutorial").mkdir(parents=True)
    got = _resolve_archive_root(env_val="", candidates=[empty, real])
    assert got == real


def test_neither_has_marker_legacy_fallback(tmp_path):
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    got = _resolve_archive_root(env_val="", candidates=[a, b])
    assert got == Path("/mnt/ml-archive")  # legacy default


def test_any_marker_matches(tmp_path):
    # marker 3개 중 하나만 있어도 인식 (rec_adult)
    real = tmp_path / "archive"; (real / "rec_adult").mkdir(parents=True)
    got = _resolve_archive_root(env_val="", candidates=[real])
    assert got == real
