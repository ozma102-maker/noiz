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
ARCHIVE_DIR = ROOT / "data" / "archive"
ARCHIVE_INDEX_PATH = ROOT / "data" / "noiz-archive-index.json"
THEME_HISTORY_PATH = ROOT / "data" / "noiz-theme-history.json"
SOURCES_PATH = ROOT / "scripts" / "sources.json"
KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NOIZBot/1.5; weekly-space-radar)",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
}

COLOR_SCHEMES: list[dict[str, str]] = [{'id': 'hippie-green-lemon', 'name': 'Hippie Green & Lemon', 'bg': '#5f914f', 'ink': '#ffde00', 'muted': '#ffe84c', 'line': 'rgba(255,222,0,.32)', 'paper': 'rgba(255,255,255,.10)', 'white': '#fffbe6'}, {'id': 'coffee-broom', 'name': 'Coffee & Broom', 'bg': '#7b705d', 'ink': '#f5ff00', 'muted': '#fbff61', 'line': 'rgba(245,255,0,.30)', 'paper': 'rgba(255,255,255,.09)', 'white': '#fffde8'}, {'id': 'carnation-fiord', 'name': 'Carnation & Fiord', 'bg': '#f57365', 'ink': '#395b80', 'muted': '#466c95', 'line': 'rgba(57,91,128,.26)', 'paper': 'rgba(255,255,255,.12)', 'white': '#fff4ef'}, {'id': 'sisal-cerise', 'name': 'Sisal & Cerise', 'bg': '#d3d0c1', 'ink': '#ef2ea6', 'muted': '#d72896', 'line': 'rgba(239,46,166,.24)', 'paper': 'rgba(255,255,255,.16)', 'white': '#fff7fb'}, {'id': 'san-juan-salmon', 'name': 'San Juan & Salmon', 'bg': '#2c5b7b', 'ink': '#ff8174', 'muted': '#ff9b91', 'line': 'rgba(255,129,116,.30)', 'paper': 'rgba(255,255,255,.09)', 'white': '#fff3f1'}, {'id': 'dodger-blue-ebb', 'name': 'Dodger Blue & Ebb', 'bg': '#3987ee', 'ink': '#efe5e2', 'muted': '#f7efed', 'line': 'rgba(239,229,226,.34)', 'paper': 'rgba(255,255,255,.12)', 'white': '#fff8f6'}, {'id': 'ripe-lemon-royal-blue', 'name': 'Ripe Lemon & Royal Blue', 'bg': '#f2ec00', 'ink': '#387ee8', 'muted': '#4c8cef', 'line': 'rgba(56,126,232,.27)', 'paper': 'rgba(255,255,255,.16)', 'white': '#f7fbff'}, {'id': 'screamin-green-martinique', 'name': "Screamin' Green & Martinique", 'bg': '#67f86f', 'ink': '#4b4070', 'muted': '#5d5280', 'line': 'rgba(75,64,112,.25)', 'paper': 'rgba(255,255,255,.14)', 'white': '#fbf7ff'}, {'id': 'bossanova-chartreuse', 'name': 'Bossanova & Chartreuse Yellow', 'bg': '#5c3e73', 'ink': '#d8ff00', 'muted': '#e4ff45', 'line': 'rgba(216,255,0,.30)', 'paper': 'rgba(255,255,255,.08)', 'white': '#fbffe8'}, {'id': 'cerise-pear', 'name': 'Cerise & Pear', 'bg': '#d7359c', 'ink': '#bfff32', 'muted': '#ceff67', 'line': 'rgba(191,255,50,.30)', 'paper': 'rgba(255,255,255,.10)', 'white': '#fbffe8'}, {'id': 'chathams-blue-screamin-green', 'name': "Chathams Blue & Screamin' Green", 'bg': '#126a7a', 'ink': '#62f777', 'muted': '#86ff96', 'line': 'rgba(98,247,119,.30)', 'paper': 'rgba(255,255,255,.08)', 'white': '#f0fff3'}, {'id': 'sunset-orange-starship', 'name': 'Sunset Orange & Starship', 'bg': '#fb4f43', 'ink': '#fffb2a', 'muted': '#fff766', 'line': 'rgba(255,251,42,.30)', 'paper': 'rgba(255,255,255,.10)', 'white': '#fffde8'}, {'id': 'mulled-wine-screamin-green', 'name': "Mulled Wine & Screamin' Green", 'bg': '#584966', 'ink': '#62fa84', 'muted': '#85ffa0', 'line': 'rgba(98,250,132,.30)', 'paper': 'rgba(255,255,255,.08)', 'white': '#f0fff5'}, {'id': 'geyser-mandy', 'name': 'Geyser & Mandy', 'bg': '#d9e0e0', 'ink': '#ef4d54', 'muted': '#d94249', 'line': 'rgba(239,77,84,.24)', 'paper': 'rgba(255,255,255,.18)', 'white': '#fff6f6'}, {'id': 'deco-royal-blue', 'name': 'Deco & Royal Blue', 'bg': '#dcd996', 'ink': '#367ee8', 'muted': '#4b8df0', 'line': 'rgba(54,126,232,.25)', 'paper': 'rgba(255,255,255,.16)', 'white': '#f7fbff'}]
DEFAULT_THEME_ID = 'legacy-lime-blue'
LEGACY_THEME: dict[str, str] = {'id': 'legacy-lime-blue', 'name': 'Legacy Lime & Blue', 'bg': '#c6ff00', 'paper': 'rgba(255,255,255,.18)', 'ink': '#3f5d7f', 'muted': '#58779a', 'line': 'rgba(63,93,127,.24)', 'white': '#f4ffd8'}

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
    start: str = ""
    end: str = ""


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



