from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any


DEFAULT_STRATEGY_SETTINGS: dict[str, Any] = {
    "bollinger_window": 20,
    "bollinger_std": 2.0,
    "underlying_bar_history_limit": 59,
    "bollinger_touch_tolerance_pct": 0.0025,
    "book_depth": 5,
    "signal_score_threshold": 70.0,
    "min_call_imbalance": 0.62,
    "max_put_imbalance": 0.38,
    "max_option_spread_pct": 1.50,
    "min_option_bid_size": 1.0,
    "min_option_volume": 1.0,
    "entry_ttl_seconds": 20,
    "exit_requote_seconds": 10,
    "position_timeout_seconds": 120,
    "cooldown_seconds": 180,
    "max_signals_per_minute": 4,
    "daily_paper_loss_limit_pct": 3.0,
    "paper_starting_cash": 1_000_000.0,
    "stop_loss_pct": 0.10,
    "tape_trade_through_ticks": 0.0,
    "anti_trend_adx_threshold": 25.0,
    "anti_trend_ema_slope_threshold": 0.0015,
    "anti_trend_band_stick_bars": 3,
    "signal_weights": {
        "spread_quality": 25.0,
        "book_velocity": 20.0,
        "pressure": 20.0,
        "liquidity": 15.0,
        "reversion_speed": 10.0,
        "bollinger_context": 10.0,
    },
}


DEFAULT_WATCHLIST: dict[str, Any] = {
    "name": "GGAL scalping",
    "underlying_symbol": "GGAL",
    "active_call_symbol": "",
    "active_put_symbol": "",
    "monitored_symbols": [],
    "enabled": True,
}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_json(name: str, default: dict[str, Any]) -> dict[str, Any]:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return default
    return parsed if isinstance(parsed, dict) else default


@dataclass(slots=True)
class Settings:
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./panel_arbitraje.db")
    )
    primary_rest_url: str = field(
        default_factory=lambda: os.getenv(
            "PRIMARY_REST_URL", "https://api.remarkets.primary.com.ar"
        )
    )
    primary_ws_url: str = field(default_factory=lambda: os.getenv("PRIMARY_WS_URL", ""))
    primary_username: str = field(default_factory=lambda: os.getenv("PRIMARY_USERNAME", ""))
    primary_password: str = field(default_factory=lambda: os.getenv("PRIMARY_PASSWORD", ""))
    primary_auth_token: str = field(default_factory=lambda: os.getenv("PRIMARY_AUTH_TOKEN", ""))
    primary_ws_auth_mode: str = field(
        default_factory=lambda: os.getenv("PRIMARY_WS_AUTH_MODE", "none")
    )
    primary_ws_use_header_auth: bool = field(
        default_factory=lambda: _env_bool("PRIMARY_WS_USE_HEADER_AUTH", False)
    )
    primary_ws_token_query_param: str = field(
        default_factory=lambda: os.getenv("PRIMARY_WS_TOKEN_QUERY_PARAM", "token")
    )
    primary_ws_subprotocol: str = field(
        default_factory=lambda: os.getenv("PRIMARY_WS_SUBPROTOCOL", "")
    )
    primary_ws_auth_message_template: dict[str, Any] = field(
        default_factory=lambda: _env_json("PRIMARY_WS_AUTH_MESSAGE_TEMPLATE", {})
    )
    primary_market_id: str = field(default_factory=lambda: os.getenv("PRIMARY_MARKET_ID", "ROFX"))
    primary_md_entries: list[str] = field(
        default_factory=lambda: [
            item.strip().upper()
            for item in os.getenv("PRIMARY_MD_ENTRIES", "BI,OF,LA,TV").split(",")
            if item.strip()
        ]
    )
    primary_book_depth: int = field(
        default_factory=lambda: int(os.getenv("PRIMARY_BOOK_DEPTH", "5"))
    )
    worker_poll_interval: float = field(
        default_factory=lambda: float(os.getenv("WORKER_POLL_INTERVAL", "1.0"))
    )
    worker_heartbeat_seconds: int = field(
        default_factory=lambda: int(os.getenv("WORKER_HEARTBEAT_SECONDS", "15"))
    )
    panel_refresh_ms: int = field(
        default_factory=lambda: int(os.getenv("PANEL_REFRESH_MS", "3000"))
    )
    signal_defaults: dict[str, Any] = field(
        default_factory=lambda: DEFAULT_STRATEGY_SETTINGS.copy()
    )
    watchlist_defaults: dict[str, Any] = field(
        default_factory=lambda: DEFAULT_WATCHLIST.copy()
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
