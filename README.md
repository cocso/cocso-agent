# COCSO Agent

> COCSO(코쏘) 비즈니스사를 위한 한국어 AI 에이전트 — Discord, Slack, Telegram, CLI, MCP 지원.

```
 ██████╗  ██████╗   ██████╗ ███████╗  ██████╗ 
██╔════╝ ██╔═══██╗ ██╔════╝ ██╔════╝ ██╔═══██╗
██║      ██║   ██║ ██║      ███████╗ ██║   ██║
██║      ██║   ██║ ██║      ╚════██║ ██║   ██║
╚██████╗ ╚██████╔╝ ╚██████╗ ███████║ ╚██████╔╝
 ╚═════╝  ╚═════╝   ╚═════╝ ╚══════╝  ╚═════╝
```

**COCO**는 COCSO 플랫폼의 AI 에이전트입니다. 비즈니스사(CSO·정산자) 사용자가 영업·정산·계약 업무를 자연어로 처리할 수 있도록 보조합니다. 회사 도메인 데이터 접근은 두 종류의 MCP 서버(`cocso-client`, `cocso-service`)를 통해 이뤄집니다.

처음 사용한다면 [**QUICKSTART.md**](QUICKSTART.md)부터 — 5분 안에 첫 대화까지 안내.

---

## 구성

| 영역 | 내용 |
|---|---|
| **Provider** | Anthropic (Claude), OpenAI (GPT), OpenRouter (200+ 모델), Xiaomi MiMo, 로컬 (Ollama / LM Studio / vLLM), 커스텀 OpenAI 호환 엔드포인트 |
| **메시징** | Discord, Slack, Telegram, CLI |
| **터미널 백엔드** | local, Docker, SSH |
| **MCP (자동 등록)** | `cocso-client` (영업·정산), `cocso-service` (외부 서비스) — env 만 채우면 자동 연결 |
| **번들 plugin** | `cocso_plugin` 1개에 5 sub-module: sandbox / audit / excel / settlement / mcp_inventory |
| **번들 skill** | `cocso-company`, `cocso-mcp-usage`, `cocso-settlement-excel`, `cocso-configuration`, `webhook-subscriptions` |

---

## 설치

### 원라이너 (Linux / macOS / Termux)

```bash
curl -fsSL https://raw.githubusercontent.com/cocso/cocso-agent/main/scripts/install.sh | bash
```

repo 클론 → venv 생성 → 의존성 설치 → `cocso` 명령 PATH 등록 → `cocso setup` 위저드 자동 실행.

위저드 건너뛰려면 `bash -s -- --skip-setup`. 나중에 `cocso setup`으로 재실행.

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

또는 compose 로컬 빌드:

```bash
git clone https://github.com/cocso/cocso-agent.git
cd cocso-agent
mkdir -p ~/.cocso

# 회사 MCP / LLM 키를 호스트 export 하면 compose가 그대로 컨테이너에 전달
export COCSO_COMPANY_NAME="OO약품"
export COCSO_CLIENT_MCP_URL="https://client.example.com/mcp"
export COCSO_CLIENT_KEY="..."
export COCSO_SERVICE_MCP_URL="https://service.example.com/mcp"
export COCSO_SERVICE_KEY="..."
export ANTHROPIC_API_KEY="sk-ant-..."

COCSO_UID=$(id -u) COCSO_GID=$(id -g) docker compose up -d
docker compose logs -f
```

기본 명령은 `gateway run`. 일회성 명령은 `docker exec -it cocso /opt/cocso/cocso <cmd>`.

---

## 빠른 시작

`cocso setup` 후:

```bash
cocso chat                  # COCO와 대화 (REPL)
cocso gateway run           # 메시징 게이트웨이 (foreground)
cocso gateway start         # 백그라운드 서비스로 등록 + 시작
cocso status                # provider / API key / 플랫폼 / 게이트웨이 상태
cocso doctor                # 상세 진단 (◆ COCSO MCP 섹션 포함)
```

설정 위치 `~/.cocso/`:

