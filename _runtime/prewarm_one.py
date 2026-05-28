"""30-day KPI prewarm for a single domain — runs as detached subprocess.

Usage: python prewarm_one.py <domain> <start_iso> <end_iso>
Writes result into kpi_summary_cache (Postgres). Main mocha process picks it
up on next cache read.
"""
import asyncio
import json
import os
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kpi as kpi_mod  # noqa: E402


async def main() -> None:
    if len(sys.argv) != 4:
        print("usage: prewarm_one.py <domain> <start> <end>", file=sys.stderr)
        sys.exit(2)
    domain = sys.argv[1]
    start_d = _date.fromisoformat(sys.argv[2])
    end_d = _date.fromisoformat(sys.argv[3])

    summary = kpi_mod.summary(domain, start_d, end_d, None, None)
    series = kpi_mod.series_response(domain, start_d, end_d)

    import asyncpg
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=1)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO kpi_summary_cache(domain, start_date, end_date, content_types, "
            "summary_json, series_json) VALUES($1,$2,$3,'',$4::jsonb,$5::jsonb) "
            "ON CONFLICT (domain, start_date, end_date, content_types) DO UPDATE "
            "SET summary_json=EXCLUDED.summary_json, series_json=EXCLUDED.series_json, "
            "created_at=now()",
            domain, start_d, end_d,
            json.dumps(summary, default=str),
            json.dumps(series, default=str) if series else None,
        )
    await pool.close()
    print(f"[prewarm-sp] {domain} {start_d}~{end_d} done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
