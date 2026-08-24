"""Gemini para: (1) preguntas/conversacion con memoria del hilo, y (2) interprete de
intencion: cuando el parser de reglas no entiende una orden, Gemini la traduce a un
comando canonico que el parser SI ejecuta. Llamada REST directa, sin SDK."""
import os
import json
import time
import base64
import urllib.request

_MODEL = "gemini-flash-lite-latest"   # lite mas nuevo: barato, rapido, buena cuota diaria
_KEY = None
_HIST_PATH = os.path.join(os.path.dirname(__file__), ".gemini_chat.json")
_HIST_TTL = 300   # 5 min sin hablar -> se olvida el hilo (evita mezclar temas)

_SYS = ("Eres Jarvis, un asistente de voz personal. Responde en espanol, breve (1 a 3 "
        "frases por defecto), claro y directo, SIN markdown ni emojis, para leer en voz "
        "alta. Mantienes el hilo de la conversacion: si te piden ampliar da mas detalle "
        "pero sigue conciso; si preguntan de donde sale la info, di el tipo de fuente.")

_CMDS_HELP = """Ordenes que Jarvis ejecuta (traduce a UNA de estas, rellenando lo que falte):
- enciende la linterna / apaga la linterna
- sube el volumen / baja el volumen / silencio / modo vibracion / pon el volumen al 30
- sube el brillo / baja el brillo / pon el brillo al 50 / brillo al maximo
- bloquea el movil
- busca el movil
- que hora es / que tiempo hace / bateria
- pon una alarma a las HORA / temporizador de N minutos
- recuerdame TEXTO en N minutos
- dile a CONTACTO que MENSAJE
- manda un audio a CONTACTO
- abre el chat de CONTACTO
- abre APP  (youtube, spotify, whatsapp, instagram, tiktok, gmail...)
- abre APP en el ordenador
- sube el volumen del ordenador / baja el volumen del ordenador / pausa la musica del ordenador / siguiente cancion en el ordenador
- apaga el ordenador / reinicia el ordenador / suspende el ordenador / bloquea el ordenador
- escribe en el ordenador TEXTO
- copia al ordenador TEXTO / lee el portapapeles del ordenador
- lee la pantalla del ordenador
- haz una captura y mandamela
- activa el modo coche / modo conversacion
- contesta la llamada / cuelga la llamada
- aprende esta rutina / haz la rutina NOMBRE
- cuanto me queda de claude
- traduce TEXTO al IDIOMA
- anade COSA a la compra / que hay en la compra / quita COSA de la compra
- apunta que NOTA / que notas tengo
- dile a claude que TAREA  (solo tareas de programacion/agente)"""


def _load_key():
    global _KEY
    if _KEY is not None:
        return _KEY
    path = os.path.join(os.path.dirname(__file__), ".gemini_key")
    if os.path.exists(path):
        _KEY = open(path).read().strip()
    else:
        _KEY = os.getenv("GEMINI_API_KEY", "").strip()
    return _KEY


def _load_hist():
    try:
        d = json.load(open(_HIST_PATH))
        if time.time() - d.get("t", 0) < _HIST_TTL:
            return d.get("turns", [])
    except Exception:
        pass
    return []


def _save_hist(turns):
    try:
        json.dump({"t": time.time(), "turns": turns[-12:]}, open(_HIST_PATH, "w"))
    except Exception:
        pass


def reset_chat():
    try:
        os.remove(_HIST_PATH)
    except Exception:
        pass


def _gemini_call(contents, system_text, timeout=18, max_tokens=400):
    """Llamada cruda con reintentos (el modelo se satura a ratos: HTTP 503/429)."""
    key = _load_key()
    if not key:
        return ""
    body = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        # (flash-lite no sobre-piensa; sin thinkingConfig, que los modelos 3.x rechazan)
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
    }
    data = json.dumps(body).encode("utf-8")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{_MODEL}:generateContent?key={key}")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read().decode("utf-8"))
            cands = resp.get("candidates", [])
            if cands:
                parts = cands[0].get("content", {}).get("parts", [])
                txt = "".join(p.get("text", "") for p in parts).strip()
                if txt:
                    return txt
        except urllib.error.HTTPError as e:
            # 429 = cuota agotada (diaria) -> reintentar no sirve, fallar rapido
            if e.code not in (500, 503):
                return ""
        except Exception:
            pass
        time.sleep(0.6 * (attempt + 1))
    return ""


