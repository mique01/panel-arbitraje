from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dashboard.app import build_dashboard
from app.runtime import get_runtime


runtime = get_runtime()
repository = runtime["repository"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


app = FastAPI(title="GGAL Micro-Scalping Platform", lifespan=lifespan)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", include_in_schema=False)
def dashboard_fallback():
    return HTMLResponse(
        "<html><body><h1>Dashboard ready</h1><p>Serve with Panel integration enabled or use /api endpoints.</p></body></html>"
    )


@app.get("/api/watchlist/active")
def get_active_watchlist():
    return repository.get_active_watchlist()


@app.put("/api/watchlist/active")
def put_active_watchlist(payload: dict):
    return repository.update_active_watchlist(payload)


@app.get("/api/marketdata/current")
def get_marketdata_current():
    return repository.get_latest_market_state()


@app.get("/api/tape/current")
def get_tape_current(limit: int = 50):
    return repository.get_current_tape(limit=limit)


@app.get("/api/signals/active")
def get_signals_active():
    return repository.get_active_signals()


@app.get("/api/signals/history")
def get_signals_history(limit: int = 100):
    return repository.get_signal_history(limit=limit)


@app.get("/api/paper/orders")
def get_paper_orders(limit: int = 50):
    return repository.get_paper_orders(limit=limit)


@app.get("/api/paper/positions")
def get_paper_positions(limit: int = 50):
    return repository.get_paper_positions(limit=limit)


@app.get("/api/paper/stats")
def get_paper_stats():
    return repository.get_paper_stats()


@app.get("/api/settings/strategy")
def get_strategy_settings():
    return repository.get_strategy_settings()


@app.put("/api/settings/strategy")
def put_strategy_settings(payload: dict):
    return repository.update_strategy_settings(payload)


@app.get("/api/system/health")
def get_system_health():
    return repository.get_system_health()


def _mount_panel_dashboard() -> None:
    try:
        import panel as pn
        from panel.io import fastapi as panel_fastapi
    except Exception:
        return
    pn.extension("tabulator")
    add_application = getattr(panel_fastapi, "add_application", None)
    if add_application is not None:
        add_application("/dashboard", build_dashboard, app=app, title="GGAL Micro-Scalping Dashboard")
        return
    add_applications = getattr(panel_fastapi, "add_applications", None)
    if add_applications is not None:
        add_applications({"/dashboard": build_dashboard}, app=app)


_mount_panel_dashboard()
