# 인스타 시황 브리핑 자동화

> **이 저장소는 GitHub Actions 전용입니다.** Settings → Secrets and variables → Actions에 `NOTION_TOKEN`, `NOTION_PARENT_PAGE_ID`, `KRX_ID`, `KRX_PW`(선택: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)를 등록하면, 화~토 06:20 KST에 차트 분석을 만들어 노션에 올립니다. Actions 탭 → notion-market-brief → Run workflow로 바로 실행할 수 있고(주말엔 force 체크), 실패하면 GitHub가 메일로 알립니다. 아래 `.bat` 관련 설명은 PC에서 돌릴 때만 해당합니다.

하루 두 번 시황을 인스타그램 카드뉴스(캐러셀)로 자동 게시하는 파이프라인입니다.

> **노션 마켓 브리핑 폴더**는 **노션 전용**입니다 — 아침 차트 분석(`--session chart`)을 만들어 노션에만 올립니다 (인스타그램 게시는 쓰지 않음). 매일 자동 실행은 GitHub Actions 또는 이 PC의 작업 스케줄러로 합니다. 미국장 · 국내장 · 주간 · 적중률 세션은 원래 저장소(insta-market-brief)에만 있어요 — 아래 **이 폴더만으로 실행하기** 참고.

- **아침 06:20 KST (화~토)** — 차트 분석 세션: 코스피 · 나스닥100 · S&P500 각각 **일봉 카드 + 주봉 카드**(추세: 캔들+이평 5/20/60/120+일목균형표 / 모멘텀: 볼린저+거래량+RSI(시그널 9)+MACD) + 표지(큰 날짜 + 코스피 수급 2년 누적). 인스타용은 `output/insta_YYYYMMDD/`, **네이버 블로그용 팩**은 `output/blog_YYYYMMDD/`로 분리 — 블로그 팩에는 **환율·매크로 흐름**(원/달러·달러인덱스·미10년물 → 외국인 수급 연결 해설)이 추가로 들어갑니다
- **아침 07:30 KST (평일)** — 미국장 마감 브리핑: 다우 · S&P500 · 나스닥 · 필라델피아 반도체 + 주요 종목(엔비디아·테슬라) + **미국 매크로**(달러인덱스·미10년물·VIX·유가·비트코인)
- **오후 16:00 KST (평일)** — 국내장 마감 브리핑: 코스피 · 코스닥 지수 중심 + **투자자별 수급**(개인/외국인/기관) + **국내 매크로**(원/달러·국고채 3/10년·달러인덱스·유가·반도체지수)
- **일요일 09:00 KST** — 주간 시황 리뷰: 한 주 등락 + 주간 수급 누적 + **다음주 경제 일정·관심종목 실적 일정**
- **매월 1일 10:00 KST** — 신호 적중률 리포트: 최근 90거래일 신호 백테스트(5거래일 후 방향 적중률·평균 수익률)

두 세션 모두 마지막 장에 **주요 이슈 카드**(경제 뉴스 RSS에서 키워드 자동 선별 상위 5건)가 붙습니다.

### 시간축 구성 (일봉 / 주봉 / 월봉)

- **단기 뷰 = 일봉**: 모멘텀·과열 지표 — 이평선 크로스(5/20)·이격도, RSI, 볼린저밴드, 거래량, 일목 전환선/기준선 크로스, (국내) 수급
- **중장기 뷰 = 주봉**: 추세 지표 — 주봉 크로스(5/20주)·배열(5/20/60주), 일목 구름대·후행스팬, 주봉 RSI(과열/침체만)
- **장기 국면 = 월봉** (주간 리뷰 전용): 20개월선 위/아래, 월봉 5/20 배열, 월봉 RSI → 상승/하락/횡보 국면

일봉에서 배열·구름대를 빼고 주봉으로 올린 것, 주봉에서 볼린저·거래량을 뺀 것은 의도적입니다 — 같은 지표를 두 시간축에서 중복 집계하지 않고, 각 지표가 가장 신뢰도 높은 시간축에서만 발언권을 갖도록 했습니다.

### 차트 분석 세션 (`--session chart`)

`marketbrief/chartpack.py` — 미국장 마감 직후(06:20 KST) 나스닥100·S&P500과 전일 코스피를 지수당 2장(일봉→주봉)으로 분석합니다. 카드 상단은 추세(캔들+이평선+일목균형표 — 우측에 **선행 구름 26봉 여백**을 확보해 잘리지 않음), 하단은 모멘텀(볼린저·거래량·RSI·MACD) 묶음입니다. 테스트는 `test_chart.bat` 또는 `python main.py --session chart --force`.

