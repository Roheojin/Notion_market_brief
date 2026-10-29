# 노션 마켓 브리핑

코스피 · 코스닥 · 니케이225 · 항셍 · 상해종합 · 나스닥100 · S&P500 · 다우 · 필라델피아 반도체 · VIX · 비트코인의 일봉·주봉 차트를 **한국장 · 미국장 마감 종가 기준으로 각각** 분석해 노션 데이터베이스에 게시합니다. GitHub Actions가 실행합니다.

| 시장 | 실행 (KST) | 내용 |
|---|---|---|
| 한국장 | 평일 20:40 (15:30 종가 · 애프터마켓 이후 확정 수급) | 코스피 · 코스닥 · 니케이225 · 항셍 · 상해종합 + 코스피·코스닥 수급 2년 + 시장 폭(상승·하락 종목 수, ADR) + 환율·금리(원/달러 · 달러인덱스 · 미10년물 · 원/엔 · 국고채 3년) |
| 미국장 | 화~토 06:20 (미국장 마감 직후) | 나스닥100 · S&P500 · 다우 · 필라델피아 반도체 · VIX · 비트코인(이 시점 가격) + 금리·원자재(미10년물 · 미30년물 · WTI · 금 · 구리) |

두 페이지 모두 위에 앞으로 7일 경제지표 일정(인베스팅닷컴 미국·한국 **중요도 별 3개**, 한국 시간)을 보여 줍니다. 인베스팅닷컴에서 받지 못한 날은 `config.py`의 `ECON_CALENDAR` 수동 목록을 씁니다.

## 시작하기

1. Settings → Secrets and variables → Actions에 등록

   | 이름 | 내용 |
   |---|---|
   | `NOTION_TOKEN` | 노션 토큰 (필수) |
   | `NOTION_PARENT_PAGE_ID` | DB를 만들 노션 페이지 링크 또는 ID (필수) |
   | `KRX_ID`, `KRX_PW` | [KRX 정보데이터시스템](https://data.krx.co.kr) 계정 — 코스피 수급 (필수) |
   | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | 실패 알림 (선택) |

2. Actions 탭 → notion-market-brief → **Run workflow**로 바로 시험 (시장 kr/us/both 선택, 주말·휴장일엔 force 체크)

노션 토큰은 https://app.notion.com/developers/connections 에서 내부 연결을 만들어 발급하고, DB를 둘 페이지의 ••• → Connections에서 그 연결을 추가합니다.

## 노션에 올라가는 것

- 시장별 DB 「차트 분석 아카이브 (한국장)」 · 「… (미국장)」 — 지정한 페이지 아래에 첫 실행 때 자동 생성
- 하루 1페이지: `YYYY.MM.DD (요일) 한국장 차트 분석` / `… 미국장 차트 분석`, 날짜 = 그 시장의 거래일
- 본문: 지수별 차트 + 지표 한 줄 요약 (한국장 14장 · 미국장 13장), 종가·등락률은 상승 초록 / 하락 빨강
- 속성: 지수별 일봉/주봉 판단 · 종가 · 등락% · 다이버전스 · 피드백(월간 점검용 빈칸), 한국장은 원/달러 · 외국인 20일 순매수 · 환율-수급 추가
- 같은 날짜로 재실행하면 새 페이지로 교체 (중복 없음)
- 휴장일(최신 데이터 없음)은 건너뜀. 게시 실패 시 실행이 실패로 끝나 GitHub가 메일로 알림

## 차트

증권사 앱 형식 1장: 가격(캔들 · 이평 5/20/60/120 · 일목균형표 · 볼린저 상·하한) / 거래량 / MACD / RSI. 오른쪽 축에 현재값 태그, MACD·RSI가 시그널선을 위로 뚫으면 ▲, 아래로 뚫으면 ▼.

## 판단 로직

지표별 신호(방향 ±1 × 강도 1~2)를 합산해 **강세 / 다소 강세 / 중립 / 다소 약세 / 약세**로 판단합니다. 일봉은 단기(크로스 · RSI · 볼린저 · 거래량 · MACD), 주봉은 추세(배열 · 일목 구름대 · 후행스팬) 위주입니다. 기간·임계값은 `marketbrief/config.py`의 `PARAMS`.

`history/`(Actions가 매일 커밋):
- `chart_log.csv` — 지표 카테고리별 점수
- **적중률 자동 계산** (`marketbrief/feedback.py`): 5거래일이 지난 페이지의 노션 `피드백`(적중/빗나감) · `피드백 메모`(지수별 판단→수익률)를 자동으로 채우고, 매달 첫 실행에 최근 60거래일 카테고리별 적중률로 `indicator_weights.json`(0.5~1.5배)을 갱신 + 노션에 「YYYY-MM 적중률 리포트」 게시
- `breadth_KOSPI.csv` · `breadth_KOSDAQ.csv`, `flows_KOSPI.csv` · `flows_KOSDAQ.csv` — 시장 폭 · 수급 캐시
- `fx_log.csv` — 환율·매크로 상태
- `indicator_weights.json` — 있으면 카테고리 가중치로 반영 (예: `{"이평선": 1.2, "RSI": 0.8}`)

## 로컬 실행

```bash
pip install -r requirements.txt
python main.py --session chart --market kr --sample --force   # 합성 데이터로 차트만 생성 (output/)
python main.py --session chart --market us --post             # 실데이터 + 노션 게시 (.env 필요)
```

`.env.example`을 `.env`로 복사해 값을 채웁니다. 리눅스에서 한글이 깨지면 `sudo apt-get install fonts-noto-cjk`.

## 구조

```
main.py                     실행 진입점
marketbrief/
  config.py                 지수 · 지표 파라미터 · 테마
  fetch.py                  yfinance 시세 (+ --sample 합성 데이터)
  flowcache.py              코스피 수급 캐시 (pykrx/KRX)
  indicators.py, signals.py 지표 계산 · 신호 · 종합 판단
  chartpack.py              차트 분석 세션 (차트 · 해설 · summary.json)
  breadth.py                시장 폭 (상승·하락 종목 수 · ADR)
  feedback.py               적중률 · 노션 피드백 · 가중치 자동 갱신
  chartstyle.py             폰트 · 색
  notion.py                 노션 게시
  notify.py                 텔레그램 알림
.github/workflows/daily-brief.yml
```

## 주의

- yfinance는 비공식 래퍼라 간헐적 지연·오류가 있을 수 있습니다.
- 투자 권유가 아닌 기술적 지표 참고 자료입니다.
