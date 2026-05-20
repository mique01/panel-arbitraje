from __future__ import annotations

from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import uuid4

from app.marketdata.models import InstrumentSnapshot, PassiveOrder, PositionState, SignalDecision, TapeEvent


class PaperTradingEngine:
    def __init__(self, settings: dict[str, object]):
        self.settings = settings
        self.pending_order: PassiveOrder | None = None
        self.position: PositionState | None = None
        self.cooldowns: dict[str, datetime] = {}
        self.recent_signals: deque[datetime] = deque(maxlen=64)
        self.realized_pnl_today: float = 0.0
        self.cash: float = float(settings["paper_starting_cash"])

    def can_open(self, symbol: str, now: datetime) -> bool:
        if (self.position and self.position.status == "OPEN") or self.pending_order:
            return False
        cooldown_until = self.cooldowns.get(symbol)
        if cooldown_until and cooldown_until > now:
            return False
        self._prune_signals(now)
        return len(self.recent_signals) < int(self.settings["max_signals_per_minute"])

    def submit_entry(self, signal: SignalDecision, option_snapshot: InstrumentSnapshot) -> PassiveOrder | None:
        now = signal.event_time
        if not self.can_open(option_snapshot.symbol, now):
            return None
        bid = option_snapshot.best_bid()
        if bid is None:
            return None
        order = PassiveOrder(
            order_id=uuid4().hex,
            symbol=option_snapshot.symbol,
            side="BUY",
            intent="ENTRY",
            status="PENDING_ENTRY",
            price=bid,
            quantity=1,
            placed_at=now,
            expires_at=now + timedelta(seconds=int(self.settings["entry_ttl_seconds"])),
            meta={
                "signal_id": signal.signal_id,
                "spread_at_entry": option_snapshot.features.get("spread_pct"),
                "imbalance_at_entry": option_snapshot.features.get("imbalance"),
            },
        )
        self.pending_order = order
        self.recent_signals.append(now)
        return order

    def on_tape(
        self,
        tape: TapeEvent,
        snapshot: InstrumentSnapshot,
        signal_lookup: dict[str, SignalDecision] | None = None,
    ) -> list[dict]:
        now = tape.event_time
        events: list[dict] = []
        if self.pending_order and self.pending_order.symbol == tape.symbol:
            if self.pending_order.intent == "ENTRY":
                if self._entry_filled(self.pending_order, tape):
                    position_id = uuid4().hex
                    signal_id = str(self.pending_order.meta.get("signal_id", ""))
                    self.position = PositionState(
                        position_id=position_id,
                        signal_id=signal_id,
                        symbol=tape.symbol,
                        direction="LONG_CALL" if signal_lookup and signal_lookup.get(signal_id, None) and signal_lookup[signal_id].signal_type == "LONG_CALL" else "LONG_PUT",
                        status="OPEN",
                        quantity=self.pending_order.quantity,
                        opened_at=now,
                        entry_price=self.pending_order.price,
                        metrics={
                            "spread_at_entry": snapshot.features.get("spread_pct"),
                            "imbalance_at_entry": snapshot.features.get("imbalance"),
                            "entry_latency_seconds": (now - self.pending_order.placed_at).total_seconds(),
                        },
                    )
                    self.pending_order.status = "FILLED"
                    self.pending_order.filled_at = now
                    events.append({"type": "order_filled", "order": asdict(self.pending_order)})
                    events.append({"type": "position_opened", "position": asdict(self.position)})
                    self.pending_order = None
                elif self.pending_order.expires_at and now >= self.pending_order.expires_at:
                    self.pending_order.status = "EXPIRED"
                    events.append({"type": "order_expired", "order": asdict(self.pending_order)})
                    self.pending_order = None
            elif self.pending_order.intent == "EXIT":
                if self._exit_filled(self.pending_order, tape):
                    self.pending_order.status = "FILLED"
                    self.pending_order.filled_at = now
                    events.append({"type": "order_filled", "order": asdict(self.pending_order)})
                    if self.position:
                        self._close_position(self.pending_order.price, now, "TARGET_EXIT", snapshot)
                        self.realized_pnl_today += self.position.pnl or 0.0
                        events.append({"type": "position_closed", "position": asdict(self.position)})
                        self.cooldowns[self.position.symbol] = now + timedelta(
                            seconds=int(self.settings["cooldown_seconds"])
                        )
                        self.position = None
                    self.pending_order = None

        if self.position and self.position.symbol == snapshot.symbol:
            events.extend(self._manage_open_position(snapshot, now))
        return events

    def _manage_open_position(self, snapshot: InstrumentSnapshot, now: datetime) -> list[dict]:
        events: list[dict] = []
        if not self.position or self.position.entry_price is None:
            return events
        bid = snapshot.best_bid()
        ask = snapshot.best_ask()
        if bid is not None:
            pnl_mark = bid - self.position.entry_price
            self.position.mae = min(self.position.mae, pnl_mark)
            self.position.mfe = max(self.position.mfe, pnl_mark)

        stop_price = self.position.entry_price * (1 - float(self.settings["stop_loss_pct"]))
        if bid is not None and bid <= stop_price:
            self._close_position(bid, now, "STOPPED", snapshot)
            events.append({"type": "position_closed", "position": asdict(self.position)})
            self.cooldowns[self.position.symbol] = now + timedelta(seconds=int(self.settings["cooldown_seconds"]))
            self.position = None
            return events

        if self.position.opened_at and now >= self.position.opened_at + timedelta(
            seconds=int(self.settings["position_timeout_seconds"])
        ):
            if self.pending_order is None and ask is not None:
                self.pending_order = PassiveOrder(
                    order_id=uuid4().hex,
                    symbol=snapshot.symbol,
                    side="SELL",
                    intent="EXIT",
                    status="PENDING_EXIT",
                    price=ask,
                    quantity=self.position.quantity,
                    placed_at=now,
                    expires_at=now + timedelta(seconds=int(self.settings["exit_requote_seconds"])),
                    meta={"reason": "TIMEOUT_EXIT"},
                )
                events.append({"type": "order_placed", "order": asdict(self.pending_order)})
            return events

        positive_edge = ask is not None and ask > self.position.entry_price
        fading_momentum = snapshot.features.get("pressure_side") != ("BUY" if self.position.direction == "LONG_CALL" else "SELL")
        spread_normalized = (snapshot.features.get("spread_pct") or 999) <= (
            float(self.settings["max_option_spread_pct"]) * 0.75
        )

        if self.pending_order and self.pending_order.intent == "EXIT":
            if self.pending_order.expires_at and now >= self.pending_order.expires_at and ask is not None:
                self.pending_order.price = ask
                self.pending_order.placed_at = now
                self.pending_order.expires_at = now + timedelta(
                    seconds=int(self.settings["exit_requote_seconds"])
                )
                self.pending_order.meta["requote"] = self.pending_order.meta.get("requote", 0) + 1
                events.append({"type": "order_requoted", "order": asdict(self.pending_order)})
            return events

        if self.pending_order is None and ask is not None and positive_edge and (fading_momentum or spread_normalized):
            self.pending_order = PassiveOrder(
                order_id=uuid4().hex,
                symbol=snapshot.symbol,
                side="SELL",
                intent="EXIT",
                status="PENDING_EXIT",
                price=ask,
                quantity=self.position.quantity,
                placed_at=now,
                expires_at=now + timedelta(seconds=int(self.settings["exit_requote_seconds"])),
                meta={"reason": "OFFER_MOMENTUM_FADE", "position_id": self.position.position_id},
            )
            events.append({"type": "order_placed", "order": asdict(self.pending_order)})
        return events

    def _close_position(
        self,
        exit_price: float,
        now: datetime,
        reason: str,
        snapshot: InstrumentSnapshot,
    ) -> None:
        if not self.position or self.position.entry_price is None:
            return
        self.position.status = "CLOSED" if reason != "STOPPED" else "STOPPED"
        self.position.closed_at = now
        self.position.exit_price = exit_price
        self.position.pnl = exit_price - self.position.entry_price
        self.position.exit_reason = reason
        self.position.metrics.update(
            {
                "spread_at_exit": snapshot.features.get("spread_pct"),
                "imbalance_at_exit": snapshot.features.get("imbalance"),
                "time_in_position_seconds": (
                    (now - self.position.opened_at).total_seconds() if self.position.opened_at else None
                ),
                "mae": self.position.mae,
                "mfe": self.position.mfe,
                "exit_reason": reason,
            }
        )

    @staticmethod
    def _entry_filled(order: PassiveOrder, tape: TapeEvent) -> bool:
        return tape.price <= order.price

    @staticmethod
    def _exit_filled(order: PassiveOrder, tape: TapeEvent) -> bool:
        return tape.price >= order.price

    def _prune_signals(self, now: datetime) -> None:
        limit = timedelta(minutes=1)
        while self.recent_signals and now - self.recent_signals[0] > limit:
            self.recent_signals.popleft()
