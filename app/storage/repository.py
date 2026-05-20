from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import delete, desc, select

from app.config import DEFAULT_STRATEGY_SETTINGS, DEFAULT_WATCHLIST
from app.marketdata.models import Bar, InstrumentSnapshot, PassiveOrder, PositionState, SignalDecision, TapeEvent
from app.storage.models import (
    AppLog,
    Bar5m,
    EngineHeartbeat,
    LatestMarketState,
    MarketTick,
    OrderBookSnapshot,
    PaperFill,
    PaperMetric,
    PaperOrder,
    PaperPosition,
    SignalEvent,
    StrategySetting,
    TradeTapeEvent,
    Watchlist,
    WatchlistInstrument,
)


class PersistenceService:
    def __init__(self, session_scope_factory: Callable[[], AbstractContextManager]):
        self.session_scope = session_scope_factory

    @staticmethod
    def _split_option_lists(watchlist: Watchlist) -> tuple[list[str], list[str]]:
        call_symbols: list[str] = []
        put_symbols: list[str] = []
        for raw_symbol in watchlist.monitored_symbols or []:
            if not raw_symbol:
                continue
            if raw_symbol.startswith("CALL:"):
                call_symbols.append(raw_symbol.split(":", 1)[1])
            elif raw_symbol.startswith("PUT:"):
                put_symbols.append(raw_symbol.split(":", 1)[1])
        if watchlist.active_call_symbol and watchlist.active_call_symbol not in call_symbols:
            call_symbols.insert(0, watchlist.active_call_symbol)
        if watchlist.active_put_symbol and watchlist.active_put_symbol not in put_symbols:
            put_symbols.insert(0, watchlist.active_put_symbol)
        return call_symbols, put_symbols

    @staticmethod
    def _serialize_option_lists(call_symbols: list[str], put_symbols: list[str]) -> list[str]:
        serialized: list[str] = []
        serialized.extend([f"CALL:{symbol}" for symbol in call_symbols if symbol])
        serialized.extend([f"PUT:{symbol}" for symbol in put_symbols if symbol])
        return serialized

    def ensure_defaults(self) -> None:
        with self.session_scope() as session:
            watchlist = session.scalar(select(Watchlist).where(Watchlist.is_active.is_(True)))
            if watchlist is None:
                watchlist = Watchlist(**DEFAULT_WATCHLIST, is_active=True)
                session.add(watchlist)
            if session.scalar(select(StrategySetting).where(StrategySetting.key == "default")) is None:
                session.add(StrategySetting(key="default", value_json=DEFAULT_STRATEGY_SETTINGS))

    def get_active_watchlist(self) -> dict[str, Any]:
        self.ensure_defaults()
        with self.session_scope() as session:
            watchlist = session.scalar(select(Watchlist).where(Watchlist.is_active.is_(True)))
            call_symbols, put_symbols = self._split_option_lists(watchlist)
            return {
                "name": watchlist.name,
                "underlying_symbol": watchlist.underlying_symbol,
                "active_call_symbol": watchlist.active_call_symbol,
                "active_put_symbol": watchlist.active_put_symbol,
                "call_symbols": call_symbols,
                "put_symbols": put_symbols,
                "monitored_symbols": [*call_symbols, *put_symbols],
                "enabled": watchlist.enabled,
            }

    def update_active_watchlist(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_defaults()
        with self.session_scope() as session:
            watchlist = session.scalar(select(Watchlist).where(Watchlist.is_active.is_(True)))
            current_calls, current_puts = self._split_option_lists(watchlist)
            call_symbols = [
                symbol.strip().upper()
                for symbol in payload.get("call_symbols", current_calls)
                if str(symbol).strip()
            ]
            put_symbols = [
                symbol.strip().upper()
                for symbol in payload.get("put_symbols", current_puts)
                if str(symbol).strip()
            ]
            for key in [
                "name",
                "underlying_symbol",
                "enabled",
            ]:
                if key in payload:
                    setattr(watchlist, key, payload[key])
            requested_active_call = str(payload.get("active_call_symbol", watchlist.active_call_symbol)).strip().upper()
            requested_active_put = str(payload.get("active_put_symbol", watchlist.active_put_symbol)).strip().upper()
            if requested_active_call and requested_active_call not in call_symbols:
                call_symbols.insert(0, requested_active_call)
            if requested_active_put and requested_active_put not in put_symbols:
                put_symbols.insert(0, requested_active_put)
            watchlist.active_call_symbol = requested_active_call or (call_symbols[0] if call_symbols else "")
            watchlist.active_put_symbol = requested_active_put or (put_symbols[0] if put_symbols else "")
            watchlist.monitored_symbols = self._serialize_option_lists(call_symbols, put_symbols)
            watchlist.updated_at = datetime.utcnow()
            session.execute(
                delete(WatchlistInstrument).where(WatchlistInstrument.watchlist_id == watchlist.id)
            )
            instruments = [
                (watchlist.underlying_symbol, "UNDERLYING"),
                (watchlist.active_call_symbol, "CALL"),
                (watchlist.active_put_symbol, "PUT"),
            ]
            for monitored in call_symbols:
                instruments.append((monitored, "CALL_MONITORED"))
            for monitored in put_symbols:
                instruments.append((monitored, "PUT_MONITORED"))
            for symbol, kind in instruments:
                if symbol:
                    session.add(
                        WatchlistInstrument(
                            watchlist_id=watchlist.id,
                            symbol=symbol,
                            kind=kind,
                            is_active=True,
                            metadata_json={},
                        )
                    )
            return {
                "name": watchlist.name,
                "underlying_symbol": watchlist.underlying_symbol,
                "active_call_symbol": watchlist.active_call_symbol,
                "active_put_symbol": watchlist.active_put_symbol,
                "call_symbols": call_symbols,
                "put_symbols": put_symbols,
                "monitored_symbols": [*call_symbols, *put_symbols],
                "enabled": watchlist.enabled,
            }

    def get_strategy_settings(self) -> dict[str, Any]:
        self.ensure_defaults()
        with self.session_scope() as session:
            row = session.scalar(select(StrategySetting).where(StrategySetting.key == "default"))
            return row.value_json if row else DEFAULT_STRATEGY_SETTINGS.copy()

    def update_strategy_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_defaults()
        with self.session_scope() as session:
            row = session.scalar(select(StrategySetting).where(StrategySetting.key == "default"))
            current = row.value_json if row else DEFAULT_STRATEGY_SETTINGS.copy()
            merged = {**current, **payload}
            if row is None:
                row = StrategySetting(key="default", value_json=merged)
                session.add(row)
            else:
                row.value_json = merged
            return merged

    def persist_market_snapshot(self, snapshot: InstrumentSnapshot, event_time: datetime) -> None:
        with self.session_scope() as session:
            latest = session.get(LatestMarketState, snapshot.symbol)
            if latest is None:
                latest = LatestMarketState(symbol=snapshot.symbol, market_id=snapshot.market_id)
                session.add(latest)
            latest.bids = [asdict(level) for level in snapshot.bids]
            latest.offers = [asdict(level) for level in snapshot.offers]
            latest.last_price = snapshot.last_price
            latest.last_size = snapshot.last_size
            latest.trade_volume = snapshot.trade_volume
            latest.spread_abs = snapshot.features.get("spread_abs")
            latest.spread_pct = snapshot.features.get("spread_pct")
            latest.imbalance = snapshot.features.get("imbalance")
            latest.mid_price = snapshot.features.get("mid_price")
            latest.pressure_side = snapshot.features.get("pressure_side")
            latest.book_velocity = snapshot.features.get("book_velocity")
            latest.last_trade_at = snapshot.last_trade_at
            latest.features_json = snapshot.features
            latest.updated_at = datetime.utcnow()

    def persist_tape_event(self, event: TapeEvent) -> None:
        with self.session_scope() as session:
            session.add(
                TradeTapeEvent(
                    symbol=event.symbol,
                    market_id=event.market_id,
                    event_time=event.event_time,
                    price=event.price,
                    size=event.size,
                    bid=event.bid,
                    ask=event.ask,
                    meta_json=event.meta,
                )
            )
            rows = session.scalars(
                select(TradeTapeEvent)
                .where(TradeTapeEvent.symbol == event.symbol)
                .order_by(desc(TradeTapeEvent.event_time))
            ).all()
            for row in rows[200:]:
                session.delete(row)

    def persist_bar(self, bar: Bar) -> None:
        with self.session_scope() as session:
            session.add(
                Bar5m(
                    symbol=bar.symbol,
                    bar_time=bar.bar_time,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
            )
            rows = session.scalars(
                select(Bar5m)
                .where(Bar5m.symbol == bar.symbol)
                .order_by(desc(Bar5m.bar_time))
            ).all()
            for row in rows[59:]:
                session.delete(row)

    def get_recent_bars(self, symbol: str, limit: int = 59) -> list[Bar]:
        with self.session_scope() as session:
            rows = session.scalars(
                select(Bar5m)
                .where(Bar5m.symbol == symbol)
                .order_by(desc(Bar5m.bar_time))
                .limit(limit)
            ).all()
            ordered = list(reversed(rows))
            return [
                Bar(
                    symbol=row.symbol,
                    bar_time=row.bar_time,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                )
                for row in ordered
            ]

    def persist_signal(self, signal: SignalDecision) -> None:
        with self.session_scope() as session:
            session.add(
                SignalEvent(
                    signal_id=signal.signal_id,
                    signal_type=signal.signal_type,
                    underlying_symbol=signal.underlying_symbol,
                    option_symbol=signal.option_symbol,
                    score=signal.score,
                    status="ACTIVE",
                    reason=signal.reason,
                    event_time=signal.event_time,
                    features_json=signal.features,
                )
            )

    def expire_old_signals(self, older_than_seconds: int = 180) -> None:
        threshold = datetime.utcnow() - timedelta(seconds=older_than_seconds)
        with self.session_scope() as session:
            rows = session.scalars(
                select(SignalEvent).where(
                    SignalEvent.status == "ACTIVE",
                    SignalEvent.event_time < threshold,
                )
            ).all()
            for row in rows:
                row.status = "EXPIRED"

    def persist_paper_order(self, order: PassiveOrder) -> None:
        with self.session_scope() as session:
            row = session.scalar(select(PaperOrder).where(PaperOrder.order_id == order.order_id))
            if row is None:
                row = PaperOrder(order_id=order.order_id)
                session.add(row)
            row.position_id = str(order.meta.get("position_id") or "")
            row.symbol = order.symbol
            row.side = order.side
            row.intent = order.intent
            row.status = order.status
            row.price = order.price
            row.quantity = order.quantity
            row.placed_at = order.placed_at
            row.expires_at = order.expires_at
            row.filled_at = order.filled_at
            row.meta_json = order.meta
            if order.status == "FILLED" and order.filled_at:
                session.add(
                    PaperFill(
                        order_id=order.order_id,
                        symbol=order.symbol,
                        price=order.price,
                        quantity=order.quantity,
                        fill_time=order.filled_at,
                        meta_json=order.meta,
                    )
                )

    def persist_position(self, position: PositionState) -> None:
        with self.session_scope() as session:
            row = session.scalar(select(PaperPosition).where(PaperPosition.position_id == position.position_id))
            if row is None:
                row = PaperPosition(position_id=position.position_id, signal_id=position.signal_id)
                session.add(row)
            row.signal_id = position.signal_id
            row.symbol = position.symbol
            row.direction = position.direction
            row.status = position.status
            row.entry_price = position.entry_price
            row.exit_price = position.exit_price
            row.quantity = position.quantity
            row.opened_at = position.opened_at
            row.closed_at = position.closed_at
            row.pnl = position.pnl
            row.mae = position.mae
            row.mfe = position.mfe
            row.exit_reason = position.exit_reason
            row.metrics_json = position.metrics
            for metric_name, metric_value in position.metrics.items():
                if isinstance(metric_value, (int, float)):
                    session.add(
                        PaperMetric(
                            position_id=position.position_id,
                            metric_name=metric_name,
                            metric_value=float(metric_value),
                            meta_json={},
                        )
                    )

    def heartbeat(self, service_name: str, status: str, detail: str = "", payload: dict | None = None) -> None:
        with self.session_scope() as session:
            session.add(
                EngineHeartbeat(
                    service_name=service_name,
                    status=status,
                    detail=detail,
                    payload=payload or {},
                )
            )

    def log(self, level: str, logger_name: str, message: str, payload: dict | None = None) -> None:
        with self.session_scope() as session:
            session.add(
                AppLog(
                    level=level,
                    logger_name=logger_name,
                    message=message,
                    payload=payload or {},
                )
            )

    def get_latest_market_state(self) -> list[dict[str, Any]]:
        with self.session_scope() as session:
            rows = session.scalars(
                select(LatestMarketState).order_by(LatestMarketState.symbol.asc())
            ).all()
            return [
                {
                    "symbol": row.symbol,
                    "market_id": row.market_id,
                    "last_price": row.last_price,
                    "last_size": row.last_size,
                    "trade_volume": row.trade_volume,
                    "spread_abs": row.spread_abs,
                    "spread_pct": row.spread_pct,
                    "imbalance": row.imbalance,
                    "mid_price": row.mid_price,
                    "pressure_side": row.pressure_side,
                    "book_velocity": row.book_velocity,
                    "bids": row.bids,
                    "offers": row.offers,
                    "features": row.features_json,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
                for row in rows
            ]

    def get_current_tape(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.session_scope() as session:
            rows = session.scalars(
                select(TradeTapeEvent).order_by(desc(TradeTapeEvent.event_time)).limit(limit)
            ).all()
            return [
                {
                    "symbol": row.symbol,
                    "event_time": row.event_time.isoformat(),
                    "price": row.price,
                    "size": row.size,
                    "bid": row.bid,
                    "ask": row.ask,
                    "meta": row.meta_json,
                }
                for row in rows
            ]

    def get_active_signals(self) -> list[dict[str, Any]]:
        self.expire_old_signals()
        with self.session_scope() as session:
            rows = session.scalars(
                select(SignalEvent)
                .where(SignalEvent.status == "ACTIVE")
                .order_by(desc(SignalEvent.event_time))
                .limit(20)
            ).all()
            return [self._signal_row(row) for row in rows]

    def get_signal_history(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.session_scope() as session:
            rows = session.scalars(
                select(SignalEvent).order_by(desc(SignalEvent.event_time)).limit(limit)
            ).all()
            return [self._signal_row(row) for row in rows]

    def get_paper_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.session_scope() as session:
            rows = session.scalars(
                select(PaperOrder).order_by(desc(PaperOrder.updated_at)).limit(limit)
            ).all()
            return [
                {
                    "order_id": row.order_id,
                    "position_id": row.position_id,
                    "symbol": row.symbol,
                    "side": row.side,
                    "intent": row.intent,
                    "status": row.status,
                    "price": row.price,
                    "quantity": row.quantity,
                    "placed_at": row.placed_at.isoformat() if row.placed_at else None,
                    "filled_at": row.filled_at.isoformat() if row.filled_at else None,
                    "meta": row.meta_json,
                }
                for row in rows
            ]

    def get_paper_positions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.session_scope() as session:
            rows = session.scalars(
                select(PaperPosition).order_by(desc(PaperPosition.updated_at)).limit(limit)
            ).all()
            return [
                {
                    "position_id": row.position_id,
                    "signal_id": row.signal_id,
                    "symbol": row.symbol,
                    "direction": row.direction,
                    "status": row.status,
                    "entry_price": row.entry_price,
                    "exit_price": row.exit_price,
                    "quantity": row.quantity,
                    "opened_at": row.opened_at.isoformat() if row.opened_at else None,
                    "closed_at": row.closed_at.isoformat() if row.closed_at else None,
                    "pnl": row.pnl,
                    "mae": row.mae,
                    "mfe": row.mfe,
                    "exit_reason": row.exit_reason,
                    "metrics": row.metrics_json,
                }
                for row in rows
            ]

    def get_paper_stats(self) -> dict[str, Any]:
        with self.session_scope() as session:
            positions = session.scalars(select(PaperPosition)).all()
            closed = [row for row in positions if row.status in {"CLOSED", "STOPPED"} and row.pnl is not None]
            wins = sum(1 for row in closed if (row.pnl or 0.0) > 0)
            total_pnl = sum((row.pnl or 0.0) for row in closed)
            avg_hold = [
                row.metrics_json.get("time_in_position_seconds")
                for row in closed
                if row.metrics_json.get("time_in_position_seconds") is not None
            ]
            return {
                "open_positions": sum(1 for row in positions if row.status == "OPEN"),
                "closed_positions": len(closed),
                "winrate": (wins / len(closed) * 100) if closed else 0.0,
                "total_pnl": total_pnl,
                "avg_hold_seconds": (sum(avg_hold) / len(avg_hold)) if avg_hold else 0.0,
            }

    def get_system_health(self) -> dict[str, Any]:
        with self.session_scope() as session:
            heartbeat = session.scalar(
                select(EngineHeartbeat).order_by(desc(EngineHeartbeat.created_at)).limit(1)
            )
            return {
                "status": heartbeat.status if heartbeat else "UNKNOWN",
                "detail": heartbeat.detail if heartbeat else "No heartbeat yet",
                "created_at": heartbeat.created_at.isoformat() if heartbeat else None,
            }

    @staticmethod
    def _signal_row(row: SignalEvent) -> dict[str, Any]:
        return {
            "signal_id": row.signal_id,
            "signal_type": row.signal_type,
            "underlying_symbol": row.underlying_symbol,
            "option_symbol": row.option_symbol,
            "score": row.score,
            "status": row.status,
            "reason": row.reason,
            "event_time": row.event_time.isoformat(),
            "features": row.features_json,
        }
