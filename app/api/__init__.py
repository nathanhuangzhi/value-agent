"""JSON API surface for the React Native mobile app.

Routes live in `app.api.routes`; the FastAPI app in `app.main` includes
the router. All endpoints are read-only — they expose data the pipeline
already wrote to disk (`companies_*.json`, `daily_industry_log.json`)
plus a small amount of derived shape that's nicer for mobile consumption.
"""