```
~/.cocso/
├── .env                 # 시크릿 (COCSO_*_KEY, LLM API key, 봇 토큰)
├── config.yaml          # provider, 터미널 백엔드, 에이전트, plugins.enabled
├── SOUL.md              # COCO persona (첫 실행 시 자동 seed, 편집 가능)
├── sandbox.yaml         # soul_sandbox 보호 파일/env 목록 (자동 seed)
├── sessions/            # 대화 기록
├── audit/               # cocso_audit JSONL 감사 로그 (세션별)
├── skills/              # 사용자 설치 skill
└── plugins/             # 사용자 설치 plugin
```

대부분 `cocso setup` (대화형) 또는 `cocso config set <key> <value>`로 설정. 파일 직접 수정도 가능.

---

## 셋업 위저드

`cocso setup`이 차례로 실행:

1. **회사 식별** (`setup_cocso`) — 회사명 + Client MCP URL/KEY + Service MCP URL/KEY
2. **모델 & Provider** — Anthropic / OpenAI 등 선택, API key, 기본 모델
3. **터미널 백엔드** — local / Docker / SSH
4. **메시징 플랫폼** — Discord / Slack / Telegram 봇 토큰 + 허용 사용자

회사 식별 단계에서 MCP URL을 입력하면 `mcp` SDK 자동 설치 + gateway 자동 재시작. 사용자 수동 작업 없음.

단일 섹션 실행: `cocso setup cocso | model | terminal | gateway | tools | agent`.

---

## COCSO 두 종류 MCP

COCO가 회사 데이터에 접근하는 통로. 환경변수만 채우면 자동 등록.

| MCP 서버 | 환경변수 | 용도 |
|---|---|---|
| `cocso-client` | `COCSO_CLIENT_MCP_URL` + `COCSO_CLIENT_KEY` | 영업·정산 운영 (딜러, 거래처, 수수료, 정산 그룹) |
| `cocso-service` | `COCSO_SERVICE_MCP_URL` + `COCSO_SERVICE_KEY` | 외부 서비스 노출 (자격 조회, 제안, 재위임 통지) |

각 MCP는 독립적으로 설정 — 한쪽만 채워도 됨. 진단:

```bash
cocso mcp list      # 등록된 MCP 서버 + 인증 헤더 상태
cocso doctor        # ◆ COCSO MCP 섹션
```

채팅 안에서 `cocso_mcp_inventory` tool을 통해 COCO가 실제 사용 가능한 MCP tool을 직접 확인 — 이름 추측·환각 방지.

---

## 번들 plugin: `cocso_plugin`

설치 직후 자동 활성화. 5 sub-module:

| Sub-module | 역할 |
|---|---|
| **sandbox** | SOUL.md / .env / config.yaml / 자격증명 보호 (`pre_tool_call` block). `/sandbox list` 로 현재 보호 목록 확인 |
| **audit** | 모든 user/assistant turn + tool 호출을 `~/.cocso/audit/<session>.jsonl`로 기록. 자격증명-shape 인자 자동 redact. 세션 sliding-window rate limit. `/audit stats`, `/audit tail 20` |
| **excel** | Excel (.xlsx) 6 generic tool — open, read_range, write_cell, write_range, add_sheet, save_as |
| **settlement** | **다른 회사 양식 엑셀 → COCSO 표준 의약품 정산 수수료 내역서 변환·생성** (도메인). 데모 샘플: `excel/samples/거래처_원본_2026-05.xlsx` |
| **mcp_inventory** | 등록된 MCP tool을 서버별로 그룹핑해 인벤토리 반환. COCO가 추측 전에 자기 점검 |

비활성화: `cocso plugins disable cocso_plugin` (sub-module 단위 토글은 코드 수정).

---

## 자주 쓰는 명령

```bash
cocso chat                       # 대화 모드
cocso chat -q "5월 정산 합계는?"  # 단일 쿼리

cocso model                      # provider/모델 전환
cocso config show
cocso config set model.default claude-opus-4-7

cocso gateway run                # foreground
cocso gateway start | stop | restart | status
cocso gateway install            # systemd / launchd 등록

cocso mcp list                   # MCP 서버 + 인증 상태
cocso mcp add <name> <url>       # 추가 MCP 수동 등록

cocso skills browse              # 설치된 skill
cocso skills install <repo>      # GitHub 에서 추가 설치

cocso plugins list               # 활성/비활성 plugin
cocso cron list                  # 예약 작업
cocso insights --days 7          # 사용 리포트
cocso doctor                     # 상세 진단
cocso uninstall [--full]         # 제거 (--full 은 ~/.cocso 까지 삭제)
```

