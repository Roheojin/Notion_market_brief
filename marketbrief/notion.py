# -*- coding: utf-8 -*-
"""노션 아카이브 — 차트 분석 블로그 팩을 노션 데이터베이스에 하루 1페이지로 게시.

블로그 팩 폴더(output/blog_YYYYMMDD/)를 그대로 읽어서 올립니다:
  본문.txt      → 노션 블록 (■ → 제목, [..] → 소제목, 《이미지》 → 이미지,
                  · → 글머리, 포착 신호 → 콜아웃, → 종합 → 굵은 문단)
  *.png         → 노션에 직접 업로드 (File Upload API, 무료 플랜 파일당 5MiB)
  summary.json  → DB 속성 (날짜 · 지수별 일봉/주봉 판단 · 종가 · 등락% ·
                  다이버전스 · 원/달러 · 외국인 20일 순매수 · 환율-수급 부합 여부)

데이터베이스는 부모 페이지 아래에 처음 한 번 자동으로 만들고(있으면 재사용),
DB는 시장별로 따로(「차트 분석 아카이브 (한국장)」 · 「… (미국장)」) 둡니다.
같은 날짜 페이지가 있으면 새 페이지를 만든 뒤 옛 페이지를 휴지통으로 보냅니다
(재실행해도 중복 없음). '피드백' · '피드백 메모' 열은 월간 피드백에서 채웁니다.

환경변수:
  NOTION_TOKEN           내부 연결(Internal connection) 토큰 또는 개인 액세스 토큰
  NOTION_PARENT_PAGE_ID  DB를 만들 페이지 — ID 또는 페이지 링크 통째로
  NOTION_DATABASE_ID     (선택) 이미 있는 DB를 직접 지정할 때
  NOTION_DRYRUN=1        실제 호출 없이 요청 내용만 팩 폴더의 notion_dryrun.json에 저장

단독 실행 (재게시 · 연결 테스트):
  python marketbrief/notion.py output/blog_20261015          # 그날 팩을 게시
  python marketbrief/notion.py sample_blog --test            # 테스트 DB에 게시

이 파일은 표준 라이브러리 + requests만 씁니다 (단독 실행 가능).
"""
import json
import os
import re
import sys
import time

NOTION_VERSION = "2026-03-11"
API_BASE = "https://api.notion.com"
DB_TITLE = "차트 분석 아카이브"
TEST_DB_TITLE = "차트 분석 아카이브 (테스트)"

MAX_CHILDREN = 100      # 요청 1회당 블록 수 한도
MAX_TEXT = 1900         # 텍스트 조각 1개 한도 2000자 (여유 두고 분할)
MIN_INTERVAL = 0.35     # 평균 초당 3회 제한 → 요청 간 최소 간격(초)
FREE_FILE_LIMIT = 5 * 1024 * 1024

VERDICTS = [("강세", "red"), ("다소 강세", "pink"), ("중립", "gray"),
            ("다소 약세", "purple"), ("약세", "blue")]
DISCLAIMER_PREFIX = "본 게시물은 투자 권유가"


class NotionError(RuntimeError):
    pass


# ──────────────────────────────────────────────────────────────
# HTTP 클라이언트 (속도 제한 · 429/5xx 재시도) + 드라이런
# ──────────────────────────────────────────────────────────────

class _Client:
    def __init__(self, token: str):
        import requests
        self._s = requests.Session()
        self._base = (os.environ.get("NOTION_API_BASE") or API_BASE).rstrip("/")
        self._h = {"Authorization": f"Bearer {token}",
                   "Notion-Version": NOTION_VERSION}
        self._last = 0.0

    def call(self, method: str, path: str, body: dict | None = None,
             files: dict | None = None) -> dict:
        url = self._base + path
        for attempt in range(5):
            gap = time.monotonic() - self._last
            if gap < MIN_INTERVAL:
                time.sleep(MIN_INTERVAL - gap)
            self._last = time.monotonic()
            if files is not None:   # multipart — Content-Type은 requests가 지정
                r = self._s.request(method, url, headers=self._h, files=files,
                                    timeout=60)
            else:
                r = self._s.request(method, url, json=body, timeout=30,
                                    headers={**self._h,
                                             "Content-Type": "application/json"})
            if r.status_code == 429 or r.status_code >= 500:
                try:
                    wait = float(r.headers.get("Retry-After", ""))
                except ValueError:
                    wait = 2.0 ** attempt
                time.sleep(min(max(wait, 0.5), 30))
                continue
            if r.status_code >= 400:
                try:
                    err = r.json()
                    msg = f"{err.get('code')}: {err.get('message')}"
                except Exception:
                    msg = r.text[:300]
                raise NotionError(f"{method} {path} → {r.status_code} {msg}")
            return r.json() if r.content else {}
        raise NotionError(f"{method} {path} → 재시도 한도 초과")


