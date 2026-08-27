"""Titulares de noticias por RSS (gratis, sin clave)."""
import re
import html
import urllib.request
import xml.etree.ElementTree as ET

_TIMEOUT = 9

_FEEDS = {
    "general": [("https://www.20minutos.es/rss/", "20 minutos"),
                ("https://e00-marca.uecdn.es/rss/portada.xml", "Marca")],
    "deportes": [("https://e00-marca.uecdn.es/rss/portada.xml", "Marca")],
    "tecnologia": [("https://www.xataka.com/index.xml", "Xataka")],
    "economia": [("https://e00-expansion.uecdn.es/rss/portada.xml", "Expansion")],
}


def _clean(t):
    t = html.unescape(t)
    t = re.sub(r"<[^>]+>", " ", t)       # quita etiquetas HTML
    return re.sub(r"\s+", " ", t).strip()


def _titles(url, n=5):
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0"})
    raw = urllib.request.urlopen(req, timeout=_TIMEOUT).read()
    root = ET.fromstring(raw)
    out = []
    for item in root.iter():
        if item.tag.split("}")[-1] not in ("item", "entry"):
            continue
        for ch in item:
            if ch.tag.split("}")[-1] == "title" and ch.text and ch.text.strip():
                t = _clean(ch.text)
                if t:
                    out.append(t)
                break
        if len(out) >= n:
            break
    return out


def brief(n: int = 2) -> str:
    """Version corta para el 'buenos dias': n titulares generales, o '' si falla."""
    for url, _src in _FEEDS["general"]:
        try:
            ts = _titles(url, n)
            if ts:
                return "Titulares: " + ". ".join(ts[:n]) + "."
        except Exception:
            continue
    return ""


def news_speech(query: str = "") -> str:
    q = (query or "").lower()
    cat = "general"
    if re.search(r"deporte|futbol|marca", q):
        cat = "deportes"
    elif re.search(r"tecnolog|informatic|\btech\b|xataka|gadget", q):
        cat = "tecnologia"
    elif re.search(r"econom|bolsa|finanz|mercado", q):
        cat = "economia"
    for url, _src in _FEEDS.get(cat, _FEEDS["general"]):
        try:
            ts = _titles(url, 5)
            if ts:
                return "Titulares de " + cat + ": " + ". ".join(ts[:5]) + "."
        except Exception:
            continue
    return "No he podido cargar las noticias ahora mismo."
