#!/usr/bin/env python3
"""
NOIZ updater — free MVP max mode.

핵심 방식
1. 지정 소스 페이지에서 전시/팝업 후보를 넓게 수집한다.
2. 무료 공개 검색 페이지/RSS에서 후보별·키워드별 후기/노출 신호를 추가 수집한다.
3. 후기 축적 전, 오픈 예정, 반응 없음 항목은 랭킹에서 제외한다.
4. 전체 후보군에서 먼저 필터링한 뒤 NOIZ 점수순 Top 10을 만든다.

주의
- GEMINI_API_KEY가 있으면 매일 후보 그룹핑/노이즈 제거에 Gemini를 사용한다.
- API 키가 없거나 Gemini 호출이 실패하면 무료 로컬 그룹핑으로 자동 폴백한다.
- 네이버 플레이스/인스타그램 리뷰 전체 수집은 하지 않는다.
- 결과는 "객관적 평점"이 아니라 공개 노출·후기성 신호 기반 레이더다.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
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
GROUPING_DEBUG_PATH = ROOT / "data" / "noiz-grouping-debug.json"
SOURCES_PATH = ROOT / "scripts" / "sources.json"
KST = timezone(timedelta(hours=9))

# Optional daily AI grouping. Keep empty to use the free local fallback.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

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
    "오픈 예정", "공개 예정", "개최 예정", "전시 예정", "팝업 예정", "예정서울전시",
    "coming soon", "pre-open", "preopen"
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



STOPWORDS = {
    "서울", "수도권", "전시", "전시회", "팝업", "팝업스토어", "스토어", "행사", "후기", "방문",
    "가볼만한곳", "가볼만한", "추천", "일정", "정보", "예약", "오픈", "무료", "관람", "개인전",
    "기획전", "브랜드", "공간", "성수", "여의도", "한남", "청담", "삼청", "중구", "강남", "송파",
    "popup", "pop", "up", "store", "exhibition", "review", "seoul", "visit", "event", "official"
}

NOISE_PAGE_WORDS = [
    "로그인", "회원가입", "개인정보", "이용약관", "공지사항", "전체보기", "더보기",
    "목록", "검색결과", "카테고리", "이벤트 전체", "지난 전시", "사이트맵"
]


def normalize_group_text(text: str) -> str:
    text = clean_text(text).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[\[\](){},./|_<>:;!?\"'“”‘’·•]", " ", text)
    text = re.sub(r"\b(20\d{2})[.\-/년\s]*(\d{1,2})[.\-/월\s]*(\d{1,2})\s*(?:일)?\b", " ", text)
    text = re.sub(r"\b\d{1,2}[.\-/월\s]+\d{1,2}\s*(?:일)?\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def group_tokens(text: str) -> set[str]:
    normalized = normalize_group_text(text)
    tokens = re.findall(r"[a-z0-9]{2,}|[가-힣]{2,}", normalized)
    return {
        token for token in tokens
        if token not in STOPWORDS and len(token) >= 2 and not token.isdigit()
    }


def compact_key_text(text: str) -> str:
    normalized = normalize_group_text(text)
    return re.sub(r"[^0-9a-z가-힣]+", "", normalized)


def title_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, compact_key_text(a), compact_key_text(b)).ratio()


def token_jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def meaningful_venue(venue: str) -> str:
    venue = clean_text(venue)
    generic = {"서울", "서울/수도권", "수도권", "성수", "여의도", "한남", "청담", "삼청", "중구", "강남", "송파", ""}
    return "" if venue in generic else venue


def looks_like_noise_candidate(c: Candidate) -> bool:
    text = " ".join([c.title, c.venue, c.area, c.brand, c.description])
    if any(word in text for word in NOISE_PAGE_WORDS):
        return True
    tokens = group_tokens(text)
    # Too little content and no meaningful venue usually means a generic result page.
    if len(tokens) <= 1 and not meaningful_venue(c.venue):
        return True
    return False


def candidates_same_event(a: Candidate, b: Candidate) -> bool:
    va = meaningful_venue(a.venue)
    vb = meaningful_venue(b.venue)

    # Strong venue conflict guard: don't merge if both have different specific venues
    # and the titles are not extremely similar.
    title_sim = title_similarity(a.title, b.title)
    if va and vb and va != vb and title_sim < 0.86:
        return False

    ta = group_tokens(" ".join([a.title, a.venue, a.area, a.brand]))
    tb = group_tokens(" ".join([b.title, b.venue, b.area, b.brand]))
    jac = token_jaccard(ta, tb)

    same_specific_venue = bool(va and vb and va == vb)
    same_area = bool(a.area and b.area and a.area == b.area)

    if title_sim >= 0.86:
        return True
    if same_specific_venue and jac >= 0.18:
        return True
    if same_specific_venue and title_sim >= 0.54:
        return True
    if same_area and jac >= 0.42:
        return True
    if jac >= 0.52:
        return True

    return False



def truncate_for_ai(text: str, limit: int = 220) -> str:
    text = clean_text(text)
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def normalize_ai_groups(raw_groups: Any, candidates_len: int, *, require_coverage: bool = False) -> list[list[int]] | None:
    """Validate LLM group output and remove duplicate/out-of-range indices.

    By default this is lenient because the model is allowed to exclude noise pages.
    Missing non-noise candidates are handled by the caller as singleton groups.
    """
    if isinstance(raw_groups, dict):
        raw_groups = raw_groups.get("groups")
    if not isinstance(raw_groups, list):
        return None

    seen: set[int] = set()
    groups: list[list[int]] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, list):
            continue
        group: list[int] = []
        for value in raw_group:
            try:
                idx = int(value)
            except Exception:
                continue
            if 0 <= idx < candidates_len and idx not in seen:
                seen.add(idx)
                group.append(idx)
        if group:
            # Very large groups usually mean over-merging. Keep them as singles.
            if len(group) > 18:
                groups.extend([[idx] for idx in group])
            else:
                groups.append(group)

    if not groups:
        return None

    if require_coverage and candidates_len >= 20 and len(seen) < max(5, int(candidates_len * 0.18)):
        return None

    return groups

def extract_json_from_model_text(text: str) -> Any:
    text = clean_text(text)
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except Exception:
        pass

    # Last-resort extraction if a model wraps JSON with a sentence.
    m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if not m:
        raise ValueError("No JSON found in model response")
    return json.loads(m.group(1))


def write_grouping_debug(method: str, candidates: list[Candidate], groups: list[list[Candidate]], dropped: int = 0) -> None:
    try:
        debug = {
            "method": method,
            "model": GEMINI_MODEL if method.startswith("gemini") else "",
            "raw_count": len(candidates),
            "group_count": len(groups),
            "dropped_as_noise": dropped,
            "groups": [
                {
                    "size": len(group),
                    "representative": group[0].title,
                    "venue": group[0].venue,
                    "items": [
                        {
                            "title": item.title,
                            "venue": item.venue,
                            "area": item.area,
                            "brand": item.brand,
                            "noiz": item.noiz,
                        }
                        for item in group[:8]
                    ],
                }
                for group in groups[:80]
            ],
        }
        GROUPING_DEBUG_PATH.write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] grouping debug write failed: {e}")


def request_gemini_group_indices(brief: list[dict[str, Any]], *, offset: int = 0) -> list[list[int]] | None:
    prompt = (
        "You are cleaning search results for NOIZ!, a CX/space planning radar in Korea.\n"
        "Task: group search-result candidates that refer to the same real-world pop-up, exhibition, branded space, "
        "retail activation, or cultural experience. Also exclude obvious noise pages.\n\n"
        "Rules:\n"
        "1. Return JSON only, no markdown.\n"
        "2. Output shape: {\"groups\": [[0,4,12],[1],[2,7]]}.\n"
        "3. Use the local integer indices shown in the data.\n"
        "4. Exclude login pages, generic listing pages, category pages, unrelated news, and results that are not a real event/place.\n"
        "5. Be conservative: do not merge different events just because they are in the same area.\n"
        "6. If two candidates have clearly different specific venues and are not the same titled event, keep them separate.\n"
        "7. Same event can be grouped even when blog-style titles differ, if title, venue, brand, description, or dates indicate the same place/event.\n"
        "8. Include valid but uncertain candidates as singleton groups.\n\n"
        f"Candidates JSON:\n{json.dumps(brief, ensure_ascii=False)}"
    )

    res = requests.post(
        GEMINI_ENDPOINT,
        params={"key": GEMINI_API_KEY},
        headers={
            "x-goog-api-key": GEMINI_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
            },
        },
        timeout=70,
    )
    res.raise_for_status()
    payload = res.json()
    parts = payload["candidates"][0]["content"]["parts"]
    response_text = "\n".join(part.get("text", "") for part in parts).strip()
    raw = extract_json_from_model_text(response_text)
    return normalize_ai_groups(raw, len(brief), require_coverage=False)


def gemini_group_candidates(candidates: list[Candidate]) -> list[list[Candidate]] | None:
    """Use Gemini once per daily update to group same-event candidates and remove obvious noise.

    This makes the live updater AI-assisted, but keeps ranking deterministic:
    Gemini only groups duplicate search results and drops clear non-event pages.
    NOIZ scoring/ranking still runs through the existing rule-based logic.
    """
    if not GEMINI_API_KEY or not candidates:
        return None

    try:
        chunk_size = 80
        all_index_groups: list[list[int]] = []
        used_global_indices: set[int] = set()

        for start_idx in range(0, len(candidates), chunk_size):
            chunk = candidates[start_idx:start_idx + chunk_size]
            brief = [
                {
                    "i": local_i,
                    "title": truncate_for_ai(c.title, 110),
                    "venue": truncate_for_ai(c.venue, 55),
                    "area": truncate_for_ai(c.area, 35),
                    "source": truncate_for_ai(c.brand or c.sourceLabel, 45),
                    "description": truncate_for_ai(c.description, 140),
                }
                for local_i, c in enumerate(chunk)
            ]

            try:
                local_groups = request_gemini_group_indices(brief, offset=start_idx)
            except Exception as chunk_error:
                print(f"[WARN] Gemini chunk failed at {start_idx}, using local singles for this chunk: {chunk_error}")
                local_groups = None

            if local_groups:
                for group in local_groups:
                    global_group = []
                    for local_i in group:
                        global_i = start_idx + local_i
                        if 0 <= global_i < len(candidates) and global_i not in used_global_indices:
                            used_global_indices.add(global_i)
                            global_group.append(global_i)
                    if global_group:
                        all_index_groups.append(global_group)

            # Add missing non-noise candidates as singleton groups.
            for local_i, cand in enumerate(chunk):
                global_i = start_idx + local_i
                if global_i in used_global_indices:
                    continue
                if not looks_like_noise_candidate(cand):
                    used_global_indices.add(global_i)
                    all_index_groups.append([global_i])

        if not all_index_groups:
            raise ValueError("Gemini returned no usable groups")

        groups = [[candidates[i] for i in group] for group in all_index_groups]
        groups = [group for group in groups if group]

        write_grouping_debug(
            "gemini_api_chunked",
            candidates,
            groups,
            dropped=len(candidates) - sum(len(g) for g in groups),
        )
        print(f"[INFO] Gemini grouping: raw={len(candidates)} groups={len(groups)}")
        return groups
    except Exception as e:
        print(f"[WARN] Gemini grouping failed, fallback to free local grouping: {e}")
        return None

def free_group_candidates(candidates: list[Candidate]) -> list[list[Candidate]]:
    """Free local alternative to API-based semantic grouping.

    This is not an LLM. It uses deterministic normalization, token overlap,
    fuzzy title matching, venue/area guards, and noise-page filtering.
    Purpose: merge obvious duplicate signals for the same real-world popup/exhibition
    without requiring a paid API key.
    """
    usable = [c for c in candidates if not looks_like_noise_candidate(c)]
    groups: list[list[Candidate]] = []

    # High-signal candidates first so weaker snippets attach to a clearer representative.
    usable = sorted(
        usable,
        key=lambda c: (c.noiz, c.evidenceCount, c.reactionCount, len(group_tokens(c.title))),
        reverse=True,
    )

    for cand in usable:
        best_idx = -1
        best_score = 0.0
        for idx, group in enumerate(groups):
            representative = group[0]
            if not candidates_same_event(cand, representative):
                continue
            score = (
                title_similarity(cand.title, representative.title) * 0.55 +
                token_jaccard(
                    group_tokens(" ".join([cand.title, cand.venue, cand.area, cand.brand])),
                    group_tokens(" ".join([representative.title, representative.venue, representative.area, representative.brand])),
                ) * 0.45
            )
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx >= 0:
            groups[best_idx].append(cand)
        else:
            groups.append([cand])

    write_grouping_debug(
        "free_local_semantic_grouping",
        candidates,
        groups,
        dropped=len(candidates) - len(usable),
    )
    print(f"[INFO] free grouping: raw={len(candidates)} usable={len(usable)} groups={len(groups)}")
    return groups



SEARCH_SOURCE_NAMES = {"Naver View", "Google News", "Web Search"}


def is_search_source_name(name: str) -> bool:
    return clean_text(name) in SEARCH_SOURCE_NAMES


def is_review_or_search_url(url: str) -> bool:
    url = str(url or "").lower()
    review_domains = [
        "blog.naver.com",
        "post.naver.com",
        "cafe.naver.com",
        "news.google.com",
        "search.naver.com",
        "html.duckduckgo.com",
    ]
    return any(domain in url for domain in review_domains)


def candidate_is_official_source(c: Candidate) -> bool:
    if not c.sourceUrl or not str(c.sourceUrl).startswith("http"):
        return False
    if is_search_source_name(c.brand):
        return False
    if is_review_or_search_url(c.sourceUrl):
        return False
    return True


def preferred_official_candidate(group: list[Candidate]) -> Candidate | None:
    official = [c for c in group if candidate_is_official_source(c)]
    if not official:
        return None

    # Prefer source/detail pages with dates and specific venue, then higher base signal.
    official.sort(
        key=lambda c: (
            1 if (c.start or c.end) else 0,
            1 if meaningful_venue(c.venue) else 0,
            c.noiz,
            len(clean_text(c.title)),
        ),
        reverse=True,
    )
    return official[0]


def group_has_current_period(group: list[Candidate]) -> bool:
    for c in group:
        if c.start or c.end:
            return True
    return False


def source_labels_for_group(group: list[Candidate]) -> list[str]:
    official_labels: list[str] = []
    search_labels: list[str] = []
    for g in group:
        label = clean_text(g.brand)
        if not label:
            continue
        target = search_labels if is_search_source_name(label) else official_labels
        if label not in target:
            target.append(label)
    return official_labels + search_labels


def item_link_is_non_official(item: dict[str, Any]) -> bool:
    url = item.get("officialSourceUrl") or item.get("sourceUrl") or ""
    if not url:
        return True
    if is_review_or_search_url(str(url)):
        return True
    brand = str(item.get("brand", ""))
    if any(name in brand for name in SEARCH_SOURCE_NAMES):
        return True
    return False


def official_match_score(item: dict[str, Any], c: Candidate) -> float:
    item_title = " ".join([
        str(item.get("title", "")),
        str(item.get("rawTitle", "")),
    ])
    cand_title = c.title
    title_sim = max(
        title_similarity(item_title, cand_title),
        title_similarity(str(item.get("title", "")), cand_title),
        title_similarity(str(item.get("rawTitle", "")), cand_title),
    )
    item_tokens = group_tokens(" ".join([
        str(item.get("title", "")),
        str(item.get("rawTitle", "")),
        str(item.get("venue", "")),
        str(item.get("area", "")),
    ]))
    cand_tokens = group_tokens(" ".join([c.title, c.venue, c.area, c.brand]))
    jac = token_jaccard(item_tokens, cand_tokens)

    item_venue = meaningful_venue(str(item.get("venue", "")))
    cand_venue = meaningful_venue(c.venue)
    same_venue = bool(item_venue and cand_venue and item_venue == cand_venue)
    same_area = bool(item.get("area") and c.area and item.get("area") == c.area)

    score = title_sim * 0.58 + jac * 0.32
    if same_venue:
        score += 0.18
    if same_area:
        score += 0.08
    if c.start or c.end:
        score += 0.05
    return score


def assign_official_links(items: list[dict[str, Any]], candidates: list[Candidate]) -> list[dict[str, Any]]:
    """Make card title links point to official/source-detail pages, not review posts.

    Search/blog/news candidates are useful as evidence, but final card links should go
    to official or event-information pages whenever a matching source candidate exists.
    """
    official_candidates = [c for c in candidates if candidate_is_official_source(c)]
    if not official_candidates:
        return items

    for item in items:
        current_url = item.get("officialSourceUrl") or item.get("sourceUrl")
        if current_url and not item_link_is_non_official(item):
            continue

        best: Candidate | None = None
        best_score = 0.0
        for c in official_candidates:
            score = official_match_score(item, c)
            if score > best_score:
                best_score = score
                best = c

        # Keep threshold conservative to avoid linking to the wrong official page.
        if best and best_score >= 0.42:
            item["sourceUrl"] = best.sourceUrl
            item["officialSourceUrl"] = best.sourceUrl
            item["sourceLabel"] = "공식/정보 페이지"
            item["officialSourceName"] = best.brand
            if item_link_is_non_official(item):
                item["brand"] = best.brand
            if best.venue and (not item.get("venue") or item.get("venue") == "서울/수도권"):
                item["venue"] = best.venue
            if best.area and (not item.get("area") or item.get("area") == "서울/수도권"):
                item["area"] = best.area
                item["region"] = best.area
            for field in ["start", "end"]:
                if getattr(best, field, "") and not item.get(field):
                    item[field] = getattr(best, field)
            item["linkResolved"] = True
        else:
            # Never leave a blog/review URL on the title. Fall back to a search for the official page.
            query = quote_plus(" ".join([
                str(item.get("title", "")),
                str(item.get("venue", "")),
                "공식",
            ]).strip())
            if item_link_is_non_official(item):
                item["sourceUrl"] = f"https://www.google.com/search?q={query}"
                item["sourceLabel"] = "공식 페이지 검색"
                item["linkResolved"] = False

    return items



def strip_date_noise_from_title(title: str) -> str:
    t = clean_text(str(title or "")).replace("_", " ")
    # Remove explicit date ranges often embedded in source titles.
    t = re.sub(r"\s*(?:20)?\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\s*[-~–—]\s*(?:20)?\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\s*$", "", t)
    t = re.sub(r"\s*(?:20)?\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\s*[-~–—]\s*\d{1,2}[.\-/]\d{1,2}\s*$", "", t)
    t = re.sub(r"\s*\d{1,2}[.\-/]\d{1,2}\s*[-~–—]\s*\d{1,2}[.\-/]\d{1,2}\s*$", "", t)
    t = re.sub(r"\s*20\d{2}\.\d{1,2}\.\d{1,2}.*$", "", t)
    t = re.sub(r"\s*기간\s*[:：]?\s*.*$", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def clean_official_display_title(title: str) -> str:
    """Keep the previous card format: actual event title, not source slug or date-heavy text."""
    t = strip_date_noise_from_title(title)
    t = t.replace("예정서울전시", " ").replace("예정 서울전시", " ")
    t = t.replace("서울전시", " ").replace("무료입장", " ").replace("무료 전시", " ")
    t = re.sub(r"\bALT\s*:\s*\d+\b", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -_·|")
    # Remove duplicated trailing venue chunks only when the title is too long.
    if len(t) > 55:
        t = re.sub(r"\s+(더현대서울현대백화점|그라운드시소\s*이스트|서울시립미술관|국립현대미술관).*$", "", t).strip()
    return t or clean_text(title)


def official_candidates_same_event(a: Candidate, b: Candidate) -> bool:
    """Stricter rule for preventing Popga/Ddoing/GroundSeesaw pages from over-merging."""
    title_sim = title_similarity(a.title, b.title)
    ta = group_tokens(" ".join([a.title, a.venue, a.area]))
    tb = group_tokens(" ".join([b.title, b.venue, b.area]))
    jac = token_jaccard(ta, tb)
    va = meaningful_venue(a.venue)
    vb = meaningful_venue(b.venue)

    if va and vb and va != vb and title_sim < 0.88:
        return False
    if title_sim >= 0.82:
        return True
    if va and vb and va == vb and title_sim >= 0.58 and jac >= 0.18:
        return True
    return False


def candidate_to_official_score(candidate: Candidate, official: Candidate) -> float:
    title_sim = title_similarity(candidate.title, official.title)
    jac = token_jaccard(
        group_tokens(" ".join([candidate.title, candidate.venue, candidate.area, candidate.brand])),
        group_tokens(" ".join([official.title, official.venue, official.area, official.brand])),
    )
    same_venue = bool(meaningful_venue(candidate.venue) and meaningful_venue(candidate.venue) == meaningful_venue(official.venue))
    same_area = bool(candidate.area and official.area and candidate.area == official.area)
    score = title_sim * 0.62 + jac * 0.30
    if same_venue:
        score += 0.18
    if same_area:
        score += 0.05
    return score


def split_overmerged_groups(groups: list[list[Candidate]]) -> list[list[Candidate]]:
    """Split AI/local groups when unrelated official source pages were merged together."""
    fixed: list[list[Candidate]] = []

    for group in groups:
        official = [c for c in group if candidate_is_official_source(c)]
        non_official = [c for c in group if not candidate_is_official_source(c)]

        if len(official) <= 1:
            fixed.append(group)
            continue

        clusters: list[list[Candidate]] = []
        for cand in official:
            placed = False
            for cluster in clusters:
                if official_candidates_same_event(cand, cluster[0]):
                    cluster.append(cand)
                    placed = True
                    break
            if not placed:
                clusters.append([cand])

        # Attach review/search evidence to the best matching official cluster.
        loose: list[Candidate] = []
        for cand in non_official:
            best_idx = -1
            best_score = 0.0
            for idx, cluster in enumerate(clusters):
                score = max(candidate_to_official_score(cand, official_c) for official_c in cluster)
                if score > best_score:
                    best_score = score
                    best_idx = idx
            if best_idx >= 0 and best_score >= 0.36:
                clusters[best_idx].append(cand)
            else:
                loose.append(cand)

        fixed.extend(clusters)
        fixed.extend([[cand] for cand in loose])

    if len(fixed) != len(groups):
        print(f"[INFO] split overmerged groups: {len(groups)} -> {len(fixed)}")
    return fixed



def enrich_official_items_with_search_evidence(items: list[dict[str, Any]], candidates: list[Candidate]) -> list[dict[str, Any]]:
    """Attach review/search/news evidence to official/source-page cards.

    This preserves the old good format: the card is the real exhibition/popup page,
    while blog/news/search results only raise DECIBEL and reaction confidence.
    """
    search_candidates = [c for c in candidates if not candidate_is_official_source(c)]
    if not search_candidates:
        return items

    for item in items:
        if not item.get("hasOfficialSource"):
            continue

        matches: list[Candidate] = []
        for cand in search_candidates:
            score = official_match_score(item, cand)
            if score >= 0.34:
                matches.append(cand)

        if not matches:
            continue

        evidence_count = int(item.get("evidenceCount", 1)) + sum(max(1, c.evidenceCount) for c in matches)
        reaction_count = int(item.get("reactionCount", 0)) + sum(max(0, c.reactionCount) for c in matches)
        text_blob = " ".join(
            [
                str(item.get("title", "")),
                str(item.get("rawTitle", "")),
                str(item.get("description", "")),
                " ".join(str(s) for s in item.get("signals", [])),
            ]
            + [
                " ".join([
                    c.title,
                    c.description,
                    " ".join(str(s) for s in c.signals),
                    c.brand,
                    c.area,
                ])
                for c in matches
            ]
        )

        base_score = max(35, min(86, int(item.get("noiz", 45)) - 6))
        noiz, favor, signals, info_volume, confidence = text_score(
            text_blob,
            base=base_score,
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
        item["owner"] = f"공개 노출 {evidence_count}건 · 후기성 신호 {reaction_count}건"
        item["evidenceSources"] = sorted({c.brand for c in matches if c.brand})[:4]
        item["description"] = make_description(
            str(item.get("title", "")),
            evidence_count,
            reaction_count,
            str(item.get("area") or item.get("region") or "서울/수도권"),
        )

    return items


def merge_candidates(candidates: list[Candidate]) -> list[dict[str, Any]]:
    # Gemini is optional. If no key is configured or the API fails, use the free local fallback.
    try:
        groups = gemini_group_candidates(candidates)
        if groups is None:
            groups = free_group_candidates(candidates)
    except Exception as e:
        print(f"[WARN] grouping failed, fallback to candidate_key grouping: {e}")
        grouped: dict[str, list[Candidate]] = {}
        for c in candidates:
            key = candidate_key(c.title)
            grouped.setdefault(key, []).append(c)
        groups = list(grouped.values())

    groups = split_overmerged_groups(groups)

    merged: list[dict[str, Any]] = []
    for group in groups:
        group = sorted(group, key=lambda c: c.noiz, reverse=True)
        official_source = preferred_official_candidate(group)
        best = asdict(group[0])
        best["rawTitle"] = best.get("title", "")
        best["hasOfficialSource"] = bool(official_source)
        best["searchOnlyEvidence"] = not bool(official_source) and not group_has_current_period(group)

        if official_source:
            best["title"] = clean_official_display_title(official_source.title)
            best["sourceUrl"] = official_source.sourceUrl
            best["officialSourceUrl"] = official_source.sourceUrl
            best["officialSourceName"] = official_source.brand
            best["sourceLabel"] = "공식/정보 페이지"
            if official_source.venue:
                best["venue"] = official_source.venue
            if official_source.area:
                best["area"] = official_source.area
                best["region"] = official_source.area
            if official_source.start and not best.get("start"):
                best["start"] = official_source.start
            if official_source.end and not best.get("end"):
                best["end"] = official_source.end

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

        source_labels = source_labels_for_group(group)

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



def parse_iso_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=KST)
    except Exception:
        return None


def item_text_for_filter(item: dict[str, Any]) -> str:
    return " ".join([
        str(item.get("rawTitle", "")),
        str(item.get("title", "")),
        str(item.get("description", "")),
        str(item.get("venue", "")),
        str(item.get("area", "")),
        str(item.get("region", "")),
        " ".join(str(s) for s in item.get("signals", [])),
    ])


def has_stale_month_marker(text: str, now_dt: datetime | None = None) -> bool:
    """Detect old month-specific blog/search results when no full end date is available.

    This catches cases like old January popup reviews resurfacing in July search results.
    It intentionally avoids filtering texts that explicitly say ongoing/current/permanent.
    """
    now_dt = now_dt or datetime.now(KST)
    source = clean_text(text)
    if not source:
        return False

    ongoing_words = ["상설", "진행중", "진행 중", "현재", "ongoing", "until", "까지", "연장"]
    if any(word.lower() in source.lower() for word in ongoing_words):
        return False

    # Explicit year-month mentions: 2026년 1월 / 2026.01 / 2026-01
    explicit_patterns = [
        r"(20\d{2})\s*년\s*(1[0-2]|0?[1-9])\s*월",
        r"(20\d{2})[.\-/](1[0-2]|0?[1-9])(?:[.\-/월\s]|$)",
    ]
    for pattern in explicit_patterns:
        for m in re.finditer(pattern, source):
            year = int(m.group(1))
            month = int(m.group(2))
            if year < now_dt.year:
                return True
            if year == now_dt.year and month <= now_dt.month - 2:
                return True

    # Month-only blog titles like "1월 성수 팝업 후기" are stale in July unless current-context words are present.
    if "후기" in source or "다녀" in source or "방문" in source:
        for m in re.finditer(r"(?<!\d)(1[0-2]|0?[1-9])\s*월", source):
            month = int(m.group(1))
            if month <= now_dt.month - 3:
                return True

    return False


def is_temporally_rankable_item(item: dict[str, Any], now_dt: datetime | None = None) -> bool:
    now_dt = now_dt or datetime.now(KST)
    today = now_dt.date()
    start = parse_iso_date(item.get("start") or item.get("startDate") or item.get("openDate"))
    end = parse_iso_date(item.get("end") or item.get("endDate") or item.get("closeDate"))
    text = item_text_for_filter(item)

    if end and end.date() < today:
        return False

    # Future-only items are not this week's public reaction yet.
    # NOIZ ranks currently open/ongoing spaces; upcoming items can be picked up after opening.
    if start and start.date() > today:
        return False

    # If only an opening/start date is visible and it is very old, avoid ranking stale blog reviews.
    if start and not end and start.date() < today - timedelta(days=120):
        return False

    if not start and not end and has_stale_month_marker(text, now_dt=now_dt):
        return False

    return True


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
    # Search/blog/news-only items are evidence signals, not primary NOIZ cards.
    # Cards should represent actual popup/exhibition/source pages, not review posts.
    if item.get("searchOnlyEvidence") is True:
        return False
    if item_link_is_non_official(item) and not item.get("hasOfficialSource"):
        return False
    if not is_temporally_rankable_item(item):
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

    # Existing payload is only a safety fallback when the fresh crawl is too thin.
    # Do not let old ended popups/exhibitions keep ranking just because they were in yesterday's JSON.
    if len(new_items) < 12:
        for old in existing_items:
            old.setdefault("infoVolume", "medium")
            signals_text = " ".join(old.get("signals", []))
            old.setdefault("reactionCount", 0 if ("후기 축적 전" in signals_text or "후기 부족" in signals_text) else 1)
            old.setdefault("evidenceCount", 2 if old.get("reactionCount", 0) else 1)
            old.setdefault("confidence", "medium" if old.get("reactionCount", 0) else "low")
            if not is_temporally_rankable_item(old):
                continue
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



REVIEW_TITLE_PATTERNS = [
    r"\s*방문\s*후기.*$",
    r"\s*관람\s*후기.*$",
    r"\s*다녀왔(?:어요|다).*$",
    r"\s*후기.*$",
    r"\s*추천.*$",
    r"\s*가볼\s*만한.*$",
    r"\s*가볼만한.*$",
]


def fallback_clean_display_title(title: str) -> str:
    """Local fallback for blog-style titles when Gemini refinement is unavailable."""
    original = clean_official_display_title(title)
    t = original

    # Prefer strong all-caps English event/brand phrase near the end.
    caps = re.findall(r"\b[A-Z][A-Z0-9&+.'-]*(?:\s+[A-Z][A-Z0-9&+.'-]*){0,5}\b", t)
    if caps:
        pick = caps[-1].strip()
        if 3 <= len(pick) <= 48:
            # Include obvious place/type suffix when present after the caps phrase.
            suffix_match = re.search(re.escape(pick) + r"\s*((?:성수|용산|한남|더현대|서울|팝업|전시|스토어|매장|공간)[가-힣A-Za-z0-9\s]{0,18})", t)
            if suffix_match:
                suffix = clean_text(suffix_match.group(1))
                if suffix:
                    return clean_text(f"{pick} {suffix}")
            return pick

    # Remove common review/blog tail language.
    for pattern in REVIEW_TITLE_PATTERNS:
        t = re.sub(pattern, "", t, flags=re.I).strip()

    # Remove common lead-in expressions while keeping the place/event phrase.
    t = re.sub(r"^(나처럼|직접|요즘|이번\s*주|서울|성수|한남|용산|더현대|홍대|삼청)\s+", "", t).strip()
    t = re.sub(r"(좋아한다면|좋아하면|관심있다면|가볼\s*만한|가볼만한)\s+", "", t).strip()
    t = re.sub(r"\s+", " ", t).strip()

    return t if 3 <= len(t) <= 55 else original


def fallback_refine_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in items:
        raw_title = item.get("rawTitle") or item.get("title", "")
        cleaned = fallback_clean_display_title(raw_title)
        if cleaned:
            item["title"] = cleaned

        area = item.get("area") or item.get("region") or "서울/수도권"
        kind = classify_experience_type(item)
        if kind == "전시/문화 경험":
            item["description"] = f"{area}권에서 관람 신호가 포착된 전시/문화 경험 후보. 작품·기관·방문 후기가 함께 잡히는지 확인할 만해."
        elif kind == "팝업/브랜드 경험":
            item["description"] = f"{area}권에서 반응이 포착된 팝업/브랜드 경험 후보. 굿즈, 체험 요소, 방문 후기의 강도를 함께 볼 만해."
        else:
            item["description"] = f"{area}권에서 공개 반응이 포착된 공간 경험 후보. 이번 주 벤치마크로 확인할 만한 신호가 있어."
        item["aiRefined"] = False
    return items


def gemini_refine_items_and_summary(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    """Use Gemini to turn raw search/blog titles into clean event cards and a natural weekly read.

    Gemini does not change DECIBEL scoring/ranking here. It only rewrites:
    - display title: actual popup/exhibition/space name, not blog-review title
    - description: what the space/event seems to be
    - weekly_read: natural editorial summary
    """
    if not GEMINI_API_KEY or not items:
        return fallback_refine_items(items), None

    brief = []
    for item in items[:10]:
        brief.append({
            "rank": item.get("rank"),
            "rawTitle": truncate_for_ai(item.get("rawTitle") or item.get("title", ""), 150),
            "title": truncate_for_ai(item.get("title", ""), 150),
            "venue": truncate_for_ai(item.get("venue", ""), 70),
            "area": truncate_for_ai(item.get("area") or item.get("region", ""), 50),
            "source": truncate_for_ai(item.get("brand", ""), 70),
            "signals": item.get("signals", []),
            "decibel": item.get("noiz"),
            "evidenceCount": item.get("evidenceCount", 0),
            "reactionCount": item.get("reactionCount", 0),
            "start": item.get("start", ""),
            "end": item.get("end", ""),
            "description": truncate_for_ai(item.get("description", ""), 180),
        })

    prompt = (
        "NOIZ!는 CX·스페이스 기획자를 위한 팝업/전시/브랜드 공간 리서치 레이더다.\n"
        "아래 Top 10 후보는 공개 검색/블로그/뉴스 신호에서 잡힌 항목이라 제목이 블로그 후기처럼 지저분할 수 있다.\n\n"
        "해야 할 일:\n"
        "1. 각 후보의 display title을 실제 팝업, 전시, 브랜드 공간 이름처럼 정리해라.\n"
        "   - '후기', '방문 후기', '다녀왔어요', '추천', '가볼만한' 같은 블로그 문구는 제거.\n"
        "   - 확실한 브랜드/전시명이 보이면 그것을 우선 사용.\n"
        "   - 모호하면 과하게 창작하지 말고 원제목을 조금만 정리.\n"
        "2. description은 '공개 노출 4건' 같은 시스템 설명이 아니라, 공간/전시/팝업이 무엇인지 설명하는 1문장으로 써라.\n"
        "3. weekly_read는 키워드 나열이 아니라, 이번 주 공간 신호를 사람이 쓴 에디토리얼 톤으로 2~3문장 요약해라.\n"
        "4. 끝난 1월/과거 팝업처럼 보이는 항목은 title/description에서 과거 후기처럼 보이지 않게 과장하지 마라.\n"
        "5. 점수, 순위, DECIBEL 숫자는 바꾸지 마라.\n"
        "6. 링크는 후기 글이 아니라 공식/정보 페이지를 우선 사용한다. URL은 입력에 없으면 만들지 마라.\n"
        "7. JSON만 출력해라.\n\n"
        "출력 형식:\n"
        "{\n"
        "  \"weekly_read\": \"...\",\n"
        "  \"items\": [\n"
        "    {\"rank\": 1, \"title\": \"...\", \"venue\": \"...\", \"area\": \"...\", \"description\": \"...\", \"category\": \"팝업/브랜드 경험\"}\n"
        "  ]\n"
        "}\n\n"
        f"입력 후보:\n{json.dumps(brief, ensure_ascii=False)}"
    )

    try:
        res = requests.post(
            GEMINI_ENDPOINT,
            params={"key": GEMINI_API_KEY},
            headers={
                "x-goog-api-key": GEMINI_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 4096,
                    "responseMimeType": "application/json",
                },
            },
            timeout=70,
        )
        res.raise_for_status()
        payload = res.json()
        parts = payload["candidates"][0]["content"]["parts"]
        response_text = "\n".join(part.get("text", "") for part in parts).strip()
        parsed = extract_json_from_model_text(response_text)
        if not isinstance(parsed, dict):
            raise ValueError("Gemini refinement output is not an object")

        refined_by_rank: dict[int, dict[str, Any]] = {}
        for refined in parsed.get("items", []):
            if not isinstance(refined, dict):
                continue
            try:
                rank = int(refined.get("rank"))
            except Exception:
                continue
            refined_by_rank[rank] = refined

        for item in items:
            try:
                rank = int(item.get("rank"))
            except Exception:
                continue
            refined = refined_by_rank.get(rank)
            if not refined:
                continue

            title = clean_text(refined.get("title", ""))
            description = clean_text(refined.get("description", ""))
            venue = clean_text(refined.get("venue", ""))
            area = clean_text(refined.get("area", ""))
            category = clean_text(refined.get("category", ""))

            if title:
                item["title"] = clean_official_display_title(fallback_clean_display_title(title))
            else:
                item["title"] = clean_official_display_title(item.get("title", ""))
            if description:
                item["description"] = description
            if venue:
                item["venue"] = venue
            if area:
                item["area"] = area
                item["region"] = area
            if category:
                item["category"] = category
            item["aiRefined"] = True

        weekly_read = clean_text(parsed.get("weekly_read", ""))
        print("[INFO] Gemini refinement: card titles/descriptions and weekly_read updated")
        return items, weekly_read or None
    except Exception as e:
        print(f"[WARN] Gemini refinement failed, using local display cleanup: {e}")
        return fallback_refine_items(items), None


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

    candidates: list[Candidate] = []

    for source in sources:
        print(f"[INFO] scanning source: {source['name']}")
        candidates.extend(extract_candidates_from_source(source))

    print("[INFO] scanning free public search signals")
    candidates.extend(discover_search_candidates())

    merged_new = merge_candidates(candidates)
    merged_new = enrich_official_items_with_search_evidence(merged_new, candidates)
    items = merge_with_existing(merged_new, existing.get("items", []))
    items, ai_weekly_read = gemini_refine_items_and_summary(items)
    items = assign_official_links(items, candidates)
    items = [item for item in items if is_rankable_item(item)]
    for i, item in enumerate(items[:10], 1):
        item["rank"] = i
        item["title"] = clean_official_display_title(item.get("title", ""))
    items = items[:10]
    theme = existing.get("theme") or LEGACY_THEME

    payload = {
        "site": "NOIZ",
        "updated_at": now_dt.isoformat(timespec="seconds"),
        "theme": theme,
        "weekly_read": ai_weekly_read or make_weekly_read(items),
        "items": items,
        "creator": "이원준 시니어매니저",
        "method_note": "무료 공개 소스, 검색 결과, 뉴스 RSS, 블로그/후기성 스니펫을 바탕으로 본 주간 신호 레이더야. 객관적 평점이라기보다는 지금 어디가 시끄러운지 읽는 용도야!",
    }

    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] wrote {DATA_PATH} with {len(items)} rankable items")


if __name__ == "__main__":
    main()
