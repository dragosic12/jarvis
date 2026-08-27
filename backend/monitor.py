"""Monitor de draleserver: avisa por Telegram si una app pm2 se cae, el disco se
llena o un servicio no responde. Cron cada 5 min. Solo avisa en CAMBIOS de estado."""
import os
import json
import shutil
import subprocess
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, ".alert_state.json")
ENVF = os.path.join(HERE, ".alert.env")

DISK_WARN = 90
SERVICES = {
    "Immich": "http://localhost:2283/api/server/ping",
    "lagatta.es": "https://lagatta.es",
    "jarvis web": "https://jarvis.swapcar.app/version.json",
}


def _env():
    d = {}
    try:
        for line in open(ENVF):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k] = v.strip()
    except Exception:
        pass
    return d


def _run(cmd, t=10):
    try:
        return subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception:
        return ""


def _http_ok(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "JarvisMon/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.getcode() < 500
    except Exception:
        return False


def problems():
    probs = {}
    try:
        apps = json.loads(_run("pm2 jlist", 8) or "[]")
        for a in apps:
            st = a.get("pm2_env", {}).get("status")
            if st != "online":
                probs["pm2:" + a.get("name", "?")] = "La app " + a.get("name", "?") + " esta " + str(st)
    except Exception:
        pass
    try:
        du = shutil.disk_usage("/")
        pct = int(du.used / du.total * 100)
        if pct >= DISK_WARN:
            probs["disk"] = "Disco al " + str(pct) + " por ciento"
    except Exception:
        pass
    for name, url in SERVICES.items():
        if not _http_ok(url):
            probs["svc:" + name] = name + " no responde"
    return probs


def tg(msg):
    e = _env()
    tok, chat = e.get("TELEGRAM_BOT_TOKEN"), e.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
    try:
        urllib.request.urlopen("https://api.telegram.org/bot" + tok + "/sendMessage", data=data, timeout=10)
        return True
    except Exception:
        return False


def main():
    cur = problems()
    try:
        prev = json.load(open(STATE))
    except Exception:
        prev = {}
    nuevos = [v for k, v in cur.items() if k not in prev]
    recuperados = [prev[k] for k in prev if k not in cur]
    if nuevos:
        tg("⚠️ Jarvis - problema en draleserver:\n- " + "\n- ".join(nuevos))
    if recuperados:
        tg("✅ Jarvis - recuperado:\n- " + "\n- ".join(recuperados))
    json.dump(cur, open(STATE, "w"))


if __name__ == "__main__":
    main()
