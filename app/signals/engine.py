from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.marketdata.models import InstrumentSnapshot, SignalDecision
from app.signals.anti_trend import AntiTrendFilter
from app.signals.bollinger import BollingerEngine


class SignalEngine:
    def __init__(self, settings: dict[str, object]):
        self.settings = settings
        self.bollinger = BollingerEngine(
            window=int(settings["bollinger_window"]),
            std_multiplier=float(settings["bollinger_std"]),
        )
        self.anti_trend = AntiTrendFilter(
            adx_threshold=float(settings["anti_trend_adx_threshold"]),
            ema_slope_threshold=float(settings["anti_trend_ema_slope_threshold"]),
            band_stick_bars=int(settings["anti_trend_band_stick_bars"]),
        )

    def evaluate(
        self,
        underlying: InstrumentSnapshot,
        option: InstrumentSnapshot,
        bars,
        option_side: str,
    ) -> SignalDecision | None:
        if not option.symbol:
            return None
        bollinger = self.bollinger.compute(bars)
        anti_trend = self.anti_trend.evaluate(list(bars), bollinger)
        if anti_trend["blocked"]:
            return None

        option_features = option.features
        underlying_features = underlying.features
        if not option_features or not underlying_features:
            return None

        spread_pct = option_features.get("spread_pct")
        if spread_pct is None or spread_pct > float(self.settings["max_option_spread_pct"]):
            return None

        if (option.best_bid() or 0) <= 0 or option.bid_volume() < float(self.settings["min_option_bid_size"]):
            return None
        if (option.trade_volume or 0.0) < float(self.settings["min_option_volume"]):
            return None

        last_close = bollinger.get("last_close")
        upper_band = bollinger.get("upper_band")
        lower_band = bollinger.get("lower_band")
        if last_close is None:
            return None

        is_call = option_side == "CALL"
        touch_ok = bool(bollinger.get("touch_lower")) if is_call else bool(bollinger.get("touch_upper"))
        if not touch_ok:
            tolerance = float(self.settings["bollinger_touch_tolerance_pct"])
            if is_call and lower_band:
                touch_ok = last_close <= lower_band * (1 + tolerance)
            elif not is_call and upper_band:
                touch_ok = last_close >= upper_band * (1 - tolerance)
        if not touch_ok:
            return None

        imbalance = underlying_features.get("imbalance")
        if imbalance is None:
            return None
        if is_call and imbalance < float(self.settings["min_call_imbalance"]):
            return None
        if not is_call and imbalance > float(self.settings["max_put_imbalance"]):
            return None

        pressure_side = underlying_features.get("pressure_side")
        if is_call and pressure_side != "BUY":
            return None
        if not is_call and pressure_side != "SELL":
            return None

        absorption = float(underlying_features.get("absorption_score") or 0.0)
        if absorption <= 0.1:
            return None

        score = self._score(bollinger, underlying_features, option_features, option, is_call)
        if score < float(self.settings["signal_score_threshold"]):
            return None

        reason = "Lower band reversion with strong bid pressure" if is_call else "Upper band reversion with strong offer pressure"
        return SignalDecision(
            signal_id=uuid4().hex,
            signal_type="LONG_CALL" if is_call else "LONG_PUT",
            underlying_symbol=underlying.symbol,
            option_symbol=option.symbol,
            score=score,
            event_time=datetime.utcnow(),
            reason=reason,
            features={
                "bollinger": bollinger,
                "underlying": underlying_features,
                "option": option_features,
                "anti_trend": anti_trend,
            },
        )

    def _score(self, bollinger, underlying_features, option_features, option: InstrumentSnapshot, is_call: bool) -> float:
        weights = self.settings["signal_weights"]
        spread_pct = float(option_features.get("spread_pct") or 0.0)
        spread_quality = max(
            0.0,
            1.0 - (spread_pct / float(self.settings["max_option_spread_pct"])),
        )
        book_velocity = min(float(underlying_features.get("book_velocity") or 0.0) / 500.0, 1.0)
        pressure = float(underlying_features.get("pressure") or 0.0)
        pressure_score = pressure if is_call else -pressure
        pressure_score = max(0.0, min(1.0, (pressure_score + 1.0) / 2.0))
        liquidity = min(option.bid_volume() / 50.0, 1.0)
        liquidity = max(liquidity, min(float(option_features.get("bid_volume_top_n") or 0.0) / 50.0, 1.0))
        reversion_speed = min(float(underlying_features.get("absorption_score") or 0.0), 1.0)
        bollinger_context = 1.0 if ((bollinger.get("touch_lower") if is_call else bollinger.get("touch_upper"))) else 0.6

        total = (
            spread_quality * float(weights["spread_quality"])
            + book_velocity * float(weights["book_velocity"])
            + pressure_score * float(weights["pressure"])
            + liquidity * float(weights["liquidity"])
            + reversion_speed * float(weights["reversion_speed"])
            + bollinger_context * float(weights["bollinger_context"])
        )
        return round(total, 2)
