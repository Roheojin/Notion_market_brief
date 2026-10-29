# -*- coding: utf-8 -*-
"""시장 폭(상승·하락 종목 수) — KRX 전 종목 등락률로 매일 집계, history/에 캐시.

  · ADR(20) = 최근 20거래일 상승 종목 합 / 하락 종목 합 × 100
    (120↑ 과열, 75↓ 침체로 흔히 봅니다)
  · 캐시: history/breadth_KOSPI.csv · breadth_KOSDAQ.csv (날짜, 상승, 하락, 보합)
  · 마지막 저장일부터 오늘까지만 하루씩 조회 (최초 1회는 약 60영업일 백필)
"""
import datetime as dt
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "history")
BACKFILL_DAYS = 90        # 최초 백필 달력일 (약 60영업일)
COLS = ["상승", "하락", "보합"]


def _path(market: str) -> str:
    return os.path.join(CACHE_DIR, f"breadth_{market}.csv")


def _read(market: str) -> pd.DataFrame | None:
    p = _path(market)
    if not os.path.exists(p):
        return None
    try:
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        return df[COLS].sort_index() if not df.empty else None
    except Exception as e:
        print(f"  (시장 폭 캐시 읽기 실패: {e})")
        return None


def _fetch_day(market: str, day: dt.date) -> dict | None:
    """그날 전 종목 등락률로 상승/하락/보합 수. 휴장일이면 None."""
    from pykrx import stock

    df = stock.get_market_ohlcv(day.strftime("%Y%m%d"), market=market)
    if df is None or df.empty or "등락률" not in df.columns:
        return None
    if "거래량" in df.columns and float(df["거래량"].sum()) == 0:
        return None
    r = df["등락률"]
    return {"상승": int((r > 0).sum()), "하락": int((r < 0).sum()),
            "보합": int((r == 0).sum())}


def load_breadth(market: str, days: int = 120) -> pd.DataFrame | None:
    """시장 폭 일별 집계 (+ADR20). 실패하면 있는 캐시만, 없으면 None."""
    today = dt.date.today()
    cached = _read(market)
    if cached is not None:
        # 마지막 저장일도 다시 받아 덮어씀 (장중 저장분 확정값으로 갱신)
        start = cached.index[-1].date()
    else:
        start = today - dt.timedelta(days=BACKFILL_DAYS)
    rows = {}
    day = start
    try:
        while day <= today:
            if day.weekday() < 5:
                got = _fetch_day(market, day)
                if got:
                    rows[pd.Timestamp(day)] = got
            day += dt.timedelta(days=1)
    except Exception as e:
        print(f"  (시장 폭 조회 실패 {market} {day}: {type(e).__name__}: {e})")
    new = pd.DataFrame.from_dict(rows, orient="index", columns=COLS) if rows else None
    parts = [d for d in (cached, new) if d is not None and not d.empty]
    if not parts:
        return None
    merged = pd.concat(parts)
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        merged.to_csv(_path(market), encoding="utf-8-sig")
    except Exception as e:
        print(f"  (시장 폭 캐시 저장 실패: {e})")
    return add_adr(merged.tail(days))


def add_adr(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    df = df.copy()
    df["ADR"] = (df["상승"].rolling(n).sum()
                 / df["하락"].rolling(n).sum().replace(0, np.nan) * 100)
    return df


def sample_breadth(market: str, days: int = 120) -> pd.DataFrame:
    """합성 시장 폭 (테스트용)."""
    import zlib

    rng = np.random.default_rng(zlib.crc32(("breadth" + market).encode()))
    total = 950 if market == "KOSPI" else 1750
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    p = np.clip(0.5 + np.cumsum(rng.normal(0, 0.03, days)) * 0.3, 0.2, 0.8)
    up = (p * total).astype(int)
    flat = rng.integers(20, 60, days)
    down = total - up - flat
    return add_adr(pd.DataFrame({"상승": up, "하락": down, "보합": flat}, index=idx))
