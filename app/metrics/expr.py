"""A small, safe expression language for user-defined metrics.

    fcf / revenue
    net_income.ttm / mcap
    (cash + sti - total_debt) / shares
    revenue.yoy > 0.2 and fcf > 0
    avg(fcf, 4) / max(revenue, 1)

Grammar (Pratt parser, no eval):
    expr     := or
    or       := and ("or" and)*
    and      := cmp ("and" cmp)*
    cmp      := sum (("<" | "<=" | ">" | ">=" | "==" | "!=") sum)?
    sum      := term (("+" | "-") term)*
    term     := unary (("*" | "/") unary)*
    unary    := "-" unary | "not" unary | postfix
    postfix  := primary ("." NAME)*                  suffixes: q ttm fy yoy abs
    primary  := NUMBER | NAME | NAME "(" args ")" | "(" expr ")"

Every value is a SERIES aligned on the evaluation grid (quarterly or
annual periods); arithmetic is element-wise, a missing operand makes the
result None for that period, and division by zero is None. Functions:
abs(x) max(a, b) min(a, b) avg(x, n) lag(x, n) sum(x, n).

`parse()` returns an AST; `evaluate()` walks it against a `Context`
providing the base series. `validate()` type-checks suffixes (`.ttm` on a
balance-sheet item is an error) without needing data.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ---- identifiers --------------------------------------------------------------

# alias → (statement item name, kind). kind: flow (income / cash flow), stock (balance sheet),
# per_share (already per share), market (price-derived).
ALIASES: dict[str, tuple[str, str]] = {
    "revenue": ("Total Revenue", "flow"),
    "cogs": ("Cost Of Revenue", "flow"),
    "gross_profit": ("Gross Profit", "flow"),
    "op_income": ("Operating Income", "flow"),
    "net_income": ("Net Income", "flow"),
    "eps": ("Diluted EPS", "per_share"),
    "sga": ("Selling General And Administration", "flow"),
    "s_and_m": ("Selling And Marketing Expense", "flow"),
    "g_and_a": ("General And Administrative Expense", "flow"),
    "ocf": ("Cash Flow From Continuing Operating Activities", "flow"),
    "capex": ("Capital Expenditure", "flow"),
    "fcf": ("Free Cash Flow", "flow"),
    "shares": ("Diluted Average Shares", "stock"),
    "cash": ("Cash And Cash Equivalents", "stock"),
    "sti": ("Short Term Investments", "stock"),
    "restricted_cash": ("Restricted Cash", "stock"),
    "cash_all": ("Cash Cash Equivalents And Short Term Investments", "stock"),
    "receivables": ("Receivables", "stock"),
    "inventory": ("Inventory", "stock"),
    "ppe": ("Net PPE", "stock"),
    "goodwill": ("Goodwill", "stock"),
    "intangibles": ("Other Intangible Assets", "stock"),
    "lt_investments": ("Long Term Investments", "stock"),
    "total_assets": ("Total Assets", "stock"),
    "total_liabilities": ("Total Liabilities", "stock"),
    "equity": ("Common Stock Equity", "stock"),
    "total_debt": ("Total Debt", "stock"),
    "current_debt": ("Current Debt", "stock"),
    "lt_debt": ("Long Term Debt", "stock"),
    "leases": ("Lease Obligations", "stock"),
    "ap": ("Accounts Payable", "stock"),
    "accrued": ("Accrued Liabilities", "stock"),
    "deferred_revenue": ("Deferred Revenue", "stock"),
    # market
    "price": ("__price__", "market"),
    "mcap": ("__mcap__", "market"),
}
DERIVED: dict[str, str] = {           # shorthands expanded before parsing
    "pe": "mcap / net_income.ttm",
    "pb": "mcap / equity",
    "ps": "mcap / revenue.ttm",
    "pfcf": "mcap / fcf.ttm",
    "pocf": "mcap / ocf.ttm",
    "ev": "mcap + total_debt - cash_all",
}
SUFFIXES = {"q", "ttm", "fy", "yoy", "abs"}
FUNCTIONS = {"abs": 1, "max": 2, "min": 2, "avg": 2, "lag": 2, "sum": 2}


class ExprError(ValueError):
    pass


# ---- tokenizer ---------------------------------------------------------------------

_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][+-]?\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|(<=|>=|==|!=|[<>+\-*/().,]))")


def tokenize(src: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    src = src.strip()
    while pos < len(src):
        while pos < len(src) and src[pos].isspace():
            pos += 1
        if pos >= len(src):
            break
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise ExprError(f"unexpected character {src[pos]!r} at position {pos}")
        num, name, op = m.groups()
        if num is not None:
            out.append(("num", num))
        elif name is not None:
            out.append(("kw" if name in ("and", "or", "not") else "name", name))
        else:
            out.append(("op", op))
        pos = m.end()
    return out


# ---- AST -------------------------------------------------------------------------

@dataclass
class Node:
    kind: str                       # num | ref | suffix | unary | binary | call
    value: Any = None
    args: list[Node] = field(default_factory=list)


_BIN_PREC = {"or": 1, "and": 2, "<": 3, "<=": 3, ">": 3, ">=": 3, "==": 3, "!=": 3, "+": 4, "-": 4, "*": 5, "/": 5}


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.t = tokens
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, kind=None, val=None):
        k, v = self.peek()
        if k is None or (kind and k != kind) or (val and v != val):
            raise ExprError(f"expected {val or kind} but found {v!r}" if k else f"unexpected end of expression (expected {val or kind})")
        self.i += 1
        return v

    def parse(self) -> Node:
        node = self.expr(0)
        if self.peek()[0] is not None:
            raise ExprError(f"unexpected {self.peek()[1]!r}")
        return node

    def expr(self, min_prec: int) -> Node:
        left = self.unary()
        while True:
            k, v = self.peek()
            if k not in ("op", "kw") or v not in _BIN_PREC or _BIN_PREC[v] < min_prec:
                return left
            self.i += 1
            right = self.expr(_BIN_PREC[v] + 1)
            left = Node("binary", v, [left, right])

    def unary(self) -> Node:
        k, v = self.peek()
        if k == "op" and v == "-":
            self.i += 1
            return Node("unary", "-", [self.unary()])
        if k == "kw" and v == "not":
            self.i += 1
            return Node("unary", "not", [self.unary()])
        return self.postfix()

    def postfix(self) -> Node:
        node = self.primary()
        while self.peek() == ("op", "."):
            self.i += 1
            suffix = self.take("name")
            if suffix not in SUFFIXES:
                raise ExprError(f"unknown suffix .{suffix} (use .q .ttm .fy .yoy .abs)")
            node = Node("suffix", suffix, [node])
        return node

    def primary(self) -> Node:
        k, v = self.peek()
        if k == "num":
            self.i += 1
            return Node("num", float(v))
        if k == "op" and v == "(":
            self.i += 1
            node = self.expr(0)
            self.take("op", ")")
            return node
        if k == "name":
            self.i += 1
            if self.peek() == ("op", "("):
                if v not in FUNCTIONS:
                    raise ExprError(f"unknown function {v}()")
                self.i += 1
                args = [self.expr(0)]
                while self.peek() == ("op", ","):
                    self.i += 1
                    args.append(self.expr(0))
                self.take("op", ")")
                if len(args) != FUNCTIONS[v]:
                    raise ExprError(f"{v}() takes {FUNCTIONS[v]} argument(s)")
                return Node("call", v, args)
            if v in DERIVED:
                return parse(DERIVED[v])
            if v not in ALIASES:
                raise ExprError(f"unknown metric {v!r}")
            return Node("ref", v)
        raise ExprError(f"unexpected {v!r}" if k else "unexpected end of expression")


def parse(src: str) -> Node:
    if not src or not src.strip():
        raise ExprError("empty expression")
    return _Parser(tokenize(src)).parse()


def validate(src: str) -> Node:
    """Parse and check suffix use; raises ExprError with a human message."""
    node = parse(src)

    def kind_of(n: Node) -> str:
        if n.kind == "ref":
            return ALIASES[n.value][1]
        if n.kind == "suffix":
            inner = kind_of(n.args[0])
            if n.value == "ttm" and inner in ("stock", "market"):
                raise ExprError(f".ttm only applies to income / cash-flow items, not {n.args[0].value!r}")
            if n.value == "q" and inner == "market":
                return inner
            return "flow" if n.value == "ttm" else inner
        for a in n.args:
            kind_of(a)
        return "mixed"

    kind_of(node)
    return node


def references(node: Node) -> set[str]:
    if node.kind == "ref":
        return {node.value}
    out: set[str] = set()
    for a in node.args:
        out |= references(a)
    return out


# ---- evaluation ---------------------------------------------------------------

Series = list[float | None]


@dataclass
class Context:
    """Base series on the evaluation grid.

    periods:   the grid's period labels (ascending)
    quarterly: alias → series on the quarterly grid (single-quarter values)
    annual:    alias → series on the ANNUAL grid (fiscal years, ascending), plus
               annual_periods for alignment of .fy on a quarterly grid
    """
    periods: list[str]
    grid: str                                   # "quarterly" | "annual"
    values: dict[str, Series]                   # alias → series on `periods`
    annual_periods: list[str] = field(default_factory=list)
    annual_values: dict[str, Series] = field(default_factory=dict)


def _lift(f: Callable[..., float | None]) -> Callable[..., Series]:
    def run(*series: Series) -> Series:
        n = len(series[0]) if series else 0
        out: Series = []
        for i in range(n):
            vals = [s[i] for s in series]
            out.append(None if any(v is None for v in vals) else f(*vals))
        return out
    return run


def _div(a, b):
    return None if b == 0 else a / b


_BINARY = {
    "+": _lift(lambda a, b: a + b), "-": _lift(lambda a, b: a - b),
    "*": _lift(lambda a, b: a * b), "/": _lift(_div),
    "<": _lift(lambda a, b: float(a < b)), "<=": _lift(lambda a, b: float(a <= b)),
    ">": _lift(lambda a, b: float(a > b)), ">=": _lift(lambda a, b: float(a >= b)),
    "==": _lift(lambda a, b: float(a == b)), "!=": _lift(lambda a, b: float(a != b)),
    "and": _lift(lambda a, b: float(bool(a) and bool(b))), "or": _lift(lambda a, b: float(bool(a) or bool(b))),
}


def _rolling(series: Series, n: int, agg: Callable[[list[float]], float]) -> Series:
    out: Series = []
    for i in range(len(series)):
        window = series[max(0, i - n + 1): i + 1]
        out.append(None if len(window) < n or any(v is None for v in window) else agg([v for v in window if v is not None]))
    return out


def _lag(series: Series, n: int) -> Series:
    return [None] * min(n, len(series)) + series[: max(0, len(series) - n)]


def _fy_on_grid(ctx: Context, alias: str) -> Series:
    """The latest completed fiscal-year value at each grid period."""
    if ctx.grid == "annual":
        return ctx.values.get(alias) or [None] * len(ctx.periods)
    ann = ctx.annual_values.get(alias) or []
    out: Series = []
    for p in ctx.periods:
        best = None
        for fy, v in zip(ctx.annual_periods, ann, strict=False):
            # FY label "2025" is complete once the quarter reaches that year's end
            # (calendar-year assumption; 52-week filers are keyed the same way).
            if v is not None and (fy < p[:4] or (fy == p[:4] and p[5:7] == "12")):
                best = v
        out.append(best)
    return out


def evaluate(node: Node, ctx: Context) -> Series:
    n = len(ctx.periods)
    if node.kind == "num":
        return [node.value] * n
    if node.kind == "ref":
        return ctx.values.get(node.value) or [None] * n
    if node.kind == "suffix":
        inner = node.args[0]
        if node.value == "fy":
            if inner.kind != "ref":
                raise ExprError(".fy applies to a metric name, e.g. revenue.fy")
            return _fy_on_grid(ctx, inner.value)
        s = evaluate(inner, ctx)
        if node.value == "q":
            return s
        if node.value == "abs":
            return [None if v is None else abs(v) for v in s]
        if node.value == "ttm":
            return s if ctx.grid == "annual" else _rolling(s, 4, sum)
        if node.value == "yoy":
            prev = _lag(s, 1 if ctx.grid == "annual" else 4)
            return _lift(lambda a, b: None if b == 0 else (a - b) / abs(b))(s, prev)
        raise ExprError(f"unknown suffix {node.value}")
    if node.kind == "unary":
        s = evaluate(node.args[0], ctx)
        if node.value == "-":
            return [None if v is None else -v for v in s]
        return [None if v is None else float(not v) for v in s]
    if node.kind == "binary":
        return _BINARY[node.value](evaluate(node.args[0], ctx), evaluate(node.args[1], ctx))
    if node.kind == "call":
        name = node.value
        if name == "abs":
            return [None if v is None else abs(v) for v in evaluate(node.args[0], ctx)]
        if name in ("max", "min"):
            f = max if name == "max" else min
            return _lift(lambda a, b: f(a, b))(evaluate(node.args[0], ctx), evaluate(node.args[1], ctx))
        s = evaluate(node.args[0], ctx)
        k = node.args[1]
        if k.kind != "num" or int(k.value) < 1:
            raise ExprError(f"{name}() needs a positive whole number of periods")
        w = int(k.value)
        if name == "avg":
            return _rolling(s, w, lambda xs: sum(xs) / len(xs))
        if name == "sum":
            return _rolling(s, w, sum)
        if name == "lag":
            return _lag(s, w)
    raise ExprError(f"cannot evaluate {node.kind}")


def is_boolean(node: Node) -> bool:
    return (node.kind == "binary" and node.value in ("<", "<=", ">", ">=", "==", "!=", "and", "or")) or \
           (node.kind == "unary" and node.value == "not")


def guess_format(node: Node) -> str:
    """A sensible display format when the user hasn't chosen one."""
    if is_boolean(node):
        return "bool"
    if node.kind == "binary" and node.value == "/":
        return "ratio"
    if node.kind == "suffix" and node.value == "yoy":
        return "pct"
    refs = references(node)
    if refs and all(ALIASES[r][1] in ("flow", "stock", "market") and r not in ("shares", "price") for r in refs):
        return "money"
    return "number"


__all__ = ["ALIASES", "DERIVED", "Context", "ExprError", "Node", "evaluate", "guess_format", "is_boolean",
           "parse", "references", "validate"]
