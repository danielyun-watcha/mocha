"""Unit tests for the conditional Critic pure functions.

verify() (LLM call) is not tested here — it lazy-imports claude_agent_sdk.
The gate / prompt / verdict-parse logic is pure and fully testable.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents import critic as c  # noqa: E402


# ── should_verify gate ───────────────────────────────────────────────────
def test_should_verify_fires_on_deep_normal_answer():
    assert c.should_verify("deep", errored=False, answer="분석 결과입니다.") is True


def test_should_verify_skips_fast_track():
    assert c.should_verify("fast", errored=False, answer="결과") is False


def test_should_verify_skips_errored():
    assert c.should_verify("deep", errored=True, answer="결과") is False


def test_should_verify_skips_aborted_or_empty():
    assert c.should_verify("deep", errored=False, answer="(중단됨)") is False
    assert c.should_verify("deep", errored=False, answer="") is False


# ── parse_verdict ────────────────────────────────────────────────────────
def test_parse_verdict_pass():
    raw = '여기 결과: {"pass": true, "confidence": 0.9, "issues": [], "summary": "이상 없음"}'
    v = c.parse_verdict(raw)
    assert v["pass"] is True and v["confidence"] == 0.9 and v["parsed"] is True


def test_parse_verdict_high_severity_forces_fail():
    # 모델이 pass=true 라 해도 high severity issue 있으면 강제 fail
    raw = '{"pass": true, "confidence": 0.8, "issues": [{"dim":"계산sanity","severity":"high","detail":"비율 합이 120%"}], "summary":"의심"}'
    v = c.parse_verdict(raw)
    assert v["pass"] is False
    assert len(v["issues"]) == 1


def test_parse_verdict_no_json_is_conservative():
    v = c.parse_verdict("검증 못 했어요")
    assert v["parsed"] is False and v["pass"] is True and v["confidence"] == 0.0


def test_parse_verdict_clamps_confidence():
    assert c.parse_verdict('{"pass": true, "confidence": 5}')["confidence"] == 1.0
    assert c.parse_verdict('{"pass": true, "confidence": -2}')["confidence"] == 0.0


def test_parse_verdict_bad_confidence_type():
    v = c.parse_verdict('{"pass": true, "confidence": "high"}')
    assert v["confidence"] == 0.0


# ── build_critic_prompt ──────────────────────────────────────────────────
def test_build_critic_prompt_contains_inputs():
    p = c.build_critic_prompt("큰손 누구?", "유저 A가 1위", "revenue.top_payers 정의…")
    assert "큰손 누구?" in p
    assert "유저 A가 1위" in p
    assert "revenue.top_payers" in p
    assert "JSON only" in p
    # 체크리스트 6개 항목이 들어있는지
    for kw in ["정의일치", "계산sanity", "도메인격리", "caveat위반", "응답성"]:
        assert kw in p
