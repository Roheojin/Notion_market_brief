# -*- coding: utf-8 -*-
"""일봉 데이터 수집 (yfinance) + 국내 투자자별 수급 (pykrx/KRX).

--sample 모드에서는 합성 데이터 생성.
"""
import datetime as dt

import numpy as np
import pandas as pd

from .config import PARAMS

FLOW_COLS = ["개인", "외국인", "기관"]  # 순매수 대금 (억원)
FLOW_LONG_DAYS = 490  # 수급 흐름 차트 기간 (약 2년 거래일)


def fetch_daily(ticker: str, days: int | None = None) -> pd.DataFrame:
    """yfinance에서 일봉 OHLCV를 받아 표준 컬럼(open/high/low/close/volume)으로 반환."""
    import yfinance as yf

    days = days or PARAMS["history_days"]
    df = yf.download(
        ticker,
        period=f"{max(days, 260) + 120}d",
        interval="1d",
        auto_adjust=False,
        progress=False,
    )
    if df is None or df.empty:
        raise RuntimeError(f"데이터 수신 실패: {ticker}")
    # yfinance 멀티인덱스 컬럼 정리
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    df = df.dropna(subset=["close"])
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df.tail(days)


def sample_daily(ticker: str, days: int | None = None, seed: int | None = None) -> pd.DataFrame:
    """실데이터를 못 받는 환경에서 파이프라인 검증용 합성 일봉 생성."""
    days = days or PARAMS["history_days"]
    import zlib
    rng = np.random.default_rng(seed if seed is not None else zlib.crc32(ticker.encode()))
    n = days
    # 국면(레짐)이 있는 수익률: 추세 + 노이즈
    regimes = []
    left = n
    while left > 0:
        length = int(rng.integers(15, 60))
        drift = rng.normal(0, 0.0015)
        vol = rng.uniform(0.008, 0.022)
        regimes.append((min(length, left), drift, vol))
        left -= length
    rets = np.concatenate([rng.normal(d, v, size=m) for m, d, v in regimes])[:n]
    base = {"^KS11": 2600, "^KQ11": 850, "^GSPC": 5600, "^IXIC": 18000,
            "005930.KS": 72000, "000660.KS": 180000, "NVDA": 130, "TSLA": 250}.get(ticker, 100)
    close = base * np.exp(np.cumsum(rets))
    intraday = np.abs(rng.normal(0, 0.008, size=n))
    open_ = close * (1 + rng.normal(0, 0.004, size=n))
    high = np.maximum(open_, close) * (1 + intraday)
    low = np.minimum(open_, close) * (1 - intraday)
    vol_base = rng.uniform(3e5, 5e7)
    volume = vol_base * (1 + 8 * np.abs(rets) + rng.uniform(0, 0.6, size=n))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    m = len(idx)
    return pd.DataFrame(
        {"open": open_[-m:], "high": high[-m:], "low": low[-m:],
         "close": close[-m:], "volume": volume[-m:]},
        index=idx,
    )


# ──────────────────────────────────────────────────────────────
# 국내 투자자별 수급 (개인/외국인/기관 순매수, 억원)
# ──────────────────────────────────────────────────────────────

def fetch_flows(krx_code: str, days: int = 15) -> pd.DataFrame | None:
    """KRX 투자자별 순매수 대금. krx_code: 'KOSPI'/'KOSDAQ' 또는 '005930'.

    pykrx 최신 버전은 KRX 정보데이터시스템 무료 계정이 필요합니다
    (환경변수 KRX_ID / KRX_PW). 실패하면 None을 반환하고 수급 없이 진행합니다.
    """
    try:
        from pykrx import stock

        today = dt.date.today()
        frm = (today - dt.timedelta(days=days * 2 + 10)).strftime("%Y%m%d")
        to = today.strftime("%Y%m%d")
        df = stock.get_market_trading_value_by_date(frm, to, krx_code)
        if df is None or df.empty:
            return None
        rename = {}
        for c in df.columns:
            if "개인" in c:
                rename[c] = "개인"
            elif "외국인" in c and "기타" not in c:
                rename[c] = "외국인"
            elif c in ("기관합계", "기관"):
                rename[c] = "기관"
        df = df.rename(columns=rename)
        if not set(FLOW_COLS).issubset(df.columns):
            return None
        out = df[FLOW_COLS] / 1e8  # 원 -> 억원
        out.index = pd.to_datetime(out.index)
        return out.tail(days)
    except Exception as e:
        print(f"  (수급 조회 실패 — 수급 없이 진행: {e})")
        return None


def sample_flows(krx_code: str, days: int = 15) -> pd.DataFrame:
    """수급 합성 데이터 (테스트용). 관성이 있는 순매수 흐름 생성."""
    import zlib

    rng = np.random.default_rng(zlib.crc32(("flow" + krx_code).encode()))
    scale = 4000 if krx_code in ("KOSPI", "KOSDAQ") else 300  # 억원
    data = {}
    for i, col in enumerate(FLOW_COLS):
        x = np.zeros(days)
        x[0] = rng.normal(0, scale * 0.5)
        drift = rng.normal(0, scale * 0.08)  # 장기 매수/매도 편향 재현
        for t in range(1, days):  # AR(1): 연속 순매수 흐름 재현
            x[t] = 0.55 * x[t - 1] + drift + rng.normal(0, scale * 0.6)
        data[col] = x
    df = pd.DataFrame(data, index=pd.bdate_range(end=pd.Timestamp.today().normalize(),
                                                 periods=days))
    # 개인 ≈ -(외국인+기관) 경향 반영
    df["개인"] = -(df["외국인"] + df["기관"]) * rng.uniform(0.7, 1.0) \
        + rng.normal(0, scale * 0.2, size=len(df))
    return df