class _DryRun:
    """실제 호출 없이 요청 내용만 기록 (형식 점검용)."""

    def __init__(self):
        self.log: list[dict] = []
        self._n = 0

    def call(self, method, path, body=None, files=None) -> dict:
        self._n += 1
        fake = f"00000000-0000-0000-0000-{self._n:012d}"
        entry = {"method": method, "path": path}
        if body is not None:
            entry["body"] = body
        if files is not None:
            entry["files"] = {k: f"{v[0]} ({len(v[1])} bytes)"
                              for k, v in files.items()}
        self.log.append(entry)
        if method == "POST" and path == "/v1/databases":
            return {"id": fake, "data_sources": [{"id": fake, "name": DB_TITLE}]}
        if method == "POST" and path == "/v1/pages":
            return {"id": fake, "url": f"https://www.notion.so/dryrun-{fake}"}
        if path.endswith("/query") or "/children" in path:
            return {"results": [], "has_more": False}
        if method == "GET" and path.startswith("/v1/databases/"):
            return {"id": fake, "data_sources": [{"id": fake}]}
        if method == "GET" and path.startswith("/v1/data_sources/"):
            return {"properties": {}}
        return {"id": fake}


# ──────────────────────────────────────────────────────────────
# DB 스키마 · 속성
# ──────────────────────────────────────────────────────────────

def _norm_id(s: str) -> str:
    """페이지 링크/ID → 하이픈 UUID. 링크 끝의 32자리 16진수를 씁니다."""
    seg = (s or "").strip().split("?")[0].split("#")[0].rstrip("/").split("/")[-1]
    m = re.search(r"([0-9a-fA-F]{32})$", seg.replace("-", ""))
    if not m:
        raise NotionError(f"노션 페이지 ID를 찾을 수 없습니다: {s!r}")
    h = m.group(1).lower()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _schema(summary: dict) -> dict:
    v_opts = [{"name": n, "color": c} for n, c in VERDICTS]
    props: dict = {"제목": {"title": {}}, "날짜": {"date": {}}}
    div_opts = []
    for ix in summary.get("indices", []):
        n = ix["name"]
        props[f"{n} 일봉"] = {"select": {"options": v_opts}}
        props[f"{n} 주봉"] = {"select": {"options": v_opts}}
        props[f"{n} 종가"] = {"number": {"format": "number_with_commas"}}
        props[f"{n} 등락%"] = {"number": {"format": "number"}}
        for tf in ("일봉", "주봉"):
            div_opts += [{"name": f"{n} {tf} 상승", "color": "red"},
                         {"name": f"{n} {tf} 하락", "color": "blue"}]
    props["다이버전스"] = {"multi_select": {"options": div_opts}}
    if summary.get("market") != "미국장":   # 환율·수급 열은 한국장(·통합)만
        props["원/달러"] = {"number": {"format": "number_with_commas"}}
        props["원/달러 20일"] = {"number": {"format": "number"}}
        props["외국인 20일(조)"] = {"number": {"format": "number"}}
        props["환율-수급"] = {"select": {"options": [
            {"name": "부합", "color": "green"},
            {"name": "엇갈림", "color": "orange"}]}}
    props["피드백"] = {"select": {"options": [
        {"name": "적중", "color": "green"}, {"name": "빗나감", "color": "red"},
        {"name": "보류", "color": "gray"}]}}
    props["피드백 메모"] = {"rich_text": {}}
    return props


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f      # NaN → 빈 칸


