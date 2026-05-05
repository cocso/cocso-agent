# COCSO Agent

> A lean personal assistant for Discord, Slack, Telegram, CLI, and optional MCP.

COCSO is a slim, opinionated assistant focused on Discord, Slack, Telegram, and CLI surfaces with a small, well-defined feature set.

```
                       ░████████ 
               ████████████████  
         █████████████████░      
     ███████████████████████████ 
  ░███████████████████████████   
 ███████████████████░            
 ███████████████████████████████ 
 █████████████████████████████   
  █████████████████████          
   ██████████████████████        
    ███████░                     
```

## What ships

| Surface | COCSO |
|---|---|
| **Providers** | Anthropic (Claude), OpenAI (GPT), OpenAI Codex, Xiaomi MiMo, OpenRouter (200+ models), local (LM Studio / Ollama / vLLM), custom (any OpenAI-compatible endpoint) |
| **Messaging** | Discord, Slack, Telegram |
| **Terminal backends** | local, Docker, SSH |
| **MCP** | Supported. Zero servers shipped — add your own with `cocso mcp add`. |
| **Skills** | Bundled `configuration` + `devops`; install more with `cocso skills install <repo>` |

## Install

### One-liner (Linux / macOS / Termux)

```bash
curl -fsSL https://raw.githubusercontent.com/cocso/cocso-agent/main/scripts/install.sh | bash
```

This clones the repo, creates a venv, installs all extras, links `cocso` onto your `PATH`, and runs `cocso setup` so you finish with a working bot.

Skip the wizard with `bash -s -- --skip-setup` and rerun later with `cocso setup`.

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/cocso/cocso-agent/main/scripts/install.ps1 | iex
```

### Manual

```bash
git clone https://github.com/cocso/cocso-agent.git
cd cocso-agent
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
cocso setup
```

### Docker

Pre-built image from GitHub Container Registry:

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

Or build locally with the included compose file:

```bash
git clone https://github.com/cocso/cocso-agent.git
cd cocso-agent
mkdir -p ~/.cocso
COCSO_UID=$(id -u) COCSO_GID=$(id -g) docker compose build
docker compose run --rm gateway setup            # interactive wizard, writes ~/.cocso/.env
COCSO_UID=$(id -u) COCSO_GID=$(id -g) docker compose up -d
docker compose logs -f
```

The image runs `gateway run` by default. Use `docker exec -it cocso /opt/cocso/cocso <cmd>` for one-off commands against the running container.

---

## Quick start

After `cocso setup`:

```bash
cocso chat                  # interactive REPL with the agent
cocso gateway run           # run the messaging gateway in the foreground
cocso gateway start         # install + start as a background service
cocso status                # show provider / API keys / platforms / gateway state
cocso doctor                # detailed diagnostics
```

Configuration lives in `~/.cocso/`:

```
~/.cocso/
├── .env                # secrets (API keys, bot tokens)
├── config.yaml         # provider, terminal backend, agent settings
├── sessions/           # conversation history
├── skills/             # installed skills
└── plugins/            # user-added plugins
```

Almost everything is set via `cocso setup` (interactive) or `cocso config set <key> <value>`. Direct file edits are also fine.

---

## Setup wizard

`cocso setup` walks the three essentials:

1. **Model & Provider** — pick provider, enter API key, choose default model
2. **Terminal Backend** — local / Docker / SSH
3. **Messaging Platforms** — Discord / Slack / Telegram bot tokens + allowlists

Advanced sections are opt-in:

```bash
cocso setup tools           # toolset checklist per platform
cocso setup agent           # max iterations, compression, display
```

Or run a single section directly: `cocso setup model | terminal | gateway | tools | agent`.

---

## Common commands

```bash
cocso chat                       # interactive chat
cocso chat -q "what is 2+2"      # one-shot query

cocso model                      # switch provider/model
cocso config show                # show current config
cocso config set model.default mimo-v2.5-pro
cocso config set model.provider xiaomi

cocso gateway run                # foreground gateway
cocso gateway start | stop | restart | status
cocso gateway install            # install as systemd / launchd service
cocso logs --follow              # tail gateway logs

cocso mcp add <name> <url-or-cmd>  # connect a Model Context Protocol server
cocso mcp list

cocso skills browse              # browse available skills
cocso skills install <repo>      # install from GitHub

cocso cron list                  # scheduled jobs
cocso cron create "0 9 * * *" "Daily standup reminder"

cocso insights --days 7          # session usage report
cocso status                     # health summary
cocso doctor                     # detailed diagnostics
cocso uninstall [--full]         # remove (--full also wipes ~/.cocso)
```

---

## Configuration via environment

`~/.cocso/.env` holds secrets. The full template lives at [`.env.example`](.env.example). Common keys:

```bash
# Provider — pick one or several
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
XIAOMI_API_KEY=...
OPENROUTER_API_KEY=sk-or-...            # 200+ models via one endpoint
LM_BASE_URL=http://localhost:11434/v1   # local Ollama / LM Studio

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

# Terminal backend (local / docker / ssh)
TERMINAL_ENV=local
```

Provider/model live in `~/.cocso/config.yaml` so multi-bot setups don't fight over env vars.

---

## Project layout

```
cocso_cli/         CLI entrypoint, setup wizard, model picker, gateway commands
agent/               agent loop, prompt builder, transports (anthropic / chat_completions / codex)
tools/               built-in tools: terminal, file, web, browser, memory, todo, vision, MCP, skills
gateway/             messaging gateway (Discord / Slack / Telegram adapters + session store)
plugins/             user-extensible plugin host
cron/                cron scheduler
skills/              bundled skills (configuration, devops)
docker/              Docker entrypoint
scripts/             install / uninstall / build helpers
```

`run_agent.py`, `cli.py`, and `cocso_cli/main.py` are the three big entry surfaces; everything else fans out from there.

---

## Status

- **Version:** v0.1.0 (2026-05-05) — first clean COCSO release after the lean refactor.
- **Stability:** dogfood-grade. Used personally; report issues you hit.
- **Tests:** the `tests/` directory currently holds smoke checks only — contributions welcome.

---

## License

See [LICENSE](LICENSE).
