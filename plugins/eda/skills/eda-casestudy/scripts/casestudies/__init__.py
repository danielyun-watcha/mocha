"""eda-casestudy domain modules.

Each module exposes `run(df, info, top_n) -> {case_studies, analysis_suggestions}`.
"""

from . import mars, galaxy, adult, negative

__all__ = ["mars", "galaxy", "adult", "negative"]
