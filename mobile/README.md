# Valueland — mobile

React Native + Expo app that consumes the value-agent FastAPI JSON
endpoints (`/api/...`) and presents the daily equity research in a
native UI.

## First-time setup

Requires **Expo Go SDK 54** on the phone (App Store / Play Store auto-update).

```bash
cd mobile/
npm install                       # install all Expo + RN deps (~3 min)
npm run fix-deps                  # `expo install --fix` aligns peer-dep
                                  # versions to whatever exact pins SDK 54
                                  # wants; harmless if everything's already
                                  # correct.

cp .env.example .env              # then edit EXPO_PUBLIC_API_URL
                                  # to your laptop's LAN IP, e.g.
                                  # EXPO_PUBLIC_API_URL=http://192.168.68.63:8000
```

If you ever upgrade to a newer Expo SDK, run `npx create-expo-app@latest --template blank-typescript --no-install /tmp/new-app` and diff its `package.json` against this one to see which pins moved.

## Running in dev

Two terminals:

**Terminal 1 — backend (from repo root):**
```bash
./venv/bin/uvicorn app.main:app --host 0.0.0.0 --reload
# bind to 0.0.0.0 so the phone can reach you, not just localhost
```

**Terminal 2 — mobile (from `mobile/`):**
```bash
npm run start
# scan the QR code with Expo Go on your phone (App Store / Play Store)
# OR press i for iOS simulator, a for Android emulator, w for web preview
```

Make sure phone + laptop are on the same Wi-Fi network.

## Project layout

```
mobile/
├── app/                  Expo Router file-based routes
│   ├── _layout.tsx       Root stack navigator + theme wiring
│   ├── index.tsx         Home: industry list
│   ├── industry/
│   │   └── [slug].tsx    Industry detail: ticker list
│   └── ticker/
│       └── [symbol].tsx  Ticker detail: snapshot + narrative + validation
├── src/
│   ├── api/
│   │   ├── client.ts     Fetch wrapper around the FastAPI endpoints
│   │   └── types.ts      TypeScript shapes matching the API responses
│   ├── components/       Reusable UI pieces
│   │   ├── KPIGrid.tsx
│   │   ├── Section.tsx
│   │   ├── StatusBadge.tsx
│   │   └── TickerRow.tsx
│   ├── theme/
│   │   └── colors.ts     Single source of truth for palette + spacing
│   └── utils/
│       └── format.ts     Number / date formatters (mirror Python helpers)
├── app.json              Expo config (name, bundle IDs, plugins)
├── babel.config.js
├── package.json
├── tsconfig.json
└── README.md             ← you are here
```

## Adding a screen

Expo Router uses file-based routing. To add `/watchlist`, create
`app/watchlist.tsx`. To add a parameterized route like `/industry/:slug`,
create `app/industry/[slug].tsx`. Then add a `Stack.Screen` entry in
`app/_layout.tsx` to configure the navigation bar.

## Adding an API endpoint

1. Add the route + Pydantic-like dict shape on the backend
   (`app/api/routes.py`).
2. Add the matching TypeScript type to `src/api/types.ts`.
3. Add a method to the `api` object in `src/api/client.ts`.
4. Call it from a screen with `useEffect` + `useState` (this app is
   intentionally not using React Query yet — straightforward
   useEffect+fetch keeps the dep list small while we're prototyping).

## What's still TODO

- **Price chart** on the ticker detail screen (currently shows snapshot
  KPIs + narrative only). Plan: use `react-native-svg` to draw a
  sparkline directly from the `/api/tickers/{t}/price-history` payload.
- **Historical statements table** — the big income/balance/cashflow
  matrix from the web report. Likely scroll-snap horizontally on mobile.
- **Watchlist** with persistent storage (AsyncStorage) and push
  notifications when a watched ticker's status changes.
- **Today's digest** screen — top of the home screen, summarizing the
  most recent daily-scan batch with the LLM-generated text.
- **App icon + splash screen** assets — currently using Expo defaults.
