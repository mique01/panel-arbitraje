def update_quotes(event=None):
    global _is_updating
    if _is_updating:
        return
    _is_updating = True

    spinner.value = True
    progress.visible = True

    try:
        tickers = parse_tickers(w_tickers.value)
        spread_min = safe_float(w_spread_min.value, 0.0)

        if not iol.is_logged():
            status.object = "🔴 **No estás conectado a IOL.** Tocá **Conectar**."
            return

        rows = []
        progress.max = max(1, len(tickers))
        progress.value = 0

        for i, t in enumerate(tickers, start=1):
            status.object = f"⏳ **Procesando {t} ({i}/{len(tickers)})…**"

            r_t0 = iol.get_quote(t, "t0")  # CI
            r_t1 = iol.get_quote(t, "t1")  # 24hs

            p0 = best_punta_from_iol_quote(r_t0)
            p1 = best_punta_from_iol_quote(r_t1)

            ask_t0 = p0.get("precioVenta")
            bid_t1 = p1.get("precioCompra")

            spread_pct = None
            if ask_t0 is not None and bid_t1 is not None and ask_t0 > 0 and bid_t1 > 0:
                spread_pct = (bid_t1 / ask_t0 - 1) * 100

            rows.append({
                "Activo": t,
                "Ask T0": ask_t0,
                "Bid T1": bid_t1,
                "Spread %": spread_pct,
            })

            progress.value = i

        df = pd.DataFrame(rows)

        if df.empty:
            df = pd.DataFrame(columns=TABLE_COLUMNS)

        df["Spread %"] = pd.to_numeric(df["Spread %"], errors="coerce")
        df_sorted = df.sort_values("Spread %", ascending=False, na_position="last")

        table.value = df_sorted.reset_index(drop=True).copy()

        df_opps = df_sorted[
            df_sorted["Spread %"].notna() &
            (df_sorted["Spread %"] >= spread_min)
        ]

        status.object = (
            f"✅ **Actualizado** — {len(df_opps)} oportunidades "
            f"(min {spread_min:.2f}%) | Total: {len(df_sorted)}"
        )

    except Exception as e:
        status.object = (
            f"🔴 **Error al actualizar:** `{type(e).__name__}` — {one_line(e)}"
        )

    finally:
        progress.visible = False
        spinner.value = False
        _is_updating = False
