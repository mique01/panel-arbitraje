# app.py
import os
import time
import re
import requests
import pandas as pd
import panel as pn

pn.extension("tabulator")

# =========================
# Helpers
# =========================
def parse_tickers(text: str):
    """
    Lee tickers desde un TextArea (uno por línea).
    Soporta separadores: \n, \r\n, coma, punto y coma, tab.
    Limpia espacios y elimina vacíos/duplicados preservando orden.
    """
    if not text:
        return []
    # separa por saltos o comas/; tabs
    raw = re.split(r"[\n\r,;\t]+", text.strip())
    out = []
    seen = set()
    for x in raw:
        t = x.strip().upper()
        if not t:
            continue
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out

def safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        if isinstance(x, str) and x.strip() == "":
            return default
        return float(x)
    except Exception:
        return default

def best_punta_from_iol_quote(js: dict):
    """
    Intenta sacar mejor punta compra/venta desde distintas estructuras posibles.
    Devuelve dict con:
      - precioCompra
      - precioVenta
      - moneda (si existe)
    Ajustá esta función si tu JSON viene distinto.
    """
    if not isinstance(js, dict):
        return {"precioCompra": None, "precioVenta": None, "moneda": None}

    moneda = js.get("moneda") or js.get("Moneda")

    # Caso 1: viene algo tipo { ... "puntas": {"compra":[...], "venta":[...] } }
    puntas = js.get("puntas") or js.get("Puntas")
    if isinstance(puntas, dict):
        compras = puntas.get("compra") or puntas.get("Compra") or []
        ventas  = puntas.get("venta")  or puntas.get("Venta")  or []
        pc = compras[0].get("precio") if compras and isinstance(compras[0], dict) else None
        pv = ventas[0].get("precio")  if ventas  and isinstance(ventas[0], dict)  else None
        return {"precioCompra": pc, "precioVenta": pv, "moneda": moneda}

    # Caso 1b (IOL común): puntas es lista con un objeto mejor punta
    # [{"precioCompra": ..., "precioVenta": ..., ...}]
    if isinstance(puntas, list) and puntas and isinstance(puntas[0], dict):
        top = puntas[0]
        pc = top.get("precioCompra") or top.get("PrecioCompra") or top.get("bid") or top.get("Bid")
        pv = top.get("precioVenta") or top.get("PrecioVenta") or top.get("ask") or top.get("Ask")
        return {"precioCompra": pc, "precioVenta": pv, "moneda": moneda}

    # Caso 2: viene directo tipo { "precioCompra":..., "precioVenta":... }
    pc = js.get("precioCompra") or js.get("PrecioCompra") or js.get("bid") or js.get("Bid")
    pv = js.get("precioVenta") or js.get("PrecioVenta") or js.get("ask") or js.get("Ask")
    if pc is not None or pv is not None:
        return {"precioCompra": pc, "precioVenta": pv, "moneda": moneda}

    # Caso 3: viene en "cotizacion" o similar
    cot = js.get("cotizacion") or js.get("Cotizacion")
    if isinstance(cot, dict):
        pc = cot.get("precioCompra") or cot.get("PrecioCompra") or cot.get("bid") or cot.get("Bid")
        pv = cot.get("precioVenta") or cot.get("PrecioVenta") or cot.get("ask") or cot.get("Ask")
        moneda = moneda or cot.get("moneda") or cot.get("Moneda")
        return {"precioCompra": pc, "precioVenta": pv, "moneda": moneda}

    return {"precioCompra": None, "precioVenta": None, "moneda": moneda}


# =========================
# IOL Client (reemplazable)
# =========================
class IOLClient:
    """
    Cliente mínimo para IOL.
    Si vos ya tenés tu wrapper funcionando, podés borrar esta clase
    y reemplazar las llamadas en `get_quote()` por las tuyas.
    """
    def __init__(self):
        self.base = "https://api.invertironline.com"
        self.session = requests.Session()
        self.token = None
        self.token_expires_at = 0
        self.username = None
        self.password = None

    def login(self, username: str, password: str):
        """
        Login típico OAuth password grant (IOL).
        Si tu auth es diferente, ajustá acá.
        """
        url = f"{self.base}/token"
        data = {
            "grant_type": "password",
            "username": username,
            "password": password,
        }
        r = self.session.post(url, data=data, timeout=20)
        r.raise_for_status()
        js = r.json()
        self.token = js["access_token"]
        self.username = username
        self.password = password
        expires_in = js.get("expires_in", 900)
        self.token_expires_at = time.time() + int(expires_in) - 30

        self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    def is_logged(self):
        return self.token is not None and time.time() < self.token_expires_at

    def get_quote(self, ticker: str, plazo: str, mercado="bCBA"):
        """
        Obtiene cotización. Ajustá endpoint según tu implementación.

        En muchos ejemplos de IOL:
        /api/v2/Cotizaciones/{mercado}/Titulos/{ticker}/Cotizacion?plazo=...
        """
        # plazo: "T0" / "T1"
        # mercado: "bCBA" para BYMA (ejemplo)
        if (not self.is_logged()) and self.username and self.password:
            self.login(self.username, self.password)

        url = f"{self.base}/api/v2/Cotizaciones/{mercado}/Titulos/{ticker}/Cotizacion"
        params = {"plazo": plazo.upper()}
        r = self.session.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()


# =========================
# Panel UI
# =========================
iol = IOLClient()

