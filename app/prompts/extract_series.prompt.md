---
provider: "deepseek"
model: "deepseek-v4-flash"
temperature: 0.0
description: "Extend a user's extracted series (GMV, a segment's operating income, …) from one new filing: find the value for the new period, or say it isn't there. JSON mode, ~$0.003 per filing."
---

# Task
A user tracks **{{label}}** (`${{name}}`, unit {{unit}}{{currency_note}}) for {{company}} ({{ticker}}), {{grid}} periods. Their note on where it comes from:

> {{source_hint}}

Known points (most recent last): {{known_points}}

Below is a newer filing ({{filing_kind}}, {{filed}}). Find the value of this series for the period(s) this filing reports — most often just the newest period — in the SAME unit and currency as the known points (e.g. if known points are in full CNY, convert "RMB 50.6 billion" to 50600000000). Return ONE JSON object:

```json
{"points": [{"period": "2026-06-30", "value": 50600000000, "source": "6-K 2026-08-25 Highlights: total GMV RMB 50.6 billion"}], "note": ""}
```

- `period`: {{period_rule}}
- Include a prior-period restatement only if the filing explicitly restates it.
- If the filing does not disclose the series, return `{"points": [], "note": "<why, in one sentence>"}`. Never guess or derive from other figures.

# Filing text
{{text}}
