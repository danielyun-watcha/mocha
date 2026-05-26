# Theme 파일 형식

`themes/<name>.md` 형태로 정의. anthropics/skills/theme-factory 패턴을 따른다 — 단순한 markdown 파일에 색·폰트만 명시.

## 형식

```markdown
# Theme Name

## Primary Colors

- Dark: `#1a1a2e` — 텍스트, 강한 contrast
- Light: `#faf9f5` — 배경 (필요 시)
- Neutral Mid: `#8a8780` — 보조 텍스트, grid
- Neutral Light: `#e8e6dc` — 배경 분할

## Accent Colors (3-rotation)

- Warm: `#d97757` — 첫 번째 강조 (보통 orange/coral)
- Cool: `#6a9bcc` — 두 번째 강조 (보통 blue)
- Natural: `#788c5d` — 세 번째 강조 (보통 green)
- Critical: `#c93636` — 임계점/위험 (red)

## Typography

- Heading: Malgun Gothic Bold (또는 NotoSansKR Bold) — 24pt+
- Body: Malgun Gothic / NotoSansKR — 12~14pt
- Big numbers: 위 폰트 Bold 40~46pt

## Optimal Applications

이 테마가 어떤 용도에 적합한지 (예: 데이터 분석 보고서 / 프레젠테이션 / 외부 공유).
```

## render.py 의 파싱 규칙

`themes/<name>.md` 파일에서 다음 패턴으로 색 추출:

```python
import re
def parse_theme(theme_path):
    text = Path(theme_path).read_text()
    # `- <Name>: \`#RRGGBB\`` 패턴 매칭
    pattern = re.compile(r"-\s*([A-Za-z][\w\s]*?):\s*`(#[0-9a-fA-F]{6})`")
    colors = {}
    for m in pattern.finditer(text):
        key = m.group(1).strip().lower().replace(" ", "_")
        colors[key] = m.group(2)
    return colors
```

키는 lowercase + underscore. `dark`, `light`, `neutral_mid`, `accent_warm` 등.

## 사용 가능한 테마

- **watcha-default.md** — 라이트 배경 + 친화적 (Anthropic brand-guidelines 스타일)

추가 테마는 `themes/` 아래에 `.md` 파일로 만들고 위 형식 따르면 자동 사용 가능.

## 새 테마 만들기

1. `themes/<name>.md` 생성
2. 위 형식대로 8개 색 + 폰트 정의
3. `render.py --theme <name>` 으로 호출

색만 바뀌고 layout/타이포 규칙은 그대로.
