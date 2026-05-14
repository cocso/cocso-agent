# COCSO Agent Architecture

> 변경 빈도가 다른 것은 다른 layer에. 자주 바뀌는 도메인이 자주 안 바뀌는 코어를 끌어내리지 않게.

---

## 4-Layer 분리

```
┌──────────────────────────────────────────────────────────────────────┐
│  L4. Runtime customization (사용자가 채팅 중 수정)                     │
│      Slash commands, custom skills, ephemeral session config          │
│      ─ 변경: 매일 / 사용자 직접                                         │
├──────────────────────────────────────────────────────────────────────┤
│  L3. Tenant config (회사별 식별·정책·자산)                              │
│      $COCSO_HOME/{.env, config.yaml, SOUL.md, sandbox.yaml,          │
│                   audit.yaml, mappings/, plugins/, skills/}           │
│      ─ 변경: 회사 도입 시 1회 + 가끔 (가입 / 키 회전 / 정책 갱신)        │
├──────────────────────────────────────────────────────────────────────┤
│  L2. Domain (회사 도메인 로직 + 마스터 데이터)                          │
│      MCP server (cocso-client + cocso-service) — Node.js NestJS       │
│      약품 검색, 정산제약사, 수수료 계산, 거래처 정보, 제안서, 자격 등   │
│      ─ 변경: 주 1~수 회 / 백엔드 deploy → tools/list_changed 자동 반영 │
├──────────────────────────────────────────────────────────────────────┤
│  L1. Core (cocso-agent 코드)                                           │
│      Agent loop, MCP client, plugin runtime, sandbox/audit/excel/    │
│      mcp_inventory, COCO persona, branding, gateway 어댑터            │
│      ─ 변경: 분기별 / 코어 팀 / pip 또는 docker pull                    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Layer 별 책임

### L1 — Core (cocso-agent 코드)

`cocso-agent` repo. Python 3.13+. 다음 책임:

| 영역 | 위치 | 역할 |
|---|---|---|
| Agent loop | `agent/` | LLM 호출, tool 실행 루프, prompt 빌드 |
| Provider 어댑터 | `agent/transports/` | Anthropic / OpenAI / Codex / OpenRouter |
| MCP 클라이언트 | `tools/mcp_tool.py` | MCP server 자동 발견·등록·invoke |
| Tool registry | `tools/registry.py` | 동적 tool 등록·discovery |
| Generic tool | `tools/{terminal,file,web,browser,memory,...}.py` | 도메인 무관 IO |
| Plugin runtime | `cocso_cli/plugins.py` | plugin 발견·load·hook 실행 |
| Bundled plugin | `plugins/cocso_plugin/` | sandbox / audit / excel / settlement / mcp_inventory |
| Gateway | `gateway/` | Discord / Slack / Telegram / API server |
| ACP adapter | `acp_adapter/` | 외부 ACP 클라이언트 (Claude Code 등) |
| CLI | `cocso_cli/` | setup 위저드, 명령 라우팅, doctor |
| Persona | `cocso_cli/branding.py`, `cocso_cli/default_soul.py` | COCO 정체성 + fallback |

**변경 트리거**: 코어 기능 추가 (새 provider, 새 transport, 새 generic tool), 보안 fix.
**배포**: pip release (PyPI) 또는 docker push (GHCR).

### L2 — Domain (MCP server)

`mcp-server` repo (별도, Node.js NestJS). cocso-agent 가 client로 connect.

| 서버 | 노출 tool 수 | prefix | 도메인 |
|---|---|---|---|
| `cocso-client` | ~33 | `client_` | 영업·정산·딜러·수수료·거래처 |
| `cocso-service` | ~17 | `service_` | 약품 검색·재고·자격·제안서 |

**Connect 방식**: Streamable HTTP (`<base>/<server>/mcp`) + Bearer key. cocso-agent 의 env (`COCSO_*_MCP_URL` + `COCSO_*_KEY`) 만 채우면 자동.

**변경 트리거**: 회사 정책 변경, 새 비즈니스 룰, 마스터 데이터 갱신.
**배포**: 백엔드 server deploy → `tools/list_changed` notification → cocso-agent registry 자동 갱신 (cocso-agent 재시작 불필요).

### L3 — Tenant config

`$COCSO_HOME/` 디렉토리. 회사별 / 사용자별 config·자산.

| 파일 / 디렉토리 | 용도 | 누가 편집 |
|---|---|---|
| `.env` | secret (COCSO_*_KEY, LLM API key, 봇 토큰) | 회사 IT 팀 (또는 secret backend) |
| `config.yaml` | provider, plugin enable/disable, gateway, agent | 회사 IT 팀 |
| `SOUL.md` | COCO persona (회사별 변형 가능) | 회사 또는 사용자 |
| `sandbox.yaml` | 보호 파일·env 패턴 | 회사 IT 팀 (보안 정책) |
| `audit.yaml` | 감사 로그 / rate limit 정책 | 회사 IT 팀 |
| `audit/<session>.jsonl` | 세션별 감사 로그 | 자동 (rotation 정책 적용) |
| `mappings/<name>.json` | 정산서 변환 매핑 preset | 자동 (사용 시 학습) |
| `sessions/<id>/` | 대화 기록 | 자동 |
| `plugins/<name>/` | 회사 / 사용자 추가 plugin | 회사 또는 사용자 |
| `skills/<name>/` | 회사 / 사용자 추가 skill | 회사 또는 사용자 |
| `profiles/<name>/` | 멀티테넌시 — profile 별 격리된 위 자산 | 멀티 호스트 시 |

**변경 트리거**: 회사 가입, 키 회전, 정책 갱신.
**배포**: `cocso setup` 위저드 또는 직접 편집 + `cocso gateway restart` (env/config는 자동 restart 분류).

### L4 — Runtime customization

세션 안에서 사용자가 즉시 변경. 재시작 X, hot reload.

| 항목 | 메커니즘 |
|---|---|
| Slash command | `/sandbox list`, `/audit stats`, `/help`, `/new` 등 |
| Skill 추가 로드 | `skill_view("plugin:name")` |
| Ephemeral session config | `cocso config set ...` 후 다음 turn |

**변경 트리거**: 일상 작업.
**배포**: 즉시 반영.

---

## Plugin 발견 위치 (cocso-agent runtime)

```
순서대로 scan, 첫 발견 우선:

