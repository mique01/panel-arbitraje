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


def one_line(text, max_len=200):
    if text is None:
        return ""
    return str(text).replace("\n", " ").replace("\r", " ")[:max_len]


def best_punta_from_iol_quote(resp: dict):
    """
    Recibe wrapper de _request_quote():
      { ok, status_code, json, text, ... }
    Devuelve:
      precioCompra, precioVenta, cantidadCompra, cantidadVenta, moneda, hint
    """
    base = {
        "precioCompra": None,
        "precioVenta": None,
        "cantidadCompra": None,
        "cantidadVenta": None,
        "moneda": None,
        "hint": "",
    }

    if not isinstance(resp, dict):
        base["hint"] = "Respuesta inválida"
        return base

    if not resp.get("ok"):
        sc = resp.get("status_code")
        txt = one_line(resp.get("text"))
        base["hint"] = f"HTTP {sc}" + (f" - {txt}" if txt else "")
        return base

    js = resp.get("json")
    if not isinstance(js, dict):
        base["hint"] = "JSON vacío/estructura desconocida"
        return base

    base["moneda"] = js.get("moneda") or js.get("Moneda")

    puntas = js.get("puntas") or js.get("Puntas")

    # CotizacionDetalleMobile: puntas suele ser lista con un objeto
    if isinstance(puntas, list) and puntas and isinstance(puntas[0], dict):
        top = puntas[0]
        base["precioCompra"] = safe_float(top.get("precioCompra"), None)
        base["precioVenta"] = safe_float(top.get("precioVenta"), None)
        base["cantidadCompra"] = safe_float(top.get("cantidadCompra"), None)
        base["cantidadVenta"] = safe_float(top.get("cantidadVenta"), None)
        base["hint"] = "OK"
        return base

    # A veces puntas viene como dict
    if isinstance(puntas, dict):
        base["precioCompra"] = safe_float(puntas.get("precioCompra"), None)
        base["precioVenta"] = safe_float(puntas.get("precioVenta"), None)
        base["cantidadCompra"] = safe_float(puntas.get("cantidadCompra"), None)
        base["cantidadVenta"] = safe_float(puntas.get("cantidadVenta"), None)
        base["hint"] = "OK"
        return base

    base["hint"] = "JSON sin puntas"
    return base


# =========================
# IOL Client
# =========================
class IOLClient:
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
        # alias útiles (por si te tentás a escribir ci/24)
        if p in {"ci", "inmediato"}:
            return "t0"
        if p in {"24", "24hs", "24h"}:
            return "t1"
        if p in {"72", "72hs", "72h"}:
            return "t2"
        raise ValueError(f"Plazo inválido: {plazo}")

    def _request_quote(self, ticker: str, mercado: str, plazo_norm: str):
        # Según tu doc: /CotizacionDetalleMobile/{plazo} con plazo="t0"/"t1"/"t2"
        url = f"{self.base}/api/v2/{mercado}/Titulos/{ticker}/CotizacionDetalleMobile/{plazo_norm}"
        try:
            r = self.session.get(url, timeout=20, params={"_": int(time.time() * 1000)})
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

        r1 = self._request_quote(ticker=ticker, mercado=mercado, plazo_norm=plazo_norm)
        r1["fallback_used"] = False

        # fallback típico por case-sensitive de mercado (bCBA vs BCBA)
        if r1.get("status_code") in {400, 404} and mercado == "bCBA":
            r2 = self._request_quote(ticker=ticker, mercado="BCBA", plazo_norm=plazo_norm)
            r2["fallback_used"] = True
            r2["fallback_from"] = "bCBA"
            return r2

        return r1


# =========================
# Panel UI
# =========================
iol = IOLClient()

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

# Persistir configuración del usuario en el navegador para sobrevivir recargas.
# No se persiste la password por seguridad.
for _w in (w_user, w_spread_min, w_refresh, w_autorefresh, w_tickers):
    _w.persist = True

btn_connect = pn.widgets.Button(name="Conectar", button_type="primary")
btn_update = pn.widgets.Button(name="Actualizar ahora", button_type="success")

status = pn.pane.Markdown("🔴 **Desconectado**")
spinner = pn.indicators.LoadingSpinner(value=False, size=24)
progress = pn.widgets.Progress(name="Progreso", value=0, max=100, visible=False)

TABLE_COLUMNS = ["Activo", "Ask T0", "Bid T1", "Spread %"]


def make_table(value=None):
    if value is None:
        value = pd.DataFrame(columns=TABLE_COLUMNS)
    return pn.widgets.Tabulator(
        value,
        height=360,
        pagination="local",
        page_size=20,
        show_index=False,
        sizing_mode="stretch_width",
    )


table_container = pn.Column(make_table(), sizing_mode="stretch_width")


def set_table_value(df):
    """Recrea Tabulator en cada refresh para evitar estados internos inválidos."""
    if df is None:
        df = pd.DataFrame(columns=TABLE_COLUMNS)

    # Normalizar columnas esperadas para mantener el schema estable.
    for col in TABLE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[TABLE_COLUMNS].copy()

    table_container[:] = [make_table(df)]

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
        status.object = f"🔴 **Error de login:** `{type(e).__name__}` — {one_line(e)}"
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

    try:
        rows = []

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

        # Evitar pasar por `None` para no desmontar el Tabulator en algunos reloads.
        set_table_value(df_sorted.reset_index(drop=True).copy())

        # Oportunidades (para contador)
        df_opps = df_sorted[df_sorted["Spread %"].notna() & (df_sorted["Spread %"] >= spread_min)]
        status.object = f"✅ **Actualizado** — {len(df_opps)} oportunidades (min {spread_min:.2f}%) | Total: {len(df_sorted)}"
    except Exception as e:
        status.object = f"🔴 **Error al actualizar:** `{type(e).__name__}` — {one_line(e)}"
    finally:
        progress.visible = False
        spinner.value = False


# Auto refresh callback
_auto_cb = None

def set_autorefresh(event=None):
    global _auto_cb
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

app = pn.Row(left, table_container, sizing_mode="stretch_width")

pn.state.onload(lambda: set_autorefresh())

app.servable()
