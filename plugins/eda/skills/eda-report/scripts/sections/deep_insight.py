"""§도메인 깊이 해석 — LLM (orchestrator)이 채울 placeholder.

Deterministic 부분(분석 결과, 표, 차트, hardcode 설명)이 끝난 뒤
오케스트레이터의 마지막 step에서 Claude가 데이터를 보고 도메인 맥락에 맞춰
직접 작성하는 섹션.

Placeholder 형식 — `<!-- LLM_DEEP_INSIGHT_* -->` 주석으로 위치 표시.
오케스트레이터가 해당 marker 사이를 자체 작성으로 교체.
"""

PLACEHOLDER = """## 🎯 도메인 깊이 해석

<!-- LLM_DEEP_INSIGHT_START -->

> ℹ️ _이 섹션은 위 분석 결과를 종합해 **오케스트레이터(Claude)** 가 도메인 맥락 (Watcha · 추천시스템 · 콘텐츠 비즈니스) 에 맞춰 작성합니다._
> _작성 가이드: `references/llm_insight_pattern.md`_

**작성 미완료 — 오케스트레이터가 다음 5-7개 인사이트를 채워야 함**:

각 인사이트는 다음 4요소를 포함:
1. **관찰** (observation): 분석 결과의 구체 수치 + 도메인 의미
2. **비즈니스 함의**: 콘텐츠 수급 / UX / 큐레이션 / KPI 관점에서의 함의
3. **유저 행동 추정**: 이 패턴이 발생하는 유저측 이유 (가설)
4. **모델링 권장**: 구체적인 algorithm / feature / training 권장 (generic ML 용어 X)

<!-- LLM_DEEP_INSIGHT_END -->
"""


def render() -> str:
    """LLM placeholder 반환. 오케스트레이터가 marker 사이를 채움."""
    return PLACEHOLDER