1. plugins/                 (bundled in cocso-agent repo)
2. $COCSO_HOME/plugins/     (tenant 추가)
3. ~/.cocso/plugins/        (user — tenant 디렉토리와 다른 경우)
4. pip entry-points         (cocso_agent.plugins, 3rd party)
```

---

## 데이터 흐름 — 정산서 변환 예시

```
사용자: "거래처 양식 5월 정산서로 변환해줘 (path)"

[L4] /chat 모드 안에서
  ↓
[L1] cocso-agent agent loop — skill 로드
  ↓
[L1] cocso_settlement_sniff(path)        ← 헤더 자동 감지 + COCSO 매칭
[L1] cocso_settlement_mapping_match()    ← preset 있나?
[L1] excel_read_range(path, sheet, range)← 데이터 읽기
  ↓
[L2] mcp__cocso-service__service_search_medicines("타이레놀")  ← 보험코드 보강
[L2] mcp__cocso-client__client_lookup_partner_hospitals("한빛의원") ← 사업자번호 보강
  ↓
[L1] cocso_settlement_validate(items)    ← 검증 (처방금액 = 단가×수량 등)
[L1] cocso_settlement_create({...})      ← 표준 xlsx 생성
[L1] cocso_settlement_mapping_save(...)  ← preset 학습
  ↓
[L3] ~/.cocso/audit/<session>.jsonl     ← 감사 로그 자동 기록
[L3] ~/.cocso/mappings/한빛약품-*.json   ← 다음 변환 위해 저장
  ↓
사용자: "완료. ~/Documents/COCSO_정산_2026-05.xlsx"
```

---

## Plugin 시스템 (L1 안)

### 통합 plugin: `cocso_plugin`

```
plugins/cocso_plugin/
├── __init__.py              # 5 sub-module 순차 register
├── plugin.yaml              # 13 tools + 6 hooks 선언
├── sandbox.py               # SOUL/.env/credential 보호 (pre_tool_call block)
├── audit.py                 # 세션 JSONL 로그 + rate limit
├── excel.py                 # .xlsx 6 generic tool
├── settlement.py            # COCSO 정산서 변환·생성·검증
├── settlement_sniff.py      # 헤더 자동 감지 + 매핑 preset
├── mcp_inventory.py         # 등록된 MCP tool 인벤토리
├── template.xlsx            # 정산서 표준 템플릿 (번들)
└── skills/
    └── cocso-settlement-excel/SKILL.md   # 변환 워크플로우 (번들)