- 카테고리별 지표 점수가 매일 `history/chart_log.csv`에 축적됩니다 — 한 달 주기로 적중률을 계산해 지표 가중치를 조정하는 피드백의 원장입니다
- `history/indicator_weights.json`이 있으면 (예: `{"이평선": 1.2, "RSI": 0.8}`) 카드의 종합 판단 점수에 카테고리 가중치로 곱해집니다. 없으면 전부 1.0
- 월봉은 매일 그리지 않습니다 — 큰 흐름 확인은 주간 리뷰의 월봉 국면 판단을 그대로 사용합니다
- 신호는 **마지막 종가 기준**으로 판정·표시합니다: 가격/RSI 피벗 비교로 **상승·하락 다이버전스**를 탐지해 차트 위에 연결선으로 그리고, RSI에는 **시그널선(9)** 교차, 거래량은 마지막 봉 급증(×배수)/한산 마커를 찍습니다
- 환율·매크로 일일 상태는 `history/fx_log.csv`에 축적됩니다 — 환율→수급 판단의 월간 검증용

### 노션 아카이브 (선택)

`marketbrief/notion.py` — 블로그 팩(본문 + 차트 8장 + `summary.json`)을 노션 데이터베이스에 **하루 1페이지**로 자동 게시합니다. 네이버 블로그는 글쓰기 API가 없어 직접 붙여넣어야 하지만, 노션은 공식 API로 이미지까지 올라갑니다.

- DB 「차트 분석 아카이브」는 지정한 페이지 아래에 첫 실행 때 자동 생성됩니다 (있으면 재사용)
- 속성: 날짜 · 지수별 일봉/주봉 판단 · 종가 · 등락% · 다이버전스 · 원/달러 · 원/달러 20일 · 외국인 20일(조) · 환율-수급(부합/엇갈림) · 피드백 · 피드백 메모 — 피드백 두 열은 비워 두었다가 월간 피드백에서 채웁니다
- 같은 날 다시 실행하면 새 페이지를 만든 뒤 옛 페이지를 휴지통으로 보냅니다 (중복 없음, 새 페이지 생성이 실패하면 기존 페이지 보존)
- `--post` 실행(`post_notion.bat`, GitHub 자동 실행)에서만 게시합니다. `--sample` 실행은 게시하지 않습니다
- 토큰이 없거나 노션 게시가 실패하면 실행이 실패로 끝납니다 (GitHub는 실패 메일을 보내고, 텔레그램 키가 있으면 텔레그램으로도 알림). 블로그 팩은 그대로 남습니다
- 지난 팩 재게시: `python marketbrief/notion.py output/blog_20261015`

설정:

1. 토큰 발급 (둘 중 하나)
   - **권장 — 내부 연결**: https://app.notion.com/developers/connections → Internal connections → Create a new connection → Configuration 탭의 토큰 복사. 그다음 DB를 둘 노션 페이지에서 오른쪽 위 ••• → Connections → + Add connection으로 이 연결을 추가 (그 페이지와 하위에만 접근)
   - **간편 — 개인 액세스 토큰**: https://www.notion.so/developers/tokens → New token (Notion API 권한). 페이지 연결 없이 바로 되지만 내 모든 페이지에 접근할 수 있고, 최대 1년 뒤 만료
2. DB를 둘 페이지의 링크를 복사 (공유 → 링크 복사 — 링크를 통째로 넣어도 됩니다)
3. `.env`에 `NOTION_TOKEN=...`, `NOTION_PARENT_PAGE_ID=...` 추가
4. 연결 확인: `test_notion.bat` — 동봉한 `sample_blog/`(합성 데이터)를 「차트 분석 아카이브 (테스트)」 DB에 올립니다. 확인 후 테스트 DB는 지워도 됩니다
5. (선택) 공개하려면 그 페이지 → 공유 → 웹에 게시

## 이 폴더만으로 실행하기 (노션 마켓 브리핑)

원래 저장소 없이 이 폴더만으로 아침 차트 분석(블로그 팩 → 노션 아카이브)이 돌아갑니다. 인스타그램은 쓰지 않습니다.

