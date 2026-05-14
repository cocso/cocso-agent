# 정산서 변환 데모용 샘플

`cocso_settlement` plugin 시연용 sample 입력 파일.

## 파일

| 파일 | 용도 |
|---|---|
| `거래처_원본_2026-05.xlsx` | 거래처 자체 양식 (8행). COCSO 표준이 아닌 흔한 변형 — 컬럼명·순서 다름. |

## 거래처 원본 컬럼 → COCSO 표준 매핑 (자동 매칭 예시)

| 원본 컬럼 | COCSO 표준 |
|---|---|
| 거래코드 | 정산코드 |
| 거래처 | 처방 병원명 |
| 사업자번호 | 처방 병원 사업자번호 |
| 제조사 | 제약사명 |
| 약품명 | 제품명 |
| 약가 | 단가(원) |
| 청구수량 | 수량 |
| 청구금액 | 처방금액(원) |
| 정산액(VAT포함) | 정산금액(원, VAT 포함) |
| 메모 | 비고 |

원본은 **보험코드** 컬럼이 없음 — 변환 시 빈 값으로 두거나 사용자에게 묻기.

## 시연 흐름

```
사용자: "5월 정산서 변환해줘. 입력은 ~/cocso-agent/excel/samples/거래처_원본_2026-05.xlsx"
COCO: skill cocso-settlement-excel 로드
  → excel_open + excel_read_range 로 헤더 + 샘플 데이터 읽기
  → 매핑 표 사용자에게 제시 + 보험코드 빠짐 알림
사용자: "보험코드는 빈 값으로 두고 진행"
COCO: → cocso_settlement_create({...})
  → "완료. 8행 채움. ~/Documents/COCSO_정산_2026-05.xlsx 저장됨."
```

## 직접 변환 시뮬레이션 (CLI)

```bash
python3 << 'EOF'
import importlib.util, openpyxl, json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "cs", "plugins/cocso_plugin/settlement.py"
)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

# 원본 읽기
wb = openpyxl.load_workbook("excel/samples/거래처_원본_2026-05.xlsx")
ws = wb["5월 정산"]
items = []
for row in ws.iter_rows(min_row=5, max_row=12, values_only=True):
    items.append({
        "정산코드": row[0],
        "처방 병원명": row[1],
        "처방 병원 사업자번호": row[2],
        "제약사명": row[3],
        "제품명": row[4],
        "단가(원)": row[5],
        "수량": row[6],
        "처방금액(원)": row[7],
        "정산금액(원, VAT 포함)": row[8],
        "비고": row[9],
    })
wb.close()

# COCSO 양식 생성
out = m.cocso_settlement_create({
    "output_path": "/tmp/COCSO_정산_2026-05.xlsx",
    "company_name": "한빛약품",
    "items": items,
    "overwrite": True,
})
print(json.loads(out))
EOF
```

→ `/tmp/COCSO_정산_2026-05.xlsx` 생성됨. Excel로 열면 통계 영역(N3:R) 자동 집계.
