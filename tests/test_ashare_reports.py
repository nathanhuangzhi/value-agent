"""Markdown 年报: heading hierarchy, section spans, and what counts as a report."""
from __future__ import annotations

from app.ai.tools.annual_reports import _toc_lines
from app.tools.ashare_reports import _ANNUAL_TITLE, _SKIP_TITLE, _fiscal_year, build_toc
from app.tools.sec_annual_reports import find_section, search_text, section_text

# Shaped like pymupdf4llm's output: heading depth comes from font size, which
# is why the logical level has to come from the filing's own numbering.
MD = """# 宇通客车股份有限公司 2025 年年度报告

## 目录

第一节 释义

## 第一节 释义

常用词语释义

## 第三节 管理层讨论与分析

### 一、报告期内公司从事的业务情况

公司是一家集客车产品研发、制造与销售为一体的大型企业。

# (一) 主营业务分析

# 1、利润表相关科目变动分析表

|科目|本期数|上年同期数|
|---|---|---|
|营业收入|4,142,617.40|3,721,758.66|

### (二) 非主营业务导致利润重大变化的说明

不适用

## 第八节 财务报告

### 合并利润表

营业总收入 41,426,173,982.34
"""


def _toc():
    return build_toc(MD)


def test_levels_come_from_the_numbering_not_the_markdown_depth():
    by_title = {h["title"]: h for h in _toc()}
    assert by_title["第三节 管理层讨论与分析"]["level"] == 1
    assert by_title["一、报告期内公司从事的业务情况"]["level"] == 2
    # Written as `#` (shallower than its parent) but logically a sub-section:
    assert by_title["(一) 主营业务分析"]["level"] == 3
    assert by_title["1、利润表相关科目变动分析表"]["level"] == 4
    assert by_title["合并利润表"]["level"] == 5          # unnumbered


def test_a_section_runs_to_the_next_heading_at_its_own_level_or_shallower():
    toc = _toc()
    section = find_section({"toc": toc}, "管理层讨论与分析")
    body, total, _ = section_text(MD, section)
    assert "一、报告期内公司从事的业务情况" in body       # its children are included
    assert "(一) 主营业务分析" in body
    assert "第八节 财务报告" not in body                 # the next 节 ends it
    assert total > 150

    # A level-3 heading keeps its own level-4 table…
    sub = find_section({"toc": toc}, "主营业务分析")
    body, _, _ = section_text(MD, sub)
    assert "营业收入|4,142,617.40" in body
    assert "非主营业务" not in body                      # …and stops at the next (二)


def test_the_duplicate_in_the_table_of_contents_loses_to_the_real_section():
    toc = _toc()
    first = find_section({"toc": toc}, "第一节 释义")
    body, _, _ = section_text(MD, first)
    assert "常用词语释义" in body                        # not the 目录 line


def test_tables_survive_as_tables_and_are_searchable():
    hits = search_text(MD, "营业收入")
    assert hits and any("4,142,617.40" in h["snippet"] for h in hits)


def test_the_listing_collapses_a_deep_toc():
    big = [{"line": i, "end": i + 1, "key": f"k{i}", "title": f"t{i}",
            "level": 1 if i % 20 == 0 else 4} for i in range(400)]
    lines = _toc_lines(big)
    assert len(lines) < 30
    assert "deeper sub-sections not listed" in lines[-1]
    # A small TOC (the SEC shape, no levels) is listed in full.
    small = [{"line": 1, "end": 9, "key": "item 5", "title": "Item 5. MD&A"}]
    assert _toc_lines(small) == ["- item 5: Item 5. MD&A  (8 lines)"]


def test_only_real_reports_are_kept():
    for title in ("2025年年度报告", "2026年半年度报告"):
        assert _ANNUAL_TITLE.search(title) and not _SKIP_TITLE.search(title)
    for title in ("2025年年度报告摘要", "2025年年度报告（英文版）",
                  "2024年年度报告更正公告", "关于2025年年度报告的问询函回复公告"):
        assert _ANNUAL_TITLE.search(title) and _SKIP_TITLE.search(title), title


def test_fiscal_year_prefers_the_title():
    assert _fiscal_year("2025年年度报告", None) == "2025"
    assert _fiscal_year("2026年半年度报告", None) == "2026"
    assert _fiscal_year("年度报告", 1774886400000) == "2025"     # filed 2026 → FY2025
    assert _fiscal_year("年度报告", None) == ""


def test_the_series_updater_reads_the_right_filings_and_sections(tmp_path, monkeypatch):
    """An extracted series (客车销量, GMV…) extends itself from new filings. For
    an A-share those are the cninfo 定期报告, and what matters is the management
    discussion — handing over the first 60k characters of a 200k-character
    report would usually miss the number."""
    from app.metrics import updater
    from app.tools import ashare_reports

    index = {"ticker": "600066.SS", "filings": [
        {"accession": "a1", "form": "年度报告", "title": "2025年年度报告", "fiscal_year": "2025",
         "filed": "2026-03-30", "report_date": "2025-12-31", "cumulative": True,
         "toc": build_toc(MD)},
        {"accession": "a2", "form": "半年度报告", "title": "2026年半年度报告", "fiscal_year": "2026",
         "filed": "2026-08-10", "report_date": "2026-06-30", "cumulative": True,
         "toc": build_toc(MD)},
        {"accession": "a3", "form": "第一季度报告", "title": "2026年第一季度报告",
         "fiscal_year": "2026", "filed": "2026-04-27", "report_date": "2026-03-31",
         "cumulative": False, "toc": build_toc(MD)},
        # A row written before `report_date` existed: the period must still
        # come out right, from the form.
        {"accession": "a4", "form": "第三季度报告", "title": "2025年第三季度报告",
         "fiscal_year": "2025", "filed": "2025-10-28", "toc": build_toc(MD)},
    ]}
    monkeypatch.setattr(ashare_reports, "load_index", lambda t: index)
    monkeypatch.setattr(ashare_reports, "read_text", lambda t, f: MD)

    quarterly = updater._new_filings({"ticker": "600066.SS", "grid": "quarterly",
                                      "last_source": "", "points": []})
    assert [f["period"] for f in quarterly] == ["2025-09-30", "2025-12-31",
                                                "2026-03-31", "2026-06-30"]
    assert [f["filed"] for f in quarterly] == sorted(f["filed"] for f in quarterly)
    # 一季报 figures are for the quarter; the others are cumulative, and the
    # model is told so or it would book 前三季度 sales as one quarter's.
    by_period = {f["period"]: f["kind"] for f in quarterly}
    assert "年初至报告期末" not in by_period["2026-03-31"]
    assert "年初至报告期末" in by_period["2026-06-30"]
    assert "年初至报告期末" in by_period["2025-09-30"]

    # An annual series ignores the interim report…
    annual = updater._new_filings({"ticker": "600066.SS", "grid": "annual",
                                   "last_source": "", "points": []})
    assert [f["period"] for f in annual] == ["2025"]

    # …and a series already fed the 年报 only sees what came after it.
    later = updater._new_filings({"ticker": "600066.SS", "grid": "quarterly",
                                  "last_source": "2026-03-30", "points": []})
    assert [f["period"] for f in later] == ["2026-03-31", "2026-06-30"]

    # The text handed to the model starts at the management discussion.
    assert quarterly[0]["text"].startswith("## 第三节 管理层讨论与分析")
