from __future__ import annotations

from datetime import datetime

from app.marketdata.models import InstrumentSnapshot, TapeEvent


class TradeTapeBuilder:
    def build(self, snapshot: InstrumentSnapshot) -> TapeEvent | None:
        if snapshot.last_price is None or snapshot.last_trade_at is None:
            return None
        return TapeEvent(
            symbol=snapshot.symbol,
            market_id=snapshot.market_id,
            price=snapshot.last_price,
            size=snapshot.last_size,
            event_time=snapshot.last_trade_at,
            bid=snapshot.best_bid(),
            ask=snapshot.best_ask(),
            meta={"source": "LA", "captured_at": datetime.utcnow().isoformat()},
        )
