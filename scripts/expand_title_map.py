"""Expand content_titles_ko.pkl with ALL unique content_ids in archive.

- existing pickle: only top-3000 / file → ~7903 entries, books mostly missing
- this script: pulls every unique content_id in /archive/*/behavior_logs*/*.ftr
  (most recent 3 files per domain) and batch-resolves titles from MySQL.

Run once before demo. Safe to re-run — only fetches missing ids.
"""

import os
import pickle
import sys
from pathlib import Path

import pandas as pd

os.environ.setdefault("REMY_ENV", "dev")
sys.path.insert(0, "/home/jupyterhub/jupyter/daniel/remy-worker")

from remy import Remy
from remy.core.datatypes.basic import Content, ContentType, CountryCode
from remy.ds.mysql.content import ContentComponent


def _parse(cid: str) -> Content | None:
    if not cid or ":" not in cid:
        return None
    ct_str, id_str = cid.split(":", 1)
    try:
        return Content(ContentType(int(ct_str)), int(id_str))
    except (ValueError, KeyError):
        return None

# Path 는 mocha 디렉토리 (scripts/ 의 상위) 기준 — clone 위치 무관하게 작동.
OUT = Path(__file__).resolve().parent.parent / "_runtime" / "content_titles_ko.pkl"
ARCHIVE_DIRS = [
    Path("/archive/rec_galaxy/behavior_logs"),
    Path("/archive/user_bert/behavior_logs2/train"),
    Path("/archive/rec_adult/behavior_logs"),
]
RECENT_FILES_PER_DIR = 3
BATCH = 4000


def main() -> None:
    Remy.bootstrap()

    title_map: dict[str, str] = {}
    if OUT.exists():
        title_map = pickle.loads(OUT.read_bytes())
    print(f"[existing] {len(title_map)} titles")

    ids: set[str] = set()
    for d in ARCHIVE_DIRS:
        if not d.exists():
            print(f"  skip (missing dir): {d}")
            continue
        files = sorted(d.glob("*.ftr"))[-RECENT_FILES_PER_DIR:]
        for f in files:
            try:
                df = pd.read_feather(f, columns=["content"])
            except Exception as exc:
                print(f"  warn read {f}: {exc}")
                continue
            uniq = df["content"].astype(str).dropna().unique().tolist()
            ids.update(uniq)
            print(f"  + {f.name}: {len(uniq)} unique (cum {len(ids)})")

    missing = sorted(c for c in ids if c and c not in title_map)
    print(f"[missing] {len(missing)} ids to fetch (skip {len(ids) - len(missing)} already cached)")

    if not missing:
        print("done — nothing to fetch")
        return

    fetched = 0
    for i in range(0, len(missing), BATCH):
        chunk = missing[i : i + BATCH]
        try:
            contents = {c for c in (_parse(x) for x in chunk) if c is not None}
            if not contents:
                continue
            df_t = ContentComponent.get_titles(
                contents, CountryCode.KOREA, columns=["content", "title"]
            )
        except Exception as exc:
            print(f"  batch {i // BATCH} failed: {exc}")
            continue
        new_map = dict(
            zip(df_t["content"].astype(str).tolist(),
                df_t["title"].astype(str).tolist(),
                strict=False)
        )
        title_map.update(new_map)
        fetched += len(new_map)
        print(f"  batch {i // BATCH}: +{len(new_map)} (total {len(title_map)})")

    # Books (content_type=4) are in `books` table, NOT in `translations`.
    book_ids = sorted({int(c.split(":")[1]) for c in missing if c.startswith("4:") and c.split(":")[1].isdigit()})
    book_ids = [b for b in book_ids if f"4:{b}" not in title_map or not title_map[f"4:{b}"]]
    if book_ids:
        from remy.shared_infra import SharedInfra

        gns = SharedInfra().db_gns
        book_fetched = 0
        with gns.get_conn() as conn:
            for i in range(0, len(book_ids), 5000):
                chunk = book_ids[i : i + 5000]
                placeholders = ",".join(["%s"] * len(chunk))
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT id, title FROM books WHERE id IN ({placeholders})", chunk
                    )
                    rows = cur.fetchall()
                for bid, title in rows:
                    if title:
                        title_map[f"4:{bid}"] = title
                        book_fetched += 1
                print(f"  book batch {i // 5000}: +{len(rows)} (total books {book_fetched})")
        print(f"[books] +{book_fetched}")

    OUT.write_bytes(pickle.dumps(title_map))
    print(f"[saved] {OUT} — total {len(title_map)} (fetched {fetched})")


if __name__ == "__main__":
    main()
