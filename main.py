#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시황 브리핑 파이프라인.

세션:
  us      아침 07:30 — 미국장 마감 브리핑 (+미국 매크로, 이슈)
  kr      오후 16:00 — 국내장 마감 브리핑 (+수급, 국내 매크로, 이슈)
  weekly  일요일     — 주간 리뷰 (+다음주 경제·실적 일정)
  stats   매월 1일   — 신호 적중률 리포트 (최근 90거래일 백테스트)

사용법:
  python main.py --session kr            # 카드 생성만
  python main.py --session kr --post     # + 인스타그램 캐러셀 게시
  python main.py --session kr --sample   # 합성 데이터 테스트 (네트워크 불필요)
"""
import argparse
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# .env 파일 자동 로드 (로컬 실행용 — 없으면 조용히 넘어감)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

from marketbrief.config import INDICES, WATCHLIST, SESSIONS, MACRO_BY_SESSION, PARAMS
from marketbrief.fetch import (
    fetch_daily, sample_daily, fetch_flows, sample_flows, FLOW_LONG_DAYS,
)
from marketbrief.indicators import add_indicators, to_weekly, to_monthly
from marketbrief.signals import analyze, analyze_monthly
from marketbrief.notify import send_telegram

# 미국장/국내장/주간/적중률 세션 전용 모듈 — 차트 분석 전용 폴더(노션 마켓 브리핑)에는
# 없으므로, 없으면 chart 세션만 실행할 수 있게 둡니다
try:
    from marketbrief.macro import fetch_macro, sample_macro
    from marketbrief.news import fetch_news, sample_news
    from marketbrief.resolve import get_watchlist
    from marketbrief.cards import (
        make_cover_card, make_symbol_card, make_flows_card, make_macro_card,
        make_news_card, make_weekly_cover, make_schedule_card, make_stats_card,
        make_caption, stamp_pages,
    )
    _BRIEF_ERR = None
except ImportError as _e:
    _BRIEF_ERR = _e

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
KST = ZoneInfo("Asia/Seoul")
WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def run(session: str = "kr", sample: bool = False, post: bool = False,
        force: bool = False) -> list[str]:
    os.makedirs(OUT, exist_ok=True)
    now = dt.datetime.now(KST)
    date_str = f"{now:%Y.%m.%d} ({WEEKDAY_KO[now.weekday()]})"
    tag = f"{now:%Y%m%d}_{session}"
    title = SESSIONS[session]["title"]
    market = SESSIONS[session]["market"]

    get_daily = sample_daily if sample else fetch_daily
    get_flows = sample_flows if sample else fetch_flows

    all_watch = WATCHLIST + get_watchlist()  # watchlist.txt에서 자동 해석
    indices = [m for m in INDICES if m["market"] == market]
    watch = [m for m in all_watch if m["market"] == market]

    # ── 휴장일 체크: 대표 지수의 최신 데이터가 신선하지 않으면 스킵 ──
    if not sample and not force:
        try:
            ref = get_daily(indices[0]["ticker"])
            last_date = ref.index[-1].date()
            today_kst = now.date()
            fresh = (last_date == today_kst) if market == "KR" \
                else (last_date >= today_kst - dt.timedelta(days=1))
            if not fresh:
                msg = (f"[{title}] 최신 일봉이 아직 없어 스킵합니다 "
                       f"(최신: {last_date}, 오늘: {today_kst}) — "
                       f"휴장일이거나 장 마감 전 실행입니다. "
                       f"정시(크론) 실행은 정상 통과하며, 테스트는 --force를 쓰세요")
                print(msg)
                from marketbrief.notify import send_telegram
                send_telegram(f"⏸ {msg}")
                return []
        except Exception as e:
            print(f"(휴장일 체크 실패, 계속 진행: {e})")

    rows_idx, rows_watch, cards = [], [], []
    index_flows, stock_flows = [], []

    for group, universe, rows in (("idx", indices, rows_idx),
                                  ("watch", watch, rows_watch)):
        for meta in universe:
            print(f"[{group}] {meta['name']} ({meta['ticker']}) 분석 중...")
            try:
                df = add_indicators(get_daily(meta["ticker"]))
            except Exception as e:
                print(f"  !! 시세 수집 실패, 건너뜀: {e}")
                continue

            flows = None
            if market == "KR" and meta.get("krx"):
                flows = get_flows(meta["krx"])
                if flows is not None:
                    (index_flows if group == "idx" else stock_flows).append(
                        (meta["name"], flows))

            dfw = to_weekly(df)  # 주봉 (중장기 뷰)
            an = analyze(df, flows, dfw)
            # 전일 판단 재계산 → 판단 전환 감지 + 근거(신규/소멸 신호)
            try:
                prev = analyze(df.iloc[:-1],
                               flows.iloc[:-1] if flows is not None else None,
                               to_weekly(df.iloc[:-1]))
                an.prev_verdict = prev.verdict
                today_titles = {s.title for s in an.signals}
                prev_titles = {s.title for s in prev.signals}
                added = [s.title for s in an.signals
                         if s.title not in prev_titles]
                removed = [t for t in prev_titles if t not in today_titles]
                an.change_reasons = (added[:2]
                                     + [f"{t} 해소" for t in removed[:max(0, 2 - len(added))]])
            except Exception:
                pass
            rows.append((meta, an))
            safe = meta["ticker"].replace("^", "").replace(".", "_")
            path = os.path.join(OUT, f"{tag}_{len(cards)+1:02d}_{safe}.png")
            make_symbol_card(df, meta, an, date_str, path)
            cards.append(path)
            print(f"  -> {an.verdict} (score {an.score:+.0f}), 신호 {len(an.signals)}개")

    if not rows_idx and not rows_watch:
        raise SystemExit("분석에 성공한 종목이 없습니다.")

    # 매크로 지표 + 이슈 뉴스 + 시장 맵
    print("[macro] 매크로 지표 수집 중...")
    macro = (sample_macro if sample else fetch_macro)(MACRO_BY_SESSION[session])
    print("[news] 이슈 뉴스 수집 중...")
    try:
        news = (sample_news if sample else fetch_news)(session)
    except Exception as e:
        print(f"  (뉴스 수집 실패, 카드 생략: {e})")
        news = []
    print("[econ] 경제지표 수집 중...")
    from marketbrief.econdata import fetch_us_econ, fetch_kr_econ, sample_econ
    try:
        if sample:
            econ_tiles = sample_econ(session)
        else:
            econ_tiles = fetch_us_econ() if market == "US" else fetch_kr_econ()
    except Exception as e:
        print(f"  (경제지표 실패, 카드 생략: {e})")
        econ_tiles = []
    print("[map] 시장 맵 데이터 수집 중...")
    from marketbrief.sectors import (
        US_UNIVERSE, KR_UNIVERSE, fetch_map_changes, sample_map_changes,
    )
    map_universe = US_UNIVERSE if market == "US" else KR_UNIVERSE
    try:
        map_items = (sample_map_changes if sample
                     else fetch_map_changes)(map_universe)
    except Exception as e:
        print(f"  (시장 맵 실패, 카드 생략: {e})")
        map_items = []

    # 오늘의 한 줄 (규칙 기반 헤드라인)
    from marketbrief.headline import build_headline
    headline = build_headline(rows_idx, rows_watch, index_flows or None, macro)
    print(f'오늘의 한 줄: "{headline}"')

    # 표지
    cover = os.path.join(OUT, f"{tag}_00_cover.png")
    # 행이 적은 세션(국내장)은 표지에 매크로 핵심 3개도 요약
    macro_summary = macro[:3] if len(rows_idx) + len(rows_watch) <= 4 else None
    make_cover_card(rows_idx, rows_watch, date_str, cover, title=title,
                    index_flows=index_flows or None, headline=headline,
                    macro_summary=macro_summary)
    all_cards = [cover]

    # 카드 순서: 표지 → 경제지표(발표일만) → 매크로 → 시장 맵 → 수급
    #   → 지수/종목 차트 → 이슈
    if econ_tiles:
        from marketbrief.cards import make_econ_card
        ep = os.path.join(OUT, f"{tag}_00a_econ.png")
        make_econ_card(econ_tiles, date_str, ep, session=session)
        all_cards.append(ep)
    if macro:
        mpath = os.path.join(OUT, f"{tag}_00b_macro.png")
        make_macro_card(macro, date_str, mpath, session=session)
        all_cards.append(mpath)
    if map_items:
        from marketbrief.cards import make_market_map_card
        map_title = "미국 시장 맵" if market == "US" else "국내 시장 맵"
        mp = os.path.join(OUT, f"{tag}_00c_map.png")
        make_market_map_card(map_items, date_str, mp, title=map_title)
        all_cards.append(mp)
    if index_flows:
        fpath = os.path.join(OUT, f"{tag}_00d_flows.png")
        make_flows_card(index_flows, stock_flows, date_str, fpath)
        all_cards.append(fpath)
    all_cards += cards
    if news:
        npath = os.path.join(OUT, f"{tag}_98_news.png")
        make_news_card(news, date_str, npath)
        all_cards.append(npath)

    from marketbrief.cards import make_story_card
    stamp_pages(all_cards)  # 하단 페이지 번호 (1/N) + 워터마크

    # 스토리용 세로 카드 (피드 유도)
    story = os.path.join(OUT, f"{tag}_story.png")
    make_story_card(rows_idx, date_str, title, story, headline=headline,
                    index_flows=index_flows or None,
                    macro=macro[:3] if macro else None)

    caption = make_caption(rows_idx, rows_watch, date_str, session=session,
                           index_flows=index_flows or None, news=news,
                           headline=headline)
    with open(os.path.join(OUT, f"{tag}_caption.txt"), "w", encoding="utf-8") as f:
        f.write(caption)

    # 판단 아카이브 (history/verdicts.csv)
    from marketbrief.history import append_history
    append_history(session, rows_idx + rows_watch, now)

    print(f"\n[{title}] 카드 {len(all_cards)}장 생성 완료 -> {OUT}")

    if post:
        from marketbrief.instagram import post_carousel, post_story
        media_id = post_carousel(all_cards[:10], caption)  # 캐러셀 최대 10장
        print(f"인스타그램 게시 완료: media_id={media_id}")
        if os.environ.get("IG_POST_STORY") == "1":
            sid = post_story(story)
            print(f"스토리 게시 완료: media_id={sid}")

    return all_cards


def run_weekly(sample: bool = False, post: bool = False) -> list[str]:
    """일요일 주간 리뷰: 한 주 등락 + 주간 수급 + 다음주 일정."""
    from marketbrief.weekly import (
        weekly_change, weekly_flow_sum, next_week_range,
        econ_events_next_week, earnings_next_week, sample_schedule,
    )

    os.makedirs(OUT, exist_ok=True)
    now = dt.datetime.now(KST)
    tag = f"{now:%Y%m%d}_weekly"
    week_ago = now - dt.timedelta(days=6)
    range_str = f"{week_ago:%Y.%m.%d} ~ {now:%m.%d}"

    get_daily = sample_daily if sample else fetch_daily
    get_flows = sample_flows if sample else fetch_flows

    rows, flow_sums, flows_long, weekly_charts = [], [], [], []
    universe = INDICES + WATCHLIST + get_watchlist()
    for meta in universe:
        print(f"[weekly] {meta['name']} 집계 중...")
        try:
            df = get_daily(meta["ticker"])
        except Exception as e:
            print(f"  !! 실패, 건너뜀: {e}")
            continue
        # 주봉 차트용 (지수만 — 중장기 추세)
        if meta in INDICES:
            try:
                weekly_charts.append((meta, to_weekly(df)))
            except Exception as e:
                print(f"  (주봉 변환 실패: {e})")
        # 월봉 국면 체크 (지수만 — 10년치로 20개월선까지 판단)
        monthly_txt = None
        if meta in INDICES:
            try:
                dfm = to_monthly(get_daily(meta["ticker"],
                                           PARAMS["monthly_days"]))
                mv, mwhy = analyze_monthly(dfm)
                monthly_txt = mv
                print(f"  월봉: {mv} ({mwhy})")
            except Exception as e:
                print(f"  (월봉 체크 실패: {e})")
        rows.append((meta, weekly_change(df), float(df["close"].iloc[-1]),
                     monthly_txt))
        if meta.get("krx") and meta["market"] == "KR" and meta in INDICES:
            # 수급: 최초 1회만 2년치 백필, 이후 매주 최근분만 증분 요청 (history/에 캐시)
            if sample:
                fl = get_flows(meta["krx"], FLOW_LONG_DAYS)
            else:
                from marketbrief.flowcache import load_flows_long
                fl = load_flows_long(meta["krx"], FLOW_LONG_DAYS)
            fs = weekly_flow_sum(fl.tail(15) if fl is not None else None)
            if fs is not None:
                flow_sums.append((meta["name"], fs))
            if fl is not None and len(fl) > 60:
                flows_long.append((meta["name"], fl))

    if sample:
        econ, earn = sample_schedule()
    else:
        econ, earn = econ_events_next_week(), earnings_next_week()

    lo, hi = next_week_range()
    cover = os.path.join(OUT, f"{tag}_00_cover.png")
    make_weekly_cover(rows, flow_sums, range_str, cover)
    all_cards = [cover]
    if weekly_charts:
        from marketbrief.cards import make_weekly_chart_card
        wpath = os.path.join(OUT, f"{tag}_01_weekly_chart.png")
        if make_weekly_chart_card(weekly_charts, range_str, wpath):
            all_cards.append(wpath)
    if flows_long:
        from marketbrief.cards import make_flows_trend_card
        tpath = os.path.join(OUT, f"{tag}_01b_flows_trend.png")
        make_flows_trend_card(flows_long, range_str, tpath)
        all_cards.append(tpath)
    # 경제 일정(날짜별) → 해외 실적(섹터별) → 국내 실적(섹터별)
    # 캐러셀 10장 한도 안에서 분배
    from marketbrief.cards import (
        EARN_FOOT_KR, EARN_FOOT_US, make_earnings_cards, make_schedule_cards,
    )
    range_next = f"{lo:%Y.%m.%d} ~ {hi:%m.%d}"
    room = max(1, 10 - len(all_cards))
    all_cards += make_schedule_cards(
        econ, [], range_next,
        os.path.join(OUT, f"{tag}_02_schedule"), max_pages=min(2, room))

    # 국내 실적은 기본적으로 수집하지 않습니다(earnings.COLLECT_KR 참고).
    # watchlist.txt에 국내 종목이 있으면 그것만 국내 카드로 나옵니다.
    earn_us = [e for e in earn if len(e) < 4 or e[3] != "KR"]
    earn_kr = [e for e in earn if len(e) > 3 and e[3] == "KR"]
    kr_pages = 1 if earn_kr else 0    # 국내는 한 장이면 충분 — 자리를 먼저 확보
    room = max(1, 10 - len(all_cards) - kr_pages)
    if earn_us:
        all_cards += make_earnings_cards(
            earn_us, range_next, os.path.join(OUT, f"{tag}_03_earnings_us"),
            max_pages=room, title="다음주 해외 실적",
            footnote=EARN_FOOT_US)
    if earn_kr:
        all_cards += make_earnings_cards(
            earn_kr, range_next, os.path.join(OUT, f"{tag}_04_earnings_kr"),
            max_pages=max(1, 10 - len(all_cards)), title="다음주 국내 실적",
            footnote=EARN_FOOT_KR)
    stamp_pages(all_cards)

    lines = [f"📅 주간 시황 리뷰 ({range_str})", ""]
    for row in rows:
        meta, chg, monthly = row[0], row[1], row[3] if len(row) > 3 else None
        arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "—")
        line = f"{meta['name']} {arrow}{chg:+.2f}%"
        if monthly:
            line += f" · 월봉 {monthly}"
        lines.append(line)
    if econ:
        lines += ["", "다음주 경제 일정 (한국시간)"]
        for e in sorted(econ, key=lambda x: (x[0], x[3] if len(x) > 3 and x[3]
                                             else "99:99"))[:12]:
            imp = e[2] if len(e) > 2 and isinstance(e[2], int) else 0
            hhmm = f" {e[3]}" if len(e) > 3 and e[3] else ""
            lines.append(f"· {e[0]:%m/%d}{hhmm} {e[1]}"
                         f"{' ' + '★' * imp if imp else ''}")
    for label, group in (("다음주 해외 실적", earn_us),
                         ("다음주 국내 실적", earn_kr)):
        if not group:
            continue
        lines += ["", label]
        by_sec: dict = {}
        for e in group:                     # 이미 시총 큰 순
            when = f" {e[4]}" if len(e) > 4 and e[4] else ""
            by_sec.setdefault(e[2] if len(e) > 2 and e[2] else "기타",
                              []).append(f"{e[1]}({e[0]:%m/%d}{when})")
        shown = 0
        for sec, names in by_sec.items():
            lines.append(f"· {sec}: " + ", ".join(names[:4])
                         + (f" 외 {len(names) - 4}" if len(names) > 4 else ""))
            shown += min(len(names), 4)
        if shown < len(group):
            lines.append(f"· 전체 {len(group)}건은 카드 참고")
        # 시총 상위 몇 개는 컨센서스까지 (group은 이미 시총 큰 순)
        head = [e for e in group if len(e) > 5 and e[5]][:3]
        if head:
            lines.append("")
            for e in head:
                lines.append(f"· {e[1]} — {e[5]}")
    from marketbrief.config import HASHTAGS_BY_SESSION
    from marketbrief.cards import C  # noqa: F401
    lines += ["", "#주간시황 " + HASHTAGS_BY_SESSION["kr"]]
    caption = "\n".join(lines)
    with open(os.path.join(OUT, f"{tag}_caption.txt"), "w", encoding="utf-8") as f:
        f.write(caption)

    print(f"\n[주간 리뷰] 카드 {len(all_cards)}장 생성 완료 -> {OUT}")
    if post:
        from marketbrief.instagram import post_carousel
        media_id = post_carousel(all_cards[:10], caption)  # 캐러셀 최대 10장
        print(f"인스타그램 게시 완료: media_id={media_id}")
    return all_cards


def run_stats(sample: bool = False, post: bool = False) -> list[str]:
    """월간 신호 적중률 리포트."""
    from marketbrief.stats import backtest_signals, LOOKBACK, HORIZON

    os.makedirs(OUT, exist_ok=True)
    now = dt.datetime.now(KST)
    tag = f"{now:%Y%m%d}_stats"
    get_daily = sample_daily if sample else fetch_daily

    dfs = {}
    for meta in INDICES + WATCHLIST + get_watchlist():
        print(f"[stats] {meta['name']} 데이터 준비 중...")
        try:
            dfs[meta["name"]] = add_indicators(get_daily(meta["ticker"]))
        except Exception as e:
            print(f"  !! 실패, 건너뜀: {e}")

    print(f"[stats] 백테스트 실행 (최근 {LOOKBACK}거래일, {HORIZON}일 성과)...")
    stats = backtest_signals(dfs)
    if stats.empty:
        raise SystemExit("집계된 신호가 없습니다.")

    period_str = f"최근 {LOOKBACK}거래일 · 지수/관심종목 {len(dfs)}개 종합"
    path = os.path.join(OUT, f"{tag}_00_report.png")
    make_stats_card(stats, period_str, path)
    all_cards = [path]
    stamp_pages(all_cards)

    top = stats.head(3)
    lines = [f"📈 월간 신호 적중률 리포트 ({now:%Y.%m})", "",
             f"최근 {LOOKBACK}거래일 동안 발생한 기술적 신호의",
             f"{HORIZON}거래일 후 방향 적중률입니다.", ""]
    for _, r in top.iterrows():
        lines.append(f"· {r['signal']}: {r['hit_rate']:.0f}% "
                     f"({int(r['count'])}회, 평균 {r['avg_ret']:+.2f}%)")
    lines += ["", "과거 성과가 미래를 보장하지 않습니다.", "",
              "#신호적중률 #백테스트 #기술적분석 #주식공부"]
    caption = "\n".join(lines)
    with open(os.path.join(OUT, f"{tag}_caption.txt"), "w", encoding="utf-8") as f:
        f.write(caption)

    print(f"\n[적중률 리포트] 카드 생성 완료 -> {OUT}")
    if post:
        from marketbrief.instagram import post_carousel
        media_id = post_carousel(all_cards, caption)
        print(f"인스타그램 게시 완료: media_id={media_id}")
    return all_cards


ALL_SESSIONS = list(SESSIONS) + ["weekly", "stats", "chart"]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", choices=ALL_SESSIONS, default=None,
                    help="us/kr/weekly/stats. 생략 시 KST 시각·요일로 자동")
    ap.add_argument("--sample", action="store_true", help="합성 데이터로 테스트")
    ap.add_argument("--post", action="store_true", help="인스타그램 자동 게시")
    ap.add_argument("--force", action="store_true", help="휴장일 체크 무시하고 실행")
    args = ap.parse_args()

    session = args.session
    if session is None:
        now = dt.datetime.now(KST)
        session = "weekly" if now.weekday() == 6 \
            else ("us" if now.hour < 12 else "kr")
        print(f"세션 자동 선택: {session}")

    if session != "chart" and _BRIEF_ERR is not None:
        raise SystemExit(f"'{session}' 세션에 필요한 모듈이 이 폴더에 없습니다 "
                         f"({_BRIEF_ERR}) — 이 폴더에서는 --session chart 만 "
                         f"실행할 수 있어요")

    # 카드 테마: CARD_THEME 환경변수 > config의 세션별 지정
    try:
        from marketbrief.cards import set_theme
    except ImportError:          # 차트 분석 전용 폴더 — cards.py 대신 chartstyle.py
        from marketbrief.chartstyle import set_theme
    from marketbrief.config import CARD_THEME_BY_SESSION
    set_theme(os.environ.get("CARD_THEME")
              or CARD_THEME_BY_SESSION.get(session, "light"))

    label = {"us": "미국장", "kr": "국내장", "weekly": "주간 리뷰",
             "stats": "적중률 리포트", "chart": "차트 분석"}[session]
    try:
        if session == "weekly":
            cards_out = run_weekly(sample=args.sample, post=args.post)
        elif session == "stats":
            cards_out = run_stats(sample=args.sample, post=args.post)
        elif session == "chart":
            from marketbrief.chartpack import run_chart
            cards_out = run_chart(sample=args.sample, post=args.post,
                                  force=args.force)
        else:
            cards_out = run(session=session, sample=args.sample,
                            post=args.post, force=args.force)
        if cards_out:
            send_telegram(f"✅ [{label}] 브리핑 {'게시' if args.post else '생성'} 완료 "
                          f"(카드 {len(cards_out)}장)")
    except Exception as e:
        send_telegram(f"❌ [{label}] 브리핑 실패: {e}")
        raise
