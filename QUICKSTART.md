# COCSO Agent 빠른 시작 (5분 가이드)

> COCO를 처음 써보는 비즈니스사 사용자를 위한 5분 안내. 자세한 설정은 [README.md](README.md)와 `cocso setup --help` 참고.

---

## 1. 사전 준비

| 항목 | 필요 |
|---|---|
| Python | 3.11 이상 |
| OS | macOS / Linux (Windows는 WSL 권장) |
| 디스크 | 약 200 MB |
| 네트워크 | 회사 MCP 서버 + LLM provider 접근 가능 |

회사 운영팀에서 미리 받아둘 것:
- **Client MCP URL** + **인증 키** (영업·정산 데이터 접근용)
- **Service MCP URL** + **인증 키** (외부 서비스용 — 선택)
- **LLM API 키** (Anthropic 또는 OpenAI)

---

## 2. 설치

```bash
pip install cocso-agent
```

또는 source 설치:
```bash
git clone https://github.com/cocso/cocso-agent
cd cocso-agent
pip install -e .
```

---

## 3. 셋업 (대화형 1회)

```bash
cocso setup
```

순서:

1. **회사 식별** — 회사명 입력
2. **Client MCP** — URL + 인증 키 입력
3. **Service MCP** — URL + 인증 키 입력 (선택)
4. **LLM provider** — Anthropic / OpenAI 중 선택 + API 키 입력
5. 모델 선택 (기본값: 추천 모델 자동 선택)

> 모든 값은 `~/.cocso/.env` 에 저장됨. 다시 바꾸려면 `cocso setup` 재실행 또는 파일 직접 편집.

---

## 4. 첫 대화

```bash
cocso
```

프롬프트가 뜨면 한국어로 자유롭게:
```
> 박 딜러 이번 달 정산 얼마야?
COCO: 이번 달(2026-05) 박 딜러 정산을 Client MCP에서 조회합니다.
     ...
```

명령:
- `/help` — 슬래시 명령 목록
- `/new` — 새 세션
- `/sandbox list` — 보호 파일 목록 확인
- 종료: `Ctrl+C` 두 번 또는 `/quit`

---

## 5. 동작 확인

```bash
cocso doctor
```

확인 사항:
- ✅ Configuration Files
- ✅ COCSO MCP — Client + Service 등록 상태
- ✅ Auth Providers
- ✅ Tool Availability

문제가 있으면 ⚠ 또는 ✗ 와 함께 해결 안내가 나옴.

---

## 6. MCP 연결 확인

```bash
cocso mcp list
```

다음과 같이 나오면 정상:
```
cocso-client    https://client.your-company.com/mcp    Bearer ✓
cocso-service   https://service.your-company.com/mcp   Bearer ✓
```

---

## 기본 탑재 도구 (cocso_plugin)

설치하면 자동 활성화되는 통합 plugin. 4 sub-module:

### 🛡️ Sandbox — 보호 파일 차단
SOUL.md / .env / config.yaml / 자격증명 등 보호 파일 수정 시도 자동 차단. 보호 목록 조회: `/sandbox list`. 수정: `~/.cocso/sandbox.yaml`

### 📊 Audit — 컴플라이언스 로그
모든 user/assistant turn + tool 호출을 `~/.cocso/audit/<session>.jsonl` 로 기록. 자격증명-shape 인자는 자동 redact. 세션별 sliding-window rate limit (기본 60회/60초). `/audit stats` / `/audit tail 20`

### 📁 Excel — generic .xlsx 도구
파일 열기/시트 읽기/셀 쓰기/범위 batch 쓰기/시트 추가/다른 이름 저장 — 6 tools. 임의 엑셀 파일 다룰 때 사용.

### 💼 Settlement — 정산서 변환·생성 (도메인)
**다른 회사 양식 엑셀을 COCSO 표준 의약품 정산 수수료 내역서로 변환**. 컬럼 자동 매핑 + 사용자 확인 + 통계 영역 자동 집계.

