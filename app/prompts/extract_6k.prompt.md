---
provider: "deepseek"
model: "deepseek-v4-flash"
temperature: 0.0
description: "Extract the full financial statements from a foreign private issuer's 6-K earnings press release (EX-99.1) into JSON: every line item as reported, plus a mapping onto the pipeline's standard metric keys. JSON mode + Pydantic-validated; ~$0.004 per filing."
---

# Task
Below is the text of a quarterly-results press release that a foreign private issuer furnished to the SEC on Form 6-K (Exhibit 99.1). Extract its financial statements into ONE JSON object. Be exhaustive on line items and exact on numbers. Do not compute anything the document doesn't state, except unit scaling.

# Output template
Return exactly this shape (JSON object, no prose):

```json
{
  "company": "PDD Holdings Inc.",
  "period_end": "2026-06-30",
  "period_type": "quarter",
  "fiscal_label": "Q2 2026",
  "currency": "CNY",
  "unit_scale": 1000,
  "convenience_usd_rate": 7.1586,
  "cash_flow_period_type": "quarter",
  "statements": {
    "income_statement": [
      {"label": "Total revenues", "value": 112392600000, "prior_year_value": 103984700000}
    ],
    "balance_sheet": [
      {"label": "Cash and cash equivalents", "value": 60152300000, "prior_year_value": 57768200000}
    ],
    "cash_flow": [
      {"label": "Net cash provided by operating activities", "value": 30000000000, "prior_year_value": null}
    ]
  },
  "standard": {
    "revenue": 112392600000,
    "cost_of_revenue": null,
    "gross_profit": null,
    "operating_income": null,
    "net_income": null,
    "diluted_eps_per_ads": null,
    "diluted_ads": null,
    "cash": null,
    "total_assets": null,
    "total_liabilities": null,
    "stockholders_equity": null,
    "short_term_debt": null,
    "long_term_debt": null,
    "accounts_payable": null,
    "deferred_revenue": null,
    "operating_cf": null,
    "capex": null,
    "receivables": null,
    "inventory": null,
    "ppe_net": null,
    "goodwill": null,
    "intangibles": null,
    "long_term_investments": null
  }
}
```

# Rules
- **period_end**: the end date of the reporting period the release is about (ISO date). **period_type**: `quarter`, `half_year`, `nine_months`, or `full_year`. **fiscal_label**: as the company words it (e.g. "Q2 2026", "Second Quarter 2026", "Fiscal Q4 2026").
- **currency**: the currency the statements are in (`CNY`, `HKD`, `USD`, …). **unit_scale**: the scale the tables are printed in (`1000` for "in thousands", `1000000` for "in millions", `1` if full units). **convenience_usd_rate**: the rate the release quotes for its US$ convenience columns (currency per 1 USD), or null.
- **Every `value` must be in FULL currency units** — multiply the printed number by `unit_scale`. Negative for losses / outflows / parentheses.
- **statements**: list EVERY line item of the consolidated income statement, balance sheet, and cash-flow statement, in the document's order, using the document's own labels (English). `value` = the current period column in the reporting currency (NOT the US$ convenience column). `prior_year_value` = the same-period-prior-year column if present, else null. Skip per-share and per-ADS rows from these lists only if they are clearly not currency amounts; keep everything else including subtotals.
- If the income statement has both "three months ended" and "six/nine months ended" columns, use the **three months** column for `income_statement` and set `period_type` = `quarter`. For the cash-flow statement use the shortest period column available and say which in `cash_flow_period_type` (`quarter`, `half_year`, `nine_months`, `full_year`); null if there is no cash-flow statement.
- **standard**: map onto these keys from the statements you extracted (reporting currency, full units): revenue, cost_of_revenue, gross_profit, operating_income (income from operations), net_income (attributable to ordinary shareholders of the company), diluted_eps_per_ads (diluted earnings **per ADS**, not per ordinary share, in the reporting currency), diluted_ads (weighted-average diluted **ADS** count — if only ordinary shares are given, divide by the ordinary-shares-per-ADS ratio the release states; null if unknown), cash (cash and cash equivalents), total_assets, total_liabilities, stockholders_equity (total shareholders' equity), short_term_debt (short-term borrowings + current portion of long-term debt), long_term_debt, accounts_payable, deferred_revenue (contract liabilities / deferred revenue), operating_cf, capex (purchase of property and equipment, negative), receivables (accounts receivable, net — not other/related-party receivables), inventory, ppe_net (property and equipment, net), goodwill, intangibles (intangible assets, net, PLUS land-use rights if listed separately), long_term_investments (non-current investments: equity-method investees, long-term/other investments, held-to-maturity — not short-term investments). Use null for anything the release does not state.
- If the document is not a financial results release (no statements), return `{"company": null, "period_end": null, "statements": {"income_statement": [], "balance_sheet": [], "cash_flow": []}, "standard": {}}` with the other fields null.

# Document
Company: {{company}} ({{ticker}}); filed {{filed}}; accession {{accession}}.

{{document}}
