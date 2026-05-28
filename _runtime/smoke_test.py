"""Mocha smoke test — 4 demo queries 회귀 검증.

Usage:  python _runtime/smoke_test.py [base_url]
        base_url default = http://localhost:8090

Auth: env MOCHA_AUTH_USER + MOCHA_AUTH_PASS 가 있으면 그 값으로 Basic auth header
      자동 첨부. /health 는 auth 제외이므로 무관.
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request


# (query, expected_chart_name) — answer must inline a chart whose filename
# matches `<expected_chart_name>.png` (PIcked by `_pick_chart` based on intent).
DEMO_QUERIES: list[tuple[str, str]] = [
    ("🎬 Mars 최근 30일 인기 장르 차트로 보여줘", "top_genres"),
    ("💰 성인관 최다 결제 유저는?",            "top_payers"),
    ("⭐ 피디아 평점 높은 영화 TOP 10",        "top_rated_contents"),
    ("🎥 왓챠 인기 감독 TOP 5 그래프로",       "top_directors"),
]


def _auth_header() -> dict[str, str]:
    u = os.environ.get("MOCHA_AUTH_USER")
    p = os.environ.get("MOCHA_AUTH_PASS")
    if u and p:
        token = base64.b64encode(f"{u}:{p}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    return {}


def _post(url: str, body: dict, timeout: int = 60) -> bytes:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **_auth_header()},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get(url: str, timeout: int = 5) -> bytes:
    req = urllib.request.Request(url, headers=_auth_header())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _parse_sse(raw: bytes) -> tuple[str, dict]:
    """Returns (concatenated answer text, last 'done' event dict)."""
    texts: list[str] = []
    done: dict = {}
    for m in re.finditer(rb"data: (\{[^\n]+\})", raw):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        if d.get("type") == "text":
            texts.append(d.get("text", ""))
        elif d.get("type") == "done":
            done = d
    return "".join(texts), done


def run(base: str = "http://localhost:8090") -> int:
    print(f"=== MOCHA smoke test against {base} ===")
    # 1) health
    try:
        h = json.loads(_get(f"{base}/health", 3))
        assert h.get("status") == "ok"
        print(f"  ✅ /health: {h}")
    except Exception as e:
        print(f"  ❌ /health failed: {e}")
        return 1

    fails = 0
    for i, (q, expected_chart) in enumerate(DEMO_QUERIES, 1):
        try:
            sess = json.loads(_post(f"{base}/api/sessions", {"title": f"smoke-{i}"}))
            t0 = time.time()
            raw = _post(f"{base}/api/sessions/{sess['id']}/chat", {"message": q}, timeout=60)
            dur = time.time() - t0
            ans, done = _parse_sse(raw)
            # extract inlined chart filename(s) — `![](/eda-files/sess_XX/<name>.png)`
            inlined_charts = re.findall(r"/eda-files/sess_\d+/([A-Za-z_]+)\.png", ans)
            has_chart = bool(inlined_charts)
            correct_chart = expected_chart in inlined_charts
            has_basis = "집계 기준" in ans
            has_source = "데이터 소스" in ans
            insight_n = ans.count("✅")
            ok = (has_chart and correct_chart and has_basis and has_source
                  and 2 <= insight_n <= 4)
            mark = "✅" if ok else "❌"
            picked = inlined_charts[0] if inlined_charts else "<none>"
            chart_status = "✓" if correct_chart else f"✗ (got {picked}, want {expected_chart})"
            print(f"  {mark} [{dur:5.1f}s] chart={chart_status} 기준={has_basis} "
                  f"소스={has_source} insights={insight_n}  Q: {q[:30]}…")
            if not ok:
                fails += 1
        except Exception as e:
            print(f"  ❌ [error] {q[0][:40]}: {e}" if isinstance(q, tuple) else f"  ❌ [error] {q[:40]}: {e}")
            fails += 1

    print()
    if fails == 0:
        print("✅ All checks passed.")
        return 0
    print(f"❌ {fails}/{len(DEMO_QUERIES)} demo queries failed.")
    return 1


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8090"
    sys.exit(run(base))
