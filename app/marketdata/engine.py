from __future__ import annotations

from datetime import datetime
from queue import Empty, Queue
from typing import Any

from app.config import Settings
from app.marketdata.analyzer import OrderBookAnalyzer
from app.marketdata.auth import PrimaryAuthClient
from app.marketdata.models import BookLevel, InstrumentSnapshot, SignalDecision
from app.marketdata.rest import PrimaryRestClient
from app.marketdata.tape import TradeTapeBuilder
from app.marketdata.websocket_client import PrimaryWebSocketClient
from app.papertrading.engine import PaperTradingEngine
from app.signals.bollinger import BarAccumulator
from app.signals.engine import SignalEngine
from app.storage.repository import PersistenceService
from app.utils.logging import get_logger


class MarketDataEngine:
    def __init__(self, settings: Settings, repository: PersistenceService):
        self.settings = settings
        self.repository = repository
        self.logger = get_logger("marketdata.engine")
        self.queue: Queue = Queue()
        self.auth_client = PrimaryAuthClient(settings)
        self.rest_client = PrimaryRestClient(settings, self.auth_client)
        self.ws_client = PrimaryWebSocketClient(settings, self.auth_client, self.queue)
        self.analyzer = OrderBookAnalyzer(depth=settings.primary_book_depth)
        self.tape_builder = TradeTapeBuilder()
        self.bar_accumulator = BarAccumulator(
            max_bars=int(repository.get_strategy_settings().get("underlying_bar_history_limit", 59))
        )
        strategy_settings = repository.get_strategy_settings()
        self.signal_engine = SignalEngine(strategy_settings)
        self.paper_engine = PaperTradingEngine(strategy_settings)
        self.snapshots: dict[str, InstrumentSnapshot] = {}
        self.signals: dict[str, SignalDecision] = {}

    def bootstrap_watchlist(self) -> dict[str, Any]:
        watchlist = self.repository.get_active_watchlist()
        products = []
        symbols = [watchlist["underlying_symbol"], watchlist["active_call_symbol"], watchlist["active_put_symbol"]]
        symbols.extend(watchlist["monitored_symbols"])
        deduped = [symbol for symbol in dict.fromkeys([symbol for symbol in symbols if symbol])]
        for symbol in deduped:
            snapshot = self.snapshots.setdefault(
                symbol,
                InstrumentSnapshot(symbol=symbol, market_id=self.settings.primary_market_id),
            )
            products.append({"symbol": symbol, "marketId": snapshot.market_id})
            try:
                md = self.rest_client.get_market_data(
                    symbol=symbol,
                    entries=self.settings.primary_md_entries,
                    depth=self.settings.primary_book_depth,
                )
                if md.get("status") == "OK":
                    self._apply_market_data(symbol, md.get("marketData", {}), datetime.utcnow())
            except Exception as exc:
                self.logger.warning("Bootstrap market data failed for %s: %s", symbol, exc)
        self.ws_client.add_market_data_subscription(
            products=products,
            entries=self.settings.primary_md_entries,
            depth=self.settings.primary_book_depth,
        )
        return watchlist

    def start(self) -> None:
        self.bootstrap_watchlist()
        self.ws_client.start()

    def stop(self) -> None:
        self.ws_client.stop()

    def process_next(self, timeout: float = 1.0) -> None:
        try:
            payload = self.queue.get(timeout=timeout)
        except Empty:
            return
        self._process_payload(payload)

    def _process_payload(self, payload: dict[str, Any]) -> None:
        msg_type = str(payload.get("type", "")).lower()
        if msg_type == "md":
            instrument = payload.get("instrumentId", {})
            symbol = instrument.get("symbol")
            market_data = payload.get("marketData", {})
            if symbol:
                event_time = datetime.utcnow()
                self._apply_market_data(symbol, market_data, event_time)
        elif msg_type == "ws_status":
            self.repository.heartbeat("worker", payload.get("status", "UNKNOWN"), payload.get("detail", ""))
        elif msg_type == "ws_error":
            self.repository.heartbeat("worker", "ERROR", payload.get("error", ""))

    def _apply_market_data(self, symbol: str, market_data: dict[str, Any], event_time: datetime) -> None:
        snapshot = self.snapshots.setdefault(
            symbol, InstrumentSnapshot(symbol=symbol, market_id=self.settings.primary_market_id)
        )
        snapshot.updated_at = event_time
        if "BI" in market_data:
            snapshot.bids = [
                BookLevel(price=float(level["price"]), size=float(level["size"]))
                for level in market_data["BI"][: self.settings.primary_book_depth]
            ]
        if "OF" in market_data:
            snapshot.offers = [
                BookLevel(price=float(level["price"]), size=float(level["size"]))
                for level in market_data["OF"][: self.settings.primary_book_depth]
            ]
        if "LA" in market_data and market_data["LA"]:
            last = market_data["LA"]
            snapshot.last_price = float(last["price"])
            size = last.get("size")
            snapshot.last_size = float(size) if size is not None else None
            snapshot.last_trade_at = event_time
            closed = self.bar_accumulator.update(
                symbol=symbol,
                price=snapshot.last_price,
                size=snapshot.last_size,
                ts=event_time,
            )
            if closed is not None:
                self.repository.persist_bar(closed)
        if "TV" in market_data:
            tv = market_data["TV"]
            snapshot.trade_volume = float(tv.get("size") if isinstance(tv, dict) else tv or 0.0)

        self.analyzer.analyze(snapshot)
        self.repository.persist_market_snapshot(snapshot, event_time)
        tape = self.tape_builder.build(snapshot)
        if tape:
            self.repository.persist_tape_event(tape)
        self._evaluate_signals_and_paper(snapshot, tape)

    def _evaluate_signals_and_paper(
        self,
        changed_snapshot: InstrumentSnapshot,
        tape,
    ) -> None:
        watchlist = self.repository.get_active_watchlist()
        underlying_symbol = watchlist["underlying_symbol"]
        if not underlying_symbol:
            return
        underlying = self.snapshots.get(underlying_symbol)
        if underlying is None:
            return

        closed_bars = self.bar_accumulator.closed_history(underlying_symbol)
        current_bar = self.bar_accumulator.current_bar(underlying_symbol)
        for option_symbol, option_side in [
            (watchlist["active_call_symbol"], "CALL"),
            (watchlist["active_put_symbol"], "PUT"),
        ]:
            if not option_symbol:
                continue
            option = self.snapshots.get(option_symbol)
            if option is None:
                continue
            signal = self.signal_engine.evaluate(underlying, option, closed_bars, current_bar, option_side)
            if signal and signal.signal_id not in self.signals:
                self.signals[signal.signal_id] = signal
                self.repository.persist_signal(signal)
                order = self.paper_engine.submit_entry(signal, option)
                if order:
                    self.repository.persist_paper_order(order)

        if tape and changed_snapshot.symbol == tape.symbol:
            events = self.paper_engine.on_tape(tape, changed_snapshot, self.signals)
            for event in events:
                if event["type"] in {"order_filled", "order_expired", "order_placed", "order_requoted"}:
                    from app.marketdata.models import PassiveOrder

                    self.repository.persist_paper_order(PassiveOrder(**event["order"]))
                elif event["type"] in {"position_opened", "position_closed"}:
                    from app.marketdata.models import PositionState

                    self.repository.persist_position(PositionState(**event["position"]))
