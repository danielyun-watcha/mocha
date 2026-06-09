"""Archive root 해석 — 환경마다 다른 마운트 경로를 안전하게 픽한다.

우선순위:
  1. ARCHIVE_DIR 환경변수 (명시 지정 — 그대로 신뢰)
  2. content-marker 가 있는 후보 (/archive → /mnt/ml-archive 순)
  3. legacy fallback /mnt/ml-archive

단순 exists() 가 아니라 **marker(도메인 디렉토리)** 까지 확인하는 이유:
jupyterhub NFS 에 /mnt/ml-archive 가 raw data 없이 빈 디렉토리로 존재할 수
있고, ADP 파드에 둘 다 마운트될 수도 있다. 그 때 빈 쪽을 잘못 잡으면 archive
패널이 통째로 빈다. marker 가 있어야 '진짜 데이터가 있는' root 로 인정.
"""
from __future__ import annotations

import os
from pathlib import Path

# 진짜 archive 임을 식별하는 도메인 디렉토리 (하나만 있어도 인정)
_MARKERS = ("tutorial", "rec_galaxy", "rec_adult")
# 탐색 순서 — /archive(현재 표준) 우선, /mnt/ml-archive(legacy) 차순
_CANDIDATES = (Path("/archive"), Path("/mnt/ml-archive"))
_LEGACY_DEFAULT = Path("/mnt/ml-archive")


def _resolve_archive_root(
    env_val: str | None = None,
    candidates: list[Path] | tuple[Path, ...] | None = None,
    markers: tuple[str, ...] = _MARKERS,
) -> Path:
    """archive root 경로 결정. 인자는 테스트 주입용 (기본은 실제 env/경로).

    env_val: ARCHIVE_DIR 값. None 이면 os.environ 에서 읽음. "" 이면 미지정 취급.
    """
    if env_val is None:
        env_val = os.environ.get("ARCHIVE_DIR")
    if env_val:
        return Path(env_val)
    for c in (candidates if candidates is not None else _CANDIDATES):
        try:
            if c.exists() and any((c / m).exists() for m in markers):
                return c
        except OSError:
            continue  # 마운트 stale 등 — 다음 후보
    return _LEGACY_DEFAULT


__all__ = ["_resolve_archive_root"]
