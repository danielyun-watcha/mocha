"""Common helpers — number formatting, table builders."""
from pathlib import Path
from typing import Any


def fmt_int(n: int | float | None) -> str:
    """1234567 → '1,234,567'. None → '-'."""
    if n is None:
        return "-"
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)


def fmt_compact(n: int | float | None) -> str:
    """142_000 → '142K', 2_300_000 → '2.33M'."""
    if n is None:
        return "-"
    n = float(n)
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if abs(n) >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:.0f}"


def fmt_pct(p: float | None, digits: int = 1) -> str:
    """0.157 → '15.7%'. p가 0-100 스케일이면 그대로."""
    if p is None:
        return "-"
    p = float(p)
    if abs(p) <= 1.0:
        p *= 100
    return f"{p:.{digits}f}%"


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    """헤더 + 행 → 마크다운 표."""
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    body_lines = []
    for row in rows:
        body_lines.append("| " + " | ".join(str(c) if c is not None else "-" for c in row) + " |")
    return "\n".join([head, sep] + body_lines)


def find_figure(figures_dir: Path | None, prefix: str) -> Path | None:
    """figures 디렉토리에서 prefix로 시작하는 PNG 찾기. 없으면 None."""
    if figures_dir is None or not figures_dir.exists():
        return None
    matches = sorted(figures_dir.glob(f"{prefix}*.png"))
    return matches[0] if matches else None


def find_figure_by_name(figures_dir: Path | None, name_part: str) -> Path | None:
    """파일명에 name_part 포함된 PNG 찾기 (예: peak_hours)."""
    if figures_dir is None or not figures_dir.exists():
        return None
    matches = sorted(figures_dir.glob(f"*{name_part}*.png"))
    return matches[0] if matches else None


def img_embed(rel_path: Path | None, alt: str) -> str:
    """MD 이미지 임베드. None이면 빈 문자열."""
    if rel_path is None:
        return ""
    return f"![{alt}]({rel_path})"
