"""Cripto (CoinGecko), acciones (Yahoo Finance) y conversion de moneda (Frankfurter).
Todo con APIs gratuitas sin clave."""
import re
import json
import urllib.request

_TIMEOUT = 9


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0"})
    return json.loads(urllib.request.urlopen(req, timeout=_TIMEOUT).read().decode("utf-8", "replace"))


_COINS = {
    "bitcoin": "bitcoin", "btc": "bitcoin", "ethereum": "ethereum", "ether": "ethereum",
    "eth": "ethereum", "dogecoin": "dogecoin", "doge": "dogecoin", "cardano": "cardano",
    "solana": "solana", "sol": "solana", "ripple": "ripple", "xrp": "ripple",
    "litecoin": "litecoin", "ltc": "litecoin", "bnb": "binancecoin", "binance coin": "binancecoin",
    "polkadot": "polkadot", "tron": "tron", "monero": "monero", "shiba": "shiba-inu",
}
_COIN_SAY = {"bitcoin": "El bitcoin", "ethereum": "El ethereum", "dogecoin": "El dogecoin",
             "cardano": "Cardano", "solana": "Solana", "ripple": "XRP", "litecoin": "El litecoin",
             "binancecoin": "BNB", "polkadot": "Polkadot", "tron": "Tron", "monero": "Monero",
             "shiba-inu": "Shiba"}

_STOCKS = {
    "apple": "AAPL", "tesla": "TSLA", "microsoft": "MSFT", "amazon": "AMZN", "google": "GOOGL",
    "alphabet": "GOOGL", "nvidia": "NVDA", "meta": "META", "facebook": "META", "netflix": "NFLX",
    "amd": "AMD", "intel": "INTC", "coca cola": "KO", "disney": "DIS", "paypal": "PYPL",
    "spotify": "SPOT", "santander": "SAN.MC", "telefonica": "TEF.MC", "inditex": "ITX.MC",
    "iberdrola": "IBE.MC", "repsol": "REP.MC", "bbva": "BBVA.MC",
}

_CUR = {"euro": "EUR", "euros": "EUR", "dolar": "USD", "dolares": "USD", "dollar": "USD",
        "libra": "GBP", "libras": "GBP", "yen": "JPY", "yenes": "JPY", "franco": "CHF",
        "francos": "CHF", "peso": "MXN", "pesos": "MXN"}
_CUR_SAY = {"EUR": "euros", "USD": "dolares", "GBP": "libras", "JPY": "yenes",
            "CHF": "francos", "MXN": "pesos"}


def _fmt(n):
    n = float(n)
    if abs(n - round(n)) < 0.005:
        return str(int(round(n)))
    return ("%.2f" % n).replace(".", ",")


def _crypto(q):
    coin = None
    for k in sorted(_COINS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(k) + r"\b", q):
            coin = _COINS[k]
            break
    if not coin:
        return None
    d = _get("https://api.coingecko.com/api/v3/simple/price?ids=" + coin + "&vs_currencies=eur")
    price = d.get(coin, {}).get("eur")
    if price is None:
        return "No he podido consultar el precio."
    return _COIN_SAY.get(coin, coin) + " esta a " + _fmt(price) + " euros."


def _stock(q):
    tick, name = None, None
    for k in sorted(_STOCKS, key=len, reverse=True):
        if k in q:
            tick, name = _STOCKS[k], k
            break
    if not tick:
        return None
    d = _get("https://query1.finance.yahoo.com/v8/finance/chart/" + tick + "?interval=1d&range=1d")
    m = d["chart"]["result"][0]["meta"]
    price = m.get("regularMarketPrice")
    say = {"USD": "dolares", "EUR": "euros", "GBP": "libras"}.get(m.get("currency", "USD"), "")
    return "La accion de " + name.capitalize() + " esta a " + _fmt(price) + " " + say + "."


def _convert(q):
    m = re.search(r"(\d+(?:[.,]\d+)?)", q)
    if not m:
        return None
    amount = float(m.group(1).replace(",", "."))
    numpos = m.start(1)
    mentions = []
    for k in sorted(_CUR, key=len, reverse=True):
        for mm in re.finditer(r"\b" + re.escape(k) + r"\b", q):
            mentions.append((mm.start(), _CUR[k]))
    if len({c for _, c in mentions}) < 2:
        return None
    after = [x for x in mentions if x[0] > numpos]
    frm = (min(after, key=lambda x: x[0] - numpos)[1] if after
           else min(mentions, key=lambda x: abs(x[0] - numpos))[1])
    to = next((c for _, c in mentions if c != frm), None)
    if not to:
        return None
    d = _get("https://api.frankfurter.app/latest?amount=" + str(amount) + "&from=" + frm + "&to=" + to)
    val = d.get("rates", {}).get(to)
    if val is None:
        return "No he podido convertir esa moneda."
    return _fmt(amount) + " " + _CUR_SAY[frm] + " son " + _fmt(val) + " " + _CUR_SAY[to] + "."


def finance_speech(query: str = "") -> str:
    q = (query or "").lower()
    for fn in (_convert, _crypto, _stock):
        try:
            r = fn(q)
            if r:
                return r
        except Exception:
            continue
    return "No he encontrado ese dato financiero."
