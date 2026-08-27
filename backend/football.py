"""Partidos de futbol en tiempo real (TheSportsDB, API gratuita sin registro).
Responde a 'quien juega hoy' y 'cuando/a que hora juega el <equipo>'."""
import re
import json
import datetime
import urllib.parse
import urllib.request

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Madrid")
except Exception:
    _TZ = None

_BASE = "https://www.thesportsdb.com/api/v1/json/3"
_TIMEOUT = 9

_MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# alias (texto normalizado, sin tildes) -> nombre canonico para searchteams
_ALIASES = {
    "real madrid": "Real Madrid", "madrid": "Real Madrid",
    "barcelona": "Barcelona", "barca": "Barcelona", "barsa": "Barcelona", "barza": "Barcelona",
    "atletico de madrid": "Atletico Madrid", "atletico": "Atletico Madrid", "atleti": "Atletico Madrid",
    "athletic": "Athletic Bilbao", "bilbao": "Athletic Bilbao",
    "real sociedad": "Real Sociedad", "la real": "Real Sociedad",
    "sevilla": "Sevilla", "betis": "Real Betis", "valencia": "Valencia",
    "villarreal": "Villarreal", "celta": "Celta Vigo", "getafe": "Getafe",
    "girona": "Girona", "osasuna": "Osasuna", "rayo": "Rayo Vallecano",
    "espanyol": "Espanyol", "mallorca": "Mallorca", "alaves": "Alaves", "cadiz": "Cadiz",
    "las palmas": "Las Palmas", "leganes": "Leganes", "valladolid": "Valladolid",
    "psg": "Paris SG", "manchester city": "Manchester City", "city": "Manchester City",
    "manchester united": "Manchester United", "united": "Manchester United",
    "liverpool": "Liverpool", "chelsea": "Chelsea", "arsenal": "Arsenal", "tottenham": "Tottenham",
    "tottenham": "Tottenham", "newcastle": "Newcastle", "aston villa": "Aston Villa",
    "west ham": "West Ham", "everton": "Everton", "brighton": "Brighton", "wolves": "Wolves",
    "nottingham": "Nottingham Forest", "fulham": "Fulham", "crystal palace": "Crystal Palace",
    "brentford": "Brentford", "bournemouth": "Bournemouth", "leeds": "Leeds",
    "bayern": "Bayern Munich", "juventus": "Juventus", "milan": "AC Milan", "inter": "Inter",
    "napoles": "Napoli", "dortmund": "Borussia Dortmund", "porto": "Porto", "benfica": "Benfica",
}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _today():
    now = datetime.datetime.now(_TZ) if _TZ else datetime.datetime.now()
    return now.date()


def _when(ev):
    """(hora 'HH:MM' en Madrid, fecha date) del evento, o ('', None)."""
    ts = ev.get("strTimestamp")
    try:
        if ts:
            dt = datetime.datetime.fromisoformat(ts.replace("Z", ""))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            if _TZ:
                dt = dt.astimezone(_TZ)
            return dt.strftime("%H:%M"), dt.date()
    except Exception:
        pass
    t = (ev.get("strTime") or "")[:5]
    try:
        d = datetime.date.fromisoformat(ev.get("dateEvent"))
    except Exception:
        d = None
    return t, d


def _find_team(q):
    padded = " " + q + " "
    best = None
    for k in _ALIASES:
        if (" " + k + " ") in padded and (best is None or len(k) > len(best)):
            best = k
    return _ALIASES.get(best) if best else None


def _team_speech(canonical):
    try:
        d = _get(_BASE + "/searchteams.php?t=" + urllib.parse.quote(canonical))
        teams = d.get("teams")
        if not teams:
            return "No he encontrado ese equipo."
        tid = teams[0]["idTeam"]
        name = teams[0].get("strTeam", canonical)
        ev = _get(_BASE + "/eventsnext.php?id=" + tid)
        events = ev.get("events")
        if not events:
            return "No tengo el proximo partido de " + name + " ahora mismo."
        e = events[0]
        hhmm, edate = _when(e)
        match = e.get("strEvent", "")
        if edate == _today():
            r = "Si, " + name + " juega hoy"
            if hhmm:
                r += " a las " + hhmm
            return r + ". " + match + "."
        r = name + " no juega hoy. Su proximo partido es"
        if edate:
            r += " el " + str(edate.day) + " de " + _MESES[edate.month]
        if hhmm:
            r += " a las " + hhmm
        return r + ": " + match + "."
    except Exception:
        return "No he podido consultar los partidos ahora mismo."


# ligas para "quien juega hoy" -> id TheSportsDB (eventsnextleague, mas completo que eventsday)
_LEAGUES = (("4335", "La Liga"), ("4328", "Premier"), ("4480", "Champions"))


