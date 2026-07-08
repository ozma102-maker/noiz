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


TAG_KO = {
    "painting": "회화",
    "sculpture": "조각",
    "photography": "사진",
    "video": "영상",
    "media": "미디어",
    "sound": "사운드",
    "installation": "설치",
    "archive": "아카이브",
    "conceptual": "개념미술",
    "contemporary": "동시대미술",
    "solo": "개인전",
    "group": "그룹전",
    "museum": "미술관 전시",
    "gallery": "갤러리 전시",
    "korean modern": "한국 근현대",
    "young artist": "젊은 작가",
    "old masters": "고전 명작",
    "modern": "근대미술",
    "institution": "기관 전시",
    "design": "디자인",
    "illustration": "일러스트레이션",
    "family": "가족 관람",
    "collection": "소장품",
}

KNOWN_DESCRIPTIONS = {
    "Katherine Bradford: Living a Dream": "몽환적인 색면과 느슨한 인물 형상이 중심이 되는 회화 전시. 꿈, 밤, 물, 몸의 감각이 섞인 장면을 통해 일상적인 풍경을 비현실적인 분위기로 밀어붙인다.",
    "유영국: A Mountain Within Me": "산과 자연을 추상 회화의 구조로 밀어붙인 유영국의 대규모 전시. 색면, 리듬, 형태가 어떻게 한국 근현대 추상의 핵심 언어가 되는지 보기 좋다.",
    "This is (Not) Conceptual Art": "개념미술을 둘러싼 언어, 제도, 기록의 방식을 살피는 기획전. 작품이 물성보다 아이디어와 맥락으로 작동하는 순간을 보여준다.",
    "Objects in Oscillation / 진동하는 사물들": "사진과 사물이 서로의 경계를 흔드는 그룹전. 이미지가 단순한 재현을 넘어 물성, 표면, 시간의 감각으로 확장되는 지점을 다룬다.",
    "The Poetics of Form / 형태의 시학": "로버트 메이플소프의 사진이 가진 조형성과 균형감을 중심으로 보는 전시. 인물, 신체, 사물의 형태가 고전적인 긴장감으로 정리된다.",
    "Before It Becomes a Scene": "이근민의 회화가 장면으로 고정되기 직전의 불안정한 형상과 감각을 보여주는 개인전. 인물, 환각, 심리적 압력이 뒤엉키는 지점이 핵심이다.",
    "SAUVE QUI PEUT": "여러 작가의 작업을 통해 불안정한 시대의 감각과 생존의 태도를 묶어보는 그룹전. 하나의 주제보다 서로 다른 시각적 긴장이 만들어내는 분위기가 중요하다.",
    "조각의 바깥에서 At the Edge of Sculpture": "이승택의 조각적 실험을 통해 조각이 물질, 행위, 공간으로 확장되는 방식을 보여주는 전시. 전통적인 조각 개념의 바깥을 확인할 수 있다.",
    "권병준: 내 마음속에 너는": "소리, 기계, 신체 감각이 결합된 미디어아트 전시. 보는 전시라기보다 듣고 움직이며 체감하는 경험에 가깝다.",
    "Endoskopeia": "송은에서 진행되는 동시대미술 전시. 내면을 들여다보는 듯한 제목처럼 시선, 구조, 감각의 안쪽을 탐색하는 흐름으로 읽힌다.",
    "렘브란트에서 고야까지 : 톨레도 미술관 명작展": "렘브란트, 고야 등 서양미술사의 주요 작가들을 통해 고전 회화의 밀도와 시대적 변화를 확인하는 명작전.",
    "The Cubists: Inventing Modern Vision": "입체주의를 중심으로 근대적 시각이 어떻게 분해되고 재구성되었는지 보여주는 전시. 피카소와 브라크 이후의 시각 언어를 따라가기 좋다.",
}


def scrub_personal_framing(text: str) -> str:
    if not isinstance(text, str):
        return text
    text = re.sub(r"\uC0AC\uC6A9\uC790\uC758[^.。]*[.。]?", "", text)
    text = re.sub(r"\uCEEC\uB809\uC158 \uAD00\uC2EC\uC0AC\uC640\uB3C4 \uC9C1\uC811 \uC5F0\uACB0\uB418\uB294[^.。]*[.。]?", "", text)
    return re.sub(r"\s+", " ", text).strip()

