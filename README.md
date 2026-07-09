# NOIZ Daily

서울/수도권의 전시, 팝업, 브랜드 공간 중 공개 노출 신호가 큰 Top 10을 보여주는 정적 웹페이지입니다.

## 구조

```txt
index.html
data/noiz-data.json
scripts/update_noiz.py
scripts/sources.json
.github/workflows/daily-update.yml
requirements.txt
```

## 작동 방식

- `index.html`은 열릴 때마다 `data/noiz-data.json`을 불러오고, 상단에 현재 주차를 `2026 July week 1` 형식으로 표시합니다.
- GitHub Actions가 매일 09:00 KST에 `scripts/update_noiz.py`를 실행합니다.
- 스크립트가 전시/팝업 정보 사이트를 확인하고 `data/noiz-data.json`을 갱신합니다.
- GitHub Pages는 갱신된 JSON을 보여줍니다.

## 배포 순서

1. GitHub에서 새 repository를 만듭니다. 예: `noiz`
2. 이 폴더 안의 모든 파일을 repository root에 업로드합니다.
3. GitHub repository에서 `Settings → Pages`로 이동합니다.
4. `Build and deployment`에서 `Deploy from a branch`를 선택합니다.
5. Branch는 `main`, folder는 `/root`를 선택합니다.
6. 저장 후 몇 분 기다리면 아래 형태의 주소가 생깁니다.

```txt
https://YOUR_GITHUB_ID.github.io/noiz/
```

## 매일 업데이트 확인

- `.github/workflows/daily-update.yml`이 매일 09:00 KST에 실행됩니다.
- 바로 테스트하려면 GitHub repository의 `Actions → Daily NOIZ Update → Run workflow`를 누르세요.
- 실행 후 `data/noiz-data.json`이 commit되면 사이트도 갱신됩니다.

## 소스 추가

`scripts/sources.json`에 아래 형식으로 추가합니다.

```json
{
  "name": "Source Name",
  "url": "https://example.com",
  "type": "popup",
  "weight": 20
}
```

`weight`가 높을수록 해당 소스에서 발견된 항목의 NOIZ 점수가 높게 시작합니다.

## 한계

이 버전은 무료 MVP입니다.

- 정해진 공개 사이트만 확인합니다.
- 인스타그램 최신 피드는 수집하지 않습니다.
- 네이버 리뷰/블로그/검색량을 직접 가져오지 않습니다.
- AI 감정 분석은 붙어 있지 않고, 키워드 기반 톤 추정입니다.

고도화하려면 검색 API, AI 요약/감정 분석, 별도 DB를 붙이면 됩니다.




## favorability 기준

현재 화면의 표정 라벨은 `favorability` 점수를 기준으로 표시됩니다.

```txt
80 이상  → 매우 긍정적
70–79    → 긍정적
50–69    → 복합적
49 이하  → 대체로 부정적
```

단, `infoVolume`이 `low`이거나 `signals`에 `후기 축적 전`이 있으면 점수와 관계없이 `후기 축적 중`으로 표시합니다.

무료 MVP에서는 실제 리뷰 전체를 긁지 않고, 공개 페이지의 문구/링크 텍스트에서 긍정·피로 신호를 읽어 임시 여론 점수를 만듭니다. 검색 API나 리뷰 데이터를 붙이면 뉴스·블로그·후기 스니펫을 `text_score()`에 합쳐 넣어 더 실제 여론에 가까운 점수로 확장할 수 있습니다.


## 랭킹 표기 기준

NOIZ Top 10에는 실제로 오픈되었고 공개 반응 신호가 있는 항목만 표시합니다. `후기 축적 전`, `후기 부족`, `오픈 예정`, `반응 없음`, `infoVolume: "low"` 항목은 랭킹에서 제외합니다.


## Top 10 산출 방식

NOIZ는 먼저 전체 후보군을 충분히 넓게 수집한 뒤, `후기 축적 전`, `오픈 예정`, `반응 없음`, `infoVolume: "low"` 항목을 제외하고 남은 항목 중 NOIZ 점수순으로 Top 10을 뽑습니다. 즉, 후기 부족 항목이 순위에 들어가지 않도록 제외하되, 10개는 전체 후보군에서 다시 채우는 방식입니다. 단, 정적 샘플 데이터에 적격 후보가 10개 미만이면 임의의 가짜 항목을 만들지 않습니다.


## 무료 수집 강화 버전

현재 자동 업데이트는 최대한 무료로 할 수 있는 범위에서 다음 신호를 함께 봅니다.

```txt
1. 지정된 전시/팝업 정보 페이지
2. 무료 공개 검색 결과
3. 뉴스 RSS 검색 결과
4. 블로그/후기성 검색 스니펫
```

랭킹 방식은 다음과 같습니다.

```txt
전체 후보군 수집
→ 오픈 예정/후기 부족/반응 없음 제외
→ 공개 노출 수 + 후기성 반응 수 + 긍정/피로 신호 계산
→ NOIZ 점수순 Top 10 선정
```

주의: API key 없는 무료 MVP이므로 네이버 플레이스 리뷰, 인스타그램 댓글, 실제 방문자 평점 전체를 수집하지 않습니다. 따라서 NOIZ는 객관적 평점이 아니라 공개 신호 기반 주간 레이더입니다.


