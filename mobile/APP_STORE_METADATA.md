# App Store Connect metadata — Valueland

Reference draft to paste into App Store Connect once the app record is
created. All limits are Apple's hard limits.

---

## Required fields

**Name (30 char)**
```
Valueland
```
> If taken, fallbacks: `Valueland: Value Stocks`, `Valueland Research`,
> `Valueland Equities`.

**Subtitle (30 char)**
```
Daily value-stock research
```

**Category (primary)**
`Finance`

**Category (secondary, optional)**
`News`

**Bundle ID**
`com.nathanhuang.valueland`  (already set in app.json)

---

## Privacy policy URL

```
https://value-agent-reports.vercel.app/privacy.html
```

## Support URL

```
https://github.com/nathanhuangzhi/value-agent
```

(Or any page you own. A GitHub repo or your personal site is fine.)

## Marketing URL (optional)

Leave blank, or use the same as Support.

---

## Description (4000 char)

```
Valueland is a daily equity-research app for value investors.

Every morning, our pipeline picks a new industry, runs a Munger-style
deep dive on every small- and mid-cap ticker in it, and renders a
clean per-company report you can read on your phone:

• Business overview: what the company does, end markets, customers,
  moat, regulatory exposure — extracted directly from the latest
  10-K so it's never out of date.

• Snapshot KPIs: market cap, TTM P/E, P/B, EV/Revenue, Free Cash
  Flow yield, profitability margins, ROE, debt/asset — at a glance.

• Historical statements: 10 years annual + 8 quarters of Income
  Statement, Balance Sheet, and Cash Flow, all from SEC EDGAR
  primary filings with yfinance gap-fill where SEC has no value.
  Sourced cell-by-cell.

• Static valuation multiples: Static P/E, Static P/S, and P/B
  computed per period from price × diluted shares ÷ annual baseline.

• Investment narrative: an LLM-written Munger-style write-up biased
  toward "too hard / PASS" over false-positive enthusiasm. Sources
  cited inline.

• Daily story-of-the-day: a one-pager summary of every batch,
  surfacing patterns across the day's companies.

No accounts. No tracking. No ads. The data comes from SEC EDGAR and
Yahoo Finance — both free, both public.

For research and educational purposes only. Not investment advice.
```

---

## Promotional text (170 char, editable any time without re-review)

```
Today's batch lands every morning. Swipe through every ticker in
the day's industry — full statements, valuation history, and a
Munger-style narrative on each.
```

---

## Keywords (100 char total, comma-separated, NO spaces after commas)

```
value investing,stocks,equity,sec filings,financial statements,dcf,munger,buffett,fundamentals
```
(99 chars — leaves 1 char of headroom.)

---

## What's New in This Version (4000 char, per release)

```
First public release of Valueland.

- Daily industry rotation across NYSE + Nasdaq
- Per-ticker reports with SEC + yfinance financial statements
- Swipe between companies in an industry like cards
- Daily story-of-the-day summary across every batch
```

---

## Screenshots required

App Store Connect needs at minimum these iPhone screenshot sizes,
3-10 each:

- **6.7" Display** (iPhone 15 Plus / 14 Pro Max): 1290 × 2796
- **6.5" Display** (iPhone 11 Pro Max): 1242 × 2688  → optional in
  recent versions, can be skipped if 6.7" provided
- **5.5" Display** (iPhone 8 Plus): 1242 × 2208  → required if you
  want to support older iPhones; Apple has been relaxing this

Easy way to capture: run the app in Xcode Simulator (iPhone 15 Pro
Max), `Cmd+S` saves a screenshot to your desktop. Or run on your
own iPhone 14 Pro / 15 / 16, screenshot with side button + volume
up, then `Save to Files` and AirDrop to your laptop.

Suggested set:
1. Home screen with today's batch banner + industry list
2. Industry detail with column-header table (PE, PB, etc)
3. Ticker detail header + snapshot KPIs
4. Ticker detail historical statements table
5. Ticker detail narrative section

**For TestFlight internal testing only, screenshots are NOT required.**

---

## Reviewer notes (Apple App Review)

```
Hi reviewers,

Valueland is a read-only equity research app. It does not require
an account or login. All data is fetched from a public CDN
(value-agent-reports.vercel.app) — no authentication needed.

The app contains a clear "not investment advice" disclaimer on each
ticker page footer, and the same wording in the privacy policy
(see Privacy URL).

There is no in-app purchase, no third-party SDK, and no ad network.

Encryption: the app only uses HTTPS for fetching JSON from our CDN.
Per ITSAppUsesNonExemptEncryption=false in Info.plist, we are
declaring no use of non-exempt encryption.

Test credentials: none needed — the app loads immediately on launch.

Thanks!
```

---

## Age rating questionnaire

When prompted, answer "No" to every question except possibly:

- **Unrestricted Web Access**: No (the app doesn't open URLs in a
  built-in browser; source-citation links go to Safari).
- **Gambling & Contests**: No
- **Profanity**: No
- **Sexual Content**: No
- **Violence**: No

Result will be 4+.
