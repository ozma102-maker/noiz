#!/usr/bin/env python3
"""
NOIZ daily updater.

무료 MVP용 규칙 기반 수집기.
- 지정된 전시/팝업 정보 페이지를 가져온다.
- 링크 텍스트와 본문에서 후보를 만든다.
- NOIZ 점수는 출처 가중치, 키워드, 예약/웨이팅/종료임박 신호로 계산한다.
- 충분한 후보가 없으면 data/noiz-data.json의 기존 데이터를 fallback으로 사용한다.

정확한 리뷰 수/감정 분석이 필요한 버전은 검색 API 또는 AI API를 추가해야 한다.
"""

from __future__ import annotations

import json
import re
import hashlib
import html
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, quote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "noiz-data.json"
SOURCES_PATH = ROOT / "scripts" / "sources.json"
KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NOIZBot/1.0; +https://github.com/)",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

POSITIVE_WORDS = [
    "인기", "추천", "핫", "화제", "예약", "사전예약", "매진", "굿즈", "무료",
    "포토존", "체험", "한정", "오픈런", "팝업", "전시", "도슨트", "이벤트"
]
NEGATIVE_WORDS = [
    "웨이팅", "혼잡", "줄", "품절", "비싸", "아쉽", "실망", "상업적", "마감",
    "종료", "혼선", "예약필수"
]
NOISE_WORDS = [
    "팝업", "전시", "성수", "더현대", "예약", "웨이팅", "굿즈", "체험", "한정",
    "오픈", "종료", "추천", "무료", "포토존", "브랜드"
]

@dataclass
class Candidate:
    brand: str
    title: str
    owner: str
    venue: str
    area: str
    region: str
    mapQuery: str
    sourceUrl: str
    sourceLabel: str
    noiz: int
    favorability: int
    description: str
    signals: list[str]

def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def fetch(url: str) -> str:
    res = requests.get(url, headers=HEADERS, timeout=20)
    res.raise_for_status()
    if not res.encoding:
        res.encoding = "utf-8"
    return res.text

def text_score(text: str, base: int) -> tuple[int, int, list[str]]:
    t = text.lower()
    pos = sum(1 for w in POSITIVE_WORDS if w.lower() in t)
    neg = sum(1 for w in NEGATIVE_WORDS if w.lower() in t)
    noise = sum(1 for w in NOISE_WORDS if w.lower() in t)
    score = base + min(45, noise * 6) + min(18, pos * 3) + min(12, neg * 2)
    score = max(40, min(99, score))
    favor = 70 + min(18, pos * 3) - min(20, neg * 4)
    favor = max(45, min(90, favor))

    signals = []
    if pos:
        signals.append("긍정 키워드")
    if neg:
        signals.append("혼잡/피로 신호")
    if "예약" in text:
        signals.append("예약 신호")
    if "웨이팅" in text or "줄" in text:
        signals.append("웨이팅 가능성")
    if "무료" in text:
        signals.append("무료/체험")
    if not signals:
        signals.append("공개 노출")
    return score, favor, signals[:3]

def guess_area(text: str) -> str:
    areas = ["성수", "여의도", "한남", "삼청", "청담", "을지로", "중구", "종로", "서촌", "용산", "강남", "홍대", "잠실"]
    for a in areas:
        if a in text:
            return a
    return "서울/수도권"

def make_description(title: str, text: str, source_type: str) -> str:
    if source_type == "popup":
        return f"{title} 관련 공개 노출과 예약/굿즈/체험 신호를 기준으로 잡힌 팝업 후보. 방문 전 운영 기간과 예약 여부를 확인하는 편이 좋다."
    return f"{title} 관련 공개 전시 정보와 플랫폼 노출을 기준으로 잡힌 전시 후보. 관람 전 공식 페이지에서 기간과 장소를 확인하는 편이 좋다."

def load_existing() -> dict[str, Any]:
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return {"items": []}

def candidate_key(title: str, venue: str) -> str:
    base = re.sub(r"[^0-9A-Za-z가-힣]+", "", (title + venue).lower())
    return hashlib.md5(base.encode("utf-8")).hexdigest()

def extract_candidates_from_source(source: dict[str, Any]) -> list[Candidate]:
    url = source["url"]
    source_type = source.get("type", "event")
    base = int(source.get("weight", 15))
    out: list[Candidate] = []

    try:
        raw = fetch(url)
    except Exception as e:
        print(f"[WARN] fetch failed: {url}: {e}")
        return out

    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    links = soup.find_all("a")
    seen = set()

    for a in links:
        text = clean_text(a.get_text(" ", strip=True))
        href = a.get("href") or ""
        if len(text) < 6 or len(text) > 120:
            continue
        if not any(w in text for w in NOISE_WORDS + ["전시회", "개인전", "기획전"]):
            continue

        link = urljoin(url, href)
        title = text
        venue = source["name"]
        area = guess_area(text + " " + url)
        key = candidate_key(title, venue)
        if key in seen:
            continue
        seen.add(key)

        noiz, favor, signals = text_score(text + " " + source["name"], base)
        out.append(Candidate(
            brand=source["name"],
            title=title[:70],
            owner=f"{source['name']}에서 확인된 {'팝업' if source_type == 'popup' else '전시'} 후보",
            venue=venue,
            area=area,
            region=area,
            mapQuery=f"{venue} {area}",
            sourceUrl=link,
            sourceLabel="정보 출처",
            noiz=noiz,
            favorability=favor,
            description=make_description(title[:70], text, source_type),
            signals=signals,
        ))

    return out

def merge_and_rank(candidates: list[Candidate], existing_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}

    for c in candidates:
        item = asdict(c)
        k = candidate_key(item["title"], item["venue"])
        if k not in by_key or item["noiz"] > by_key[k]["noiz"]:
            by_key[k] = item

    # 기존 데이터는 fallback으로 사용하되, 새 후보가 부족할 때만 채움.
    for old in existing_items:
        k = candidate_key(old.get("title", ""), old.get("venue", ""))
        if k not in by_key:
            by_key[k] = old

    ranked = sorted(by_key.values(), key=lambda x: int(x.get("noiz", 0)), reverse=True)[:10]
    for i, item in enumerate(ranked, 1):
        item["rank"] = i
    return ranked

def make_weekly_read(items: list[dict[str, Any]]) -> str:
    if not items:
        return "이번 주 공개 검색에서 충분한 후보를 찾지 못했다."
    top_areas = {}
    for item in items[:5]:
        area = item.get("area", "서울/수도권")
        top_areas[area] = top_areas.get(area, 0) + 1
    area_line = "·".join(sorted(top_areas, key=top_areas.get, reverse=True)[:3])
    top = items[0]
    return f"이번 주 NOIZ 상위권은 {area_line} 중심으로 잡힌다. 1위는 {top.get('title')}이며, 공개 노출·예약/후기성 신호를 기준으로 가장 높은 화제성을 보인다."

def main() -> None:
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    existing = load_existing()
    candidates: list[Candidate] = []

    for source in sources:
        print(f"[INFO] scanning {source['name']}")
        candidates.extend(extract_candidates_from_source(source))

    items = merge_and_rank(candidates, existing.get("items", []))
    payload = {
        "site": "NOIZ",
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "weekly_read": make_weekly_read(items),
        "items": items,
        "creator": "이원준 시니어매니저",
        "method_note": "GitHub Actions가 공개 전시/팝업 정보 페이지를 확인해 갱신한 NOIZ 데이터."
    }

    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] wrote {DATA_PATH} with {len(items)} items")

if __name__ == "__main__":
    main()