def _props(summary: dict, title_key: str) -> dict:
    p: dict = {
        title_key: {"title": [{"type": "text",
                               "text": {"content": summary["title"]}}]},
        "날짜": {"date": {"start": summary["date"]}},
    }
    divs: list[str] = []
    for ix in summary.get("indices", []):
        n = ix["name"]
        if ix.get("vd"):
            p[f"{n} 일봉"] = {"select": {"name": ix["vd"]}}
        if ix.get("vw"):
            p[f"{n} 주봉"] = {"select": {"name": ix["vw"]}}
        p[f"{n} 종가"] = {"number": _num(ix.get("close"))}
        p[f"{n} 등락%"] = {"number": _num(ix.get("chg"))}
        divs += [f"{n} {d}" for d in ix.get("divs", [])]
    p["다이버전스"] = {"multi_select": [{"name": d} for d in dict.fromkeys(divs)]}
    fx = summary.get("fx") or {}
    if fx.get("krw") is not None:
        p["원/달러"] = {"number": _num(fx["krw"])}
    if fx.get("krw_d20") is not None:
        p["원/달러 20일"] = {"number": _num(fx["krw_d20"])}
    if summary.get("foreign_20d") is not None:
        p["외국인 20일(조)"] = {"number": _num(summary["foreign_20d"])}
    if summary.get("fx_flow"):
        p["환율-수급"] = {"select": {"name": summary["fx_flow"]}}
    return p


# ──────────────────────────────────────────────────────────────
# 본문.txt → 노션 블록
# ──────────────────────────────────────────────────────────────

_IMG = re.compile(r"^《이미지\s*\d+\s*—\s*(.+?)》$")


def _rt(text: str, bold: bool = False, color: str | None = None) -> list[dict]:
    out = []
    for i in range(0, max(len(text), 1), MAX_TEXT):
        seg: dict = {"type": "text", "text": {"content": text[i:i + MAX_TEXT]}}
        ann = {}
        if bold:
            ann["bold"] = True
        if color:
            ann["color"] = color
        if ann:
            seg["annotations"] = ann
        out.append(seg)
    return out


def _blk(kind: str, text: str, bold: bool = False, color: str | None = None,
         emoji: str | None = None) -> dict:
    body: dict = {"rich_text": _rt(text, bold, color)}
    if kind == "callout":
        body["icon"] = {"type": "emoji", "emoji": emoji or "📌"}
        body["color"] = "gray_background"
    return {"object": "block", "type": kind, kind: body}


def text_to_blocks(text: str, upload) -> list[dict]:
    """블로그 본문 → 노션 블록 목록. upload(파일명) → file_upload id 또는 None.

    본문은 네이버용이라 이미지가 제목 앞에 오는데, 노션에선 제목 → 이미지 → 해설
    순서가 읽기 좋아서 이미지 바로 뒤가 제목이면 둘의 순서를 바꿉니다.
    """
    blocks: list[dict] = []
    pending: dict | None = None      # 다음 줄이 제목인지 보려고 잠시 보류한 이미지

    def _flush():
        nonlocal pending
        if pending is not None:
            blocks.append(pending)
            pending = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("[제목 제안]"):
            continue
        m = _IMG.match(line)
        if m:
            _flush()
            fn = m.group(1).strip()
            fid = upload(fn)
            if fid:
                pending = {"object": "block", "type": "image",
                           "image": {"type": "file_upload",
                                     "file_upload": {"id": fid}}}
            else:
                pending = _blk("paragraph", f"(이미지 누락: {fn})", color="gray")
            continue
        if line.startswith("■"):
            blocks.append(_blk("heading_2", line.lstrip("■").strip()))
            _flush()
            continue
        if line.startswith("[") and line.endswith("]"):
            blocks.append(_blk("heading_3", line[1:-1].strip()))
            _flush()
            continue
        _flush()
        if line.startswith("· "):
            blocks.append(_blk("bulleted_list_item", line[2:].strip()))
        elif line.startswith("포착 신호:"):
            blocks.append(_blk("callout", line, emoji="📍"))
        elif line.startswith("→ "):
            blocks.append(_blk("paragraph", line, bold=True))
        elif line.startswith(DISCLAIMER_PREFIX):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            blocks.append(_blk("paragraph", line, color="gray"))
        else:
            blocks.append(_blk("paragraph", line))
    _flush()
    return blocks