1. Python 3.11 이상 설치
2. `test_notion.bat` — `.env`에 `NOTION_TOKEN`, `NOTION_PARENT_PAGE_ID`를 넣고, 샘플을 테스트 DB에 올려 노션 연결 확인
3. `post_notion.bat` — 오늘 차트 분석을 만들어 노션 「차트 분석 아카이브」에 게시 (`.env`에 `KRX_ID`/`KRX_PW`도 — 코스피 수급 차트용). 미국장 최신 데이터가 없는 날(주말·휴장)은 건너뜁니다
4. 매일 자동 실행 — 둘 중 **하나만** 쓰세요 (둘 다 돌면 같은 날 페이지는 교체되지만 지표 로그가 두 곳에 따로 쌓입니다)
   - **GitHub Actions (권장 — PC가 꺼져 있어도 실행)**: github.com에서 비어 있는 비공개 저장소를 만들고 `setup_github.bat` 실행 → 워크플로를 `.github/workflows/`에 넣고 폴더를 저장소에 올립니다 (Git이 없으면 웹에서 올리는 방법을 안내). 그다음 저장소 Settings → Secrets and variables → Actions에 `NOTION_TOKEN`, `NOTION_PARENT_PAGE_ID`, `KRX_ID`, `KRX_PW` 등록 (선택: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). 화~토 06:20 KST에 실행되고 `history/`(지표 로그·환율 로그·수급 캐시)를 저장소에 커밋합니다. Actions 탭 → notion-market-brief → Run workflow로 바로 시험할 수 있고, 주말에 시험할 땐 force를 켜세요
   - **이 PC에서**: `register_daily.bat` — 윈도우 작업 스케줄러에 화~토 06:20 실행을 등록합니다. 그 시각에 PC가 꺼져 있거나 잠자기면 다음에 켜질 때 실행되고, 기록은 `output/daily.log`. 해제: `schtasks /Delete /TN NotionMarketBrief /F`

- `test_chart.bat`은 노션에 올리지 않고 블로그 팩만 만듭니다 (`output/blog_날짜/`)
- `marketbrief/instagram.py`는 이제 쓰지 않습니다 (지워도 됩니다)
- 폴더 맨 위의 `daily-brief.yml`은 GitHub 워크플로 원본입니다 — `setup_github.bat`이 `.github/workflows/`로 복사합니다
- `marketbrief/chartstyle.py` — 원래 `cards.py` 중 차트 세션이 쓰는 부분(폰트·팔레트). `cards.py`가 있는 저장소에서는 그쪽을 씁니다
- `marketbrief/notify.py` — 텔레그램 알림 (선택, `.env`에 키가 없으면 아무것도 안 함)
- `main.py` — 다른 세션 모듈이 없으면 `--session chart`만 실행 (원래 저장소에서는 동작 동일)
- 첫 실행 때 코스피 수급 2년치를 KRX에서 새로 받아 `history/`에 캐시합니다

카드 순서: 표지 → 매크로 → **시장 맵**(Finviz 스타일 트리맵 — 미국은 대형주 40여 개, 국내는 대형주 30여 개를 섹터별로 배치, 크기=시총·색=등락률) → (수급) → 지수·종목 차트 → 주요 이슈. 모든 카드에 페이지 번호가 자동으로 찍히며, 환경변수 `IG_HANDLE`(예: `@my_account`)을 넣으면 하단에 계정 워터마크가 들어갑니다. 매크로 지표 구성·뉴스 피드·키워드·경보 임계값은 `config.py`에서 수정합니다.

### 계정 차별화 장치

- **단기 / 중장기 이중 뷰**: 모든 신호에 시계(단기: 크로스·RSI·볼린저·거래량·수급 / 중장기: 배열·구름대·후행스팬)를 부여해 두 개의 판단을 따로 제시합니다. "단기 반등 vs 추세 하락" 같은 국면이 한눈에 구분됩니다
- **판단 전환 감지 + 근거**: 전일 데이터로 판단을 재계산해 바뀐 자산을 표시하고, 어떤 신호가 새로 발생/해소돼서 바뀌었는지 근거를 캡션에 함께 적습니다
- **오늘의 한 줄**: 지수 흐름·최대 변동 자산·수급 연속일을 규칙 기반으로 조합한 헤드라인. VIX·금리가 임계값 이상 움직인 날만 ⚠ 경보가 앞에 붙습니다 (경보 기준은 변동성과 금리만 — config.py MACRO_ALERTS)
- **다음주 일정 카드**: 한국시간 기준 날짜별로 경제 일정과 관심종목 실적 발표를 정리 (미국 실적은 KST로 환산)
- **스토리 카드**: 1080×1920 세로 요약 카드가 매번 함께 생성됩니다. `IG_POST_STORY=1`을 설정하면 캐러셀 게시 후 스토리도 자동 게시 (피드 유도)
- **월간 적중률 리포트**: 자기 신호의 성적을 투명하게 공개
- **휴장일 자동 스킵**: 최신 데이터가 오늘자가 아니면(공휴일 등) 게시를 건너뛰고 텔레그램으로 알립니다 (`--force`로 무시)
- **판단 아카이브**: 매일의 스코어·판단이 `history/verdicts.csv`에 축적되고 GitHub Actions가 자동 커밋합니다 — 실측 성적 콘텐츠의 기반

