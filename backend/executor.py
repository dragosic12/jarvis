"""
Ejecutor de acciones: recibe la intencion parseada y ejecuta la accion correspondiente.
"""

import os
import json
import subprocess
import webbrowser
import urllib.parse
from database import get_db


def _infra(key, default):
    """Lee infraestructura local (host del PC, etc.) de .infra.json (no versionado)."""
    try:
        p = os.path.join(os.path.dirname(__file__), ".infra.json")
        return json.load(open(p)).get(key, default)
    except Exception:
        return default


# Host SSH del PC de sobremesa (usuario@ip). El valor real vive en .infra.json.
_PC_HOST = _infra("pc_host", "user@192.168.1.50")


def execute_action(intent: dict, target_platform: str = "linux") -> dict:
    """
    Ejecuta la accion asociada al intent.
    target_platform: "linux" (servidor) o "windows" (remoto)
    Devuelve: {"success": bool, "message": str, "data": any}
    """
    if not intent.get("matched"):
        return {"success": False, "message": intent.get("error", "Comando no reconocido"), "data": None}

    action_type = intent["action_type"]
    action_value = intent["action_value"]
    query = intent.get("query")

    # Apagar el ordenador es destructivo: pedir confirmacion en pantalla
    if intent.get("category") == "apagar" and action_type == "server_cmd":
        return {
            "success": True,
            "message": "Apagar el ordenador — requiere confirmacion",
            "data": {
                "needs_confirm": True,
                "action": "apagar el ordenador",
                "command": action_value,
            },
        }

    try:
        if action_type == "url":
            return _handle_url(action_value, target_platform)

        elif action_type in ("time", "say"):
            return {"success": True, "message": action_value,
                    "data": {"type": "spoken_response", "text": action_value}}

        elif action_type == "usage":
            from claude_usage import usage_speech
            txt = usage_speech()
            return {"success": True, "message": txt,
                    "data": {"type": "spoken_response", "text": txt}}

        elif action_type == "weather":
            from weather import weather_speech
            txt = weather_speech()
            return {"success": True, "message": txt,
                    "data": {"type": "spoken_response", "text": txt}}

        elif action_type == "football":
            from football import football_speech
            txt = football_speech(intent.get("query") or intent.get("raw_text") or "")
            return {"success": True, "message": txt,
                    "data": {"type": "spoken_response", "text": txt}}

        elif action_type == "finance":
            from finance import finance_speech
            txt = finance_speech(intent.get("query") or intent.get("raw_text") or "")
            return {"success": True, "message": txt,
                    "data": {"type": "spoken_response", "text": txt}}

        elif action_type == "news":
            from news import news_speech
            txt = news_speech(intent.get("query") or intent.get("raw_text") or "")
            return {"success": True, "message": txt,
                    "data": {"type": "spoken_response", "text": txt}}

        elif action_type == "server_status":
            from sysadmin import server_status_speech
            txt = server_status_speech()
            return {"success": True, "message": txt,
                    "data": {"type": "spoken_response", "text": txt}}

        elif action_type == "uptime_check":
            from sysadmin import uptime_check_speech
            txt = uptime_check_speech(intent.get("query") or "")
            return {"success": True, "message": txt,
                    "data": {"type": "spoken_response", "text": txt}}

        elif action_type == "devtools":
            from sysadmin import devtools_speech
            txt = devtools_speech(intent.get("raw_text") or intent.get("query") or "")
            return {"success": True, "message": txt,
                    "data": {"type": "spoken_response", "text": txt}}

        elif action_type == "briefing":
            txt = _handle_briefing()
            return {"success": True, "message": txt,
                    "data": {"type": "spoken_response", "text": txt}}

        elif action_type == "translate":
            from translate import translate as _tr, VOICE_BY_CODE
            try:
                txt = _tr(action_value, query)
            except Exception:
                m = "No he podido traducir ahora mismo."
                return {"success": False, "message": m,
                        "data": {"type": "spoken_response", "text": m}}
            voice = VOICE_BY_CODE.get(query, "es-ES-AlvaroNeural")
            return {"success": True, "message": txt,
                    "data": {"type": "spoken_response", "text": txt, "voice": voice}}

        elif action_type == "claude_chat":
            return _handle_claude_chat(action_value)

        elif action_type == "claude_agent":
            return _handle_claude_agent(action_value)

        elif action_type == "pc_open":
            return _handle_pc_open(action_value)

        elif action_type == "pc_ctrl":
            return _handle_pc_ctrl(action_value)

        elif action_type == "pc_type":
            return _handle_pc_type(action_value)

        elif action_type == "pc_shot":
            return _handle_pc_shot()

        elif action_type == "pc_clip_set":
            return _handle_pc_clip_set(action_value)

        elif action_type == "pc_clip_get":
            return _handle_pc_clip_get()

        elif action_type == "pc_read_screen":
            return _handle_pc_read_screen()

        elif action_type == "chat_reset":
            from gemini import reset_chat
            reset_chat()
            m = "Vale, tema nuevo. Dime."
            return {"success": True, "message": m, "data": {"type": "spoken_response", "text": m}}

        elif action_type == "list":
            return _handle_list(action_value)

        elif action_type == "say":
            return {"success": True, "message": action_value,
                    "data": {"type": "spoken_response", "text": action_value}}

        elif action_type == "search":
            return _handle_search(action_value, query, target_platform)

        elif action_type == "shell":
            return _handle_shell(action_value, target_platform)

        elif action_type == "server_cmd":
            return _handle_server_cmd(action_value)

        elif action_type == "system":
            return _handle_system(action_value, target_platform)

        elif action_type == "claude":
            return _handle_claude(action_value)

        elif action_type == "device":
            return _handle_device(action_value)

        elif action_type == "question":
            return _handle_question(action_value)

        else:
            return {"success": False, "message": f"Tipo de accion desconocido: {action_type}", "data": None}

    except Exception as e:
        return {"success": False, "message": f"Error ejecutando: {str(e)}", "data": None}
    finally:
        _log_execution(intent, action_type)


