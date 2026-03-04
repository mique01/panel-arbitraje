import time
import re
import requests
import pandas as pd
import panel as pn
from concurrent.futures import ThreadPoolExecutor, as_completed

pn.extension("tabulator")

# =========================
# Helpers
# =========================

def parse_tickers(text):
    if not text:
        return []

    raw = re.split(r"[\n\r,;\t]+", text.strip())

    out = []
    seen = set()

    for x in raw:
        t = x.strip().upper()

        if t and t not in seen:
            seen.add(t)
            out.append(t)

    return out


def beep():
    print("\a")


# =========================
# IOL Client
# =========================

class IOLClient:

    def __init__(self):

        self.base = "https://api.invertironline.com"
        self.session = requests.Session()
        self.token = None
        self.token_exp = 0

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

        self.session.headers.update({
            "Authorization": f"Bearer {self.token}"
        })


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
# Widgets
# =========================

w_user = pn.widgets.TextInput(name="Usuario IOL")

w_pass = pn.widgets.PasswordInput(name="Password")

w_tipo = pn.widgets.Select(
    name="Tipo de activo",
    options=["Bonos","Letras","Acciones/CEDEAR","Opciones"],
    value="Bonos"
)

w_spread = pn.widgets.FloatInput(name="Spread Neto mínimo (%)", value=0.05)

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

spinner = pn.indicators.LoadingSpinner(value=False)

TABLE_COLUMNS = [
"Activo",
"Ask T0",
"Bid T1",
"Spread %",
"Spread Neto %",
"TNA %"
]

table = pn.widgets.Tabulator(
    pd.DataFrame(columns=TABLE_COLUMNS),
    height=450,
    show_index=False,
    sizing_mode="stretch_width"
)

# =========================
# Comisiones ida + vuelta
# =========================

def get_comision():

    tipo = w_tipo.value

    if tipo == "Bonos":
        return 0.32

    if tipo == "Letras":
        return 0.302

    if tipo == "Acciones/CEDEAR":
        return 0.484

    if tipo == "Opciones":
        return 0.847

    return 0


# =========================
# Login
# =========================

def connect(event=None):

    spinner.value = True

    try:

        iol.login(w_user.value, w_pass.value)

        status.object = "🟢 Conectado a IOL"

    except Exception as e:

        status.object = f"🔴 Error login: {e}"

    spinner.value = False


btn_connect.on_click(connect)

# =========================
# Quotes
# =========================

_is_updating = False


def fetch_ticker(t):

    q0 = iol.get_quote(t,"t0")
    q1 = iol.get_quote(t,"t1")

    ask = None
    bid = None

    if "puntas" in q0 and q0["puntas"]:
        ask = q0["puntas"][0].get("precioVenta")

    if "puntas" in q1 and q1["puntas"]:
        bid = q1["puntas"][0].get("precioCompra")

    return t, ask, bid


def update_quotes(event=None):

    global _is_updating

    if _is_updating:
        return

    _is_updating = True

    spinner.value = True

    try:

        tickers = parse_tickers(w_tickers.value)

        comision = get_comision()

        rows = []

        oportunidades = 0

        with ThreadPoolExecutor(max_workers=12) as executor:

            futures = [executor.submit(fetch_ticker,t) for t in tickers]

            for future in as_completed(futures):

                t, ask, bid = future.result()

                spread = None
                spread_neto = None
                tna = None

                if ask and bid and ask > 0 and bid > 0:

                    spread = round((bid/ask-1)*100,2)

                    spread_neto = round(spread-comision,2)

                    tna = round(spread_neto*365,2)

                    if spread_neto >= w_spread.value:
                        oportunidades += 1

                rows.append({
                    "Activo":t,
                    "Ask T0":ask,
                    "Bid T1":bid,
                    "Spread %":spread,
                    "Spread Neto %":spread_neto,
                    "TNA %":tna
                })


        df = pd.DataFrame(rows)

        if not df.empty:

            df["Spread Neto %"] = pd.to_numeric(df["Spread Neto %"], errors="coerce")

            df = df.sort_values("Spread Neto %",ascending=False)

        table.value = df.reset_index(drop=True)

        if oportunidades > 0:
            beep()

        status.object = f"✅ Actualizado | {oportunidades} oportunidades"

    except Exception as e:

        status.object = f"🔴 Error: {e}"

    spinner.value = False

    _is_updating = False


btn_update.on_click(update_quotes)

# =========================
# Auto refresh
# =========================

_auto_cb = None


def set_autorefresh(event=None):

    global _auto_cb

    if _auto_cb:
        pn.state.remove_periodic_callback(_auto_cb)

    if w_auto.value:

        _auto_cb = pn.state.add_periodic_callback(
            update_quotes,
            period=w_refresh.value*1000
        )


w_auto.param.watch(set_autorefresh,"value")
w_refresh.param.watch(set_autorefresh,"value")

# =========================
# Layout
# =========================

left = pn.Column(

    pn.pane.Markdown("## 🔎 Arbitraje CI → 24hs"),

    pn.Row(status,spinner),

    w_user,
    w_pass,

    w_tipo,

    w_spread,

    w_refresh,
    w_auto,

    w_tickers,

    pn.Row(btn_connect,btn_update),

    width=350
)

app = pn.Row(left,table,sizing_mode="stretch_width")

pn.state.onload(lambda: set_autorefresh())
