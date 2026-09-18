"""    GET    /me/metrics                         → {metrics:[…]}
    POST   /me/metrics {name, expr, format?}    → the metric
    PUT    /me/metrics/{id} {name?, expr?, format?, position?}
    DELETE /me/metrics/{id}
    POST   /me/metrics/preview {expr, ticker}   → {series, latest, format} | {error}
    GET    /me/tickers/{T}/custom.json          → {metrics:[{…, series, latest, error}]}
    GET    /me/metrics/{id}/latest?tickers=A,B  → {values:{A: …}}
    GET    /me/metrics/aliases                  → the vocabulary (for the editor's autocomplete)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.auth import require_app_token
from app.auth.deps import current_user
from app.metrics import service
from app.metrics.expr import ALIASES, DERIVED, FUNCTIONS, SUFFIXES, ExprError

router = APIRouter(prefix="/me", tags=["metrics"], dependencies=[Depends(require_app_token)])


class MetricIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    expr: str = Field(min_length=1, max_length=500)
    format: str | None = None


class MetricPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    expr: str | None = Field(default=None, min_length=1, max_length=500)
    format: str | None = None
    position: int | None = Field(default=None, ge=0)


class Preview(BaseModel):
    expr: str = Field(min_length=1, max_length=500)
    ticker: str = Field(min_length=1, max_length=10)
    grid: str = "quarterly"


@router.get("/metrics/aliases")
def aliases():
    return {
        "metrics": [{"alias": a, "item": item, "kind": kind} for a, (item, kind) in ALIASES.items()],
        "derived": DERIVED, "suffixes": sorted(SUFFIXES), "functions": FUNCTIONS, "formats": list(service.FORMATS),
    }


@router.get("/metrics")
def list_metrics(user: dict = Depends(current_user)):
    return {"metrics": service.list_metrics(user["id"])}


@router.post("/metrics")
def create_metric(body: MetricIn, user: dict = Depends(current_user)):
    try:
        return service.create_metric(user["id"], body.name, body.expr, body.format)
    except ExprError as e:
        raise HTTPException(422, detail=str(e)) from e


@router.put("/metrics/{metric_id}")
def update_metric(metric_id: int, body: MetricPatch, user: dict = Depends(current_user)):
    try:
        m = service.update_metric(user["id"], metric_id, name=body.name, expr=body.expr, fmt=body.format, position=body.position)
    except ExprError as e:
        raise HTTPException(422, detail=str(e)) from e
    if not m:
        raise HTTPException(404, detail="metric not found")
    return m


@router.delete("/metrics/{metric_id}")
def delete_metric(metric_id: int, user: dict = Depends(current_user)):
    if not service.delete_metric(user["id"], metric_id):
        raise HTTPException(404, detail="metric not found")
    return {"deleted": metric_id}


@router.post("/metrics/preview")
def preview(body: Preview, user: dict = Depends(current_user)):
    return service.evaluate_expr(body.expr, body.ticker, grid="annual" if body.grid == "annual" else "quarterly")


@router.get("/tickers/{ticker}/custom.json")
def ticker_custom(ticker: str, user: dict = Depends(current_user)):
    return {"ticker": ticker.upper(), "metrics": service.evaluate_user_metrics(user["id"], ticker)}


@router.get("/metrics/{metric_id}/latest")
def metric_latest(metric_id: int, tickers: str = Query(min_length=1, max_length=2000), user: dict = Depends(current_user)):
    syms = [t.strip().upper() for t in tickers.split(",") if t.strip()][:200]
    values = service.latest_for_tickers(user["id"], metric_id, syms)
    if not values and not service.get_metric(user["id"], metric_id):
        raise HTTPException(404, detail="metric not found")
    return {"values": values}
