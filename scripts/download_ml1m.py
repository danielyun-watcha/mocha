#!/usr/bin/env python3
"""MovieLens 1M 다운로드 + EDA 스킬 호환 스키마로 변환.

출력:
    mocha/data/rating_prediction/ml-1m/ratings.ftr
        columns: user_id (int), content (str "1:{MovieID}"),
                 value (float, 1~5), content_type (int, =1),
                 updated_at (int unix UTC — 스킬이 +9h KST 보정)
    mocha/data/rating_prediction/ml-1m/movies.parquet
        columns: movie_id, content, title, year, genres

도메인 감지: 경로에 'rating_prediction' 포함 → key_metric='rate' 자동 매핑.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import pandas as pd

# 워크스페이스 egress 제한으로 files.grouplens.org 차단됨 → GitHub mirror 사용.
MIRROR = "https://raw.githubusercontent.com/ChicagoBoothML/DATA___MovieLens___1M/master"
FILES = ["ratings.dat", "movies.dat"]
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "rating_prediction" / "ml-1m"
RAW_DIR = REPO_ROOT / "data" / "_raw" / "ml-1m"


def download() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        dst = RAW_DIR / name
        if dst.exists() and dst.stat().st_size > 0:
            print(f"[skip] {name} already downloaded ({dst.stat().st_size/1e6:.1f} MB)")
            continue
        url = f"{MIRROR}/{name}"
        print(f"[download] {url}")
        with urllib.request.urlopen(url, timeout=60) as r:
            dst.write_bytes(r.read())
        print(f"[ok] {dst} ({dst.stat().st_size/1e6:.1f} MB)")
    return RAW_DIR


def convert_ratings(raw: Path) -> pd.DataFrame:
    # ratings.dat: UserID::MovieID::Rating::Timestamp
    df = pd.read_csv(
        raw / "ratings.dat",
        sep="::",
        engine="python",
        names=["user_id", "movie_id", "value", "updated_at"],
        encoding="latin-1",
    )
    df["content"] = "1:" + df["movie_id"].astype(str)
    df["content_type"] = 1  # all movies
    df["value"] = df["value"].astype("float32")
    df["user_id"] = df["user_id"].astype("int32")
    df["updated_at"] = df["updated_at"].astype("int64")  # unix UTC
    out = df[["user_id", "content", "value", "content_type", "updated_at"]]
    return out


def convert_movies(raw: Path) -> pd.DataFrame:
    # movies.dat: MovieID::Title (with year)::Genres
    df = pd.read_csv(
        raw / "movies.dat",
        sep="::",
        engine="python",
        names=["movie_id", "title_year", "genres"],
        encoding="latin-1",
    )
    df["year"] = df["title_year"].str.extract(r"\((\d{4})\)").astype("Int64")
    df["title"] = df["title_year"].str.replace(r"\s*\(\d{4}\)\s*$", "", regex=True)
    df["content"] = "1:" + df["movie_id"].astype(str)
    return df[["movie_id", "content", "title", "year", "genres"]]


def main() -> int:
    raw = download()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ratings = convert_ratings(raw)
    ratings_out = OUT_DIR / "ratings.ftr"
    ratings.reset_index(drop=True).to_feather(ratings_out)
    print(f"[ok] {ratings_out} ({len(ratings):,} rows, {ratings_out.stat().st_size/1e6:.1f} MB)")

    movies = convert_movies(raw)
    movies_out = OUT_DIR / "movies.parquet"
    movies.to_parquet(movies_out, index=False)
    print(f"[ok] {movies_out} ({len(movies):,} rows)")

    # 검증 요약
    print("\n--- ratings preview ---")
    print(ratings.head(3).to_string(index=False))
    print(f"\nperiod (UTC unix): {ratings['updated_at'].min()} ~ {ratings['updated_at'].max()}")
    print(f"period (KST):      "
          f"{pd.to_datetime(ratings['updated_at'].min(), unit='s') + pd.Timedelta(hours=9)} ~ "
          f"{pd.to_datetime(ratings['updated_at'].max(), unit='s') + pd.Timedelta(hours=9)}")
    print(f"\nNext: python3 plugins/eda/skills/eda-overview/scripts/run.py {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
