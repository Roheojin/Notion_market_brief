# -*- coding: utf-8 -*-
"""차트 분석 세션 (--session chart) — 아침 06:20 KST.

미국장 마감 직후, 나스닥100·S&P500 마감 차트와 전일 코스피 차트를 함께 분석합니다.

인스타 카드 함수(make_chart_card · make_chart_cover · build_chart_caption)는
남아 있지만, 노션 전용으로 바꿔서 실행 흐름에서는 쓰지 않습니다.

블로그 팩 (output/blog_YYYYMMDD/):
  붙여넣기용 본문 텍스트(지표별 상세 분석) + 차트 이미지
  — 증권사 앱 형식 1장(가격·이평·일목·BB / 거래량 / MACD / RSI), 일봉·주봉 각각

지표 판단 로그 (history/chart_log.csv):
  카테고리별 점수를 매일 축적 → 1달 주기로 적중률을 계산해
  history/indicator_weights.json 의 가중치를 조정하는 피드백의 기반

노션 아카이브 (marketbrief/notion.py):
  블로그 팩(본문.txt + 이미지 + summary.json)을 노션 DB에 하루 1페이지로 게시
  — --post 실행(post_notion.bat) 또는 NOTION_FORCE=1 일 때, NOTION_TOKEN이 있으면
"""
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    from .cards import (C, DPI, FIGSIZE, _dir_color, _fmt_price, _style_ax,
                        _verdict_style, stamp_pages)
except ImportError:      # 차트 분석 전용 폴더 — cards.py 대신 chartstyle.py
    from .chartstyle import (C, DPI, FIGSIZE, _dir_color, _fmt_price, _style_ax,
                             _verdict_style, stamp_pages)
from .config import (CHART_INDICES, CHART_PARAMS, DISCLAIMER, ECON_CALENDAR,
                     PARAMS)
from .fetch import FLOW_LONG_DAYS, fetch_daily, sample_daily, sample_flows
from .indicators import add_indicators, to_weekly
from .signals import (Signal, _crossed_above, _crossed_below, _verdict,
                      daily_signal_set, signals_flows, weekly_signal_set)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")
HIST_DIR = os.path.join(ROOT, "history")
WEIGHTS_PATH = os.path.join(HIST_DIR, "indicator_weights.json")
CHART_LOG = os.path.join(HIST_DIR, "chart_log.csv")

KST = ZoneInfo("Asia/Seoul")
WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]

# 일목 보조 요소 색 — 이평선과 헷갈리지 않게 색 + 점선(이중 인코딩)으로 구분
COL_TENKAN = "#e0507a"   # 전환선 (장미)
COL_KIJUN = "#3d5aa8"    # 기준선 (남청)
COL_CHIKOU = "#8a8880"   # 후행스팬 (회색)

MARKET_LABEL = {"kr": "한국장", "us": "미국장"}
# 실행 시장별 지수 묶음 (니케이는 한국장과 같은 시각 마감, 비트코인은 미국장 마감 시점)
MARKET_GROUP = {"kr": ("KR", "JP", "CN"), "us": ("US", "CRYPTO")}

CATEGORIES = ["이평선", "일목", "볼린저", "RSI", "MACD", "거래량", "수급"]

HASHTAGS_CHART = ("#차트분석 #기술적분석 #코스피 #나스닥100 #S&P500 "
                  "#일목균형표 #이동평균선 #볼린저밴드 #RSI #MACD #주식공부")


# ──────────────────────────────────────────────────────────────
# MACD 신호 (일봉/주봉 공용)
# ──────────────────────────────────────────────────────────────

def sig_macd(df: pd.DataFrame, tf: str = "일봉") -> list[Signal]:
    s: list[Signal] = []
    if "macd" not in df.columns or pd.isna(df["macd_sig"].iloc[-1]):
        return s
    m, ms, h = df["macd"], df["macd_sig"], df["macd_hist"]
    horizon = "short" if tf == "일봉" else "long"
    lb = 3 if tf == "일봉" else 2
    unit = "일" if tf == "일봉" else "주"

    def _sig(direction, strength, title, desc):
        s.append(Signal("MACD", direction, strength, title, desc,
                        horizon=horizon, tf=tf))

    if _crossed_above(m, ms, lb):
        _sig(+1, 2, f"MACD 골든크로스({tf})",
             f"MACD가 시그널선을 상향 돌파 — {unit}봉 모멘텀 개선")
    elif _crossed_below(m, ms, lb):
        _sig(-1, 2, f"MACD 데드크로스({tf})",
             f"MACD가 시그널선을 하향 이탈 — {unit}봉 모멘텀 약화")

    zero = m * 0.0
    if _crossed_above(m, zero, lb):
        _sig(+1, 1, f"MACD 0선 상향({tf})",
             "MACD가 0선 위로 — 중심 추세가 상승 쪽으로 전환")
    elif _crossed_below(m, zero, lb):
        _sig(-1, 1, f"MACD 0선 하향({tf})",
             "MACD가 0선 아래로 — 중심 추세가 하락 쪽으로 전환")

    hh = h.dropna()
    if len(hh) >= 4:
        h1, h2, h3 = hh.iloc[-1], hh.iloc[-2], hh.iloc[-3]
        if h1 < 0 and h1 > h2 > h3:
            _sig(+1, 1, f"히스토그램 개선({tf})",
                 "마이너스 히스토그램이 3연속 축소 — 반등 준비 신호")
        elif h1 > 0 and h1 < h2 < h3:
            _sig(-1, 1, f"히스토그램 약화({tf})",
                 "플러스 히스토그램이 3연속 축소 — 상승 탄력 둔화")
    return s


# ──────────────────────────────────────────────────────────────
# RSI 시그널(9) 교차 + 상승/하락 다이버전스 — 마지막 봉 기준
# ──────────────────────────────────────────────────────────────

def sig_rsi_signal(df: pd.DataFrame, tf: str = "일봉") -> list[Signal]:
    """RSI(14)와 시그널선(9기간 이평)의 교차 — 최근 발생분만."""
    s: list[Signal] = []
    if "rsi_sig" not in df.columns or pd.isna(df["rsi_sig"].iloc[-1]):
        return s
    horizon = "short" if tf == "일봉" else "long"
    lb = 3 if tf == "일봉" else 2
    if _crossed_above(df["rsi"], df["rsi_sig"], lb):
        s.append(Signal("RSI", +1, 1, f"RSI 시그널 상향 교차({tf})",
                        "RSI가 시그널선(9) 위로 올라섬 — 모멘텀 회복",
                        horizon=horizon, tf=tf))
    elif _crossed_below(df["rsi"], df["rsi_sig"], lb):
        s.append(Signal("RSI", -1, 1, f"RSI 시그널 하향 교차({tf})",
                        "RSI가 시그널선(9) 아래로 내려섬 — 모멘텀 이탈",
                        horizon=horizon, tf=tf))
    return s


def _pivot_idx(vals: np.ndarray, mode: str, wing: int = 3) -> list[int]:
    """좌우 wing봉보다 낮은(높은) 지점 = 피벗 저점(고점)."""
    idx: list[int] = []
    for i in range(wing, len(vals) - wing):
        seg = vals[i - wing:i + wing + 1]
        if np.isnan(seg).any():
            continue
        if mode == "low" and vals[i] <= seg.min():
            idx.append(i)
        elif mode == "high" and vals[i] >= seg.max():
            idx.append(i)
    return idx


def detect_divergence(d: pd.DataFrame, recent: int = 20,
                      max_span: int = 45, min_span: int = 5) -> list[dict]:
    """표시 구간 d 내 가격/RSI 피벗 비교 — 상승·하락 다이버전스.

    마지막 종가 기준: 두 번째 피벗이 최근 recent봉 이내일 때만 유효 신호.
    피벗 간격은 min_span~max_span봉으로 제한 (너무 먼 연결 방지).
    반환: kind(bull/bear), i1·i2(표시 구간 x 인덱스), p1·p2(가격), r1·r2(RSI)
    """
    out: list[dict] = []
    lows = d["low"].to_numpy(dtype=float)
    highs = d["high"].to_numpy(dtype=float)
    rsi = d["rsi"].to_numpy(dtype=float)
    n = len(d)

    def _match(piv: list[int], vals: np.ndarray, kind: str):
        if len(piv) < 2:
            return
        i2 = piv[-1]
        if i2 < n - recent:
            return
        for i1 in reversed(piv[:-1]):        # 가까운 이전 피벗부터
            span = i2 - i1
            if span < min_span:
                continue
            if span > max_span:
                break
            if kind == "bull" and vals[i2] < vals[i1] * 0.999 \
                    and rsi[i2] > rsi[i1] + 1.0:
                out.append(dict(kind="bull", i1=i1, i2=i2,
                                p1=vals[i1], p2=vals[i2],
                                r1=rsi[i1], r2=rsi[i2]))
                return
            if kind == "bear" and vals[i2] > vals[i1] * 1.001 \
                    and rsi[i2] < rsi[i1] - 1.0:
                out.append(dict(kind="bear", i1=i1, i2=i2,
                                p1=vals[i1], p2=vals[i2],
                                r1=rsi[i1], r2=rsi[i2]))
                return

    _match([i for i in _pivot_idx(lows, "low") if not np.isnan(rsi[i])],
           lows, "bull")
    _match([i for i in _pivot_idx(highs, "high") if not np.isnan(rsi[i])],
           highs, "bear")
    return out


def sig_divergence(divs: list[dict], tf: str) -> list[Signal]:
    horizon = "short" if tf == "일봉" else "long"
    s: list[Signal] = []
    for dv in divs:
        if dv["kind"] == "bull":
            s.append(Signal("RSI", +1, 2, f"상승 다이버전스({tf})",
                            "주가는 저점을 낮췄지만 RSI 저점은 높아짐 — "
                            "하락 탄력 소진, 반전 관찰",
                            horizon=horizon, tf=tf))
        else:
            s.append(Signal("RSI", -1, 2, f"하락 다이버전스({tf})",
                            "주가는 고점을 높였지만 RSI 고점은 낮아짐 — "
                            "상승 탄력 소진, 조정 경계",
                            horizon=horizon, tf=tf))
    return s


# ──────────────────────────────────────────────────────────────
# 지표 가중치 (월간 피드백으로 조정) + 판단 로그
# ──────────────────────────────────────────────────────────────

def load_weights() -> dict:
    """history/indicator_weights.json — 없으면 전부 1.0."""
    try:
        with open(WEIGHTS_PATH, encoding="utf-8") as f:
            return {k: float(v) for k, v in json.load(f).items()}
    except Exception:
        return {}


def weighted_score(sigs: list[Signal], weights: dict) -> float:
    return sum(s.score * float(weights.get(s.category, 1.0)) for s in sigs)


def log_chart(now: dt.datetime, name: str, tf: str, sigs: list[Signal],
              close: float):
    """카테고리별 점수를 매일 축적 (무신호 카테고리는 0으로 — 피드백 계산용)."""
    try:
        os.makedirs(HIST_DIR, exist_ok=True)
        per = {c: 0.0 for c in CATEGORIES}
        for s in sigs:
            per[s.category] = per.get(s.category, 0.0) + s.score
        new = not os.path.exists(CHART_LOG)
        with open(CHART_LOG, "a", encoding="utf-8-sig") as f:
            if new:
                f.write("date,name,tf,category,score,close\n")
            for c, v in per.items():
                f.write(f"{now:%Y-%m-%d},{name},{tf},{c},{v:+.1f},{close:.2f}\n")
    except Exception as e:
        print(f"  (차트 로그 저장 실패: {e})")


# ──────────────────────────────────────────────────────────────
# 그리기 공통
# ──────────────────────────────────────────────────────────────

def _candles(ax, x, d, body_w=0.62, wick_w=1.0, up_col=None, dn_col=None):
    up_col, dn_col = up_col or C["up"], dn_col or C["down"]
    up = (d["close"] >= d["open"]).to_numpy()
    ax.vlines(x, d["low"], d["high"],
              colors=np.where(up, up_col, dn_col), lw=wick_w, zorder=3)
    ax.bar(x[up], (d["close"] - d["open"])[up], body_w, bottom=d["open"][up],
           color=up_col, zorder=4)
    ax.bar(x[~up], (d["open"] - d["close"])[~up], body_w,
           bottom=d["close"][~up], color=dn_col, zorder=4)
    return up


