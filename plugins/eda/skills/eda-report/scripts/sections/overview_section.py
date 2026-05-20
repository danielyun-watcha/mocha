"""§데이터 개요 — 단순 메타 통계 표만.

분석 결과(시간 분포 / 꼬리 / 시간대 / value 등)는 § 주요 인사이트로 분리.
"""
from pathlib import Path

from ._common import fmt_int, fmt_pct, md_table


def render(results: dict, figures_dir: Path | None = None) -> str:
    """§데이터 개요 — 메타 통계 표 하나만 (Watcha 스타일)."""
    ov = results.get("overview", {})
    meta = results.get("_meta", {})
    ct = results.get("content_type", {})

    if not ov and not meta:
        return ""

    lines = ["## 📅 데이터 개요", ""]

    rows = []
    # 수집 기간 첫 행
    period_start = meta.get("period_start")
    period_end = meta.get("period_end")
    n_days = meta.get("n_days")
    if period_start and period_end:
        n_days_part = f" ({n_days}일)" if n_days else ""
        rows.append(["**수집 기간**", f"{period_start} ~ {period_end}{n_days_part}"])

    if "n_users" in ov:
        rows.append(["고유 유저", fmt_int(ov["n_users"])])
    if "n_contents" in ov:
        rows.append(["고유 콘텐츠", fmt_int(ov["n_contents"])])
    if "n_rows" in ov:
        rows.append(["총 인터랙션", fmt_int(ov["n_rows"])])
    if "avg_per_user" in ov:
        rows.append(["유저당 평균 인터랙션", f"{ov['avg_per_user']:.1f}건"])
    if "sparsity_pct" in ov:
        rows.append(["Sparsity", fmt_pct(ov["sparsity_pct"], digits=3)])
    if ct:
        series_pct = ct.get("Series_pct")
        movie_pct = ct.get("Movie_pct")
        if series_pct is not None and movie_pct is not None:
            rows.append(["콘텐츠 타입 비율", f"Series {series_pct:.1f}% / Movie {movie_pct:.1f}%"])

    if rows:
        lines.append(md_table(["항목", "값"], rows))
        lines.append("")

    return "\n".join(lines)
