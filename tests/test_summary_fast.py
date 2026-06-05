"""TDD: summary_fast (DuckDB) ≡ summary (pandas oracle).

기준 (사용자 합의):
- count/합계 값 = 정확히 일치
- 동점 항목 순서 = 허용 (set/multiset 비교, tie-swap 허용)
- 파생 float(share, avg) = 작은 tolerance

실제 archive(/archive) 필요 → 없으면 skip (CI 안전). 로컬 검증용.
oracle 빠르게 하려고 3일 윈도우 사용 (모든 panel 커버).
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import kpi

_ARCHIVE = Path(os.environ.get("ARCHIVE_DIR", "/mnt/ml-archive"))
pytestmark = pytest.mark.skipif(
    not (_ARCHIVE / "user_bert").exists(),
    reason="archive 미마운트 — summary_fast 동일성 테스트 skip",
)

# 도메인별 3일 검증 윈도우 (archive 데이터 있는 구간)
WINDOWS = {
    "galaxy": (date(2026, 5, 22), date(2026, 5, 24)),
    "mars":   (date(2026, 5, 8), date(2026, 5, 10)),
    "adult":  (date(2026, 5, 22), date(2026, 5, 24)),
}


# ── 비교 헬퍼 ────────────────────────────────────────────────────────────
def _dict_exact(fast, oracle, key, valkeys):
    """dict-keyed panel (kpis/actions/timeseries/...) — 값 정확 일치."""
    fo = {r[key]: tuple(r[v] for v in valkeys) for r in oracle}
    ff = {r[key]: tuple(r[v] for v in valkeys) for r in fast}
    assert ff == fo, f"키={key}: fast={ff} != oracle={fo}"


def _topn_match(fast, oracle, key, valkeys):
    """top-N panel — 같은 길이 + 공통 항목 값 일치 + 값 multiset 일치(tie 허용)."""
    assert len(fast) == len(oracle), f"길이 {len(fast)}!={len(oracle)}"
    fo = {r[key]: tuple(r[v] for v in valkeys) for r in oracle}
    ff = {r[key]: tuple(r[v] for v in valkeys) for r in fast}
    for k in set(fo) & set(ff):
        assert ff[k] == fo[k], f"{key}={k}: {ff[k]} != {fo[k]}"
    assert sorted(fo.values()) == sorted(ff.values()), "값 multiset 불일치"


def _kpis_to_dict(kpis):
    return {k["label"]: k["value"] for k in kpis}


# ── 테스트 ──────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def pair():
    out = {}
    for dom, (s, e) in WINDOWS.items():
        # oracle 은 pandas 경로 강제 (summary() 가 summary_fast 로 위임하므로)
        out[dom] = (kpi.summary(dom, s, e, _force_oracle=True),
                    kpi.summary_fast(dom, s, e))
    return out


@pytest.mark.parametrize("domain", ["galaxy", "mars", "adult"])
def test_kpis(pair, domain):
    o, f = pair[domain]
    od, fd = _kpis_to_dict(o["kpis"]), _kpis_to_dict(f["kpis"])
    # 정수 KPI 는 정확 일치, 비율 KPI(f2)는 tolerance
    for label, ov in od.items():
        fv = fd.get(label)
        assert fv is not None, f"{domain}: kpi '{label}' 누락"
        if isinstance(ov, float):
            assert abs(fv - ov) < 1e-6, f"{domain}.{label}: {fv} != {ov}"
        else:
            assert fv == ov, f"{domain}.{label}: {fv} != {ov}"


@pytest.mark.parametrize("domain", ["galaxy", "mars", "adult"])
def test_actions(pair, domain):
    o, f = pair[domain]
    _dict_exact(f["actions"], o["actions"], "label", ["count"])


@pytest.mark.parametrize("domain", ["galaxy", "mars", "adult"])
def test_timeseries(pair, domain):
    o, f = pair[domain]
    _dict_exact(f["timeseries"], o["timeseries"], "date", ["events", "users"])


@pytest.mark.parametrize("domain", ["galaxy", "mars", "adult"])
def test_content_type_breakdown(pair, domain):
    o, f = pair[domain]
    _dict_exact(f["content_type_breakdown"], o["content_type_breakdown"], "code", ["count"])


@pytest.mark.parametrize("domain", ["galaxy", "mars", "adult"])
def test_top_contents(pair, domain):
    o, f = pair[domain]
    _topn_match(f["top_contents"], o["top_contents"], "content", ["events", "users"])


@pytest.mark.parametrize("domain", ["galaxy", "mars", "adult"])
def test_top_users(pair, domain):
    o, f = pair[domain]
    _topn_match(f["top_users"], o["top_users"], "user_id", ["events", "contents"])


@pytest.mark.parametrize("domain", ["galaxy", "mars"])
def test_top_genres(pair, domain):
    o, f = pair[domain]
    _dict_exact(f["top_genres"], o["top_genres"], "name", ["events", "users"])


@pytest.mark.parametrize("domain", ["galaxy", "mars"])
def test_hourly(pair, domain):
    o, f = pair[domain]
    _dict_exact(f["hourly_activity"], o["hourly_activity"], "hour", ["count"])


@pytest.mark.parametrize("domain", ["galaxy", "mars"])
def test_rating_distribution(pair, domain):
    o, f = pair[domain]
    od = {r["rating"]: r["count"] for r in o["rating_distribution"]}
    fd = {r["rating"]: r["count"] for r in f["rating_distribution"]}
    assert fd == od


@pytest.mark.parametrize("domain", ["galaxy", "mars", "adult"])
def test_pareto(pair, domain):
    o, f = pair[domain]
    od = {r["top_pct"]: r["share"] for r in o["pareto_curve"]}
    fd = {r["top_pct"]: r["share"] for r in f["pareto_curve"]}
    assert set(fd) == set(od)
    for p, ov in od.items():
        assert abs(fd[p] - ov) < 1e-6, f"{domain} pareto {p}: {fd[p]} != {ov}"


@pytest.mark.parametrize("domain", ["galaxy", "mars"])
def test_top_rated(pair, domain):
    o, f = pair[domain]
    # avg_rating + rate_count, tie 허용 (multiset)
    fo = {r["content"]: (r["avg_rating"], r["rate_count"]) for r in o["top_rated_contents"]}
    ff = {r["content"]: (r["avg_rating"], r["rate_count"]) for r in f["top_rated_contents"]}
    assert len(ff) == len(fo)
    for k in set(fo) & set(ff):
        assert ff[k] == fo[k], f"{domain} top_rated {k}: {ff[k]} != {fo[k]}"
    assert sorted(fo.values()) == sorted(ff.values())


@pytest.mark.parametrize("domain,kind", [("galaxy", "top_actors"), ("galaxy", "top_directors"),
                                         ("mars", "top_actors"), ("mars", "top_directors")])
def test_meta(pair, domain, kind):
    o, f = pair[domain]
    # 배우/감독 — meta_id→count, tie 허용
    fo = {r["meta_id"]: r["count"] for r in o[kind]}
    ff = {r["meta_id"]: r["count"] for r in f[kind]}
    assert len(ff) == len(fo)
    for k in set(fo) & set(ff):
        assert ff[k] == fo[k], f"{domain}.{kind} {k}: {ff[k]} != {fo[k]}"
    assert sorted(fo.values()) == sorted(ff.values())


def test_adult_revenue(pair):
    o, f = pair["adult"]
    orv, frv = o["revenue"], f["revenue"]
    assert frv.get("available") == orv.get("available")
    if orv.get("available"):
        assert frv["total_revenue"] == orv["total_revenue"]
        assert frv["paying_users"] == orv["paying_users"]
    # top_revenue_contents — revenue/purchases 정확 일치 (tie 허용)
    fo = {r["content"]: (r["revenue"], r["purchases"]) for r in o["top_revenue_contents"]}
    ff = {r["content"]: (r["revenue"], r["purchases"]) for r in f["top_revenue_contents"]}
    for k in set(fo) & set(ff):
        assert ff[k] == fo[k]
    assert sorted(fo.values()) == sorted(ff.values())
