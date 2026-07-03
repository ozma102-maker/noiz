#!/usr/bin/env python3
"""
ART NOIZ updater

이 스크립트는 Art Week Korea expanded HTML에서 추출한
전시 후보(candidates)와 서울·수도권 공간 watchlist(venues)를 기반으로
히든 art.html 페이지용 data/art-noiz-data.json을 갱신한다.

적용 원칙
- 미술관/갤러리/대안공간/아트 플랫폼 중심
- 브랜드 팝업/굿즈 팝업 단독 후보 제외
- 공식 홈페이지 우선, ARTMAP/서울아트가이드/네오룩/Ocula/Frieze/리뷰 검색은 교차 확인 레이어
- 무료 MVP라서 네이버 플레이스 리뷰/인스타 댓글 전체 수집은 하지 않음
"""

from __future__ import annotations

import hashlib
import html
import json
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "art-noiz-data.json"
SEED_PATH = ROOT / "data" / "art-week-seed.json"
KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NOIZArtBot/1.0; hidden-art-radar)",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
}

ART_SEARCH_QUERIES = [
    "서울 미술 전시 후기",
    "서울 미술관 전시 후기",
    "서울 갤러리 전시 후기",
    "서울 개인전 후기",
    "서울 기획전 후기",
    "서울 현대미술 전시 후기",
    "서울 전시 관람 후기",
    "삼청 갤러리 전시 후기",
    "한남 갤러리 전시 후기",
    "청담 갤러리 전시 후기",
    "을지로 갤러리 전시 후기",
    "국립현대미술관 전시 후기",
    "서울시립미술관 전시 후기",
    "아트선재 전시 후기",
    "리움미술관 전시 후기",
    "송은 전시 후기",
    "국제갤러리 전시 후기",
    "PKM 전시 후기",
    "Ocula Seoul exhibitions",
    "ARTMAP 서울 전시",
    "네오룩 서울 전시",
    "서울아트가이드 전시",
]

ART_WORDS = [
    "전시", "전시회", "개인전", "기획전", "미술", "미술관", "갤러리",
    "작가", "회화", "조각", "설치", "사진", "영상", "현대미술",
    "관람", "도슨트", "오프닝", "아트", "아트맵", "네오룩", "서울아트가이드",
    "국립현대미술관", "서울시립미술관", "리움", "송은", "국제갤러리",
    "PKM", "페로탕", "삼청", "한남", "청담", "을지로",
    "exhibition", "artist", "gallery", "museum", "art"
]

POSITIVE_WORDS = [
    "좋", "좋았", "만족", "추천", "강추", "볼만", "알차", "감각", "퀄리티",
    "중요", "주요", "거장", "도슨트", "몰입", "새롭", "풍성", "인상적"
]
NEGATIVE_WORDS = ["아쉽", "실망", "별로", "비추", "비싸", "혼잡", "웨이팅", "줄", "대기", "불편", "복잡"]
BAD_WORDS = ["로그인", "회원가입", "개인정보", "이용약관", "전체보기", "더보기"]
POPUP_ONLY_WORDS = ["팝업스토어", "브랜드 팝업", "굿즈 팝업"]

KNOWN_AREAS = ["삼청", "한남", "청담", "성수", "을지로", "서촌", "종로", "중구", "강남", "용산", "송파", "여의도", "서초", "인천", "경기", "수원", "파주"]

