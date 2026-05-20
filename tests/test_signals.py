from datetime import datetime, timedelta
from unittest import TestCase

from app.marketdata.analyzer import OrderBookAnalyzer
from app.marketdata.models import Bar, BookLevel, InstrumentSnapshot
from app.signals.bollinger import BollingerEngine


class SignalMathTests(TestCase):
    def test_orderbook_analyzer_computes_spread_and_imbalance(self):
        snapshot = InstrumentSnapshot(symbol="GGAL", market_id="ROFX")
        snapshot.bids = [BookLevel(price=100.0, size=50), BookLevel(price=99.5, size=25)]
        snapshot.offers = [BookLevel(price=100.5, size=40), BookLevel(price=101.0, size=20)]
        snapshot.last_price = 100.25
        snapshot.updated_at = datetime.utcnow()
        features = OrderBookAnalyzer(depth=2).analyze(snapshot)
        self.assertAlmostEqual(features["spread_abs"], 0.5)
        self.assertAlmostEqual(features["mid_price"], 100.25)
        self.assertGreater(features["imbalance"], 0.5)

    def test_bollinger_engine_returns_bands(self):
        base = datetime(2026, 1, 1, 10, 0)
        bars = [
            Bar("GGAL", base + timedelta(minutes=5 * i), 100 + i, 101 + i, 99 + i, 100 + i, 10)
            for i in range(25)
        ]
        result = BollingerEngine(window=20, std_multiplier=2.0).compute(bars)
        self.assertIsNotNone(result["upper_band"])
        self.assertTrue("vwap" in result)
