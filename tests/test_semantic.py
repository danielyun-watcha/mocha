"""Unit tests for the semantic layer (glossary + metric registry + resolver).

No I/O: kpi.summary() is monkeypatched so contracts are tested without /archive.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import kpi  # noqa: E402
import semantic as s  # noqa: E402


# ── glossary resolution ──────────────────────────────────────────────────
@pytest.mark.parametrize("question, expected_key", [
    ("성인관 큰손 누구야?", "revenue.top_payers"),
    ("지난주 mars 인기 장르 보여줘", "content.top_genres"),
    ("galaxy 평점 분포 알려줘", "rating.distribution"),
    ("객단가 얼마야", "revenue.arppu"),
    ("관심없어요 많은 콘텐츠", "content.top_meh"),
])
def test_resolve_terms_maps_colloquial_to_metric(question, expected_key):
    keys = [h.metric_key for h in s.resolve_terms(question)]
    assert expected_key in keys


def test_resolve_terms_dedups_by_metric():
    # 같은 metric 으로 가는 여러 alias 가 있어도 1회만
    hits = s.resolve_terms("활성 유저 활성유저 액티브")
    keys = [h.metric_key for h in hits]
    assert keys.count("engagement.active_users") == 1


def test_resolve_terms_domain_filter():
    # revenue 용어는 galaxy 도메인에선 안 잡혀야 함
    hits = s.resolve_terms("큰손 누구", domain="galaxy")
    assert all(h.metric_key != "revenue.top_payers" for h in hits)


# ── registry integrity ───────────────────────────────────────────────────
def test_every_glossary_term_maps_to_known_metric():
    for term in s.GLOSSARY:
        assert term.maps_to in s.BY_KEY, f"{term.canonical} → unknown {term.maps_to}"


def test_metric_keys_unique():
    keys = [m.key for m in s.REGISTRY]
    assert len(keys) == len(set(keys))


# 실제 kpi.py 구조 대비 검증 (stub 아님 — 순환 검증 방지).
# summary() 의 kpis 리스트는 도메인별 HERO_LABELS ∪ TABLE_PRIORITY 라벨만 포함하므로,
# 'kpi:<라벨>' resolve 는 그 집합 안에 있어야 한다. (mars '1인당 RATE' 누락 같은 버그 차단)
def _valid_kpi_labels(domain: str) -> set[str]:
    import kpi as k
    return set(k.HERO_LABELS.get(domain, [])) | set(k.TABLE_PRIORITY.get(domain, []))


def test_kpi_resolve_labels_exist_in_real_kpi_lists():
    bad = []
    for m in s.REGISTRY:
        if not m.resolve.startswith("kpi:"):
            continue
        label = m.resolve[4:]
        for d in m.domains:
            if label not in _valid_kpi_labels(d):
                bad.append((m.key, d, label))
    assert not bad, f"kpi 라벨이 해당 도메인 KPI 목록에 없음: {bad}"


def test_path_resolve_top_level_keys_exist():
    # summary() 가 실제로 내보내는 top-level 키 (kpi.py summary() 기준)
    summary_keys = {
        "kpis", "timeseries", "actions", "top_contents", "top_genres",
        "content_type_breakdown", "rating_distribution", "hourly_activity",
        "pareto_curve", "revenue", "top_actors", "top_directors",
        "top_revenue_contents", "top_rated_contents", "top_meh_contents",
        "top_users",
    }
    bad = [m.key for m in s.REGISTRY
           if not m.resolve.startswith("kpi:")
           and m.resolve.split(".")[0] not in summary_keys]
    assert not bad, f"summary() 에 없는 top-level 키 참조: {bad}"


def test_rate_per_user_not_available_for_mars():
    # mars 는 '1인당 RATE' KPI 가 없음 → 매핑에서 제외돼야 함
    assert "mars" not in s.BY_KEY["engagement.rate_per_user"].domains


# ── metric_value contract (kpi.summary stubbed) ──────────────────────────
@pytest.fixture
def stub_summary(monkeypatch):
    def _fake(domain, start, end, content_types=None, action_types=None):
        return {
            "kpis": [{"label": "active_users", "value": 12345, "fmt": "int"}],
            "revenue": {
                "revenue_per_paying_user": 8800,
                "top_payers": [{"user_id": 1, "revenue": 99000}],
            },
        }
    monkeypatch.setattr(kpi, "summary", _fake)


def test_metric_value_scalar(stub_summary):
    r = s.metric_value("engagement.active_users", "adult",
                       date(2026, 5, 1), date(2026, 5, 7))
    assert r["value"] == 12345
    assert r["display"] == "12,345"
    assert "2026-05-01 ~ 2026-05-07" in r["조회기준"]
    assert r["definition"]  # 정의가 비어있지 않음


def test_metric_value_won_format(stub_summary):
    r = s.metric_value("revenue.arppu", "adult", date(2026, 5, 1), date(2026, 5, 7))
    assert r["display"] == "₩8,800"


def test_metric_value_table(stub_summary):
    r = s.metric_value("revenue.top_payers", "adult",
                       date(2026, 5, 1), date(2026, 5, 7))
    assert r["kind"] == "table"
    assert r["rows"] == [{"user_id": 1, "revenue": 99000}]


def test_metric_value_domain_guard(stub_summary):
    r = s.metric_value("revenue.arppu", "galaxy", date(2026, 5, 1), date(2026, 5, 7))
    assert "error" in r


def test_metric_value_unknown_metric(stub_summary):
    r = s.metric_value("nope.nope", "adult", date(2026, 5, 1), date(2026, 5, 7))
    assert "error" in r


# ── answer_scaffold (점진적 출력용) ──────────────────────────────────────
def test_answer_scaffold_scalar_and_criteria():
    summary = {"kpis": [{"label": "active_users", "value": 12345, "fmt": "int"}]}
    out = s.answer_scaffold("활성 유저 몇 명이야", "mars",
                            date(2026, 5, 1), date(2026, 5, 7), summary)
    assert out["criteria"] and "2026-05-01 ~ 2026-05-07" in out["criteria"]
    keys = [r["metric"] for r in out["results"]]
    assert "engagement.active_users" in keys
    blk = next(r for r in out["results"] if r["metric"] == "engagement.active_users")
    assert blk["display"] == "12,345"


def test_answer_scaffold_table_truncates_to_5():
    rows = [{"user_id": i, "revenue": i * 1000} for i in range(20)]
    summary = {"revenue": {"top_payers": rows}}
    out = s.answer_scaffold("큰손 누구", "adult",
                            date(2026, 5, 1), date(2026, 5, 7), summary)
    blk = next(r for r in out["results"] if r["metric"] == "revenue.top_payers")
    assert blk["kind"] == "table"
    assert len(blk["rows"]) == 5


def test_answer_scaffold_empty_when_no_term():
    out = s.answer_scaffold("오늘 날씨 어때", "mars",
                            date(2026, 5, 1), date(2026, 5, 7), {})
    assert out["results"] == [] and out["criteria"] is None


# ── prompt catalogs ──────────────────────────────────────────────────────
def test_describe_metrics_domain_filtered():
    txt = s.describe_metrics("adult")
    assert "revenue.arppu" in txt
    assert "engagement.play_total" not in txt  # mars 전용 → adult 카탈로그에 없어야


def test_describe_glossary_includes_disambiguation_note():
    txt = s.describe_glossary("galaxy")
    assert "rating.distribution" in txt
    # rating 분포의 모호성 해소 note 가 노출되는지
    assert "action_type 필터 무관" in txt
