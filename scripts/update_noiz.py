from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_PATH = DATA_DIR / "noiz-data.json"
INVENTORY_PATH = DATA_DIR / "event-inventory.json"
DRAFT_REVIEW_PATH = DATA_DIR / "noiz-draft-review.json"
CURATION_SEED_PATH = DATA_DIR / "noiz-curation-seed.json"
SOURCES_PATH = ROOT / "scripts" / "sources.json"
ARCHIVE_INDEX_PATH = DATA_DIR / "noiz-archive-index.json"
ARCHIVE_DIR = DATA_DIR / "archive"

KST = timezone(timedelta(hours=9))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NOIZBot/1.0; +https://github.com/)",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
}

THEME_DEFAULT = {
    "id": "legacy-lime-blue",
    "name": "Legacy Lime & Blue",
    "bg": "#c6ff00",
    "paper": "rgba(255,255,255,.18)",
    "ink": "#3f5d7f",
    "muted": "#58779a",
    "line": "rgba(63,93,127,.24)",
    "white": "#f4ffd8",
}

AGGREGATE_WORDS = [
    "총정리", "놀거리", "가볼만한", "가볼 만한", "추천", "모음", "리스트", "한눈에",
    "캘린더", "일정 정리", "전시 추천", "전시회 추천", "팝업 추천", "팝업스토어 추천",
    "데이트코스", "핫플", "새창 열림", "오픈일 팝업 방문 후기", "방문 후기",
]
BAD_CARD_URL_PARTS = [
    "blog.naver.com", "post.naver.com", "cafe.naver.com", "news.google.com",
    "search.naver.com", "html.duckduckgo.com"
]
EXPERIENCE_WORDS = [
    "팝업", "pop up", "popup", "전시", "exhibition", "미술관", "박물관", "갤러리",
    "스토어", "공간", "마켓", "브랜드", "체험", "관람", "개인전", "기획전",
]
AREA_WORDS = ["성수", "여의도", "잠실", "한남", "삼청", "종로", "중구", "강남", "송파", "동대문", "노원", "용산", "홍대", "마포"]
VENUE_HINTS = [
    "T Factory 성수", "더현대 서울", "서울시립미술관", "서울시립 미술아카이브",
    "그라운드시소", "DDP", "한성백제박물관", "청계천박물관", "서울생활사박물관",
    "국립현대미술관", "쎈느", "더가베",
]


@dataclass
class RawCandidate:
    sourceName: str
    sourceType: str
    title: str
    text: str
    url: str
    weight: int
    start: str = ""
    end: str = ""
    venue: str = ""
    area: str = ""


@dataclass
class InventoryEvent:
    title: str
    venue: str
    area: str
    region: str
    category: str
    start: str
    end: str
    officialUrl: str
    sourceName: str
    summary: str
    notes: str = ""
    lastSeen: str = ""
    seed: bool = False


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u200b", " ")).strip()


def safe_fetch(url: str, timeout: int = 18) -> str:
    try:
        res = requests.get(url, headers=HEADERS, timeout=timeout)
        res.raise_for_status()
        return res.text
    except Exception as e:
        print(f"[WARN] fetch failed: {url}: {e}")
        return ""


def parse_jsonish(text: str) -> Any:
    text = clean_text(text).removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if not match:
            raise
        return json.loads(match.group(1))


def ask_gemini(prompt: str, *, max_tokens: int = 8192, temperature: float = 0.15) -> Any:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    res = requests.post(
        GEMINI_ENDPOINT,
        params={"key": GEMINI_API_KEY},
        headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        },
        timeout=90,
    )
    res.raise_for_status()
    payload = res.json()
    parts = payload["candidates"][0]["content"]["parts"]
    return parse_jsonish("\n".join(part.get("text", "") for part in parts).strip())