## 히든 ART 모드

상단 `NOIZ!` 로고를 빠르게 세 번 탭/클릭하면 `art.html`로 이동합니다. 이 페이지는 미술관, 갤러리, 아트 플랫폼, 전시 리뷰 검색 신호만 따로 읽는 미술 전시 전용 모드입니다.

```txt
NOIZ! 로고 3회 빠른 탭
→ art.html
→ 미술 전시 전용 ART NOIZ
```

ART 모드는 메인 페이지와 별도로 `data/art-noiz-data.json`을 읽고, GitHub Actions에서 `scripts/update_art_noiz.py`가 함께 갱신합니다.


## ART NOIZ 수집 강화

`art.html`은 업로드한 `Art Week Korea — Expanded Coverage Prototype`의 전시 후보와 서울·수도권 공간 watchlist를 기반으로 갱신됩니다.

```txt
data/art-week-seed.json
→ 기존 Art Week Korea candidates 25개
→ 서울·수도권 watchlist venues 175개
→ scripts/update_art_noiz.py에서 공식 페이지/검색 신호와 결합
→ data/art-noiz-data.json 생성
```

메인 NOIZ와 달리 ART 모드는 브랜드 팝업을 제외하고 미술관, 갤러리, 대안공간, 아트 플랫폼, 전시 리뷰 신호만 봅니다.


## 메인 NOIZ 표시 오류 수정

메인 `index.html`은 이제 `reactionCount`가 없는 기존 정적 데이터까지 모두 숨기지 않습니다. 명시적으로 `후기 축적 전`, `후기 부족`, `오픈 예정`, `반응 없음`, `infoVolume: "low"`인 항목만 제외합니다.


## ART 모드 한국어 표기

ART NOIZ의 `venue`, `area`, `region`, `mapQuery`, 주간 요약문은 한국어 표기를 우선 사용합니다. 예: `Samcheong` → `삼청`, `Jung-gu` → `중구`, `Seoul Museum of Art, Seosomun` → `서울시립미술관 서소문본관`.


## ART 모드 객관성 정리

ART NOIZ 데이터에서 개인 취향·사용자 컬렉션 관련 문구를 제거했습니다. 전시 설명은 개인 관심사 기준이 아니라 작가, 매체, 전시 형식, 기관/갤러리 맥락 중심으로 작성됩니다.


## Archive

NOIZ는 매주 월요일 자동 업데이트 시 `data/archive/noiz-week-YYYY-MM-DD.json`으로 주간 스냅샷을 저장합니다. 페이지의 날짜 옆 좌우 화살표로 이전/다음 주간 아카이브를 확인할 수 있습니다.

## Clean stable reset

This package is a static, pre-Gemini rollback build for recovery.

- Gemini update pipeline removed
- GitHub Actions removed
- `scripts/` removed
- stable `data/noiz-data.json` and `data/art-noiz-data.json` preserved
- latest accepted UI files kept

Use this as a fresh GitHub Pages repository or as a full wipe-and-reupload baseline. Do not run the previous daily update workflow against this package.

## Stable daily update restored without AI

This v98 stable package restores the original pre-Gemini daily update pipeline.

Included fixes:
- fixed date extraction regex runtime error
- fixed `merge_candidates` string-join TypeError
- limited reuse of existing JSON data so malformed experimental data is not preserved
- no Gemini / no external AI API
- no `GEMINI_API_KEY` required

## v99 official-card daily update

v99 keeps the no-AI daily update approach but fixes the main quality issue:
- Naver View / Google News / Web Search are evidence only
- blog/search/news titles cannot become cards
- roundup/listing pages such as "총정리", "놀거리", "추천", "모음" are excluded as primary cards
- card owner/description are experience overview copy, not signal-count system text

## v100 stable seed fallback

v100 keeps the no-AI official-card pipeline from v99, but adds a static stable seed fallback.

Why:
- v99 fixed the Naver/Google card problem, but it could become too strict and leave only one card.
- v100 uses live official/source-page crawl first.
- If the live crawl returns too few current cards, it fills the remaining slots from the recovered pre-Gemini stable data.
- Seed fallback cards are still filtered by dates and search/review URL rules.

## v101 Gemini curator inventory pipeline

Dev-only automation experiment.

Pipeline:
1. crawl official/source pages
2. Gemini judges whether each candidate is a single real-world popup/exhibition/space experience
3. accepted candidates merge into `data/event-inventory.json`
4. Google News/search evidence is used only as reaction signal
5. Gemini performs final editorial curation for descriptions and weekly read
6. hard validation rejects review/search/listing URLs and aggregate titles
7. if fewer than 8 cards pass, `data/noiz-draft-review.json` is written and existing `data/noiz-data.json` is kept

## v102 Gemini curator seed guard

v102 fixes the sparse-output problem seen in v101.

If live/Gemini-curated inventory returns too few active events, the updater fills the list from `data/noiz-curation-seed.json`, which is based on the manually curated weekly set. This keeps dev from publishing a 1–2 card page while still allowing Gemini to add newly accepted events into the inventory over time.
