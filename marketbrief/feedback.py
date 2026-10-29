# -*- coding: utf-8 -*-
"""판단 적중률 — history/chart_log.csv로 계산.

  · 판단: 그날 카테고리 점수 합의 부호 (+ 강세 쪽 / - 약세 쪽, 0은 제외)
  · 결과: 일봉은 5거래일 뒤, 주봉은 20거래일 뒤 종가 방향
  · 노션 피드백: 5거래일이 지난 페이지의 '피드백' · '피드백 메모'를 자동으로 채움
  · 가중치: 매달 첫 실행에 최근 60거래일 카테고리별 적중률로
    history/indicator_weights.json 갱신 (표본 20개 이상만, 0.5~1.5배)
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST_DIR = os.path.join(ROOT, "history")
CHART_LOG = os.path.join(HIST_DIR, "chart_log.csv")
WEIGHTS_PATH = os.path.join(HIST_DIR, "indicator_weights.json")
STATE_PATH = os.path.join(HIST_DIR, "feedback_state.json")
HORIZON = {"일봉": 5, "주봉": 20}
MIN_SAMPLES = 20


def _load() -> pd.DataFrame | None:
    if not os.path.exists(CHART_LOG):
        return None
    df = pd.read_csv(CHART_LOG, encoding="utf-8-sig")
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    return df


def _with_forward(df: pd.DataFrame) -> pd.DataFrame:
    """(지수, 시간축)별 날짜 순서로 N회 뒤 종가 대비 수익률 열(fwd)을 붙임."""
    out = []
    for (name, tf), g in df.groupby(["name", "tf"]):
        closes = g.groupby("date")["close"].last().sort_index()
        fwd = closes.shift(-HORIZON.get(tf, 5)) / closes - 1
        out.append(g.merge(fwd.rename("fwd"), left_on="date", right_index=True))
    return pd.concat(out) if out else df.assign(fwd=np.nan)


def verdict_results(names: list[str]) -> dict:
    """날짜 → [(지수, 점수합, 수익률)] — 일봉 판단 중 결과가 나온 것만."""
    df = _load()
    if df is None:
        return {}
    df = _with_forward(df[(df["tf"] == "일봉") & df["name"].isin(names)])
    tot = df.groupby(["date", "name"]).agg(score=("score", "sum"),
                                           fwd=("fwd", "first")).reset_index()
    tot = tot.dropna(subset=["fwd"])
    res: dict = {}
    for _, r in tot.iterrows():
        res.setdefault(r["date"].date(), []).append(
            (r["name"], float(r["score"]), float(r["fwd"])))
    return res


def feedback_props(items: list[tuple]) -> tuple[str, str]:
    """[(지수, 점수, 수익률)] → (피드백 선택값, 메모)."""
    hit = miss = 0
    memo = []
    for name, score, fwd in items:
        if score == 0:
            memo.append(f"{name} 중립 {fwd * 100:+.1f}%")
            continue
        ok = (score > 0) == (fwd > 0)
        hit, miss = hit + ok, miss + (not ok)
        memo.append(f"{name} {'강세' if score > 0 else '약세'}→{fwd * 100:+.1f}% "
                    f"{'✓' if ok else '✗'}")
    sel = "보류" if hit + miss == 0 else ("적중" if hit >= miss else "빗나감")
    return sel, " / ".join(memo) + " (5거래일 뒤)"


def category_accuracy(last_days: int = 60) -> pd.DataFrame:
    """카테고리별 적중률 (일봉, 최근 last_days 날짜)."""
    df = _load()
    if df is None:
        return pd.DataFrame()
    df = _with_forward(df[df["tf"] == "일봉"]).dropna(subset=["fwd"])
    df = df[df["date"].isin(sorted(df["date"].unique())[-last_days:])]
    df = df[df["score"] != 0]
    if df.empty:
        return pd.DataFrame()
    df["hit"] = (df["score"] > 0) == (df["fwd"] > 0)
    acc = df.groupby("category")["hit"].agg(["mean", "count"])
    acc.columns = ["적중률", "표본"]
    return acc


def monthly_update(month: str) -> dict | None:
    """그 달 첫 실행이면 가중치를 갱신하고 리포트 내용을 돌려줌. 이미 했으면 None."""
    state = {}
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    if state.get("weights_month") == month:
        return None
    acc = category_accuracy()
    weights = {}
    if os.path.exists(WEIGHTS_PATH):
        with open(WEIGHTS_PATH, encoding="utf-8") as f:
            weights = json.load(f)
    for cat, r in acc.iterrows():
        if r["표본"] >= MIN_SAMPLES:
            weights[cat] = round(float(np.clip(1 + (r["적중률"] - 0.5) * 2,
                                               0.5, 1.5)), 2)
    os.makedirs(HIST_DIR, exist_ok=True)
    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(weights, f, ensure_ascii=False, indent=1)
    state["weights_month"] = month
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    return {"month": month, "accuracy": acc, "weights": weights}


def report_text(rep: dict) -> str:
    """월간 리포트 본문 (notion.text_to_blocks 형식)."""
    L = [f"{rep['month']} 지표 적중률 · 가중치 갱신", ""]
    acc = rep["accuracy"]
    L.append("■ 카테고리별 적중률 (일봉 판단 → 5거래일 뒤 방향, 최근 60거래일)")
    if acc.empty:
        L.append("· 아직 결과가 나온 판단이 없습니다")
    for cat, r in acc.sort_values("적중률", ascending=False).iterrows():
        L.append(f"· {cat} {r['적중률'] * 100:.0f}% (표본 {int(r['표본'])})")
    L.append("")
    L.append(f"■ 적용 가중치 (표본 {MIN_SAMPLES}개 이상만 조정, 0.5~1.5배)")
    for cat, w in rep["weights"].items():
        L.append(f"· {cat} ×{w}")
    if not rep["weights"]:
        L.append("· 표본이 부족해 모두 1.0 유지")
    return "\n".join(L)