# Widgets
w_user = pn.widgets.TextInput(name="Usuario IOL", placeholder="tu_mail@...")
w_pass = pn.widgets.PasswordInput(name="Password IOL", placeholder="********")
w_user.value = os.getenv("IOL_USER", "")
w_pass.value = os.getenv("IOL_PASS", "")
w_spread_min = pn.widgets.FloatInput(name="Spread mínimo (%)", value=0.5, step=0.1)
w_refresh = pn.widgets.IntInput(name="Refresh (seg)", value=60, step=5)
w_autorefresh = pn.widgets.Switch(name="Auto refresh", value=True)

w_tickers = pn.widgets.TextAreaInput(
    name="Tickers (uno por línea)",
    value="AL30\nGD30",
    height=220
)

btn_connect = pn.widgets.Button(name="Conectar", button_type="primary")
btn_update = pn.widgets.Button(name="Actualizar ahora", button_type="success")

# Indicadores
status = pn.pane.Markdown("🔴 **Desconectado**")
spinner = pn.indicators.LoadingSpinner(value=False, size=24)
progress = pn.widgets.Progress(name="Progreso", value=0, max=100, visible=False)

# Tabla
table = pn.widgets.Tabulator(
    pd.DataFrame(columns=["Activo", "Ask T0", "Bid T1", "Spread %", "Moneda"]),
    height=360,
    pagination="local",
    page_size=20,
    show_index=False,
    sizing_mode="stretch_width",
)

# =========================
# Logic
# =========================
def connect(event=None):
    spinner.value = True
    status.object = "⏳ **Conectando a IOL…**"
    try:
        iol.login(w_user.value.strip(), w_pass.value)
        status.object = "🟢 **Conectado a IOL**"
    except Exception as e:
        status.object = f"🔴 **Error de login:** `{type(e).__name__}`"
    finally:
        spinner.value = False

def update_quotes(event=None):
    tickers = parse_tickers(w_tickers.value)
    spread_min = safe_float(w_spread_min.value, 0.0)

    if not iol.is_logged():
        status.object = "🔴 **No estás conectado a IOL.** Tocá **Conectar**."
        return

    if not tickers:
        status.object = "⚠️ **No hay tickers cargados.**"
        return

    spinner.value = True
    progress.visible = True
    progress.value = 0
    progress.max = len(tickers)
    status.object = "⏳ **Actualizando cotizaciones…**"

    rows = []

    for i, t in enumerate(tickers, start=1):
        status.object = f"⏳ **Procesando {t} ({i}/{len(tickers)})…**"
        err_msg = None
        ask_t0 = None
        bid_t1 = None
        moneda = None
        spread_pct = None

        try:
            js_t0 = iol.get_quote(t, "t0")  # CI
            js_t1 = iol.get_quote(t, "t1")  # 24hs

            p0 = best_punta_from_iol_quote(js_t0)
            p1 = best_punta_from_iol_quote(js_t1)

            ask_t0 = safe_float(p0.get("precioVenta"), None)
            bid_t1 = safe_float(p1.get("precioCompra"), None)
            moneda = p0.get("moneda") or p1.get("moneda")

            if ask_t0 is not None and bid_t1 is not None and ask_t0 > 0:
                spread_pct = (bid_t1 / ask_t0 - 1) * 100

        except Exception as e:
            err_msg = f"{type(e).__name__}"

        rows.append({
            "Activo": t,
            "Ask T0": ask_t0,
            "Bid T1": bid_t1,
            "Spread %": spread_pct,
            "Moneda": moneda,
        })

        progress.value = i  # barra real

    df = pd.DataFrame(rows)

    # Filtrado por spread mínimo (si Spread % es None => queda afuera)
    df2 = df.copy()
    df2["Spread %"] = pd.to_numeric(df2["Spread %"], errors="coerce")
    df2 = df2[df2["Spread %"].notna()]
    df2 = df2[df2["Spread %"] >= spread_min]
    df2["Spread %"] = df2["Spread %"].round(2)
    df2 = df2.sort_values("Spread %", ascending=False)

    table.value = df2[["Activo", "Ask T0", "Bid T1", "Spread %", "Moneda"]].reset_index(drop=True)

    progress.visible = False
    spinner.value = False
    status.object = f"✅ **Actualizado** — {len(df2)} oportunidades (min {spread_min:.2f}%)"

# Auto refresh callback
_auto_cb = None

def set_autorefresh(event=None):
    global _auto_cb
    # limpia callback anterior
    if _auto_cb is not None:
        try:
            pn.state.remove_periodic_callback(_auto_cb)
        except Exception:
            pass
        _auto_cb = None

    if w_autorefresh.value:
        period_ms = max(5, int(w_refresh.value)) * 1000
        _auto_cb = pn.state.add_periodic_callback(update_quotes, period=period_ms, start=True)
        status.object = "🟡 **Auto refresh activado**"
    else:
        status.object = "🟢 **Auto refresh desactivado**"

# Bind events
btn_connect.on_click(connect)
btn_update.on_click(update_quotes)
w_autorefresh.param.watch(set_autorefresh, "value")
w_refresh.param.watch(set_autorefresh, "value")

# Layout
left = pn.Column(
    pn.pane.Markdown("## 🔎 Arbitraje CI → 24hs (IOL)"),
    pn.Row(status, spinner),
    progress,
    pn.layout.Divider(),
    w_user,
    w_pass,
    w_spread_min,
    w_refresh,
    w_autorefresh,
    w_tickers,
    pn.Row(btn_connect, btn_update),
    width=380,
)

app = pn.Row(left, table, sizing_mode="stretch_width")

# Inicializa auto-refresh si está activado
pn.state.onload(lambda: set_autorefresh())

app.servable()
