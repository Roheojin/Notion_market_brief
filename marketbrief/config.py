# -*- coding: utf-8 -*-
"""분석 대상 설정. 종목 추가/삭제는 여기만 수정하면 됩니다."""

# 지수 (yfinance 티커)
# krx: pykrx 수급 조회용 코드 (국내만)
INDICES = [
    {"ticker": "^KS11",  "name": "코스피",   "market": "KR", "currency": "pt", "krx": "KOSPI"},
    {"ticker": "^KQ11",  "name": "코스닥",   "market": "KR", "currency": "pt", "krx": "KOSDAQ"},
    {"ticker": "^DJI",   "name": "다우존스", "market": "US", "currency": "pt"},
    {"ticker": "^GSPC",  "name": "S&P 500",  "market": "US", "currency": "pt"},
    {"ticker": "^IXIC",  "name": "나스닥",   "market": "US", "currency": "pt"},
    {"ticker": "^SOX",   "name": "필라델피아 반도체", "market": "US", "currency": "pt"},
]

# 관심 종목 — 기본값 없음. 프로젝트 루트의 watchlist.txt에 종목 이름을
# 한 줄씩 적으면 티커를 자동으로 찾아 분석합니다 (marketbrief/resolve.py).
WATCHLIST: list[dict] = []

# 카드 테마: 세션별 light/dark/tradingview/app 지정 (환경변수 CARD_THEME이 있으면 그게 우선)
CARD_THEME_BY_SESSION = {
    "us": "light", "kr": "light", "weekly": "light", "stats": "light",
    "chart": "app",
}

# 세션: 아침(07:30)엔 미국장, 저녁(16:00)엔 국내장 마감 브리핑
SESSIONS = {
    "us": {"title": "미국장 마감 브리핑", "market": "US"},
    "kr": {"title": "국내장 마감 브리핑", "market": "KR"},
}

# 세션별 매크로 지표
#   ticker: yfinance 티커, 또는 "stooq:심볼" (stooq.com CSV)
#   kind: price(등락률 %) / yield(변동 %p) / fx(등락률 %)
MACRO_BY_SESSION = {
    "us": [
        {"ticker": "DX-Y.NYB", "name": "달러인덱스", "kind": "price", "fmt": "{:,.2f}"},
        {"ticker": "^TNX", "name": "미 10년물", "kind": "yield", "scale": 0.1, "fmt": "{:.2f}%"},
        {"ticker": "^VIX", "name": "VIX", "kind": "price", "fmt": "{:,.1f}"},
        {"ticker": "CL=F", "name": "WTI 유가", "kind": "price", "fmt": "${:,.1f}"},
    ],
    "kr": [
        {"ticker": "KRW=X", "name": "원/달러", "kind": "fx", "fmt": "{:,.1f}원"},
        {"ticker": "krxbond:국고채3년", "name": "국고채 3년", "kind": "yield", "fmt": "{:.2f}%"},
        {"ticker": "krxbond:국고채10년", "name": "국고채 10년", "kind": "yield", "fmt": "{:.2f}%"},
        {"ticker": "DX-Y.NYB", "name": "달러인덱스", "kind": "price", "fmt": "{:,.2f}"},
        {"ticker": "CL=F", "name": "WTI 유가", "kind": "price", "fmt": "${:,.1f}"},
        # 안전자산 선호도 프록시
        {"ticker": "GC=F", "name": "금", "kind": "price", "fmt": "${:,.0f}"},
    ],
}

# 주요 경제 일정 — 이제 marketbrief/econcal.py가 미국·한국 지표를 자동 수집합니다.
# 여기 적는 항목은 자동 수집분에 "덧붙는" 보조 목록입니다
# (자동 수집이 놓치는 일정이 있을 때만 추가하세요. 비워둬도 정상 동작).
# 형식: ("YYYY-MM-DD", "일정명", 중요도 1~3)  — 중요도는 인베스팅닷컴 기준처럼
# 3=시장 전체를 움직임(FOMC·CPI), 2=주요 지표, 1=참고. 생략하면 2로 간주.
ECON_CALENDAR = [
    # (날짜 KST, 이름, 중요도 1~3) — 한 달에 한 번 정도 채워 넣으면 됩니다
    ("2026-11-10", "미국 CPI (10월분) 21:30 발표", 3),
    ("2026-11-26", "한국은행 금통위 (예정)", 3),
    ("2026-12-10", "FOMC 결과 발표 (12/9 회의, KST 새벽)", 3),
    ("2026-12-10", "미국 CPI (11월분) 22:30 발표", 3),
]

# 이슈 뉴스: RSS 피드 + 키워드 선별
NEWS_FEEDS = [
    ("연합뉴스 경제", "https://www.yna.co.kr/rss/economy.xml"),
    ("연합뉴스 국제", "https://www.yna.co.kr/rss/international.xml"),
    ("매일경제 증권", "https://www.mk.co.kr/rss/50200011/"),
    ("한국경제", "https://www.hankyung.com/feed/finance"),
]

