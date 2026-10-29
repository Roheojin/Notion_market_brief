# -*- coding: utf-8 -*-
"""신호 탐지 로직 — 시간축별 역할 분담.

단기 뷰 (일봉): 모멘텀·과열 지표
  이평선 크로스(5/20), 이격도, RSI, 볼린저밴드, 거래량, 전환선/기준선 크로스, 수급
중장기 뷰 (주봉): 추세 지표
  주봉 이평선 크로스·배열, 일목 구름대·후행스팬, 주봉 RSI
장기 국면 (월봉, 주간 리뷰 전용):
  20개월선 위/아래, 월봉 5/20 배열, 월봉 RSI

의도적으로 제외한 조합:
  일봉 배열/구름대 (추세 판단은 주봉이 더 신뢰적 — 중복 방지)
  주봉 볼린저·거래량 (주봉에서는 신호 대비 잡음이 큼)

방향: +1 강세 / -1 약세 / 0 중립·관찰,  강도: 1 보통 / 2 강함
"""
from dataclasses import dataclass, field

import pandas as pd

from .config import PARAMS
from .indicators import cloud_bounds

CROSS_LOOKBACK = 3  # 며칠(주) 이내의 교차를 "최근 발생"으로 볼지


@dataclass
class Signal:
    category: str      # 이평선 / RSI / 볼린저 / 일목 / 거래량 / 수급
    direction: int     # +1 / -1 / 0
    strength: int      # 1 / 2
    title: str
    desc: str
    horizon: str = "short"   # short(단기) / long(중장기)
    tf: str = "일봉"          # 일봉 / 주봉 / 수급 (카드 우측 태그)

    @property
    def score(self) -> float:
        return self.direction * self.strength


@dataclass
class Analysis:
    signals: list[Signal] = field(default_factory=list)
    score: float = 0.0
    verdict: str = "중립"
    close: float = 0.0
    change_pct: float = 0.0
    rsi: float = 0.0
    spark: object = None                 # 최근 20일 종가 (표지 스파크라인)
    prev_verdict: str | None = None      # 전일 종합 판단 (전환 감지)
    change_reasons: list = field(default_factory=list)
    short_score: float = 0.0
    long_score: float = 0.0
    short_verdict: str = "중립"          # 단기 뷰 (일봉)
    long_verdict: str = "중립"           # 중장기 뷰 (주봉)


def _crossed_above(a: pd.Series, b: pd.Series, lookback: int = CROSS_LOOKBACK) -> bool:
    diff = (a - b).dropna()
    if len(diff) < lookback + 1:
        return False
    recent = diff.iloc[-(lookback + 1):]
    return bool((recent.iloc[:-1] <= 0).any() and recent.iloc[-1] > 0)


def _crossed_below(a: pd.Series, b: pd.Series, lookback: int = CROSS_LOOKBACK) -> bool:
    return _crossed_above(b, a, lookback)


def _streak(s: pd.Series) -> int:
    """마지막 값 기준 같은 부호 연속 일수 (+ 순매수 / - 순매도)."""
    vals = s.dropna().to_numpy()
    if len(vals) == 0 or vals[-1] == 0:
        return 0
    sign = 1 if vals[-1] > 0 else -1
    n = 0
    for v in vals[::-1]:
        if v * sign > 0:
            n += 1
        else:
            break
    return n * sign


# ──────────────────────────────────────────────────────────────
# 일봉(단기) 신호
# ──────────────────────────────────────────────────────────────

def sig_ma_daily(df: pd.DataFrame) -> list[Signal]:
    s: list[Signal] = []
    last = df.iloc[-1]

    if _crossed_above(df["ma5"], df["ma20"]):
        s.append(Signal("이평선", +1, 2, "골든크로스",
                        "5일선이 20일선을 상향 돌파 — 단기 상승 전환 신호"))
    elif _crossed_below(df["ma5"], df["ma20"]):
        s.append(Signal("이평선", -1, 2, "데드크로스",
                        "5일선이 20일선을 하향 이탈 — 단기 하락 전환 신호"))

    ma20 = last["ma20"]
    if pd.notna(ma20) and ma20 > 0:
        disp = (last["close"] / ma20 - 1) * 100
        if disp >= 5:
            s.append(Signal("이평선", -1, 1, "이격 과열",
                            f"20일선 대비 +{disp:.1f}% 이격 — 단기 과열 주의"))
        elif disp <= -5:
            s.append(Signal("이평선", +1, 1, "이격 과대",
                            f"20일선 대비 {disp:.1f}% 이격 — 기술적 반등 여지"))
    return s