def _handle_url(url: str, platform: str) -> dict:
    if platform == "windows":
        return {
            "success": True,
            "message": f"Abriendo {url}",
            "data": {"type": "open_url", "url": url},
            "remote_action": True,
        }
    # En el servidor, devolver la URL para que el frontend la abra
    return {
        "success": True,
        "message": f"Abriendo {url}",
        "data": {"type": "open_url", "url": url},
    }


def _handle_search(url_template: str, query: str, platform: str) -> dict:
    if not query:
        return {"success": False, "message": "No se especifico que buscar", "data": None}
    # Esquemas de app (spotify:, vnd.youtube:, intent:) quieren %20; http quiere +
    if url_template.startswith("http"):
        q = urllib.parse.quote_plus(query)
    else:
        q = urllib.parse.quote(query, safe="")
    url = url_template.replace("{query}", q)
    return {
        "success": True,
        "message": f"Buscando: {query}",
        "data": {"type": "open_url", "url": url},
    }


def _handle_shell(cmd: str, platform: str) -> dict:
    if platform == "windows":
        return {
            "success": True,
            "message": f"Ejecutando en Windows: {cmd}",
            "data": {"type": "shell_cmd", "command": cmd},
            "remote_action": True,
        }
    # Ejecutar en servidor Linux
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=15
        )
        return {
            "success": result.returncode == 0,
            "message": f"Ejecutado: {cmd}",
            "data": {"stdout": result.stdout, "stderr": result.stderr},
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"Timeout ejecutando: {cmd}", "data": None}