def ask_gemini(question: str, timeout: int = 18, remember: bool = True) -> str:
    """Respuesta breve en espanol (con memoria del hilo), o '' si falla."""
    if not question:
        return ""
    hist = _load_hist() if remember else []
    contents = [{"role": t["role"], "parts": [{"text": t["text"]}]} for t in hist]
    contents.append({"role": "user", "parts": [{"text": question}]})
    txt = _gemini_call(contents, _SYS, timeout=timeout)
    if txt and remember:
        hist.append({"role": "user", "text": question})
        hist.append({"role": "model", "text": txt})
        _save_hist(hist)
    return txt


def read_image(image_bytes: bytes, prompt: str, timeout: int = 25) -> str:
    """Envia una imagen a Gemini (vision) y devuelve su lectura/resumen, o ''."""
    if not image_bytes:
        return ""
    b64 = base64.b64encode(image_bytes).decode()
    contents = [{"role": "user", "parts": [
        {"text": prompt},
        {"inline_data": {"mime_type": "image/png", "data": b64}},
    ]}]
    return _gemini_call(contents, _SYS, timeout=timeout, max_tokens=400)


def smart_reply(utterance: str, contacts=None):
    """UNA sola llamada: decide si es orden o charla y responde a la vez (con memoria).
    Devuelve ('cmd', orden_canonica) si es una orden, o ('say', respuesta) si es
    charla/pregunta, o ('', '') si falla."""
    if not utterance:
        return ("", "")
    contacts_line = ("Contactos: " + ", ".join(contacts) + ".\n") if contacts else ""
    sys = (_SYS + "\n\nIMPORTANTE: si el mensaje del usuario es una ORDEN para el movil o el "
           "PC (no una pregunta ni charla), responde SOLO con 'CMD: ' seguido de la orden "
           "canonica equivalente de esta lista (rellenando contacto/app/valor) y NADA mas:\n"
           + _CMDS_HELP + "\n" + contacts_line +
           "Si es una pregunta o charla, respondela normal y breve (sin 'CMD:').")
    hist = _load_hist()
    contents = [{"role": t["role"], "parts": [{"text": t["text"]}]} for t in hist]
    contents.append({"role": "user", "parts": [{"text": utterance}]})
    txt = _gemini_call(contents, sys, max_tokens=400)
    if not txt:
        return ("", "")
    if txt.strip().upper().startswith("CMD:"):
        return ("cmd", txt.strip()[4:].strip().strip('"'))
    # Es charla/pregunta: guardar en el hilo
    hist.append({"role": "user", "text": utterance})
    hist.append({"role": "model", "text": txt})
    _save_hist(hist)
    return ("say", txt)


def interpret_command(transcript: str, contacts=None) -> str:
    """Traduce lo que dijo el usuario a una orden canonica que el parser entiende.
    Devuelve la orden, o 'PREGUNTA' si no es una orden sino charla/pregunta, o ''."""
    if not transcript:
        return ""
    contacts_line = ("Contactos: " + ", ".join(contacts) + ".\n") if contacts else ""
    sys = ("Eres el interprete de intenciones de Jarvis, un asistente de voz del movil. "
           "Traduce lo que dice el usuario (puede tener errores de transcripcion) a UNA "
           "sola orden canonica de la lista, rellenando contacto/app/valor. Responde SOLO "
           "con la orden (una linea, espanol, sin comillas ni explicacion). Si NO es una "
           "orden para el movil o el PC sino una pregunta o charla general, responde "
           "exactamente: PREGUNTA\n\n" + _CMDS_HELP)
    user = contacts_line + 'Usuario: "' + transcript + '"'
    out = _gemini_call([{"role": "user", "parts": [{"text": user}]}], sys, timeout=12, max_tokens=60)
    return out.strip().strip('"').strip()