def extract_period_from_text(text: str) -> tuple[str, str]:
    source = clean_text(text)
    now_year = datetime.now(KST).year
    dash = r"(?:~|–|—|-|부터|에서|to|TO|\s+)"
    year = r"(20\d{2})"
    month = r"(1[0-2]|0?[1-9])"
    day = r"(3[01]|[12]\d|0?[1-9])"
    ym_sep = r"[.\-/년\s]+"
    md_sep = r"[.\-/월\s]+"

    patterns = [
        rf"{year}{ym_sep}{month}{md_sep}{day}\s*(?:일)?\s*{dash}\s*{year}{ym_sep}{month}{md_sep}{day}",
        rf"{year}{ym_sep}{month}{md_sep}{day}\s*(?:일)?\s*{dash}\s*{month}{md_sep}{day}",
        rf"{month}{md_sep}{day}\s*(?:일)?\s*{dash}\s*{month}{md_sep}{day}",
    ]

    def iso(y: int, m: int, d: int) -> str:
        try:
            return datetime(y, m, d, tzinfo=KST).date().isoformat()
        except ValueError:
            return ""

    for pattern in patterns:
        m = re.search(pattern, source, flags=re.I)
        if not m:
            continue
        groups = m.groups()
        if len(groups) == 6:
            y1, mo1, d1, y2, mo2, d2 = groups
            return iso(int(y1), int(mo1), int(d1)), iso(int(y2), int(mo2), int(d2))
        if len(groups) == 5:
            y1, mo1, d1, mo2, d2 = groups
            return iso(int(y1), int(mo1), int(d1)), iso(int(y1), int(mo2), int(d2))
        if len(groups) == 4:
            mo1, d1, mo2, d2 = groups
            y2 = now_year
            if int(mo2) < int(mo1):
                y2 += 1
            return iso(now_year, int(mo1), int(d1)), iso(y2, int(mo2), int(d2))

    single_patterns = [
        rf"{year}{ym_sep}{month}{md_sep}{day}\s*(?:일)?\s*(?:오픈|개막|시작|부터|open|opens)",
        rf"{month}{md_sep}{day}\s*(?:일)?\s*(?:오픈|개막|시작|부터|open|opens)",
    ]
    for pattern in single_patterns:
        m = re.search(pattern, source, flags=re.I)
        if not m:
            continue
        groups = m.groups()
        if len(groups) == 3:
            y, mo, d = groups
            return iso(int(y), int(mo), int(d)), ""
        if len(groups) == 2:
            mo, d = groups
            return iso(now_year, int(mo), int(d)), ""
    return "", ""


def is_bad_card_url(url: str) -> bool:
    lower = str(url or "").lower()
    return any(x in lower for x in BAD_CARD_URL_PARTS)


def is_aggregate_title(title: str, text: str = "") -> bool:
    blob = clean_text(f"{title} {text}").lower()
    if "#" in title:
        return True
    if any(w.lower() in blob for w in AGGREGATE_WORDS):
        return True
    if re.search(r"20\d{2}\s*년\s*\d{1,2}\s*월", title) and any(w in title for w in ["팝업", "전시", "놀거리", "추천"]):
        if not any(mark in title for mark in [":", "：", "〈", "《", " x ", " X ", "IN ", "POP UP"]):
            return True
    return False


def looks_like_experience(text: str) -> bool:
    lower = clean_text(text).lower()
    return any(w.lower() in lower for w in EXPERIENCE_WORDS)


