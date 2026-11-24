# AI DEV DIRECTOR — 학습용 재구현

원본(저장소 루트의 `core/`, `agents/` 등)을 단계별로 다시 만드는 폴더입니다.
전체 계획은 "AI DEV DIRECTOR 재구현 학습 계획" 문서를 보세요.

## 진행 상황

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 뼈대: 설정 로더, 데이터 스키마 | 완료 |
| 2 | 프로세스 실행기: 타임아웃, 프로세스 트리 종료, 과금 변수 제거, CLI 탐색 | 완료 |
| 3 | Git worktree 격리 | 다음 |

## 실행 (윈도우 / 맥 공통, VS Code 터미널)

```bash
cd rebuild
python -m venv .venv
```

윈도우: `.venv\Scripts\activate` / 맥: `source .venv/bin/activate`

```bash
pip install -r requirements.txt
python -m pytest
```

VS Code에서는 `Python: Select Interpreter`로 `.venv`를 고르면 테스트 탐색기에서 바로 돌릴 수 있습니다.
GitHub에 올리면 `.github/workflows/rebuild-tests.yml`이 윈도우·맥·리눅스에서 자동으로 테스트합니다.

## 파일

```
director/schemas.py   AI끼리 주고받는 데이터 형식 (Order, BuilderResult, ReviewResult, Decision, Provenance)
director/config.py    config.yaml 검증 로더 (오타가 있으면 시작 시 오류)
director/env.py       과금 변수 제거(sanitized_env), CLI 실행 파일 찾기(resolve_cli)
director/process.py   안전한 프로세스 실행기(run), 프로세스 트리 종료(kill_tree)
tests/                34개 테스트. 실제 AI CLI는 부르지 않습니다(DIRECTOR_TESTING=1이면 차단)
```

## 직접 확인할 코드 (1~2단계)

코드 안에 `# [핵심]` 표시가 있는 함수 세 개입니다.

1. `director/env.py` `sanitized_env()` — 무엇을 왜 지우는지, 그리고 지우지 못하는 경우(CLI 자체 API 키 로그인).
2. `director/process.py` `run()` — 읽기 스레드, stdin 쓰기 스레드, 세 가지 정지 조건(시간 초과, 무출력, 사용자 정지).
3. `director/process.py` `kill_tree()` — 자손 목록을 먼저 찍어 두는 이유, OS별 종료 방법, 기다리는 방식.

## 원본과 다르게 만든 부분

| 부분 | 원본 | 재구현 | 이유 |
|---|---|---|---|
| 설정 | dict를 `.get()`으로 읽음 | pydantic 모델, 모르는 키 거부 | 오타가 조용히 기본값으로 바뀌는 문제 방지 |
| stdin | 읽기 스레드 시작 전에 전부 씀 | 읽기 스레드를 먼저 띄우고 별도 스레드에서 씀 | 큰 프롬프트에서 교착 가능성 제거 (`test_large_stdin_while_child_floods_stdout`) |
| 출력 읽기 | 줄 단위(readline), 줄마다 디코딩 | 바이트 덩어리, 끝에서 한 번 디코딩 | 줄바꿈 없는 진행 표시도 출력으로 인정, 한글이 덩어리 경계에서 깨지지 않음 |
| 맥 종료 | psutil로 자식 목록만 순회 | 새 세션으로 실행 후 프로세스 그룹째 종료 + psutil | 이미 고아가 된 손자까지 정리 |
| 종료 대기 | `kill()` 후 pid 존재 여부 확인 | 좀비를 죽은 것으로 보고 직접 대기 | `psutil.wait_procs`는 자식을 거둬 버려 종료 코드가 0으로 기록되는 버그가 생김 (`test_kill_active_stops_running_process`) |

## 다음 단계 전에 생각해 볼 질문

- 자식이 정상 종료(exit 0)했는데 손자가 백그라운드에 남아 있으면 어떻게 할까요? 지금은 그대로 둡니다.
  AI가 쓴 테스트가 서버를 띄워 놓고 끝나는 경우가 여기에 해당합니다.
- 윈도우의 `taskkill /T`도 부모-자식 관계에 의존합니다. 완전한 해결책은 Job Object인데, 학습 범위에서 다룰지 정해야 합니다.
