#!/usr/bin/env python3
"""데이터 경로를 받아서 파일 목록 + timestamp 범위를 자동 추출한다.

eda-intake 스킬에서 호출되어 brief 작성 전 데이터 프로파일링에 사용된다.

Dependencies:
    - pandas (선택 — 없으면 파일 size만 추출, rows/cols/timestamp 추출 불가)
    - 표준 라이브러리: argparse, json, sys, pathlib

Output (stdout, JSON):
    {
        "path": "...",
        "files": [{"name": "...", "size_mb": ..., "rows": ..., "cols": [...]}, ...],
        "period": {"start": "...", "end": "...", "days": ...} or null
    }
"""

import argparse
import json
import sys
from pathlib import Path


SUPPORTED_DATA_SUFFIXES = {".ftr", ".feather", ".parquet", ".csv", ".pkl"}
PROFILING_SUFFIXES = {".ftr", ".feather", ".parquet", ".csv"}
TIMESTAMP_KEYWORDS = ("updated_at", "created_at", "timestamp", "_ts", "_at")

# Sibling 디렉토리 카테고리 분류
SIBLING_PREPROCESSED = {"builtin", "default"}  # 기본 prep
SIBLING_RAW = {"behavior_logs"}                 # 원본 로그
SIBLING_OTHER = {"pretrain", "embeddings", "tags", "images", "models",
                 "checkpoints", "inference"}    # EDA 대상 아님


def probe_file(p: Path) -> dict:
    """단일 파일을 빠르게 프로파일링한다."""
    info = {
        "name": p.name,
        "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
        "rows": None,
        "cols": None,
        "ts_range": None,
    }

    suffix = p.suffix.lower()
    if suffix not in PROFILING_SUFFIXES:
        return info

    try:
        import pandas as pd
    except ImportError:
        info["note"] = "pandas not installed — size only"
        return info

    try:
        if suffix in {".ftr", ".feather"}:
            df = pd.read_feather(p)
        elif suffix == ".parquet":
            df = pd.read_parquet(p)
        else:
            df = pd.read_csv(p, nrows=10000)
    except Exception as e:
        info["error"] = str(e)
        return info

    info["rows"] = int(len(df))
    info["cols"] = list(df.columns)

    ts_candidates = [c for c in df.columns
                     if any(kw in c.lower() for kw in TIMESTAMP_KEYWORDS)]
    if ts_candidates:
        col = ts_candidates[0]
        try:
            series = df[col].dropna()
            if pd.api.types.is_numeric_dtype(series):
                ts = pd.to_datetime(series, unit="s", errors="coerce").dropna()
            else:
                ts = pd.to_datetime(series, errors="coerce").dropna()
            if len(ts):
                info["ts_range"] = {
                    "column": col,
                    "start": str(ts.min().date()),
                    "end": str(ts.max().date()),
                    "days": int((ts.max() - ts.min()).days),
                }
        except Exception:
            pass

    return info


def list_siblings(data_path: Path) -> dict:
    """data_path의 부모(도메인) 디렉토리에서 sibling 디렉토리를 카테고리로 분류.

    예: data_path=/archive/graph_modeling/builtin → 부모 /archive/graph_modeling 의
    builtin, exp-*, behavior_logs, pretrain 등을 분류.
    """
    parent = data_path if data_path.is_dir() else data_path.parent
    domain_dir = parent.parent  # /archive/<도메인>

    siblings = {"preprocessed": [], "raw": [], "other": []}

    if not domain_dir.exists() or not domain_dir.is_dir():
        return siblings

    for entry in sorted(domain_dir.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        full = str(entry)
        if name in SIBLING_PREPROCESSED:
            siblings["preprocessed"].append({"name": name, "path": full, "kind": "default"})
        elif name.startswith("exp-"):
            siblings["preprocessed"].append({"name": name, "path": full, "kind": "experiment"})
        elif name in SIBLING_RAW:
            siblings["raw"].append({"name": name, "path": full})
        elif name in SIBLING_OTHER:
            siblings["other"].append({"name": name, "path": full})

    return siblings


def probe_path(data_path: Path) -> dict:
    """경로 (파일 or 디렉토리)를 프로파일링 + sibling 후보 분류."""
    result = {"path": str(data_path), "files": [], "period": None, "siblings": None}

    if data_path.is_file():
        result["files"].append(probe_file(data_path))
    else:
        for p in sorted(data_path.iterdir()):
            if p.is_file() and p.suffix.lower() in SUPPORTED_DATA_SUFFIXES:
                result["files"].append(probe_file(p))

    starts, ends = [], []
    for f in result["files"]:
        if f.get("ts_range"):
            starts.append(f["ts_range"]["start"])
            ends.append(f["ts_range"]["end"])
    if starts:
        result["period"] = {"start": min(starts), "end": max(ends)}

    # Sibling 디렉토리 분류 (도메인의 다른 후보들)
    result["siblings"] = list_siblings(data_path)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="데이터 경로를 받아 파일 목록 + timestamp 범위를 JSON으로 출력한다.",
        epilog="예시: python3 probe_data.py /archive/rec_galaxy/builtin",
    )
    parser.add_argument(
        "data_path",
        help="분석할 데이터의 경로 (파일 또는 디렉토리). 디렉토리면 .ftr/.parquet/.csv/.pkl 파일만 프로파일링.",
    )
    args = parser.parse_args()

    data_path = Path(args.data_path).resolve()
    if not data_path.exists():
        print(json.dumps({"error": f"path not found: {data_path}"}, ensure_ascii=False))
        sys.exit(1)

    result = probe_path(data_path)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
