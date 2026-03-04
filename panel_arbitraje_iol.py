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


def one_line(text):
    return str(text).replace("\n", " ").replace("\r", " ")[:200]


# =========================
# IOL API
# =========================

class IOLClient:

    def __init__(self):
        self.base = "https://api.invertironline.com"
        self.session = requests.Session()
        self.token = None
        self.token_exp = 0
        self.username = None
        self.password = None

    def login(self, user, password):

        url = f"{self.base}/token"

        data = {
            "grant_type": "password",
            "username": user,
            "password": password
        }

        r = self.session.post(url, data=data)

        r.raise_for_status()

        js = r.json()

        self.token = js["access_token"]

        self.token_exp = time.time() + js.get("expires_in", 900) - 30

        self.session.headers.update(
            {"Authorization": f"Bearer {self.token}"}
        )

        self.username = user
        self.password = password

    def is_logged(self):
        return self.token and time.time() < self.token_exp

    def get_quote(self, ticker, plazo):

        url = f"{self.base}/api/v2/bCBA/Titulos/{ticker}/CotizacionDetalleMobile/{plazo}"

        r = self.session.get(url)

        if r.status_code != 200:
            return {}

        return r.json()


iol = IOLClient()

# =========================
# Panel Widgets
# =========================

w_user = pn.widgets.TextInput(name="Usuario IOL")
w_pass = pn.widgets.PasswordInput(name="Password")

w_spread = pn.widgets.FloatInput(name="Spread mínimo (%)", value=0.5)

w_refresh = pn.widgets.IntInput(name="Refresh (seg)", value=60)

w_auto = pn.widgets.Switch(name="Auto refresh", value=True)

w_tickers = pn.widgets.TextAreaInput(
    name="Tickers",
    value="AL30\nGD30",
    height=200
)

btn_connect = pn.widgets.Button(name="Conectar", button_type="primary")

btn_update = pn.widgets.Button(name="Actualizar", button_type="success")

status = pn.pane.Markdown("🔴 Desconectado")

spinner = pn.indicators.LoadingSpinner(value=False, size=20)

progress = pn.widgets.Progress(value=0, max=100)

TABLE_COLUMNS = ["Activo", "Ask T0", "Bid T1", "Spread %"]

table = pn.widgets.Tabulator(
    pd.DataFrame(columns=TABLE_COLUMNS),
    height=350,
    show_index=False
)

# =========================
# Login
# =========================

def connect(event=None):

    spinner.value = True

    try:

        iol.login(w_user.value, w_pass.value)

        status.object = "🟢 Conectado"

    except Exception as e:

        status.object = f"🔴 Error login: {one_line(e)}"

    spinner.value = False


btn_connect.on_click(connect)

# =========================
# Quotes
# =========================

_is_updating = False


def update_quotes(event=None):

    global _is_updating

    if _is_updating:
        return

    _is_updating = True

    spinner.value = True

    try:

        tickers = parse_tickers(w_tickers.value)

        spread_min = safe_float(w_spread.value, 0)

        rows = []

        for t in tickers:

            q0 = iol.get_quote(t, "t0")

            q1 = iol.get_quote(t, "t1")

            ask = None
            bid = None

            if "puntas" in q0 and q0["puntas"]:
                ask = q0["puntas"][0].get("precioVenta")

            if "puntas" in q1 and q1["puntas"]:
                bid = q1["puntas"][0].get("precioCompra")

            spread = None

            if ask and bid:
                spread = (bid / ask - 1) * 100

            rows.append({
                "Activo": t,
                "Ask T0": ask,
                "Bid T1": bid,
                "Spread %": spread
            })

        df = pd.DataFrame(rows)

        if not df.empty:

            df["Spread %"] = pd.to_numeric(df["Spread %"], errors="coerce")

            df = df.sort_values("Spread %", ascending=False)

        table.value = df.reset_index(drop=True)

        status.object = f"✅ Actualizado ({len(df)})"

    except Exception as e:

        status.object = f"🔴 Error: {one_line(e)}"

    spinner.value = False

    _is_updating = False


btn_update.on_click(update_quotes)

# =========================
# Layout
# =========================

left = pn.Column(

    pn.pane.Markdown("## Arbitraje CI → 24hs"),

    pn.Row(status, spinner),

    w_user,
    w_pass,

    w_spread,

    w_refresh,
    w_auto,

    w_tickers,

    pn.Row(btn_connect, btn_update),

    width=350
)

app = pn.Row(left, table, sizing_mode="stretch_width")
