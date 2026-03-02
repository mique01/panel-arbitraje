import os
import time
import re
import requests
import pandas as pd
import panel as pn

pn.extension("tabulator")


def parse_tickers(text: str):
    if not text:
        return []
    raw = re.split(r"[\n\r,;\t]+", text.strip())
    out, seen = [], set()
    for x in raw:
        t = x.strip().upper()
        if t and t not in seen:
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


def one_line(text, max_len=180):
    if text is None:
        return ""
    return str(text).replace("\n", " ").replace("\r", " ")[:max_len]


def best_punta_from_iol_quote(resp: dict):
    """
    Recibe respuesta estándar de get_quote() y devuelve:
    - precioCompra, precioVenta, moneda
    - cantidadCompra, cantidadVenta
    - hint
    """
    if not isinstance(resp, dict):
        return {
            "precioCompra": None,
            "precioVenta": None,
            "cantidadCompra": None,
            "cantidadVenta": None,
            "moneda": None,
            "hint": "Respuesta inválida",
        }

    if not resp.get("ok"):
        sc = resp.get("status_code")
        txt = one_line(resp.get("text"))
        hint = f"HTTP {sc}" + (f" - {txt}" if txt else "")
        return {
            "precioCompra": None,
            "precioVenta": None,
            "cantidadCompra": None,
            "cantidadVenta": None,
            "moneda": None,
            "hint": hint,
        }

    js = resp.get("json")
    if not isinstance(js, dict):
        return {
            "precioCompra": None,
            "precioVenta": None,
            "cantidadCompra": None,
            "cantidadVenta": None,
            "moneda": None,
            "hint": "JSON vacío / estructura desconocida",
        }

    moneda = js.get("moneda") or js.get("Moneda")
    puntas = js.get("puntas")

    if isinstance(puntas, list) and puntas and isinstance(puntas[0], dict):
        top = puntas[0]
        return {
            "precioCompra": safe_float(top.get("precioCompra"), None),
            "precioVenta": safe_float(top.get("precioVenta"), None),
            "cantidadCompra": safe_float(top.get("cantidadCompra"), None),
            "cantidadVenta": safe_float(top.get("cantidadVenta"), None),
            "moneda": moneda,
            "hint": "OK",
        }

    return {
        "precioCompra": None,
        "precioVenta": None,
        "cantidadCompra": None,
        "cantidadVenta": None,
        "moneda": moneda,
        "hint": "JSON sin puntas válidas",
    }


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

        r1 = self._request_quote(ticker=ticker, mercado=mercado, plazo_norm=plazo_norm)
        r1["fallback_used"] = False

        if r1.get("status_code") in {400, 404} and mercado == "bCBA":
            r2 = self._request_quote(ticker=ticker, mercado="BCBA", plazo_norm=plazo_norm)
            r2["fallback_used"] = True
            r2["fallback_from"] = "bCBA"
            return r2

        return r1


iol = IOLClient()

w_user = pn.widgets.TextInput(name="Usuario IOL", placeholder="tu_mail@...")
w_pass = pn.widgets.PasswordInput(name="Password IOL", placeholder="********")
w_user.value = os.getenv("IOL_USER", "")
w_pass.value = os.getenv("IOL_PASS", "")
w_spread_min = pn.widgets.FloatInput(name="Spread mínimo (%)", value=0.5, step=0.1)
w_refresh = pn.widgets.IntInput(name="Refresh (seg)", value=60, step=1, start=3)
w_autorefresh = pn.widgets.Switch(name="Auto refresh", value=True)

w_tickers = pn.widgets.TextAreaInput(name="Tickers (uno por línea)", value="AL30\nGD30", height=220)

btn_connect = pn.widgets.Button(name="Conectar", button_type="primary")
btn_disconnect = pn.widgets.Button(name="Desconectar", button_type="warning")
btn_update = pn.widgets.Button(name="Actualizar ahora", button_type="success")

status = pn.pane.Markdown("🔴 **Desconectado**")
spinner = pn.indicators.LoadingSpinner(value=False, size=24)
progress = pn.widgets.Progress(name="Progreso", value=0, max=100, visible=False)

TABLE_COLUMNS = [
    "Activo", "Ask T0", "Bid T1", "Spread %", "Moneda",
    "QtyAskT0", "QtyBidT1", "HTTP_T0", "HTTP_T1", "Hint_T0", "Hint_T1"
]

table = pn.widgets.Tabulator(
    pd.DataFrame(columns=TABLE_COLUMNS),
    height=360,
    pagination="local",
    page_size=20,
    show_index=False,
    sizing_mode="stretch_width",
)

last_error = pn.pane.Markdown("**Último error:** _(sin errores todavía)_", sizing_mode="stretch_width")


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
    table.value = pd.DataFrame(columns=TABLE_COLUMNS)


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
            "QtyAskT0": qty_ask_t0,
            "QtyBidT1": qty_bid_t1,
            "HTTP_T0": r_t0.get("status_code"),
            "HTTP_T1": r_t1.get("status_code"),
            "Hint_T0": hint_t0,
            "Hint_T1": hint_t1,
            "_SpreadRaw": spread_pct,
        })

        progress.value = i

    df_all = pd.DataFrame(rows)
    df_all["_SpreadRaw"] = pd.to_numeric(df_all["_SpreadRaw"], errors="coerce")
    df_all["Spread %"] = df_all["_SpreadRaw"].round(2)
    df_all = df_all.sort_values("_SpreadRaw", ascending=False, na_position="last")

    table.value = df_all[TABLE_COLUMNS].reset_index(drop=True)

    df_opps = df_all[(df_all["_SpreadRaw"].notna()) & (df_all["_SpreadRaw"] >= spread_min)]

    if last_fail is not None:
        last_error.object = (
            "**Último error:**  "
            f"ticker=`{last_fail['ticker']}` | plazo=`{last_fail['plazo']}` | "
            f"status=`{last_fail['status_code']}`  \n"
            f"url=`{last_fail['url']}`  \n"
            f"text=`{one_line(last_fail.get('text'), 250)}`  \n"
            f"json_keys=`{last_fail.get('json_keys')}`"
        )

    progress.visible = False
    spinner.value = False
    status.object = (
        f"✅ **Actualizado** — {len(df_opps)} oportunidades (min {spread_min:.4f}%) | "
        f"Total tickers: {len(df_all)}"
    )


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
        period_ms = max(3, int(w_refresh.value)) * 1000
        _auto_cb = pn.state.add_periodic_callback(update_quotes, period=period_ms, start=True)
        status.object = "🟡 **Auto refresh activado**"
    else:
        status.object = "🟢 **Auto refresh desactivado**"


btn_connect.on_click(connect)
btn_disconnect.on_click(disconnect)
btn_update.on_click(update_quotes)
w_autorefresh.param.watch(set_autorefresh, "value")
w_refresh.param.watch(set_autorefresh, "value")

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

right = pn.Column(table, last_error, sizing_mode="stretch_width")
app = pn.Row(left, right, sizing_mode="stretch_width")

pn.state.onload(lambda: set_autorefresh())