def _last_price_tag(ax, d):
    """트레이딩뷰식 현재가 표시 — 마지막 종가 점선 + 오른쪽 가격축 색 태그."""
    close = float(d["close"].iloc[-1])
    col = C["up"] if close >= float(d["open"].iloc[-1]) else C["down"]
    ax.axhline(close, color=col, lw=0.8, ls=(0, (2, 2)), alpha=0.9, zorder=5)
    ax.annotate(f"{close:,.2f}", xy=(1, close),
                xycoords=("axes fraction", "data"), xytext=(3, 0),
                textcoords="offset points", ha="left", va="center",
                fontsize=8.5, weight="bold", color="#ffffff", zorder=8,
                annotation_clip=False,
                bbox=dict(boxstyle="square,pad=0.25", facecolor=col,
                          edgecolor="none"))
    # 태그와 겹치는 가격축 눈금 숫자는 숨김 (트레이딩뷰처럼)
    lo, hi = ax.get_ylim()
    gap = _pt_to_data(ax, 8.5 * 1.6)
    ax.set_yticks([t for t in ax.get_yticks()
                   if lo <= t <= hi and abs(t - close) >= gap])


def _pt_to_data(ax, pt: float) -> float:
    """글자 크기(pt)를 그 축의 y 데이터 단위로 환산."""
    lo, hi = ax.get_ylim()
    h_px = ax.get_window_extent().height or 1.0
    return (hi - lo) * (pt * ax.figure.dpi / 72) / h_px


def _spread_labels(ys, gap: float, hi: float) -> np.ndarray:
    """라벨 y 위치를 서로 gap 이상 떨어지게 벌림 (위아래 순서 유지, 위쪽 hi 넘지 않게)."""
    ys = np.asarray(ys, dtype=float)
    order = np.argsort(ys)
    pos = ys[order].copy()
    for i in range(1, len(pos)):
        pos[i] = max(pos[i], pos[i - 1] + gap)
    if len(pos) and pos[-1] > hi:
        pos[-1] = hi
        for i in range(len(pos) - 2, -1, -1):
            pos[i] = min(pos[i], pos[i + 1] - gap)
    out = np.empty_like(pos)
    out[order] = pos
    return out


def _future_cloud(df: pd.DataFrame, fwd: int):
    """마지막 봉 이후 fwd봉의 선행스팬 A/B (아직 shift 안 된 원값 꼬리)."""
    ich = PARAMS["ichimoku"]
    raw_a = ((df["tenkan"] + df["kijun"]) / 2).to_numpy(dtype=float)
    raw_b = ((df["high"].rolling(ich["senkou_b"]).max()
              + df["low"].rolling(ich["senkou_b"]).min()) / 2).to_numpy(dtype=float)
    return raw_a[-fwd:], raw_b[-fwd:]


def _draw_trend(ax, df: pd.DataFrame, n_bars: int, fwd: int,
                tf: str, legend: bool = True):
    """캔들 + 이평선 + 일목균형표. 우측 fwd봉 선행 구름 포함. 표시 구간 d 반환."""
    d = df.tail(n_bars)
    x = np.arange(len(d))

    # 구름 (표시 구간)
    a = d["senkou_a"].to_numpy(dtype=float)
    b = d["senkou_b"].to_numpy(dtype=float)
    valid = ~(np.isnan(a) | np.isnan(b))
    ax.fill_between(x, a, b, where=valid & (a >= b), color=C["cloud_up"],
                    alpha=0.16, linewidth=0, interpolate=True)
    ax.fill_between(x, a, b, where=valid & (a < b), color=C["cloud_dn"],
                    alpha=0.14, linewidth=0, interpolate=True)
    ax.plot(x, a, color=C["cloud_up"], lw=0.7, alpha=0.6)
    ax.plot(x, b, color=C["cloud_dn"], lw=0.7, alpha=0.6)

    # 선행 구름 — 마지막 봉 이후 fwd봉 전체 (잘리지 않게)
    fa, fb = _future_cloud(df, fwd)
    if len(fa) and not (np.isnan(a[-1]) or np.isnan(b[-1])):
        xf = np.arange(len(d) - 1, len(d) - 1 + len(fa) + 1)
        af = np.concatenate([[a[-1]], fa])
        bf = np.concatenate([[b[-1]], fb])
        vf = ~(np.isnan(af) | np.isnan(bf))
        ax.fill_between(xf, af, bf, where=vf & (af >= bf), color=C["cloud_up"],
                        alpha=0.16, linewidth=0, interpolate=True)
        ax.fill_between(xf, af, bf, where=vf & (af < bf), color=C["cloud_dn"],
                        alpha=0.14, linewidth=0, interpolate=True)
        ax.plot(xf, af, color=C["cloud_up"], lw=0.7, alpha=0.6)
        ax.plot(xf, bf, color=C["cloud_dn"], lw=0.7, alpha=0.6)

    # 전환선/기준선 (점선) + 후행스팬 (종가를 26봉 뒤로 — 왼쪽으로 이동한 회색 선)
    ax.plot(x, d["tenkan"], color=COL_TENKAN, lw=1.3, ls=(0, (5, 2)),
            label="전환선", zorder=5)
    ax.plot(x, d["kijun"], color=COL_KIJUN, lw=1.3, ls=(0, (5, 2)),
            label="기준선", zorder=5)
    ax.plot(x, d["chikou"], color=COL_CHIKOU, lw=1.2, alpha=0.9,
            label="후행스팬", zorder=2)

    # 이평선
    for w_, key in [(5, "ma5"), (20, "ma20"), (60, "ma60"), (120, "ma120")]:
        u = "" if tf == "일봉" else ""
        ax.plot(x, d[key], color=C[key], lw=1.5, label=f"MA{w_}", zorder=4)

    _candles(ax, x, d)
    _style_ax(ax)

    # y 범위: 캔들 + 구름(선행 포함) + 이평선 모두 포함
    parts = [d["low"].to_numpy(dtype=float), d["high"].to_numpy(dtype=float),
             a, b]
    if len(fa):
        parts += [fa, fb]
    allv = np.concatenate([p[~np.isnan(p)] for p in parts if len(p)])
    lo, hi = float(allv.min()), float(allv.max())
    span = (hi - lo) or 1.0
    # 위쪽은 범례 자리를 여유 있게 (범례가 캔들·구름을 가리지 않도록)
    ax.set_ylim(lo - span * 0.04, hi + span * 0.11)
    ax.set_xlim(-1, len(d) - 1 + fwd + 2)
    _last_price_tag(ax, d)

    if legend:
        ax.legend(loc="upper left", fontsize=8.5, ncols=7, frameon=False,
                  labelcolor=C["ink2"], handlelength=1.3, columnspacing=0.9,
                  borderaxespad=0.2)

    # x축 날짜 라벨
    ticks = np.linspace(0, len(d) - 1, 6).astype(int)
    fmt = "%y.%m.%d" if tf == "일봉" else "%y.%m"
    ax.set_xticks(ticks)
    ax.set_xticklabels([d.index[i].strftime(fmt) for i in ticks], fontsize=9)
    ax.tick_params(labelbottom=True)
    return d, x, ticks


def _draw_bb(ax, d, x, divs: list[dict] | None = None):
    ax.fill_between(x, d["bb_up"], d["bb_dn"], color=C["bb"], alpha=0.10,
                    linewidth=0)
    ax.plot(x, d["bb_up"], color=C["bb"], lw=1.0, ls=(0, (4, 3)), alpha=0.9,
            label="볼린저(20,2σ)")
    ax.plot(x, d["bb_dn"], color=C["bb"], lw=1.0, ls=(0, (4, 3)), alpha=0.9)
    ax.plot(x, d["bb_mid"], color=C["bb"], lw=1.0, alpha=0.8)
    _candles(ax, x, d, body_w=0.55, wick_w=0.8)
    # 다이버전스 가격 연결선 (피벗 저점/고점)
    for dv in (divs or []):
        col = C["up"] if dv["kind"] == "bull" else C["down"]
        ax.plot([dv["i1"], dv["i2"]], [dv["p1"], dv["p2"]], color=col,
                lw=1.7, alpha=0.95, zorder=6, solid_capstyle="round")
        ax.scatter([dv["i1"], dv["i2"]], [dv["p1"], dv["p2"]], s=16,
                   color=col, zorder=7)
    _style_ax(ax)
    vals = np.concatenate([d["low"].to_numpy(dtype=float),
                           d["high"].to_numpy(dtype=float),
                           d["bb_up"].dropna().to_numpy(dtype=float),
                           d["bb_dn"].dropna().to_numpy(dtype=float)])
    vals = vals[~np.isnan(vals)]
    lo, hi = float(vals.min()), float(vals.max())
    pad = (hi - lo) * 0.06 or 1.0
    ax.set_ylim(lo - pad, hi + pad)
    _last_price_tag(ax, d)
    ax.legend(loc="upper left", fontsize=8.5, frameon=False,
              labelcolor=C["ink2"], handlelength=1.3)


def _draw_vol(ax, d, x, unit_label="거래량"):
    vol = d["volume"].to_numpy(dtype=float)
    if not np.isfinite(vol).any() or np.nanmax(vol) <= 0:
        ax.text(0.5, 0.5, "지수 거래량 데이터 미제공", color=C["muted"],
                fontsize=10, ha="center", va="center", transform=ax.transAxes)
        _style_ax(ax)
        ax.set_yticks([])
        ax.set_ylabel(unit_label, color=C["muted"], fontsize=9)
        return
    up = (d["close"] >= d["open"]).to_numpy()
    ax.bar(x, vol, 0.62, color=np.where(up, C["up"], C["down"]), alpha=0.85)
    ax.plot(x, d["vol_ma"], color=C["ink2"], lw=1.1)
    # 마지막 봉 기준 거래량 변화 마커 (급증 ×배수 / 한산)
    ratio = d["vol_ratio"].iloc[-1]
    if pd.notna(ratio) and np.isfinite(vol[-1]):
        r = float(ratio)
        if r >= 1.5:
            col = C["up"] if bool(up[-1]) else C["down"]
            ax.annotate(f"×{r:.1f}", xy=(x[-1], vol[-1]),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=9.5, weight="bold",
                        color=col, zorder=6)
        elif r <= 0.5:
            ax.annotate(f"한산 ×{r:.1f}", xy=(x[-1], vol[-1]),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=8.5,
                        color=C["muted"], zorder=6)
    _style_ax(ax)
    ax.set_yticks([])
    ax.set_ylabel(unit_label, color=C["muted"], fontsize=9)


def _draw_rsi(ax, d, x, label="RSI(14)", divs: list[dict] | None = None):
    ax.plot(x, d["rsi"], color=C["ma20"], lw=1.6, label="RSI(14)")
    if "rsi_sig" in d.columns:
        ax.plot(x, d["rsi_sig"], color=C["ma120"], lw=1.1, alpha=0.95,
                label="시그널(9)")
    for lv, ls in [(70, "--"), (50, ":"), (30, "--")]:
        ax.axhline(lv, color=C["muted"], lw=0.8, ls=ls, alpha=0.7)
    ax.fill_between(x, 70, d["rsi"], where=d["rsi"] >= 70, color=C["up"],
                    alpha=0.25, interpolate=True)
    ax.fill_between(x, d["rsi"], 30, where=d["rsi"] <= 30, color=C["down"],
                    alpha=0.25, interpolate=True)
    # 다이버전스 연결선 + 라벨 (RSI 피벗)
    for dv in (divs or []):
        bull = dv["kind"] == "bull"
        col = C["up"] if bull else C["down"]
        ax.plot([dv["i1"], dv["i2"]], [dv["r1"], dv["r2"]], color=col,
                lw=1.8, alpha=0.95, zorder=6, solid_capstyle="round")
        ax.scatter([dv["i1"], dv["i2"]], [dv["r1"], dv["r2"]], s=16,
                   color=col, zorder=7)
        # 라벨은 점 왼쪽에 — 오른쪽 가격축 숫자와 겹치지 않게
        ax.annotate("상승 다이버전스" if bull else "하락 다이버전스",
                    xy=(dv["i2"], dv["r2"]),
                    xytext=(-5, -11 if bull else 7), textcoords="offset points",
                    ha="right", fontsize=8.5, weight="bold", color=col,
                    zorder=7)
    _style_ax(ax)
    ax.set_ylim(0, 100)
    ax.set_yticks([30, 50, 70])
    ax.set_ylabel(label, color=C["muted"], fontsize=9)
    ax.legend(loc="upper left", fontsize=7.5, ncols=2, frameon=False,
              labelcolor=C["ink2"], handlelength=1.1, columnspacing=0.8,
              borderaxespad=0.15)


def _draw_macd(ax, d, x):
    h = d["macd_hist"].to_numpy(dtype=float)
    pos = h >= 0
    ax.bar(x[pos], h[pos], 0.62, color=C["up"], alpha=0.45)
    ax.bar(x[~pos], h[~pos], 0.62, color=C["down"], alpha=0.45)
    ax.plot(x, d["macd"], color=C["ma20"], lw=1.5, label="MACD(12,26)")
    ax.plot(x, d["macd_sig"], color=C["ma120"], lw=1.2, label="시그널(9)")
    ax.axhline(0, color=C["muted"], lw=0.8, alpha=0.8)
    _style_ax(ax)
    ax.set_ylabel("MACD", color=C["muted"], fontsize=9)
    ax.legend(loc="upper left", fontsize=8, ncols=2, frameon=False,
              labelcolor=C["ink2"], handlelength=1.2, columnspacing=0.9)