def sig_rsi_daily(df: pd.DataFrame) -> list[Signal]:
    s: list[Signal] = []
    rsi = df["rsi"]
    cur, prev = rsi.iloc[-1], rsi.iloc[-2]

    if cur >= 70:
        s.append(Signal("RSI", -1, 1, "과매수",
                        f"RSI {cur:.0f} — 과매수권, 단기 조정 가능성"))
    elif cur <= 30:
        s.append(Signal("RSI", +1, 1, "과매도",
                        f"RSI {cur:.0f} — 과매도권, 반등 관찰 구간"))

    if prev <= 30 < cur:
        s.append(Signal("RSI", +1, 2, "과매도 탈출",
                        "RSI가 30선을 상향 돌파 — 반등 신호"))
    elif prev >= 70 > cur:
        s.append(Signal("RSI", -1, 2, "과매수 이탈",
                        "RSI가 70선을 하향 이탈 — 조정 시작 신호"))
    elif prev < 50 <= cur:
        s.append(Signal("RSI", +1, 1, "모멘텀 전환(상)",
                        "RSI 50선 상향 돌파 — 매수 우위 전환"))
    elif prev > 50 >= cur:
        s.append(Signal("RSI", -1, 1, "모멘텀 전환(하)",
                        "RSI 50선 하향 이탈 — 매도 우위 전환"))
    return s


def sig_bb_daily(df: pd.DataFrame) -> list[Signal]:
    s: list[Signal] = []
    last = df.iloc[-1]
    close, up, dn = last["close"], last["bb_up"], last["bb_dn"]
    if pd.isna(up):
        return s

    if close > up:
        riding = (df["close"] > df["bb_up"]).iloc[-3:].all()
        if riding:
            s.append(Signal("볼린저", +1, 1, "밴드 타기",
                            "상단 밴드를 따라 상승 지속 — 강한 추세, 과열 병존"))
        else:
            s.append(Signal("볼린저", -1, 1, "상단 돌파",
                            "상단 밴드 돌파 — 단기 과열, 되돌림 주의"))
    elif close < dn:
        s.append(Signal("볼린저", +1, 1, "하단 이탈",
                        "하단 밴드 이탈 — 과매도, 기술적 반등 관찰"))

    width = df["bb_width"].dropna()
    if len(width) >= 120:
        if width.tail(120).rank(pct=True).iloc[-1] <= 0.10:
            s.append(Signal("볼린저", 0, 1, "스퀴즈",
                            "밴드폭이 6개월 최저 수준 — 변동성 확대 임박"))
    return s


def sig_ichimoku_daily(df: pd.DataFrame) -> list[Signal]:
    """일봉 일목은 전환선/기준선 크로스만 (구름대·후행스팬은 주봉에서)."""
    s: list[Signal] = []
    if pd.isna(df["tenkan"].iloc[-1]) or pd.isna(df["kijun"].iloc[-1]):
        return s
    if _crossed_above(df["tenkan"], df["kijun"]):
        s.append(Signal("일목", +1, 1, "전환선 골든크로스",
                        "전환선이 기준선 상향 돌파 — 단기 매수 우위"))
    elif _crossed_below(df["tenkan"], df["kijun"]):
        s.append(Signal("일목", -1, 1, "전환선 데드크로스",
                        "전환선이 기준선 하향 이탈 — 단기 매도 우위"))
    return s