def clean_title(title: str) -> str:
    t = clean_text(title).replace("_", " ")
    t = re.sub(r"\s*(?:방문\s*)?후기.*$", "", t)
    t = re.sub(r"\s*(추천|가볼\s*만한|가볼만한).*$", "", t)
    t = re.sub(r"예정\s*서울\s*전시", " ", t)
    t = re.sub(r"서울\s*전시", " ", t)
    t = re.sub(r"\bALT\s*:\s*\d+\b", " ", t, flags=re.I)
    t = re.sub(r"\s*(?:20)?\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\s*[-~–—]\s*(?:20)?\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\s*$", "", t)
    t = re.sub(r"\s*(?:20)?\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\s*[-~–—]\s*\d{1,2}[.\-/]\d{1,2}\s*$", "", t)
    t = re.sub(r"\s*\d{1,2}[.\-/]\d{1,2}\s*[-~–—]\s*\d{1,2}[.\-/]\d{1,2}\s*$", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -_·|")
    return t or clean_text(title)


def guess_area(text: str) -> str:
    for area in AREA_WORDS:
        if area in text:
            return area
    if "서소문" in text:
        return "중구"
    if "DDP" in text or "동대문" in text:
        return "동대문"
    return "서울/수도권"


def guess_venue(text: str) -> str:
    for venue in VENUE_HINTS:
        if venue in text:
            return venue
    return guess_area(text)


def key(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", clean_text(text).lower())


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, key(a), key(b)).ratio()


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=KST)
    except Exception:
        return None


def is_current_or_week_event(event: dict[str, Any], now_dt: datetime | None = None) -> bool:
    now_dt = now_dt or datetime.now(KST)
    today = now_dt.date()
    start = parse_date(event.get("start", ""))
    end = parse_date(event.get("end", ""))

    if end and end.date() < today:
        return False
    if start and start.date() > today + timedelta(days=7):
        return False
    if is_bad_card_url(event.get("officialUrl") or event.get("sourceUrl", "")):
        return False
    if is_aggregate_title(event.get("title", ""), event.get("summary", "")):
        return False
    return True


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] failed to load {path}: {e}")
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scan_official_candidates(sources: list[dict[str, Any]]) -> tuple[list[RawCandidate], list[dict[str, Any]]]:
    out: list[RawCandidate] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for source in sources:
        name = source.get("name", "source")
        url = source.get("url", "")
        source_type = source.get("type", "event")
        weight = int(source.get("weight", 18))
        print(f"[INFO] scanning official source: {name}")
        raw = safe_fetch(url)
        if not raw:
            continue

        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        for a in soup.find_all("a", href=True)[:260]:
            title = clean_text(a.get_text(" ", strip=True))
            if not title or len(title) < 3 or len(title) > 120:
                continue
            parent_text = clean_text(a.find_parent().get_text(" ", strip=True) if a.find_parent() else title)
            link = urllib.parse.urljoin(url, a.get("href") or "")
            blob = clean_text(f"{title} {parent_text}")

            if not looks_like_experience(blob):
                continue
            if is_aggregate_title(title, blob):
                rejected.append({"title": title, "url": link, "sourceName": name, "reason": "aggregate/listing/review-like title"})
                continue
            if is_bad_card_url(link):
                rejected.append({"title": title, "url": link, "sourceName": name, "reason": "review/search URL"})
                continue

            k = key(f"{title} {link}")
            if k in seen:
                continue
            seen.add(k)

            start, end = extract_period_from_text(blob)
            out.append(RawCandidate(
                sourceName=name,
                sourceType=source_type,
                title=clean_title(title),
                text=blob[:800],
                url=link,
                weight=weight,
                start=start,
                end=end,
                venue=guess_venue(blob),
                area=guess_area(blob),
            ))

    print(f"[INFO] official raw candidates: {len(out)} rejected_pre: {len(rejected)}")
    return out, rejected


def local_candidate_judgement(candidates: list[RawCandidate]) -> tuple[list[InventoryEvent], list[dict[str, Any]]]:
    events: list[InventoryEvent] = []
    rejected: list[dict[str, Any]] = []
    for c in candidates:
        if is_aggregate_title(c.title, c.text) or is_bad_card_url(c.url):
            rejected.append({**asdict(c), "reason": "local reject aggregate/search"})
            continue
        category = "popup_brand" if c.sourceType == "popup" or "팝업" in c.text or "스토어" in c.text else "exhibition_culture"
        summary = f"{c.venue or c.area}에서 진행되는 {'팝업/브랜드 경험' if category == 'popup_brand' else '전시/문화 경험'} 후보."
        events.append(InventoryEvent(
            title=clean_title(c.title),
            venue=c.venue,
            area=c.area,
            region=c.area,
            category=category,
            start=c.start,
            end=c.end,
            officialUrl=c.url,
            sourceName=c.sourceName,
            summary=summary,
            notes="local fallback judgement",
            lastSeen=datetime.now(KST).isoformat(timespec="seconds"),
            seed=False,
        ))
    return events, rejected


