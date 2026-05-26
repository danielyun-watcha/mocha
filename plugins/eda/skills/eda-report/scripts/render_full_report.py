#!/usr/bin/env python3
"""eda-report 풀 모드 — analysis_results.json + figures → Korean MD."""
import argparse
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from sections import header, criteria, overview_section, insights, appendix, tldr, distributions, cross_analysis, deep_insight
from sections._inspector_loader import load_inspect_results


def _try_load_inspect(results: dict) -> dict | None:
    """공통 loader 호출 — _inspector_loader.py 참고."""
    return load_inspect_results(results, SKILL_DIR, strict=False)


def main():
    parser = argparse.ArgumentParser(description="Render full EDA report (Korean MD).")
    parser.add_argument("results_json", help="analysis_results.json 경로")
    parser.add_argument("--figures-dir", default=None, help="figures PNG 디렉토리")
    parser.add_argument("--out", default="./EDA_REPORT.md", help="출력 MD 경로")
    args = parser.parse_args()

    results = json.loads(Path(args.results_json).read_text())
    figures_dir = Path(args.figures_dir).resolve() if args.figures_dir else None

    meta = results.get("_meta", {})
    inspect_report = _try_load_inspect(results)

    # 분석 결과 = 분포 + cross-tab. 깊이 해석은 deep_insight (LLM)에서 통합.
    distributions_body = distributions.render(results, figures_dir)
    cross_body = cross_analysis.render(results)
    main_blocks = [b for b in (distributions_body, cross_body) if b]
    full_insights = "## 📈 분석 결과\n\n" + "\n".join(main_blocks) if main_blocks else ""

    sections_md = [
        header.render(meta, mode="full"),
        tldr.render(results, inspect_report),
        overview_section.render(results, figures_dir),  # 메타 통계만
        criteria.render(meta),
        "---",
        full_insights,         # deterministic — 분포 + cross-tab + 기본 인사이트
        deep_insight.render(), # LLM placeholder — 오케스트레이터가 채움
        appendix.render(results),
    ]

    doc = "\n\n".join([s for s in sections_md if s.strip()])

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc + "\n")

    print(f"✅ Saved: {out_path}")
    print(f"   Sections rendered: {sum(1 for s in sections_md if s.strip())}/6")
    print(f"   Length: {len(doc):,} chars, {doc.count(chr(10)) + 1} lines")
    if inspect_report:
        s = inspect_report["summary"]
        print(f"   Inspect: {inspect_report['completeness_score']:.2f} completeness · "
              f"{s['n_strong']} strong / {s['n_notable']} notable findings")


if __name__ == "__main__":
    main()