VENUE_KO = {
    "MMCA Seoul": "국립현대미술관 서울",
    "National Museum of Modern and Contemporary Art, Seoul": "국립현대미술관 서울",
    "Seoul Museum of Art, Seosomun": "서울시립미술관 서소문본관",
    "Seoul Museum of Art, Buk-Seoul": "서울시립 북서울미술관",
    "Seoul Museum of Art": "서울시립미술관",
    "Leeum Museum of Art": "리움미술관",
    "Amorepacific Museum of Art": "아모레퍼시픽미술관",
    "Art Sonje Center": "아트선재센터",
    "SONGEUN Art and Cultural Foundation": "송은",
    "SOMA Museum of Art": "소마미술관",
    "The Hyundai Seoul ALT.1": "더현대 서울 ALT.1",
    "Centre Pompidou Hanwha": "퐁피두센터 한화 서울",
    "Suwon Museum of Art": "수원시립미술관",
    "Kukje Gallery": "국제갤러리",
    "Kukje Gallery K1/K2": "국제갤러리 K1/K2",
    "Kukje Gallery Seoul Hanok": "국제갤러리 서울 한옥",
    "Gallery Hyundai": "갤러리현대",
    "PKM Gallery": "PKM 갤러리",
    "Arario Gallery Seoul": "아라리오갤러리 서울",
    "Gallery Baton": "갤러리바톤",
    "The Page Gallery": "더페이지갤러리",
    "CAPTION Seoul": "캡션 서울",
    "G Gallery": "G갤러리",
    "WWNN": "WWNN",
    "OMG SEOUL": "OMG 서울",
    "Space ISU": "스페이스 이수",
}

AREA_KO = {
    "Samcheong": "삼청",
    "Samcheong/Jongno": "삼청/종로",
    "Jongno": "종로",
    "Jongno-gu": "종로",
    "Jung-gu": "중구",
    "Nowon": "노원",
    "Nowon-gu": "노원",
    "Seoul": "서울",
    "Hannam": "한남",
    "Yongsan": "용산",
    "Cheongdam": "청담",
    "Seochon": "서촌",
    "Seongsu": "성수",
    "Gangnam": "강남",
    "Songpa": "송파",
    "Yeouido": "여의도",
    "Seocho": "서초",
    "Gwanghwamun": "광화문",
    "Pyeongchang": "평창동",
    "Eunpyeong": "은평",
    "Apgujeong": "압구정",
    "Daehak-ro": "대학로",
    "Anguk": "안국",
    "Nanji": "난지",
    "Dobong": "도봉",
    "Gwanak": "관악",
    "Itaewon": "이태원",
    "Seongbuk": "성북",
    "Sinsa": "신사",
    "Gyeonggi": "경기",
    "Suwon": "수원",
    "Gwacheon": "과천",
    "Yongin": "용인",
    "Ansan": "안산",
    "Paju": "파주",
    "Incheon": "인천",
    "Yeongjong": "영종",
    "서울/수도권": "서울/수도권",
}

CITY_KO = {
    "Seoul": "서울",
    "Gyeonggi": "경기",
    "Incheon": "인천",
}

def ko_venue(value: str) -> str:
    return VENUE_KO.get(value, value)

def ko_area(value: str) -> str:
    return AREA_KO.get(value, value)

def ko_city(value: str) -> str:
    return CITY_KO.get(value, value)


def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def normalize(text: str) -> str:
    text = (text or "").lower().normalize("NFKD") if hasattr(str, "normalize") else (text or "").lower()
    return re.sub(r"exhibition|solo|group|개인전|기획전|展|전시|《|》|〈|〉|<|>|:|：|\.|,|'|\"|\(|\)|\[|\]|\s+|the", "", text)

def candidate_key(title: str, venue: str = "") -> str:
    base = re.sub(r"[^0-9A-Za-z가-힣]+", "", (title + venue).lower())
    return hashlib.md5(base.encode("utf-8")).hexdigest()

def canonical_key(item: dict[str, Any]) -> str:
    return f"{candidate_key(item.get('title',''), item.get('venue',''))}"

def has_any(text: str, words: list[str]) -> bool:
    low = text.lower()
    return any(w.lower() in low for w in words)

def looks_like_art(text: str) -> bool:
    text = clean_text(text)
    if len(text) < 6 or len(text) > 260:
        return False
    if has_any(text, BAD_WORDS):
        return False
    popup_only = has_any(text, POPUP_ONLY_WORDS) and not has_any(text, ["미술", "갤러리", "미술관", "작가", "전시"])
    return has_any(text, ART_WORDS) and not popup_only

