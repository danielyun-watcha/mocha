#!/usr/bin/env python3
"""eda-casestudy 진입점."""
import argparse
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from casestudies import mars, galaxy, adult, negative
from casestudies._common import (
    detect_domain_group, load_main, load_or_create_results, save_results,
)


DOMAIN_MODULES = {
    "mars": mars.run,
    "galaxy": galaxy.run,
    "adult": adult.run,
    "negative": negative.run,
}


def main():
    parser = argparse.ArgumentParser(description="Extract case studies for Appendix.")
    parser.add_argument("data_path", help="데이터 경로")
    parser.add_argument("--brief", default=None)
    parser.add_argument("--out", default="./analysis_results.json")
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()

    data_path = Path(args.data_path).resolve()
    if not data_path.exists():
        print(f"❌ Path not found: {data_path}")
        sys.exit(1)

    domain_group = detect_domain_group(data_path)
    print(f"Domain group: {domain_group}")

    if domain_group == "unknown" or domain_group not in DOMAIN_MODULES:
        print(f"❌ Unsupported domain. Supported: {list(DOMAIN_MODULES.keys())}")
        sys.exit(1)

    df, main_file = load_main(data_path, domain_group)
    print(f"Loaded {main_file}: {len(df):,} rows")

    # 모듈 호출
    result = DOMAIN_MODULES[domain_group](df, data_path, top_n=args.top_n)

    # 기존 results와 병합
    out_path = Path(args.out)
    results = load_or_create_results(out_path, args.append)

    if "case_studies" in result:
        existing_cs = results.get("case_studies", {})
        existing_cs.update(result["case_studies"])
        results["case_studies"] = existing_cs

    if "analysis_suggestions" in result:
        existing_sg = results.get("analysis_suggestions", [])
        existing_sg.extend(result["analysis_suggestions"])
        results["analysis_suggestions"] = existing_sg

    save_results(results, out_path)

    cs = result.get("case_studies", {})
    sg = result.get("analysis_suggestions", [])
    print(f"\n✅ Saved to {out_path}")
    print(f"   case_studies: {list(cs.keys())}")
    print(f"   analysis_suggestions: {len(sg)} items")
    for s in sg[:3]:
        print(f"     - {s}")


if __name__ == "__main__":
    main()
