from __future__ import annotations

import pandas as pd
import panel as pn

from app.runtime import get_runtime


pn.extension("tabulator")


def build_dashboard():
    runtime = get_runtime()
    repository = runtime["repository"]
    settings = repository.get_strategy_settings()
    watchlist = repository.get_active_watchlist()

    title = pn.pane.Markdown("## Plataforma GGAL Micro-Scalping")
    system_status = pn.pane.Markdown("Estado cargando...")
    save_watchlist = pn.widgets.Button(name="Guardar watchlist", button_type="primary")
    save_strategy = pn.widgets.Button(name="Guardar estrategia", button_type="success")

    underlying_symbol = pn.widgets.TextInput(name="Underlying", value=watchlist["underlying_symbol"])
    calls_text = pn.widgets.TextAreaInput(
        name="Tickers CALL",
        value="\n".join(watchlist.get("call_symbols", [])),
        height=120,
    )
    puts_text = pn.widgets.TextAreaInput(
        name="Tickers PUT",
        value="\n".join(watchlist.get("put_symbols", [])),
        height=120,
    )
    active_call_symbol = pn.widgets.Select(
        name="Call activa",
        options=watchlist.get("call_symbols", []) or [watchlist["active_call_symbol"] or ""],
        value=watchlist["active_call_symbol"] or "",
    )
    active_put_symbol = pn.widgets.Select(
        name="Put activa",
        options=watchlist.get("put_symbols", []) or [watchlist["active_put_symbol"] or ""],
        value=watchlist["active_put_symbol"] or "",
    )
    enabled = pn.widgets.Switch(name="Watchlist habilitada", value=watchlist["enabled"])

    score_threshold = pn.widgets.FloatInput(
        name="Score mínimo", value=float(settings["signal_score_threshold"]), step=1
    )
    max_spread = pn.widgets.FloatInput(
        name="Spread opción máx. %",
        value=float(settings["max_option_spread_pct"]),
        step=0.05,
    )
    entry_ttl = pn.widgets.IntInput(
        name="Entry TTL (seg)", value=int(settings["entry_ttl_seconds"]), step=1
    )
    exit_requote = pn.widgets.IntInput(
        name="Requote salida (seg)", value=int(settings["exit_requote_seconds"]), step=1
    )
    timeout_seconds = pn.widgets.IntInput(
        name="Timeout posición (seg)", value=int(settings["position_timeout_seconds"]), step=5
    )
    stop_loss_pct = pn.widgets.FloatInput(
        name="Stop loss %",
        value=float(settings["stop_loss_pct"]) * 100,
        step=0.5,
    )

    market_table = pn.widgets.Tabulator(
        pd.DataFrame(),
        height=240,
        show_index=False,
        sizing_mode="stretch_width",
    )
    tape_table = pn.widgets.Tabulator(
        pd.DataFrame(),
        height=240,
        show_index=False,
        sizing_mode="stretch_width",
    )
    signals_table = pn.widgets.Tabulator(
        pd.DataFrame(),
        height=220,
        show_index=False,
        sizing_mode="stretch_width",
    )
    orders_table = pn.widgets.Tabulator(
        pd.DataFrame(),
        height=220,
        show_index=False,
        sizing_mode="stretch_width",
    )
    positions_table = pn.widgets.Tabulator(
        pd.DataFrame(),
        height=220,
        show_index=False,
        sizing_mode="stretch_width",
    )
    stats_md = pn.pane.Markdown("")

    def _parse_lines(value: str) -> list[str]:
        return [line.strip().upper() for line in value.splitlines() if line.strip()]

    def _sync_active_options(*_events):
        call_symbols = _parse_lines(calls_text.value)
        put_symbols = _parse_lines(puts_text.value)
        active_call_symbol.options = call_symbols or [""]
        active_put_symbol.options = put_symbols or [""]
        if call_symbols:
            active_call_symbol.value = (
                active_call_symbol.value if active_call_symbol.value in call_symbols else call_symbols[0]
            )
        else:
            active_call_symbol.value = ""
        if put_symbols:
            active_put_symbol.value = (
                active_put_symbol.value if active_put_symbol.value in put_symbols else put_symbols[0]
            )
        else:
            active_put_symbol.value = ""

    def _refresh():
        nonlocal watchlist
        watchlist = repository.get_active_watchlist()
        system = repository.get_system_health()
        system_status.object = (
            f"**Worker:** `{system['status']}`  \n"
            f"**Detalle:** {system['detail']}  \n"
            f"**Último heartbeat:** {system['created_at']}"
        )
        market_table.value = pd.DataFrame(repository.get_latest_market_state())
        tape_table.value = pd.DataFrame(repository.get_current_tape())
        signals_table.value = pd.DataFrame(repository.get_signal_history(limit=30))
        orders_table.value = pd.DataFrame(repository.get_paper_orders(limit=30))
        positions_table.value = pd.DataFrame(repository.get_paper_positions(limit=30))
        stats = repository.get_paper_stats()
        stats_md.object = (
            f"**PnL total:** {stats['total_pnl']:.2f}  \n"
            f"**Winrate:** {stats['winrate']:.2f}%  \n"
            f"**Posiciones abiertas:** {stats['open_positions']}  \n"
            f"**Hold promedio:** {stats['avg_hold_seconds']:.1f}s"
        )

    def _save_watchlist(_event=None):
        call_symbols = _parse_lines(calls_text.value)
        put_symbols = _parse_lines(puts_text.value)
        repository.update_active_watchlist(
            {
                "underlying_symbol": underlying_symbol.value.strip().upper(),
                "active_call_symbol": str(active_call_symbol.value or "").strip().upper(),
                "active_put_symbol": str(active_put_symbol.value or "").strip().upper(),
                "call_symbols": call_symbols,
                "put_symbols": put_symbols,
                "enabled": enabled.value,
            }
        )
        _refresh()

    def _save_strategy(_event=None):
        repository.update_strategy_settings(
            {
                "signal_score_threshold": score_threshold.value,
                "max_option_spread_pct": max_spread.value,
                "entry_ttl_seconds": entry_ttl.value,
                "exit_requote_seconds": exit_requote.value,
                "position_timeout_seconds": timeout_seconds.value,
                "stop_loss_pct": stop_loss_pct.value / 100.0,
            }
        )
        _refresh()

    save_watchlist.on_click(_save_watchlist)
    save_strategy.on_click(_save_strategy)
    calls_text.param.watch(_sync_active_options, "value")
    puts_text.param.watch(_sync_active_options, "value")
    _sync_active_options()

    left = pn.Column(
        title,
        system_status,
        pn.pane.Markdown("### Watchlist"),
        pn.pane.Markdown("#### Subyacente a monitorear"),
        underlying_symbol,
        pn.pane.Markdown("#### Bases a monitorear"),
        pn.Row(calls_text, puts_text),
        pn.Row(active_call_symbol, active_put_symbol),
        enabled,
        save_watchlist,
        pn.layout.Divider(),
        pn.pane.Markdown("### Estrategia"),
        score_threshold,
        max_spread,
        entry_ttl,
        exit_requote,
        timeout_seconds,
        stop_loss_pct,
        save_strategy,
        width=360,
    )

    center = pn.Column(
        pn.pane.Markdown("### Market Data"),
        market_table,
        pn.pane.Markdown("### Tape"),
        tape_table,
        sizing_mode="stretch_width",
    )

    right = pn.Column(
        pn.pane.Markdown("### Señales"),
        signals_table,
        pn.pane.Markdown("### Órdenes Paper"),
        orders_table,
        pn.pane.Markdown("### Posiciones"),
        positions_table,
        pn.pane.Markdown("### Estadísticas"),
        stats_md,
        sizing_mode="stretch_width",
    )

    dashboard = pn.Row(left, center, right, sizing_mode="stretch_width")
    pn.state.add_periodic_callback(_refresh, period=runtime["settings"].panel_refresh_ms)
    _refresh()
    return dashboard