def _handle_server_cmd(cmd: str) -> dict:
    """Ejecutar comando en el servidor Linux."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        output = result.stdout or result.stderr
        return {
            "success": result.returncode == 0,
            "message": output.strip() if output else "Ejecutado sin salida",
            "data": {"stdout": result.stdout, "stderr": result.stderr, "command": cmd},
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"Timeout: {cmd}", "data": None}


def _handle_system(action: str, platform: str) -> dict:
    """Acciones de sistema: suspender, apagar, reiniciar, bloquear."""
    cmds = {
        "linux": {
            "suspend": "systemctl suspend",
            "shutdown": "shutdown -h now",
            "reboot": "reboot",
            "lock": "loginctl lock-session",
        },
        "windows": {
            "suspend": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
            "shutdown": "shutdown /s /t 5",
            "reboot": "shutdown /r /t 5",
            "lock": "rundll32.exe user32.dll,LockWorkStation",
        }
    }

    if platform == "windows":
        cmd = cmds["windows"].get(action)
        return {
            "success": True,
            "message": f"Enviando comando sistema a Windows: {action}",
            "data": {"type": "shell_cmd", "command": cmd},
            "remote_action": True,
        }

    cmd = cmds["linux"].get(action)
    if not cmd:
        return {"success": False, "message": f"Accion de sistema desconocida: {action}", "data": None}

    # Requiere confirmacion para acciones destructivas
    return {
        "success": True,
        "message": f"Accion de sistema: {action}",
        "data": {"type": "system_action", "action": action, "command": cmd, "needs_confirm": True},
    }


def _handle_claude_chat(prompt: str) -> dict:
    """Conversar con Claude por voz manteniendo el HILO (recuerda contexto)."""
    import os
    script = os.path.join(os.path.dirname(__file__), "claude_chat.sh")
    try:
        r = subprocess.run([script, prompt], capture_output=True, text=True,
                           timeout=28, start_new_session=True)
        ans = (r.stdout or "").strip()
        if not ans:
            ans = "No he podido responder ahora mismo."
    except subprocess.TimeoutExpired:
        ans = "Claude ha tardado demasiado."
    return {"success": True, "message": ans, "data": {"type": "spoken_response", "text": ans}}


def _handle_claude_agent(task: str) -> dict:
    """Lanzar a Claude como AGENTE (hace tareas en el repo). Fire-and-forget."""
    import os
    script = os.path.join(os.path.dirname(__file__), "claude_agent.sh")
    try:
        subprocess.Popen([script, task], start_new_session=True)
    except Exception:
        pass
    msg = "Vale, se lo digo a Claude. Se pone con ello."
    return {"success": True, "message": msg, "data": {"type": "spoken_response", "text": msg}}


def _pc_target_to_url(target: str) -> str:
    from urllib.parse import quote_plus
    t = target.lower().strip()
    known = {"youtube": "https://youtube.com", "spotify": "https://open.spotify.com",
             "gmail": "https://mail.google.com", "whatsapp": "https://web.whatsapp.com",
             "netflix": "https://netflix.com", "instagram": "https://instagram.com",
             "twitch": "https://twitch.tv", "chatgpt": "https://chatgpt.com",
             "claude": "https://claude.ai", "maps": "https://maps.google.com",
             "amazon": "https://amazon.es", "twitter": "https://x.com", "github": "https://github.com"}
    for k, v in known.items():
        if k in t:
            return v
    first = t.split()[0] if t.split() else t
    if first.startswith("http"):
        return target
    if "." in first and " " not in t:
        return "https://" + t
    return "https://www.google.com/search?q=" + quote_plus(target)


def _handle_pc_open(target: str) -> dict:
    """Abrir una web/app en el sobremesa Windows por SSH (Start-Process)."""
    url = _pc_target_to_url(target)
    try:
        # Por la sesion interactiva, para que se abra en la pantalla que ve el usuario
        _pc_run_interactive("Start-Process '" + url.replace("'", "''") + "'")
        msg = f"Abriendo {target} en el ordenador."
    except Exception:
        msg = "No he podido abrirlo en el ordenador. Comprueba que esta encendido."
    return {"success": True, "message": msg, "data": {"type": "spoken_response", "text": msg}}


# --- Control del sobremesa: volumen, media, energia, captura ---
# Inyecta teclas multimedia reales con keybd_event (P/Invoke); SendKeys NO sirve
# para teclas de volumen/media (escribiria caracteres).
_KBD_DEF = ('$k=Add-Type -MemberDefinition '
            "'[DllImport(\"user32.dll\")] public static extern void keybd_event(byte b,byte s,uint f,int e);'"
            ' -Name Kbd -Namespace Win32 -PassThru;')


def _vk(code: str, times: int = 1) -> str:
    tap = f"$k::keybd_event({code},0,0,0); $k::keybd_event({code},0,2,0)"
    if times > 1:
        return _KBD_DEF + f" 1..{times} | ForEach-Object {{ {tap} }}"
    return _KBD_DEF + " " + tap


_PC_SCREENSHOT = (
    "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
    "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen; "
    "$bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height); "
    "$g=[System.Drawing.Graphics]::FromImage($bmp); "
    "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); "
    "$p=Join-Path $env:USERPROFILE ('Pictures\\jarvis_'+(Get-Date -Format yyyyMMdd_HHmmss)+'.png'); "
    "$bmp.Save($p); $g.Dispose(); $bmp.Dispose()"
)

_PC_CMDS = {
    "vol_up":    _vk("0xAF", 5),   # VK_VOLUME_UP
    "vol_down":  _vk("0xAE", 5),   # VK_VOLUME_DOWN
    "mute":      _vk("0xAD"),      # VK_VOLUME_MUTE
    "playpause": _vk("0xB3"),      # VK_MEDIA_PLAY_PAUSE
    "next":      _vk("0xB0"),      # VK_MEDIA_NEXT_TRACK
    "prev":      _vk("0xB1"),      # VK_MEDIA_PREV_TRACK
    "lock":      "rundll32.exe user32.dll,LockWorkStation",
    "shutdown":  "shutdown /s /t 5",
    "reboot":    "shutdown /r /t 5",
    "suspend":   "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
    "screenshot": _PC_SCREENSHOT,
}

_PC_SAY = {
    "vol_up": "Subo el volumen del ordenador.",
    "vol_down": "Bajo el volumen del ordenador.",
    "mute": "Silencio en el ordenador.",
    "playpause": "Hecho.",
    "next": "Siguiente cancion.",
    "prev": "Cancion anterior.",
    "lock": "Bloqueo el ordenador.",
    "shutdown": "Apagando el ordenador.",
    "reboot": "Reiniciando el ordenador.",
    "suspend": "Suspendiendo el ordenador.",
    "screenshot": "Captura guardada en el ordenador.",
}


def _pc_run(ps_cmd: str, timeout: int = 15):
    """Ejecuta PowerShell en el sobremesa por SSH via -EncodedCommand (a prueba de
    comillas y caracteres especiales)."""
    import base64
    enc = base64.b64encode(ps_cmd.encode("utf-16-le")).decode()
    return subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
         _PC_HOST, "powershell", "-NoProfile", "-EncodedCommand", enc],
        capture_output=True, text=True, errors="replace", timeout=timeout,
    )


# El SSH entra en la sesion 0 (sin escritorio visible), asi que SendKeys, captura
# de pantalla y abrir apps NO llegan a la pantalla del usuario. Solucion: una tarea
# programada (JarvisRun) que corre en la sesion INTERACTIVA del usuario; escribimos
# el comando en un .ps1 y la disparamos.
_pc_task_ready = False


def _pc_ensure_task():
    global _pc_task_ready
    if _pc_task_ready:
        return
    # RunLevel Limited (integridad NORMAL): por UIPI de Windows, un proceso elevado
    # no puede enviar teclas (SendKeys/keybd_event) a ventanas normales. Registramos
    # siempre con -Force para corregir una tarea previa que estuviera elevada.
    ps = (
        "$p=Join-Path $env:USERPROFILE 'jarvis_cmd.ps1';"
        "$a=New-ScheduledTaskAction -Execute 'powershell.exe' "
        "-Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"'+$p+'\"');"
        "$pr=New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited;"
        "Register-ScheduledTask -TaskName 'JarvisRun' -Action $a -Principal $pr -Force | Out-Null"
    )
    try:
        _pc_run(ps, timeout=20)
        _pc_task_ready = True
    except Exception:
        pass


def _pc_run_interactive(ps_cmd: str, timeout: int = 15):
    """Ejecuta PowerShell en la sesion interactiva del usuario (para SendKeys,
    captura, abrir apps visibles). Escribe el comando en jarvis_cmd.ps1 y lanza la tarea."""
    import base64
    _pc_ensure_task()
    b64 = base64.b64encode(ps_cmd.encode("utf-8")).decode()
    writer = ("$c=[System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + b64 + "')); "
              "Set-Content -Path (Join-Path $env:USERPROFILE 'jarvis_cmd.ps1') -Value $c -Encoding UTF8")
    _pc_run(writer, timeout=timeout)
    return _pc_run("Start-ScheduledTask -TaskName 'JarvisRun'", timeout=timeout)


def _handle_pc_ctrl(action: str) -> dict:
    """Volumen / media / apagar-bloquear-suspender / captura en el sobremesa."""
    cmd = _PC_CMDS.get(action)
    if not cmd:
        return {"success": False, "message": f"Accion de PC desconocida: {action}", "data": None}
    try:
        _pc_run_interactive(cmd)
        msg = _PC_SAY.get(action, "Hecho en el ordenador.")
    except Exception:
        msg = "No he podido. Comprueba que el ordenador esta encendido."
    return {"success": True, "message": msg, "data": {"type": "spoken_response", "text": msg}}


def _sendkeys_escape(s: str) -> str:
    """Escapa los caracteres especiales de SendKeys (+^%~(){}[]) envolviendolos."""
    special = set("+^%~(){}[]")
    return "".join("{" + c + "}" if c in special else c for c in s)


def _handle_pc_type(text: str) -> dict:
    """Teclea texto en la ventana activa del sobremesa (dictado por voz)."""
    if not text or not text.strip():
        return {"success": False, "message": "No he entendido que escribir.", "data": None}
    esc = _sendkeys_escape(text.strip()).replace("'", "''")
    cmd = ("$w=New-Object -ComObject WScript.Shell; Start-Sleep -Milliseconds 250; "
           "$w.SendKeys('" + esc + "')")
    try:
        _pc_run_interactive(cmd)
        msg = "Escrito en el ordenador."
    except Exception:
        msg = "No he podido escribir en el ordenador."
    return {"success": True, "message": msg, "data": {"type": "spoken_response", "text": msg}}


_PC_SCREENSHOT_HOME = (
    "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
    "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen; "
    "$bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height); "
    "$g=[System.Drawing.Graphics]::FromImage($bmp); "
    "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); "
    "$p=Join-Path $env:USERPROFILE 'jarvis_shot.png'; "
    "$bmp.Save($p); $g.Dispose(); $bmp.Dispose()"
)


def _handle_pc_shot() -> dict:
    """Captura la pantalla del sobremesa (en la sesion interactiva), la trae al
    servidor y la abre en el movil."""
    import time, os
    try:
        # Borrar la captura anterior para no traer una vieja, y disparar la nueva
        _pc_run("Remove-Item -Force \"$env:USERPROFILE\\jarvis_shot.png\" -ErrorAction SilentlyContinue")
        _pc_run_interactive(_PC_SCREENSHOT_HOME, timeout=20)
        fname = f"pc_shot_{int(time.time())}.png"
        dest = f"/var/www/jarvis/{fname}"
        # La tarea es asincrona: sondear hasta que aparezca la captura real
        for _ in range(9):
            time.sleep(1)
            r = subprocess.run(
                ["scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                 f"{_PC_HOST}:jarvis_shot.png", dest],
                capture_output=True, text=True, errors="replace", timeout=15,
            )
            if r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 5000:
                try:
                    os.chmod(dest, 0o644)  # que el servidor web pueda servirla
                except Exception:
                    pass
                return {"success": True, "message": "Aqui tienes la captura del ordenador.",
                        "data": {"type": "open_url", "url": f"https://jarvis.swapcar.app/{fname}"}}
        m = "Hice la captura pero no pude traerla al movil."
        return {"success": True, "message": m, "data": {"type": "spoken_response", "text": m}}
    except Exception:
        m = "No he podido hacer la captura del ordenador."
        return {"success": True, "message": m, "data": {"type": "spoken_response", "text": m}}


def _handle_pc_clip_set(text: str) -> dict:
    """Copia texto al portapapeles del sobremesa (sesion interactiva)."""
    if not text or not text.strip():
        return {"success": False, "message": "No he entendido que copiar.", "data": None}
    esc = text.strip().replace("'", "''")
    try:
        _pc_run_interactive("Set-Clipboard -Value '" + esc + "'")
        m = "Copiado al ordenador."
    except Exception:
        m = "No he podido copiar al ordenador."
    return {"success": True, "message": m, "data": {"type": "spoken_response", "text": m}}


def _handle_pc_clip_get() -> dict:
    """Lee el portapapeles del sobremesa y lo dice en alto."""
    import time, os
    try:
        _pc_run("Remove-Item -Force \"$env:USERPROFILE\\jarvis_clip.txt\" -ErrorAction SilentlyContinue")
        _pc_run_interactive("Get-Clipboard | Out-File -Encoding UTF8 \"$env:USERPROFILE\\jarvis_clip.txt\"")
        for _ in range(8):
            time.sleep(1)
            r = subprocess.run(
                ["scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                 f"{_PC_HOST}:jarvis_clip.txt", "/tmp/jarvis_clip.txt"],
                capture_output=True, text=True, errors="replace", timeout=15)
            if r.returncode == 0 and os.path.exists("/tmp/jarvis_clip.txt"):
                txt = open("/tmp/jarvis_clip.txt", encoding="utf-8-sig", errors="replace").read().strip()
                m = ("En el portapapeles del ordenador pone: " + txt[:400]) if txt \
                    else "El portapapeles del ordenador esta vacio."
                return {"success": True, "message": m, "data": {"type": "spoken_response", "text": m}}
        m = "No he podido leer el portapapeles del ordenador."
    except Exception:
        m = "No he podido leer el portapapeles del ordenador."
    return {"success": True, "message": m, "data": {"type": "spoken_response", "text": m}}


def _handle_pc_read_screen() -> dict:
    """Captura la pantalla del sobremesa y la lee/resume en alto (vision de Gemini)."""
    import time, os
    try:
        _pc_run("Remove-Item -Force \"$env:USERPROFILE\\jarvis_shot.png\" -ErrorAction SilentlyContinue")
        _pc_run_interactive(_PC_SCREENSHOT_HOME, timeout=20)
        img = None
        for _ in range(9):
            time.sleep(1)
            r = subprocess.run(
                ["scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                 f"{_PC_HOST}:jarvis_shot.png", "/tmp/jarvis_read.png"],
                capture_output=True, text=True, errors="replace", timeout=15)
            if (r.returncode == 0 and os.path.exists("/tmp/jarvis_read.png")
                    and os.path.getsize("/tmp/jarvis_read.png") > 5000):
                img = open("/tmp/jarvis_read.png", "rb").read()
                break
        if not img:
            m = "No he podido capturar la pantalla del ordenador."
            return {"success": True, "message": m, "data": {"type": "spoken_response", "text": m}}
        from gemini import read_image
        m = read_image(img, "Resume en espanol, breve y para leer en voz alta (maximo 3 frases), "
                            "lo principal que se ve en esta pantalla de ordenador.")
        if not m:
            m = "No he podido leer la pantalla."
        return {"success": True, "message": m, "data": {"type": "spoken_response", "text": m}}
    except Exception:
        m = "No he podido leer la pantalla del ordenador."
        return {"success": True, "message": m, "data": {"type": "spoken_response", "text": m}}


def _handle_device(action: str) -> dict:
    """Acciones de dispositivo movil: camara, linterna, etc."""
    return {
        "success": True,
        "message": f"Accion de dispositivo: {action}",
        "data": {"type": "device_action", "action": action},
    }


def _handle_briefing() -> str:
    """Saludo segun la hora + hora + tiempo + uso de Claude, en una frase hablada."""
    import datetime
    now = datetime.datetime.now()
    h, m = now.hour, now.minute
    saludo = "Buenos dias" if 5 <= h < 12 else ("Buenas tardes" if 12 <= h < 21 else "Buenas noches")
    hora = f"Son las {h}" + (" en punto" if m == 0 else f" y {m}")
    parts = [f"{saludo}. {hora}."]
    try:
        from weather import weather_now
        parts.append("Ahora mismo " + weather_now() + ".")
    except Exception:
        pass
    try:
        from claude_usage import fetch_usage
        d = fetch_usage()
        w = max(0, min(100, round(100 - (d.get("seven_day", {}).get("utilization") or 0))))
        parts.append(f"Y te queda el {w} por ciento de Claude esta semana.")
    except Exception:
        pass
    try:
        from football import _today_matches
        fb = _today_matches()
        if fb.startswith("Hoy juegan"):
            parts.append(fb)
    except Exception:
        pass
    try:
        from news import brief as _nbrief
        nb = _nbrief(2)
        if nb:
            parts.append(nb)
    except Exception:
        pass
    try:
        from sysadmin import server_brief
        parts.append(server_brief())
    except Exception:
        pass
    return " ".join(parts)


def _handle_list(spec: str) -> dict:
    """Notas y lista de la compra. spec = 'op:lista:item' (op: add/read/clear/remove)."""
    from lists import add_item, read_items, clear_list, remove_item
    parts = spec.split(":", 2)
    op = parts[0]
    lst = parts[1] if len(parts) > 1 else ""
    item = parts[2] if len(parts) > 2 else ""
    label = "la compra" if lst == "compra" else "las notas"
    if op == "add":
        add_item(lst, item)
        m = f"Anadido a {label}: {item}." if lst == "compra" else f"Apuntado: {item}."
    elif op == "read":
        items = read_items(lst)
        if not items:
            m = f"No tienes nada en {label}."
        elif lst == "compra":
            m = "En la compra tienes: " + ", ".join(items) + "."
        else:
            m = "Tus notas: " + ". ".join(items) + "."
    elif op == "clear":
        n = clear_list(lst)
        m = f"He vaciado {label}." if n else f"No habia nada en {label}."
    elif op == "remove":
        n = remove_item(lst, item)
        m = f"Quitado de {label}: {item}." if n else f"No encontre {item} en {label}."
    else:
        m = "No he entendido lo de la lista."
    return {"success": True, "message": m, "data": {"type": "spoken_response", "text": m}}


def _handle_question(question: str) -> dict:
    """Responder preguntas. Primero Gemini (libera el limite de Claude); si falla,
    fallback a Claude CLI con Haiku (OAuth Pro)."""
    import os
    # 1) Gemini (rapido y no consume el limite de Claude)
    try:
        from gemini import ask_gemini
        ans = ask_gemini(question)
        if ans:
            return {"success": True, "message": ans,
                    "data": {"type": "spoken_response", "text": ans, "question": question}}
    except Exception:
        pass
    # 2) Fallback: Claude CLI (Haiku)
    env = {k: v for k, v in os.environ.items()}
    env.pop("ANTHROPIC_API_KEY", None)  # Forzar OAuth, no API key
    env["TERM"] = "dumb"
    try:
        script_path = os.path.join(os.path.dirname(__file__), "claude_ask.sh")
        prompt = f"Responde breve y conciso en espanol (2-3 frases, sin emojis, sin markdown): {question}"
        result = subprocess.run(
            [script_path, prompt],
            capture_output=True, text=True, timeout=30, env=env,
            start_new_session=True,
        )
        answer = result.stdout.strip()
        if result.returncode != 0 or not answer:
            answer = "No pude obtener una respuesta ahora."
        # Claude puede estar al limite: no soltar mensajes de tokens/limite al usuario
        low = answer.lower()
        if any(w in low for w in ("limit", "token", "credit", "saldo", "cuota", "quota", "usage")):
            answer = "Ahora mismo no puedo responder eso. Intentalo otra vez en un momento."
        return {
            "success": result.returncode == 0 and bool(result.stdout.strip()),
            "message": answer,
            "data": {"type": "spoken_response", "text": answer, "question": question},
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "La respuesta tardo demasiado.", "data": {"type": "spoken_response", "text": "La respuesta tardó demasiado."}}
    except FileNotFoundError:
        return {"success": False, "message": "Claude CLI no disponible.", "data": {"type": "info", "text": "Claude CLI no esta instalado."}}


def _handle_claude(action: str) -> dict:
    """Interaccion con Claude CLI."""
    if action == "new":
        return {
            "success": True,
            "message": "Para iniciar nueva conversacion Claude, usa el terminal",
            "data": {"type": "info", "text": "Claude CLI: claude (nueva sesion)"},
        }
    elif action == "continue":
        return {
            "success": True,
            "message": "Para continuar conversacion Claude, usa: claude --continue",
            "data": {"type": "info", "text": "Claude CLI: claude --continue"},
        }
    return {"success": False, "message": f"Accion Claude desconocida: {action}", "data": None}


def _log_execution(intent: dict, action_type: str):
    """Guarda log de ejecucion."""
    try:
        db = get_db()
        db.execute(
            "INSERT INTO command_log (transcript, matched_command_id, category, action_executed, result, success) VALUES (?, ?, ?, ?, ?, ?)",
            (
                intent.get("raw_text"),
                intent.get("command_id"),
                intent.get("category"),
                f"{action_type}:{intent.get('action_value', '')}",
                "ok",
                1 if intent.get("matched") else 0,
            )
        )
        db.commit()
        db.close()
    except Exception:
        pass
