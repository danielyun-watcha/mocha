"""MOCHA 측정 하니스 — 블로그용 before/after 수치 생성.

배포 환경(asyncpg/archive/LLM 크레덴셜 有)에서 실행:
    python _runtime/bench.py [base_url] --runs 3 --deep
    python _runtime/bench.py --no-deep            # fast 만 (비용 절약)

측정 항목:
  - 결정성(determinism): 같은 질문 N회 → semantic result 블록이 동일한가 (계약의 핵심 증명)
  - 지연(latency): 첫 토큰까지 / 전체
  - 토큰: input / output / cache_read / cache_creation (prompt caching 효과)
  - 비용(cost_usd)
  - Critic: deep 답변 중 verdict fail(차단) 비율, 신뢰도 분포

출력: /tmp/mocha_bench.json (raw) + stdout 마크다운 요약표.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import urllib.request

# (질문, track, registry_covered?) — covered=True 면 result 블록이 결정적이어야 함
QUESTION_SET: list[tuple[str, str, bool]] = [
    ("🎬 Mars 최근 7일 활성 유저 수", "fast", True),
    ("💰 성인관 큰손 TOP 10", "fast", True),
    ("⭐ 피디아 평점 분포 보여줘", "fast", True),
    ("🎬 Mars 최근 7일 인기 장르", "fast", True),
    ("성인관 ARPPU 얼마야", "fast", True),
    ("rec_galaxy 데이터 전반 EDA 리포트", "deep", False),
    ("성인관 결제 패턴 분석해줘", "deep", False),
]


def _post_stream(base: str, sid: int, msg: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(
        f"{base}/api/sessions/{sid}/chat",
        data=json.dumps({"message": msg}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _new_session(base: str, title: str) -> int:
    req = urllib.request.Request(
        f"{base}/api/sessions", data=json.dumps({"title": title}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["id"]


def _parse_events(raw: bytes) -> dict:
    """SSE → {text, results:[...], verdict, usage, first_token_ms, done}."""
    out = {"text": [], "results": [], "criteria": None, "verdict": None,
           "usage": None, "first_token_ms": None, "done": False}
    for m in re.finditer(rb"data: (\{.*?\})\n\n", raw, re.DOTALL):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        t = d.get("type")
        if t == "text":
            out["text"].append(d.get("text", ""))
        elif t == "result":
            out["results"].append(d)
        elif t == "criteria":
            out["criteria"] = d.get("text")
        elif t == "verdict":
            out["verdict"] = d
        elif t == "status" and d.get("stage") == "llm_first_token":
            out["first_token_ms"] = d.get("elapsed_ms")
        elif t == "done":
            out["done"] = True
            out["usage"] = d.get("usage")
    return out


def _result_signature(results: list[dict]) -> str:
    """결정성 비교용 — result 블록의 값/행만 안정 직렬화 (라벨·순서 포함)."""
    norm = []
    for r in results:
        if r.get("kind") == "table":
            norm.append((r.get("metric"), "table", json.dumps(r.get("rows", []), sort_keys=True, ensure_ascii=False)))
        else:
            norm.append((r.get("metric"), "scalar", str(r.get("display"))))
    return json.dumps(sorted(norm), ensure_ascii=False)


def run(base: str, runs: int, include_deep: bool) -> dict:
    rows = []
    for q, track, covered in QUESTION_SET:
        if track == "deep" and not include_deep:
            continue
        per_run = []
        signatures = set()
        for i in range(runs):
            sid = _new_session(base, f"bench-{q[:12]}-{i}")
            t0 = time.time()
            try:
                raw = _post_stream(base, sid, q)
            except Exception as e:
                per_run.append({"error": str(e)})
                continue
            dt = time.time() - t0
            ev = _parse_events(raw)
            u = ev["usage"] or {}
            per_run.append({
                "total_ms": int(dt * 1000),
                "first_token_ms": ev["first_token_ms"],
                "input_tokens": u.get("input_tokens"),
                "output_tokens": u.get("output_tokens"),
                "cache_read": u.get("cache_read_input_tokens"),
                "cache_creation": u.get("cache_creation_input_tokens"),
                "verdict_pass": (ev["verdict"] or {}).get("pass"),
                "verdict_conf": (ev["verdict"] or {}).get("confidence"),
                "n_results": len(ev["results"]),
            })
            if covered:
                signatures.add(_result_signature(ev["results"]))
        ok = [r for r in per_run if "error" not in r]
        rows.append({
            "q": q, "track": track, "covered": covered, "runs": per_run,
            # 결정성: covered 질문은 모든 run 의 result 시그니처가 1개여야 함
            "deterministic": (len(signatures) == 1) if covered and ok else None,
            "median_total_ms": int(statistics.median([r["total_ms"] for r in ok])) if ok else None,
            "median_first_token_ms": int(statistics.median(
                [r["first_token_ms"] for r in ok if r["first_token_ms"]])) if any(r["first_token_ms"] for r in ok) else None,
        })
    return _summarize(rows, runs)


def _summarize(rows: list[dict], runs: int) -> dict:
    fast = [r for r in rows if r["track"] == "fast"]
    deep = [r for r in rows if r["track"] == "deep"]
    covered = [r for r in rows if r["covered"]]
    det = [r["deterministic"] for r in covered if r["deterministic"] is not None]
    deep_runs = [run_ for r in deep for run_ in r["runs"] if "error" not in run_]
    verdicts = [r["verdict_pass"] for r in deep_runs if r["verdict_pass"] is not None]
    in_tok = [run_["input_tokens"] for r in rows for run_ in r["runs"]
              if run_.get("input_tokens")]
    cache_rd = [run_["cache_read"] for r in rows for run_ in r["runs"]
                if run_.get("cache_read")]
    return {
        "rows": rows,
        "summary": {
            "runs_per_q": runs,
            "determinism_rate": (sum(det) / len(det)) if det else None,
            "fast_median_total_ms": _med([r["median_total_ms"] for r in fast]),
            "deep_median_total_ms": _med([r["median_total_ms"] for r in deep]),
            "critic_fail_rate": (1 - sum(verdicts) / len(verdicts)) if verdicts else None,
            "avg_input_tokens": int(statistics.mean(in_tok)) if in_tok else None,
            "avg_cache_read_tokens": int(statistics.mean(cache_rd)) if cache_rd else None,
            "cache_hit_observed": bool(cache_rd),
        },
    }


def _med(xs: list) -> int | None:
    xs = [x for x in xs if x is not None]
    return int(statistics.median(xs)) if xs else None


def _md(s: dict) -> str:
    def pct(x):
        return f"{x*100:.0f}%" if isinstance(x, (int, float)) else "—"
    return "\n".join([
        "## MOCHA Bench",
        f"- 질문당 반복: {s['runs_per_q']}회",
        f"- **결정성(covered 질문 result 동일율)**: {pct(s['determinism_rate'])}",
        f"- fast 중앙 지연: {s['fast_median_total_ms']} ms / deep: {s['deep_median_total_ms']} ms",
        f"- **Critic fail(차단)율(deep)**: {pct(s['critic_fail_rate'])}",
        f"- 평균 input 토큰: {s['avg_input_tokens']} / 평균 cache_read: {s['avg_cache_read_tokens']} "
        f"(캐시 관측: {s['cache_hit_observed']})",
    ])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="http://localhost:8090")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--no-deep", dest="deep", action="store_false")
    a = ap.parse_args()
    res = run(a.base, a.runs, a.deep)
    with open("/tmp/mocha_bench.json", "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(_md(res["summary"]))
    print("\nraw → /tmp/mocha_bench.json")
    sys.exit(0)
