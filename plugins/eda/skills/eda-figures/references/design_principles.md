# 8개 디자인 원칙

PPT 스타일 정적 EDA figure를 만들 때 일관되게 적용한다. 모든 layout 모듈은 이 원칙을 따른다.

## 1. Non-data ink 최소화

차트의 본질이 아닌 시각 요소를 제거. matplotlib 기본값보다 깔끔.

```python
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.grid(axis="y", alpha=0.3)  # 필요한 축만, alpha 낮게
```

3D 효과·과한 색 그라데이션·장식용 테두리 금지.

## 2. annotate() + 화살표로 peak/anomaly 직접 표시

legend나 caption 대신 데이터 옆에 직접 표시 — MIT 2017 연구: 해석 속도 41% ↑.

```python
ax.annotate(
    "전체의 71.5%가\n10회 이상 시청 콘텐츠",
    xy=(3, 71.5), xytext=(1.5, 55),
    fontsize=12, weight="bold", color=COLOR["accent_red"],
    arrowprops=dict(arrowstyle="->", color=COLOR["accent_red"], lw=2),
    bbox=dict(boxstyle="round,pad=0.5", facecolor="#fff8e1",
              edgecolor=COLOR["accent_red"], linewidth=1.5),
)
```

## 3. 인사이트 박스 — 모든 figure에 1개

figure 하단(또는 그림 영역 외부)에 "이 그림에서 알 수 있는 한 줄"을 박스로.

```python
fig.text(0.5, -0.06, text, ha="center", fontsize=12, weight="bold",
         bbox=dict(boxstyle="round,pad=0.6", facecolor="#fff3e0",
                   edgecolor="#f57c00", linewidth=2))
```

박스 색은 통일 (`#fff3e0` 배경, `#f57c00` 테두리). 사용자가 figure 1장만 봐도 핵심 발견을 알 수 있게.

## 4. 3-tier 색상 + 3-accent 순환

theme에서 정의된 토큰 그대로 사용. 임의 색 X.

```
3-tier   : dark / neutral / light
3-accent : warm (#d97757) → cool (#6a9bcc) → natural (#788c5d)
critical : red (#c93636) — 임계점/위험 신호에만
```

순서대로 순환하면 figure 간 일관성 유지.

## 5. 한글 폰트 폴백

`assets/fonts/` 디렉토리 폴백 → 시스템 한글 폰트 → DejaVu. 자세한 건 `font_setup.md`.

```python
plt.rcParams["font.family"] = "Malgun Gothic"  # 또는 NotoSansKR
plt.rcParams["axes.unicode_minus"] = False
```

이모지 글리프 (📊 📈 등)는 한글 폰트에 없으면 □로 깨짐 — figure 텍스트에서 사용 금지.

## 6. DPI 240+ 출력

```python
plt.rcParams["figure.dpi"] = 120     # 화면 렌더
plt.rcParams["savefig.dpi"] = 240    # 출력 (보고서·노션 임베드)
plt.rcParams["savefig.bbox"] = "tight"
```

PDF 출력 옵션도 가능 (벡터). PNG가 기본 (노션 호환).

## 7. 폰트 위계 통일

분석 보고서용 figure는 본문보다 약간 크게.

```python
plt.rcParams.update({
    "axes.labelsize": 14,        # x/y label
    "axes.titlesize": 15,        # 차트 제목
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
    "legend.fontsize": 12,
    "font.size": 13,
})
```

크리티컬 숫자 (callout) 40pt+, 그 외 12~15pt.

## 8. 분석 결과 종류에 맞는 차트 선택

bar만 X. layout_catalog의 매핑 룰 준수:
- **비율** → pie / horizontal bar
- **분포 비교** → boxplot (분포 범위 크면 log scale)
- **시계열** → line + moving average
- **누적** → Lorenz curve
- **구간** → bar
- **2D** → bar + boxplot 2-panel

## Anti-patterns (피할 것)

| Anti-pattern | 대신 |
|---|---|
| 모든 figure가 bar | layout_catalog 매핑 |
| 막대 안에 단위 다른 텍스트 (예: "중앙값 821") | 박스 옆 별도 annotation |
| 텍스트 겹침 (label vs 막대 vs 통계 박스) | 위치 조정·rcParams 폰트 크기·figsize 확대 |
| caption만 있고 시각 강조 없음 | annotate() + bbox 활용 |
| 이모지 (한글 폰트 미지원) | 한글 단어 또는 ASCII |
| legend가 너무 많음 (10+ 카테고리) | direct labels |
| 3D 효과·gradient·decorative | 평면 + 깔끔 |
