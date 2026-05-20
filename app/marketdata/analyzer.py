from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

from app.marketdata.models import InstrumentSnapshot


class OrderBookAnalyzer:
    def __init__(self, depth: int = 5):
        self.depth = depth

    def analyze(self, snapshot: InstrumentSnapshot) -> dict[str, Any]:
        bid_volume = snapshot.bid_volume(self.depth)
        ask_volume = snapshot.ask_volume(self.depth)
        total = bid_volume + ask_volume
        imbalance = bid_volume / total if total else None
        best_bid = snapshot.best_bid()
        best_ask = snapshot.best_ask()
        spread_abs = None
        spread_pct = None
        mid_price = None
        if best_bid is not None and best_ask is not None and best_ask >= best_bid:
            spread_abs = best_ask - best_bid
            mid_price = (best_bid + best_ask) / 2 if (best_bid + best_ask) else None
            if mid_price:
                spread_pct = (spread_abs / mid_price) * 100

        now = snapshot.updated_at or datetime.utcnow()
        seconds = 1.0
        if snapshot.previous_update_at:
            seconds = max((now - snapshot.previous_update_at).total_seconds(), 1e-6)
        previous_bid = snapshot.previous_bid_volume or 0.0
        previous_ask = snapshot.previous_ask_volume or 0.0
        bid_delta = bid_volume - previous_bid
        ask_delta = ask_volume - previous_ask
        book_velocity = (abs(bid_delta) + abs(ask_delta)) / seconds
        pressure = (bid_volume - ask_volume) / total if total else 0.0
        pressure_side = "BUY" if pressure > 0.05 else "SELL" if pressure < -0.05 else "NEUTRAL"
        absorption = 0.0
        if snapshot.last_price is not None and mid_price is not None and spread_abs is not None and spread_abs > 0:
            absorption = max(0.0, 1.0 - abs(snapshot.last_price - mid_price) / spread_abs)

        features = {
            "bid_volume_top_n": bid_volume,
            "ask_volume_top_n": ask_volume,
            "imbalance": imbalance,
            "spread_abs": spread_abs,
            "spread_pct": spread_pct,
            "mid_price": mid_price,
            "book_velocity": book_velocity,
            "pressure": pressure,
            "pressure_side": pressure_side,
            "bid_delta": bid_delta,
            "ask_delta": ask_delta,
            "absorption_score": absorption,
        }

        clean = {
            key: value
            for key, value in features.items()
            if value is None or not isinstance(value, float) or isfinite(value)
        }
        snapshot.features = clean
        snapshot.previous_bid_volume = bid_volume
        snapshot.previous_ask_volume = ask_volume
        snapshot.previous_update_at = now
        return clean
