---
provider: "deepseek"
model: "deepseek-v4-flash"
temperature: 0.0
description: "Map an already-extracted 6-K statement (every line item, reporting currency) onto the pipeline's standard metrics using precise definitions aligned with Yahoo Finance's, so 6-K-derived figures reconcile with Yahoo. Small input, ~300-token output; ~$0.001 per filing."
---

# Task
Below are the line items of a foreign private issuer's quarterly results release (income statement, balance sheet, cash-flow statement), already extracted, in **{{currency}}** full units. Map them onto the standard metrics defined here. Return ONE JSON object with exactly these keys (number or null). Sum lines where a definition says so; never invent a number that isn't the sum of stated lines.

# Definitions (aligned with Yahoo Finance so the two reconcile)
Income statement (three-month period):
- `revenue`: total net revenues.
- `cost_of_revenue`: cost of revenues as a POSITIVE number.
- `gross_profit`: gross profit if stated, else revenue − cost_of_revenue.
- `operating_income`: income/(loss) from operations (GAAP, not non-GAAP).
- `net_income`: net income attributable to the company's ordinary/common shareholders — after non-controlling interests AND after any accretion/deemed dividends on preferred shares (the last "attributable to ... shareholders" line). Negative for a loss.
- `diluted_eps_per_ads`: diluted earnings per ADS (if only per ordinary share is given, multiply by the ordinary-shares-per-ADS ratio stated in the release; null if the ratio isn't stated).
- `diluted_ads`: weighted-average diluted ADS count (ordinary shares ÷ ratio when only ordinary shares are given; null if unknown).

Balance sheet (period end):
- `cash`: cash and cash equivalents only (exclude restricted cash and client/customer cash). If the release only gives a combined line such as "Cash, cash equivalents and restricted cash", put that combined figure here and set `restricted_cash` to null.
- `restricted_cash`: restricted cash + restricted deposits (current and non-current) + cash held on behalf of clients/customers.
- `short_term_investments`: short-term investments + term/time deposits + securities purchased under agreements to resell + current financial assets at fair value / marketable securities.
- `receivables`: ALL current receivables: accounts receivable, other receivables, receivables from online payment platforms, amounts due from related parties, interest receivable, loans and advances (current), receivables from clients / brokers / clearing organizations / fund distributors. EXCLUDE any line that starts with "Prepayments" / "Prepaid" ("Prepayments and other current assets", "Prepaid expenses and other current assets") even if it may contain receivables, and exclude non-current loans. Include "Other receivables and prepayments" only when the line is led by receivables.
- `inventory`: inventories.
- `ppe_net`: property and equipment, net — exclude land-use rights and right-of-use assets.
- `goodwill`: goodwill. If the release only gives a combined "Goodwill and intangible assets" line, set goodwill to null and put the combined figure in `intangibles`.
- `intangibles`: intangible assets, net + land-use rights (+ the combined goodwill-and-intangibles line when goodwill isn't separate).
- `long_term_investments`: all non-current investments: equity-method investees, long-term investments, long-term deposits, held-to-maturity and available-for-sale securities (non-current), other investments.
- `total_assets`, `total_liabilities`: as stated (total liabilities excludes mezzanine equity).
- `stockholders_equity`: equity attributable to the company's shareholders — EXCLUDING non-controlling interests and mezzanine equity ("Total <Company>'s shareholders' equity"). If only a single total equity line is given, use it.
- `short_term_debt`: short-term borrowings/loans + current portion of long-term debt + securities sold under agreements to repurchase + current convertible notes. Exclude lease liabilities and payables to clients/brokers.
- `long_term_debt`: non-current borrowings, notes, bonds, convertible notes. Exclude lease liabilities.
- `accounts_payable`: accounts payable (trade).
- `deferred_revenue`: CURRENT deferred revenue / contract liabilities + advances/deposits from customers. Exclude non-current deferred income (often government grants or asset-related deferrals, not customer money).

Cash flow (three-month column if the statement has one; otherwise null for both):
- `operating_cf`: net cash provided by/(used in) operating activities.
- `capex`: purchases of property and equipment (+ intangible assets if in the same line), as a NEGATIVE number.

# Output template
```json
{"revenue": null, "cost_of_revenue": null, "gross_profit": null, "operating_income": null, "net_income": null,
 "diluted_eps_per_ads": null, "diluted_ads": null,
 "cash": null, "restricted_cash": null, "short_term_investments": null, "receivables": null, "inventory": null,
 "ppe_net": null, "goodwill": null, "intangibles": null, "long_term_investments": null,
 "total_assets": null, "total_liabilities": null, "stockholders_equity": null,
 "short_term_debt": null, "long_term_debt": null, "accounts_payable": null, "deferred_revenue": null,
 "operating_cf": null, "capex": null}
```

# Filing
{{company}} ({{ticker}}), period ending {{period_end}} ({{fiscal_label}}); cash-flow column: {{cash_flow_period_type}}; ADS ratio note: {{ads_note}}

## Income statement
{{income_statement}}

## Balance sheet
{{balance_sheet}}

## Cash-flow statement
{{cash_flow}}
