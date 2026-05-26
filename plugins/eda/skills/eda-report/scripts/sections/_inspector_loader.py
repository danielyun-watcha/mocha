"""Inspector 로드 helper — 두 entry script(render_full_report, render_qa) 공유.

기존 _find_inspector + _try_load_inspect의 DRY violation 해소 + 명시적 에러.
"""
import os
import sys
from pathlib import Path


def find_inspector_path(skill_dir: Path) -> Path | None:
    """inspector.py 위치 동적 resolution.

    탐색 순서:
    1. 환경변수 EDA_INSPECTOR_PATH (가장 강력)
    2. 형제 eda 스킬 디렉토리 (같은 플러그인 내)
    3. ~/.claude/plugins 하위 어디든 (marketplace 이름 무관)
    """
    env = os.environ.get("EDA_INSPECTOR_PATH")
    if env:
        p = Path(env)
        if p.exists():
            return p

    sibling = skill_dir.parent / "eda" / "scripts" / "inspector.py"
    if sibling.exists():
        return sibling

    plugin_root = Path.home() / ".claude" / "plugins"
    if plugin_root.exists():
        matches = list(plugin_root.glob("**/skills/eda/scripts/inspector.py"))
        if matches:
            return matches[0]
    return None


def load_inspect_results(results: dict, skill_dir: Path,
                         strict: bool = False) -> dict | None:
    """Inspector를 로드해서 results에 대해 inspect_results 호출.

    Args:
        results: analysis_results.json 내용
        skill_dir: 호출하는 skill의 디렉토리 (Path(__file__).parent.parent.parent)
        strict: True면 inspector를 못 찾을 때 RuntimeError raise (default: False → None 반환 + warning)

    Returns:
        inspect_results dict 또는 None (못 찾았거나 실패)
    """
    insp = find_inspector_path(skill_dir)
    if insp is None:
        msg = ("⚠ inspector.py not found. 검색 경로: "
               "$EDA_INSPECTOR_PATH / 형제 eda 디렉토리 / ~/.claude/plugins/**/inspector.py")
        if strict:
            raise RuntimeError(msg)
        print(msg, file=sys.stderr)
        return None

    sys.path.insert(0, str(insp.parent))
    try:
        from inspector import inspect_results  # type: ignore
        return inspect_results(results)
    except Exception as e:
        msg = f"⚠ inspector load failed: {type(e).__name__}: {e}"
        if strict:
            raise RuntimeError(msg) from e
        print(msg, file=sys.stderr)
        return None
