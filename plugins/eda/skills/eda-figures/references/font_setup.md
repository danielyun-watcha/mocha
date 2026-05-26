# 한글 폰트 폴백 시스템

EDA 보고서가 한국어이므로 한글 폰트 처리가 핵심. 환경마다 가용한 폰트가 달라서 폴백 체인이 필요하다.

## 폴백 순서

```
1. {CLAUDE_SKILL_DIR}/assets/fonts/NotoSansKR-Regular.otf  (있으면 우선)
2. {CLAUDE_SKILL_DIR}/assets/fonts/malgun.ttf              (기본 fallback)
3. 시스템 한글 폰트 (Malgun Gothic, AppleGothic 등)
4. DejaVu Sans (한글 깨짐, 마지막 보루)
```

## render.py 셋업 코드

```python
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm


def setup_korean_font(skill_dir: Path):
    """폰트 폴백 체인 적용."""
    candidates = [
        skill_dir / "assets/fonts/NotoSansKR-Regular.otf",
        skill_dir / "assets/fonts/malgun.ttf",
    ]
    chosen = None
    for p in candidates:
        if p.exists():
            fm.fontManager.addfont(str(p))
            font_name = fm.FontProperties(fname=str(p)).get_name()
            chosen = font_name
            break

    if chosen:
        plt.rcParams["font.family"] = chosen
    # else: 시스템 폰트 그대로 (Malgun Gothic 자동 인식되는 환경도 있음)

    plt.rcParams["axes.unicode_minus"] = False  # 마이너스 깨짐 방지
```

## 주의 사항

### 이모지 글리프 없음

`Malgun Gothic`, `NotoSansKR`, `DejaVu Sans` 모두 이모지 글리프 없음. figure 텍스트에 📊 📈 💡 같은 이모지 쓰면 □로 깨진다.

**대안**: 한글 단어 또는 ASCII 사용.

```python
# 나쁨
ax.set_title("📊 데이터셋 개요")

# 좋음
ax.set_title("데이터셋 개요")
```

### `unicode_minus` 설정

`plt.rcParams["axes.unicode_minus"] = False` 누락하면 음수 부호가 깨짐:

```
# unicode_minus=True (default): −1.0  (깨질 수 있음, 폰트에 글리프 없으면)
# unicode_minus=False         : -1.0  (ASCII hyphen, 안전)
```

### 시스템에 폰트 추가 (배포 시)

`assets/fonts/` 안에 폰트 파일을 동봉하면 환경 의존성 없음. malgun.ttf는 약 9MB이라 plugin 동봉 권장.

NotoSansKR는 Apache 2.0, malgun은 Microsoft Windows 폰트라 라이선스 주의. 사내 배포라면 NotoSansKR 다운로드 권장:

```bash
# NotoSansKR-Regular.otf (Apache 2.0)
curl -L "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/Korean/NotoSansCJKkr-Regular.otf" \
    -o assets/fonts/NotoSansKR-Regular.otf
```

## 동작 확인

```python
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = "Malgun Gothic"  # 또는 NotoSansKR
plt.text(0.5, 0.5, "한글 테스트 — 가나다라마바사", ha="center", fontsize=20)
plt.axis("off")
plt.savefig("/tmp/font_test.png", dpi=150)
```

생성된 PNG에서 한글이 안 깨지면 OK.
