# -*- coding: utf-8 -*-
"""경제지표 일정 — 인베스팅닷컴 경제 캘린더의 미국 · 한국 '중요도 별 3개'.

요청 형식은 investpy(인베스팅닷컴 캘린더 파이썬 래퍼)의 구현을 따릅니다:
  POST /economic-calendar/Service/getCalendarFilteredData
  country[] 5=미국 · 11=한국, importance[] 3=높음(별 3개), timeZone 88=GMT+9(서울)
응답 JSON의 "data"(표 HTML)에서 행을 뽑습니다. 막히면(Cloudflare 등) 빈 목록을
돌려주고, 호출하는 쪽이 config.ECON_CALENDAR(수동 목록)로 대신합니다.
"""
import datetime as dt
import html
import re

URLS = [
    "https://kr.investing.com/economic-calendar/Service/getCalendarFilteredData",
    "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
]
COUNTRIES = {"5": "🇺🇸", "11": "🇰🇷"}
FLAG_BY_CUR = {"USD": "🇺🇸", "KRW": "🇰🇷"}

_TR = re.compile(r"(<tr[^>]*>)(.*?)</tr>", re.S)
_DAY = re.compile(r'id="theDay(\d+)"')
_DT = re.compile(r'data-event-datetime="(\d{4}/\d{2}/\d{2} \d{2}:\d{2})')
_TIME = re.compile(r'<td[^>]*class="first left[^"]*"[^>]*>\s*(\d{1,2}:\d{2})')
_CUR = re.compile(r'flagCur[^>]*>.*?</span>\s*([A-Z]{3})', re.S)
_EVENT = re.compile(r'<td[^>]*class="left event"[^>]*>(.*?)</td>', re.S)


def fetch_events(start: dt.date, end: dt.date) -> list[tuple]:
    """[(datetime KST, 국기, 지표명)] — 실패하면 []."""
    import requests

    data = {
        "country[]": list(COUNTRIES),
        "importance[]": ["3"],
        "dateFrom": start.isoformat(), "dateTo": end.isoformat(),
        "timeZone": "88", "timeFilter": "timeOnly",
        "currentTab": "custom", "submitFilters": "1", "limit_from": "0",
    }
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    for url in URLS:
        try:
            r = requests.post(url, data=data, timeout=20,
                              headers={**headers, "Referer": url.split("/Service")[0] + "/"})
            if r.status_code != 200:
                print(f"  (경제 캘린더 {r.status_code}: {url.split('/')[2]})")
                continue
            events = _parse(r.json().get("data", ""))
            print(f"  [calendar] 인베스팅닷컴 별 3개 {len(events)}건 ({url.split('/')[2]})")
            return events
        except Exception as e:
            print(f"  (경제 캘린더 실패 {url.split('/')[2]}: {type(e).__name__}: {e})")
    return []


def _parse(table_html: str) -> list[tuple]:
    """표 HTML → [(datetime KST 또는 None, 국기, 지표명)].

    날짜는 행의 data-event-datetime, 없으면 앞선 날짜 구분 행(theDay<타임스탬프>)과
    시간 칸으로 만듭니다.
    """
    out, day = [], None
    for tag, body in _TR.findall(table_html):
        m_day = _DAY.search(tag + body)
        if m_day and "eventRowId_" not in tag:
            day = dt.datetime.fromtimestamp(int(m_day.group(1)),
                                            dt.timezone.utc).date()
            continue
        if "eventRowId_" not in tag:
            continue
        m_ev = _EVENT.search(body)
        if not m_ev:
            continue
        name = " ".join(html.unescape(re.sub(r"<[^>]+>", "", m_ev.group(1))).split())
        m_cur = _CUR.search(body)
        flag = FLAG_BY_CUR.get(m_cur.group(1) if m_cur else "", "")
        when = None
        m_dt = _DT.search(tag)
        if m_dt:
            when = dt.datetime.strptime(m_dt.group(1), "%Y/%m/%d %H:%M")
        elif day is not None:
            m_t = _TIME.search(body)
            when = dt.datetime.combine(day, dt.time()) if not m_t else \
                dt.datetime.strptime(f"{day} {m_t.group(1)}", "%Y-%m-%d %H:%M")
        out.append((when, flag, name))
    return out