NEWS_KEYWORDS = {
    "us": ["뉴욕증시", "나스닥", "다우", "S&P", "연준", "Fed", "FOMC", "파월",
           "미국 금리", "국채 금리", "CPI", "고용", "인플레이션", "엔비디아",
           "테슬라", "애플", "AI", "반도체", "실적", "관세", "달러"],
    "kr": ["코스피", "코스닥", "외국인", "기관", "삼성전자", "SK하이닉스",
           "반도체", "환율", "원/달러", "원달러", "일본은행", "BOJ", "엔화",
           "수출", "무역", "공매도", "금리", "한국은행", "관세"],
}
NEWS_MAX_AGE_HOURS = 20   # 이 시간 이내 기사만
NEWS_TOP_N = 5

# 매크로 급변 경보 임계값 (헤드라인 ⚠ 표시)
# 위험 판단이 실제로 의미 있는 지표만: 변동성(VIX)과 금리
MACRO_ALERTS = {
    "VIX": ("price", 8.0),         # 등락률 % 이상
    "미 10년물": ("yield", 0.08),   # %p 이상
    "국고채 10년": ("yield", 0.08),
    "국고채 3년": ("yield", 0.08),
}


# 지표 파라미터
PARAMS = {
    "ma_windows": [5, 20, 60, 120],
    "rsi_period": 14,
    "rsi_signal": 9,       # RSI 시그널선 (RSI의 9기간 이동평균)
    "bb_period": 20,
    "bb_std": 2.0,
    "ichimoku": {"tenkan": 9, "kijun": 26, "senkou_b": 52, "shift": 26},
    "vol_ma": 20,
    "macd_fast": 12,       # MACD (차트 분석 세션에서 사용)
    "macd_slow": 26,
    "macd_signal": 9,
    "history_days": 900,   # 일봉 수 — 주봉 지표(120주선 등) 계산에 충분하도록
    "monthly_days": 2600,  # 월봉 국면 체크용 (약 10년, 주간 리뷰에서만)
    "chart_days": 75,      # 카드 차트에 표시할 일봉 수
}

# ──────────────────────────────────────────────────────────────
# 차트 분석 세션 (--session chart, 아침 06:20 KST)
#   미국장 마감 직후: 나스닥100·S&P500 + 전일 코스피
#   카드: 표지(큰 날짜+코스피 수급 2년) → 지수별 일봉·주봉 2장씩
# ──────────────────────────────────────────────────────────────
CHART_INDICES = [
    {"ticker": "^KS11", "name": "코스피",    "market": "KR", "currency": "pt",
     "krx": "KOSPI"},
    {"ticker": "^KQ11", "name": "코스닥",    "market": "KR", "currency": "pt",
     "krx": "KOSDAQ"},
    {"ticker": "^N225", "name": "니케이225", "market": "JP", "currency": "pt"},
    {"ticker": "^HSI",  "name": "항셍",      "market": "CN", "currency": "pt"},
    {"ticker": "000001.SS", "name": "상해종합", "market": "CN", "currency": "pt"},
    {"ticker": "^NDX",  "name": "나스닥100", "market": "US", "currency": "pt"},
    {"ticker": "^GSPC", "name": "S&P 500",   "market": "US", "currency": "pt"},
    {"ticker": "^DJI",  "name": "다우",      "market": "US", "currency": "pt"},
    {"ticker": "^SOX",  "name": "필라델피아 반도체", "market": "US", "currency": "pt"},
    {"ticker": "^VIX",  "name": "VIX",       "market": "US", "currency": "pt"},
    {"ticker": "BTC-USD", "name": "비트코인", "market": "CRYPTO", "currency": "$"},
]

CHART_PARAMS = {
    "daily_bars": 130,    # 일봉 카드 표시 봉 수 (약 6개월)
    "weekly_bars": 104,   # 주봉 카드 표시 봉 수 (약 2년)
    "forward": 26,        # 일목 선행 구름 여백 (봉) — 잘리지 않게 확보
    "fetch_days": 1700,   # 수집 일봉 수 — 주봉 120주선 워밍업+2년 표시 충분
}

HASHTAGS_BY_SESSION = {
    "kr": "#주식 #시황 #코스피 #코스닥 #국내주식 #수급 #외국인순매수 "
          "#기술적분석 #차트분석 #오늘의시황",
    "us": "#주식 #시황 #나스닥 #다우 #미국주식 #해외주식 "
          "#기술적분석 #차트분석 #오늘의시황",
}

DISCLAIMER = "본 게시물은 투자 권유가 아닌 기술적 지표 참고 자료입니다."