def safe_fetch(url: str, timeout: int = 14) -> str:
    try:
        time.sleep(random.uniform(0.12, 0.32))
        res = requests.get(url, headers=HEADERS, timeout=timeout)
        res.raise_for_status()
        if not res.encoding:
            res.encoding = "utf-8"
        return res.text
    except Exception as e:
        print(f"[WARN] fetch failed: {url}: {e}")
        return ""

def guess_area(text: str) -> str:
    for a in KNOWN_AREAS:
        if a in text:
            return a
    return "서울/수도권"

def score_item(raw: dict[str, Any], source_count: int = 1) -> tuple[int, int, list[str], str, int, str]:
    text = " ".join([
        str(raw.get("title","")),
        str(raw.get("artist","")),
        str(raw.get("venue","")),
        str(raw.get("note","")),
        " ".join(raw.get("tags", []) or []),
        " ".join(raw.get("sourceNames", []) or [raw.get("sourceName","")]),
    ])
    confidence = int(raw.get("confidence", 70) or 70)
    recommended = bool(raw.get("recommended"))
    needs_review = bool(raw.get("needsReview"))
    official = "official" in (raw.get("sourceKeys") or [raw.get("sourceKey", "")])

    pos = sum(1 for w in POSITIVE_WORDS if w in text)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text)

    noiz = 42 + min(28, round(confidence * 0.28))
    if recommended: noiz += 12
    if official: noiz += 8
    if source_count >= 2: noiz += min(12, source_count * 4)
    if raw.get("venueType") == "museum": noiz += 3
    noiz += min(8, pos * 2)
    noiz += min(5, neg)
    if needs_review: noiz -= 10
    noiz = max(50, min(99, noiz))

    favor = 58 + round(confidence * 0.22) + min(8, pos * 2) - min(10, neg * 3)
    if recommended: favor += 6
    if needs_review: favor -= 8
    favor = max(50, min(92, favor))

    info_volume = "medium" if confidence >= 70 or source_count >= 1 else "low"
    reaction_count = 1 if confidence >= 45 else 0
    confidence_label = "high" if confidence >= 88 else "medium" if confidence >= 70 else "low"

    signals = []
    if official: signals.append("공식 확인")
    if source_count >= 2: signals.append("교차 확인")
    if recommended: signals.append("추천/중요")
    if needs_review: signals.append("검토 필요")
    if raw.get("venueType") == "museum": signals.append("미술관")
    elif raw.get("venueType") == "gallery": signals.append("갤러리")
    elif raw.get("venueType") == "nonprofit": signals.append("대안공간")
    for tag in raw.get("tags", []) or []:
        if len(signals) >= 4: break
        if tag not in signals: signals.append(str(tag))
    if not signals:
        signals = ["미술 전시"]
    return noiz, favor, signals[:4], info_volume, reaction_count, confidence_label

def merge_seed_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for c in candidates:
        key = canonical_key(c)
        if key not in grouped:
            item = dict(c)
            item["sourceKeys"] = [c.get("sourceKey", "unknown")]
            item["sourceNames"] = [c.get("sourceName", "unknown")]
            item["sourceUrls"] = [{"name": c.get("sourceName","unknown"), "key": c.get("sourceKey","unknown"), "url": c.get("url","#")}]
            item["candidateIds"] = [c.get("id", key)]
            item["conflicts"] = []
            grouped[key] = item
        else:
            base = grouped[key]
            if c.get("sourceKey") not in base["sourceKeys"]:
                base["sourceKeys"].append(c.get("sourceKey","unknown"))
            if c.get("sourceName") not in base["sourceNames"]:
                base["sourceNames"].append(c.get("sourceName","unknown"))
            base["sourceUrls"].append({"name": c.get("sourceName","unknown"), "key": c.get("sourceKey","unknown"), "url": c.get("url","#")})
            base["candidateIds"].append(c.get("id", key))
            base["confidence"] = max(int(base.get("confidence",0) or 0), int(c.get("confidence",0) or 0))
            base["needsReview"] = bool(base.get("needsReview")) or bool(c.get("needsReview")) or c.get("start") != base.get("start") or c.get("end") != base.get("end")
            if c.get("start") != base.get("start") or c.get("end") != base.get("end"):
                base.setdefault("conflicts", []).append(f"Date conflict: {c.get('sourceName')} {c.get('start')}~{c.get('end')}")
            if (c.get("sourceKey") == "official" and base.get("sourceKey") != "official") or int(c.get("confidence",0) or 0) > int(base.get("confidence",0) or 0):
                keep = {k: base[k] for k in ["sourceKeys", "sourceNames", "sourceUrls", "candidateIds", "conflicts"]}
                keep["needsReview"] = base["needsReview"]
                new_base = dict(c)
                new_base.update(keep)
                grouped[key] = new_base
    return list(grouped.values())

