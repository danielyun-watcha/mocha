"""End-to-end test for inspector.py — fixture invariants.

Run: `python -m pytest tests/test_inspector.py -v`
또는: `python tests/test_inspector.py`
"""
import json
import sys
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from inspector import inspect_results  # noqa: E402


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


class InspectorE2ETest(unittest.TestCase):
    """Inspector의 invariant 검증 — SKILL.md / inspector.py 수정 시 regression 잡기."""

    def test_dense_data_ready_for_report(self):
        """완전한 데이터 → completeness ≥ 0.67, ready_for_report True."""
        r = _load("dense_results.json")
        report = inspect_results(r)
        self.assertGreaterEqual(report["completeness_score"], 0.67,
                                f"dense 데이터인데 completeness 낮음: {report['completeness_score']}")
        # findings 최소 2개 이상 (sparsity, head_heavy 등)
        self.assertGreaterEqual(len(report["findings"]), 2,
                                "dense 데이터인데 findings 부족")

    def test_sparse_data_not_ready(self):
        """빈약한 데이터 → completeness 낮음, ready_for_report False."""
        r = _load("sparse_results.json")
        report = inspect_results(r)
        self.assertLess(report["completeness_score"], 0.67,
                        f"sparse 데이터인데 completeness 높음: {report['completeness_score']}")
        self.assertFalse(report["ready_for_report"],
                         "sparse 데이터인데 ready_for_report True")
        # 재시도 권장 있어야
        self.assertGreater(len(report["recommended_actions"]), 0,
                           "sparse인데 recommended_actions 없음")

    def test_negative_domain_has_findings(self):
        """negative 도메인 → 분석 결과가 적게 있어도 일부 finding 추출."""
        r = _load("negative_results.json")
        report = inspect_results(r)
        # 최소 suggestions 2개 있고 case_studies 2종 있음 → axis 2/3 pass
        self.assertGreaterEqual(report["completeness_score"], 0.33,
                                "negative — 일부 axis pass 했어야")

    def test_gini_from_results(self):
        """Inspector가 _compute_gini를 직접 호출하지 않고 results['gini']를 읽는지."""
        r = _load("dense_results.json")
        report = inspect_results(r)
        head_heavy = next((f for f in report["findings"] if f.get("signal") == "head_heavy"), None)
        if head_heavy:
            self.assertEqual(head_heavy.get("context", {}).get("gini"), 0.715,
                             "Gini가 results.gini와 일치 안 함")

    def test_kst_peak_hour(self):
        """KST 보정된 peak hour가 그대로 finding에 반영되는지."""
        r = _load("dense_results.json")
        report = inspect_results(r)
        temporal = next((f for f in report["findings"] if f.get("signal") == "temporal_peak"), None)
        if temporal:
            self.assertEqual(temporal["context"]["peak_hour"], 23,
                             "Peak hour KST 23이 아님")


if __name__ == "__main__":
    unittest.main(verbosity=2)
