"""eda-overview analysis modules.

Each module exposes a `run(df, info, ts) -> dict` function returning
the JSON keys for its section.
"""

from . import overview, temporal, tail, content, value_dist, quality

__all__ = ["overview", "temporal", "tail", "content", "value_dist", "quality"]
