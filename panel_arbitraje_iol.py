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


def safe_float(x, default=None):
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

    # Caso 0: viene directo tipo {"precioCompra":..., "precioVenta":...}
    pc = safe_float(js.get("precioCompra") or js.get("PrecioCompra") or js.get("bid") or js.get("Bid"), None)
    pv = safe_float(js.get("precioVenta") or js.get("PrecioVenta") or js.get("ask") or js.get("Ask"), None)
    if pc is not None or pv is not None:
        return {"precioCompra": pc, "precioVenta": pv, "moneda": moneda}

    # Caso 1: viene algo tipo { ... "puntas": {"compra":[...], "venta":[...] } }
    puntas = js.get("puntas") or js.get("Puntas")
    if isinstance(puntas, dict):
        compras = puntas.get("compra") or puntas.get("Compra") or []
        ventas  = puntas.get("venta")  or puntas.get("Venta")  or []
        pc = safe_float(compras[0].get("precio") if compras and isinstance(compras[0], dict) else None, None)
        pv = safe_float(ventas[0].get("precio")  if ventas  and isinstance(ventas[0], dict)  else None, None)
        return {"precioCompra": pc, "precioVenta": pv, "moneda": moneda}

    # Caso 1b (IOL común): puntas es lista con un objeto mejor punta
    # [{"precioCompra": ..., "precioVenta": ..., ...}]
    if isinstance(puntas, list) and puntas and isinstance(puntas[0], dict):
        top = puntas[0]
        pc = safe_float(top.get("precioCompra") or top.get("PrecioCompra") or top.get("bid") or top.get("Bid"), None)
        pv = safe_float(top.get("precioVenta") or top.get("PrecioVenta") or top.get("ask") or top.get("Ask"), None)
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

    def _normalize_plazo(self, plazo):
        p = str(plazo).strip().lower()
        if p in {"t0", "t1", "t2"}:
            return p
        raise ValueError(f"Plazo inválido: {plazo}")

    def _request_quote(self, ticker: str, mercado: str, plazo_norm: str):
        url = f"{self.base}/api/v2/{mercado}/Titulos/{ticker}/CotizacionDetalleMobile/{plazo_norm}"
        try:
            r = self.session.get(url, timeout=20)
            status = r.status_code
            try:
                js = r.json()
                txt = None
            except Exception:
                js = None
                txt = (r.text or "")[:400]
            return {
                "ok": 200 <= status < 300,
                "status_code": status,
                "url": url,
                "json": js,
                "text": txt,
                "mercado": mercado,
            }
        except Exception as e:
            return {
                "ok": False,
                "status_code": 0,
                "url": url,
                "json": None,
                "text": str(e)[:400],
                "mercado": mercado,
            }

    def get_quote(self, ticker: str, plazo: str, mercado="bCBA"):
        plazo_norm = self._normalize_plazo(plazo)

        if (not self.is_logged()) and self.username and self.password:
            self.login(self.username, self.password)

        url = f"{self.base}/api/v2/{mercado}/Titulos/{ticker}/CotizacionDetalleMobile/{plazo_num}"
        r = self.session.get(url, timeout=20)
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
w_refresh = pn.widgets.IntInput(name="Refresh (seg)", value=60, step=1, start=3)
w_autorefresh = pn.widgets.Switch(name="Auto refresh", value=True)

w_tickers = pn.widgets.TextAreaInput(name="Tickers (uno por línea)", value="AL30\nGD30", height=220)
w_refresh = pn.widgets.IntInput(name="Refresh (seg)", value=60, step=5)
w_autorefresh = pn.widgets.Switch(name="Auto refresh", value=True)

w_tickers = pn.widgets.TextAreaInput(
    name="Tickers (uno por línea)",
    value="AL30\nGD30",
    height=220
)

btn_connect = pn.widgets.Button(name="Conectar", button_type="primary")
btn_disconnect = pn.widgets.Button(name="Desconectar", button_type="warning")
btn_update = pn.widgets.Button(name="Actualizar ahora", button_type="success")

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


def disconnect(event=None):
    global _auto_cb
    w_autorefresh.value = False
    if _auto_cb is not None:
        try:
            pn.state.remove_periodic_callback(_auto_cb)
        except Exception:
            pass
        _auto_cb = None

    iol.token = None
    iol.token_expires_at = 0
    iol.session.headers.pop("Authorization", None)

    status.object = "🔴 **Desconectado**"
    spinner.value = False
    progress.visible = False
    table.value = pd.DataFrame(columns=["Activo", "Ask T0", "Bid T1", "Spread %", "Moneda", "Error", "Debug"])

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
    last_fail = None

    for i, t in enumerate(tickers, start=1):
        status.object = f"⏳ **Procesando {t} ({i}/{len(tickers)})…**"

        r_t0 = iol.get_quote(t, "t0")
        r_t1 = iol.get_quote(t, "t1")

        p0 = best_punta_from_iol_quote(r_t0)
        p1 = best_punta_from_iol_quote(r_t1)

        ask_t0 = p0.get("precioVenta")
        bid_t1 = p1.get("precioCompra")
        qty_ask_t0 = p0.get("cantidadVenta")
        qty_bid_t1 = p1.get("cantidadCompra")
        moneda = p0.get("moneda") or p1.get("moneda")

        spread_pct = None
        if ask_t0 is not None and bid_t1 is not None and ask_t0 > 0 and bid_t1 > 0:
            spread_pct = (bid_t1 / ask_t0 - 1) * 100

        hint_t0 = p0.get("hint", "")
        hint_t1 = p1.get("hint", "")

        if r_t0.get("fallback_used"):
            hint_t0 = f"{hint_t0} | mercado={r_t0.get('mercado')}"
        if r_t1.get("fallback_used"):
            hint_t1 = f"{hint_t1} | mercado={r_t1.get('mercado')}"

        if (not r_t0.get("ok")) or (not r_t1.get("ok")) or ask_t0 is None or bid_t1 is None:
            bad_resp = r_t0 if (not r_t0.get("ok") or ask_t0 is None) else r_t1
            js = bad_resp.get("json")
            keys_info = list(js.keys())[:10] if isinstance(js, dict) else str(type(js).__name__)
            last_fail = {
                "ticker": t,
                "plazo": "t0" if bad_resp is r_t0 else "t1",
                "status_code": bad_resp.get("status_code"),
                "url": bad_resp.get("url"),
                "text": bad_resp.get("text"),
                "json_keys": keys_info,
            }

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
        period_ms = max(3, int(w_refresh.value)) * 1000
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
    pn.Row(btn_connect, btn_disconnect, btn_update),
    width=380,
)

app = pn.Row(left, table, sizing_mode="stretch_width")

# Inicializa auto-refresh si está activado
pn.state.onload(lambda: set_autorefresh())

app.servable()
