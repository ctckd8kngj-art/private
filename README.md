# FSS 게시글 제목 모니터

금융감독원 특정 게시글 제목이 변경되면 Gmail로 알림을 보내는 GitHub Actions입니다.

## 파일 구조

```
├── check_title.py                    # 크롤링 + 변경 감지 스크립트
├── last_title.txt                    # 마지막으로 확인한 제목 (자동 관리)
└── .github/workflows/monitor.yml    # 스케줄 + 메일 발송 워크플로우
```

## 세팅 방법

### 1. 저장소 생성 및 파일 업로드
이 파일들을 GitHub Private 저장소에 올립니다.

### 2. Gmail 앱 비밀번호 생성
1. Google 계정 → 보안 → 2단계 인증 활성화
2. [앱 비밀번호](https://myaccount.google.com/apppasswords) 생성 → `메일 / Windows 컴퓨터` 선택
3. 16자리 비밀번호 복사

### 3. GitHub Secrets 등록
저장소 → Settings → Secrets and variables → Actions → New repository secret

| Secret 이름      | 값                          |
|------------------|-----------------------------|
| `MAIL_USERNAME`  | 발신 Gmail 주소 (예: `your@gmail.com`) |
| `MAIL_PASSWORD`  | 앱 비밀번호 (16자리)         |
| `MAIL_TO`        | 수신 메일 주소               |

### 4. 최초 실행
- Actions 탭 → `FSS 게시글 제목 모니터링` → `Run workflow` 버튼으로 수동 실행
- 최초 실행 시 현재 제목을 `last_title.txt`에 저장만 하고 메일은 발송하지 않음
- 이후부터 제목이 바뀌면 자동 알림

## 스케줄

| 실행 시각 | KST    |
|-----------|--------|
| UTC 00:00 | 오전 09:00 |
| UTC 06:00 | 오후 03:00 |

시간을 바꾸려면 `monitor.yml`의 `cron` 값을 수정하세요.  
예) 오전 8시 → `0 23 * * *` (전날 UTC)

## 주의사항

- **셀렉터 오류** 시 `check_title.py`의 `fetch_title()` 함수에서 CSS 셀렉터를 수정합니다.
  금감원 홈페이지 개편 시 셀렉터가 달라질 수 있습니다.
- `last_title.txt`는 Actions가 자동으로 커밋하므로 직접 수정하지 마세요.