def make_exhibition_description(raw: dict[str, Any]) -> str:
    title = raw.get("title", "이 전시")
    if title in KNOWN_DESCRIPTIONS:
        return KNOWN_DESCRIPTIONS[title]
    if raw.get("editorialDescription"):
        return raw["editorialDescription"]

    artist = raw.get("artist") or raw.get("brand") or ""
    tags = raw.get("tags", []) or []
    ko_tags = []
    for tag in tags:
        value = TAG_KO.get(str(tag), str(tag))
        if value and value not in ko_tags:
            ko_tags.append(value)
    ko_tags = ko_tags[:3]

    if "group" in tags:
        who = "여러 작가의 작업을 묶어"
    elif artist and artist not in ["Group exhibition", "TBC"]:
        who = f"{artist}의 작업을 중심으로"
    else:
        who = "동시대 작가들의 작업을 중심으로"

    medium = "·".join(ko_tags) if ko_tags else "동시대미술"
    venue_type = raw.get("venueType", "")
    if venue_type == "museum":
        frame = "미술관 규모의 맥락 안에서"
    elif venue_type == "gallery":
        frame = "갤러리 공간의 밀도 안에서"
    elif venue_type == "nonprofit":
        frame = "대안공간 특유의 실험성 안에서"
    else:
        frame = "전시 공간 안에서"

    return f"{who} {medium}의 흐름을 보여주는 전시. {frame} 작품의 형식과 분위기를 함께 읽어볼 수 있다."



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


