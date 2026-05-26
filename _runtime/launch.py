"""Mocha local launcher — embedded postgres + uvicorn (reload mode)."""
import os
import sys
from pathlib import Path


def _main() -> None:
    import pgserver

    runtime = Path(__file__).parent
    pgdata = runtime / "pgdata"
    pgdata.mkdir(parents=True, exist_ok=True)

    srv = pgserver.get_server(str(pgdata), cleanup_mode=None)
    base_uri = srv.get_uri()
    # get_uri → postgresql://postgres:@/postgres?host=/...  swap db name to mocha
    db_uri = base_uri.replace("/postgres?", "/mocha?", 1)

    check = srv.psql("SELECT 1 FROM pg_database WHERE datname='mocha'")
    if "(1 row)" not in check:
        srv.psql("CREATE DATABASE mocha")

    os.environ["DATABASE_URL"] = db_uri
    os.environ.setdefault("PORT", os.environ.get("DEV_PORT", "8090"))

    print(f"[launcher] postgres unix-socket: {pgdata}")
    print(f"[launcher] DATABASE_URL={db_uri}")
    print(f"[launcher] PORT={os.environ['PORT']}")

    mocha_dir = runtime.parent
    sys.path.insert(0, str(mocha_dir))
    os.chdir(mocha_dir)

    import uvicorn

    # reload=True: main.py / kpi.py / static/* 저장 시 자동 reload.
    # uvicorn supervisor PID 유지 → port forward 끊김 X (worker 만 재시작).
    # NOTE: must run inside `if __name__ == "__main__":` guard — uvicorn
    # uses multiprocessing.spawn for the reload subprocess which re-imports
    # this module; without the guard pgserver init runs twice → conflict.
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ["PORT"]),
        reload=True,
        reload_dirs=[str(mocha_dir)],
        reload_includes=["*.py", "*.html", "*.js", "*.css", "*.svg"],
        reload_excludes=["_runtime/server.log", "_runtime/pgdata/*", "_runtime/*.feather"],
        log_level="info",
    )


if __name__ == "__main__":
    _main()
