# 노션 마켓 브리핑

코스피 · 나스닥100 · S&P500의 일봉·주봉 차트를 분석해 **노션 데이터베이스에 하루 1페이지**로 자동 게시합니다. GitHub Actions로 화~토 06:20 KST(미국장 마감 + 전일 코스피)에 실행됩니다.

## 시작하기

1. Settings → Secrets and variables → Actions에 등록

   | 이름 | 내용 |
   |---|---|
   | `NOTION_TOKEN` | 노션 토큰 (필수) |
   | `NOTION_PARENT_PAGE_ID` | DB를 만들 노션 페이지 링크 또는 ID (필수) |
   | `KRX_ID`, `KRX_PW` | [KRX 정보데이터시스템](https://data.krx.co.kr) 계정 — 코스피 수급 (필수) |
   | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | 실패 알림 (선택) |

2. Actions 탭 → notion-market-brief → **Run workflow**로 바로 시험 (주말·휴장일엔 force 체크)

노션 토큰은 https://app.notion.com/developers/connections 에서 내부 연결을 만들어 발급하고, DB를 둘 페이지의 ••• → Connections에서 그 연결을 추가합니다.

## 노션에 올라가는 것

- DB 「차트 분석 아카이브」 — 지정한 페이지 아래에 첫 실행 때 자동 생성
- 페이지 제목 `YYYY.MM.DD (요일) 차트 분석`, 날짜 = 실행일(KST)
- 본문: 지표별 해설 + 차트 8장 (코스피 수급 2년 · 환율/매크로 · 지수별 일봉/주봉)
- 속성: 지수별 일봉/주봉 판단 · 종가 · 등락% · 다이버전스 · 원/달러 · 외국인 20일 순매수 · 환율-수급 · 피드백(월간 점검용 빈칸)
- 같은 날 재실행하면 새 페이지로 교체 (중복 없음)
- 휴장일(최신 데이터 없음)은 건너뜀. 게시 실패 시 실행이 실패로 끝나 GitHub가 메일로 알림

## 차트

증권사 앱 형식 1장: 가격(캔들 · 이평 5/20/60/120 · 일목균형표 · 볼린저 상·하한) / 거래량 / MACD / RSI. 오른쪽 축에 현재값 태그, MACD·RSI가 시그널선을 위로 뚫으면 ▲, 아래로 뚫으면 ▼.

## 판단 로직

지표별 신호(방향 ±1 × 강도 1~2)를 합산해 **강세 / 다소 강세 / 중립 / 다소 약세 / 약세**로 판단합니다. 일봉은 단기(크로스 · RSI · 볼린저 · 거래량 · MACD), 주봉은 추세(배열 · 일목 구름대 · 후행스팬) 위주입니다. 기간·임계값은 `marketbrief/config.py`의 `PARAMS`.

`history/`(Actions가 매일 커밋):
- `chart_log.csv` — 지표 카테고리별 점수 (월간 적중률 점검용)
- `fx_log.csv` — 환율·매크로 상태
- `indicator_weights.json` — 있으면 카테고리 가중치로 반영 (예: `{"이평선": 1.2, "RSI": 0.8}`)

## 로컬 실행

```bash
pip install -r requirements.txt
python main.py --session chart --sample --force   # 합성 데이터로 차트만 생성 (output/)
python main.py --session chart --post             # 실데이터 + 노션 게시 (.env 필요)
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
  chartstyle.py             폰트 · 색
  notion.py                 노션 게시
  notify.py                 텔레그램 알림
.github/workflows/daily-brief.yml
```

## 주의

- yfinance는 비공식 래퍼라 간헐적 지연·오류가 있을 수 있습니다.
- 투자 권유가 아닌 기술적 지표 참고 자료입니다.