def _today_matches():
    today = _today()
    found = []
    for lid, _name in _LEAGUES:
        try:
            d = _get(_BASE + "/eventsnextleague.php?id=" + lid)
            for e in (d.get("events") or []):
                hhmm, edate = _when(e)
                if edate == today:
                    found.append((hhmm or "99:99", e.get("strEvent", "")))
        except Exception:
            continue
    if not found:
        return ("Hoy no hay partidos de La Liga, Premier ni Champions. "
                "Dime un equipo y te digo cuando juega.")
    found.sort(key=lambda x: x[0])
    partes = [nm + (" a las " + h if h != "99:99" else "") for h, nm in found[:6]]
    return "Hoy juegan: " + "; ".join(partes) + "."


def _result_speech(canonical):
    try:
        d = _get(_BASE + "/searchteams.php?t=" + urllib.parse.quote(canonical))
        teams = d.get("teams")
        if not teams:
            return "No he encontrado ese equipo."
        tid = teams[0]["idTeam"]
        name = teams[0].get("strTeam", canonical)
        d = _get(_BASE + "/eventslast.php?id=" + tid)
        res = d.get("results")
        if not res:
            return "No tengo el ultimo resultado de " + name + "."
        e = res[0]
        try:
            hs, aw = int(e.get("intHomeScore")), int(e.get("intAwayScore"))
        except (TypeError, ValueError):
            return name + " todavia no tiene resultado de su ultimo partido."
        home = e.get("idHomeTeam") == tid
        mine, theirs = (hs, aw) if home else (aw, hs)
        rival = e.get("strAwayTeam") if home else e.get("strHomeTeam")
        if mine > theirs:
            return name + " gano " + str(mine) + " a " + str(theirs) + " contra " + rival + "."
        if mine < theirs:
            return name + " perdio " + str(mine) + " a " + str(theirs) + " contra " + rival + "."
        return name + " empato a " + str(mine) + " contra " + rival + "."
    except Exception:
        return "No he podido consultar el resultado ahora mismo."


_RESULT_RE = re.compile(r"como quedo|que resultado|resultado d|como (fue|quedaron|han quedado)|"
                        r"gano el|perdio el|empato el|marcador")
_TABLE_RE = re.compile(r"clasificacion|en que puesto|que puesto|en que posicion|posicion va|"
                       r"\btabla\b|lider de la liga|como va la liga|quien va (primero|lider)")

_ORD = {1: "primero", 2: "segundo", 3: "tercero", 4: "cuarto", 5: "quinto", 6: "sexto"}


def _season():
    d = _today()
    return "%d-%d" % (d.year, d.year + 1) if d.month >= 7 else "%d-%d" % (d.year - 1, d.year)


def _standings_speech(team):
    season = _season()
    ligas = (("4335", "La Liga"), ("4328", "la Premier"))
    try:
        if team:
            d = _get(_BASE + "/searchteams.php?t=" + urllib.parse.quote(team))
            teams = d.get("teams")
            if not teams:
                return "No he encontrado ese equipo."
            tid = teams[0]["idTeam"]
            name = teams[0].get("strTeam", team)
            for lid, lname in ligas:
                tabla = _get(_BASE + "/lookuptable.php?l=" + lid + "&s=" + season).get("table") or []
                for row in tabla:
                    if row.get("idTeam") == tid:
                        r = int(row.get("intRank"))
                        pts = row.get("intPoints")
                        if r == 1:
                            return name + " es el lider de " + lname + " con " + str(pts) + " puntos."
                        return name + " va en el puesto " + str(r) + " de " + lname + " con " + str(pts) + " puntos."
            return name + " no aparece en la clasificacion ahora mismo."
        # sin equipo: top 5 de La Liga
        tabla = _get(_BASE + "/lookuptable.php?l=4335&s=" + season).get("table") or []
        if not tabla:
            return "No tengo la clasificacion ahora mismo."
        partes = []
        for row in tabla[:5]:
            r = int(row.get("intRank"))
            partes.append(_ORD.get(r, str(r)) + " " + row.get("strTeam") + " con " + str(row.get("intPoints")))
        return "En La Liga va " + ", ".join(partes) + " puntos."
    except Exception:
        return "No he podido consultar la clasificacion."


def football_speech(query: str = "") -> str:
    q = (query or "").lower()
    team = _find_team(q)
    if _TABLE_RE.search(q):
        return _standings_speech(team)
    if _RESULT_RE.search(q):
        return _result_speech(team) if team else "De que equipo quieres el resultado?"
    if team:
        return _team_speech(team)
    return _today_matches()
