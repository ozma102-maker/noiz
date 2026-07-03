#!/usr/bin/env python3
"""
NOIZ updater — free MVP max mode.

핵심 방식
1. 지정 소스 페이지에서 전시/팝업 후보를 넓게 수집한다.
2. 무료 공개 검색 페이지/RSS에서 후보별·키워드별 후기/노출 신호를 추가 수집한다.
3. 후기 축적 전, 오픈 예정, 반응 없음 항목은 랭킹에서 제외한다.
4. 전체 후보군에서 먼저 필터링한 뒤 NOIZ 점수순 Top 10을 만든다.

주의
- API key 없는 무료 MVP라서 검색 결과 HTML/RSS 구조 변경에 취약하다.
- 네이버 플레이스/인스타그램 리뷰 전체 수집은 하지 않는다.
- 결과는 "객관적 평점"이 아니라 공개 노출·후기성 신호 기반 레이더다.
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
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "noiz-data.json"
SOURCES_PATH = ROOT / "scripts" / "sources.json"
KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NOIZBot/1.5; weekly-space-radar)",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
}

# 무료 공개 검색 쿼리. 후보군을 넓히는 용도.
SEARCH_QUERIES = [
    "서울 팝업 후기",
    "성수 팝업 후기",
    "더현대 서울 팝업 후기",
    "서울 브랜드 팝업 후기",
    "서울 전시 후기",
    "서울 전시회 후기",
    "서울 전시 추천 후기",
    "이번 주 서울 전시 후기",
    "서울 무료 전시 후기",
    "성수 전시 팝업 후기",
    "한남 전시 팝업 후기",
    "삼청 전시 후기",
    "DDP 전시 후기",
    "국립현대미술관 전시 후기",
    "서울시립미술관 전시 후기",
]

POSITIVE_WORDS = [
    "좋", "좋았", "만족", "추천", "강추", "재밌", "재미", "예쁘", "멋있",
    "인기", "핫", "화제", "볼만", "알차", "감각", "퀄리티", "포토존",
    "굿즈", "무료", "체험", "한정", "오픈런", "매진", "예약", "도슨트",
    "인생샷", "힐링", "몰입", "새롭", "풍성"
]

NEGATIVE_WORDS = [
    "아쉽", "실망", "별로", "비추", "비싸", "혼잡", "웨이팅", "줄", "대기",
    "품절", "좁", "불편", "상업적", "혼선", "예약필수", "마감", "허무",
    "부족", "복잡", "시끄럽", "덥", "춥"
]

NOISE_WORDS = [
    "팝업", "전시", "전시회", "개인전", "기획전", "브랜드", "공간", "성수",
    "더현대", "한남", "삼청", "을지로", "예약", "웨이팅", "굿즈", "체험",
    "한정", "오픈", "추천", "무료", "포토존", "후기", "리뷰", "방문"
]

REACTION_WORDS = [
    "후기", "리뷰", "방문", "다녀왔", "관람", "웨이팅", "대기", "굿즈", "추천",
    "별로", "아쉽", "좋았", "만족", "실망"
]

UPCOMING_WORDS = [
    "오픈 예정", "공개 예정", "개최 예정", "coming soon", "pre-open", "preopen"
]

CLOSED_WORDS = [
    "종료되었습니다", "종료된 전시", "전시 종료", "팝업 종료", "마감되었습니다",
    "운영 종료", "지난 전시"
]

BAD_TITLE_WORDS = [
    "로그인", "회원가입", "더보기", "바로가기", "전체보기", "메뉴", "검색",
    "공지사항", "개인정보", "이용약관"
]

AREA_WORDS = [
    "성수", "여의도", "한남", "삼청", "청담", "을지로", "중구", "종로",
    "서촌", "용산", "강남", "홍대", "잠실", "마포", "DDP", "동대문",
    "압구정", "신사", "가로수길", "광화문", "서울숲"
]

KNOWN_VENUES = [
    "더현대 서울", "DDP", "서울시립미술관", "국립현대미술관", "그라운드시소",
    "문화역서울284", "코엑스", "롯데월드몰", "디뮤지엄", "대림미술관",
    "아모레퍼시픽미술관", "리움미술관", "국제갤러리", "PKM", "페로탕",
    "송은", "성수", "한남", "삼청", "을지로"
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
    infoVolume: str
    evidenceCount: int = 1
    reactionCount: int = 0
    confidence: str = "low"


def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch(url: str, timeout: int = 18) -> str:
    res = requests.get(url, headers=HEADERS, timeout=timeout)
    res.raise_for_status()
    if not res.encoding:
        res.encoding = "utf-8"
    return res.text


def safe_fetch(url: str, timeout: int = 18) -> str:
    try:
        time.sleep(random.uniform(0.15, 0.45))
        return fetch(url, timeout=timeout)
    except Exception as e:
        print(f"[WARN] fetch failed: {url}: {e}")
        return ""


def normalize_title(title: str) -> str:
    title = clean_text(title)
    title = re.sub(r"\s*[-|:]\s*(네이버 블로그|네이버 포스트|브런치|YouTube|유튜브|뉴스|공식.*)$", "", title, flags=re.I)
    title = re.sub(r"\[(.*?)\]", r"\1", title)
    title = re.sub(r"\((.*?)\)", r"\1", title)
    title = title.strip(" -_|·")
    return title[:90]


def candidate_key(title: str, venue: str = "") -> str:
    base = re.sub(r"[^0-9A-Za-z가-힣]+", "", (title + venue).lower())
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def has_any(text: str, words: list[str]) -> bool:
    low = text.lower()
    return any(w.lower() in low for w in words)


def looks_like_candidate(text: str) -> bool:
    if len(text) < 6 or len(text) > 240:
        return False
    if any(w in text for w in BAD_TITLE_WORDS):
        return False
    return has_any(text, NOISE_WORDS + ["exhibition", "popup", "pop-up"])


def is_upcoming_or_closed(text: str) -> bool:
    low = text.lower()
    return any(w.lower() in low for w in UPCOMING_WORDS + CLOSED_WORDS)


def guess_area(text: str) -> str:
    for a in AREA_WORDS:
        if a in text:
            return a
    return "서울/수도권"


def guess_venue(text: str, fallback: str = "서울/수도권") -> str:
    for venue in KNOWN_VENUES:
        if venue in text:
            return venue
    return fallback


def reaction_count_from_text(text: str, channel: str) -> int:
    count = sum(1 for w in REACTION_WORDS if w in text)
    if channel in {"naver_view", "duckduckgo", "google_news"} and count > 0:
        count += 1
    return min(5, count)


def text_score(text: str, base: int, evidence_count: int = 1, reaction_count: int = 0) -> tuple[int, int, list[str], str, str]:
    pos = sum(1 for w in POSITIVE_WORDS if w.lower() in text.lower())
    neg = sum(1 for w in NEGATIVE_WORDS if w.lower() in text.lower())
    noise = sum(1 for w in NOISE_WORDS if w.lower() in text.lower())

    if reaction_count >= 3 or evidence_count >= 5:
        info_volume = "high"
        confidence = "high"
    elif reaction_count >= 1 or evidence_count >= 2:
        info_volume = "medium"
        confidence = "medium"
    else:
        info_volume = "low"
        confidence = "low"

    noiz = base
    noiz += min(30, evidence_count * 5)
    noiz += min(24, reaction_count * 6)
    noiz += min(24, noise * 3)
    noiz += min(10, pos * 2)
    noiz += min(8, neg * 2)  # 부정도 화제성/노이즈 신호로 일부 반영
    noiz = max(35, min(99, noiz))

    # favorability: 여론 톤. 기본은 중립 60.
    favor = 60 + min(30, pos * 4) - min(34, neg * 6)
    if "웨이팅" in text or "혼잡" in text or "줄" in text or "대기" in text:
        favor -= 5
    if "무료" in text or "추천" in text or "좋았" in text or "만족" in text:
        favor += 4

    # 정보량이 낮으면 극단 판단 금지
    if info_volume == "low":
        favor = max(50, min(69, favor))

    favor = max(0, min(100, favor))

    signals: list[str] = []
    if reaction_count:
        signals.append("후기 반응")
    if evidence_count >= 2:
        signals.append("복수 출처")
    if pos:
        signals.append("긍정 신호")
    if neg:
        signals.append("혼잡/피로 신호")
    if "웨이팅" in text or "대기" in text:
        signals.append("웨이팅 가능성")
    if "굿즈" in text:
        signals.append("굿즈 신호")
    if "무료" in text:
        signals.append("무료/체험")
    if info_volume == "low":
        signals.append("후기 축적 전")
    if is_upcoming_or_closed(text):
        signals.append("오픈 예정")
    if not signals:
        signals.append("공개 노출")

    return noiz, favor, signals[:4], info_volume, confidence


def make_description(title: str, evidence_count: int, reaction_count: int, area: str) -> str:
    return (
        f"{area}권에서 공개 노출 {evidence_count}건, 후기성 신호 {reaction_count}건을 기준으로 포착된 후보. "
        "NOIZ는 평점이 아니라 이번 주 노출량과 반응 톤을 읽는 레이더다."
    )


def make_candidate(
    *,
    title: str,
    text: str,
    url: str,
    source_name: str,
    channel: str,
    source_type: str = "event",
    base: int = 18,
) -> Candidate | None:
    text = clean_text(f"{title} {text}")
    title = normalize_title(title)
    if not looks_like_candidate(text) or not title:
        return None

    area = guess_area(text)
    venue = guess_venue(text, fallback=area)
    reaction_count = reaction_count_from_text(text, channel)
    evidence_count = 1
    noiz, favor, signals, info_volume, confidence = text_score(
        text,
        base=base,
        evidence_count=evidence_count,
        reaction_count=reaction_count,
    )

    return Candidate(
        brand=source_name,
        title=title,
        owner=f"{source_name}에서 확인된 {'팝업' if source_type == 'popup' else '전시/공간'} 후보",
        venue=venue,
        area=area,
        region=area,
        mapQuery=f"{title} {venue} {area}",
        sourceUrl=url,
        sourceLabel="정보 출처",
        noiz=noiz,
        favorability=favor,
        description=make_description(title, evidence_count, reaction_count, area),
        signals=signals,
        infoVolume=info_volume,
        evidenceCount=evidence_count,
        reactionCount=reaction_count,
        confidence=confidence,
    )


def extract_candidates_from_source(source: dict[str, Any]) -> list[Candidate]:
    url = source["url"]
    source_type = source.get("type", "event")
    base = int(source.get("weight", 18))
    raw = safe_fetch(url)
    if not raw:
        return []

    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    out: list[Candidate] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True)[:220]:
        title = clean_text(a.get_text(" ", strip=True))
        if not title or not looks_like_candidate(title):
            continue

        parent_text = clean_text(a.find_parent().get_text(" ", strip=True) if a.find_parent() else title)
        link = urljoin(url, a.get("href") or "")
        key = candidate_key(title, source["name"])
        if key in seen:
            continue
        seen.add(key)

        cand = make_candidate(
            title=title,
            text=parent_text,
            url=link,
            source_name=source["name"],
            channel="official",
            source_type=source_type,
            base=base,
        )
        if cand:
            out.append(cand)

    print(f"[INFO] source {source['name']}: {len(out)} candidates")
    return out


def decode_ddg_link(href: str) -> str:
    if not href:
        return ""
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    if "uddg" in qs:
        return unquote(qs["uddg"][0])
    return href


def search_duckduckgo(query: str, max_results: int = 8) -> list[Candidate]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    raw = safe_fetch(url)
    if not raw:
        return []

    soup = BeautifulSoup(raw, "lxml")
    out: list[Candidate] = []
    for block in soup.select(".result")[:max_results]:
        a = block.select_one(".result__a")
        if not a:
            continue
        title = clean_text(a.get_text(" ", strip=True))
        href = decode_ddg_link(a.get("href") or "")
        snippet_el = block.select_one(".result__snippet")
        snippet = clean_text(snippet_el.get_text(" ", strip=True) if snippet_el else block.get_text(" ", strip=True))
        cand = make_candidate(
            title=title,
            text=f"{query} {snippet}",
            url=href,
            source_name="Web Search",
            channel="duckduckgo",
            source_type="event",
            base=22,
        )
        if cand:
            out.append(cand)

    print(f"[INFO] duckduckgo '{query}': {len(out)} candidates")
    return out


def search_naver_view(query: str, max_results: int = 10) -> list[Candidate]:
    url = f"https://search.naver.com/search.naver?where=view&query={quote_plus(query)}"
    raw = safe_fetch(url)
    if not raw:
        return []

    soup = BeautifulSoup(raw, "lxml")
    out: list[Candidate] = []
    seen: set[str] = set()

    # 네이버 검색 결과 구조는 자주 바뀌므로 generic하게 링크를 읽는다.
    for a in soup.find_all("a", href=True):
        if len(out) >= max_results:
            break
        href = a.get("href") or ""
        title = clean_text(a.get_text(" ", strip=True))
        if not title or href in seen:
            continue
        if "blog.naver.com" not in href and "post.naver.com" not in href and "cafe.naver.com" not in href:
            continue
        parent = a.find_parent()
        snippet = clean_text(parent.get_text(" ", strip=True) if parent else title)
        cand = make_candidate(
            title=title,
            text=f"{query} {snippet}",
            url=href,
            source_name="Naver View",
            channel="naver_view",
            source_type="event",
            base=24,
        )
        if cand:
            out.append(cand)
            seen.add(href)

    print(f"[INFO] naver view '{query}': {len(out)} candidates")
    return out


def search_google_news(query: str, max_results: int = 8) -> list[Candidate]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ko&gl=KR&ceid=KR:ko"
    raw = safe_fetch(url)
    if not raw:
        return []

    soup = BeautifulSoup(raw, "xml")
    out: list[Candidate] = []
    for item in soup.find_all("item")[:max_results]:
        title = clean_text(item.title.get_text(" ", strip=True) if item.title else "")
        link = clean_text(item.link.get_text(" ", strip=True) if item.link else "")
        desc = clean_text(item.description.get_text(" ", strip=True) if item.description else "")
        cand = make_candidate(
            title=title,
            text=f"{query} {desc}",
            url=link,
            source_name="Google News",
            channel="google_news",
            source_type="event",
            base=20,
        )
        if cand:
            out.append(cand)

    print(f"[INFO] google news '{query}': {len(out)} candidates")
    return out


def discover_search_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []
    for query in SEARCH_QUERIES:
        candidates.extend(search_naver_view(query, max_results=8))
        candidates.extend(search_duckduckgo(query, max_results=6))
        candidates.extend(search_google_news(query, max_results=5))
    return candidates


def merge_candidates(candidates: list[Candidate]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Candidate]] = {}
    for c in candidates:
        # 검색 결과 제목이 블로그식으로 길 수 있어 venue보다 title 중심으로 묶는다.
        key = candidate_key(c.title)
        grouped.setdefault(key, []).append(c)

    merged: list[dict[str, Any]] = []
    for group in grouped.values():
        group = sorted(group, key=lambda c: c.noiz, reverse=True)
        best = asdict(group[0])

        evidence_count = sum(max(1, g.evidenceCount) for g in group)
        reaction_count = sum(max(0, g.reactionCount) for g in group)
        text_blob = " ".join(
            [g.title, g.description, " ".join(g.signals), g.brand, g.area]
            for g in group
        )
        base = max(g.noiz for g in group) - 10
        noiz, favor, signals, info_volume, confidence = text_score(
            text_blob,
            base=max(35, min(85, base)),
            evidence_count=evidence_count,
            reaction_count=reaction_count,
        )

        source_labels = []
        for g in group:
            if g.brand not in source_labels:
                source_labels.append(g.brand)

        best["noiz"] = noiz
        best["favorability"] = favor
        best["signals"] = signals[:4]
        best["infoVolume"] = info_volume
        best["evidenceCount"] = evidence_count
        best["reactionCount"] = reaction_count
        best["confidence"] = confidence
        best["brand"] = " / ".join(source_labels[:2])
        best["owner"] = f"공개 노출 {evidence_count}건 · 후기성 신호 {reaction_count}건"
        best["description"] = make_description(best["title"], evidence_count, reaction_count, best.get("area", "서울/수도권"))

        merged.append(best)

    return merged


def is_rankable_item(item: dict[str, Any]) -> bool:
    signals = " ".join(item.get("signals", []))
    status = str(item.get("status", item.get("openStatus", ""))).lower()
    text = " ".join([
        item.get("title", ""),
        item.get("description", ""),
        signals,
        status,
    ])

    if item.get("infoVolume") == "low" or item.get("lowInfo") is True:
        return False
    if any(x in signals for x in ["후기 축적 전", "후기 부족", "오픈 예정", "반응 없음"]):
        return False
    if any(x in status for x in ["upcoming", "preopen", "pre-open"]):
        return False
    if is_upcoming_or_closed(text):
        return False
    return True


def load_existing() -> dict[str, Any]:
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return {"items": []}


def merge_with_existing(new_items: list[dict[str, Any]], existing_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}

    # 새 후보 우선
    for item in new_items:
        k = candidate_key(item.get("title", ""))
        if k not in by_key or int(item.get("noiz", 0)) > int(by_key[k].get("noiz", 0)):
            by_key[k] = item

    # 새 후보가 적을 때만 기존 데이터 보강. 단 low-info는 제외된다.
    for old in existing_items:
        old.setdefault("infoVolume", "medium")
        signals_text = " ".join(old.get("signals", []))
        old.setdefault("reactionCount", 0 if ("후기 축적 전" in signals_text or "후기 부족" in signals_text) else 1)
        old.setdefault("evidenceCount", 2 if old.get("reactionCount", 0) else 1)
        old.setdefault("confidence", "medium" if old.get("reactionCount", 0) else "low")
        k = candidate_key(old.get("title", ""))
        if k not in by_key:
            by_key[k] = old

    ranked_pool = [item for item in by_key.values() if is_rankable_item(item)]
    ranked_pool.sort(key=lambda x: int(x.get("noiz", 0)), reverse=True)

    top = ranked_pool[:10]
    for i, item in enumerate(top, 1):
        item["rank"] = i
    return top


def classify_experience_type(item: dict[str, Any]) -> str:
    category = str(item.get("category", item.get("type", ""))).lower()
    if any(x in category for x in ["exhibition", "culture", "art", "museum"]):
        return "전시/문화 경험"
    if any(x in category for x in ["popup", "brand", "retail"]):
        return "팝업/브랜드 경험"

    title = item.get("title", "")
    brand = item.get("brand", item.get("owner", ""))
    signals = " ".join(item.get("signals", []))
    description = item.get("description", "")
    strong_text = " ".join([title, brand, signals])
    all_text = " ".join([strong_text, description])
    strong_lower = strong_text.lower()
    all_lower = all_text.lower()

    exhibition_words = [
        "개인전", "기획전", "미술관", "전시", "명작전", "회고전", "회고", "작가",
        "서울시립미술관", "그라운드시소", "도슨트", "유영국", "렘브란트", "고야"
    ]
    popup_words = [
        "팝업", "pop up", "popup", "팝업스토어", "스토어", "굿즈", "ip 팬덤", "캐릭터",
        "브랜드 체험", "제품 탐색", "구매 욕구", "이벤트", "더현대", "t1", "sk텔레콤",
        "gs25", "돈키호테", "nh농협", "마른파이브"
    ]

    if any(w.lower() in strong_lower for w in exhibition_words):
        return "전시/문화 경험"
    if any(w.lower() in strong_lower for w in popup_words):
        return "팝업/브랜드 경험"
    if any(w.lower() in all_lower for w in ["팝업", "pop up", "popup", "굿즈", "한정", "브랜드 체험", "제품 탐색", "구매 욕구"]):
        return "팝업/브랜드 경험"
    if any(w in all_text for w in ["전시", "미술", "관람", "작품", "작가", "회화", "사진", "조각"]):
        return "전시/문화 경험"
    return "공간 경험"


def make_weekly_read(items: list[dict[str, Any]]) -> str:
    rankable = sorted([i for i in items if is_rankable_item(i)], key=lambda x: int(x.get("noiz", 0)), reverse=True)[:10]
    if not rankable:
        return "이번 주는 아직 잡히는 신호가 많지 않아. 조금 더 쌓이면 바로 읽어볼게!"

    areas: dict[str, int] = {}
    types: dict[str, int] = {"팝업/브랜드 경험": 0, "전시/문화 경험": 0, "공간 경험": 0}
    blob_parts: list[str] = []

    for item in rankable:
        area = item.get("area") or item.get("region") or "서울/수도권"
        areas[area] = areas.get(area, 0) + 1
        types[classify_experience_type(item)] += 1
        blob_parts.append(" ".join([
            item.get("title", ""),
            item.get("brand", ""),
            item.get("owner", ""),
            item.get("venue", ""),
            item.get("area", ""),
            item.get("description", ""),
            " ".join(item.get("signals", [])),
        ]))

    area_line = "·".join(sorted(areas, key=areas.get, reverse=True)[:3])
    popup_count = types.get("팝업/브랜드 경험", 0)
    art_count = types.get("전시/문화 경험", 0)
    blob = " ".join(blob_parts)

    why = "관심은 단순 정보 탐색보다, 바로 가볼 수 있고 짧게 즐길 수 있는 경험 쪽으로 모이는 분위기야."
    if popup_count > art_count and any(x in blob for x in ["굿즈", "한정", "무료", "체험", "팬덤"]):
        why = "관심이 모이는 이유는 굿즈, 한정성, 무료 체험처럼 바로 움직이게 만드는 요소가 강하기 때문이야."
    elif art_count >= popup_count and any(x in blob for x in ["미술관", "명작", "거장", "기관", "도슨트", "기획전"]):
        why = "관심이 모이는 이유는 검증된 작가명, 기관 전시, 명확한 관람 목적처럼 실패 확률이 낮은 문화 경험이 강하기 때문이야."

    environment = "전체적으로는 상권형 팝업과 전시형 문화 경험이 같은 주말 시간을 두고 경쟁하는 분위기야."
    if popup_count >= 5:
        environment = "전체 환경은 성수·더현대식 팝업 경쟁이 강하고, 관객은 오래 머무는 전시보다 짧고 인증하기 좋은 방문 경험에 빠르게 반응하는 흐름이야."
    elif art_count >= 5:
        environment = "전체 환경은 대형 전시와 미술관 동선의 비중이 높고, 관객은 검증된 콘텐츠를 중심으로 주말 일정을 짜는 흐름이야."

    congestion = "다만 웨이팅·혼잡 신호도 같이 보여. 화제성은 높지만 방문 피로도는 꼭 같이 봐야 해!" if any(x in blob for x in ["웨이팅", "혼잡", "줄", "대기", "더현대"]) else "혼잡 신호는 상대적으로 약해. 이번 주는 화제성 대비 접근성이 꽤 괜찮아 보여!"
    list_name = "Top 10" if len(rankable) >= 10 else "상위 후보"
    return f"이번 주 NOIZ는 {area_line or '서울/수도권'} 중심으로 잡혀. {list_name}는 팝업/브랜드 경험 {popup_count}개, 전시/문화 경험 {art_count}개가 섞여 있고, 가장 강한 신호는 {rankable[0].get('title', '상위 후보')}야. {why} {environment} {congestion}"

def main() -> None:
    existing = load_existing()
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))

    candidates: list[Candidate] = []

    for source in sources:
        print(f"[INFO] scanning source: {source['name']}")
        candidates.extend(extract_candidates_from_source(source))

    print("[INFO] scanning free public search signals")
    candidates.extend(discover_search_candidates())

    merged_new = merge_candidates(candidates)
    items = merge_with_existing(merged_new, existing.get("items", []))

    payload = {
        "site": "NOIZ",
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "weekly_read": make_weekly_read(items),
        "items": items,
        "creator": "이원준 시니어매니저",
        "method_note": "무료 공개 소스, 검색 결과, 뉴스 RSS, 블로그/후기성 스니펫을 바탕으로 본 주간 신호 레이더야. 객관적 평점이라기보다는 지금 어디가 시끄러운지 읽는 용도야!",
    }

    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] wrote {DATA_PATH} with {len(items)} rankable items")


if __name__ == "__main__":
    main()