---

## 환경변수

`~/.cocso/.env`에 보관. 전체 템플릿: [`.env.example`](.env.example).

```bash
# COCSO 회사 식별 + MCP (둘 다 또는 한쪽만 설정 가능)
COCSO_COMPANY_NAME=OO약품
COCSO_CLIENT_MCP_URL=https://client.example.com/mcp
COCSO_CLIENT_KEY=...
COCSO_SERVICE_MCP_URL=https://service.example.com/mcp
COCSO_SERVICE_KEY=...

# Provider (하나 이상)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...
XIAOMI_API_KEY=...
LM_BASE_URL=http://localhost:11434/v1   # 로컬 Ollama/LM Studio

# Discord / Slack / Telegram
DISCORD_BOT_TOKEN=...
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
TELEGRAM_BOT_TOKEN=...

# 터미널 백엔드 (local / docker / ssh)
TERMINAL_ENV=local
```

---

## 프로젝트 구조

```
cocso_cli/         CLI 진입점, 셋업 위저드, 모델·MCP·gateway 명령, doctor
cocso_core/        공용 인프라 — constants, state, logging, time, utils,
                   model_tools, toolsets
agent/             에이전트 루프, prompt 빌더, transports
                   (anthropic / chat_completions / codex)
tools/             내장 tool: terminal, file, web, browser, memory, todo,
                   vision, MCP, skills
gateway/           메시징 게이트웨이 (Discord / Slack / Telegram 어댑터)
acp_adapter/       Agent Client Protocol 어댑터 (Claude Code 등 외부 ACP 클라이언트)
plugins/
  └── cocso_plugin/    sandbox / audit / excel / settlement / mcp_inventory
                       + 번들 SKILL.md + 정산서 표준 template.xlsx
cron/              cron 스케줄러
skills/            번들 skill (cocso-company, cocso-mcp-usage,
                   cocso-configuration, webhook-subscriptions)
excel/             표준 정산 템플릿 + 데모 샘플 (samples/)
docker/            Docker entrypoint
scripts/           설치 / 제거 / 빌드 헬퍼
tests/             pytest 스위트 (98 케이스)
```

진입점: `cocso_cli/main.py` (CLI), `cocso_cli/run_agent.py` (에이전트 런타임).

---

## 보안 / 컴플라이언스

- **Sandbox**: SOUL.md / .env / 자격증명 등 보호 파일 수정 시도 자동 차단. `/sandbox list` 로 현재 보호 목록 확인. 추가 권장: OS-level immutable bit, Docker readonly mount (자세한 내용은 [QUICKSTART.md](QUICKSTART.md) "보안 권장 사항" 섹션)
- **Audit log**: 모든 turn·tool 호출 JSONL 기록. 자격증명 자동 redact. 정기 백업 / 외부 SIEM ship 권장
- **Rate limit**: 세션당 도구 호출 한도 (기본 60회/60초)
- **MCP 인증**: 서버별 별도 키 (`COCSO_CLIENT_KEY`, `COCSO_SERVICE_KEY`)
- **권한 격리**: COCO는 비즈니스사 권한 범위 안에서만 응답 — 다른 회사 데이터, Admin/Settler 영역 자동 거절

---

## 테스트

```bash
pytest -p no:xdist -o addopts=""    # 전체
pytest tests/plugins/                # plugin 테스트만
pytest tests/plugins/test_cocso_plugin_combined.py    # cocso_plugin 통합
```

현재 98 케이스 통과 (audit 16 / combined 5 / excel 22 / mcp_dual 13 / mcp_inventory 12 / sandbox 14 / settlement 16).

---

## 문서

- [QUICKSTART.md](QUICKSTART.md) — 5분 빠른 시작 (한글)
- [SOUL.md](SOUL.md) — COCO persona 정의
- [.env.example](.env.example) — 전체 환경변수 템플릿
- `skills/company/cocso-company/SKILL.md` — COCSO 회사·플랫폼 개요
- `skills/company/cocso-mcp-usage/SKILL.md` — MCP 사용 워크플로우
- `plugins/cocso_plugin/skills/cocso-settlement-excel/SKILL.md` — 정산서 변환 가이드
- `excel/samples/README.md` — 정산서 데모 샘플 사용법

---

## 라이선스

[LICENSE](LICENSE) 참고.