시장 맵의 종목 구성·시총 가중치는 `marketbrief/sectors.py`에서 관리합니다 (가중치는 타일 크기용 근사값이라 가끔만 갱신하면 됩니다). 배포 절차는 **DEPLOY.md** 참고.

## 구조

```
insta-market-brief/
├── main.py                     # 실행 진입점
├── marketbrief/
│   ├── config.py               # 지수/관심종목/지표 파라미터 — 종목 추가는 여기
│   ├── fetch.py                # yfinance 일봉 수집 (+ --sample 합성 데이터)
│   ├── indicators.py           # 지표 계산
│   ├── signals.py              # 신호 탐지 + 종합 판단(강세/중립/약세)
│   ├── cards.py                # 1080x1350 카드 이미지 생성
│   ├── chartpack.py            # 차트 분석 세션 (인스타 카드 + 블로그 팩 + summary.json)
│   ├── notion.py               # 노션 아카이브 게시 (단독 실행 가능)
│   └── instagram.py            # Graph API 캐러셀 게시 + 토큰 갱신
├── .github/workflows/daily-brief.yml  # 매일 07:30 KST 자동 실행
└── output/                     # 생성된 카드 + 캡션
```

## 실행

```bash
pip install -r requirements.txt
python main.py --session us            # 미국장 카드 생성 (게시 X)
python main.py --session kr            # 국내장 카드 + 수급 (게시 X)
python main.py --session kr --post     # 인스타그램 게시까지
python main.py --session kr --sample   # 네트워크 없이 합성 데이터 테스트
```

`--session`을 생략하면 시각(KST 오전=us, 오후=kr)으로 자동 선택합니다.
한글 폰트가 없으면(리눅스): `sudo apt-get install fonts-noto-cjk`

### 국내 수급 데이터 (pykrx → KRX 정보데이터시스템 API)

개인/외국인/기관 순매수는 KRX 정보데이터시스템(data.krx.co.kr)의 API를 감싸는
`pykrx`로 받아옵니다. 최신 pykrx는 **KRX 무료 계정 로그인**이 필요합니다:

1. https://data.krx.co.kr 회원가입 (무료)
2. 환경변수 설정: `KRX_ID`(아이디), `KRX_PW`(비밀번호)

수급 조회에 실패하면 수급 카드 없이 시세 분석만으로 진행됩니다.
(참고: KRX 공식 Open API(openapi.krx.co.kr)는 시세·지수만 있고 투자자별 매매는
제공하지 않아 정보데이터시스템 경유가 필요합니다.)

### 국고채 금리 (한국은행 ECOS API)

국내 매크로 카드의 국고채 3년/10년 금리는 한국은행 ECOS Open API를 사용합니다:

1. https://ecos.bok.or.kr/api/ 에서 무료 인증키 발급
2. 환경변수 `ECOS_API_KEY` 설정

키가 없으면 해당 타일만 자동 제외되고 나머지는 정상 생성됩니다.

### 텔레그램 알림 (선택)

게시 성공/실패를 텔레그램으로 받으려면:

1. 텔레그램에서 @BotFather 에게 `/newbot` → 봇 토큰 발급
2. 만든 봇에게 아무 메시지 전송 후 `https://api.telegram.org/bot<토큰>/getUpdates` 접속해 `chat.id` 확인
3. 환경변수 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 설정

### 경제 일정 관리

주간 리뷰의 "다음주 경제 일정"은 `config.py`의 `ECON_CALENDAR` 목록에서 관리합니다
(FOMC·CPI·금통위 등 확정 일정을 한 달에 한 번 정도 채워 넣으면 됩니다).
관심 종목 실적 발표 일정은 yfinance에서 자동으로 가져옵니다.

## 신호 로직 요약

