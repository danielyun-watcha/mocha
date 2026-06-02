"""Gateway routing accuracy 측정 — fast/deep / intent / domain.

mocha 의 gateway_classify() 를 직접 호출해서 expected vs predicted 비교.
도메인 / track / intent 별 precision / recall + confusion 표.

사용:
  $PYBIN _runtime/routing_eval.py
  (mocha 서버 실행 중이어야 — gateway_classify 가 ClaudeAgentOptions 로 LLM 호출)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

# Import gateway from running mocha (sys.path 에 mocha root 추가)
MOCHA_ROOT = Path("/home/jupyterhub/jupyter/daniel/mocha")
sys.path.insert(0, str(MOCHA_ROOT))
os.environ["IS_SANDBOX"] = "1"
os.environ["DATABASE_URL"] = "postgresql://postgres:@/mocha?host=" + str(MOCHA_ROOT / "_runtime" / "pgdata")

# Defer import — needs env first
from main import gateway_classify  # noqa: E402


# ── Test set ──────────────────────────────────────────────────
# (query, expected{track, intent, domain})
# 30-50 자연어 질문 — 회사 PM/분석가가 실제로 묻는 패턴
TESTS: list[tuple[str, dict]] = [
    # ── pedia / GALAXY (12) ─────────────────────────
    ("왓챠 피디아 평균 평점 얼마야?", {"track": "fast", "intent": "narrow_count", "domain": "pedia"}),
    ("피디아 TOP 10 별점 영화 보여줘", {"track": "fast", "intent": "narrow_top_n", "domain": "pedia"}),
    ("rec_galaxy 별점 분포", {"track": "fast", "intent": "narrow_distribution", "domain": "pedia"}),
    ("피디아 보싶 많이 받은 콘텐츠 TOP 10", {"track": "fast", "intent": "narrow_top_n", "domain": "pedia"}),
    ("피디아 1인당 평가 수 어떻게 돼?", {"track": "fast", "intent": "narrow_count", "domain": "pedia"}),
    ("rec_galaxy 어제 활성 유저", {"track": "fast", "intent": "narrow_count", "domain": "pedia"}),
    ("rec_galaxy EDA 리포트 만들어줘", {"track": "deep", "intent": "broad_eda", "domain": "pedia"}),
    ("피디아 데이터 전체 특성 분석", {"track": "deep", "intent": "broad_eda", "domain": "pedia"}),
    ("피디아 long tail 분석", {"track": "fast", "intent": "interpretive_qa", "domain": "pedia"}),
    ("rec_galaxy 큰손 유저 TOP 5", {"track": "fast", "intent": "narrow_top_n", "domain": "pedia"}),
    ("피디아 인기 감독 보여줘", {"track": "fast", "intent": "narrow_top_n", "domain": "pedia"}),
    ("rec_galaxy 평가율 추이", {"track": "fast", "intent": "narrow_distribution", "domain": "pedia"}),

    # ── watcha_main / MARS (12) ─────────────────────
    ("왓챠에서 가장 많이 시청된 영화 TOP 10", {"track": "fast", "intent": "narrow_top_n", "domain": "watcha_main"}),
    ("graph_modeling 시청 패턴 EDA", {"track": "deep", "intent": "broad_eda", "domain": "watcha_main"}),
    ("왓챠 어제 DAU", {"track": "fast", "intent": "narrow_count", "domain": "watcha_main"}),
    ("user_bert mars play 1인당 추이", {"track": "fast", "intent": "narrow_distribution", "domain": "watcha_main"}),
    ("왓챠 시청율 어떻게 돼?", {"track": "fast", "intent": "narrow_count", "domain": "watcha_main"}),
    ("next_watch 데이터 사이즈", {"track": "fast", "intent": "narrow_count", "domain": "watcha_main"}),
    ("왓챠 CVR click→play", {"track": "fast", "intent": "narrow_count", "domain": "watcha_main"}),
    ("MARS 인기 배우 TOP 5", {"track": "fast", "intent": "narrow_top_n", "domain": "watcha_main"}),
    ("왓챠 재시청률 분석해줘", {"track": "fast", "intent": "interpretive_qa", "domain": "watcha_main"}),
    ("graph_modeling EDA 리포트", {"track": "deep", "intent": "broad_eda", "domain": "watcha_main"}),
    ("왓챠 본 서비스 일주일 추이", {"track": "fast", "intent": "narrow_distribution", "domain": "watcha_main"}),
    ("MARS 콘텐츠 타입별 시청 비율", {"track": "fast", "intent": "narrow_distribution", "domain": "watcha_main"}),

    # ── adult / ADULT (10) ──────────────────────────
    ("성인+ 어제 총매출", {"track": "fast", "intent": "narrow_count", "domain": "adult"}),
    ("rec_adult heavy buyer TOP 10", {"track": "fast", "intent": "narrow_top_n", "domain": "adult"}),
    ("성인관 1인당 구매 매출", {"track": "fast", "intent": "narrow_count", "domain": "adult"}),
    ("rec_adult 매출 분포 분석", {"track": "fast", "intent": "narrow_distribution", "domain": "adult"}),
    ("adult CVR click→구매", {"track": "fast", "intent": "narrow_count", "domain": "adult"}),
    ("성인+ rental TOP 10", {"track": "fast", "intent": "narrow_top_n", "domain": "adult"}),
    ("rec_adult EDA 전반", {"track": "deep", "intent": "broad_eda", "domain": "adult"}),
    ("성인관 재구매율 추이", {"track": "fast", "intent": "narrow_distribution", "domain": "adult"}),
    ("adult preview→구매 funnel", {"track": "fast", "intent": "interpretive_qa", "domain": "adult"}),
    ("성인+ heavy buyer 매출 점유", {"track": "fast", "intent": "interpretive_qa", "domain": "adult"}),

    # ── A/B test, report, notion (6) ────────────────
    ("우리 abtest 결과 정리해줘", {"track": "deep", "intent": "ab_test", "domain": "unknown"}),
    ("rec_galaxy A/B test 사후 분석", {"track": "deep", "intent": "ab_test", "domain": "pedia"}),
    ("rec_adult LightGBM vs HSTU A/B", {"track": "deep", "intent": "ab_test", "domain": "adult"}),
    ("이번 분석 노션에 올려줘", {"track": "fast", "intent": "notion", "domain": "unknown"}),
    ("최근 분석 결과 마크다운 리포트", {"track": "deep", "intent": "report", "domain": "unknown"}),
    ("piedia AB test 결과 리포트", {"track": "deep", "intent": "report", "domain": "pedia"}),

    # ── small talk / unknown / 모호 (5) ─────────────
    ("안녕", {"track": "fast", "intent": "small_talk", "domain": "unknown"}),
    ("뭐 할 수 있어?", {"track": "fast", "intent": "small_talk", "domain": "unknown"}),
    ("데이터 좀 분석해줘", {"track": "deep", "intent": "broad_eda", "domain": "unknown"}),
    ("우리 모델 성능 알려줘", {"track": "deep", "intent": "interpretive_qa", "domain": "unknown"}),
    ("어떤 도메인이 가장 활발해?", {"track": "fast", "intent": "interpretive_qa", "domain": "unknown"}),
]


# ── Eval runner ──────────────────────────────────────────────

async def run_eval(tests: list[tuple[str, dict]], concurrency: int = 5) -> dict:
    """병렬 호출 + per-field precision."""
    results = []
    sem = asyncio.Semaphore(concurrency)

    async def _one(q: str, exp: dict):
        async with sem:
            t0 = time.time()
            try:
                pred = await gateway_classify(q)
            except Exception as e:
                pred = {"track": "error", "intent": "error", "domain": "error", "summary": str(e)[:200]}
            return {"q": q, "exp": exp, "pred": pred, "elapsed": time.time() - t0}

    tasks = [_one(q, exp) for q, exp in tests]
    for i, fut in enumerate(asyncio.as_completed(tasks), 1):
        r = await fut
        results.append(r)
        print(f"  [{i}/{len(tests)}] {r['elapsed']:.1f}s  "
              f"track={r['pred'].get('track')}/{r['exp']['track']}  "
              f"intent={r['pred'].get('intent')}/{r['exp']['intent']}  "
              f"dom={r['pred'].get('domain')}/{r['exp']['domain']}  "
              f"| {r['q'][:40]}")
    return results


def summarize(results: list[dict]) -> None:
    n = len(results)
    fields = ("track", "intent", "domain")
    correct = {f: 0 for f in fields}
    by_field_confusion = {f: Counter() for f in fields}
    per_intent = defaultdict(lambda: {"total": 0, "correct": 0})

    elapsed_list = [r["elapsed"] for r in results]
    total_time = sum(elapsed_list)

    for r in results:
        exp, pred = r["exp"], r["pred"]
        for f in fields:
            ok = exp.get(f) == pred.get(f)
            if ok:
                correct[f] += 1
            else:
                by_field_confusion[f][(exp[f], pred.get(f))] += 1
        per_intent[exp["intent"]]["total"] += 1
        if exp["intent"] == pred.get("intent"):
            per_intent[exp["intent"]]["correct"] += 1

    print("\n" + "═" * 70)
    print(f"Routing Eval — n={n}, avg latency={total_time/n:.2f}s, total={total_time:.1f}s")
    print("═" * 70)
    for f in fields:
        pct = correct[f] / n * 100
        print(f"  {f:<8} acc = {correct[f]:>2}/{n} = {pct:5.1f}%")
    print()
    print("── 오답 (confusion expected → predicted) ──")
    for f in fields:
        if not by_field_confusion[f]:
            print(f"  {f}: (없음)")
            continue
        print(f"  {f}:")
        for (e, p), c in by_field_confusion[f].most_common():
            print(f"    {e!s:>20} → {p!s:<20}  ×{c}")
    print()
    print("── intent 별 정확도 ──")
    for intent, s in sorted(per_intent.items(), key=lambda x: -x[1]["total"]):
        pct = s["correct"] / s["total"] * 100 if s["total"] else 0
        print(f"  {intent:<22} {s['correct']:>2}/{s['total']:<2} = {pct:5.1f}%")


async def main():
    print(f"Running routing eval on {len(TESTS)} queries (concurrency 5)…\n")
    results = await run_eval(TESTS, concurrency=5)
    summarize(results)
    # Save raw results
    out_path = MOCHA_ROOT / "_runtime" / "routing_eval_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print(f"\nRaw results → {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
