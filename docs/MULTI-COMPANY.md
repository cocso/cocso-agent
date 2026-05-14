# 여러 회사 운영 가이드

> 1명이 N개 회사를 cocso 로 관리하는 흐름. **회사 = profile**. 각 회사 별로 MCP 키 / LLM 토큰 / 페르소나 / 감사 로그 / 대화 세션 완전 격리.

---

## 전체 흐름

```
~/.cocso/                       ← 글로벌 (active_profile sticky)
├── active_profile              ← 현재 활성 회사 이름
├── profiles/
│   ├── default/                ← 기본 (개인 작업)
│   ├── acme/                   ← acme 회사 격리 자산
│   │   ├── .env                ← acme MCP 키 + LLM 키
│   │   ├── config.yaml
│   │   ├── SOUL.md             ← acme 페르소나
│   │   ├── sandbox.yaml
│   │   ├── audit/              ← acme 감사 로그
│   │   ├── sessions/           ← acme 대화
│   │   ├── mappings/           ← acme 정산 매핑
│   │   ├── skills/             ← acme 추가 skill
│   │   └── plugins/            ← acme 추가 plugin
│   ├── beta/                   ← beta 회사
│   └── gamma/
└── ...

~/.local/bin/
├── acme                        ← wrapper: exec cocso -p acme "$@"
├── beta                        ← wrapper: exec cocso -p beta "$@"
└── gamma
```

---

## 1. 신규 회사 추가 (3 분)

### Step 1 — Profile 생성 + alias

```bash
cocso profile create acme
# → ~/.cocso/profiles/acme/ 생성
# → ~/.local/bin/acme wrapper script 생성
# → 다음부터 `acme <command>` = `cocso -p acme <command>`
```

기본으로 wrapper script 자동 생성 (이후 `acme` 만 입력하면 acme 컨텍스트로 모든 cocso 명령 실행). 자동 생성 끄려면 `--no-alias` 추가. 나중에 따로 만들려면 `cocso profile alias acme`.

### Step 2 — 회사 정보 + 키 입력

```bash
acme setup
# 위저드:
#   - 회사명: acme 약품
#   - Client MCP URL: https://mcp.cocso.co.kr/client/mcp
#   - Client MCP key: cocso_mcp_acme_xxxxx
#   - Service MCP URL: https://mcp.cocso.co.kr/service/mcp
#   - Service MCP key: cocso_mcp_acme_yyyyy
#   - LLM provider: Anthropic
#   - ANTHROPIC_API_KEY: sk-ant-acme-zzzzz
```

저장 위치: `~/.cocso/profiles/acme/.env` (다른 회사와 완전 분리).

### Step 3 — 검증

```bash
acme doctor          # ◆ COCSO MCP 섹션에 acme 키 적용 확인
acme mcp list        # cocso-client / cocso-service 등록 확인
acme chat            # acme 컨텍스트로 대화 시작
```

---

## 2. 회사 전환

### 명시적 (권장 — 안전)

```bash
acme chat            # acme 컨텍스트
beta chat            # beta 컨텍스트
gamma gateway run    # gamma 컨텍스트로 게이트웨이
```

→ 매 호출마다 명시. 실수 가능성 0.

### Sticky (1번 정한 후 유지)

```bash
cocso profile use acme   # ~/.cocso/active_profile 에 "acme" 기록
cocso chat               # acme 컨텍스트 (sticky)
cocso doctor             # 여전히 acme

# 다른 회사로
cocso profile use beta
cocso chat               # 이제 beta
```

→ 한 회사 집중 작업 시 편함. 단 다른 cocso 명령도 자동 acme — 잘못 실행 위험.

### Sticky + 일회성 override

```bash
cocso profile use acme       # default = acme
acme chat                    # acme (sticky)
beta -- doctor               # 일회성으로 beta — sticky 안 바꿈
acme chat                    # 다시 acme
```

---

## 3. 회사 목록 / 상태 확인

