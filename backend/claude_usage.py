"""
Uso de la suscripcion de Claude (limite semanal + sesion de 5h).
Lee el token OAuth de ~/.claude/.credentials.json (la misma cuenta que usa el CLI
en el servidor), lo refresca si esta caducado, y consulta el endpoint que usa
Claude Code para /usage. Devuelve una frase en espanol para que Jarvis la hable.
"""
import os
import json
import time
import datetime
import urllib.request
import urllib.error

CRED = os.path.expanduser("~/.claude/.credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"   # client OAuth publico de Claude Code
UA = "claude-cli/2.1.77 (external, jarvis)"
BETA = "oauth-2025-04-20"

_DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def _load():
    with open(CRED) as f:
        return json.load(f)


def _save(data):
    tmp = CRED + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, CRED)
    try:
        os.chmod(CRED, 0o600)
    except OSError:
        pass


def _refresh(data):
    """Refresca el accessToken con el refreshToken y lo guarda (rotacion incluida)."""
    oauth = data["claudeAiOauth"]
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": oauth["refreshToken"],
        "client_id": CLIENT_ID,
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        tok = json.loads(r.read().decode())
    oauth["accessToken"] = tok["access_token"]
    if tok.get("refresh_token"):
        oauth["refreshToken"] = tok["refresh_token"]
    if tok.get("expires_in"):
        oauth["expiresAt"] = int((time.time() + tok["expires_in"]) * 1000)
    _save(data)
    return oauth["accessToken"]


def _access_token(force=False):
    data = _load()
    oauth = data["claudeAiOauth"]
    exp = oauth.get("expiresAt", 0) / 1000.0
    if force or exp < time.time() + 300:
        try:
            return _refresh(data)
        except Exception:
            pass
    return oauth["accessToken"]


def _get_usage(token):
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": BETA,
        "Content-Type": "application/json",
        "User-Agent": UA,
    })
    with urllib.request.urlopen(req, timeout=6) as r:
        return json.loads(r.read().decode())


def fetch_usage():
    try:
        return _get_usage(_access_token())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return _get_usage(_access_token(force=True))
        raise


def _reset_phrase(iso, session=False):
    if not iso:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        secs = (dt - now).total_seconds()
        local = dt.astimezone()
        if session and secs < 6 * 3600:
            mins = max(0, int(secs // 60))
            h, m = mins // 60, mins % 60
            if h and m:
                return f"en {h} hora{'s' if h != 1 else ''} y {m} minutos"
            if h:
                return f"en {h} hora{'s' if h != 1 else ''}"
            return f"en {m} minutos"
        if 0 <= secs < 24 * 3600:
            return f"hoy a las {local.strftime('%H:%M')}"
        return f"el {_DIAS[local.weekday()]} a las {local.strftime('%H:%M')}"
    except Exception:
        return ""


def _rem(u):
    return max(0, min(100, round(100 - (u or 0))))


def usage_speech():
    """Frase hablada con el % que queda del semanal y de la sesion + reinicios."""
    try:
        d = fetch_usage()
    except Exception:
        return "No he podido consultar tu uso de Claude ahora mismo."
    week = d.get("seven_day") or {}
    sess = d.get("five_hour") or {}
    w, s = _rem(week.get("utilization")), _rem(sess.get("utilization"))
    wr = _reset_phrase(week.get("resets_at"), session=False)
    sr = _reset_phrase(sess.get("resets_at"), session=True)
    p1 = f"Te queda el {w} por ciento del limite semanal de Claude"
    if wr:
        p1 += f", se reinicia {wr}"
    p2 = f"y el {s} por ciento de la sesion actual"
    if sr:
        p2 += f", se reinicia {sr}"
    return p1 + ", " + p2 + "."


if __name__ == "__main__":
    print(usage_speech())