def gemini_candidate_judgement(candidates: list[RawCandidate]) -> tuple[list[InventoryEvent], list[dict[str, Any]]]:
    if not GEMINI_API_KEY:
        print("[INFO] GEMINI_API_KEY missing: using local judgement")
        return local_candidate_judgement(candidates)

    accepted: list[InventoryEvent] = []
    rejected: list[dict[str, Any]] = []
    now = datetime.now(KST).isoformat(timespec="seconds")

    for start_idx in range(0, len(candidates), 50):
        chunk = candidates[start_idx:start_idx + 50]
        brief = [
            {
                "i": i,
                "sourceName": c.sourceName,
                "sourceType": c.sourceType,
                "title": c.title,
                "text": c.text[:350],
                "url": c.url,
                "start": c.start,
                "end": c.end,
                "venue": c.venue,
                "area": c.area,
            }
            for i, c in enumerate(chunk)
        ]
        prompt = f"""너는 NOIZ!의 주간 팝업/전시 큐레이터다.
아래 후보들을 보고, 실제 카드로 올릴 수 있는 단일 팝업/전시/브랜드 공간 경험인지 판정해라.

KEEP 조건:
- 단일한 실제 이벤트/전시/팝업/브랜드 공간이어야 한다.
- 공식 페이지 또는 정보 페이지 후보여야 한다.
- 제목이 구체적이어야 한다.
- 현재 진행 중이거나 7일 이내 시작하는 후보는 허용한다.
- 날짜가 불명확해도 단일 이벤트성이 강하면 keep 가능.

REJECT 조건:
- 총정리, 추천, 놀거리, 모음, 리스트, 후기 글, 뉴스 기사 제목, 검색 결과 제목
- blog.naver.com / news.google.com 같은 후기/검색/뉴스 URL
- 여러 팝업을 모아놓은 페이지
- 구체적인 단일 이벤트 이름이 없는 페이지

출력은 JSON만:
{{
  "items": [
    {{
      "i": 0,
      "keep": true,
      "title": "정리된 공식 이벤트명",
      "venue": "장소",
      "area": "지역",
      "category": "popup_brand | exhibition_culture | space_experience",
      "start": "YYYY-MM-DD 또는 빈 문자열",
      "end": "YYYY-MM-DD 또는 빈 문자열",
      "summary": "현장에서 어떤 경험을 제공하는지 설명하는 한 문장",
      "reason": "판정 이유"
    }}
  ]
}}

후보:
{json.dumps(brief, ensure_ascii=False)}
"""
        try:
            parsed = ask_gemini(prompt, max_tokens=8192, temperature=0.1)
            rows = parsed.get("items", []) if isinstance(parsed, dict) else []
        except Exception as e:
            print(f"[WARN] Gemini judgement failed at chunk {start_idx}: {e}")
            local_events, local_rejected = local_candidate_judgement(chunk)
            accepted.extend(local_events)
            rejected.extend(local_rejected)
            continue

        row_by_i = {}
        for row in rows:
            if isinstance(row, dict):
                try:
                    row_by_i[int(row.get("i"))] = row
                except Exception:
                    pass

        for i, c in enumerate(chunk):
            row = row_by_i.get(i)
            if not row or not row.get("keep"):
                rejected.append({**asdict(c), "reason": row.get("reason", "Gemini reject") if isinstance(row, dict) else "Gemini omitted"})
                continue
            if is_bad_card_url(c.url) or is_aggregate_title(row.get("title", c.title), c.text):
                rejected.append({**asdict(c), "reason": "post-Gemini validation reject"})
                continue

            accepted.append(InventoryEvent(
                title=clean_title(row.get("title") or c.title),
                venue=clean_text(row.get("venue") or c.venue),
                area=clean_text(row.get("area") or c.area),
                region=clean_text(row.get("area") or c.area),
                category=clean_text(row.get("category") or ("popup_brand if popup else exhibition_culture")),
                start=clean_text(row.get("start") or c.start),
                end=clean_text(row.get("end") or c.end),
                officialUrl=c.url,
                sourceName=c.sourceName,
                summary=clean_text(row.get("summary") or f"{c.venue or c.area}에서 진행되는 공간 경험 후보."),
                notes=clean_text(row.get("reason", "")),
                lastSeen=now,
                seed=False,
            ))

    print(f"[INFO] Gemini candidate judgement accepted={len(accepted)} rejected={len(rejected)}")
    return accepted, rejected