def make_noiz_item(raw: dict[str, Any]) -> dict[str, Any]:
    source_count = len(raw.get("sourceKeys") or [raw.get("sourceKey", "unknown")])
    venue_ko = ko_venue(raw.get("venue") or "")
    area_ko = ko_area(raw.get("area") or raw.get("district") or "서울/수도권")
    region_ko = ko_city(raw.get("city") or "서울")
    noiz, favor, signals, info_volume, reaction_count, confidence_label = score_item(raw, source_count)
    return {
        "rank": 0,
        "brand": raw.get("artist") or "Group exhibition",
        "title": raw.get("title") or "Untitled",
        "owner": f"{venue_ko} · {', '.join(raw.get('sourceNames') or [raw.get('sourceName','')])}",
        "venue": venue_ko,
        "area": area_ko,
        "region": region_ko,
        "mapQuery": f"{raw.get('title','')} {venue_ko} {area_ko}",
        "sourceUrl": raw.get("url") or "#",
        "sourceLabel": "정보 출처",
        "noiz": noiz,
        "favorability": favor,
        "description": raw.get("note") or "미술관·갤러리·아트 플랫폼 기반 전시 후보입니다.",
        "signals": signals,
        "infoVolume": info_volume,
        "evidenceCount": max(1, source_count),
        "reactionCount": reaction_count,
        "confidence": confidence_label,
        "category": "art",
        "artist": raw.get("artist") or "",
        "start": raw.get("start") or "",
        "end": raw.get("end") or "",
        "venueType": raw.get("venueType") or "",
        "sourceKeys": raw.get("sourceKeys") or [raw.get("sourceKey", "unknown")],
    }

def active_or_currentish(raw: dict[str, Any], today: datetime) -> bool:
    try:
        start = datetime.fromisoformat(raw.get("start")).date()
        end = datetime.fromisoformat(raw.get("end")).date()
        d = today.date()
        return start <= d <= end
    except Exception:
        return True

def scan_venue_page(venue: list[Any]) -> list[dict[str, Any]]:
    name, vtype, city, district, website, instagram = venue
    if not website or website == "#":
        return []
    raw = safe_fetch(website)
    if not raw:
        return []
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    out = []
    for a in soup.find_all("a", href=True)[:120]:
        title = clean_text(a.get_text(" ", strip=True))
        parent = clean_text(a.find_parent().get_text(" ", strip=True) if a.find_parent() else title)
        text = f"{title} {parent} {name}"
        if not looks_like_art(text):
            continue
        out.append({
            "id": candidate_key(title, name),
            "title": title[:90],
            "artist": "TBC",
            "venue": ko_venue(name),
            "venueType": vtype,
            "city": ko_city(city),
            "district": ko_area(district),
            "area": ko_area(district),
            "start": datetime.now(KST).date().isoformat(),
            "end": (datetime.now(KST).date() + timedelta(days=45)).isoformat(),
            "tags": ["official-scan"],
            "recommended": False,
            "needsReview": True,
            "confidence": 55,
            "note": "공식 공간 페이지에서 자동 포착된 전시 후보. 날짜/작가명은 검토 필요.",
            "url": urljoin(website, a.get("href") or ""),
            "sourceKey": "official",
            "sourceName": f"{name} official scan",
        })
        if len(out) >= 4:
            break
    return out