# ──────────────────────────────────────────────────────────────
# 인스타 카드
# ──────────────────────────────────────────────────────────────

def make_chart_card(row: dict, tf: str, date_str: str, path: str):
    """지수 1개 × 시간축 1개 카드.

    상단(추세): 캔들+이평선+일목균형표 — 우측 26봉 선행 구름 여백 확보
    하단(모멘텀): 볼린저 / 거래량 / RSI / MACD
    """
    meta, df = row["meta"], (row["df"] if tf == "일봉" else row["dfw"])
    n = CHART_PARAMS["daily_bars"] if tf == "일봉" else CHART_PARAMS["weekly_bars"]
    fwd = CHART_PARAMS["forward"]
    verdict = row["vd"] if tf == "일봉" else row["vw"]
    score = row["sc_d"] if tf == "일봉" else row["sc_w"]

    fig = plt.figure(figsize=FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor(C["page"])

    gs = fig.add_gridspec(
        5, 1, height_ratios=[4.4, 1.8, 0.8, 1.0, 1.1],
        left=0.075, right=0.955, top=0.826, bottom=0.048, hspace=0.34,
    )
    ax_t = fig.add_subplot(gs[0])
    ax_b = fig.add_subplot(gs[1])
    ax_v = fig.add_subplot(gs[2])
    ax_r = fig.add_subplot(gs[3])
    ax_m = fig.add_subplot(gs[4])

    # ── 헤더 ──
    close = float(df["close"].iloc[-1])
    prev = float(df["close"].iloc[-2])
    chg = (close / prev - 1) * 100
    unit = "전일 대비" if tf == "일봉" else "전주 대비"
    fig.text(0.075, 0.962, meta["name"], color=C["ink"], fontsize=30,
             weight="bold")
    fig.text(0.075, 0.940, f"{meta['ticker']} · {date_str}", color=C["muted"],
             fontsize=11.5)
    fig.text(0.075, 0.900, _fmt_price(close, meta["currency"]),
             color=C["ink"], fontsize=23, weight="bold")
    arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "—")
    fig.text(0.075, 0.878, f"{arrow} {chg:+.2f}%  ({unit})",
             color=_dir_color(chg), fontsize=13.5, weight="bold")

    # 시간축 뱃지 + 판단 뱃지 (우측 상단)
    tf_desc = "단기" if tf == "일봉" else "중장기"
    fig.text(0.955, 0.956, f"{tf}  ·  {tf_desc}", color=C["ink"],
             fontsize=16, weight="bold", ha="right",
             bbox=dict(boxstyle="round,pad=0.45", facecolor=C["surface"],
                       edgecolor=C["axis"], linewidth=1.2))
    vc, vb = _verdict_style(verdict)
    fig.text(0.955, 0.908, vb, color=vc, fontsize=16, weight="bold", ha="right",
             bbox=dict(boxstyle="round,pad=0.45", facecolor=C["surface"],
                       edgecolor=vc, linewidth=1.4))
    fig.text(0.955, 0.874, f"지표 종합 스코어 {score:+.1f}", color=C["ink2"],
             fontsize=10.5, ha="right")

    # ── 상단: 추세 (이평선 + 일목) ──
    d, x, ticks = _draw_trend(ax_t, df, n, fwd, tf)
    ax_t.set_title("추세 — 이동평균선 · 일목균형표", color=C["ink2"],
                   fontsize=11, weight="bold", loc="left", pad=6)

    # ── 하단: 모멘텀 (볼린저 / 거래량 / RSI / MACD) ──
    divs = row.get("div_d") if tf == "일봉" else row.get("div_w")
    _draw_bb(ax_b, d, x, divs)
    ax_b.set_title("모멘텀 — 볼린저밴드 · 거래량 · RSI · MACD", color=C["ink2"],
                   fontsize=11, weight="bold", loc="left", pad=6)
    _draw_vol(ax_v, d, x)
    rsi_label = "RSI(14)" if tf == "일봉" else "주봉 RSI"
    _draw_rsi(ax_r, d, x, rsi_label, divs)
    _draw_macd(ax_m, d, x)

    # 모멘텀 패널 x축을 추세 패널과 정렬 (선행 여백 포함)
    for ax in (ax_b, ax_v, ax_r, ax_m):
        ax.set_xlim(-1, len(d) - 1 + fwd + 2)
        ax.set_xticks(ticks)
        ax.tick_params(labelbottom=False)
    fmt = "%y.%m.%d" if tf == "일봉" else "%y.%m"
    ax_m.set_xticklabels([d.index[i].strftime(fmt) for i in ticks], fontsize=9)
    ax_m.tick_params(labelbottom=True)

    fig.savefig(path, facecolor=C["page"])
    plt.close(fig)


def make_chart_cover(now: dt.datetime, rows: list[dict],
                     flows_long: pd.DataFrame | None, path: str):
    """표지: 큰 연월일 + 지수 요약 + 코스피 수급 2년 누적."""
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor(C["page"])

    # 큰 날짜
    fig.text(0.075, 0.905, f"{now:%Y.%m.%d}", color=C["ink"], fontsize=54,
             weight="bold")
    fig.text(0.075, 0.868, f"{WEEKDAY_KO[now.weekday()]}요일 · 미국장 마감 "
             f"+ 전일 코스피 차트 분석", color=C["ink2"], fontsize=15.5)
    fig.text(0.075, 0.838, "일봉·주봉 / 이동평균선 · 일목균형표 · 볼린저밴드 · "
             "RSI · MACD · 거래량", color=C["muted"], fontsize=11.5)

    # 지수 요약 3줄
    y = 0.775
    for r in rows:
        meta, df = r["meta"], r["df"]
        close = float(df["close"].iloc[-1])
        chg = (close / float(df["close"].iloc[-2]) - 1) * 100
        arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "—")
        fig.text(0.075, y, meta["name"], color=C["ink"], fontsize=17,
                 weight="bold")
        fig.text(0.50, y, _fmt_price(close, meta["currency"]), color=C["ink"],
                 fontsize=17, ha="right")
        fig.text(0.53, y, f"{arrow} {chg:+.2f}%", color=_dir_color(chg),
                 fontsize=17, weight="bold")
        vc, _ = _verdict_style(r["vd"])
        fig.text(0.955, y, f"일봉 {r['vd']} · 주봉 {r['vw']}", color=C["ink2"],
                 fontsize=12.5, ha="right")
        y -= 0.052

    # 코스피 수급 2년 누적 (하단)
    ax = fig.add_axes([0.075, 0.075, 0.80, 0.50])
    if flows_long is not None and len(flows_long) > 40:
        actors = ["개인", "외국인", "기관"]
        cum = flows_long[actors].cumsum() / 1e4  # 억원 -> 조원
        x = np.arange(len(cum))
        ax.axhline(0, color=C["axis"], lw=1.0)
        for actor in actors:
            ax.plot(x, cum[actor], color=C[actor], lw=1.9, label=actor,
                    solid_capstyle="round")
        ends = sorted(((float(cum[a].iloc[-1]), a) for a in actors),
                      reverse=True)
        rng_ = float(np.nanmax(cum.to_numpy()) - np.nanmin(cum.to_numpy())) or 1.0
        min_gap = rng_ * 0.07
        ys = [v for v, _ in ends]
        for k in range(1, len(ys)):
            if ys[k - 1] - ys[k] < min_gap:
                ys[k] = ys[k - 1] - min_gap
        for (v, actor), ylab in zip(ends, ys):
            ax.annotate(f"{actor} {v:+.1f}조", xy=(x[-1], v),
                        xytext=(x[-1] + len(x) * 0.015, ylab),
                        textcoords="data", color=C[actor], fontsize=11,
                        weight="bold", va="center", annotation_clip=False)
        _style_ax(ax)
        ax.set_title(f"코스피 수급 흐름 (2년 누적 순매수, 조원) · "
                     f"{flows_long.index[0]:%y.%m} ~ {flows_long.index[-1]:%y.%m}",
                     color=C["ink"], fontsize=13.5, weight="bold", loc="left",
                     pad=8)
        t = np.linspace(0, len(cum) - 1, 7).astype(int)
        ax.set_xticks(t)
        ax.set_xticklabels([cum.index[i].strftime("%y.%m") for i in t],
                           fontsize=9)
        ax.set_xlim(0, len(cum) - 1)
    else:
        ax.axis("off")
        ax.text(0.5, 0.5, "코스피 수급 데이터 없음", color=C["muted"],
                fontsize=13, ha="center", va="center", transform=ax.transAxes)

    fig.text(0.5, 0.024, DISCLAIMER, color=C["muted"], fontsize=9.5,
             ha="center")
    fig.savefig(path, facecolor=C["page"])
    plt.close(fig)


# ──────────────────────────────────────────────────────────────
# 지표 해설 텍스트 (블로그 본문 · 캡션 공용)
# ──────────────────────────────────────────────────────────────

def _fmt_v(v: float) -> str:
    return f"{v:,.2f}"


def _ma_state(d: pd.DataFrame, unit: str) -> list[str]:
    last = d.iloc[-1]
    close = float(last["close"])
    lines = []
    mas = {w: float(last[f"ma{w}"]) for w in (5, 20, 60, 120)
           if pd.notna(last[f"ma{w}"])}
    if len(mas) >= 3:
        seq = [mas[w] for w in sorted(mas)]
        if all(seq[i] > seq[i + 1] for i in range(len(seq) - 1)):
            lines.append(f"이평선은 {'>'.join(f'{w}{unit}' for w in sorted(mas))} "
                         "순의 정배열로, 추세의 기울기가 위를 향해 있습니다.")
        elif all(seq[i] < seq[i + 1] for i in range(len(seq) - 1)):
            lines.append(f"이평선은 {'<'.join(f'{w}{unit}' for w in sorted(mas))} "
                         "순의 역배열로, 추세가 아래로 눌려 있는 구간입니다.")
        else:
            above = [f"{w}{unit}선" for w in sorted(mas) if close >= mas[w]]
            below = [f"{w}{unit}선" for w in sorted(mas) if close < mas[w]]
            seg = []
            if above:
                seg.append(f"{'·'.join(above)} 위")
            if below:
                seg.append(f"{'·'.join(below)} 아래")
            lines.append("이평선 배열은 혼조입니다. 현재가는 "
                         + ", ".join(seg) + "에 위치합니다.")
    if 20 in mas and mas[20] > 0:
        disp = (close / mas[20] - 1) * 100
        judge = ("과열권으로 이격 축소(눌림)를 경계할 자리"
                 if disp >= 5 else
                 ("이격 과대로 기술적 반등 여지를 볼 자리" if disp <= -5
                  else "이격은 부담스럽지 않은 수준"))
        lines.append(f"{20}{unit}선({_fmt_v(mas[20])}) 대비 이격도는 "
                     f"{disp:+.1f}%로 {judge}입니다.")
        if 5 in mas:
            g = _crossed_above(d["ma5"], d["ma20"])
            de = _crossed_below(d["ma5"], d["ma20"])
            if g:
                lines.append(f"최근 5{unit}선이 20{unit}선을 상향 돌파(골든크로스)"
                             "했습니다.")
            elif de:
                lines.append(f"최근 5{unit}선이 20{unit}선을 하향 이탈(데드크로스)"
                             "했습니다.")
    return lines


def _ichimoku_state(df: pd.DataFrame, unit: str) -> list[str]:
    last = df.iloc[-1]
    close = float(last["close"])
    lines = []
    if pd.notna(last["senkou_a"]) and pd.notna(last["senkou_b"]):
        top = max(float(last["senkou_a"]), float(last["senkou_b"]))
        bot = min(float(last["senkou_a"]), float(last["senkou_b"]))
        if close > top:
            pos = f"구름대 상단({_fmt_v(top)}) 위"
            judge = "일목상 상승 국면이며, 구름 상단이 1차 지지로 작동할 수 있습니다"
        elif close < bot:
            pos = f"구름대 하단({_fmt_v(bot)}) 아래"
            judge = "일목상 하락 국면이며, 구름 하단이 1차 저항으로 작동할 수 있습니다"
        else:
            pos = f"구름대 내부({_fmt_v(bot)}~{_fmt_v(top)})"
            judge = "방향 탐색 구간으로, 구름 이탈 방향을 확인할 필요가 있습니다"
        lines.append(f"현재가는 {pos}에 있어 {judge}.")
    if pd.notna(last["tenkan"]) and pd.notna(last["kijun"]):
        t, k = float(last["tenkan"]), float(last["kijun"])
        rel = "위" if t > k else ("아래" if t < k else "같은 수준")
        lines.append(f"전환선({_fmt_v(t)})은 기준선({_fmt_v(k)}) {rel}에 있어 "
                     f"단기 힘은 {'매수' if t > k else '매도' if t < k else '균형'} "
                     "쪽입니다.")
    shift = PARAMS["ichimoku"]["shift"]
    if len(df) > shift:
        past = float(df["close"].iloc[-1 - shift])
        if close > past * 1.01:
            lines.append(f"후행스팬은 {shift}{unit} 전 가격({_fmt_v(past)}) 위 — "
                         "매물 부담이 크지 않은 호전 상태입니다.")
        elif close < past * 0.99:
            lines.append(f"후행스팬은 {shift}{unit} 전 가격({_fmt_v(past)}) 아래 — "
                         "위쪽 매물 부담이 남아 있는 역전 상태입니다.")
    # 선행 구름 색 (앞으로 26봉)
    fa, fb = _future_cloud(df, PARAMS["ichimoku"]["shift"])
    if len(fa) and not (np.isnan(fa[-1]) or np.isnan(fb[-1])):
        lines.append("앞쪽에 깔리는 선행 구름은 "
                     + ("양운(상승 구름)" if fa[-1] >= fb[-1] else "음운(하락 구름)")
                     + "입니다.")
    return lines