def merge_inventory(existing: list[dict[str, Any]], fresh: list[InventoryEvent], *, now_dt: datetime) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}

    for item in existing:
        if not isinstance(item, dict):
            continue
        title = clean_title(item.get("title", ""))
        if not title:
            continue
        item = dict(item)
        item["title"] = title
        by_key[key(title)] = item

    for event in fresh:
        item = asdict(event)
        k = key(item["title"])
        old = by_key.get(k, {})
        merged = {**old, **{kk: vv for kk, vv in item.items() if vv not in ("", None, [])}}
        merged["lastSeen"] = event.lastSeen or now_dt.isoformat(timespec="seconds")
        by_key[k] = merged

    # remove ended events from inventory only after a grace period
    out = []
    for item in by_key.values():
        end = parse_date(item.get("end", ""))
        if end and end.date() < (now_dt.date() - timedelta(days=14)):
            continue
        out.append(item)
    out.sort(key=lambda x: (x.get("end", "9999-12-31"), x.get("title", "")))
    return out


def google_news_hits(query: str) -> list[str]:
    q = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    raw = safe_fetch(url, timeout=12)
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
        return [clean_text(item.findtext("title") or "") for item in root.findall(".//item")[:8]]
    except Exception:
        return []


def signal_text_for_event(event: dict[str, Any], hits: list[str]) -> str:
    return " ".join([
        event.get("title", ""),
        event.get("venue", ""),
        event.get("area", ""),
        event.get("category", ""),
        event.get("summary", ""),
        " ".join(hits),
    ])


def score_event(event: dict[str, Any], hits: list[str]) -> tuple[int, int, list[str], int, int]:
    text = signal_text_for_event(event, hits)
    category = event.get("category", "")
    evidence_count = 1 + len(hits)
    reaction_count = len([h for h in hits if any(w in h for w in ["후기", "방문", "추천", "오픈", "인기", "화제"])])

    score = 52
    if category == "popup_brand":
        score += 10
    elif category == "exhibition_culture":
        score += 5
    if event.get("seed"):
        score += 4
    score += min(22, evidence_count * 4)
    score += min(18, reaction_count * 5)

    hot_words = ["T1", "페이커", "굿즈", "한정", "무료", "더현대", "성수", "예약", "팬덤", "콜라보", "비치클럽", "회고전", "미술관"]
    score += min(12, sum(2 for word in hot_words if word.lower() in text.lower()))
    score = max(45, min(99, score))

    favor = 68 + min(18, sum(2 for word in ["무료", "굿즈", "예약", "팬덤", "미술관", "회고전", "성수"] if word in text))
    favor = max(55, min(92, favor))

    signals = ["공식/정보 출처"]
    if reaction_count:
        signals.append("후기/뉴스 반응")
    if "무료" in text:
        signals.append("무료/체험")
    if any(w in text for w in ["굿즈", "한정", "팬덤", "T1", "페이커"]):
        signals.append("팬덤/굿즈")
    if any(w in text for w in ["웨이팅", "혼잡", "대기"]):
        signals.append("웨이팅 가능성")
    if len(signals) < 2:
        signals.append("공간 경험")

    return score, favor, signals[:4], evidence_count, reaction_count


