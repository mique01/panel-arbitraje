from datetime import datetime, timedelta
from unittest import TestCase

from app.config import DEFAULT_STRATEGY_SETTINGS
from app.marketdata.models import BookLevel, InstrumentSnapshot, SignalDecision, TapeEvent
from app.papertrading.engine import PaperTradingEngine


class PaperTradingEngineTests(TestCase):
    def setUp(self):
        self.engine = PaperTradingEngine(DEFAULT_STRATEGY_SETTINGS.copy())
        self.snapshot = InstrumentSnapshot(symbol="GFGC8700JU", market_id="ROFX")
        self.snapshot.bids = [BookLevel(price=100.0, size=10)]
        self.snapshot.offers = [BookLevel(price=102.0, size=10)]
        self.snapshot.features = {"spread_pct": 1.0, "imbalance": 0.7, "pressure_side": "BUY"}

    def test_entry_fills_when_tape_trades_through_bid(self):
        signal = SignalDecision(
            signal_id="sig-1",
            signal_type="LONG_CALL",
            underlying_symbol="GGAL",
            option_symbol="GFGC8700JU",
            score=80.0,
            event_time=datetime.utcnow(),
            reason="test",
            features={},
        )
        order = self.engine.submit_entry(signal, self.snapshot)
        self.assertIsNotNone(order)
        tape = TapeEvent(
            symbol="GFGC8700JU",
            market_id="ROFX",
            price=100.0,
            size=1,
            event_time=datetime.utcnow() + timedelta(seconds=1),
        )
        events = self.engine.on_tape(tape, self.snapshot, {"sig-1": signal})
        self.assertTrue(any(event["type"] == "position_opened" for event in events))

    def test_stop_uses_bid_reference(self):
        position_signal = SignalDecision(
            signal_id="sig-2",
            signal_type="LONG_CALL",
            underlying_symbol="GGAL",
            option_symbol="GFGC8700JU",
            score=80.0,
            event_time=datetime.utcnow(),
            reason="test",
            features={},
        )
        self.engine.submit_entry(position_signal, self.snapshot)
        fill_tape = TapeEvent(
            symbol="GFGC8700JU",
            market_id="ROFX",
            price=100.0,
            size=1,
            event_time=datetime.utcnow(),
        )
        self.engine.on_tape(fill_tape, self.snapshot, {"sig-2": position_signal})
        self.snapshot.bids = [BookLevel(price=89.0, size=10)]
        stop_tape = TapeEvent(
            symbol="GFGC8700JU",
            market_id="ROFX",
            price=89.0,
            size=1,
            event_time=datetime.utcnow() + timedelta(seconds=5),
        )
        events = self.engine.on_tape(stop_tape, self.snapshot, {"sig-2": position_signal})
        self.assertTrue(any(event["type"] == "position_closed" for event in events))
