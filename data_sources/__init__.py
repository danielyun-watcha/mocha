"""Data source adapters — fetch raw event/log frames from upstream stores.

Adapters output pandas DataFrames in the mocha convention so that
`kpi_calc.py` can post-process them uniformly. Each adapter module is
responsible for one store:

- `bq` — BigQuery (galaxy/mars/adult production tables)
- (future) `archive` — `/archive/*` feather snapshots
- (future) `mysql` — direct MySQL (only if BQ mirror is insufficient)

Adapters never depend on `kpi_calc` or each other; they are pure I/O.
"""