def make_exhibition_overview(raw: dict[str, Any]) -> str:
    title = raw.get("title", "")
    known = {
        "Katherine Bradford: Living a Dream": "몽환적 색면과 느슨한 인물 형상이 중심이 되는 회화 전시.",
        "유영국: A Mountain Within Me": "산과 자연을 추상 회화의 구조로 밀어붙인 유영국 회고적 전시.",
        "This is (Not) Conceptual Art": "개념미술의 언어와 제도적 맥락을 살피는 기획전.",
        "Objects in Oscillation / 진동하는 사물들": "사진과 사물의 경계를 흔드는 사진 중심 그룹전.",
        "The Poetics of Form / 형태의 시학": "로버트 메이플소프 사진의 조형성과 균형감을 보는 전시.",
        "Before It Becomes a Scene": "이근민 회화의 불안정한 형상과 심리적 긴장을 다루는 개인전.",
        "SAUVE QUI PEUT": "불안정한 시대의 감각과 생존의 태도를 묶어보는 그룹전.",
        "조각의 바깥에서 At the Edge of Sculpture": "이승택의 조각적 실험과 확장된 조각 개념을 보는 전시.",
        "권병준: 내 마음속에 너는": "소리와 신체 감각이 결합된 체험형 미디어아트 전시.",
        "Endoskopeia": "시선과 감각의 안쪽을 탐색하는 동시대미술 전시.",
        "렘브란트에서 고야까지 : 톨레도 미술관 명작展": "서양 고전 회화의 밀도와 시대적 변화를 보는 명작전.",
        "The Cubists: Inventing Modern Vision": "입체주의를 통해 근대적 시각의 분해와 재구성을 보는 전시.",
    }
    if title in known:
        return known[title]
    if raw.get("overview"):
        return raw["overview"]
    desc = make_exhibition_description(raw)
    return re.split(r"(?<=다\.)\s|(?<=[.!?。])\s", desc)[0][:90]

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
        "owner": f"{venue_ko} 전시",
        "venue": venue_ko,
        "area": area_ko,
        "region": region_ko,
        "mapQuery": venue_ko,
        "sourceUrl": raw.get("url") or "#",
        "sourceLabel": "정보 출처",
        "overview": make_exhibition_overview(raw),
        "noiz": noiz,
        "favorability": favor,
        "description": scrub_personal_framing(make_exhibition_description(raw)),
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
    ranked = sorted(items, key=lambda x: int(x.get("noiz", 0)), reverse=True)[:10]
    if not ranked:
        return "현재는 아직 뚜렷하게 잡히는 전시 신호가 많지 않아. 조금 더 쌓이면 바로 읽어볼게!"

    areas: dict[str, int] = {}
    venue_types: dict[str, int] = {"미술관": 0, "갤러리": 0, "전시공간": 0}
    mediums: dict[str, int] = {}

    def medium(item: dict[str, Any]) -> str:
        text = " ".join([
            item.get("title", ""),
            item.get("description", ""),
            item.get("overview", ""),
            " ".join(item.get("signals", [])),
            " ".join(item.get("tags", [])),
        ]).lower()
        if any(x in text for x in ["회화", "painting", "색면", "추상"]):
            return "회화"
        if any(x in text for x in ["사진", "photography", "메이플소프"]):
            return "사진"
        if any(x in text for x in ["조각", "sculpture"]):
            return "조각"
        if any(x in text for x in ["미디어", "영상", "sound", "사운드"]):
            return "미디어"
        if any(x in text for x in ["명작", "고야", "렘브란트", "입체주의", "cubist", "modern"]):
            return "미술사/명작"
        return "동시대미술"

    for item in ranked:
        area = item.get("area") or item.get("region") or "서울/수도권"
        areas[area] = areas.get(area, 0) + 1
        vt = item.get("venueType", "")
        sig = " ".join(item.get("signals", []))
        if vt == "museum" or "미술관" in sig:
            venue_types["미술관"] += 1
        elif vt == "gallery" or "갤러리" in sig:
            venue_types["갤러리"] += 1
        else:
            venue_types["전시공간"] += 1
        m = medium(item)
        mediums[m] = mediums.get(m, 0) + 1

    area_line = "·".join(sorted(areas, key=areas.get, reverse=True)[:3])
    medium_line = "·".join(sorted(mediums, key=mediums.get, reverse=True)[:2])
    museum_count = venue_types.get("미술관", 0)
    gallery_count = venue_types.get("갤러리", 0)
    painting_count = mediums.get("회화", 0)
    photo_count = mediums.get("사진", 0)
    history_count = mediums.get("미술사/명작", 0)

    interest = "관객 관심은 특정 작가 한 명보다, 주말 동선 안에서 여러 전시를 묶어보는 쪽으로 움직이고 있어."
    if painting_count >= 4:
        interest = "관객 관심은 회화와 색채, 화면 자체의 몰입감처럼 설명보다 먼저 체감되는 전시에 모이는 중이야."
    elif history_count >= 2:
        interest = "관객 관심은 검증된 이름과 미술사적 맥락이 분명한 전시에 모이는 중이야."
    elif photo_count >= 2:
        interest = "관객 관심은 사진과 이미지 기반 전시처럼 직관적으로 읽히면서도 공간감이 있는 전시에 모이는 중이야."

    market = "시장적으로는 블록버스터 전시와 상업 갤러리 전시가 동시에 관객의 시간을 나눠 갖는 상황이야."
    if gallery_count > museum_count:
        market = "상위권에서 갤러리 비중이 높아서, 기관 전시보다 삼청·한남·청담 동선의 갤러리 방문성이 더 강하게 보여."
    elif museum_count > gallery_count:
        market = "상위권에서 미술관 비중이 높아서, 단발성 발견보다 검증된 기관 전시와 큰 규모의 관람 경험이 더 안정적인 선택지로 보여."

    reason = "이 흐름은 여름 시즌의 이동 피로 속에서, 관객이 실패 확률 낮고 한 번에 이해되는 전시를 선호하는 상황과도 맞닿아 있어."
    if gallery_count >= 5 and "삼청" in area_line:
        reason = "특히 삼청권 갤러리들이 상위권에 모이면서, 하나의 전시만 보기보다 짧은 반경 안에서 여러 전시를 이어보는 동선형 관심이 강해져."

    return f"현재 ART NOIZ는 {area_line or '서울/수도권'} 중심으로 잡혀. Top 10의 핵심 매체는 {medium_line or '동시대미술'}이고, 구성은 미술관 {museum_count}개, 갤러리 {gallery_count}개에 가까워. {interest} 가장 강한 신호는 {ranked[0].get('title', '상위 전시')}지만, 단독 목적지라기보다 주변 전시들과 묶어 볼 때 더 설득력 있어 보여. {market} {reason}"

def main() -> None:
    items = build_items()
    payload = {
        "site": "NOIZ. Art",
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "weekly_read": make_weekly_read(items),
        "items": items,
        "creator": "이원준 시니어매니저",
        "method_note": "미술관·갤러리 공식 페이지, 아트 플랫폼, 전시 리뷰 검색 신호를 함께 본 ART NOIZ 데이터야. 전시를 평점 매기기보다, 현재 관객 관심이 어디로 움직이는지 읽는 용도야!",
    }
    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] wrote {DATA_PATH} with {len(items)} ART NOIZ items")

if __name__ == "__main__":
    main()