def sig_volume_daily(df: pd.DataFrame) -> list[Signal]:
    s: list[Signal] = []
    last = df.iloc[-1]
    ratio = last["vol_ratio"]
    if pd.isna(ratio) or last["vol_ma"] == 0:
        return s
    up_day = last["close"] >= df["close"].iloc[-2]

    if ratio >= 2.0:
        if up_day:
            s.append(Signal("거래량", +1, 2, "거래 급증+상승",
                            f"평균 대비 {ratio:.1f}배 거래량 실린 상승 — 매수세 유입"))
        else:
            s.append(Signal("거래량", -1, 2, "거래 급증+하락",
                            f"평균 대비 {ratio:.1f}배 거래량 실린 하락 — 매도 압력"))
    elif ratio >= 1.5:
        s.append(Signal("거래량", +1 if up_day else -1, 1, "거래 증가",
                        f"평균 대비 {ratio:.1f}배 — {'상승' if up_day else '하락'}에 무게"))
    elif ratio <= 0.5:
        s.append(Signal("거래량", 0, 1, "거래 한산",
                        f"평균 대비 {ratio:.1f}배 — 관망세, 에너지 응축"))
    return s


def signals_flows(flows: pd.DataFrame) -> list[Signal]:
    """투자자별 수급 신호 (단기 축, 국내 전용)."""
    s: list[Signal] = []
    if flows is None or flows.empty:
        return s
    last = flows.iloc[-1]

    for actor in ("외국인", "기관"):
        st = _streak(flows[actor])
        if st >= 3:
            s.append(Signal("수급", +1, 2 if st >= 5 else 1,
                            f"{actor} 연속 순매수",
                            f"{actor} {st}일 연속 순매수 — 수급 개선", tf="수급"))
        elif st <= -3:
            s.append(Signal("수급", -1, 2 if st <= -5 else 1,
                            f"{actor} 연속 순매도",
                            f"{actor} {-st}일 연속 순매도 — 수급 부담", tf="수급"))

    if last["외국인"] > 0 and last["기관"] > 0:
        s.append(Signal("수급", +1, 1, "쌍끌이 매수",
                        "외국인·기관 동반 순매수 — 강한 매수 주체", tf="수급"))
    elif last["외국인"] < 0 and last["기관"] < 0:
        s.append(Signal("수급", -1, 1, "쌍끌이 매도",
                        "외국인·기관 동반 순매도 — 수급 이탈", tf="수급"))
    return s


def daily_signal_set(df: pd.DataFrame) -> list[Signal]:
    return (sig_ma_daily(df) + sig_rsi_daily(df) + sig_bb_daily(df)
            + sig_ichimoku_daily(df) + sig_volume_daily(df))


# ──────────────────────────────────────────────────────────────
# 주봉(중장기) 신호
# ──────────────────────────────────────────────────────────────

def _w(sig: Signal) -> Signal:
    sig.horizon = "long"
    sig.tf = "주봉"
    return sig


def weekly_signal_set(dfw: pd.DataFrame) -> list[Signal]:
    if dfw is None or len(dfw) < 25:
        return []
    s: list[Signal] = []
    last = dfw.iloc[-1]

    # 주봉 이평선 크로스 (5주/20주)
    if _crossed_above(dfw["ma5"], dfw["ma20"], lookback=2):
        s.append(_w(Signal("이평선", +1, 2, "주봉 골든크로스",
                           "5주선이 20주선을 상향 돌파 — 중기 추세 전환 신호")))
    elif _crossed_below(dfw["ma5"], dfw["ma20"], lookback=2):
        s.append(_w(Signal("이평선", -1, 2, "주봉 데드크로스",
                           "5주선이 20주선을 하향 이탈 — 중기 추세 훼손")))

    # 주봉 배열 (5>20>60주)
    ma5, ma20, ma60 = last["ma5"], last["ma20"], last["ma60"]
    if pd.notna(ma60):
        if ma5 > ma20 > ma60:
            s.append(_w(Signal("이평선", +1, 1, "주봉 정배열",
                               "5>20>60주 정배열 — 중장기 상승 추세")))
        elif ma5 < ma20 < ma60:
            s.append(_w(Signal("이평선", -1, 1, "주봉 역배열",
                               "5<20<60주 역배열 — 중장기 하락 추세")))

    # 일목 구름대 (주봉)
    if pd.notna(last["senkou_a"]) and pd.notna(last["senkou_b"]):
        top, bot = cloud_bounds(last)
        close = last["close"]
        if close > top:
            s.append(_w(Signal("일목", +1, 1, "구름대 위(주봉)",
                               "주봉이 구름대 상단 위 — 중장기 상승 국면")))
        elif close < bot:
            s.append(_w(Signal("일목", -1, 1, "구름대 아래(주봉)",
                               "주봉이 구름대 하단 아래 — 중장기 하락 국면")))
        else:
            s.append(_w(Signal("일목", 0, 1, "구름대 진입(주봉)",
                               "주봉이 구름대 내부 — 중장기 방향 탐색")))

    # 후행스팬 (주봉)
    shift = PARAMS["ichimoku"]["shift"]
    if len(dfw) > shift:
        close = last["close"]
        past = dfw["close"].iloc[-1 - shift]
        if close > past * 1.01:
            s.append(_w(Signal("일목", +1, 1, "후행스팬 호전(주봉)",
                               "26주 전 주가 위 — 중장기 수급 우위")))
        elif close < past * 0.99:
            s.append(_w(Signal("일목", -1, 1, "후행스팬 역전(주봉)",
                               "26주 전 주가 아래 — 중장기 수급 열위")))

    # 주봉 RSI (과열/침체만 — 50선 잦은 신호는 제외)
    rsi = dfw["rsi"].iloc[-1]
    if pd.notna(rsi):
        if rsi >= 70:
            s.append(_w(Signal("RSI", -1, 1, "주봉 RSI 과열",
                               f"주봉 RSI {rsi:.0f} — 중기 과열권")))
        elif rsi <= 30:
            s.append(_w(Signal("RSI", +1, 1, "주봉 RSI 침체",
                               f"주봉 RSI {rsi:.0f} — 중기 침체권, 바닥 관찰")))
    return s