```

전체 enable/disable: `cocso plugins enable cocso_plugin` (DEFAULT_CONFIG 에 기본 enabled).

### 코어 plugin 타입 (one-active)

```
plugins/context_engine/<name>/    ← context 관리 전략 (compressor 외 lcm 등)
plugins/memory/<name>/             ← cross-session memory backend (mem0, hindsight 등)
```

`config.yaml` 의 `context.engine` / `memory.provider` 키로 선택.

---

## Update flow (각 layer 별로)

| 변경 유형 | Layer | 사용자 작업 | 자동 반영 |
|---|---|---|---|
| 백엔드 새 MCP tool 추가 | L2 | 없음 | `tools/list_changed` notification |
| 백엔드 룰 변경 (예: 수수료 계산식) | L2 | 없음 | 다음 호출에 즉시 |
| 회사 추가 (멀티테넌시) | L3 | `cocso profile create <name>` | 즉시 |
| MCP URL/KEY 회전 | L3 | `cocso setup cocso` 또는 `.env` 편집 | gateway 자동 restart |
| 사용자 새 skill 작성 | L3/L4 | 파일 추가 | hot reload (재시작 X) |
| cocso-agent 코어 업데이트 | L1 | `pip install -U` 또는 `docker pull` | restart 필요 |

---

## Security boundaries

```
[neutral source]               [어떤 layer가 보호]
─────────────────              ──────────────────
LLM 응답 / 모델 hallucination  → L1 sandbox plugin (pre_tool_call block)
Agent process                  → L1 audit plugin (모든 행동 기록)
Disk (~/.cocso 안)              → L3 sandbox.yaml (보호 파일 목록)
                               → OS-level (chmod 444, Docker readonly mount)
Secret 평문                    → L3 .env (현재) / Keychain·Vault (Phase 2)
MCP 서버 응답 PII              → L1 redact (audit log)
다른 회사 데이터               → L2 server-side guard (API key → tenant scope)
                               → L1 SOUL.md "권한 존중" 원칙
```

---

## 배포 모델

### 1. Single-tenant (1 회사 = 1 인스턴스)

```
[Client 컴퓨터]
└── cocso (CLI)
    └── ~/.cocso/  ← L3
                    ↑
                    └── L2 cocso.co.kr (공용)
```

### 2. Multi-tenant (1 호스트 = N 회사)

```
[Server]
└── /etc/cocso/profiles/
    ├── acme/      ← L3 (acme 회사)
    │   └── plugins/acme-rules/   ← 회사 자체 plugin
    ├── beta/      ← L3 (beta 회사)
    └── gamma/

[사용자]
└── COCSO_PROFILE=acme cocso chat
```

### 3. Container (Docker / k8s)

```
[Docker host]
└── cocso-agent container
    ├── /opt/cocso/        ← L1 (read-only mount)
    └── /opt/data/         ← L3 (volume mount)
        └── ~/.cocso/* 동등
```

healthcheck = `cocso doctor --quick` (exit 0 if healthy).

---

## 관측성 / Observability

| 신호 | 출처 | 용도 |
|---|---|---|
| Audit log JSONL | `$COCSO_HOME/audit/<session>.jsonl` | 컴플라이언스 / 사용 분석 |
| Tool latency | audit `duration_ms` 필드 | 성능 추적 |
| Healthcheck | `cocso doctor --quick` exit code | k8s liveness |
| Rate limit hit | audit `_rate_limited` event | 사용량 폭주 감지 |
| MCP 연결 상태 | `cocso doctor` "◆ COCSO MCP" 섹션 | 백엔드 장애 감지 |
| 배너 정보 | startup banner | tool/skill/MCP 카운트 즉시 확인 |

Phase 4 추가: Prometheus / OpenTelemetry export.

---

## 한 줄 요약

> **L1 = repo + bundled plugin (코어). L2 = MCP server (도메인). L3 = `$COCSO_HOME` (tenant). L4 = 채팅 안 (runtime).**
>
> 변경 빈도와 소유권이 layer 결정. cocso-agent 는 4 layer 모두 자동 발견·통합.
