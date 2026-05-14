"""Tests for ``cocso_settlement_validate``.

Pins:
- 정상 데이터 → 0 error, 0 warning, has_blockers=False
- 처방금액 ≠ 단가×수량 → error
- 핵심 컬럼 누락 → error
- 정산금액 < 처방금액 → warning
- 음수·0 단가/수량 → warning
- 사업자번호 형식 오류 → warning
- (정산코드, 제품명) 중복 → warning
- 한국어 라벨과 snake_case 둘 다 인식
- 합계 누적 정확
- 핸들러는 raise 안 함
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_PATH = PROJECT_ROOT / "plugins" / "cocso_plugin" / "settlement.py"


@pytest.fixture
def validate():
    spec = importlib.util.spec_from_file_location("s_v", str(PLUGIN_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.cocso_settlement_validate


def _decode(s):
    return json.loads(s)


GOOD_ITEM = {
    "정산코드": "S0001",
    "처방 병원명": "한빛의원",
    "처방 병원 사업자번호": "123-45-67890",
    "제품명": "타이레놀 500mg",
    "단가(원)": 500,
    "수량": 100,
    "처방금액(원)": 50000,
    "정산금액(원, VAT 포함)": 55000,
}


class TestHappyPath:
    def test_clean_items_no_errors(self, validate):
        out = _decode(validate({"items": [GOOD_ITEM]}))
        assert out["ok"] is True
        assert out["error_count"] == 0
        assert out["warning_count"] == 0
        assert out["summary"]["has_blockers"] is False

    def test_summary_totals(self, validate):
        items = [GOOD_ITEM, dict(GOOD_ITEM, **{"처방금액(원)": 30000, "정산금액(원, VAT 포함)": 33000})]
        out = _decode(validate({"items": items}))
        assert out["summary"]["total_prescription"] == 80000
        assert out["summary"]["total_settlement"] == 88000


class TestPriceQuantityMismatch:
    def test_detects_amount_mismatch(self, validate):
        bad = dict(GOOD_ITEM, **{"처방금액(원)": 99999})  # should be 50000
        out = _decode(validate({"items": [bad]}))
        assert out["error_count"] == 1
        assert "처방금액" in out["errors"][0]["msg"]

    def test_tolerates_one_won_rounding(self, validate):
        # 단가 333.333 × 수량 3 = 1000 (실제 999.999) — 1원 이내 허용
        item = dict(GOOD_ITEM, **{
            "단가(원)": 333.333, "수량": 3, "처방금액(원)": 1000,
        })
        out = _decode(validate({"items": [item]}))
        # No price-related error
        assert not any(e["field"] == "처방금액" for e in out["errors"])


class TestMissingCoreColumns:
    @pytest.mark.parametrize("drop_field", [
        "정산코드", "처방 병원명", "제품명", "단가(원)", "수량",
    ])
    def test_each_core_field_required(self, validate, drop_field):
        item = {k: v for k, v in GOOD_ITEM.items() if k != drop_field}
        out = _decode(validate({"items": [item]}))
        # core field absence registers as error
        labels = [e["field"] for e in out["errors"]]
        # field name uses short label form
        short = drop_field.replace("(원)", "")
        assert any(short in l for l in labels), f"missing {drop_field} not detected"


class TestSettlementBelowPrescription:
    def test_warns_when_settlement_lower(self, validate):
        # 단가×수량과 처방금액 일치 (1000 = 100×10) 시켜야 amount-mismatch error 안 남
        item = dict(GOOD_ITEM, **{
            "단가(원)": 100, "수량": 10, "처방금액(원)": 1000,
            "정산금액(원, VAT 포함)": 500,
        })
        out = _decode(validate({"items": [item]}))
        assert out["error_count"] == 0
        assert any(w["field"] == "정산금액" for w in out["warnings"])


class TestNegativeUnitOrQuantity:
    def test_negative_unit_warns(self, validate):
        item = dict(GOOD_ITEM, **{"단가(원)": -100,
                                  "처방금액(원)": -10000})  # match 단가×수량 to avoid amount-mismatch error
        out = _decode(validate({"items": [item]}))
        assert any(w["field"] == "단가" for w in out["warnings"])

    def test_zero_quantity_warns(self, validate):
        item = dict(GOOD_ITEM, **{"수량": 0, "처방금액(원)": 0})
        out = _decode(validate({"items": [item]}))
        assert any(w["field"] == "수량" for w in out["warnings"])


class TestBizIdFormat:
    def test_dashed_format_ok(self, validate):
        item = dict(GOOD_ITEM, **{"처방 병원 사업자번호": "123-45-67890"})
        out = _decode(validate({"items": [item]}))
        assert not any(w["field"] == "처방 병원 사업자번호" for w in out["warnings"])

    def test_no_dash_format_ok(self, validate):
        item = dict(GOOD_ITEM, **{"처방 병원 사업자번호": "1234567890"})
        out = _decode(validate({"items": [item]}))
        assert not any(w["field"] == "처방 병원 사업자번호" for w in out["warnings"])

    def test_invalid_format_warns(self, validate):
        item = dict(GOOD_ITEM, **{"처방 병원 사업자번호": "BAD-FORMAT"})
        out = _decode(validate({"items": [item]}))
        assert any(w["field"] == "처방 병원 사업자번호" for w in out["warnings"])


class TestDuplicateDetection:
    def test_same_code_and_product_warns(self, validate):
        items = [GOOD_ITEM, GOOD_ITEM]
        out = _decode(validate({"items": items}))
        assert any(w["field"] == "_duplicate" for w in out["warnings"])

    def test_same_code_different_product_ok(self, validate):
        items = [
            GOOD_ITEM,
            dict(GOOD_ITEM, **{"제품명": "다른약품", "처방금액(원)": 10000,
                               "단가(원)": 100, "수량": 100}),
        ]
        out = _decode(validate({"items": items}))
        assert not any(w["field"] == "_duplicate" for w in out["warnings"])


class TestKeyForms:
    def test_snake_case_keys_recognized(self, validate):
        item = {
            "settlement_code": "S0001",
            "hospital_name": "한빛",
            "product_name": "약A",
            "unit_price": 100,
            "quantity": 5,
            "prescription_amount": 500,
        }
        out = _decode(validate({"items": [item]}))
        # 모든 필수 필드 인식 → core errors 0
        assert out["error_count"] == 0


class TestErrorContract:
    def test_handler_never_raises(self, validate):
        for bad in ({}, {"items": None}, {"items": "not-list"},
                    {"items": [None, "string", 42]}):
            assert isinstance(validate(bad), str)

    def test_non_dict_item_recorded_as_error(self, validate):
        out = _decode(validate({"items": ["not-a-dict"]}))
        assert out["error_count"] >= 1