def _bb_state(d: pd.DataFrame) -> list[str]:
    last = d.iloc[-1]
    lines = []
    if pd.isna(last["bb_up"]):
        return lines
    close = float(last["close"])
    up, mid, dn = float(last["bb_up"]), float(last["bb_mid"]), float(last["bb_dn"])
    pctb = float(last["bb_pctb"]) * 100 if pd.notna(last["bb_pctb"]) else None
    if close > up:
        pos = "상단 밴드 밖(과열권)"
    elif close < dn:
        pos = "하단 밴드 밖(과매도권)"
    elif close >= mid:
        pos = "중심선 위쪽"
    else:
        pos = "중심선 아래쪽"
    line = (f"볼린저밴드(20,2σ)는 상단 {_fmt_v(up)} · 중심 {_fmt_v(mid)} · "
            f"하단 {_fmt_v(dn)}이며, 현재가는 {pos}에 있습니다")
    if pctb is not None:
        line += f" (%b {pctb:.0f}%)."
    else:
        line += "."
    lines.append(line)
    width = d["bb_width"].dropna()
    if len(width) >= 20:
        w_now = float(width.iloc[-1])
        w_prev = float(width.iloc[-6]) if len(width) >= 6 else w_now
        trend = "확대" if w_now > w_prev * 1.05 else \
            ("축소" if w_now < w_prev * 0.95 else "유지")
        extra = ""
        if len(width) >= 120 and width.tail(120).rank(pct=True).iloc[-1] <= 0.10:
            extra = " — 스퀴즈(변동성 응축) 구간으로 방향이 나오면 변동이 커질 수 있습니다"
        lines.append(f"밴드폭은 {trend} 중입니다{extra}.")
    return lines


def _rsi_state(d: pd.DataFrame, unit: str,
               divs: list[dict] | None = None) -> list[str]:
    rsi = d["rsi"].dropna()
    if rsi.empty:
        return []
    cur = float(rsi.iloc[-1])
    prev = float(rsi.iloc[-2]) if len(rsi) > 1 else cur
    zone = ("70 이상 과매수권" if cur >= 70 else
            ("30 이하 과매도권" if cur <= 30 else
             ("50 위 매수 우위" if cur >= 50 else "50 아래 매도 우위")))
    d_ = "상승" if cur > prev else ("하락" if cur < prev else "보합")
    lines = [f"RSI(14)는 {cur:.1f}로 {zone}이며, 직전 대비 {d_} 흐름입니다."]
    if "rsi_sig" in d.columns and pd.notna(d["rsi_sig"].iloc[-1]):
        sig = float(d["rsi_sig"].iloc[-1])
        rel = "위" if cur > sig else ("아래" if cur < sig else "겹침")
        lines.append(f"시그널선(9기간, {sig:.1f}) {rel}에 있어 단기 모멘텀은 "
                     f"{'우위' if cur > sig else '열위' if cur < sig else '중립'} "
                     "상태입니다.")
    for dv in (divs or []):
        if dv["kind"] == "bull":
            lines.append("가격은 저점을 낮췄지만 RSI 저점은 높아진 "
                         "[상승 다이버전스]가 포착됐습니다 — 하락 탄력 소진 신호로, "
                         "차트의 연결선 구간을 확인하세요.")
        else:
            lines.append("가격은 고점을 높였지만 RSI 고점은 낮아진 "
                         "[하락 다이버전스]가 포착됐습니다 — 상승 탄력 소진 신호로, "
                         "차트의 연결선 구간을 확인하세요.")
    return lines


def _macd_state(d: pd.DataFrame) -> list[str]:
    if "macd" not in d.columns:
        return []
    m = d["macd"].dropna()
    if m.empty:
        return []
    last_m = float(d["macd"].iloc[-1])
    last_s = float(d["macd_sig"].iloc[-1])
    h = d["macd_hist"].dropna()
    lines = []
    rel = "위" if last_m > last_s else "아래"
    zero = "0선 위" if last_m > 0 else "0선 아래"
    lines.append(f"MACD({_fmt_v(last_m)})는 시그널선({_fmt_v(last_s)}) {rel}, "
                 f"{zero}에 있습니다.")
    if len(h) >= 3:
        h1, h2 = float(h.iloc[-1]), float(h.iloc[-2])
        grow = abs(h1) > abs(h2)
        if h1 >= 0:
            judge = ("플러스 영역에서 확대 — 상승 모멘텀이 실리는 모습" if grow
                     else "플러스 영역에서 축소 — 상승 모멘텀이 둔화되는 모습")
        else:
            judge = ("마이너스 영역에서 확대 — 하락 모멘텀이 강해지는 모습" if grow
                     else "마이너스 영역에서 축소 — 하락 모멘텀이 잦아드는 모습")
        lines.append(f"히스토그램은 {judge}입니다.")
    return lines


def _vol_state(d: pd.DataFrame, unit: str) -> list[str]:
    vol = d["volume"].to_numpy(dtype=float)
    if not np.isfinite(vol).any() or np.nanmax(vol) <= 0:
        return ["이 지수는 거래량 데이터가 제공되지 않아 거래량 판단은 생략합니다."]
    last = d.iloc[-1]
    ratio = last["vol_ratio"]
    if pd.isna(ratio):
        return []
    up_bar = float(last["close"]) >= float(d["close"].iloc[-2])
    judge = ("거래가 실린 " + ("상승 — 매수 에너지가 붙는 모습"
                               if up_bar else "하락 — 매물 출회를 경계")
             if ratio >= 1.5 else
             ("평균 대비 한산한 거래 — 관망 속 에너지 응축" if ratio <= 0.6
              else "평균 수준의 거래"))
    return [f"거래량은 20{unit} 평균의 {float(ratio):.1f}배로, {judge}입니다."]


def _flows_state(flows: pd.DataFrame | None) -> list[str]:
    if flows is None or len(flows) < 10:
        return []
    lines = []
    recent = flows.tail(5)
    fsum = recent["외국인"].sum() / 1e4
    isum = recent["기관"].sum() / 1e4
    lines.append(f"최근 5거래일 누적으로 외국인 {fsum:+.2f}조원, "
                 f"기관 {isum:+.2f}조원 순매수를 기록했습니다.")
    cum = flows[["개인", "외국인", "기관"]].cumsum() / 1e4
    ends = {a: float(cum[a].iloc[-1]) for a in cum.columns}
    lines.append("2년 누적으로는 "
                 + ", ".join(f"{a} {v:+.1f}조" for a, v in ends.items())
                 + " — 장기 수급의 무게중심을 함께 볼 필요가 있습니다.")
    return lines


def _top_signals(sigs: list[Signal], k: int = 3) -> list[Signal]:
    return sorted(sigs, key=lambda s: -abs(s.score))[:k]


# ──────────────────────────────────────────────────────────────
# 환율·매크로 흐름 (블로그 전용)
# ──────────────────────────────────────────────────────────────

FX_SERIES = [
    {"ticker": "KRW=X",    "name": "원/달러",   "fmt": "{:,.1f}원",
     "unit": "원", "base": 1385.0},
    {"ticker": "DX-Y.NYB", "name": "달러인덱스", "fmt": "{:,.2f}",
     "unit": "pt", "base": 104.0},
    {"ticker": "^TNX",     "name": "미 10년물", "fmt": "{:.2f}%",   # 야후 ^TNX는 % 단위
     "unit": "%p", "base": 4.2},
    {"ticker": "JPYKRW=X", "name": "원/엔(100엔)", "fmt": "{:,.1f}원",
     "unit": "원", "scale": 100, "base": 9.4},
    {"ticker": "krxbond:국고채3년", "name": "국고채 3년", "fmt": "{:.2f}%",
     "unit": "%p", "base": 2.9},
]
# 미국장 매크로 (미국장 마감 시점 기준)
MACRO_SERIES = [
    {"ticker": "^TNX", "name": "미 10년물", "fmt": "{:.2f}%", "unit": "%p", "base": 4.2},
    {"ticker": "^TYX", "name": "미 30년물", "fmt": "{:.2f}%", "unit": "%p", "base": 4.8},
    {"ticker": "CL=F", "name": "WTI 유가", "fmt": "${:,.2f}", "unit": "pt", "base": 70.0},
    {"ticker": "GC=F", "name": "금", "fmt": "${:,.1f}", "unit": "pt", "base": 2400.0},
    {"ticker": "HG=F", "name": "구리", "fmt": "${:,.3f}", "unit": "pt", "base": 4.5},
]
FX_DAYS = 520   # 약 2년
FX_LOG = os.path.join(HIST_DIR, "fx_log.csv")


def _krx_bond(name: str, days: int) -> pd.DataFrame:
    """KRX 장외 국고채 수익률 일별 (pykrx) — 180일씩 나눠 조회해 OHLC 형태로."""
    from pykrx import bond

    end = dt.date.today()
    start = end - dt.timedelta(days=int(days * 1.5))
    parts, cur = [], start
    while cur <= end:
        to = min(cur + dt.timedelta(days=180), end)
        got = bond.get_otc_treasury_yields(cur.strftime("%Y%m%d"),
                                           to.strftime("%Y%m%d"), name)
        if got is not None and not got.empty:
            parts.append(got["수익률"].astype(float))
        cur = to + dt.timedelta(days=1)
    if not parts:
        raise RuntimeError(f"국고채 수익률 없음: {name}")
    c = pd.concat(parts)
    c = c[~c.index.duplicated(keep="last")].sort_index()
    c.index = pd.to_datetime(c.index)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                         "volume": 0.0}).tail(days)


def fetch_fx(sample: bool = False, series: list[dict] | None = None) -> list[dict]:
    """환율·매크로 시계열 수집 (+지표). 실패한 항목은 건너뜁니다."""
    out: list[dict] = []
    get_daily = sample_daily if sample else fetch_daily
    for meta in (series or FX_SERIES):
        try:
            if meta["ticker"].startswith("krxbond:") and not sample:
                df = _krx_bond(meta["ticker"].split(":", 1)[1], FX_DAYS)
            else:
                df = get_daily(meta["ticker"], FX_DAYS)
            if sample:  # 합성 시계열을 실제 수준으로 스케일 (레이아웃 테스트)
                df = df * (meta["base"] / float(df["close"].iloc[-1]))
            if meta.get("scale"):
                df = df * meta["scale"]
            out.append(dict(meta=meta, df=add_indicators(df)))
        except Exception as e:
            print(f"  (환율 수집 실패 {meta['name']}: {e})")
    return out


def make_blog_fx(fx_rows: list[dict], date_str: str, path: str,
                 title: str = "환율·매크로 흐름"):
    """환율·금리·원자재 — 2년 흐름 + 20/60일선 (항목 수만큼 세로로)."""
    n = len(fx_rows)
    fig = plt.figure(figsize=(BLOG_FIGSIZE[0], max(BLOG_FIGSIZE[1], 1.75 * n + 1.5)),
                     dpi=DPI)
    fig.patch.set_facecolor(C["page"])
    _blog_header(fig, f"{title} — " + " · ".join(r["meta"]["name"] for r in fx_rows),
                 date_str)
    gs = fig.add_gridspec(n, 1, left=0.05, right=0.90, top=0.89, bottom=0.075,
                          hspace=0.42)
    for i, r in enumerate(fx_rows):
        meta, df = r["meta"], r["df"]
        d = df.tail(FX_DAYS - 20)
        x = np.arange(len(d))
        ax = fig.add_subplot(gs[i])
        ax.plot(x, d["close"], color=C["ink"], lw=1.6, zorder=4)
        ax.plot(x, d["ma20"], color=C["ma20"], lw=1.1, alpha=0.9, zorder=3,
                label="20일선")
        ax.plot(x, d["ma60"], color=C["ma60"], lw=1.1, alpha=0.9, zorder=3,
                label="60일선")
        _style_ax(ax)
        ax.yaxis.tick_left()     # 오른쪽 끝은 현재값 라벨 자리
        v = float(d["close"].iloc[-1])
        v20 = float(d["close"].iloc[-21]) if len(d) > 21 else v
        col = _dir_color(v - v20)
        ax.annotate(meta["fmt"].format(v), xy=(x[-1], v),
                    xytext=(x[-1] + len(x) * 0.012, v), textcoords="data",
                    color=col, fontsize=11.5, weight="bold", va="center",
                    annotation_clip=False)
        ax.set_title(meta["name"], color=C["ink"], fontsize=13,
                     weight="bold", loc="left", pad=6)
        if i == 0:
            ax.legend(loc="upper left", fontsize=9, ncols=2, frameon=False,
                      labelcolor=C["ink2"], handlelength=1.2)
        t = np.linspace(0, len(d) - 1, 9).astype(int)
        ax.set_xticks(t)
        ax.set_xticklabels([d.index[j].strftime("%y.%m") for j in t],
                           fontsize=9)
        ax.set_xlim(0, len(d) - 1)
    fig.savefig(path, facecolor=C["page"])
    plt.close(fig)