# ──────────────────────────────────────────────────────────────
# 종합
# ──────────────────────────────────────────────────────────────

def _verdict(sc: float, hi: float, lo: float) -> str:
    if sc >= hi:
        return "강세"
    if sc >= lo:
        return "다소 강세"
    if sc <= -hi:
        return "약세"
    if sc <= -lo:
        return "다소 약세"
    return "중립"


def analyze(df: pd.DataFrame, flows: pd.DataFrame | None = None,
            dfw: pd.DataFrame | None = None) -> Analysis:
    """df: 일봉(지표 포함), dfw: 주봉(지표 포함, 없으면 중장기 뷰 생략)."""
    daily = daily_signal_set(df) + signals_flows(flows)
    weekly = weekly_signal_set(dfw)
    sigs = daily + weekly

    short_score = sum(x.score for x in daily)
    long_score = sum(x.score for x in weekly)
    score = short_score + long_score

    close = float(df["close"].iloc[-1])
    prev = float(df["close"].iloc[-2])
    return Analysis(
        signals=sigs,
        score=score,
        verdict=_verdict(score, 4, 2),
        short_score=short_score,
        long_score=long_score,
        short_verdict=_verdict(short_score, 3, 1),
        long_verdict=_verdict(long_score, 3, 1),
        close=close,
        change_pct=(close / prev - 1) * 100,
        rsi=float(df["rsi"].iloc[-1]),
        spark=df["close"].tail(20),
    )


def analyze_monthly(dfm: pd.DataFrame) -> tuple[str, str]:
    """월봉 국면 판단 (주간 리뷰용). 반환: (판단, 근거 한 줄).

    지표는 3개만: 20개월선 위/아래, 월봉 5/20 배열, 월봉 RSI.
    """
    if dfm is None or len(dfm) < 24:
        return "판단 불가", "월봉 데이터 부족"
    last = dfm.iloc[-1]
    close, ma5, ma20 = last["close"], last["ma5"], last["ma20"]
    rsi = last["rsi"]

    pts = 0
    why = []
    if pd.notna(ma20):
        if close > ma20:
            pts += 1
            why.append("20개월선 위")
        else:
            pts -= 1
            why.append("20개월선 아래")
    if pd.notna(ma5) and pd.notna(ma20):
        if ma5 > ma20:
            pts += 1
        else:
            pts -= 1
    if pd.notna(rsi):
        if rsi >= 70:
            why.append(f"월봉 RSI {rsi:.0f} 과열")
        elif rsi <= 40:
            why.append(f"월봉 RSI {rsi:.0f} 침체")

    if pts >= 2:
        verdict = "상승 국면"
    elif pts <= -2:
        verdict = "하락 국면"
    else:
        verdict = "횡보·전환 구간"
    return verdict, " · ".join(why)
