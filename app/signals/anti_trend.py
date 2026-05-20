from __future__ import annotations

import pandas as pd

from app.marketdata.models import Bar


class AntiTrendFilter:
    def __init__(
        self,
        adx_threshold: float = 25.0,
        ema_slope_threshold: float = 0.0015,
        band_stick_bars: int = 3,
    ):
        self.adx_threshold = adx_threshold
        self.ema_slope_threshold = ema_slope_threshold
        self.band_stick_bars = band_stick_bars

    def evaluate(self, bars: list[Bar], bollinger: dict[str, float | bool | None]) -> dict[str, object]:
        if len(bars) < 6:
            return {"blocked": False, "reason": "insufficient_bars", "adx": None}

        frame = pd.DataFrame(
            [{"high": b.high, "low": b.low, "close": b.close} for b in bars]
        ).astype(float)
        high = frame["high"]
        low = frame["low"]
        close = frame["close"]
        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        tr_components = pd.concat(
            [(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()],
            axis=1,
        )
        tr = tr_components.max(axis=1)
        atr = tr.rolling(14).mean()
        plus_di = 100 * (plus_dm.rolling(14).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(14).mean() / atr)
        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)) * 100
        adx = float(dx.rolling(14).mean().iloc[-1]) if len(frame) >= 14 else None

        ema = close.ewm(span=20, adjust=False).mean()
        ema_slope = ((ema.iloc[-1] - ema.iloc[-2]) / ema.iloc[-2]) if ema.iloc[-2] else 0.0
        middle = bollinger.get("middle_band")
        vwap = bollinger.get("vwap")
        band_width = bollinger.get("band_width") or 0.0
        latest = close.iloc[-1]
        stick_bars = close.tail(self.band_stick_bars)
        stick_high = bool((stick_bars > (middle or latest)).all())
        stick_low = bool((stick_bars < (middle or latest)).all())
        vwap_distance = abs((latest - vwap) / vwap) if vwap else 0.0

        blocked = False
        reason = "ok"
        if adx is not None and adx >= self.adx_threshold:
            blocked = True
            reason = "adx_trend"
        elif abs(ema_slope) >= self.ema_slope_threshold and vwap_distance >= 0.002:
            blocked = True
            reason = "ema_vwap_trend"
        elif band_width and (stick_high or stick_low):
            blocked = True
            reason = "band_stickiness"

        return {
            "blocked": blocked,
            "reason": reason,
            "adx": adx,
            "ema_slope": float(ema_slope),
            "vwap_distance": float(vwap_distance),
        }
