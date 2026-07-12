# NOIZ! Stable

NOIZ!의 제출·공유용 수동 큐레이션 버전입니다.

## 운영 원칙

- GitHub Actions를 사용하지 않습니다.
- Gemini 및 자동 크롤링 스크립트를 사용하지 않습니다.
- 매주 검수한 `data/noiz-data.json`만 수동으로 교체합니다.
- ART 데이터는 필요할 때만 `data/art-noiz-data.json`을 수동으로 교체합니다.

## 저장소에 있어야 하는 주요 파일

```text
index.html
art.html
.nojekyll
.gitignore
README.md
data/
  noiz-data.json
  art-noiz-data.json
  art-week-seed.json
  noiz-archive-index.json
  noiz-theme-history.json
  archive/
```

## 저장소에 있으면 안 되는 파일

```text
.github/
scripts/
requirements.txt
data/event-inventory.json
data/noiz-curation-seed.json
data/noiz-draft-review.json
data/noiz-grouping-debug.json
data/noiz-seed-stable.json
```

stable 저장소에서는 Actions를 실행하지 마세요.
