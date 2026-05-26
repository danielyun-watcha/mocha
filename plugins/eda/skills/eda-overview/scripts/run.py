#!/usr/bin/env python3
"""eda-overview 메인 진입점.

Usage:
    python3 run.py <data_path> [--brief brief.json] [--out analysis_results.json] [--append]
"""

import argparse
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from analyses import overview, temporal, tail, content, value_dist, quality, cross
from analyses._common import (
    detect_domain, load_main, load_or_create_results,
    save_results, detect_timestamp, build_meta,
)


def main():
    parser = argparse.ArgumentParser(
        description="Generate overview EDA section of analysis_results.json"
    )
    parser.add_argument("data_path", help="데이터 디렉토리 경로")
    parser.add_argument("--brief", default=None,
                        help="eda-intake가 생성한 analysis_brief.json (옵션)")
    parser.add_argument("--out", default="./analysis_results.json",
                        help="결과 저장 경로 (기본: ./analysis_results.json)")
    parser.add_argument("--append", action="store_true",
                        help="기존 파일의 다른 키는 보존하고 이 스킬 섹션만 덮어쓰기")
    args = parser.parse_args()

    data_path = Path(args.data_path).resolve()
    if not data_path.exists():
        print(f"❌ Path not found: {data_path}")
        sys.exit(1)

    # 1. 도메인 감지
    info = detect_domain(data_path)
    print(f"Domain: {info['domain']} / Main file: {info['main_file']}")

    if info["main_file"] is None:
        print(f"❌ No main data file found in {data_path}")
        sys.exit(1)

    # 2. 데이터 로드
    df = load_main(data_path, info)
    print(f"Loaded {len(df):,} rows, {df.shape[1]} columns")

    # 3. timestamp 감지
    ts = detect_timestamp(df, info)
    if ts is not None:
        print(f"Timestamp range: {ts.dropna().min()} ~ {ts.dropna().max()}")

    # 4. brief.json 로드 (옵션)
    brief = None
    if args.brief:
        brief_path = Path(args.brief)
        if brief_path.exists():
            brief = json.loads(brief_path.read_text())
            print(f"Brief loaded: {brief.get('goal', '')[:60]}")

    # 5. 분석 모듈 실행
    out_path = Path(args.out)
    results = load_or_create_results(out_path, args.append)

    # _meta 블록 — PANDA "조회 기준" + key_metric (도메인 KPI)
    results["_meta"] = build_meta(data_path, info, df, ts, brief)
    print(f"  ✓ _meta (period: {results['_meta'].get('period_start', '?')} ~ {results['_meta'].get('period_end', '?')}, "
          f"key_metric: {results['_meta'].get('key_metric')})")

    sections = [
        ("overview", overview.run),
        ("temporal", temporal.run),
        ("tail", tail.run),
        ("content", content.run),
        ("value_dist", value_dist.run),
        ("quality", quality.run),
        ("cross", cross.run),  # cross-tab: content_type × value, 시간대 × type, segment
    ]

    new_keys = []
    for name, fn in sections:
        try:
            section_result = fn(df, info, ts)
        except Exception as e:
            print(f"  ⚠ {name} failed: {e}")
            continue
        for k, v in section_result.items():
            results[k] = v
            new_keys.append(k)
        print(f"  ✓ {name} ({len(section_result)} keys)")

    # 6. 저장
    save_results(results, out_path)
    print(f"\n✅ Saved to {out_path}")
    print(f"   Updated keys: {', '.join(new_keys)}")

    # 7. 핵심 발견 요약
    ov = results.get("overview", {})
    print("\nKey findings:")
    if "n_users" in ov:
        print(f"  - {ov['n_users']/1000:.0f}K users · {ov.get('n_contents', 0)/1000:.1f}K contents · "
              f"{ov['n_rows']/1_000_000:.2f}M interactions")
    if "sparsity_pct" in ov:
        print(f"  - Sparsity: {ov['sparsity_pct']:.2f}%")
    if "date_range" in ov:
        print(f"  - 기간: {ov['date_range'][0]} ~ {ov['date_range'][1]} ({ov.get('span_days')}일)")
    par = results.get("pareto_long_tail", {})
    if par:
        print(f"  - Long-tail: 상위 5% 콘텐츠 → {par.get('top5pct', 0):.1f}% 점유")
    print(f"\nNext: python3 eda-figures/scripts/render.py {out_path}")


if __name__ == "__main__":
    main()