def decode_ddg_link(href: str) -> str:
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    if "uddg" in qs:
        return unquote(qs["uddg"][0])
    return href

def search_duckduckgo(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    raw = safe_fetch(url)
    if not raw:
        return []
    soup = BeautifulSoup(raw, "lxml")
    out = []
    for block in soup.select(".result")[:max_results]:
        a = block.select_one(".result__a")
        if not a:
            continue
        title = clean_text(a.get_text(" ", strip=True))
        snippet_el = block.select_one(".result__snippet")
        snippet = clean_text(snippet_el.get_text(" ", strip=True) if snippet_el else block.get_text(" ", strip=True))
        if not looks_like_art(f"{title} {snippet}"):
            continue
        out.append({
            "id": candidate_key(title, "web"),
            "title": title[:90],
            "artist": "TBC",
            "venue": "서울/수도권",
            "venueType": "gallery",
            "city": "Seoul",
            "district": guess_area(snippet),
            "area": guess_area(snippet),
            "start": datetime.now(KST).date().isoformat(),
            "end": (datetime.now(KST).date() + timedelta(days=30)).isoformat(),
            "tags": ["search-signal"],
            "recommended": False,
            "needsReview": True,
            "confidence": 52,
            "note": f"무료 공개 검색에서 포착된 전시 후보: {snippet[:120]}",
            "url": decode_ddg_link(a.get("href") or ""),
            "sourceKey": "search",
            "sourceName": "Web search",
        })
    return out

def build_items() -> list[dict[str, Any]]:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    candidates = list(seed.get("candidates", []))

    # 기존 프로토타입의 venues watchlist를 공식 페이지 수집 대상으로 사용.
    # 너무 많이 돌면 GitHub Actions가 느려지므로 우선순위 공간만 앞에서 일부만 스캔.
    venues = seed.get("venues", [])
    priority = [v for v in venues if v[1] in ("museum", "gallery", "nonprofit") and v[4] and v[4] != "#"][:45]
    for venue in priority:
        candidates.extend(scan_venue_page(venue))

    # 무료 검색 신호 보강.
    for q in ART_SEARCH_QUERIES:
        candidates.extend(search_duckduckgo(q, max_results=4))

    merged = merge_seed_candidates(candidates)
    today = datetime.now(KST)
    current = [m for m in merged if active_or_currentish(m, today)]
    items = [make_noiz_item(m) for m in current]
    items = [x for x in items if x.get("infoVolume") != "low" and x.get("reactionCount", 0) > 0]
    items.sort(key=lambda x: (int(x.get("noiz", 0)), int(x.get("favorability", 0)), int(x.get("evidenceCount", 0))), reverse=True)
    top = items[:10]
    for i, item in enumerate(top, 1):
        item["rank"] = i
    return top

def make_weekly_read(items: list[dict[str, Any]]) -> str:
    if not items:
        return "이번 주 공개 검색과 Art Week Korea watchlist에서 충분히 확인된 미술 전시 후보를 찾지 못했다."
    areas = {}
    for item in items:
        areas[item.get("area", "서울/수도권")] = areas.get(item.get("area", "서울/수도권"), 0) + 1
    area_line = "·".join(sorted(areas, key=areas.get, reverse=True)[:3])
    return (
        f"이번 주 ART NOIZ는 {area_line}의 미술관·갤러리 전시를 중심으로 잡힌다. "
        "Art Week Korea의 전시 후보와 서울·수도권 watchlist를 기반으로 공식 확인·교차 확인 신호가 있는 항목을 우선 노출한다."
    )

def main() -> None:
    items = build_items()
    payload = {
        "site": "NOIZ. Art",
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "weekly_read": make_weekly_read(items),
        "items": items,
        "creator": "이원준 시니어매니저",
        "method_note": "Art Week Korea expanded prototype의 candidates/venues 데이터, 미술관·갤러리 공식 페이지, 아트 플랫폼, 전시 리뷰 검색 신호 기반 ART NOIZ 데이터.",
    }
    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] wrote {DATA_PATH} with {len(items)} ART NOIZ items")

if __name__ == "__main__":
    main()