```bash
cocso profile list

# Output:
# Profiles (3):
#   * acme    [gateway running]  claude-opus-4-7  alias=acme
#     beta    [stopped]           gpt-5            alias=beta
#     gamma   [stopped]           claude-sonnet    alias=gamma
# 
# Active: acme
```

```bash
cocso profile show acme
# acme 회사의 model / 키 존재 여부 / skill 수 / 마지막 사용 시각 등
```

---

## 4. 회사별 독립 자산 — 무엇이 격리되나

| 자산 | acme | beta | gamma |
|---|---|---|---|
| MCP URL/KEY | acme.example.com / acme_key | beta.example.com / beta_key | gamma.example.com / gamma_key |
| LLM API key | sk-ant-acme | sk-openai-beta | sk-or-gamma |
| SOUL.md persona | acme 톤 (예: 보수적·정형) | beta 톤 (예: 창의적·자유) | 기본 |
| 감사 로그 | `~/.cocso/profiles/acme/audit/` | `~/.cocso/profiles/beta/audit/` | `~/.cocso/profiles/gamma/audit/` |
| 대화 세션 | acme/sessions/ | beta/sessions/ | gamma/sessions/ |
| 정산 매핑 | acme/mappings/ | beta/mappings/ | gamma/mappings/ |
| Sandbox 정책 | acme/sandbox.yaml | beta/sandbox.yaml | gamma/sandbox.yaml |
| Audit 정책 | acme/audit.yaml | beta/audit.yaml | gamma/audit.yaml |
| 추가 plugin | acme/plugins/ | beta/plugins/ | gamma/plugins/ |
| 추가 skill | acme/skills/ | beta/skills/ | gamma/skills/ |
| Gateway 상태 / PID | acme/gateway.pid | beta/gateway.pid | gamma/gateway.pid |

→ **Cross-tenant 누출 0** — acme 명령은 acme 키만 사용, acme 데이터만 봄.

---

## 5. 회사별 Gateway 동시 실행 (메시징 봇)

각 회사 별로 다른 Telegram/Discord/Slack 봇 운영:

```bash
# Terminal 1
acme gateway run

# Terminal 2
beta gateway run

# Terminal 3
gamma gateway run
```

또는 백그라운드 서비스로:

```bash
acme gateway start    # systemd / launchd 등록 + 실행
beta gateway start
gamma gateway start

acme gateway status   # 회사별 상태
beta gateway logs --tail 20
```

각 gateway = 다른 봇 토큰 + 다른 MCP 키 = 완전 격리.

---

## 6. 회사 복제 / export / import

### 같은 양식 새 회사

```bash
cocso profile create delta --clone acme
# acme의 config.yaml + .env + SOUL.md 복사
# delta가 같은 양식으로 시작 → 키만 바꾸면 끝
```

### 다른 컴퓨터로 옮기기

```bash
# 원본 컴퓨터
cocso profile export acme --output acme.tar.gz

# 새 컴퓨터
cocso profile import acme.tar.gz
acme doctor    # 검증
```

`.env` 의 평문 secret 도 같이 전달되므로 **암호화 채널 (scp / age) 사용 권장**. 또는 import 후 `acme setup` 으로 키 재입력.

---

## 7. 회사 삭제

```bash
cocso profile delete gamma --force
# ~/.cocso/profiles/gamma/ 통째 삭제
# wrapper script (~/.local/bin/gamma) 자동 정리
# active_profile = gamma 면 default 로 리셋
```

**주의**: 삭제 = 영구. 미리 export 권장.

---

## 8. 보안 권장

### 8.1 Secret backend (Phase 2)

`.env` 평문 대신 macOS Keychain 사용:

```bash
# 회사별 Keychain 항목으로 저장 (수동)
security add-generic-password -s cocso-agent-acme -a COCSO_CLIENT_KEY -w '<key>'

# acme profile 에서 backend 활성화
echo "COCSO_SECRET_BACKEND=keychain" >> ~/.cocso/profiles/acme/.env
```