def _fx_state(fx_rows: list[dict],
              flows_long: pd.DataFrame | None) -> list[str]:
    """환율 흐름 해설 + 외국인 수급 연결 (규칙 기반)."""
    lines: list[str] = []
    krw_d20 = None
    tnx_d20 = None
    for r in fx_rows:
        meta, df = r["meta"], r["df"]
        v = float(df["close"].iloc[-1])
        v1 = float(df["close"].iloc[-2])
        v20 = float(df["close"].iloc[-21]) if len(df) > 21 else v
        ma20 = float(df["ma20"].iloc[-1]) if pd.notna(df["ma20"].iloc[-1]) else None
        yr = df["close"].tail(252)
        pos = (v - float(yr.min())) / (float(yr.max()) - float(yr.min())) * 100 \
            if float(yr.max()) > float(yr.min()) else 50.0
        name = meta["name"]
        if name == "원/달러":
            krw_d20 = v - v20
            trend = "원화 약세(환율 상승)" if v > v20 else "원화 강세(환율 하락)"
            rel = ""
            if ma20:
                rel = f", 20일선({meta['fmt'].format(ma20)}) " \
                      + ("위" if v >= ma20 else "아래")
            lines.append(f"원/달러는 {meta['fmt'].format(v)} "
                         f"(전일 {v - v1:+.1f}원, 20일 {v - v20:+.1f}원){rel} — "
                         f"최근 한 달 흐름은 {trend} 쪽이며, 1년 레인지 내 위치는 "
                         f"{pos:.0f}%입니다.")
        elif name == "달러인덱스":
            trend = "달러 강세" if v > v20 else "달러 약세"
            lines.append(f"달러인덱스는 {meta['fmt'].format(v)} "
                         f"(20일 {((v / v20) - 1) * 100:+.1f}%) — {trend} 흐름, "
                         f"1년 레인지 내 {pos:.0f}% 수준입니다.")
        elif name == "원/엔(100엔)":
            trend = "엔화 강세(환율 상승)" if v > v20 else "엔화 약세(환율 하락)"
            lines.append(f"원/엔(100엔)은 {meta['fmt'].format(v)} "
                         f"(20일 {v - v20:+.1f}원) — {trend} 흐름, "
                         f"1년 레인지 내 {pos:.0f}% 수준입니다.")
        elif name == "미 10년물":
            tnx_d20 = v - v20
            trend = "상승" if v > v20 else "하락"
            lines.append(f"미 10년물 금리는 {meta['fmt'].format(v)} "
                         f"(20일 {v - v20:+.2f}%p) — 금리 {trend} 흐름입니다.")

    # 수급 연결 판단
    if krw_d20 is not None:
        if krw_d20 < 0:
            cond = ("원화 강세 흐름은 외국인 입장에서 환차익 기대를 키워 "
                    "국내 증시 수급에 우호적으로 작용할 수 있는 조건입니다.")
        else:
            cond = ("원화 약세 흐름은 외국인 입장에서 환차손 부담을 키워 "
                    "국내 증시 수급에 비우호적으로 작용할 수 있는 조건입니다.")
        if flows_long is not None and len(flows_long) >= 20:
            f20 = float(flows_long["외국인"].tail(20).sum()) / 1e4
            match = (krw_d20 < 0 and f20 > 0) or (krw_d20 > 0 and f20 < 0)
            cond += (f" 실제 최근 20거래일 외국인 누적 순매수는 {f20:+.2f}조원으로, "
                     f"이 조건과 {'부합하는' if match else '엇갈리는'} 모습입니다.")
        lines.append(cond)
    if tnx_d20 is not None and abs(tnx_d20) >= 0.15:
        if tnx_d20 > 0:
            lines.append("미 금리의 상승 폭이 커 성장주 비중이 높은 나스닥100의 "
                         "밸류에이션 부담 요인으로 함께 볼 필요가 있습니다.")
        else:
            lines.append("미 금리가 뚜렷이 내려와 성장주 밸류에이션 부담이 "
                         "완화되는 구간입니다.")
    lines.append("환율·금리 흐름과 실제 수급의 일치 여부는 매달 기록과 비교해 "
                 "판단 정확도를 검증합니다.")
    return lines


def log_fx(now: dt.datetime, fx_rows: list[dict]):
    """환율·매크로 일일 상태 축적 — 월간 예측 피드백의 원장."""
    try:
        os.makedirs(HIST_DIR, exist_ok=True)
        new = not os.path.exists(FX_LOG)
        with open(FX_LOG, "a", encoding="utf-8-sig") as f:
            if new:
                f.write("date,name,close,chg1,chg20,vs_ma20\n")
            for r in fx_rows:
                df = r["df"]
                v = float(df["close"].iloc[-1])
                v1 = float(df["close"].iloc[-2])
                v20 = float(df["close"].iloc[-21]) if len(df) > 21 else v
                ma20 = df["ma20"].iloc[-1]
                rel = ("above" if pd.notna(ma20) and v >= float(ma20)
                       else "below")
                f.write(f"{now:%Y-%m-%d},{r['meta']['name']},{v:.3f},"
                        f"{v - v1:+.3f},{v - v20:+.3f},{rel}\n")
    except Exception as e:
        print(f"  (환율 로그 저장 실패: {e})")


# ──────────────────────────────────────────────────────────────
# 블로그 팩 (이미지 + 본문 텍스트)
# ──────────────────────────────────────────────────────────────

BLOG_FIGSIZE = (16.0, 9.0)   # 1600x900 @ DPI 100


def _blog_header(fig, title: str, sub: str):
    fig.text(0.05, 0.945, title, color=C["ink"], fontsize=17, weight="bold")
    fig.text(0.95, 0.945, sub, color=C["muted"], fontsize=11, ha="right")