def local_summary(event: dict[str, Any]) -> str:
    title = event.get("title", "")
    venue = event.get("venue", "")
    area = event.get("area", "") or event.get("region", "")
    cat = event.get("category", "")
    if cat == "exhibition_culture":
        if venue:
            return f"{venue}에서 열리는 전시/문화 경험으로, 작품·공간 구성과 관람 동선을 함께 확인할 만해."
        return f"{title}은 {area or '서울/수도권'}권에서 열리는 전시/문화 경험으로, 주제와 관람 목적성이 분명한 후보야."
    if venue:
        return f"{venue}에서 진행 중인 팝업/브랜드 경험으로, 브랜드 연출과 현장 반응을 벤치마크할 만해."
    return f"{title}은 {area or '서울/수도권'}권에서 포착된 공간 경험으로, 현장 구성과 방문 반응을 함께 확인할 만해."


def make_card(event: dict[str, Any], rank: int, hits: list[str]) -> dict[str, Any]:
    noiz, favor, signals, evidence_count, reaction_count = score_event(event, hits)
    return {
        "rank": rank,
        "brand": event.get("sourceName", ""),
        "title": event.get("title", ""),
        "owner": event.get("summary") or local_summary(event),
        "venue": event.get("venue", ""),
        "area": event.get("area", "") or event.get("region", ""),
        "region": event.get("region", "") or event.get("area", ""),
        "mapQuery": " ".join([event.get("title", ""), event.get("venue", ""), event.get("area", "")]).strip(),
        "sourceUrl": event.get("officialUrl", ""),
        "sourceLabel": "공식/정보 출처",
        "noiz": noiz,
        "favorability": favor,
        "description": event.get("summary") or local_summary(event),
        "signals": signals,
        "category": event.get("category", ""),
        "start": event.get("start", ""),
        "end": event.get("end", ""),
        "evidenceCount": evidence_count,
        "reactionCount": reaction_count,
        "confidence": "high" if evidence_count >= 4 else "medium",
        "seedFallback": bool(event.get("seed")),
    }


def current_inventory_items(inventory: list[dict[str, Any]], now_dt: datetime) -> list[dict[str, Any]]:
    items = [item for item in inventory if is_current_or_week_event(item, now_dt=now_dt)]
    seen = set()
    out = []
    for item in items:
        k = key(item.get("title", ""))
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out



def seed_inventory_items(now_dt: datetime) -> list[dict[str, Any]]:
    """Load stable manually curated events as a hard safety net for dev automation."""
    seed_payload = load_json(CURATION_SEED_PATH, {"items": []})
    seed_items = []
    for item in seed_payload.get("items", []):
        if not isinstance(item, dict):
            continue
        copy = dict(item)
        copy["seed"] = True
        copy.setdefault("lastSeen", now_dt.isoformat(timespec="seconds"))
        if is_current_or_week_event(copy, now_dt=now_dt):
            seed_items.append(copy)
    return seed_items


def ensure_minimum_inventory(active_events: list[dict[str, Any]], now_dt: datetime, *, min_count: int = 8) -> tuple[list[dict[str, Any]], list[str]]:
    """Fill active inventory from curated seed if Gemini/live crawl is too sparse."""
    warnings: list[str] = []
    out = list(active_events)
    seen = {key(item.get("title", "")) for item in out}

    if len(out) >= min_count:
        return out, warnings

    seed_items = seed_inventory_items(now_dt)
    for item in seed_items:
        k = key(item.get("title", ""))
        if not k or k in seen:
            continue
        out.append(item)
        seen.add(k)
        if len(out) >= 10:
            break

    if len(active_events) < min_count:
        warnings.append(
            f"Active live inventory was sparse ({len(active_events)}). "
            f"Filled to {len(out)} with curated seed fallback."
        )

    return out, warnings


