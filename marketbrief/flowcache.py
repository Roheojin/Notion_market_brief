# -*- coding: utf-8 -*-
"""수급(투자자별 순매수) 장기 데이터 로컬 캐시.

주간 리뷰의 '수급 흐름' 차트는 약 2년치가 필요하지만, 매주 2년치를 통째로
다시 요청할 이유가 없습니다. 그래서:

  · 최초 1회      — 6개월씩 나눠 받아 2년치를 만들고 history/에 저장
  · 이후 매주      — 마지막 저장일 다음날부터 오늘까지(보통 7~10일)만 추가 요청
  · 조회 실패 시   — 캐시에 있는 데이터라도 그대로 반환 (카드가 통째로 사라지지 않음)

캐시 위치: history/flows_KOSPI.csv 등. GitHub Actions 워크플로가 history/를
커밋하므로 클라우드 실행에서도 누적됩니다.
"""
import datetime as dt
import os
import time

import pandas as pd

from .fetch import FLOW_COLS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "history")
CHUNK_DAYS = 180          # 한 번에 요청할 최대 달력일수
MAX_CHUNKS = 6            # 최초 백필 시 최대 요청 횟수 (약 3년치 상한)


def _path(krx_code: str) -> str:
    return os.path.join(CACHE_DIR, f"flows_{krx_code}.csv")


def _read_cache(krx_code: str) -> pd.DataFrame | None:
    p = _path(krx_code)
    if not os.path.exists(p):
        return None
    try:
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        df = df[[c for c in FLOW_COLS if c in df.columns]]
        return df.dropna(how="all").sort_index() if not df.empty else None
    except Exception as e:
        print(f"  (수급 캐시 읽기 실패, 새로 받습니다: {e})")
        return None


def _write_cache(krx_code: str, df: pd.DataFrame):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        df.sort_index().to_csv(_path(krx_code), encoding="utf-8-sig")
    except Exception as e:
        print(f"  (수급 캐시 저장 실패: {e})")


def _fetch_range(krx_code: str, frm: dt.date, to: dt.date) -> pd.DataFrame | None:
    """KRX 원본 조회 (달력일 구간 지정). 실패 시 None."""
    try:
        from pykrx import stock

        df = stock.get_market_trading_value_by_date(
            frm.strftime("%Y%m%d"), to.strftime("%Y%m%d"), krx_code)
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
        out = df[FLOW_COLS] / 1e8          # 원 -> 억원
        out.index = pd.to_datetime(out.index)
        return out
    except Exception as e:
        print(f"  (수급 조회 실패 {frm}~{to}: {type(e).__name__}: {e})")
        return None


def load_flows_long(krx_code: str, days: int = 490) -> pd.DataFrame | None:
    """장기 수급 데이터. 캐시를 쓰고 부족한 구간만 증분 요청."""
    today = dt.date.today()
    want_from = today - dt.timedelta(days=int(days * 1.5) + 30)

    cached = _read_cache(krx_code)
    chunks: list[pd.DataFrame] = []

    if cached is not None and not cached.empty:
        last = cached.index[-1].date()
        # 증분: 마지막 저장일 포함 3일 전부터 다시 받아 덮어씀
        # (장중·장 마감 직후에 저장된 날의 값도 다음 실행에서 확정값으로 갱신)
        frm = last - dt.timedelta(days=3)
        print(f"  [flows] {krx_code} 캐시 {len(cached)}행 (~{last}) "
              f"→ {frm}~{today} 증분 요청")
        got = _fetch_range(krx_code, frm, today)
        if got is not None:
            chunks.append(got)
        else:
            print("  [flows] 증분 요청 실패 — 기존 캐시로 진행")
            return cached.tail(days)
        base = cached
    else:
        # 최초 1회: 6개월씩 끊어서 백필 (긴 구간 한 번에 요청하면 자주 실패)
        print(f"  [flows] {krx_code} 캐시 없음 — {CHUNK_DAYS}일씩 나눠 백필")
        base = None
        cur_to = today
        for i in range(MAX_CHUNKS):
            cur_from = max(want_from, cur_to - dt.timedelta(days=CHUNK_DAYS))
            got = _fetch_range(krx_code, cur_from, cur_to)
            if got is None:
                print(f"  [flows] 구간 {i + 1} 실패 — 여기까지만 사용")
                break
            chunks.append(got)
            print(f"  [flows] 구간 {i + 1}: {cur_from}~{cur_to} {len(got)}행")
            if cur_from <= want_from:
                break
            cur_to = cur_from - dt.timedelta(days=1)
            time.sleep(0.5)

    if base is None and not chunks:
        return None

    merged = pd.concat([d for d in ([base] if base is not None else []) + chunks
                        if d is not None and not d.empty])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    _write_cache(krx_code, merged)
    print(f"  [flows] {krx_code} 누적 {len(merged)}행 "
          f"({merged.index[0].date()} ~ {merged.index[-1].date()})")
    return merged.tail(days)
