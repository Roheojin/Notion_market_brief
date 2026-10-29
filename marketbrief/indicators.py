# -*- coding: utf-8 -*-
"""기술적 지표 계산: 이평선, RSI, 볼린저밴드, 일목균형표, 거래량."""
import pandas as pd

from .config import PARAMS


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV DataFrame에 지표 컬럼을 추가해 반환."""
    out = df.copy()
    p = PARAMS

    # ── 이동평균선 ─────────────────────────────
    for w in p["ma_windows"]:
        out[f"ma{w}"] = out["close"].rolling(w).mean()

    # ── RSI (Wilder) ──────────────────────────
    period = p["rsi_period"]
    delta = out["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    out["rsi"] = 100 - 100 / (1 + rs)
    out["rsi_sig"] = out["rsi"].rolling(p.get("rsi_signal", 9)).mean()

    # ── 볼린저밴드 ────────────────────────────
    bb_p, bb_k = p["bb_period"], p["bb_std"]
    mid = out["close"].rolling(bb_p).mean()
    std = out["close"].rolling(bb_p).std(ddof=0)
    out["bb_mid"] = mid
    out["bb_up"] = mid + bb_k * std
    out["bb_dn"] = mid - bb_k * std
    out["bb_width"] = (out["bb_up"] - out["bb_dn"]) / mid
    out["bb_pctb"] = (out["close"] - out["bb_dn"]) / (out["bb_up"] - out["bb_dn"])

    # ── 일목균형표 ────────────────────────────
    ich = p["ichimoku"]
    t, k, sb, sh = ich["tenkan"], ich["kijun"], ich["senkou_b"], ich["shift"]
    out["tenkan"] = (out["high"].rolling(t).max() + out["low"].rolling(t).min()) / 2
    out["kijun"] = (out["high"].rolling(k).max() + out["low"].rolling(k).min()) / 2
    out["senkou_a"] = ((out["tenkan"] + out["kijun"]) / 2).shift(sh)
    out["senkou_b"] = (
        (out["high"].rolling(sb).max() + out["low"].rolling(sb).min()) / 2
    ).shift(sh)
    out["chikou"] = out["close"].shift(-sh)  # 후행스팬 (표시용: 뒤로 26일)

    # ── 거래량 ────────────────────────────────
    out["vol_ma"] = out["volume"].rolling(p["vol_ma"]).mean()
    out["vol_ratio"] = out["volume"] / out["vol_ma"]

    # ── MACD ──────────────────────────────────
    fast = p.get("macd_fast", 12)
    slow = p.get("macd_slow", 26)
    sig = p.get("macd_signal", 9)
    ema_fast = out["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = out["close"].ewm(span=slow, adjust=False).mean()
    out["macd"] = ema_fast - ema_slow
    out["macd_sig"] = out["macd"].ewm(span=sig, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_sig"]

    return out


def cloud_bounds(row) -> tuple[float, float]:
    """해당 시점 구름대의 상단/하단."""
    a, b = row["senkou_a"], row["senkou_b"]
    return (max(a, b), min(a, b))


# ──────────────────────────────────────────────
# 리샘플 (주봉 / 월봉)
# ──────────────────────────────────────────────

def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = pd.DataFrame({
        "open": df["open"].resample(rule).first(),
        "high": df["high"].resample(rule).max(),
        "low": df["low"].resample(rule).min(),
        "close": df["close"].resample(rule).last(),
        "volume": df["volume"].resample(rule).sum(),
    }).dropna(subset=["close"])
    return out


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """일봉 → 주봉 (금요일 마감 기준) + 지표."""
    return add_indicators(_resample(df, "W-FRI"))


def to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """일봉 → 월봉 + 지표."""
    return add_indicators(_resample(df, "ME"))
