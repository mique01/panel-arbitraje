"""Compatibility entrypoint for direct Panel serving."""

from app.dashboard.app import build_dashboard

dashboard = build_dashboard()
dashboard.servable()
