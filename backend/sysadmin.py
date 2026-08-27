"""Herramientas de sysadmin por voz (el backend corre DENTRO de draleserver):
estado del servidor, comprobar si un sitio esta arriba, y utilidades de dev."""
import os
import re
import time
import uuid
import base64
import hashlib
import secrets
import string
import shutil
import subprocess
import urllib.request

# ---------------------------------------------------------------- helpers ----

def _run(cmd, timeout=8):
    """Ejecuta en un shell de login (para tener el PATH de pm2/docker)."""
    try:
        r = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def _http_get(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ----------------------------------------------------- estado del servidor ----

def server_status_speech() -> str:
    partes = []
    # uptime
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        dias = int(up // 86400)
        horas = int((up % 86400) // 3600)
        if dias:
            partes.append("Encendido %d dias y %d horas" % (dias, horas))
        else:
            partes.append("Encendido %d horas" % horas)
    except Exception:
        pass
    # CPU (load / nucleos)
    try:
        load1 = os.getloadavg()[0]
        ncpu = os.cpu_count() or 1
        partes.append("CPU al %d por ciento" % min(100, int(load1 / ncpu * 100)))
    except Exception:
        pass
    # RAM
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                mem[k] = int(v.strip().split()[0])  # kB
        total = mem["MemTotal"] / 1048576.0
        avail = mem.get("MemAvailable", mem.get("MemFree", 0)) / 1048576.0
        used = total - avail
        partes.append("memoria %.1f de %.0f gigas" % (used, total))
    except Exception:
        pass
    # disco
    try:
        du = shutil.disk_usage("/")
        pct = int(du.used / du.total * 100)
        partes.append("disco al %d por ciento" % pct)
    except Exception:
        pass
    # temperatura
    try:
        for z in ("/sys/class/thermal/thermal_zone0/temp",):
            if os.path.exists(z):
                t = int(open(z).read().strip()) / 1000.0
                partes.append("temperatura %d grados" % int(t))
                break
    except Exception:
        pass
    # pm2
    try:
        import json as _json
        out = _run("pm2 jlist", 8)
        apps = _json.loads(out) if out else []
        online = sum(1 for a in apps if a.get("pm2_env", {}).get("status") == "online")
        caidas = len(apps) - online
        s = "%d apps activas" % online
        if caidas:
            s += " y %d caidas" % caidas
        partes.append(s)
    except Exception:
        pass
    # docker
    try:
        run = _run("docker ps -q | wc -l", 8)
        if run.isdigit():
            partes.append("%s contenedores docker en marcha" % run)
    except Exception:
        pass
    if not partes:
        return "No he podido leer el estado del servidor."
    return "Servidor: " + ". ".join(partes) + "."


def server_brief() -> str:
    """Una linea para el 'buenos dias': OK o aviso si algo va mal."""
    avisos = []
    try:
        du = shutil.disk_usage("/")
        pct = int(du.used / du.total * 100)
        if pct >= 88:
            avisos.append("disco al %d por ciento" % pct)
    except Exception:
        pass
    try:
        import json as _json
        apps = _json.loads(_run("pm2 jlist", 8) or "[]")
        caidas = [a.get("name") for a in apps if a.get("pm2_env", {}).get("status") != "online"]
        if caidas:
            avisos.append("%d apps caidas" % len(caidas))
    except Exception:
        pass
    if avisos:
        return "Atencion en el servidor: " + " y ".join(avisos) + "."
    return "El servidor va bien."


# ----------------------------------------------------- esta arriba? ----------

# nombre hablado -> URL a comprobar
_SERVICIOS = {
    "lagatta": "https://lagatta.es",
    "la gatta": "https://lagatta.es",
    "jarvis": "https://jarvis.swapcar.app/version.json",
    "immich": "http://localhost:2283/api/server/ping",
    "fotos": "http://localhost:2283/api/server/ping",
    "finanzas": "http://localhost:4000",
    "swapcar": "https://swapcar.app",
    "petunia": "http://localhost:8092",
}


def uptime_check_speech(query: str = "") -> str:
    q = (query or "").lower()
    url, nombre = None, None
    for k, u in _SERVICIOS.items():
        if k in q:
            url, nombre = u, k
            break
    if not url:
        m = re.search(r"\b([a-z0-9\-]+\.(?:es|com|app|net|org|io|dev))\b", q)
        if m:
            nombre = m.group(1)
            url = "https://" + nombre
    if not url:
        return "Dime que web o servicio quieres comprobar."
    try:
        import urllib.request as _u
        req = _u.Request(url, headers={"User-Agent": "Jarvis/1.0"})
        with _u.urlopen(req, timeout=8) as r:
            code = r.getcode()
        return nombre + " responde correctamente." if code < 400 else \
            nombre + " responde con error " + str(code) + "."
    except Exception:
        return nombre + " no responde. Puede estar caido."


# ----------------------------------------------------- utilidades dev --------

def _password(n=14):
    alfa = string.ascii_letters + string.digits + "@#$%&*"
    return "".join(secrets.choice(alfa) for _ in range(n))


def devtools_speech(raw: str = "") -> str:
    t = raw or ""
    low = t.lower()
    if re.search(r"contrasena|contraseña|password|clave segura", low):
        return "Contrasena: " + _password()
    if re.search(r"\buuid\b|identificador unico", low):
        return "UUID: " + str(uuid.uuid4())
    if re.search(r"ip publica|mi ip|direccion ip|cual es mi ip", low):
        try:
            return "La IP publica del servidor es " + _http_get("https://api.ipify.org", 6).strip() + "."
        except Exception:
            return "No he podido obtener la IP publica."
    if re.search(r"timestamp|marca de tiempo|epoch|hora unix", low):
        n = int(time.time())
        return "Timestamp actual: " + str(n) + "."
    m = re.search(r"(?:base ?64)\s+(?:de |del )?(.+)$", t, re.I)
    if m:
        return "En base64: " + base64.b64encode(m.group(1).strip().encode()).decode()
    m = re.search(r"\b(md5|sha1|sha256|hash)\b\s+(?:de |del )?(.+)$", t, re.I)
    if m:
        algo = m.group(1).lower()
        algo = "sha256" if algo == "hash" else algo
        payload = m.group(2).strip().encode()
        return algo + ": " + hashlib.new(algo, payload).hexdigest()
    return "Puedo darte contrasena, UUID, IP publica, timestamp, base64 o hash."