데모용 샘플 입력: `excel/samples/거래처_원본_2026-05.xlsx` (8행, 다른 양식). 사용 흐름 + 매핑 표는 `excel/samples/README.md` 참고.

```
사용자: "5월 정산서 변환해줘. 입력 = excel/samples/거래처_원본_2026-05.xlsx"
COCO: 헤더 분석 → 매핑 표 제시 → 확인 후 변환 → 출력 경로 알림
```

---

## 보안 권장 사항 (배포용)

`soul_sandbox` plugin은 에이전트가 보호 파일을 **수정·삭제**하는 걸 SW level에서 차단합니다. 다른 프로세스 / 침해 시나리오까지 막으려면 OS level 추가 보호 권장.

### macOS / Linux
```bash
# SOUL.md / .env 직접 수정 금지 (root만 변경 가능)
chmod 0444 ~/.cocso/SOUL.md ~/.cocso/.env

# 더 강하게 — Linux 한정 (immutable bit, root 권한 필요)
sudo chattr +i ~/.cocso/SOUL.md ~/.cocso/.env
```

### Docker
```yaml
# docker-compose.yml — 보호 디렉토리를 readonly mount
services:
  cocso:
    volumes:
      - ./cocso_home/SOUL.md:/app/.cocso/SOUL.md:ro
      - ./cocso_home/.env:/app/.cocso/.env:ro
```

### 자격증명 추가 보호
- `.env` 파일 권한: `chmod 0600 ~/.cocso/.env` (소유자만 읽기)
- 운영 환경에서는 **OS keychain / vault 통합** 검토 (예: macOS Keychain, HashiCorp Vault, AWS Secrets Manager). 현재 cocso는 plain `.env` 만 지원

### 감사 로그
모든 사용자 turn / 어시스턴트 응답 / tool 호출은 `cocso_audit` plugin이 자동 기록:
```
~/.cocso/audit/<session_id>.jsonl
```
컴플라이언스 (개인정보보호법 / ISMS) 대응용. 정기적으로 `cocso backup` 또는 외부 SIEM으로 ship 권장.

확인:
```bash
# 통계
cocso 안에서: /audit stats

# 최근 로그 보기
/audit tail 20
```

---

## 자주 묻는 질문

**Q. 회사 데이터가 안 보임**
→ `cocso doctor` → "COCSO MCP" 섹션 확인. URL 또는 키 누락 시 "(server will auth as anonymous)" 또는 "(not configured)" 표시.

**Q. SOUL.md가 수정되지 않음**
→ 정상. `soul_sandbox` 플러그인이 보호 중. 직접 수정하려면 텍스트 에디터로 `~/.cocso/SOUL.md` 열어 변경. 변경은 다음 turn 부터 반영 (재시작 불필요).

**Q. MCP URL을 바꿨는데 반영 안 됨**
→ `.env` 변경 후 `cocso gateway restart`. (`cocso setup` 으로 변경했다면 자동 재시작)

**Q. 자격증명이 화면에 노출되지 않게 하려면?**
→ `soul_sandbox` 가 기본 보호. `echo $COCSO_CLIENT_KEY` 같은 명령은 자동 차단됨. `/sandbox list` 로 보호 항목 확인.

**Q. 다른 회사의 데이터를 보고 싶음**
→ COCO는 사용자 권한 범위 안에서만 응답. 다른 회사 데이터는 회사 운영팀 요청 필요.

---

## 다음 단계

- 회사 도메인 능력 추가: `cocso plugins enable <plugin-name>`
- Skill 추가: `cocso skill add <skill-name>`
- Telegram / Discord / Slack 연결: `cocso gateway setup`
- 백업: `cocso backup`

문제가 있으면 회사 IT 운영팀에 문의하거나 `cocso doctor` 출력을 첨부해 GitHub Issue 등록.