def gemini_final_curation(cards: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None, list[str]]:
    warnings = []
    if not GEMINI_API_KEY or not cards:
        return cards, None, warnings

    brief = [
        {
            "rank": c.get("rank"),
            "title": c.get("title"),
            "venue": c.get("venue"),
            "area": c.get("area"),
            "period": {"start": c.get("start", ""), "end": c.get("end", "")},
            "category": c.get("category"),
            "noiz": c.get("noiz"),
            "signals": c.get("signals", []),
            "summary": c.get("description"),
        }
        for c in cards[:20]
    ]
    prompt = f"""너는 NOIZ!의 최종 편집자다.
아래 후보는 이미 단일 이벤트/공식 링크/현재 진행 기준으로 검증된 후보들이다.
Top 10 순서와 설명을 다듬어라.

절대 하지 말 것:
- 새 후보를 만들지 마라.
- title, URL, start/end는 바꾸지 마라.
- 후기글/총정리글을 추가하지 마라.

출력 JSON:
{{
  "weekly_read": "이번 주 흐름을 2~3문장으로 요약",
  "items": [
    {{"title": "입력 후보와 정확히 같은 title", "rank": 1, "description": "현장 경험 중심 한 문장"}}
  ]
}}

후보:
{json.dumps(brief, ensure_ascii=False)}
"""
    try:
        parsed = ask_gemini(prompt, max_tokens=4096, temperature=0.2)
    except Exception as e:
        warnings.append(f"Gemini final curation failed: {e}")
        return cards, None, warnings

    rows = parsed.get("items", []) if isinstance(parsed, dict) else []
    by_title = {c["title"]: dict(c) for c in cards}
    curated = []
    used = set()

    for row in rows:
        if not isinstance(row, dict):
            continue
        title = clean_text(row.get("title", ""))
        if title not in by_title or title in used:
            continue
        item = by_title[title]
        desc = clean_text(row.get("description", ""))
        if desc and not any(w in desc for w in ["페이지입니다", "정보를 모아", "공개 노출", "후기성 신호"]):
            item["description"] = desc
            item["owner"] = desc
            item["aiDescription"] = True
        curated.append(item)
        used.add(title)

    for item in cards:
        if item["title"] not in used:
            curated.append(item)
    curated = curated[:10]
    for idx, item in enumerate(curated, 1):
        item["rank"] = idx

    weekly_read = clean_text(parsed.get("weekly_read", "")) if isinstance(parsed, dict) else ""
    return curated, weekly_read or None, warnings


