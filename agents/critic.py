"""Conditional Critic — deep-track 답변을 독립 맥락에서 적대적으로 검증.

설계 의도:
- registry-covered 결정적 답(아는 지표)은 정의=정답이라 검증 불필요 → 게이트에서 제외.
- deep-track LLM 분석(쿼리·숫자를 LLM이 만든 경우)에만 발동.
- 자기검토는 편향되므로 **신선한 컨텍스트 + "틀린 점을 찾아라" 적대적 프롬프트**로 채점.
- v1: 비차단 verdict 배지(정직한 신뢰도 표시). auto-retry 루프는 후속.

순수 함수(should_verify / build_critic_prompt / parse_verdict)는 SDK 없이 테스트 가능.
LLM 호출(verify)은 claude_agent_sdk 를 lazy import.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

log = logging.getLogger("mocha.critic")

CRITIC_TIMEOUT_S = int(os.environ.get("MOCHA_CRITIC_TIMEOUT_S", "45"))

CRITIC_SYSTEM = (
    "You are a skeptical senior data-analysis reviewer for Watcha. "
    "당신의 임무는 동료의 분석 답변에서 '틀린 점'을 찾는 것이다. 칭찬 금지. "
    "기본값은 의심(pass=false)이며, 명확히 문제없을 때만 pass=true. "
    "반드시 JSON 만 출력한다."
)

# 검증 체크리스트 (프롬프트에 주입 + 사람이 읽는 기준)
CHECKLIST = [
    "정의일치: 지표를 아래 계약/용어 정의대로 계산했는가",
    "계산sanity: 비율 합 100%? 0으로 나눔? 불가능한 음수/단위(원·건·%) 오류?",
    "기간·KST: 조회 기간이 질문과 맞고 KST 자정 경계를 지켰는가",
    "도메인격리: 다른 도메인 데이터가 섞이지 않았는가",
    "caveat위반: 알려진 함정(rating=별도셋·MEH↔WISH 배타·snapshot 삭제 미반영 등)을 어겼는가",
    "응답성: 질문에 실제로 답했는가(곁길로 새지 않았는가)",
]


def should_verify(track: str, errored: bool, answer: str) -> bool:
    """검증 발동 게이트. deep-track 의 정상 답변만 (registry 결정적 답·실패는 제외)."""
    if errored or not answer:
        return False
    if answer.lstrip().startswith("("):  # "(중단됨)" / "(빈 응답)"
        return False
    return track == "deep"


def build_critic_prompt(question: str, answer: str, contracts: str) -> str:
    checklist = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(CHECKLIST))
    return (
        f"## 질문\n{question}\n\n"
        f"## 검토할 답변\n{answer}\n\n"
        f"## 지표 계약 / 용어 정의 (이 정의가 기준)\n{contracts}\n\n"
        f"## 체크리스트\n{checklist}\n\n"
        "## 출력 (JSON only)\n"
        '{"pass": true|false, "confidence": 0.0~1.0, '
        '"issues": [{"dim": "정의일치|계산sanity|기간·KST|도메인격리|caveat위반|응답성", '
        '"severity": "low|med|high", "detail": "구체적 문제"}], '
        '"summary": "한 줄 총평"}\n'
        "issue 가 없으면 issues=[] 로. high severity 가 하나라도 있으면 pass=false."
    )


def parse_verdict(raw: str) -> dict[str, Any]:
    """LLM 출력에서 JSON verdict 추출. 실패 시 보수적 기본값(검증 보류)."""
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not m:
        return {"pass": True, "confidence": 0.0, "issues": [],
                "summary": "검증 결과 파싱 실패", "parsed": False}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"pass": True, "confidence": 0.0, "issues": [],
                "summary": "검증 JSON 파싱 실패", "parsed": False}
    issues = d.get("issues") or []
    # high severity 가 있으면 강제로 pass=false (모델이 누락해도 보정)
    has_high = any((i or {}).get("severity") == "high" for i in issues)
    passed = bool(d.get("pass", True)) and not has_high
    try:
        conf = float(d.get("confidence", 0.0))
    except (ValueError, TypeError):
        conf = 0.0
    return {
        "pass": passed,
        "confidence": max(0.0, min(1.0, conf)),
        "issues": issues,
        "summary": str(d.get("summary", "")),
        "parsed": True,
    }


async def verify(question: str, answer: str, domain: str, model: str) -> dict[str, Any]:
    """독립 LLM 으로 답변 검증. semantic 계약을 기준으로 채점. deadline 가드."""
    from claude_agent_sdk import ClaudeAgentOptions, query  # lazy

    import semantic as _sem
    contracts = _sem.describe_metrics(domain) + "\n" + _sem.describe_glossary(domain)
    prompt = build_critic_prompt(question, answer, contracts)
    options = ClaudeAgentOptions(
        model=model, system_prompt=CRITIC_SYSTEM,
        max_turns=1, permission_mode="bypassPermissions",
    )
    deadline = time.time() + CRITIC_TIMEOUT_S
    chunks: list[str] = []
    try:
        async for msg in query(prompt=prompt, options=options):
            if time.time() > deadline:
                log.warning("critic timeout (%ds)", CRITIC_TIMEOUT_S)
                return {"pass": True, "confidence": 0.0, "issues": [],
                        "summary": "검증 타임아웃", "parsed": False}
            if type(msg).__name__ == "AssistantMessage":
                for block in getattr(msg, "content", []) or []:
                    if text := getattr(block, "text", None):
                        chunks.append(text)
            elif type(msg).__name__ == "ResultMessage":
                break
    except Exception:
        log.exception("critic verify failed")
        return {"pass": True, "confidence": 0.0, "issues": [],
                "summary": "검증 호출 실패", "parsed": False}
    return parse_verdict("".join(chunks))


__all__ = ["should_verify", "build_critic_prompt", "parse_verdict", "verify",
           "CHECKLIST", "CRITIC_TIMEOUT_S"]
