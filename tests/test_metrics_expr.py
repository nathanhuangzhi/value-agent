import pytest

from app.metrics.expr import Context, ExprError, evaluate, guess_format, parse, references, validate

Q = ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]
CTX = Context(
    periods=Q, grid="quarterly",
    values={"revenue": [100, 110, 120, 130, 140], "net_income": [10, 12, None, 15, 16],
            "mcap": [1000, 1100, 1200, 1300, 1400], "equity": [500, 520, 540, 560, 580],
            "fcf": [5, 6, 7, 8, 9], "shares": [10, 10, 10, 10, 10]},
    annual_periods=["2024", "2025"], annual_values={"revenue": [380, 430]},
)


def ev(expr, ctx=CTX):
    return evaluate(validate(expr), ctx)


def test_arithmetic_and_null_propagation():
    assert ev("net_income / revenue")[0] == pytest.approx(0.1)
    assert ev("net_income / revenue")[2] is None            # missing operand → None
    assert ev("revenue / (revenue - revenue)") == [None] * 5   # division by zero → None
    assert ev("-net_income.abs")[1] == -12
    assert ev("(mcap + 1) / equity")[0] == pytest.approx(1001 / 500)


def test_suffixes():
    assert ev("revenue.ttm") == [None, None, None, 460, 500]
    assert ev("revenue.yoy")[4] == pytest.approx(0.4)
    assert ev("revenue.fy") == [380, 430, 430, 430, 430]        # FY2025 complete from the 2025-12 quarter on
    ctx_early = Context(periods=["2025-03-31", "2025-12-31"], grid="quarterly", values={},
                        annual_periods=["2024", "2025"], annual_values={"revenue": [380, 430]})
    assert ev("revenue.fy", ctx_early) == [380, 430]


def test_functions_and_derived():
    assert ev("avg(fcf, 2)") == [None, 5.5, 6.5, 7.5, 8.5]
    assert ev("sum(fcf, 4)")[4] == 30
    assert ev("lag(revenue, 1)") == [None, 100, 110, 120, 130]
    assert ev("max(revenue, 125)") == [125, 125, 125, 130, 140]
    assert ev("pe")[4] == pytest.approx(1400 / (12 + 15 + 16 + 10)) if False else True   # ttm has a None inside → None
    assert ev("pe")[4] is None
    assert ev("pb")[0] == 2.0
    assert references(parse("pe + fcf")) == {"mcap", "net_income", "fcf"}


def test_booleans():
    assert ev("revenue > 115 and fcf > 6") == [0.0, 0.0, 1.0, 1.0, 1.0]
    assert ev("not (revenue > 115)") == [1.0, 1.0, 0.0, 0.0, 0.0]
    assert guess_format(parse("revenue > 1")) == "bool"


def test_format_guess():
    assert guess_format(parse("fcf / revenue")) == "pct"
    assert guess_format(parse("mcap / net_income.ttm")) == "ratio"
    assert guess_format(parse("(cash + sti - total_debt) / shares")) == "number"
    assert guess_format(parse("fcf / 4")) == "ratio"
    assert guess_format(parse("revenue.yoy")) == "pct"
    assert guess_format(parse("avg(fcf, 4)")) == "money"
    assert guess_format(parse("cash + sti - total_debt")) == "money"
    assert guess_format(parse("shares")) == "number"


@pytest.mark.parametrize("bad, msg", [
    ("equity.ttm", ".ttm only applies"),
    ("foo / 2", "unknown metric"),
    ("revenue +", "unexpected end"),
    ("avg(fcf)", "takes 2"),
    ("revenue.zzz", "unknown suffix"),
    ("1 $ 2", "unexpected character"),
    ("", "empty"),
    ("import os", "unknown metric"),
])
def test_errors(bad, msg):
    with pytest.raises(ExprError, match=msg):
        validate(bad)


def test_annual_grid():
    ctx = Context(periods=["2023", "2024", "2025"], grid="annual",
                  values={"revenue": [300, 380, 430], "net_income": [30, 40, 50]})
    assert ev("net_income.ttm / revenue", ctx)[2] == pytest.approx(50 / 430)   # .ttm == the annual value
    assert ev("revenue.yoy", ctx)[1] == pytest.approx(80 / 300)


def test_user_series_references():
    from app.metrics.expr import user_refs
    n = validate("revenue / $gmv")
    assert user_refs(n) == {"gmv"} and references(n) == {"revenue"}
    ctx = Context(periods=["2026-03-31", "2026-06-30"], grid="quarterly", values={"revenue": [100, 120]},
                  user_values={"gmv": [400, 480]})
    assert evaluate(n, ctx) == [0.25, 0.25]
    assert evaluate(validate("$missing + 1"), ctx) == [None, None]
    assert evaluate(validate("$gmv.ttm"), ctx) == [None, None]          # allowed, just needs four quarters
