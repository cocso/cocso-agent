# COCSO Agent

> Discord, Slack, Telegram, CLI, MCP를 위한 가벼운 개인 비서.

COCSO는 Discord, Slack, Telegram, CLI에 집중한 슬림한 메시징 에이전트입니다.

```
 ██████╗  ██████╗   ██████╗ ███████╗  ██████╗ 
██╔════╝ ██╔═══██╗ ██╔════╝ ██╔════╝ ██╔═══██╗
██║      ██║   ██║ ██║      ███████╗ ██║   ██║
██║      ██║   ██║ ██║      ╚════██║ ██║   ██║
╚██████╗ ╚██████╔╝ ╚██████╗ ███████║ ╚██████╔╝
 ╚═════╝  ╚═════╝   ╚═════╝ ╚══════╝  ╚═════╝      
```

## 구성

| 영역 | 내용 |
|---|---|
| **Provider** | Anthropic (Claude), OpenAI (GPT), OpenAI Codex, Xiaomi MiMo, OpenRouter (200+ 모델), 로컬 (LM Studio / Ollama / vLLM), 커스텀 (OpenAI 호환 엔드포인트) |
| **메시징** | Discord, Slack, Telegram |
| **터미널 백엔드** | local, Docker, SSH |
| **MCP** | 지원. 기본 서버 없음 — `cocso mcp add` 로 추가 |
| **Skills** | 번들: `configuration`, `devops`. 추가는 `cocso skills install <repo>` |

## 설치

### 원라이너 (Linux / macOS / Termux)

```bash
curl -fsSL https://raw.githubusercontent.com/cocso/cocso-agent/main/scripts/install.sh | bash
```

repo 클론, venv 생성, 의존성 설치, `cocso` 명령을 PATH에 등록 후 `cocso setup` 까지 진행됩니다.

위저드 건너뛰려면 `bash -s -- --skip-setup`. 나중에 `cocso setup` 으로 재실행.

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/cocso/cocso-agent/main/scripts/install.ps1 | iex
```

### 수동 설치

```bash
git clone https://github.com/cocso/cocso-agent.git
cd cocso-agent
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
cocso setup
```

### Docker

GHCR 사전 빌드 이미지:

```bash
mkdir -p ~/.cocso
docker run --rm -it -v ~/.cocso:/opt/data \
    -e COCSO_UID=$(id -u) -e COCSO_GID=$(id -g) \
    ghcr.io/cocso/cocso-agent:latest setup
docker run -d --name cocso --restart unless-stopped \
    --network host -v ~/.cocso:/opt/data \
    -e COCSO_UID=$(id -u) -e COCSO_GID=$(id -g) \
    ghcr.io/cocso/cocso-agent:latest
docker logs -f cocso
```

또는 compose 로 로컬 빌드:

```bash
git clone https://github.com/cocso/cocso-agent.git
cd cocso-agent
mkdir -p ~/.cocso
COCSO_UID=$(id -u) COCSO_GID=$(id -g) docker compose build
docker compose run --rm gateway setup            # 위저드, ~/.cocso/.env 작성
COCSO_UID=$(id -u) COCSO_GID=$(id -g) docker compose up -d
docker compose logs -f
```

기본 명령은 `gateway run`. 일회성 명령은 `docker exec -it cocso /opt/cocso/cocso <cmd>`.

---

## 빠른 시작

`cocso setup` 후:

```bash
cocso chat                  # 에이전트와 대화 (REPL)
cocso gateway run           # 메시징 게이트웨이 실행 (foreground)
cocso gateway start         # 백그라운드 서비스로 등록 + 시작
cocso status                # provider / API key / 플랫폼 / 게이트웨이 상태
cocso doctor                # 상세 진단
```

설정은 `~/.cocso/`:

```
~/.cocso/
├── .env                # 시크릿 (API key, 봇 토큰)
├── config.yaml         # provider, 터미널 백엔드, 에이전트 설정
├── sessions/           # 대화 기록
├── skills/             # 설치된 skill
└── plugins/            # 사용자 plugin
```

대부분 `cocso setup` (대화형) 또는 `cocso config set <key> <value>` 로 설정. 파일 직접 수정도 가능.

---

## 셋업 위저드

`cocso setup` 핵심 3단계:

1. **모델 & Provider** — provider 선택, API key 입력, 기본 모델 지정
2. **터미널 백엔드** — local / Docker / SSH
3. **메시징 플랫폼** — Discord / Slack / Telegram 봇 토큰 + 허용 사용자

고급 옵션:

```bash
cocso setup tools           # 플랫폼별 toolset 체크리스트
cocso setup agent           # max iteration, 압축, 표시 옵션
```

또는 단일 섹션: `cocso setup model | terminal | gateway | tools | agent`.

---

## 자주 쓰는 명령

```bash
cocso chat                       # 대화 모드
cocso chat -q "2+2 는?"          # 단일 쿼리

cocso model                      # provider/모델 전환
cocso config show                # 현재 설정 보기
cocso config set model.default mimo-v2.5-pro
cocso config set model.provider xiaomi

cocso gateway run                # foreground 게이트웨이
cocso gateway start | stop | restart | status
cocso gateway install            # systemd / launchd 서비스로 등록
cocso logs --follow              # 게이트웨이 로그 tail

cocso mcp add <name> <url-or-cmd>  # MCP 서버 연결
cocso mcp list

cocso skills browse              # skill 목록
cocso skills install <repo>      # GitHub 에서 설치

cocso cron list                  # 예약 작업
cocso cron create "0 9 * * *" "데일리 스탠드업 리마인더"

cocso insights --days 7          # 세션 사용 리포트
cocso status                     # 상태 요약
cocso doctor                     # 상세 진단
cocso uninstall [--full]         # 제거 (--full 은 ~/.cocso 까지 삭제)
```

---

## 환경변수 설정

`~/.cocso/.env` 에 시크릿 저장. 전체 템플릿은 [`.env.example`](.env.example) 참고. 주요 키:

```bash
# Provider — 하나 이상
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
XIAOMI_API_KEY=...
OPENROUTER_API_KEY=sk-or-...            # 200+ 모델 단일 엔드포인트
LM_BASE_URL=http://localhost:11434/v1   # 로컬 Ollama / LM Studio

# Discord
DISCORD_BOT_TOKEN=...
DISCORD_ALLOWED_USERS=123456789012345678
DISCORD_HOME_CHANNEL=...

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USERS=...

# 터미널 백엔드 (local / docker / ssh)
TERMINAL_ENV=local
```

Provider / 모델은 `~/.cocso/config.yaml` 에 보관 (멀티봇 환경에서 env 충돌 회피).

---

## 프로젝트 구조

```
cocso_cli/   CLI 진입점, 셋업 위저드, 모델 선택, 게이트웨이 명령
cocso_core/  공용 인프라 — constants, state, logging, utils, model_tools, toolsets
agent/       에이전트 루프, prompt 빌더, transports (anthropic / chat_completions / codex)
tools/       내장 tool: terminal, file, web, browser, memory, todo, vision, MCP, skills
gateway/     메시징 게이트웨이 (Discord / Slack / Telegram 어댑터 + 세션 저장소)
plugins/     사용자 plugin 호스트
cron/        cron 스케줄러
skills/      번들 skill (configuration, devops)
docker/      Docker entrypoint
scripts/     설치 / 제거 / 빌드 헬퍼
```

진입점은 `cocso_cli/main.py` (CLI), `cocso_cli/run_agent.py` (에이전트 런타임).

---

## 라이선스

[LICENSE](LICENSE) 참고.