def make_weekly_read(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return "이번 주는 아직 검증된 공간 신호가 충분히 잡히지 않았어. 후보 검수 후 다시 발행할게."
    popup = sum(1 for c in cards if c.get("category") == "popup_brand")
    art = sum(1 for c in cards if c.get("category") == "exhibition_culture")
    top = cards[0].get("title", "상위 후보")
    areas = []
    for c in cards:
        area = c.get("area") or c.get("region")
        if area and area not in areas:
            areas.append(area)
    return (
        f"이번 주 NOIZ는 {'·'.join(areas[:3]) or '서울/수도권'} 중심으로 잡혔어. "
        f"Top 10에는 팝업/브랜드 경험 {popup}개, 전시/문화 경험 {art}개가 섞여 있고, 가장 강한 신호는 {top} 쪽이야. "
        "이번 주는 짧고 인증하기 좋은 팝업과 검증된 기관 전시가 같은 주말 시간을 두고 경쟁하는 흐름이야."
    )


def archive_payload(existing: dict[str, Any], now_dt: datetime) -> None:
    if not existing or now_dt.weekday() != 0:
        return
    try:
        date_label = existing.get("updated_at", now_dt.isoformat())[:10]
        if date_label == now_dt.date().isoformat():
            return
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archive_path = ARCHIVE_DIR / f"noiz-week-{date_label}.json"
        if not archive_path.exists():
            save_json(archive_path, existing)

        index = load_json(ARCHIVE_INDEX_PATH, {"items": []})
        if not any(row.get("date") == date_label for row in index.get("items", [])):
            index.setdefault("items", []).append({
                "date": date_label,
                "label": f"{date_label}",
                "path": f"data/archive/noiz-week-{date_label}.json",
            })
            index["items"] = index["items"][-52:]
            save_json(ARCHIVE_INDEX_PATH, index)
    except Exception as e:
        print(f"[WARN] archive failed: {e}")


def main() -> None:
    now_dt = datetime.now(KST)
    existing_payload = load_json(DATA_PATH, {})
    archive_payload(existing_payload, now_dt)

    sources = load_json(SOURCES_PATH, [])
    inventory_payload = load_json(INVENTORY_PATH, {"items": []})

    raw_candidates, pre_rejected = scan_official_candidates(sources)
    fresh_events, judged_rejected = gemini_candidate_judgement(raw_candidates)

    inventory_items = merge_inventory(inventory_payload.get("items", []), fresh_events, now_dt=now_dt)
    save_json(INVENTORY_PATH, {
        "site": "NOIZ",
        "updated_at": now_dt.isoformat(timespec="seconds"),
        "mode": "inventory",
        "items": inventory_items,
    })

    active_events = current_inventory_items(inventory_items, now_dt)
    draft_warnings = []
    active_events, seed_warnings = ensure_minimum_inventory(active_events, now_dt, min_count=8)
    draft_warnings.extend(seed_warnings)

    if len(active_events) < 8:
        draft_warnings.append(f"Only {len(active_events)} active inventory events passed validation after seed fallback.")

    pre_cards = []
    for event in active_events:
        hits = google_news_hits(" ".join([event.get("title", ""), event.get("venue", "")]).strip())
        pre_cards.append(make_card(event, 0, hits))
        time.sleep(0.25)

    pre_cards.sort(key=lambda x: int(x.get("noiz", 0)), reverse=True)
    pre_cards = pre_cards[:20]
    for idx, card in enumerate(pre_cards, 1):
        card["rank"] = idx

    cards, ai_weekly_read, curation_warnings = gemini_final_curation(pre_cards)
    draft_warnings.extend(curation_warnings)

    # final hard validation
    cards = [c for c in cards if not is_bad_card_url(c.get("sourceUrl", "")) and not is_aggregate_title(c.get("title", ""), c.get("description", ""))]
    cards = cards[:10]
    for idx, card in enumerate(cards, 1):
        card["rank"] = idx

    should_publish = len(cards) >= 8
    review_payload = {
        "site": "NOIZ",
        "updated_at": now_dt.isoformat(timespec="seconds"),
        "published": should_publish,
        "active_inventory_count": len(active_events),
        "candidate_count": len(raw_candidates),
        "fresh_accepted_count": len(fresh_events),
        "final_card_count": len(cards),
        "seed_fallback_available": CURATION_SEED_PATH.exists(),
        "warnings": draft_warnings,
        "rejected_examples": (pre_rejected + judged_rejected)[:40],
        "items": cards,
    }
    save_json(DRAFT_REVIEW_PATH, review_payload)

    if not should_publish:
        print(f"[WARN] final cards too few ({len(cards)}). Keeping existing data/noiz-data.json; draft written.")
        return

    payload = {
        "site": "NOIZ",
        "updated_at": now_dt.isoformat(timespec="seconds"),
        "theme": existing_payload.get("theme") or THEME_DEFAULT,
        "weekly_read": ai_weekly_read or make_weekly_read(cards),
        "items": cards,
        "creator": "이원준 시니어매니저",
        "method_note": "Gemini 큐레이터 dev 버전. 공식/정보 후보를 Gemini가 단일 이벤트로 판정하고, 검색·뉴스 신호는 반응 근거로만 붙인 뒤 검증 통과 시 발행한다.",
    }
    save_json(DATA_PATH, payload)
    print(f"[OK] published data/noiz-data.json with {len(cards)} curated items")


if __name__ == "__main__":
    main()
