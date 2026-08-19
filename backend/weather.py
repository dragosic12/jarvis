"""
El tiempo (clima) via open-meteo (gratis, sin API key). Ubicacion configurable por
env: JARVIS_LAT / JARVIS_LON / JARVIS_CITY (por defecto Madrid). Devuelve una frase
en espanol para que Jarvis la hable.
"""
import os
import json
import urllib.request

LAT = os.environ.get("JARVIS_LAT", "40.4168")
LON = os.environ.get("JARVIS_LON", "-3.7038")
CITY = os.environ.get("JARVIS_CITY", "Madrid")

# Codigos WMO redactados para que suenen bien tras "esta ..."
_WMO = {
    0: "despejado", 1: "casi despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "con niebla", 48: "con niebla helada",
    51: "lloviznando", 53: "lloviznando", 55: "lloviznando fuerte",
    56: "con llovizna helada", 57: "con llovizna helada",
    61: "lloviendo un poco", 63: "lloviendo", 65: "lloviendo fuerte",
    66: "con lluvia helada", 67: "con lluvia helada",
    71: "nevando un poco", 73: "nevando", 75: "nevando fuerte", 77: "con aguanieve",
    80: "con chubascos", 81: "con chubascos", 82: "con chubascos fuertes",
    85: "con nevadas", 86: "con nevadas fuertes",
    95: "con tormenta", 96: "con tormenta y granizo", 99: "con tormenta y granizo",
}


def weather_now() -> str:
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
           "&current=temperature_2m,apparent_temperature,weather_code&timezone=auto")
    with urllib.request.urlopen(url, timeout=8) as r:
        d = json.loads(r.read().decode())
    c = d["current"]
    t = round(c["temperature_2m"])
    feels = round(c["apparent_temperature"])
    desc = _WMO.get(int(c["weather_code"]), "con tiempo variable")
    s = f"en {CITY} hace {t} grados y esta {desc}"
    if abs(feels - t) >= 3:
        s += f", con sensacion de {feels}"
    return s


def weather_speech() -> str:
    try:
        return "Ahora mismo " + weather_now() + "."
    except Exception:
        return "No he podido consultar el tiempo ahora mismo."


if __name__ == "__main__":
    print(weather_speech())