def normalize_event_date(year: int, month: int, day: int) -> str:
    try:
        return datetime(year, month, day, tzinfo=KST).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def extract_period_from_text(text: str) -> tuple[str, str]:
    """Best-effort extraction of event/exhibition periods from public snippets.

    Supports common Korean formats:
    - 2026.07.02 - 2026.09.13
    - 2026년 7월 2일 ~ 9월 13일
    - 7.2~9.13 / 7월 2일–9월 13일
    If no reliable period is visible in the fetched text/snippet, returns blanks.
    """
    source = clean_text(text)
    if not source:
        return "", ""

    now_year = datetime.now(KST).year
    dash = r"(?:~|–|—|-|부터|에서|to|TO|\s+)"
    year = r"(20\d{2})"
    month = r"(1[0-2]|0?[1-9])"
    day = r"(3[01]|[12]\d|0?[1-9])"
    ym_sep = r"[.\-/년\s]+"
    md_sep = r"[.\-/월\s]+"

    patterns = [
        # 2026.07.02 - 2026.09.13 / 2026-07-02 ~ 2026-09-13
        rf"{year}{ym_sep}{month}{md_sep}{day}\s*(?:일)?\s*{dash}\s*{year}{ym_sep}{month}{md_sep}{day}",
        # 2026.07.02 - 09.13 / 2026년 7월 2일 ~ 9월 13일
        rf"{year}{ym_sep}{month}{md_sep}{day}\s*(?:일)?\s*{dash}\s*{month}{md_sep}{day}",
        # 7.2 - 9.13 / 7월 2일 ~ 9월 13일
        rf"{month}{md_sep}{day}\s*(?:일)?\s*{dash}\s*{month}{md_sep}{day}",
    ]

    for idx, pattern in enumerate(patterns):
        m = re.search(pattern, source, flags=re.I)
        if not m:
            continue
        nums = [int(x) for x in m.groups()]
        if idx == 0 and len(nums) >= 6:
            sy, sm, sd, ey, em, ed = nums[:6]
        elif idx == 1 and len(nums) >= 5:
            sy, sm, sd, em, ed = nums[:5]
            ey = sy if em >= sm else sy + 1
        elif idx == 2 and len(nums) >= 4:
            sm, sd, em, ed = nums[:4]
            sy = now_year
            ey = sy if em >= sm else sy + 1
        else:
            continue

        start = normalize_event_date(sy, sm, sd)
        end = normalize_event_date(ey, em, ed)
        if start and end:
            return start, end

    # Single explicit opening date, useful when only a start date is visible.
    single_patterns = [
        rf"{year}{ym_sep}{month}{md_sep}{day}\s*(?:일)?\s*(?:오픈|개막|시작|부터|open|opens)",
        rf"{month}{md_sep}{day}\s*(?:일)?\s*(?:오픈|개막|시작|부터|open|opens)",
    ]
    for idx, pattern in enumerate(single_patterns):
        m = re.search(pattern, source, flags=re.I)
        if not m:
            continue
        nums = [int(x) for x in m.groups()]
        if idx == 0 and len(nums) >= 3:
            sy, sm, sd = nums[:3]
        elif idx == 1 and len(nums) >= 2:
            sy, sm, sd = now_year, nums[0], nums[1]
        else:
            continue
        start = normalize_event_date(sy, sm, sd)
        if start:
            return start, ""

    return "", ""

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
    raw_text = clean_text(f"{title} {text}")
    if is_aggregate_or_listing_candidate(title, raw_text, url=url, source_name=source_name):
        return None

    text = raw_text
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
    start, end = extract_period_from_text(text)

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
        start=start,
        end=end,
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



