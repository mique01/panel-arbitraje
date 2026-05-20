from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd

from app.marketdata.models import Bar


class BollingerEngine:
    def __init__(self, window: int = 20, std_multiplier: float = 2.0):
        self.window = window
        self.std_multiplier = std_multiplier

    def compute(self, bars: Iterable[Bar]) -> dict[str, float | bool | None]:
        frame = pd.DataFrame(
            [
                {
                    "bar_time": bar.bar_time,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in bars
            ]
        )
        if len(frame) < self.window:
            return {
                "upper_band": None,
                "lower_band": None,
                "middle_band": None,
                "band_width": None,
                "slope": None,
                "touch_lower": False,
                "touch_upper": False,
                "reentered": False,
                "vwap": None,
            }

        closes = frame["close"].astype(float)
        rolling_mean = closes.rolling(self.window).mean()
        rolling_std = closes.rolling(self.window).std(ddof=0)
        middle = rolling_mean.iloc[-1]
        std = rolling_std.iloc[-1]
        upper = middle + (std * self.std_multiplier)
        lower = middle - (std * self.std_multiplier)
        latest = frame.iloc[-1]
        prev = frame.iloc[-2]
        band_width = upper - lower
        slope = middle - rolling_mean.iloc[-2]

        cum_pv = (frame["close"] * frame["volume"]).replace({0: 0}).sum()
        cum_volume = frame["volume"].sum()
        vwap = cum_pv / cum_volume if cum_volume else latest["close"]
        touch_lower = latest["low"] <= lower if lower is not None else False
        touch_upper = latest["high"] >= upper if upper is not None else False
        reentered = prev["close"] < lower <= latest["close"] if lower is not None else False
        reentered = reentered or (prev["close"] > upper >= latest["close"] if upper is not None else False)

        return {
            "upper_band": float(upper),
            "lower_band": float(lower),
            "middle_band": float(middle),
            "band_width": float(band_width),
            "slope": float(slope),
            "touch_lower": bool(touch_lower),
            "touch_upper": bool(touch_upper),
            "reentered": bool(reentered),
            "vwap": float(vwap),
            "last_close": float(latest["close"]),
        }


class BarAccumulator:
    def __init__(self, max_bars: int = 59):
        self.max_bars = max_bars
        self._bars: dict[str, deque[Bar]] = {}
        self._open_bars: dict[str, Bar] = {}

    @staticmethod
    def _bucket(ts: datetime) -> datetime:
        minute = (ts.minute // 5) * 5
        return ts.replace(minute=minute, second=0, microsecond=0)

    def update(self, symbol: str, price: float, size: float | None, ts: datetime) -> Bar | None:
        bucket = self._bucket(ts)
        current = self._open_bars.get(symbol)
        if current is None:
            self._open_bars[symbol] = Bar(symbol, bucket, price, price, price, price, size or 0.0)
            return None
        if current.bar_time == bucket:
            current.high = max(current.high, price)
            current.low = min(current.low, price)
            current.close = price
            current.volume += size or 0.0
            return None
        closed = current
        bars = self._bars.setdefault(symbol, deque(maxlen=self.max_bars))
        bars.append(closed)
        self._open_bars[symbol] = Bar(symbol, bucket, price, price, price, price, size or 0.0)
        return closed

    def closed_history(self, symbol: str) -> list[Bar]:
        return list(self._bars.get(symbol, ()))

    def current_bar(self, symbol: str) -> Bar | None:
        return self._open_bars.get(symbol)

    def hydrate_closed_bars(self, symbol: str, bars: Iterable[Bar]) -> None:
        self._bars[symbol] = deque(bars, maxlen=self.max_bars)