# ──────────────────────────────────────────────────────────────
# API 단계
# ──────────────────────────────────────────────────────────────

def _find_db(client, parent_id: str, title: str) -> str | None:
    cursor = None
    while True:
        path = f"/v1/blocks/{parent_id}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        r = client.call("GET", path)
        for b in r.get("results", []):
            if (b.get("type") == "child_database" and not b.get("in_trash")
                    and (b.get("child_database") or {}).get("title") == title):
                return b["id"]
        if not r.get("has_more"):
            return None
        cursor = r.get("next_cursor")


def _data_source_id(client, db_id: str) -> str:
    r = client.call("GET", f"/v1/databases/{db_id}")
    ds = r.get("data_sources") or []
    if not ds:
        raise NotionError("데이터베이스의 data source를 찾을 수 없습니다")
    return ds[0]["id"]


def _create_db(client, parent_id: str, title: str, schema: dict) -> str:
    r = client.call("POST", "/v1/databases", {
        "parent": {"type": "page_id", "page_id": parent_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "icon": {"type": "emoji", "emoji": "📊"},
        "initial_data_source": {"properties": schema},
    })
    ds = r.get("data_sources") or []
    return ds[0]["id"] if ds else _data_source_id(client, r["id"])


def _ensure_schema(client, ds_id: str, schema: dict) -> str:
    """빠진 열만 추가하고, DB의 제목 열 이름을 돌려줍니다."""
    r = client.call("GET", f"/v1/data_sources/{ds_id}")
    have = r.get("properties") or {}
    title_key = next((k for k, v in have.items() if v.get("type") == "title"),
                     "제목")
    missing = {k: v for k, v in schema.items()
               if k not in have and "title" not in v}
    if missing:
        print(f"  [notion] DB 열 추가: {', '.join(missing)}")
        client.call("PATCH", f"/v1/data_sources/{ds_id}",
                    {"properties": missing})
    return title_key


def _same_day_pages(client, ds_id: str, date_str: str) -> list[str]:
    r = client.call("POST", f"/v1/data_sources/{ds_id}/query", {
        "filter": {"property": "날짜", "date": {"equals": date_str}},
        "page_size": 100,
    })
    return [p["id"] for p in r.get("results", [])
            if p.get("object") == "page" and not p.get("in_trash")]


def _upload(client, path: str, name: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    if len(data) > FREE_FILE_LIMIT:
        print(f"  [notion] {os.path.basename(path)} {len(data) / 1e6:.1f}MB — "
              f"무료 플랜 한도(5MiB) 초과, 유료 플랜이 아니면 실패할 수 있음")
    fu = client.call("POST", "/v1/file_uploads",
                     {"filename": name, "content_type": "image/png"})
    client.call("POST", f"/v1/file_uploads/{fu['id']}/send",
                files={"file": (name, data, "image/png")})
    return fu["id"]


def _create_page(client, ds_id: str, props: dict, blocks: list[dict]) -> dict:
    page = client.call("POST", "/v1/pages", {
        "parent": {"type": "data_source_id", "data_source_id": ds_id},
        "icon": {"type": "emoji", "emoji": "📈"},
        "properties": props,
        "children": blocks[:MAX_CHILDREN],
    })
    for i in range(MAX_CHILDREN, len(blocks), MAX_CHILDREN):
        client.call("PATCH", f"/v1/blocks/{page['id']}/children",
                    {"children": blocks[i:i + MAX_CHILDREN]})
    return page


# ──────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────

def publish_pack(blog_dir: str, test: bool = False) -> str | None:
    """블로그 팩 폴더를 노션에 게시하고 페이지 URL을 돌려줍니다.

    토큰이 없으면 아무것도 하지 않고 None. test=True면 테스트 DB에 올립니다.
    """
    dry = os.environ.get("NOTION_DRYRUN") == "1"
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token and not dry:
        print("  [notion] NOTION_TOKEN 없음 — 노션 게시 건너뜀")
        return None

    body_path = os.path.join(blog_dir, "본문.txt")
    sum_path = os.path.join(blog_dir, "summary.json")
    if not (os.path.exists(body_path) and os.path.exists(sum_path)):
        raise NotionError(f"블로그 팩에 본문.txt / summary.json이 없습니다: {blog_dir}")
    with open(sum_path, encoding="utf-8") as f:
        summary = json.load(f)
    with open(body_path, encoding="utf-8") as f:
        text = f.read()
    if test:
        summary["title"] = "[테스트] " + summary["title"]
    db_title = TEST_DB_TITLE if test else DB_TITLE
    if summary.get("market"):      # 시장별 DB: 「차트 분석 아카이브 (미국장)」
        db_title += f" ({summary['market']})"

    client = _DryRun() if dry else _Client(token)
    try:
        schema = _schema(summary)
        db_env = "" if test else os.environ.get("NOTION_DATABASE_ID", "").strip()
        if db_env:
            ds_id = _data_source_id(client, _norm_id(db_env))
        else:
            parent = os.environ.get("NOTION_PARENT_PAGE_ID", "").strip()
            if not parent and not dry:
                raise NotionError("NOTION_PARENT_PAGE_ID가 비어 있습니다 — "
                                  "DB를 만들 노션 페이지 링크를 넣어 주세요")
            parent_id = _norm_id(parent or "0" * 32)
            db_id = _find_db(client, parent_id, db_title)
            if db_id:
                ds_id = _data_source_id(client, db_id)
            else:
                print(f"  [notion] '{db_title}' 데이터베이스를 새로 만듭니다")
                ds_id = _create_db(client, parent_id, db_title, schema)
        title_key = _ensure_schema(client, ds_id, schema)
        old = _same_day_pages(client, ds_id, summary["date"])

        uploaded = [0]

        def _up(fn: str) -> str | None:
            p = os.path.join(blog_dir, fn)
            if not os.path.exists(p):
                print(f"  [notion] 이미지 파일 없음: {fn}")
                return None
            try:
                fid = _upload(client, p, f"chart_{uploaded[0] + 1:02d}.png")
                uploaded[0] += 1
                return fid
            except Exception as e:
                print(f"  [notion] 이미지 업로드 실패 {fn}: {e}")
                return None

        blocks = text_to_blocks(text, _up)
        page = _create_page(client, ds_id, _props(summary, title_key), blocks)
        # 새 페이지가 만들어진 뒤에만 같은 날짜 옛 페이지를 정리 (실패 시 기존 보존)
        for pid in old:
            if pid != page.get("id"):
                client.call("PATCH", f"/v1/pages/{pid}", {"in_trash": True})
        print(f"  [notion] 블록 {len(blocks)}개 · 이미지 {uploaded[0]}장 게시"
              + (f" · 같은 날짜 기존 페이지 {len(old)}개 교체" if old else ""))
        return page.get("url")
    finally:
        if dry:
            out = os.path.join(blog_dir, "notion_dryrun.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(client.log, f, ensure_ascii=False, indent=1)
            print(f"  [notion] 드라이런 — 요청 {len(client.log)}건 기록: {out}")


def _main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="블로그 팩을 노션 아카이브에 게시")
    ap.add_argument("blog_dir", help="예: output/blog_20261015")
    ap.add_argument("--test", action="store_true",
                    help=f"'{TEST_DB_TITLE}' DB에 게시 (연결 확인용)")
    args = ap.parse_args(argv)
    try:   # .env 자동 로드 (있으면)
        from dotenv import load_dotenv
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        load_dotenv(os.path.join(root, ".env"))
    except ImportError:
        pass
    try:
        url = publish_pack(args.blog_dir, test=args.test)
    except NotionError as e:
        print(f"노션 게시 실패: {e}")
        return 1
    if url:
        print(f"노션 게시 완료: {url}")
        return 0
    return 0 if os.environ.get("NOTION_DRYRUN") == "1" else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
