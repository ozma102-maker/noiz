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
