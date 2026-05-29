"""Pure-pandas KPI calculation primitives.

Carried over from remy-worker (`remy/abtest/utils.py`, `remy/abtest/names.py`).

These are standalone pandas transformations that turn raw event/log
DataFrames (rating/click/play/wish/purchase/etc.) into per
`(user_id, content, date)` aggregated rows. The output shape is the
remy-worker convention: a column `value` carrying the metric (count or sum)
and grouping keys.

Two layers of consumers:
1. Dashboard (`/api/kpi/*`) — for visible KPI tiles
2. Claude agent context — same numbers exposed as a tool/data source

Omitted from the source module (intentional):
- `adjust_virtual_user_id` family — requires MySQL chief-id lookup and
  `HashInfo.decode`. Virtual-user collapsing belongs in a dedicated module.
- `parse_analysis_config` / `parse_experiment_data` — A/B experiment model
  parsing, irrelevant to the dashboard read path.

Input schema expected:
- Raw log frames are pre-normalised to use `user_id`, `content` (string),
  `created_at` (unix seconds) or `timestamp`, plus action-specific columns
  (`exposed_count`, `total_view_time`, etc.).
- BQ adapters (`mocha/data_sources/`) are responsible for column renaming
  so these functions stay decoupled from the underlying store.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


# ── column name constants ───────────────────────────────────────────────
RESPONSE_ID_COL = "response_id"
USER_COL = "user_id"
VIRTUAL_USER_COL = "virtual_user_id"
CONTENT_COL = "content"
VALUE_COL = "value"
ACTION_COL = "action_type"
DATE_COL = "date"
GROUP_COL = "group"
RENTAL_PRICE_COL = "rental_price"
POSSESSION_PRICE_COL = "possession_price"
TIMESTAMP_COL = "timestamp"
CREATED_AT_COL = "created_at"


# ── low-level helpers ───────────────────────────────────────────────────
def _add_date_from_timestamp(df: pd.DataFrame, timestamp_col: str) -> pd.DataFrame:
    """Add a `date` column derived from a unix-second timestamp column."""
    return df.assign(date=pd.to_datetime(df[timestamp_col], unit="s").dt.date)


def _unique_count(df: pd.DataFrame, groupby_cols: list[str]) -> pd.DataFrame:
    """Deduplicate by `groupby_cols` (keeping last) then count.

    Used for rating / wish where repeated user-content actions should
    collapse to 1.
    """
    return (
        df.drop_duplicates(subset=groupby_cols, keep="last")
        .groupby(groupby_cols)
        .count()
        .reset_index()
    )


def _groupby(
    df: pd.DataFrame,
    groupby_cols: list[str],
    agg: str = "count",
    new_col: str = VALUE_COL,
    target_col: Optional[str] = None,
) -> pd.DataFrame:
    """Group-by + aggregate, emitting `[*groupby_cols, value]`.

    - `agg="count"` / `"size"` → injects a constant `1` column and counts.
    - `agg="sum"` / `"mean"` → operates on `target_col` (required).
    """
    if new_col not in df.columns:
        if agg in ("count", "size"):
            df = df.assign(**{new_col: 1})
        elif target_col and agg in ("sum", "mean"):
            df = df.assign(**{new_col: df[target_col]})
        else:
            raise ValueError(f"Unsupported agg without target_col: {agg}")

    result = df.groupby(groupby_cols).agg(agg).reset_index()
    return result[groupby_cols + [new_col]]


# ── action-specific processors ──────────────────────────────────────────
def process_unique_users_data(unique_users: pd.DataFrame) -> pd.DataFrame:
    """Tag rows with a `group` label.

    Source mapped a UserGroup enum to its name; here we accept any int /
    string and pass through. Caller can supply its own mapping dict.
    """
    if "group" in unique_users.columns:
        unique_users = unique_users.assign(**{GROUP_COL: unique_users["group"].astype(str)})
    return unique_users


def process_play_count_data(play_logs: pd.DataFrame) -> pd.DataFrame:
    """Distinct play counts per `(user, content, date)`."""
    play_logs = _add_date_from_timestamp(play_logs, CREATED_AT_COL)
    return _groupby(play_logs, [USER_COL, CONTENT_COL, DATE_COL])


def process_play_time_data(play_logs: pd.DataFrame) -> pd.DataFrame:
    """Sum of `total_view_time` (seconds) per `(user, content, date)`."""
    play_logs = _add_date_from_timestamp(play_logs, TIMESTAMP_COL)
    return _groupby(
        play_logs,
        [USER_COL, CONTENT_COL, DATE_COL],
        agg="sum",
        target_col="total_view_time",
    )


def process_impression_data(impression_logs: pd.DataFrame) -> pd.DataFrame:
    """Sum of `exposed_count` per `(user, content, date, response_id)`."""
    impression_logs = impression_logs.rename(columns={"exposed_count": VALUE_COL})
    return _groupby(impression_logs, [USER_COL, CONTENT_COL, DATE_COL, RESPONSE_ID_COL])


def process_purchase_data(purchase_logs: pd.DataFrame) -> pd.DataFrame:
    """Total purchase events per `(user, content, date, action_type)`."""
    purchase_logs = _add_date_from_timestamp(purchase_logs, CREATED_AT_COL)
    return _groupby(purchase_logs, [USER_COL, CONTENT_COL, DATE_COL, ACTION_COL])


def process_rental_data(purchase_logs: pd.DataFrame) -> pd.DataFrame:
    """Rental-only subset of purchase events."""
    purchase_logs = purchase_logs[purchase_logs[ACTION_COL] == "rental"]
    purchase_logs = _add_date_from_timestamp(purchase_logs, CREATED_AT_COL)
    return _groupby(purchase_logs, [USER_COL, CONTENT_COL, DATE_COL, ACTION_COL])


def process_possession_data(purchase_logs: pd.DataFrame) -> pd.DataFrame:
    """Possession-only subset of purchase events."""
    purchase_logs = purchase_logs[purchase_logs[ACTION_COL] == "possession"]
    purchase_logs = _add_date_from_timestamp(purchase_logs, CREATED_AT_COL)
    return _groupby(purchase_logs, [USER_COL, CONTENT_COL, DATE_COL, ACTION_COL])


def process_content_price_data(content_prices: pd.DataFrame) -> pd.DataFrame:
    """Rename source `c` → `content`, keep price columns."""
    return content_prices.rename(columns={"c": CONTENT_COL})[
        [CONTENT_COL, RENTAL_PRICE_COL, POSSESSION_PRICE_COL]
    ]


def process_click_data(click_logs: pd.DataFrame) -> pd.DataFrame:
    """Click event count per `(user, content, date, action='click')`."""
    click_logs = click_logs.assign(**{ACTION_COL: "click"})
    click_logs = _add_date_from_timestamp(click_logs, CREATED_AT_COL)
    return _groupby(click_logs, [USER_COL, CONTENT_COL, DATE_COL, ACTION_COL])


def process_rating_data(rating_logs: pd.DataFrame) -> pd.DataFrame:
    """Rating count per `(user, content, date)` with dedup.

    Repeated rating of the same content by the same user on the same date
    collapses to 1 (unlike click/search/play which double-count).
    """
    groupby_cols = [USER_COL, CONTENT_COL, DATE_COL, ACTION_COL]
    rating_logs = rating_logs.assign(**{ACTION_COL: "rating"})
    rating_logs = _add_date_from_timestamp(rating_logs, CREATED_AT_COL)
    rating_logs = _unique_count(rating_logs, groupby_cols)
    return _groupby(rating_logs, groupby_cols)


def process_search_data(search_logs: pd.DataFrame) -> pd.DataFrame:
    """Search event count per `(user, content, date, action='search')`."""
    search_logs = search_logs.assign(**{ACTION_COL: "search"})
    search_logs = _add_date_from_timestamp(search_logs, CREATED_AT_COL)
    return _groupby(search_logs, [USER_COL, CONTENT_COL, DATE_COL, ACTION_COL])


def process_visit_data(visit_logs: pd.DataFrame) -> pd.DataFrame:
    """Visit event count per `(user, date, action='visit')`.

    Note: no content dimension — visits are page-level.
    """
    visit_logs = visit_logs.assign(**{ACTION_COL: "visit"})
    visit_logs = _add_date_from_timestamp(visit_logs, CREATED_AT_COL)
    return _groupby(visit_logs, [USER_COL, DATE_COL, ACTION_COL])


def process_wish_data(wish_logs: pd.DataFrame) -> pd.DataFrame:
    """Wish (보고싶어요) count per `(user, content, date)` with dedup."""
    groupby_cols = [USER_COL, CONTENT_COL, DATE_COL, ACTION_COL]
    wish_logs = wish_logs.assign(**{ACTION_COL: "wish"})
    wish_logs = _add_date_from_timestamp(wish_logs, CREATED_AT_COL)
    wish_logs = _unique_count(wish_logs, groupby_cols)
    return _groupby(wish_logs, groupby_cols)


__all__ = [
    # constants
    "RESPONSE_ID_COL", "USER_COL", "VIRTUAL_USER_COL", "CONTENT_COL",
    "VALUE_COL", "ACTION_COL", "DATE_COL", "GROUP_COL",
    "RENTAL_PRICE_COL", "POSSESSION_PRICE_COL", "TIMESTAMP_COL", "CREATED_AT_COL",
    # processors
    "process_unique_users_data",
    "process_play_count_data", "process_play_time_data",
    "process_impression_data",
    "process_purchase_data", "process_rental_data", "process_possession_data",
    "process_content_price_data",
    "process_click_data", "process_rating_data",
    "process_search_data", "process_visit_data", "process_wish_data",
]
