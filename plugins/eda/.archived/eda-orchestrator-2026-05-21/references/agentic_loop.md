# Agentic Loop 디자인

토스 PANDA의 "탐색→실행→검증→재시도" 4단계를 우리 EDA 오케스트레이터 구조에 맞게 적응한 버전.

## 핵심 차이 — 도구 선택 루프가 아닌 완성도 루프

옛 SKILL.md의 agentic loop는 10개 fine-grained 분석 스킬 중 다음 도구를 선택하는 **도구 탐색 루프**였다. 우리 새 구조는 5개 vertical sub-skill로 통합돼 있어, 같은 의미의 "다음 도구 선택"이 자연스럽지 않다 — 도구가 사실상 고정.

대신, 우리의 루프는 **완성도(completeness) + 품질(quality) + 적응형 구성(adaptive composition)** 루프다.

| PANDA 단계 | 우리 매핑 | 구현 |
|---|---|---|
| 탐색 | 사용자 의도 분류 (full / QA / 부분) | SKILL.md 라우팅 규칙 |
| 실행 | sub-skill 호출 | Bash 또는 Skill 도구 |
| **검증** | `inspector.py` — JSON → findings + completeness | 신규 |
| **재시도** | 부족 시 sub-skill 재실행 (다른 파라미터) | SKILL.md 결정 트리 |

## 데이터 흐름

```
사용자 요청
   ↓
[탐색] 의도 분류
   ↓
[실행 R1] eda-overview
   ↓
[검증 R1] inspector → findings + completeness
   ↓
완성도 ≥ 0.7 + non-trivial ≥ 2 ?
   ├─ NO  → [재시도] 추가 sub-skill (casestudy --top-n 20) → 다시 검증
   └─ YES → [실행 R2] eda-casestudy
                ↓
            [검증 R2] inspector 재실행
                ↓
            ready_for_report ?
              ├─ NO  → 재시도 (다른 파라미터/도메인 강제)
              └─ YES → eda-figures + eda-report --mode full
```

## Inspector 출력 명세

```python
{
  "findings": [
    {
      "signal": "head_heavy" | "sparsity" | "temporal_peak" | "bot_suspect" | "extreme_value" | ...,
      "value": "<사람이 읽을 한 줄 설명>",
      "context": {<수치 raw — auto-fill 부연용>},
      "severity": "strong" | "notable" | "note",
      "action_hint": "<권장 행동 — 보고서에 자동 포함>"
    },
    ...
  ],
  "completeness_score": 0.0 ~ 1.0,
  "missing": ["_meta", "case_studies", ...],
  "recommended_actions": [
    {"action": "rerun_casestudy", "args": "--top-n 30", "reason": "..."}
  ],
  "ready_for_report": true | false,
  "summary": {"n_findings": N, "n_strong": N, "n_notable": N, "n_suggestions": N}
}
```

## 결정 규칙 (오케스트레이터가 실행)

### Round 1 후 (overview만 수행)
- `completeness < 0.5` → overview 결과 자체에 문제 (파일 누락 가능) → 사용자에게 안내
- `completeness ≥ 0.5` → casestudy 진행

### Round 2 후 (overview + casestudy)
- `ready_for_report = true` → 그대로 figures + report
- `len(suggestions) < 2` → casestudy 재실행 with `--top-n 30`
- `len(case_studies) == 0` → 다른 도메인 강제 또는 사용자 안내
- `severity strong 0개 + notable < 2` → 부족하지만 진행 (보고서가 "특이 신호 적음" 명시)

### Round N (재시도 후)
- 같은 재시도를 2번 반복하지 않음
- max_rounds 3 도달 시 강제 진행

## 보고서 자동 보강 — Auto-fill 부연

eda-report의 `insights.py`가 inspector findings를 받아 인사이트 부연(`-` bullets)을 자동 채운다.

| signal | 자동 부연 |
|---|---|
| `temporal_peak` | "다음 순위 시간대(N건) 대비 +X%" / "일평균 대비 시간당 N배" |
| `head_heavy` | "상위 1% → X%, 5% → Y%" / "Gini Z" |
| `bot_suspect` | "user uid 활동 N건 (평균 대비 N배)" |
| `extreme_value` | "평균 value 3000+ 콘텐츠 N개 — top key (value)" |
| `sparsity` | "sparsity X% — cold-start 큰" |

**해석 라인은 여전히 Claude가 채움** — "왜?" 와 "그래서?" 는 사람의 도메인 지식 영역.

## 무엇이 달라졌나 — Before vs After

**Before (fixed chain)**:
```
✅ **시청 피크 시간대: 14시**
- _(부연: ...)_
- _(해석: ...)_
```

**After (agentic loop + auto-fill)**:
```
✅ **시청 피크 시간대: 14시 (187,454건)**
- 다음 순위 시간대(184,882건) 대비 +1.4%
- 일평균(19,414건/일) 대비 시간당 9.7배 — 정점이 뾰족
- _(해석: ← Claude가 채움)_

### 추가 발견 (suggestions에는 없지만 inspector가 포착)

✅ **[head_heavy] 상위 1% → 15.4%, 5% → 40.5%, Gini=0.716**
- 상위 1% 콘텐츠 = 전체 15.4% / 상위 5% = 40.5%
- Gini 0.716 — 콘텐츠 인기 매우 불균등
- _(권장: popularity-debias 또는 long-tail 강화 sampler 검토)_
```

## 한계 + 향후

- 현재 inspector는 mars 도메인 신호에 강함 — galaxy/adult/negative 도메인별 finder 추가 필요
- 재시도는 casestudy 파라미터 변경만 — 더 풍부한 재시도 (예: brief 재작성, 다른 main_file 시도) 가능
- Strong-severity finding이 0이면 보고서 첫 줄에 "특이 신호 적음 — 안정적 데이터" 자동 추가 (TODO)
