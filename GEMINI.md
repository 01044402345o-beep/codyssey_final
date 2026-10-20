# Gemini Rules

## 커밋 & Push & PR 규칙

작업이 완료될 때마다 아래 흐름을 반드시 따른다.

### 1. 브랜치 생성
- `main` 또는 현재 작업 브랜치에서 새 feature 브랜치를 생성한다.
- 브랜치 이름 컨벤션: `<type>/<간결한-설명>`
  - 예: `docs/realtime-translation-research`, `feat/voice-agent`, `fix/tts-latency`
  - type: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### 2. 커밋
- **관련 파일만** 경로를 지정하여 `git add`한다. (`git add -A` 금지)
- 커밋 메시지 컨벤션: `<type>: <한국어 또는 영어 설명>`
  - 예: `docs: 실시간 번역 API 리서치 문서 추가`
  - type은 브랜치 type과 동일한 목록 사용

### 3. Push
- 자신의 origin 리모트로 push한다.
  ```
  git push origin <브랜치명>
  ```

### 4. PR 생성
- GitHub CLI(`gh`)를 사용하여 PR을 생성한다.
- PR 제목은 커밋 메시지와 동일한 컨벤션을 따른다.
- PR 본문에는 변경 내용 요약을 포함한다.
  ```
  gh pr create --title "<제목>" --body "<본문>" --base main
  ```
