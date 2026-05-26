"""모든 layout이 공유하는 공통 helper."""
import matplotlib.pyplot as plt


def insight_box_fig(fig, text: str) -> None:
    """그림 하단 인사이트 박스 (digit 8 원칙)."""
    fig.text(0.5, -0.06, text, ha="center", fontsize=12, weight="bold",
             bbox=dict(boxstyle="round,pad=0.6", facecolor="#fff3e0",
                       edgecolor="#f57c00", linewidth=2))


def clean_spines(ax) -> None:
    """Non-data ink 제거."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def accent_cycle(theme: dict) -> list:
    """3-accent 순환."""
    return [
        theme.get("accent_warm", "#d97757"),
        theme.get("accent_cool", "#6a9bcc"),
        theme.get("accent_natural", "#788c5d"),
    ]