SEARCH_SOURCE_NAMES = {"Naver View", "Google News", "Web Search"}

AGGREGATE_PAGE_WORDS = [
    "총정리", "놀거리", "가볼만한", "가볼 만한", "추천", "모음", "리스트", "한눈에",
    "캘린더", "일정 정리", "전시 추천", "전시회 추천", "팝업 추천", "팝업스토어 추천",
    "팝업스토어 총정리", "데이트코스", "데이트 코스", "핫플", "이번 주 뭐", "이번주 뭐",
    "new ", "신상", "오픈일 팝업 방문 후기", "방문 후기",
]

BAD_PRIMARY_URL_PARTS = [
    "blog.naver.com",
    "post.naver.com",
    "cafe.naver.com",
    "news.google.com",
    "search.naver.com",
    "html.duckduckgo.com",
]


def is_review_or_search_url(url: str) -> bool:
    url = str(url or "").lower()
    return any(part in url for part in BAD_PRIMARY_URL_PARTS)


def is_search_source_name(name: str) -> bool:
    return clean_text(name) in SEARCH_SOURCE_NAMES


def clean_display_title(title: str) -> str:
    t = clean_text(str(title or "")).replace("_", " ")
    t = re.sub(r"\s*(?:방문\s*)?후기.*$", "", t)
    t = re.sub(r"\s*(추천|가볼\s*만한|가볼만한).*$", "", t)
    t = re.sub(r"예정\s*서울\s*전시", " ", t)
    t = re.sub(r"서울\s*전시", " ", t)
    t = re.sub(r"\bALT\s*:\s*\d+\b", " ", t, flags=re.I)
    t = re.sub(r"\s*(?:20)?\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\s*[-~–—]\s*(?:20)?\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\s*$", "", t)
    t = re.sub(r"\s*(?:20)?\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\s*[-~–—]\s*\d{1,2}[.\-/]\d{1,2}\s*$", "", t)
    t = re.sub(r"\s*\d{1,2}[.\-/]\d{1,2}\s*[-~–—]\s*\d{1,2}[.\-/]\d{1,2}\s*$", "", t)
    t = re.sub(r"\s+(더현대\s*서울\s*현대백화점|더현대서울현대백화점|그라운드\s*시소\s*이스트|그라운드시소\s*이스트|서울시립미술관|국립현대미술관).*$", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -_·|")
    return t or clean_text(title)


def is_aggregate_or_listing_candidate(title: str, text: str = "", url: str = "", source_name: str = "") -> bool:
    title_clean = clean_text(str(title or ""))
    full = clean_text(" ".join([title_clean, str(text or ""), str(url or ""), str(source_name or "")])).lower()

    if "#" in title_clean:
        return True
    if any(word.lower() in full for word in AGGREGATE_PAGE_WORDS):
        return True

    # "2026년 7월 더현대서울 팝업스토어 총정리" style pages
    if re.search(r"20\d{2}\s*년\s*\d{1,2}\s*월", title_clean) and any(w in title_clean for w in ["팝업", "전시", "놀거리", "추천"]):
        if not any(mark in title_clean for mark in [":", "：", "〈", "《", "POP UP", "IN ", " x ", " X "]):
            return True

    tokens = re.findall(r"[A-Za-z0-9]{2,}|[가-힣]{2,}", title_clean)
    generic_hits = sum(1 for t in tokens if t in {"서울", "더현대", "여의도", "잠실", "성수", "팝업", "팝업스토어", "전시", "전시회", "놀거리", "추천", "총정리", "오픈"})
    if len(tokens) >= 5 and generic_hits / max(1, len(tokens)) >= 0.55:
        return True

    return False


def parse_iso_date_safe(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=KST)
    except Exception:
        return None


def item_full_text(item: dict[str, Any]) -> str:
    return " ".join([
        str(item.get("title", "")),
        str(item.get("description", "")),
        str(item.get("venue", "")),
        str(item.get("area", "")),
        str(item.get("region", "")),
        " ".join(str(s) for s in item.get("signals", [])),
    ])


def is_current_or_undated_official_item(item: dict[str, Any], now_dt: datetime | None = None) -> bool:
    now_dt = now_dt or datetime.now(KST)
    today = now_dt.date()
    start = parse_iso_date_safe(item.get("start") or item.get("startDate") or item.get("openDate"))
    end = parse_iso_date_safe(item.get("end") or item.get("endDate") or item.get("closeDate"))

    if end and end.date() < today:
        return False
    if start and start.date() > today:
        return False
    if is_upcoming_or_closed(item_full_text(item)):
        return False
    if is_review_or_search_url(str(item.get("sourceUrl", ""))):
        return False
    if is_aggregate_or_listing_candidate(item.get("title", ""), item_full_text(item), url=str(item.get("sourceUrl", "")), source_name=str(item.get("brand", ""))):
        return False
    return True


GROUP_STOPWORDS = {
    "서울", "수도권", "전시", "전시회", "팝업", "팝업스토어", "스토어", "행사", "후기", "방문",
    "가볼만한곳", "가볼만한", "추천", "일정", "정보", "예약", "오픈", "무료", "관람", "개인전",
    "기획전", "브랜드", "공간", "성수", "여의도", "한남", "청담", "삼청", "중구", "강남", "송파", "잠실",
    "popup", "pop", "up", "store", "exhibition", "review", "seoul", "visit", "event", "official"
}


def group_tokens(text: str) -> set[str]:
    normalized = clean_text(text).lower()
    normalized = re.sub(r"https?://\S+", " ", normalized)
    normalized = re.sub(r"[\[\](){},./|_<>:;!?\"'“”‘’·•#]", " ", normalized)
    normalized = re.sub(r"\b(20\d{2})[.\-/년\s]*(\d{1,2})[.\-/월\s]*(\d{1,2})\s*(?:일)?\b", " ", normalized)
    normalized = re.sub(r"\b\d{1,2}[.\-/월\s]+\d{1,2}\s*(?:일)?\b", " ", normalized)
    tokens = re.findall(r"[a-z0-9]{2,}|[가-힣]{2,}", normalized)
    return {t for t in tokens if t not in GROUP_STOPWORDS and len(t) >= 2 and not t.isdigit()}


def token_jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def compact_key_text(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", clean_text(text).lower())


def title_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, compact_key_text(a), compact_key_text(b)).ratio()


def meaningful_venue(venue: str) -> str:
    venue = clean_text(venue)
    generic = {"서울", "서울/수도권", "수도권", "성수", "여의도", "한남", "청담", "삼청", "중구", "강남", "송파", "잠실", ""}
    return "" if venue in generic else venue


def candidate_match_score(item: dict[str, Any], c: Candidate) -> float:
    item_title = str(item.get("title", ""))
    title_sim = title_similarity(item_title, c.title)
    jac = token_jaccard(
        group_tokens(" ".join([item_title, str(item.get("venue", "")), str(item.get("area", ""))])),
        group_tokens(" ".join([c.title, c.venue, c.area, c.brand])),
    )
    same_venue = bool(meaningful_venue(str(item.get("venue", ""))) and meaningful_venue(str(item.get("venue", ""))) == meaningful_venue(c.venue))
    same_area = bool(item.get("area") and c.area and item.get("area") == c.area)
    score = title_sim * 0.58 + jac * 0.34
    if same_venue:
        score += 0.18
    if same_area:
        score += 0.06
    return score


def local_overview_sentence(item: dict[str, Any]) -> str:
    title = clean_display_title(str(item.get("title", "")))
    venue = clean_text(str(item.get("venue", "")))
    area = clean_text(str(item.get("area") or item.get("region") or "서울/수도권"))
    category = classify_experience_type(item)
    signals = " ".join(str(s) for s in item.get("signals", []))

    if category == "전시/문화 경험":
        if venue and venue not in {"서울", "서울/수도권", area}:
            return f"{venue}에서 열리는 전시/문화 경험으로, 작품·공간 구성과 관람 동선을 함께 확인할 만해."
        return f"{title}은 {area}권에서 열리는 전시/문화 경험으로, 작품과 관람 동선의 완성도를 확인할 만해."

    if "굿즈" in signals or "무료" in signals or "체험" in signals:
        return f"{title}은 {area}권에서 진행 중인 팝업/브랜드 경험으로, 굿즈·체험 요소와 방문 동선을 함께 볼 만해."

    if venue and venue not in {"서울", "서울/수도권", area}:
        return f"{venue}에서 진행 중인 팝업/브랜드 경험으로, 브랜드 연출과 현장 반응을 벤치마크할 만해."

    return f"{title}은 {area}권에서 포착된 공간 경험으로, 현장 구성과 방문 반응을 함께 확인할 만해."


def enrich_official_items_with_search_evidence(items: list[dict[str, Any]], search_candidates: list[Candidate]) -> list[dict[str, Any]]:
    """Naver/Google/Web results raise DECIBEL only; they never become cards."""
    for item in items:
        if is_review_or_search_url(str(item.get("sourceUrl", ""))):
            continue

        matches = [c for c in search_candidates if candidate_match_score(item, c) >= 0.35]
        if not matches:
            item["owner"] = local_overview_sentence(item)
            item["description"] = local_overview_sentence(item)
            continue

        evidence_count = int(item.get("evidenceCount", 1)) + sum(max(1, c.evidenceCount) for c in matches)
        reaction_count = int(item.get("reactionCount", 0)) + sum(max(0, c.reactionCount) for c in matches)
        text_blob = " ".join(
            [item_full_text(item)] + [
                " ".join([c.title, c.description, " ".join(c.signals), c.brand, c.area])
                for c in matches
            ]
        )

        base = max(35, min(86, int(item.get("noiz", 45)) - 4))
        noiz, favor, signals, info_volume, confidence = text_score(
            text_blob,
            base=base,
            evidence_count=evidence_count,
            reaction_count=reaction_count,
        )

        item["noiz"] = noiz
        item["favorability"] = favor
        item["signals"] = signals[:4]
        item["infoVolume"] = info_volume
        item["evidenceCount"] = evidence_count
        item["reactionCount"] = reaction_count
        item["confidence"] = confidence
        item["signalSummary"] = f"공개 노출 {evidence_count}건 · 후기성 신호 {reaction_count}건"
        item["owner"] = local_overview_sentence(item)
        item["description"] = local_overview_sentence(item)
        item["evidenceSources"] = sorted({c.brand for c in matches if c.brand})[:4]

    return items


def finalize_items(items: list[dict[str, Any]], now_dt: datetime | None = None) -> list[dict[str, Any]]:
    finalized = []
    seen = set()

    for item in items:
        if not is_current_or_undated_official_item(item, now_dt=now_dt):
            continue
        item["title"] = clean_display_title(item.get("title", ""))
        item["owner"] = local_overview_sentence(item)
        item["description"] = local_overview_sentence(item)

        key = candidate_key(item.get("title", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        finalized.append(item)

    finalized.sort(key=lambda x: int(x.get("noiz", 0)), reverse=True)
    finalized = finalized[:10]
    for i, item in enumerate(finalized, 1):
        item["rank"] = i
    return finalized


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
            " ".join([
                str(g.title or ""),
                str(g.description or ""),
                " ".join(str(s) for s in (g.signals or [])),
                str(g.brand or ""),
                str(g.area or ""),
            ])
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
        best["title"] = clean_display_title(best.get("title", ""))
        best["signalSummary"] = f"공개 노출 {evidence_count}건 · 후기성 신호 {reaction_count}건"
        best["owner"] = local_overview_sentence(best)
        best["description"] = local_overview_sentence(best)
        if not best.get("start") or not best.get("end"):
            for g in group:
                if g.start and not best.get("start"):
                    best["start"] = g.start
                if g.end and not best.get("end"):
                    best["end"] = g.end
                if best.get("start") and best.get("end"):
                    break

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


PERIOD_FIELDS = ("start", "end", "startDate", "endDate", "openDate", "closeDate", "period", "dateRange", "displayPeriod")


def merge_with_existing(new_items: list[dict[str, Any]], existing_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}

    # 새 후보 우선
    for item in new_items:
        k = candidate_key(item.get("title", ""))
        if k not in by_key or int(item.get("noiz", 0)) > int(by_key[k].get("noiz", 0)):
            by_key[k] = item

    # Existing payload is only a fallback if the fresh crawl is too thin.
    # This prevents accidentally carrying over malformed experimental data.
    if len(new_items) < 8:
        for old in existing_items:
            old.setdefault("infoVolume", "medium")
            signals_text = " ".join(old.get("signals", []))
            old.setdefault("reactionCount", 0 if ("후기 축적 전" in signals_text or "후기 부족" in signals_text) else 1)
            old.setdefault("evidenceCount", 2 if old.get("reactionCount", 0) else 1)
            old.setdefault("confidence", "medium" if old.get("reactionCount", 0) else "low")
            k = candidate_key(old.get("title", ""))
            if k not in by_key:
                by_key[k] = old
            else:
                for field in PERIOD_FIELDS:
                    if old.get(field) and not by_key[k].get(field):
                        by_key[k][field] = old.get(field)

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
    return f"이번 주 NOIZ는 {area_line or '서울/수도권'} 중심으로 잡혀. {list_name}는 팝업/브랜드 경험 {popup_count}개, 전시/문화 경험 {art_count}개가 섞여 있고, 가장 강한 신호는 {rankable[0].get('title', '상위 후보')} 쪽이야. {why} {environment} {congestion}"



def get_theme_by_id(theme_id: str | None) -> dict[str, str]:
    if theme_id == LEGACY_THEME.get("id"):
        return dict(LEGACY_THEME)
    for theme in COLOR_SCHEMES:
        if theme.get("id") == theme_id:
            return dict(theme)
    return dict(LEGACY_THEME)


def load_theme_history() -> dict[str, Any]:
    if THEME_HISTORY_PATH.exists():
        try:
            return json.loads(THEME_HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"site": "NOIZ Theme History", "entries": []}


def pick_weekly_theme(existing_theme: dict[str, Any] | None = None) -> dict[str, str]:
    """Change the main page color scheme on Mondays, avoiding the last 8 selected themes."""
    current_dt = datetime.now(KST)
    existing_id = (existing_theme or {}).get("id")

    # Not Monday: keep the current theme stable. This lets the legacy color stay this week.
    if current_dt.weekday() != 0:
        if existing_theme and all(existing_theme.get(key) for key in ["bg", "ink", "muted", "line"]):
            return dict(existing_theme)
        return get_theme_by_id(existing_id)

    monday_key = current_dt.strftime("%Y-%m-%d")
    history = load_theme_history()
    entries = [
        entry for entry in history.get("entries", [])
        if entry.get("date") and entry.get("theme_id")
    ]

    # If today's Monday theme was already selected, reuse it.
    for entry in entries:
        if entry.get("date") == monday_key:
            return get_theme_by_id(entry.get("theme_id"))

    recent_ids = [entry.get("theme_id") for entry in entries[-8:]]
    candidates = [theme for theme in COLOR_SCHEMES if theme.get("id") not in recent_ids]
    if not candidates:
        candidates = COLOR_SCHEMES[:]

    rng = random.Random(monday_key)
    selected = dict(rng.choice(candidates))

    entries.append({
        "date": monday_key,
        "theme_id": selected.get("id"),
        "theme_name": selected.get("name"),
    })

    history = {
        "site": "NOIZ Theme History",
        "updated_at": current_dt.isoformat(timespec="seconds"),
        "entries": entries[-52:],
    }
    THEME_HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] weekly theme selected: {selected.get('name')}")
    return selected

def archive_payload(payload: dict[str, Any], *, now_dt: datetime | None = None) -> None:
    """Save the existing live NOIZ page before the Monday weekly rollover.

    This function is intentionally called BEFORE generating/writing the new Monday data.
    That way the archive keeps the page that was visible until Monday 09:00 KST,
    and the live data can then roll forward to the new week.
    """
    if not payload or not payload.get("items"):
        print("[INFO] weekly archive skipped: no existing live payload")
        return

    current_dt = now_dt or datetime.now(KST)
    if current_dt.weekday() != 0:
        print(f"[INFO] weekly archive skipped: {current_dt.date()} is not Monday")
        return

    updated_at = str(payload.get("updated_at", ""))
    try:
        payload_dt = datetime.fromisoformat(updated_at)
        if payload_dt.tzinfo is None:
            payload_dt = payload_dt.replace(tzinfo=KST)
    except Exception:
        payload_dt = current_dt - timedelta(days=1)

    # If a manual rerun happens after the Monday rollover already wrote new data,
    # do not archive the new Monday page as if it were the previous week.
    if payload_dt.date() == current_dt.date():
        print("[INFO] weekly archive skipped: live payload is already today's rollover data")
        return

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    archive_key = payload_dt.strftime("%Y-%m-%d")
    archive_file = ARCHIVE_DIR / f"noiz-week-{archive_key}.json"
    archive_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if ARCHIVE_INDEX_PATH.exists():
        try:
            archive_index = json.loads(ARCHIVE_INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            archive_index = {"site": "NOIZ Weekly Archive", "entries": []}
    else:
        archive_index = {"site": "NOIZ Weekly Archive", "entries": []}

    entries_by_date = {
        str(entry.get("date")): entry
        for entry in archive_index.get("entries", [])
        if entry.get("date")
    }
    iso = payload_dt.isocalendar()
    entries_by_date[archive_key] = {
        "date": archive_key,
        "updated_at": payload.get("updated_at"),
        "file": f"./data/archive/noiz-week-{archive_key}.json",
        "label": f"{iso.year} W{iso.week:02d}",
        "snapshot": "before_monday_rollover",
    }

    entries = sorted(entries_by_date.values(), key=lambda entry: str(entry.get("date", "")))
    archive_index = {
        "site": "NOIZ Weekly Archive",
        "updated_at": current_dt.isoformat(timespec="seconds"),
        "entries": entries[-52:],
    }
    ARCHIVE_INDEX_PATH.write_text(json.dumps(archive_index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] archived previous weekly NOIZ snapshot: {archive_file}")
def main() -> None:
    existing = load_existing()
    now_dt = datetime.now(KST)
    archive_payload(existing, now_dt=now_dt)
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))

    official_candidates: list[Candidate] = []

    for source in sources:
        print(f"[INFO] scanning source: {source['name']}")
        official_candidates.extend(extract_candidates_from_source(source))

    print("[INFO] scanning free public search signals as evidence only")
    search_candidates = discover_search_candidates()

    # Cards are official/source-page candidates only.
    # Search/blog/news results are evidence signals only and never become primary cards.
    merged_new = merge_candidates(official_candidates)
    merged_new = enrich_official_items_with_search_evidence(merged_new, search_candidates)
    merged_new = finalize_items(merged_new, now_dt=now_dt)

    items = merge_with_existing(merged_new, existing.get("items", []))
    items = finalize_items(items, now_dt=now_dt)

    theme = existing.get("theme") or LEGACY_THEME

    payload = {
        "site": "NOIZ",
        "updated_at": now_dt.isoformat(timespec="seconds"),
        "theme": theme,
        "weekly_read": make_weekly_read(items),
        "items": items,
        "creator": "이원준 시니어매니저",
        "method_note": "AI 없이 공식/정보 페이지를 카드 기준으로 삼고, 공개 검색·뉴스·후기성 스니펫은 DECIBEL 반응 신호로만 반영하는 일간 CX 레이더야.",
    }

    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] wrote {DATA_PATH} with {len(items)} rankable official/source-page items")


if __name__ == "__main__":
    main()