def make_blog_trend(row: dict, tf: str, date_str: str, path: str):
    meta = row["meta"]
    df = row["df"] if tf == "일봉" else row["dfw"]
    n = CHART_PARAMS["daily_bars"] if tf == "일봉" else CHART_PARAMS["weekly_bars"]
    fig = plt.figure(figsize=BLOG_FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor(C["page"])
    _blog_header(fig, f"{meta['name']} {tf} — 이동평균선 · 일목균형표",
                 f"{meta['ticker']} · {date_str}")
    ax = fig.add_axes([0.05, 0.09, 0.91, 0.80])
    _draw_trend(ax, df, n, CHART_PARAMS["forward"], tf)
    fig.savefig(path, facecolor=C["page"])
    plt.close(fig)


def make_blog_momentum(row: dict, tf: str, date_str: str, path: str):
    meta = row["meta"]
    df = row["df"] if tf == "일봉" else row["dfw"]
    n = CHART_PARAMS["daily_bars"] if tf == "일봉" else CHART_PARAMS["weekly_bars"]
    fwd = CHART_PARAMS["forward"]
    d = df.tail(n)
    x = np.arange(len(d))
    fig = plt.figure(figsize=BLOG_FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor(C["page"])
    _blog_header(fig, f"{meta['name']} {tf} — 볼린저밴드 · 거래량 · RSI · MACD",
                 f"{meta['ticker']} · {date_str}")
    gs = fig.add_gridspec(4, 1, height_ratios=[2.4, 0.8, 1.0, 1.0],
                          left=0.05, right=0.96, top=0.89, bottom=0.075,
                          hspace=0.30)
    ax_b = fig.add_subplot(gs[0])
    ax_v = fig.add_subplot(gs[1])
    ax_r = fig.add_subplot(gs[2])
    ax_m = fig.add_subplot(gs[3])
    divs = row.get("div_d") if tf == "일봉" else row.get("div_w")
    _draw_bb(ax_b, d, x, divs)
    _draw_vol(ax_v, d, x)
    _draw_rsi(ax_r, d, x, divs=divs)
    _draw_macd(ax_m, d, x)
    ticks = np.linspace(0, len(d) - 1, 8).astype(int)
    fmt = "%y.%m.%d" if tf == "일봉" else "%y.%m"
    for ax in (ax_b, ax_v, ax_r, ax_m):
        ax.set_xlim(-1, len(d))
        ax.set_xticks(ticks)
        ax.tick_params(labelbottom=False)
    ax_m.set_xticklabels([d.index[i].strftime(fmt) for i in ticks], fontsize=9)
    ax_m.tick_params(labelbottom=True)
    fig.savefig(path, facecolor=C["page"])
    plt.close(fig)


# ──────────────────────────────────────────────────────────────
# 증권사 앱 형식 통합 차트 (가격+이평+일목+BB / 거래량 / MACD / RSI)
# ──────────────────────────────────────────────────────────────

APP_FIGSIZE = (12.0, 15.0)    # 1200x1500 @ DPI 100
APP = {
    "candle_up": "#26a69a", "candle_dn": "#ef5350",   # 트레이딩뷰 양봉/음봉
    "ma5": "#F08A24", "ma20": "#1A1A1A", "ma60": "#4E6B3A", "ma120": "#3A9B7B",
    "tenkan": "#7F73A8", "kijun": "#A052B8",
    "span1": "#B5626B", "span2": "#5B84B8",
    "cloud1": "#F0A8B0", "cloud2": "#A0C0F0",    # 선행1 위(빨강) / 선행2 위(파랑)
    "bb_up": "#C4607A", "bb_dn": "#5B88C0",
    "macd": "#F08A24", "sig": "#587848", "osc_pos": "#4878E0", "osc_neg": "#507840",
    "rsi": "#F08A24",
    "tag_vol": "#606060", "tag_ind": "#F88000",
    "tick": "#7A7A7A", "grid": "#EEEEEE", "sep": "#C8C8C8", "band": "#F2F2F2",
    "band_txt": "#909090", "level": "#9A9A9A",
}


def _fmt_vol(v: float) -> str:
    if abs(v) >= 1e9:
        return f"{v / 1e9:,.2f}B"
    if abs(v) >= 1e6:
        return f"{v / 1e6:,.1f}M"
    return f"{v / 1e3:,.0f}K"


def _app_style(ax):
    ax.set_facecolor("#ffffff")
    for k, sp in ax.spines.items():
        sp.set_visible(k in ("top", "bottom", "right"))
        sp.set_color(APP["sep"])
        sp.set_linewidth(1.0)
    ax.yaxis.tick_right()
    ax.tick_params(colors=APP["tick"], labelsize=10, length=0, pad=6)
    ax.tick_params(axis="x", labelbottom=False)
    ax.grid(True, color=APP["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def _app_tag(ax, y: float, text: str, color: str, fmt, nlines: int = 1):
    """오른쪽 축 값 태그 + 태그·축 경계와 겹치는 눈금 숫자 숨김."""
    ax.annotate(text, xy=(1, y), xycoords=("axes fraction", "data"),
                xytext=(4, 0), textcoords="offset points", ha="left",
                va="center", fontsize=10.5, color="#ffffff", zorder=9,
                annotation_clip=False, linespacing=1.05,
                bbox=dict(boxstyle="square,pad=0.3", facecolor=color,
                          edgecolor="none"))
    lo, hi = ax.get_ylim()
    tag_gap = _pt_to_data(ax, 10.5 * (0.75 + 0.6 * nlines) + 6)
    edge_gap = _pt_to_data(ax, 8)
    ticks = [t for t in ax.get_yticks()
             if lo + edge_gap <= t <= hi - edge_gap and abs(t - y) >= tag_gap]
    ax.set_yticks(ticks)
    ax.set_yticklabels([fmt(t) for t in ticks])
    ax.set_ylim(lo, hi)


def _app_legend(fig, items, x0: float, x1: float, y0: float,
                fontsize: float = 11.5) -> float:
    """「-이름」을 색 글자로 이어 쓰고 폭을 넘으면 줄바꿈. 마지막 줄 아래 y 반환."""
    r = fig.canvas.get_renderer()
    lh = fontsize * 1.55 / 72 * fig.dpi / fig.bbox.height
    gap = 6 / fig.bbox.width
    x, y = x0, y0
    for label, col in items:
        t = fig.text(x, y, "-" + label, color=col, fontsize=fontsize, va="top")
        w = t.get_window_extent(r).width / fig.bbox.width
        if x > x0 and x + w > x1:
            x, y = x0, y - lh
            t.set_position((x, y))
        x += w + gap
    return y - lh


def _pane_title(ax, items, fontsize: float = 10.5):
    """패널 왼쪽 위 지표 이름 (색 글자)."""
    fig = ax.figure
    r = fig.canvas.get_renderer()
    bb = ax.get_window_extent(r)
    x = bb.x0 + 8
    for label, col in items:
        t = fig.text(x / fig.bbox.width, (bb.y1 - 6) / fig.bbox.height, label,
                     color=col, fontsize=fontsize, va="top", zorder=9)
        x += t.get_window_extent(r).width + 10


def _cross_arrows(ax, x, a, b):
    """선이 시그널선을 위로 뚫으면 ▲(아래), 아래로 뚫으면 ▼(위)."""
    import matplotlib.transforms as mtrans
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    diff = a - b
    ok = ~(np.isnan(diff[1:]) | np.isnan(diff[:-1]))
    up = np.where(ok & (diff[:-1] <= 0) & (diff[1:] > 0))[0] + 1
    dn = np.where(ok & (diff[:-1] >= 0) & (diff[1:] < 0))[0] + 1
    below = mtrans.offset_copy(ax.transData, fig=ax.figure, y=-9, units="points")
    above = mtrans.offset_copy(ax.transData, fig=ax.figure, y=9, units="points")
    ax.scatter(x[up], a[up], marker="^", s=46, color=C["up"], zorder=8,
               transform=below, linewidths=0)
    ax.scatter(x[dn], a[dn], marker="v", s=46, color=C["down"], zorder=8,
               transform=above, linewidths=0)


def _level_label(ax, y: float, text: str):
    ax.text(0.004, y, text, transform=ax.get_yaxis_transform(),
            color=APP["level"], fontsize=10, va="center", ha="left", zorder=7)


def make_blog_app(row: dict, tf: str, date_str: str, path: str):
    """증권사 앱 차트 형식 1장 — 가격(이평 5/20/60/120 · 일목 · BB) /
    거래량 / MACD / RSI, 시그널 교차 화살표 · 오른쪽 축 값 태그."""
    meta = row["meta"]
    df = row["df"] if tf == "일봉" else row["dfw"]
    n = CHART_PARAMS["daily_bars"] if tf == "일봉" else CHART_PARAMS["weekly_bars"]
    fwd = CHART_PARAMS["forward"]
    ich = PARAMS["ichimoku"]
    d = df.tail(n)
    x = np.arange(len(d))
    xlim = (-1, len(d) - 1 + fwd + 2)
    close = float(d["close"].iloc[-1])
    prev = float(df["close"].iloc[-2])
    chg = (close / prev - 1) * 100
    dcol = _dir_color(chg)

    fig = plt.figure(figsize=APP_FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor("#ffffff")
    L, R = 0.03, 0.865

    # ── 헤더: 이름 / 현재가 · 등락률 ──
    fig.text(L, 0.978, f"{meta['name']}  {tf}", color=C["ink"], fontsize=19,
             weight="bold", va="top")
    fig.text(L, 0.951, f"{close:,.2f}  {chg:+.2f}%", color=dcol, fontsize=19,
             weight="bold", va="top")
    fig.text(0.97, 0.951, f"{meta['ticker']} · {date_str}", color=APP["tick"],
             fontsize=11, ha="right", va="top")

    # ── 범례 (색 글자, 폭 넘으면 줄바꿈) ──
    sh = ich["shift"]
    legend = [("5", APP["ma5"]), ("20", APP["ma20"]), ("60", APP["ma60"]),
              ("120", APP["ma120"]),
              (f"전환선({ich['kijun']},{ich['tenkan']},{sh},{ich['senkou_b']},{sh})",
               APP["tenkan"]),
              ("기준선", APP["kijun"]), ("선행스팬1", APP["span1"]),
              ("선행스팬2", APP["span2"]),
              (f"BB 상한({PARAMS['bb_period']},{PARAMS['bb_std']:.2f})", APP["bb_up"]),
              ("BB 하한", APP["bb_dn"])]
    top = _app_legend(fig, legend, L + 0.005, R, 0.915) - 0.004

    gs = fig.add_gridspec(5, 1, height_ratios=[6.0, 0.42, 1.7, 1.7, 1.7],
                          left=L, right=R, top=top, bottom=0.015, hspace=0.0)
    ax_p = fig.add_subplot(gs[0])
    ax_d = fig.add_subplot(gs[1])
    ax_v = fig.add_subplot(gs[2])
    ax_m = fig.add_subplot(gs[3])
    ax_r = fig.add_subplot(gs[4])

    # ── 가격 패널 ──
    _app_style(ax_p)
    a = d["senkou_a"].to_numpy(dtype=float)
    b = d["senkou_b"].to_numpy(dtype=float)
    fa, fb = _future_cloud(df, fwd)
    xa = np.concatenate([x, np.arange(len(d), len(d) + len(fa))])
    aa = np.concatenate([a, fa])
    bb_ = np.concatenate([b, fb])
    v = ~(np.isnan(aa) | np.isnan(bb_))
    ax_p.fill_between(xa, aa, bb_, where=v & (aa >= bb_), color=APP["cloud1"],
                      alpha=0.75, linewidth=0, interpolate=True, zorder=1)
    ax_p.fill_between(xa, aa, bb_, where=v & (aa < bb_), color=APP["cloud2"],
                      alpha=0.75, linewidth=0, interpolate=True, zorder=1)
    ax_p.plot(xa, aa, color=APP["span1"], lw=0.6, zorder=2)
    ax_p.plot(xa, bb_, color=APP["span2"], lw=0.6, zorder=2)

    lo_p = float(np.nanmin(np.concatenate([d["low"], a, b, fa, fb,
                                           d["bb_dn"].dropna()])))
    hi_p = float(np.nanmax(np.concatenate([d["high"], a, b, fa, fb,
                                           d["bb_up"].dropna()])))
    span = (hi_p - lo_p) or 1.0
    ax_p.set_xlim(*xlim)
    ax_p.set_ylim(lo_p - span * 0.05, hi_p + span * 0.06)

    vol = d["volume"].to_numpy(dtype=float)
    has_vol = np.isfinite(vol).any() and np.nanmax(vol) > 0

    ax_p.plot(x, d["bb_up"], color=APP["bb_up"], lw=1.4, zorder=3)
    ax_p.plot(x, d["bb_dn"], color=APP["bb_dn"], lw=1.4, zorder=3)
    for key in ("ma5", "ma20", "ma60", "ma120"):
        ax_p.plot(x, d[key], color=APP[key], lw=1.7 if key == "ma20" else 1.2,
                  zorder=4)
    ax_p.plot(x, d["tenkan"], color=APP["tenkan"], lw=0.8, zorder=4)
    ax_p.plot(x, d["kijun"], color=APP["kijun"], lw=0.8, zorder=4)
    _candles(ax_p, x, d, body_w=0.7, wick_w=1.0,
             up_col=APP["candle_up"], dn_col=APP["candle_dn"])
    _app_tag(ax_p, close, f"{close:,.2f}\n{chg:+.2f}%", dcol,
             lambda t: f"{t:,.0f}", nlines=2)

    # ── 날짜 띠 ──
    ax_d.set_facecolor(APP["band"])
    for sp in ax_d.spines.values():
        sp.set_visible(False)
    ax_d.set_xlim(*xlim)
    ax_d.set_ylim(0, 1)
    ax_d.set_xticks([])
    ax_d.set_yticks([])
    fmt = "%m.%d" if tf == "일봉" else "%y.%m"
    for i in np.linspace(0, len(d) - 1, 5).astype(int)[:-1]:
        ax_d.text(i, 0.5, d.index[i].strftime(fmt), color=APP["band_txt"],
                  fontsize=11, va="center", ha="left")
    ax_d.text(len(d) - 1, 0.5, d.index[-1].strftime(fmt), color=APP["band_txt"],
              fontsize=11, va="center", ha="center")

    # ── 거래량 ──
    _app_style(ax_v)
    ax_v.set_xlim(*xlim)
    if has_vol:
        upc = (d["close"] >= d["open"]).to_numpy()
        ax_v.bar(x, vol, 0.7, color=np.where(upc, APP["candle_up"],
                                             APP["candle_dn"]), zorder=3)
        ax_v.set_ylim(0, np.nanmax(vol) * 1.35)
        _app_tag(ax_v, float(vol[-1]), _fmt_vol(float(vol[-1])), APP["tag_vol"],
                 _fmt_vol)
    else:
        ax_v.set_yticks([])
        ax_v.text(0.5, 0.45, "지수 거래량 데이터 미제공", color=APP["tick"],
                  fontsize=11, ha="center", va="center", transform=ax_v.transAxes)

    # ── MACD ──
    _app_style(ax_m)
    ax_m.set_xlim(*xlim)
    hh = d["macd_hist"].to_numpy(dtype=float)
    ax_m.bar(x, hh, 0.7, color=np.where(hh >= 0, APP["osc_pos"], APP["osc_neg"]),
             zorder=3)
    ax_m.axhline(0, color=APP["level"], lw=0.9, zorder=2)
    ax_m.plot(x, d["macd"], color=APP["macd"], lw=1.4, zorder=4)
    ax_m.plot(x, d["macd_sig"], color=APP["sig"], lw=1.2, zorder=4)
    _cross_arrows(ax_m, x, d["macd"], d["macd_sig"])
    mv = np.concatenate([d["macd"].dropna(), d["macd_sig"].dropna(),
                         d["macd_hist"].dropna(), [0.0]])
    mlo, mhi = float(mv.min()), float(mv.max())
    msp = (mhi - mlo) or 1.0
    ax_m.set_ylim(mlo - msp * 0.18, mhi + msp * 0.42)
    _level_label(ax_m, 0, "0.0")
    mval = float(d["macd"].iloc[-1])
    _app_tag(ax_m, mval, f"{mval:,.2f}", APP["tag_ind"], lambda t: f"{t:,.0f}"
             if msp >= 10 else f"{t:,.2f}")

    # ── RSI ──
    _app_style(ax_r)
    ax_r.set_xlim(*xlim)
    for lv in (70, 30):
        ax_r.axhline(lv, color=APP["level"], lw=0.9, zorder=2)
        _level_label(ax_r, lv, f"{lv:.1f}")
    ax_r.plot(x, d["rsi"], color=APP["rsi"], lw=1.4, zorder=4)
    ax_r.plot(x, d["rsi_sig"], color=APP["sig"], lw=1.2, zorder=4)
    _cross_arrows(ax_r, x, d["rsi"], d["rsi_sig"])
    ax_r.set_ylim(0, 118)
    ax_r.set_yticks([20, 40, 60, 80])
    rval = float(d["rsi"].iloc[-1])
    _app_tag(ax_r, rval, f"{rval:.2f}", APP["tag_ind"], lambda t: f"{t:.2f}")

    # ── 패널 이름 (색 글자) ──
    _pane_title(ax_v, [("거래량", C["ink"])])
    _pane_title(ax_m, [(f"-MACD+({PARAMS['macd_fast']},{PARAMS['macd_slow']})",
                        APP["macd"]),
                       (f"-Signal({PARAMS['macd_signal']})", APP["sig"]),
                       ("-OSC", APP["osc_pos"])])
    _pane_title(ax_r, [(f"-RSI({PARAMS['rsi_period']})", APP["rsi"]),
                       (f"-Signal({PARAMS['rsi_signal']})", APP["sig"])])

    fig.savefig(path, facecolor="#ffffff")
    plt.close(fig)


def make_blog_flows(flows_long: pd.DataFrame, date_str: str, path: str,
                    label: str = "코스피"):
    fig = plt.figure(figsize=BLOG_FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor(C["page"])
    _blog_header(fig, f"{label} 수급 흐름 — 투자자별 2년 누적 순매수 (조원)",
                 date_str)
    ax = fig.add_axes([0.05, 0.09, 0.86, 0.80])
    actors = ["개인", "외국인", "기관"]
    cum = flows_long[actors].cumsum() / 1e4
    x = np.arange(len(cum))
    ax.axhline(0, color=C["axis"], lw=1.0)
    for actor in actors:
        ax.plot(x, cum[actor], color=C[actor], lw=2.0, label=actor,
                solid_capstyle="round")
    # 끝값이 비슷해도 라벨끼리 겹치지 않게 세로 간격을 벌림
    last = [float(cum[a].iloc[-1]) for a in actors]
    ys = _spread_labels(last, _pt_to_data(ax, 11.5 * 1.4), ax.get_ylim()[1])
    for actor, v, y in zip(actors, last, ys):
        ax.annotate(f"{actor} {v:+.1f}조", xy=(x[-1], v),
                    xytext=(x[-1] + len(x) * 0.012, y), textcoords="data",
                    color=C[actor], fontsize=11.5, weight="bold", va="center",
                    annotation_clip=False)
    _style_ax(ax)
    ax.yaxis.tick_left()     # 오른쪽 끝은 투자자별 누적값 라벨 자리
    t = np.linspace(0, len(cum) - 1, 9).astype(int)
    ax.set_xticks(t)
    ax.set_xticklabels([cum.index[i].strftime("%y.%m") for i in t], fontsize=10)
    ax.set_xlim(0, len(cum) - 1)
    fig.savefig(path, facecolor=C["page"])
    plt.close(fig)


def _brief_lines(d: pd.DataFrame, unit: str) -> list[str]:
    """지표별 한 줄 요약 (마지막 봉 기준)."""
    last = d.iloc[-1]
    c = float(last["close"])
    L: list[str] = []
    mas = [last[k] for k in ("ma5", "ma20", "ma60", "ma120")]
    if all(pd.notna(m) for m in mas):
        arr = ("정배열" if mas == sorted(mas, reverse=True)
               else "역배열" if mas == sorted(mas) else "혼조")
        L.append(f"· 이평 {arr} · 20{unit}선 이격 {(c / mas[1] - 1) * 100:+.1f}%")
    a, b = last.get("senkou_a"), last.get("senkou_b")
    if pd.notna(a) and pd.notna(b):
        pos = ("구름 위" if c > max(a, b) else "구름 아래" if c < min(a, b)
               else "구름 안")
        tk = ("전환선>기준선" if last["tenkan"] > last["kijun"]
              else "전환선<기준선")
        L.append(f"· 일목 {pos} · {tk}")
    up, dn = last.get("bb_up"), last.get("bb_dn")
    if pd.notna(up) and pd.notna(dn) and up > dn:
        L.append(f"· 볼린저 %b {(c - dn) / (up - dn) * 100:.0f}%")
    if pd.notna(last.get("rsi")):
        rel = ""
        if pd.notna(last.get("rsi_sig")):
            rel = " (시그널 위)" if last["rsi"] >= last["rsi_sig"] else " (시그널 아래)"
        L.append(f"· RSI {last['rsi']:.1f}{rel}")
    if pd.notna(last.get("macd")) and pd.notna(last.get("macd_sig")):
        L.append("· MACD 시그널 " + ("위" if last["macd"] >= last["macd_sig"] else "아래")
                 + " · 0선 " + ("위" if last["macd"] >= 0 else "아래"))
    if pd.notna(last.get("vol_ratio")) and float(last["vol_ratio"]) > 0:
        L.append(f"· 거래량 평균 {float(last['vol_ratio']):.1f}배")
    return L


def _fx_brief(fx_rows: list[dict], flows_long: pd.DataFrame | None) -> list[str]:
    """환율·매크로 한 줄씩 + 환율-수급 부합 여부."""
    L: list[str] = []
    krw_d20 = None
    for r in fx_rows:
        meta, df = r["meta"], r["df"]
        v = float(df["close"].iloc[-1])
        v20 = float(df["close"].iloc[-21]) if len(df) > 21 else v
        if meta["name"] == "원/달러":
            krw_d20 = v - v20
        d20 = (f"{(v / v20 - 1) * 100:+.1f}%" if meta["unit"] == "pt"
               else f"{v - v20:+.2f}%p" if meta["unit"] == "%p"
               else f"{v - v20:+.1f}원")
        L.append(f"· {meta['name']} {meta['fmt'].format(v)} (20일 {d20})")
    if krw_d20 is not None and flows_long is not None and len(flows_long) >= 20:
        f20 = float(flows_long["외국인"].tail(20).sum()) / 1e4
        match = (krw_d20 < 0) == (f20 > 0)
        L.append(f"· 환율-수급 {'부합' if match else '엇갈림'} — 원화 "
                 f"{'강세' if krw_d20 < 0 else '약세'}, 외국인 20일 {f20:+.2f}조")
    return L


def build_blog_text(now: dt.datetime, rows: list[dict],
                    flows_long: pd.DataFrame | None,
                    img_names: dict,
                    fx_rows: list[dict] | None = None,
                    market: str = "all", extra: dict | None = None) -> str:
    """노션 게시용 본문 (간결). 《이미지 n》 자리에 해당 파일이 들어갑니다."""
    extra = extra or {}
    label = MARKET_LABEL.get(market, "")
    L: list[str] = [f"{now:%Y.%m.%d} ({WEEKDAY_KO[now.weekday()]}) "
                    f"{label + ' ' if label else ''}마감 종가 기준", ""]
    for r in rows:
        df = r["df"]
        close = float(df["close"].iloc[-1])
        chg = (close / float(df["close"].iloc[-2]) - 1) * 100
        L.append(f"· {r['meta']['name']} {_fmt_v(close)} ({chg:+.2f}%) — "
                 f"일봉 {r['vd']} / 주봉 {r['vw']}")
    L.append("")

    # 다가오는 경제 일정 (오늘부터 14일)
    today = dt.datetime.now(KST).date()
    events = [(dt.date.fromisoformat(d), name) for d, name, *_ in ECON_CALENDAR
              if today <= dt.date.fromisoformat(d) <= today + dt.timedelta(days=14)]
    if events:
        L.append("■ 다가오는 일정")
        L.extend(f"· {d:%m/%d} ({WEEKDAY_KO[d.weekday()]}) {name}"
                 for d, name in sorted(events))
        L.append("")

    img_no = 1
    for key, fl, label in (("flows", flows_long, "코스피"),
                           ("flows_kq", extra.get("flows_kq"), "코스닥")):
        if key not in img_names:
            continue
        L.append(f"《이미지 {img_no} — {img_names[key]}》")
        img_no += 1
        L.append(f"■ {label} 수급")
        cum = fl[["외국인", "기관", "개인"]]
        L.append("· 20일 " + " · ".join(
            f"{a} {cum[a].tail(20).sum() / 1e4:+.2f}조" for a in cum.columns))
        L.append("· 2년 " + " · ".join(
            f"{a} {cum[a].sum() / 1e4:+.1f}조" for a in cum.columns))
        L.append("")
    if "breadth" in img_names:
        L.append(f"《이미지 {img_no} — {img_names['breadth']}》")
        img_no += 1
        L.append("■ 시장 폭")
        for label, bd in extra.get("breadth", {}).items():
            last = bd.iloc[-1]
            adr = f" · ADR(20) {last['ADR']:.0f}%" if pd.notna(last["ADR"]) else ""
            L.append(f"· {label} 상승 {int(last['상승'])} · 하락 {int(last['하락'])}{adr}")
        L.append("")
    for key, rows_, title in (("fx", fx_rows, "환율·매크로"),
                              ("macro", extra.get("macro"), "금리·원자재")):
        if not rows_:
            continue
        if key in img_names:
            L.append(f"《이미지 {img_no} — {img_names[key]}》")
            img_no += 1
        L.append(f"■ {title}")
        L.extend(_fx_brief(rows_, flows_long if key == "fx" else None))
        L.append("")

    for r in rows:
        name = r["meta"]["name"]
        L.append(f"■ {name}")
        for tf in ("일봉", "주봉"):
            df = r["df"] if tf == "일봉" else r["dfw"]
            n = (CHART_PARAMS["daily_bars"] if tf == "일봉"
                 else CHART_PARAMS["weekly_bars"])
            unit = "일" if tf == "일봉" else "주"
            verdict = r["vd"] if tf == "일봉" else r["vw"]
            L.append(f"《이미지 {img_no} — {img_names[(name, tf, 'trend')]}》")
            img_no += 1
            L.append(f"[{tf} — {verdict}]")
            L.extend(_brief_lines(df.tail(n), unit))
            tops = _top_signals(r["sigs_d"] if tf == "일봉" else r["sigs_w"], 3)
            if tops:
                L.append("포착 신호: " + " / ".join(
                    f"{'▲' if s.direction > 0 else '▼' if s.direction < 0 else '●'}"
                    f"{s.title}" for s in tops))
        L.append("")

    L.append(DISCLAIMER)
    return "\n".join(L)


# ──────────────────────────────────────────────────────────────
# 인스타 캡션
# ──────────────────────────────────────────────────────────────

def build_chart_caption(now: dt.datetime, rows: list[dict],
                        flows_long: pd.DataFrame | None) -> str:
    date_str = f"{now:%Y.%m.%d} ({WEEKDAY_KO[now.weekday()]})"
    L = [f"📈 {date_str} 차트 분석 — 미국장 마감 + 전일 코스피", ""]
    L.append("이평선(5/20/60/120)·일목균형표·볼린저·RSI·MACD·거래량, "
             "일봉과 주봉을 함께 봅니다.")
    L.append("")
    for r in rows:
        meta, df = r["meta"], r["df"]
        close = float(df["close"].iloc[-1])
        chg = (close / float(df["close"].iloc[-2]) - 1) * 100
        L.append(f"◆ {meta['name']} {_fmt_v(close)} ({chg:+.2f}%)")
        L.append(f"  일봉 {r['vd']} · 주봉 {r['vw']}")
        for s in _top_signals(r["sigs_d"] + r["sigs_w"], 3):
            mk = "▲" if s.direction > 0 else ("▼" if s.direction < 0 else "●")
            tag = s.tf if s.tf == s.category else f"{s.tf}·{s.category}"
            L.append(f"  {mk} [{tag}] {s.title} — {s.desc}")
        L.append("")
    if flows_long is not None and len(flows_long) >= 10:
        f5 = flows_long.tail(5)
        L.append(f"💰 코스피 수급(5일): 외국인 {f5['외국인'].sum()/1e4:+.2f}조 · "
                 f"기관 {f5['기관'].sum()/1e4:+.2f}조")
        L.append("")
    L.append("차트와 지표 해설 전체는 카드에서, 지표별 적중률은 월간 리포트로 "
             "공개합니다.")
    L.append("")
    L.append(DISCLAIMER)
    L.append("")
    L.append(HASHTAGS_CHART)
    return "\n".join(L)


# ──────────────────────────────────────────────────────────────
# 요약 (summary.json) — 노션 DB 속성 · 월간 피드백용
# ──────────────────────────────────────────────────────────────

def write_summary(blog_dir: str, now: dt.datetime, rows: list[dict],
                  fx_rows: list[dict] | None,
                  flows_long: pd.DataFrame | None,
                  market: str = "all") -> dict:
    """그날의 판단·수치를 팩에 summary.json으로 저장."""
    indices = []
    for r in rows:
        df = r["df"]
        close = float(df["close"].iloc[-1])
        chg = (close / float(df["close"].iloc[-2]) - 1) * 100
        divs = [f"{tf} {'상승' if dv['kind'] == 'bull' else '하락'}"
                for tf, key in (("일봉", "div_d"), ("주봉", "div_w"))
                for dv in (r.get(key) or [])]
        indices.append({
            "name": r["meta"]["name"], "ticker": r["meta"]["ticker"],
            "close": round(close, 2), "chg": round(chg, 2),
            "vd": r["vd"], "vw": r["vw"],
            "sc_d": round(float(r["sc_d"]), 2), "sc_w": round(float(r["sc_w"]), 2),
            "divs": divs,
        })
    fx: dict = {}
    krw_d20 = None
    for fr in fx_rows or []:
        if fr["meta"]["name"] == "원/달러":
            d = fr["df"]
            v = float(d["close"].iloc[-1])
            v20 = float(d["close"].iloc[-21]) if len(d) > 21 else v
            krw_d20 = v - v20
            fx = {"krw": round(v, 1), "krw_d20": round(krw_d20, 1)}
    f20 = None
    if flows_long is not None and len(flows_long) >= 20:
        f20 = round(float(flows_long["외국인"].tail(20).sum()) / 1e4, 2)
    fx_flow = None   # 원화 강세+외국인 순매수 / 원화 약세+순매도 → 부합
    if krw_d20 and f20:
        fx_flow = "부합" if (krw_d20 < 0) == (f20 > 0) else "엇갈림"
    summary = {
        "date": f"{now:%Y-%m-%d}",
        "title": (f"{now:%Y.%m.%d} ({WEEKDAY_KO[now.weekday()]}) "
                  + (f"{MARKET_LABEL[market]} " if market in MARKET_LABEL
                     else "") + "차트 분석"),
        "market": MARKET_LABEL.get(market),
        "indices": indices, "fx": fx, "foreign_20d": f20, "fx_flow": fx_flow,
    }
    with open(os.path.join(blog_dir, "summary.json"), "w",
              encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    return summary


# ──────────────────────────────────────────────────────────────
# 실행 진입점
# ──────────────────────────────────────────────────────────────

def _load_flows(sample: bool, code: str = "KOSPI") -> pd.DataFrame | None:
    """수급 2년 (KOSPI/KOSDAQ) — 실데이터 캐시 우선, 없으면 합성(테스트)."""
    try:
        from .flowcache import load_flows_long
        fl = load_flows_long(code, FLOW_LONG_DAYS)
        if fl is not None and len(fl) > 40:
            return fl
    except Exception as e:
        print(f"  (수급 로드 실패 {code}: {e})")
    if sample:
        print(f"  [flows] {code} 캐시 없음 — 합성 수급 데이터 사용")
        return sample_flows(code, FLOW_LONG_DAYS)
    return None


def _load_breadth(sample: bool) -> dict:
    """시장 폭 {"코스피": df, "코스닥": df} — 실패한 시장은 빠짐."""
    from .breadth import load_breadth, sample_breadth
    out = {}
    for label, code in (("코스피", "KOSPI"), ("코스닥", "KOSDAQ")):
        try:
            df = sample_breadth(code) if sample else load_breadth(code)
            if df is not None and len(df) > 5:
                out[label] = df
        except Exception as e:
            print(f"  (시장 폭 로드 실패 {code}: {e})")
    return out


def make_blog_breadth(breadth: dict, date_str: str, path: str):
    """시장 폭 — 상승(위)·하락(아래) 종목 수 막대 + ADR(20) 선."""
    n = len(breadth)
    fig = plt.figure(figsize=BLOG_FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor(C["page"])
    _blog_header(fig, "시장 폭 — 상승·하락 종목 수 · ADR(20)", date_str)
    gs = fig.add_gridspec(n, 1, left=0.05, right=0.90, top=0.89, bottom=0.075,
                          hspace=0.42)
    for i, (label, df) in enumerate(breadth.items()):
        d = df.tail(60)
        x = np.arange(len(d))
        ax = fig.add_subplot(gs[i])
        ax.bar(x, d["상승"], 0.7, color=C["up"], label="상승")
        ax.bar(x, -d["하락"], 0.7, color=C["down"], label="하락")
        ax.axhline(0, color=C["axis"], lw=0.8)
        _style_ax(ax)
        ax.yaxis.tick_left()     # 오른쪽은 ADR 축
        adr = d["ADR"].iloc[-1]
        ax.set_title(label + (f"  ·  ADR(20) {adr:.0f}%" if pd.notna(adr) else ""),
                     color=C["ink"], fontsize=13, weight="bold", loc="left", pad=6)
        ax2 = ax.twinx()
        ax2.plot(x, d["ADR"], color=C["ink"], lw=1.6, label="ADR(20)")
        ax2.axhline(100, color=C["muted"], lw=0.8, ls="--")
        ax2.tick_params(colors=C["ink"], labelsize=9, length=0)
        for sp in ax2.spines.values():
            sp.set_visible(False)
        t = np.linspace(0, len(d) - 1, 6).astype(int)
        ax.set_xticks(t)
        ax.set_xticklabels([d.index[j].strftime("%m.%d") for j in t], fontsize=9)
        ax.set_xlim(-1, len(d))
        if i == 0:
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels()
            # 범례는 막대와 겹치지 않게 차트 위 오른쪽
            ax.legend(h1 + h2, l1 + l2, loc="lower right", bbox_to_anchor=(1, 1),
                      fontsize=9, ncols=3, frameon=False, labelcolor=C["ink2"],
                      borderaxespad=0.2)
    fig.savefig(path, facecolor=C["page"])
    plt.close(fig)


def run_chart(sample: bool = False, post: bool = False,
              force: bool = False, market: str = "all") -> list[str]:
    """market: "kr"(한국장 마감 — 코스피·니케이·수급·환율), "us"(미국장 마감 —
    나스닥100·S&P500·다우·비트코인), "all"(전부 한 페이지)."""
    os.makedirs(OUT, exist_ok=True)
    now = dt.datetime.now(KST)
    get_daily = sample_daily if sample else fetch_daily
    fetch_days = CHART_PARAMS["fetch_days"]
    metas = [m for m in CHART_INDICES
             if market == "all" or m["market"] in MARKET_GROUP[market]]
    with_kr = market in ("all", "kr")

    # ── 휴장일 체크: 한국장은 코스피 오늘 봉, 그 외는 S&P500 어제 이상 봉 ──
    if not sample and not force:
        try:
            anchor, lag = ("^KS11", 0) if market == "kr" else ("^GSPC", 1)
            ref = get_daily(anchor, 30)
            last_date = ref.index[-1].date()
            if last_date < now.date() - dt.timedelta(days=lag):
                label = MARKET_LABEL.get(market, "미국장")
                msg = (f"[차트 분석] {label} 최신 일봉이 아직 없어 스킵합니다 "
                       f"(최신: {last_date}) — 휴장일이거나 마감 전입니다. "
                       f"테스트는 --force를 쓰세요")
                print(msg)
                from .notify import send_telegram
                send_telegram(f"⏸ {msg}")
                return []
        except Exception as e:
            print(f"(휴장일 체크 실패, 계속 진행: {e})")

    # 매달 첫 실행: 지난 판단 적중률로 지표 가중치 갱신 (실데이터 실행만)
    report = None
    if not sample:
        try:
            from .feedback import monthly_update
            report = monthly_update(f"{now:%Y-%m}")
        except Exception as e:
            print(f"  (가중치 갱신 실패: {e})")

    flows_long = _load_flows(sample) if with_kr else None
    flows_kq = _load_flows(sample, "KOSDAQ") if with_kr else None
    weights = load_weights()
    if weights:
        print(f"[chart] 지표 가중치 적용: {weights}")

    rows: list[dict] = []
    for meta in metas:
        print(f"[chart] {meta['name']} ({meta['ticker']}) 분석 중...")
        try:
            df = add_indicators(get_daily(meta["ticker"], fetch_days))
        except Exception as e:
            print(f"  !! 시세 수집 실패, 건너뜀: {e}")
            continue
        dfw = to_weekly(df)

        # 다이버전스는 카드 표시 구간과 같은 창에서 탐지 (그림과 신호 일치)
        div_d = detect_divergence(df.tail(CHART_PARAMS["daily_bars"]),
                                  recent=20)
        div_w = detect_divergence(dfw.tail(CHART_PARAMS["weekly_bars"]),
                                  recent=12, max_span=30)

        sigs_d = (daily_signal_set(df) + sig_macd(df, "일봉")
                  + sig_rsi_signal(df, "일봉") + sig_divergence(div_d, "일봉"))
        fl = {"KOSPI": flows_long, "KOSDAQ": flows_kq}.get(meta.get("krx"))
        if fl is not None:
            sigs_d += signals_flows(fl.tail(15))
        sigs_w = (weekly_signal_set(dfw) + sig_macd(dfw, "주봉")
                  + sig_rsi_signal(dfw, "주봉") + sig_divergence(div_w, "주봉"))

        sc_d = weighted_score(sigs_d, weights)
        sc_w = weighted_score(sigs_w, weights)
        row = dict(meta=meta, df=df, dfw=dfw, sigs_d=sigs_d, sigs_w=sigs_w,
                   sc_d=sc_d, sc_w=sc_w, div_d=div_d, div_w=div_w,
                   vd=_verdict(sc_d, 3, 1), vw=_verdict(sc_w, 3, 1))
        rows.append(row)
        print(f"  -> 일봉 {row['vd']} ({sc_d:+.1f}) · 주봉 {row['vw']} "
              f"({sc_w:+.1f}), 신호 {len(sigs_d)}+{len(sigs_w)}개")

    if not rows:
        raise SystemExit("분석에 성공한 지수가 없습니다.")

    # 시장별 실행은 그 시장의 거래일(마지막 봉 날짜)을 페이지·로그 날짜로
    if market != "all":
        main = [r for r in rows if r["meta"]["market"] in ("KR", "US")] or rows
        day = max(r["df"].index[-1].date() for r in main)
        now = dt.datetime.combine(day, now.timetz())
    date_str = f"{now:%Y.%m.%d} ({WEEKDAY_KO[now.weekday()]})"
    for r in rows:
        log_chart(now, r["meta"]["name"], "일봉", r["sigs_d"],
                  float(r["df"]["close"].iloc[-1]))
        log_chart(now, r["meta"]["name"], "주봉", r["sigs_w"],
                  float(r["dfw"]["close"].iloc[-1]))

    # ── 팩 (output/blog_YYYYMMDD[_kr|_us]/) — 환율 흐름은 한국장에만 ──
    suffix = "" if market == "all" else f"_{market}"
    blog_dir = os.path.join(OUT, f"blog_{now:%Y%m%d}{suffix}")
    os.makedirs(blog_dir, exist_ok=True)
    fx_rows, macro_rows, breadth = [], [], {}
    if with_kr:
        print("[chart] 환율·금리 · 시장 폭 수집 중...")
        fx_rows = fetch_fx(sample)
        breadth = _load_breadth(sample)
    if market in ("all", "us"):
        print("[chart] 미국 금리 · 원자재 수집 중...")
        macro_rows = fetch_fx(sample, MACRO_SERIES)
    if fx_rows or macro_rows:
        log_fx(now, fx_rows + macro_rows)
    img_names: dict = {}
    img_no = 1
    for key, fl, label in (("flows", flows_long, "코스피"),
                           ("flows_kq", flows_kq, "코스닥")):
        if fl is not None and len(fl) > 40:
            fn = f"{img_no:02d}_{label}_수급_2년.png"
            make_blog_flows(fl, date_str, os.path.join(blog_dir, fn), label)
            img_names[key] = fn
            img_no += 1
    if breadth:
        fn = f"{img_no:02d}_시장폭.png"
        make_blog_breadth(breadth, date_str, os.path.join(blog_dir, fn))
        img_names["breadth"] = fn
        img_no += 1
    if fx_rows:
        fn = f"{img_no:02d}_환율_매크로.png"
        make_blog_fx(fx_rows, date_str, os.path.join(blog_dir, fn))
        img_names["fx"] = fn
        img_no += 1
    if macro_rows:
        fn = f"{img_no:02d}_금리_원자재.png"
        make_blog_fx(macro_rows, date_str, os.path.join(blog_dir, fn),
                     "금리·원자재")
        img_names["macro"] = fn
        img_no += 1
    for r in rows:
        name = r["meta"]["name"]
        safe_name = name.replace(" ", "").replace("/", "")
        for tf in ("일봉", "주봉"):
            fn = f"{img_no:02d}_{safe_name}_{tf}.png"
            make_blog_app(r, tf, date_str, os.path.join(blog_dir, fn))
            img_names[(name, tf, "trend")] = fn
            img_no += 1
    blog_txt = build_blog_text(now, rows, flows_long, img_names, fx_rows,
                               market, extra={"flows_kq": flows_kq,
                                              "breadth": breadth,
                                              "macro": macro_rows})
    with open(os.path.join(blog_dir, "본문.txt"), "w", encoding="utf-8") as f:
        f.write(blog_txt)
    write_summary(blog_dir, now, rows, fx_rows, flows_long, market)
    images = [os.path.join(blog_dir, fn) for fn in img_names.values()]

    print(f"\n[차트 분석] 블로그 팩 (이미지 {len(images)}장 + 본문) -> {blog_dir}")

    # ── 노션 아카이브: --post 실행 또는 NOTION_FORCE=1 ──
    # 노션 전용이라 게시 실패·토큰 없음은 실행 실패로 처리 (GitHub가 실패 메일 발송)
    dry = os.environ.get("NOTION_DRYRUN") == "1"
    if dry or (not sample and (post or os.environ.get("NOTION_FORCE") == "1")):
        from .notion import publish_pack
        try:
            url = publish_pack(blog_dir)
        except Exception as e:
            raise RuntimeError(f"노션 게시 실패 (블로그 팩은 생성됨: {blog_dir}): "
                               f"{e}") from e
        if url:
            print(f"[notion] 아카이브 게시 완료: {url}")
        elif not dry:
            raise RuntimeError("NOTION_TOKEN이 없어 노션에 올리지 못했습니다 — "
                               ".env 또는 GitHub Secrets를 확인하세요")
        # 5거래일 지난 페이지 피드백 자동 기록 + 월간 적중률 리포트 (실패해도 계속)
        try:
            from .feedback import feedback_props, report_text, verdict_results
            from .notion import publish_report, update_feedback
            names = [r["meta"]["name"] for r in rows]
            res = {d: feedback_props(v)
                   for d, v in verdict_results(names).items()}
            update_feedback(MARKET_LABEL.get(market), res)
            if report and not report["accuracy"].empty:   # 결과가 쌓인 달만
                rurl = publish_report(f"{report['month']} 적중률 리포트",
                                      report_text(report))
                print(f"[notion] 월간 적중률 리포트: {rurl}")
        except Exception as e:
            print(f"  (피드백 기록 실패: {type(e).__name__}: {e})")

    return images
