#!/usr/bin/env python3
"""eda-figures 메인 진입점.

analysis_results.json + theme → PPT-style PNG figures.

Usage:
    python3 render.py <analysis_results.json> [--output <dir>] [--theme <name>] [--brief <path>]

각 분석 결과 키에 대해 layout_catalog.md의 매핑 룰을 따라 layout을 선택한다.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

SKILL_DIR = Path(__file__).resolve().parent.parent


# ===== Theme parsing =====

THEME_PATTERN = re.compile(r"-\s*([A-Za-z][\w\s]*?):\s*`(#[0-9a-fA-F]{6})`")


def parse_theme(theme_name: str) -> dict:
    """themes/<name>.md → color dict."""
    p = SKILL_DIR / "themes" / f"{theme_name}.md"
    if not p.exists():
        raise FileNotFoundError(f"Theme not found: {p}")
    text = p.read_text()
    colors = {}
    for m in THEME_PATTERN.finditer(text):
        key = m.group(1).strip().lower().replace(" ", "_")
        colors[key] = m.group(2)
    return colors


# ===== Font setup =====

def setup_korean_font() -> None:
    candidates = [
        SKILL_DIR / "assets/fonts/NotoSansKR-Regular.otf",
        SKILL_DIR / "assets/fonts/malgun.ttf",
    ]
    for p in candidates:
        if p.exists():
            fm.fontManager.addfont(str(p))
            font_name = fm.FontProperties(fname=str(p)).get_name()
            plt.rcParams["font.family"] = font_name
            break

    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 120
    plt.rcParams["savefig.dpi"] = 240
    plt.rcParams["savefig.bbox"] = "tight"
    plt.rcParams.update({
        "axes.labelsize": 14,
        "axes.titlesize": 15,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12,
        "legend.fontsize": 12,
        "font.size": 13,
    })


# ===== Layout dispatch =====

def select_layout(key: str, value) -> str | None:
    """analysis_results.json 키와 값 형태를 보고 layout 결정.

    우선순위가 중요. _buckets_pct 같은 합성 suffix는 _pct(pie)보다 먼저 매칭.
    """
    # 1. overview — 표로 충분, 그림 skip
    if key == "overview" or key.endswith("_overview"):
        return None

    # 2. boxplot — 비ML 팀에 추상적, skip
    if key.endswith("_boxplot"):
        return None

    # 3. buckets (구간 분포) — _pct보다 먼저 (suffix 충돌 방지)
    if key.endswith("_buckets") or key.endswith("_buckets_pct"):
        return "bar_chart"

    # 4. 시계열
    if key in ("daily_volume", "monthly_volume", "weekly_volume") or key.endswith("_timeseries"):
        return "line_chart"

    # 5. Pareto / Lorenz — main loop에서는 skip (아래 special handler가 처리)
    if key == "pareto_long_tail" or key.startswith("pareto_"):
        return None
    if key == "lorenz" or key.endswith("_lorenz"):
        return None

    # 6. Venn
    if key.startswith("venn_") or key == "venn":
        return "venn_overlap"

    # 7. People grid
    if key.endswith("_100people") or key.endswith("_grid"):
        return "people_grid"

    # 8. Pie chart — content_type 같은 단순 2-category는 표로 충분, skip
    if key in ("content_type", "service"):
        return None
    if (key.endswith("_pct") and isinstance(value, dict)
            and 2 <= len(value) <= 5
            and all(isinstance(v, (int, float)) for v in value.values())):
        return "pie_chart"

    return None


def deduplicate_keys(keys: list, data: dict) -> set:
    """중복 의미 키는 한쪽만 처리하도록 skip 집합 반환.

    - lorenz + pareto_long_tail 동시 존재 → pareto skip
    - daily_volume + monthly_volume 동시 존재 → monthly skip (daily가 더 정밀)
    """
    skip = set()
    if "lorenz" in keys and "pareto_long_tail" in keys:
        skip.add("pareto_long_tail")
    if "daily_volume" in keys and "monthly_volume" in keys:
        skip.add("monthly_volume")
    return skip


def render_one(key: str, value, layout: str, theme: dict, output_path: Path,
               brief: dict | None) -> None:
    """단일 figure 렌더링. layout 이름에 따라 적절한 모듈 호출."""
    sys.path.insert(0, str(SKILL_DIR / "scripts"))
    from layouts import (stat_callout, pie_chart, bar_chart, boxplot,
                          line_chart, lorenz_curve, bar_box_2panel, venn_overlap, people_grid)
    module_map = {
        "stat_callout": stat_callout.render,
        "pie_chart": pie_chart.render,
        "bar_chart": bar_chart.render,
        "boxplot": boxplot.render,
        "line_chart": line_chart.render,
        "lorenz_curve": lorenz_curve.render,
        "bar_box_2panel": bar_box_2panel.render,
        "venn_overlap": venn_overlap.render,
        "people_grid": people_grid.render,
    }
    if layout not in module_map:
        print(f"  skipped (no layout for '{layout}')")
        return
    module_map[layout](key, value, theme, output_path, brief=brief)


# ===== Main =====

def main():
    parser = argparse.ArgumentParser(
        description="Generate PPT-style EDA figures from analysis results."
    )
    parser.add_argument("results_path", help="analysis_results.json")
    parser.add_argument("--output", default="./figures",
                        help="Output dir (default: ./figures)")
    parser.add_argument("--theme", default="watcha-default",
                        help="Theme name (default: watcha-default)")
    parser.add_argument("--brief", default=None,
                        help="analysis_brief.json (optional, from eda-intake)")
    args = parser.parse_args()

    setup_korean_font()
    theme = parse_theme(args.theme)
    print(f"Theme: {args.theme} ({len(theme)} colors)")

    data = json.loads(Path(args.results_path).read_text())
    brief = json.loads(Path(args.brief).read_text()) if args.brief else None

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 분석 결과의 top-level 키 순회. 두 그룹이 함께면 bar_box_2panel 우선.
    idx = 1
    keys = list(data.keys())
    skip = deduplicate_keys(keys, data)

    # bar + boxplot 2-panel 조합 우선 처리
    for key in keys:
        if key in skip:
            continue
        buckets_key = key if key.endswith("_buckets") else None
        box_key = None
        if buckets_key:
            prefix = buckets_key.replace("_buckets", "")
            box_candidate = f"{prefix}_boxplot"
            if box_candidate in data:
                box_key = box_candidate
        if buckets_key and box_key:
            output = out_dir / f"F{idx}_{buckets_key.replace('_buckets', '')}.png"
            render_one(
                buckets_key,
                {"buckets": data[buckets_key], "boxplot": data[box_key]},
                "bar_box_2panel", theme, output, brief,
            )
            print(f"  F{idx} {output.name}: bar_box_2panel  ({buckets_key} + {box_key})")
            skip.add(buckets_key)
            skip.add(box_key)
            idx += 1

    # 나머지
    for key in keys:
        if key in skip:
            continue
        value = data[key]
        layout = select_layout(key, value)
        if layout is None:
            continue
        output = out_dir / f"F{idx}_{key}.png"
        render_one(key, value, layout, theme, output, brief)
        print(f"  F{idx} {output.name}: {layout}")
        idx += 1

    # Pareto long-tail — power-law를 막대로 (lorenz 곡선 대신)
    pareto = data.get("pareto_long_tail")
    if pareto:
        chart_data = {}
        for k, v in pareto.items():
            if k.startswith("top") and k.endswith("pct") and isinstance(v, (int, float)):
                num = k.replace("top", "").replace("pct", "")
                chart_data[f"상위 {num}%"] = v
        if len(chart_data) >= 2:
            output = out_dir / f"F{idx}_pareto.png"
            render_one("pareto_long_tail_pct", chart_data, "bar_chart", theme, output, brief)
            print(f"  F{idx} {output.name}: bar_chart  (pareto power-law)")
            idx += 1

    # case_studies — 시각적으로 의미 있는 케이스만 bar chart 추가
    case_studies = data.get("case_studies", {})
    chartable = {
        "peak_hours_top10": {
            "label_key": "hour", "value_key": "n_actions",
            "label_fmt": "{}시", "fname": "peak_hours",
        },
    }
    for cs_key, spec in chartable.items():
        items = case_studies.get(cs_key)
        if not items:
            continue
        chart_data = {
            spec["label_fmt"].format(item[spec["label_key"]]): item[spec["value_key"]]
            for item in items if spec["label_key"] in item and spec["value_key"] in item
        }
        if len(chart_data) < 2:
            continue
        output = out_dir / f"F{idx}_{spec['fname']}.png"
        render_one(spec["fname"], chart_data, "bar_chart", theme, output, brief)
        print(f"  F{idx} {output.name}: bar_chart  ({cs_key})")
        idx += 1

    print(f"\nDone — {idx - 1} figures generated to {out_dir}/")


if __name__ == "__main__":
    main()
