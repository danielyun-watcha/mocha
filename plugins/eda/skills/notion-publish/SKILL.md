---
name: notion-publish
description: Markdown 파일을 받아 사용자에게 부모 페이지 경로/URL을 물은 후, 그 아래에 새 자식 페이지를 만들어 내용을 push한다. EDA 리포트 또는 일반 MD를 Notion에 게시할 때 사용.
allowed-tools: Read, AskUserQuestion, Bash(python3 *), Bash(ls *)
argument-hint: <md_path> [--parent <notion_url_or_id>] [--title <override>]
---

# Notion Publish

Markdown 파일을 Notion 새 페이지로 업로드한다. 정확한 부모 페이지 경로를 사용자에게 물어보고 그 아래에 페이지를 만든다.

---

## 워크플로

### 1. MD 읽기

`Read`로 인자 `$ARGUMENTS`의 MD 파일을 로드한다. 다음을 추출:
- **제목**: 첫 H1 (`# 제목`). 없으면 파일명에서 유추.
- **본문**: 첫 H1 다음의 모든 내용.
- **이미지 경로**: `![alt](path)` 패턴 — 로컬 경로만 추출해 사용자에게 한계 안내용으로 보관.

### 2. 부모 페이지 경로 물어보기

`--parent` 인자가 주어지지 않았다면 `AskUserQuestion`으로 정확히 묻는다:

```
질문: "Notion 어디에 페이지를 만들까요?"
header: "부모 페이지"
옵션 예시:
  - "최근에 사용한 페이지에 검색" (검색 워크플로)
  - "URL/ID 직접 입력" (사용자가 페이지 URL 또는 ID를 알고 있을 때)
```

사용자가 URL을 주면 마지막 32자(또는 마지막 `-` 뒤 hex)에서 page_id를 추출한다.
사용자가 키워드를 주면 `mcp__claude_ai_Notion__notion-search`로 검색하고 후보 3개 정도 보여준 뒤 다시 묻는다.

### 3. 부모 페이지 검증

`mcp__claude_ai_Notion__notion-fetch`로 page_id가 실제로 존재하는지 확인. 없으면 사용자에게 다시 묻는다 (URL 잘못된 경우).

### 4. 새 자식 페이지 생성

`mcp__claude_ai_Notion__notion-create-pages` 호출:

```yaml
parent:
  page_id: <검증된 부모 ID>
pages:
  - properties:
      title: <H1에서 추출한 제목 — 또는 --title 인자>
    content: <MD 본문 — 그대로 또는 Notion 호환 마크다운으로 변환>
```

MD 본문은 대체로 Notion이 마크다운을 그대로 받아들이지만, 다음은 주의:
- **이미지**: 로컬 경로(`![](file:///...)` 또는 상대경로)는 Notion에서 렌더 안 됨. 그대로 두되 사용자에게 안내.
- **표**: 마크다운 표는 Notion이 자동 변환.
- **이모지**: 그대로 유지.

### 5. 결과 보고

생성된 페이지 URL을 사용자에게 출력. 이미지 한계 안내 포함.

```
✅ Notion 페이지 생성 완료
   제목: [도메인] EDA 리포트
   URL: https://www.notion.so/<...>
   ⚠ 로컬 이미지 N개는 별도 첨부 필요 — Notion API가 로컬 파일 업로드 미지원.
```

---

## 사용 예시

### Case 1: 사용자가 부모 URL 명시
```
notion-publish /tmp/eda/graph_modeling_20260519/EDA_REPORT.md \
    --parent https://www.notion.so/workspace/EDA-Reports-abc123def456...
```
→ 바로 4단계로 진입, 새 페이지 생성.

### Case 2: 사용자가 부모 미지정
```
notion-publish /tmp/eda/graph_modeling_20260519/EDA_REPORT.md
```
→ "Notion 어디에 페이지를 만들까요?" 대화 → URL 또는 검색어 받음 → 검증 후 생성.

### Case 3: 제목 override
```
notion-publish report.md --title "2026 Q2 Mars EDA 정기 분석"
```
→ MD의 H1 무시하고 인자 제목 사용.

---

## 한계 (사용자에게 미리 안내해야 함)

| 한계 | 우회법 |
|---|---|
| 로컬 PNG 이미지 업로드 미지원 | S3/Imgur 등에 먼저 호스팅 후 URL로 교체 |
| Notion 통합 권한 필요 | 부모 페이지가 Claude integration에 access된 워크스페이스여야 함 |
| 대용량 MD (>1MB) | Notion 블록 한계 — 챕터별 분할 검토 |
| 코드 블록 언어 자동 인식 | 일부 안 됨 — fence에 명시 (` ```python `) |

---

## Resources

### Scripts

- `scripts/extract_meta.py` — MD에서 제목/본문/이미지 경로 추출 (선택적 사용)

### References

- `references/notion_markdown_compat.md` — Notion 마크다운 호환 가이드
