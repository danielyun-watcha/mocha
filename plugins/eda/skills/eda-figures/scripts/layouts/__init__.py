"""eda-figures layout modules.

Each layout module exposes `render(key, value, theme, output_path, brief=None)`.
"""

from . import stat_callout, pie_chart, bar_chart, boxplot, line_chart
from . import lorenz_curve, bar_box_2panel, venn_overlap, people_grid

__all__ = [
    "stat_callout", "pie_chart", "bar_chart", "boxplot", "line_chart",
    "lorenz_curve", "bar_box_2panel", "venn_overlap", "people_grid",
]
