"""세션 trace.jsonl 로깅 — 사후 디버깅 / 재시도 추적 / observability.

오케스트레이터 SKILL.md가 각 sub-skill 호출 후 append:
  python3 trace.py <session_dir> --step overview --skill eda-overview \
      --completeness 0.94 --decision "ready_for_report"
"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


def append_trace(session_dir: Path, entry: dict) -> None:
    """trace.jsonl에 한 줄 추가. 세션 디렉토리 없으면 생성."""
    session_dir.mkdir(parents=True, exist_ok=True)
    trace_path = session_dir / "trace.jsonl"
    kst = timezone(timedelta(hours=9))
    entry["ts"] = datetime.now(kst).isoformat(timespec="seconds")
    with trace_path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Append a trace entry.")
    parser.add_argument("session_dir", help="/tmp/eda/<session>/")
    parser.add_argument("--step", required=True, help="Step name (e.g., overview, casestudy)")
    parser.add_argument("--skill", help="Sub-skill invoked")
    parser.add_argument("--args", help="Args passed to sub-skill")
    parser.add_argument("--completeness", type=float, help="Inspector completeness score")
    parser.add_argument("--decision", help="Decision made by orchestrator")
    parser.add_argument("--note", help="Free-form note")
    args = parser.parse_args()

    entry = {k: v for k, v in {
        "step": args.step,
        "skill": args.skill,
        "args": args.args,
        "completeness": args.completeness,
        "decision": args.decision,
        "note": args.note,
    }.items() if v is not None}
    append_trace(Path(args.session_dir), entry)
    print(f"✓ Trace appended to {args.session_dir}/trace.jsonl")


if __name__ == "__main__":
    main()
