from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass(slots=True)
class BookLevel:
    price: float
    size: float


@dataclass(slots=True)
class TapeEvent:
    symbol: str
    market_id: str
    price: float
    size: float | None
    event_time: datetime
    bid: float | None = None
    ask: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InstrumentSnapshot:
    symbol: str
    market_id: str
    bids: list[BookLevel] = field(default_factory=list)
    offers: list[BookLevel] = field(default_factory=list)
    last_price: float | None = None
    last_size: float | None = None
    trade_volume: float | None = None
    last_trade_at: datetime | None = None
    updated_at: datetime | None = None
    previous_bid_volume: float | None = None
    previous_ask_volume: float | None = None
    previous_update_at: datetime | None = None
    features: dict[str, Any] = field(default_factory=dict)

    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    def best_ask(self) -> float | None:
        return self.offers[0].price if self.offers else None

    def bid_volume(self, depth: int | None = None) -> float:
        levels = self.bids if depth is None else self.bids[:depth]
        return sum(level.size for level in levels)

    def ask_volume(self, depth: int | None = None) -> float:
        levels = self.offers if depth is None else self.offers[:depth]
        return sum(level.size for level in levels)

    def is_stale(self, max_age_seconds: int = 15) -> bool:
        if self.updated_at is None:
            return True
        return datetime.utcnow() - self.updated_at > timedelta(seconds=max_age_seconds)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "market_id": self.market_id,
            "bids": [asdict(level) for level in self.bids],
            "offers": [asdict(level) for level in self.offers],
            "last_price": self.last_price,
            "last_size": self.last_size,
            "trade_volume": self.trade_volume,
            "last_trade_at": self.last_trade_at.isoformat() if self.last_trade_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "features": self.features,
        }


@dataclass(slots=True)
class Bar:
    symbol: str
    bar_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(slots=True)
class SignalDecision:
    signal_id: str
    signal_type: str
    underlying_symbol: str
    option_symbol: str
    score: float
    event_time: datetime
    reason: str
    features: dict[str, Any]


@dataclass(slots=True)
class PassiveOrder:
    order_id: str
    symbol: str
    side: str
    intent: str
    status: str
    price: float
    quantity: int
    placed_at: datetime
    expires_at: datetime | None = None
    filled_at: datetime | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PositionState:
    position_id: str
    signal_id: str
    symbol: str
    direction: str
    status: str
    quantity: int
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    pnl: float | None = None
    mae: float = 0.0
    mfe: float = 0.0
    exit_reason: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
