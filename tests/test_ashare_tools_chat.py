"""The A-share chat tools: units are the whole game here — Tushare reports
万股, 万元, 元 and percentages-as-numbers in the same payload."""
from __future__ import annotations

import pytest

from app.ai.tools.registry import run_tool


@pytest.fixture
def raw(monkeypatch):
    payload = {
        "ticker": "600066.SS",
        "fina_audit": [{"end_date": "20251231", "audit_result": "标准无保留意见",
                        "audit_agency": "大华会计师事务所", "audit_fees": 1_280_000.0}],
        # 万股 for both halves, and a ratio already in percent
        "pledge_stat": [{"end_date": "20260924", "pledge_count": 6, "unrest_pledge": 1282.54,
                         "rest_pledge": 0.0, "total_share": 221393.92, "pledge_ratio": 0.58}],
        # float_share in 股, float_ratio in percent
        "share_float": [{"float_date": "20171226", "float_share": 223_026_708.0,
                         "float_ratio": 10.0738, "holder_name": "郑州宇通集团有限公司",
                         "share_type": "公开增发一般股份"}],
        # reward in 元; the interim period discloses nothing
        "stk_rewards": [
            {"end_date": "20260630", "name": "汤玉祥", "title": "董事长,党委书记", "reward": 0.0},
            {"end_date": "20251231", "name": "汤玉祥", "title": "董事长,党委书记", "reward": 1_650_700.0},
            {"end_date": "20251231", "name": "王文韬", "title": "副总经理,董事", "reward": 1_737_800.0},
        ],
        "stk_holdertrade": [{"ann_date": "20220909", "holder_name": "郑州宇通集团有限公司",
                             "holder_type": "C", "in_de": "IN", "change_vol": 3_316_000.0}],
        "repurchase": [{"ann_date": "20220509", "proc": "完成", "vol": 19_696_300.0,
                        "amount": 130_000_000.0}],
        "disclosure_date": [{"end_date": "20260930", "pre_date": "20261015", "actual_date": None}],
        "namechange": [{"name": "宇通客车", "start_date": "20061009", "end_date": None,
                        "change_reason": "其他"}],
        "top10_holders": [{"end_date": "20260630", "holder_name": "郑州宇通集团有限公司",
                           "holder_type": "一般企业", "hold_ratio": 37.7045, "hold_change": 0.0}],
        "top10_floatholders": [{"end_date": "20260630", "holder_name": "香港中央结算有限公司",
                                "holder_type": "一般企业", "hold_ratio": 12.56,
                                "hold_change": 58_914_374.0}],
        "stk_holdernumber": [{"end_date": "20260630", "holder_num": 50346}],
    }
    import app.tools.ashare_tools as at
    monkeypatch.setattr(at, "load_raw", lambda t: payload if t == "600066.SS" else None)
    return payload


def test_governance_converts_every_unit(raw):
    out = run_tool("ashare_governance", {"ticker": "600066.SS"})
    assert "标准无保留意见 · 大华会计师事务所 · 审计费 128 万元" in out
    # 1282.54 万股 pledged, ratio quoted as filed
    assert "质押 1,283 万股 (0.58% of 总股本)" in out
    # 223,026,708 股 → 22,303 万股, and a percentage that is already one
    assert "22,303 万股 (10.07%)" in out
    # 元 → 万元, highest first, and the empty interim period is skipped
    assert "高管薪酬 20251231" in out and "王文韬 (副总经理) 173.8 万元" in out
    assert "0.0 万元" not in out
    assert "增持 20220909" in out
    assert "回购 20220509: 完成" in out and "1.30 亿元" in out
    assert "下次披露: 20260930 报告，预计 20261015" in out


def test_shareholders_shows_both_lists(raw):
    out = run_tool("ashare_shareholders", {"ticker": "600066.SS"})
    assert "十大股东" in out and "十大流通股东" in out
    assert "郑州宇通集团有限公司" in out and "香港中央结算有限公司" in out
    assert "+58,914,374 shares" in out            # the float holder's move
    assert "股东户数" in out and "50,346" in out


def test_a_non_ashare_gets_a_clear_error(raw):
    for name in ("ashare_governance", "ashare_shareholders", "ashare_indicators"):
        assert "ERROR" in run_tool(name, {"ticker": "QDEL"})
