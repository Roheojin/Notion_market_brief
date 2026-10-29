# -*- coding: utf-8 -*-
"""차트 공통 스타일 — 한글 폰트 · 팔레트 · 축 스타일 · 페이지 번호 도장.

원래 저장소의 cards.py에서 차트 분석 세션(chartpack.py)이 쓰는 부분만 옮긴 모듈입니다.
cards.py가 있는 저장소에서는 chartpack이 cards.py를 그대로 쓰고, 이 폴더처럼
cards.py가 없으면 이 파일을 씁니다 (색·폰트·여백 값은 cards.py와 동일).
"""
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

# ── 폰트 (한글 지원 — 리눅스 Noto CJK / 윈도우 맑은고딕 / 맥 애플고딕) ──
for _f in glob.glob("/usr/share/fonts/opentype/noto/NotoSansCJK*.ttc"):
    try:
        fm.fontManager.addfont(_f)
    except Exception:
        pass
_installed = {f.name for f in fm.fontManager.ttflist}
_CJK = next((name for name in [
    "Noto Sans CJK KR", "Noto Sans CJK JP", "Malgun Gothic",
    "NanumGothic", "Apple SD Gothic Neo", "AppleGothic",
] if name in _installed), None)
plt.rcParams["font.family"] = [_CJK] if _CJK else ["sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
# 달러 표기($4.71)가 수식으로 해석되지 않도록 (matplotlib 3.7+)
try:
    plt.rcParams["text.parse_math"] = False
except KeyError:
    pass
if _CJK is None:
    print("(경고: 한글 폰트를 찾지 못해 카드의 한글이 깨질 수 있습니다 — "
          "리눅스: fonts-noto-cjk 설치)")

# ── 팔레트 (라이트 기본 / CARD_THEME=dark 로 다크 전환) ──────
_C_LIGHT = {
    "page":    "#f9f9f7",
    "surface": "#efeeea",
    "ink":     "#0b0b0b",
    "ink2":    "#52514e",
    "muted":   "#898781",
    "grid":    "#e1e0d9",
    "axis":    "#c3c2b7",
    "up":      "#e34948",   # 상승 = 빨강 (국내 관례)
    "down":    "#2a78d6",   # 하락 = 파랑
    "ma5":     "#eb6834",
    "ma20":    "#c98500",
    "ma60":    "#1baf7a",
    "ma120":   "#4a3aa7",
    "bb":      "#898781",
    "cloud_up": "#1baf7a",
    "cloud_dn": "#e87ba4",
    "neutral": "#898781",
    "개인":   "#c98500",
    "외국인": "#1baf7a",
    "기관":   "#4a3aa7",
}

_C_DARK = {
    "page":    "#0d0d0d",
    "surface": "#1a1a19",
    "ink":     "#ffffff",
    "ink2":    "#c3c2b7",
    "muted":   "#898781",
    "grid":    "#2c2c2a",
    "axis":    "#383835",
    "up":      "#e66767",
    "down":    "#3987e5",
    "ma5":     "#d95926",
    "ma20":    "#c98500",
    "ma60":    "#199e70",
    "ma120":   "#9085e9",
    "bb":      "#898781",
    "cloud_up": "#199e70",
    "cloud_dn": "#d55181",
    "neutral": "#898781",
    "개인":   "#c98500",
    "외국인": "#199e70",
    "기관":   "#9085e9",
}

THEME = os.environ.get("CARD_THEME", "light").lower()
C = dict(_C_DARK if THEME == "dark" else _C_LIGHT)


def set_theme(name: str):
    """카드 테마 전환 (light/dark)."""
    global THEME
    THEME = (name or "light").lower()
    C.clear()
    C.update(_C_DARK if THEME == "dark" else _C_LIGHT)


W, H, DPI = 1080, 1350, 100
FIGSIZE = (W / DPI, H / DPI)


def _dir_color(v: float) -> str:
    return C["up"] if v > 0 else (C["down"] if v < 0 else C["muted"])


def _fmt_price(v: float, currency: str) -> str:
    if currency == "$":
        return f"${v:,.2f}"
    if currency == "원":
        return f"{v:,.0f}원"
    return f"{v:,.2f}"


def _style_ax(ax):
    ax.set_facecolor(C["surface"])
    for sp in ax.spines.values():
        sp.set_color(C["axis"])
        sp.set_linewidth(0.8)
    ax.tick_params(colors=C["muted"], labelsize=9, length=3)
    ax.grid(True, color=C["grid"], linewidth=0.6, alpha=0.9)
    ax.set_axisbelow(True)


def _verdict_style(verdict: str) -> tuple[str, str]:
    if "강세" in verdict:
        return C["up"], "▲ " + verdict
    if "약세" in verdict:
        return C["down"], "▼ " + verdict
    return C["neutral"], "● " + verdict


def stamp_pages(paths: list[str], handle: str | None = None):
    """카드 맨 아래에 페이지 번호(1 / N)와 계정 워터마크(IG_HANDLE)를 찍습니다."""
    from PIL import Image, ImageDraw, ImageFont

    handle = handle if handle is not None else os.environ.get("IG_HANDLE", "").strip()
    font_path = os.path.join(matplotlib.get_data_path(), "fonts", "ttf",
                             "DejaVuSans.ttf")
    try:
        f_page = ImageFont.truetype(font_path, 22)
        f_handle = ImageFont.truetype(font_path, 15)
    except Exception:
        f_page = f_handle = ImageFont.load_default()
    n = len(paths)
    for i, p in enumerate(paths, 1):
        try:
            im = Image.open(p).convert("RGB")
            d = ImageDraw.Draw(im)
            w, h = im.size
            d.text((36, h - 12), f"{i} / {n}", fill=C["muted"], font=f_page,
                   anchor="ls")
            if handle:
                d.text((w - 36, h - 12), handle, fill=C["muted"], font=f_handle,
                       anchor="rs")
            im.save(p)
        except Exception as e:
            print(f"  (페이지 번호 표시 실패 {os.path.basename(p)}: {e})")
