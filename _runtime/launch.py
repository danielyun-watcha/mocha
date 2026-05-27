"""Mocha local launcher.

Postgres 백엔드:
- DATABASE_URL env 가 있으면 외부 PG 사용 (RDS / Cloud SQL).
- 없으면 embedded pgserver 자동 기동 (dev/local 기본).
"""
import os
import sys
from pathlib import Path


def _main() -> None:
    runtime = Path(__file__).parent

    # External PG path: DATABASE_URL 이 미리 set 이면 그것을 그대로 사용.
    if not os.environ.get("DATABASE_URL"):
        # Embedded pgserver — local dev 기본.
        import pgserver
        pgdata = runtime / "pgdata"
        pgdata.mkdir(parents=True, exist_ok=True)

        srv = pgserver.get_server(str(pgdata), cleanup_mode=None)
        base_uri = srv.get_uri()
        db_uri = base_uri.replace("/postgres?", "/mocha?", 1)

        check = srv.psql("SELECT 1 FROM pg_database WHERE datname='mocha'")
        if "(1 row)" not in check:
            srv.psql("CREATE DATABASE mocha")

        os.environ["DATABASE_URL"] = db_uri
        print(f"[launcher] embedded postgres unix-socket: {pgdata}")
    else:
        print(f"[launcher] using external DATABASE_URL (pgserver bypassed)")
    os.environ.setdefault("PORT", os.environ.get("DEV_PORT", "8090"))

    # Mask password in displayed URL.
    db_display = os.environ["DATABASE_URL"]
    if "@" in db_display and "://" in db_display:
        scheme, rest = db_display.split("://", 1)
        if "@" in rest:
            cred, hostpart = rest.split("@", 1)
            if ":" in cred:
                user, _ = cred.split(":", 1)
                db_display = f"{scheme}://{user}:***@{hostpart}"
    print(f"[launcher] DATABASE_URL={db_display}")
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
    # MOCHA_RELOAD=1 to enable hot reload (dev only). Default OFF for demo stability
    # — reload watcher kills in-flight SSE streams and can hang on long agent calls.
    reload = os.environ.get("MOCHA_RELOAD", "0") == "1"
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ["PORT"]),
        reload=reload,
        reload_dirs=[str(mocha_dir)] if reload else None,
        reload_includes=["*.py", "*.html", "*.js", "*.css", "*.svg"] if reload else None,
        reload_excludes=["_runtime/server.log", "_runtime/pgdata/*", "_runtime/*.feather"] if reload else None,
        log_level="info",
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    _main()