→ acme/.env에 키 평문 없음. Keychain만 알면 됨.

(자동화는 다음 release — 현재 manual)

### 8.2 OS-level 보호

회사별 .env 파일 권한 강화:

```bash
chmod 0600 ~/.cocso/profiles/acme/.env
chmod 0600 ~/.cocso/profiles/beta/.env
chmod 0600 ~/.cocso/profiles/gamma/.env
```

→ 본인만 읽기. 다른 사용자 (또는 침해 process) 차단.

### 8.3 회사별 audit log 백업

```bash
# 매일 cron
for company in acme beta gamma; do
  $company backup --output ~/backups/${company}-$(date +%F).zip
done
```

각 회사 audit log + sessions + mappings 일일 백업.

---

## 9. 자주 묻는 질문

**Q. 회사 추가 한도?**
A. 디스크·메모리 외 한도 없음. 100+ 도 OK.

**Q. 동시 작업?**
A. 가능. 각 회사 = 다른 셸 / 다른 process. `acme chat` 과 `beta chat` 동시 실행 OK.

**Q. 한 LLM 토큰을 여러 회사 공유?**
A. 가능 — 각 profile 의 .env 에 같은 ANTHROPIC_API_KEY 입력. 단 회사별 사용량 분리는 안 됨 (LLM provider가 어느 회사 호출인지 모름).

**Q. 한 회사 → 다른 회사 데이터 노출?**
A. 0. 각 회사는 독립 .env / 독립 MCP 연결 / 독립 audit. Cross-tenant 호출 불가.

**Q. 봇 토큰도 회사마다?**
A. ✅ 권장. 회사 A 사용자는 회사 A 봇을 통해서만 접속. 봇 토큰 격리 = 사용자 격리.

**Q. 1대 호스트에 회사 N개 동시 봇?**
A. 가능. `acme gateway start; beta gateway start; gamma gateway start`. 각 봇 토큰 다르므로 충돌 없음. 단 메모리 N배.

**Q. 회사 이름 = 디렉토리명. 한글 허용?**
A. 영문 + 숫자 + `-`, `_` 권장. 한글은 wrapper alias 에서 깨질 수 있음.

**Q. `acme` 명령이 안 먹힘?**
A. `~/.local/bin` 이 PATH에 있어야 함:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

---

## 10. 시연 — 5분 안에 2 회사 셋업

```bash
# 1. 회사 A 추가
cocso profile create acme
acme setup
# (회사명 입력 + MCP 키 + LLM 키)

# 2. 회사 B 추가
cocso profile create beta
beta setup

# 3. 검증
cocso profile list
# Profiles (3):
#   acme  [stopped]  alias=acme
#   beta  [stopped]  alias=beta
#   default

# 4. 첫 대화
acme chat
> 5월 정산 데이터 보여줘
# acme MCP + acme 페르소나로 응답

# 5. 회사 전환
beta chat
> 5월 정산 데이터 보여줘
# beta MCP + beta 페르소나로 응답 (acme 데이터 절대 안 보임)
```

끝.

---

## 부록 — 트러블슈팅

| 증상 | 진단 |
|---|---|
| `acme: command not found` | PATH 에 `~/.local/bin` 추가 |
| `acme doctor` 가 다른 회사 MCP 보여줌 | wrapper script 내용 확인 (`cat ~/.local/bin/acme`) |
| 키 변경 후 반영 안 됨 | `acme gateway restart` (또는 `cocso -p acme gateway restart`) |
| 어느 회사 컨텍스트인지 헷갈림 | `cocso profile list` — 별표(*)가 active |
| profile 의 .env 경로? | `~/.cocso/profiles/<name>/.env` |
| 회사 통째 백업 | `acme backup` 또는 `tar -czf acme.tar.gz ~/.cocso/profiles/acme/` |