| 지표 | 강세 신호 | 약세 신호 |
|---|---|---|
| 이평선 | 골든크로스(5↗20), 정배열, 이격 과대(-5%↓) | 데드크로스, 역배열, 이격 과열(+5%↑) |
| RSI(14) | 30 상향 돌파, 50 상향 돌파, 과매도(≤30) | 70 하향 이탈, 50 하향 이탈, 과매수(≥70) |
| 볼린저(20,2σ) | 하단 이탈(반등 관찰), 밴드 타기 | 상단 돌파(과열) — 스퀴즈는 중립(변동성 임박) |
| 일목균형표 | 구름대 위, 전환선 골든크로스, 후행스팬 호전 | 구름대 아래, 전환선 데드크로스, 후행스팬 역전 |
| 거래량 | 평균 2배↑ + 상승 | 평균 2배↑ + 하락 |
| 수급(국내) | 외국인/기관 3일+ 연속 순매수, 쌍끌이 매수 | 3일+ 연속 순매도, 쌍끌이 매도 |

신호별 점수(방향 ±1 × 강도 1~2)를 합산해 **강세 / 다소 강세 / 중립 / 다소 약세 / 약세**로 종합 판단합니다. 임계값·기간은 `config.py`의 `PARAMS`에서 조정하세요.

## 인스타그램 API 셋업 (개인 계정 OK)

본인 계정에만 게시하는 용도라면 **앱 심사 불필요**, 페이스북 페이지도 필요 없습니다.

1. **프로페셔널 계정 전환**: 인스타 앱 → 설정 → 계정 유형 및 도구 → 프로페셔널 계정으로 전환 (크리에이터 선택, 무료)
2. **Meta 개발자 앱 생성**: https://developers.facebook.com → My Apps → Create App → 사용 사례에서 "Instagram" 계열 선택
3. 앱 대시보드 → **Instagram > API setup with Instagram login** → 본인 인스타 계정을 테스터로 추가·연결
4. 같은 화면에서 **액세스 토큰 생성** → "Generate token" (장기 토큰, 60일 유효). 함께 표시되는 **Instagram user ID**도 복사
5. **imgbb API 키 발급**: https://api.imgbb.com (무료 가입) — 인스타 API는 공개 URL의 이미지만 받으므로, 카드를 imgbb에 24시간짜리 임시 URL로 올린 뒤 게시하는 데 사용
6. 환경변수 설정:

```bash
export IG_USER_ID="1784..."
export IG_ACCESS_TOKEN="IGQW..."
export IMGBB_API_KEY="..."
python main.py --post
```

### 토큰 갱신 (60일)

토큰은 60일마다 만료됩니다. 만료 전 아무 때나:

```python
from marketbrief.instagram import refresh_token
print(refresh_token())   # 새 토큰 출력 → IG_ACCESS_TOKEN 교체
```

GitHub Actions로 운영한다면 한 달에 한 번 위를 실행해 시크릿을 갱신하거나, 별도 워크플로로 자동화할 수 있습니다.

## 매일 자동 실행 (GitHub Actions 권장)

1. 이 폴더를 GitHub 비공개 저장소로 푸시
2. 저장소 Settings → Secrets and variables → Actions에 `IG_USER_ID`, `IG_ACCESS_TOKEN`, `IMGBB_API_KEY`, `KRX_ID`, `KRX_PW` 등록 (노션 아카이브를 쓰면 `NOTION_TOKEN`, `NOTION_PARENT_PAGE_ID`도)
3. 끝 — `.github/workflows/daily-brief.yml`이 **평일 아침 07:30 KST(미국장)**, **평일 오후 16:00 KST(국내장+수급)** 두 번 자동 실행됩니다

Actions 탭에서 "Run workflow" 버튼으로 수동 실행도 가능합니다.

## 종목 추가/변경 (watchlist.txt)

프로젝트 루트의 **`watchlist.txt`** 에 종목 이름이나 티커를 한 줄씩 적으면 됩니다:

```
삼성전자
엔비디아
AAPL
005930.KS
```

티커는 자동으로 찾습니다 — ① 티커 형식이면 그대로, ② 내장 별칭 사전(주요 국내/미국 종목),
③ 국내 종목명은 KRX 상장 목록(FinanceDataReader), ④ 그 외 야후 검색. 해석 결과는
`.watchlist_cache.json`에 저장돼 재조회하지 않습니다. 이름을 못 찾은 줄은 건너뛰고 로그로 알려줍니다.

- 기본값은 비어 있음 — 지수 중심 브리핑
- 국내 종목은 자동으로 종목코드가 붙어 수급(개인/외국인/기관) 분석까지 활성화됩니다
- 인스타 캐러셀은 최대 10장이므로 세션당 종목 2~3개 정도를 권장합니다

## 주의

- yfinance는 비공식 야후 파이낸스 래퍼로, 간헐적 지연·오류가 있을 수 있습니다.
- 본 자료는 투자 권유가 아닌 기술적 지표 참고 자료입니다.
