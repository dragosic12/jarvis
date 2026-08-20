"""Preguntas y conversacion con Gemini (asi liberamos el limite de Claude). Mantiene
un hilo corto en .gemini_chat.json para que funcionen los seguimientos ('amplia',
'de donde lo sacaste'...). Llamada REST directa, sin SDK."""
import os
import json
import time
import urllib.request

_MODEL = "gemini-2.5-flash"   # estable y con cuota (flash-latest daba 429)
_KEY = None
_HIST_PATH = os.path.join(os.path.dirname(__file__), ".gemini_chat.json")
_HIST_TTL = 300   # 5 min sin hablar -> se olvida el hilo (evita mezclar temas)

_SYS = ("Eres Jarvis, un asistente de voz personal. Responde en espanol, breve (1 a 3 "
        "frases por defecto), claro y directo, SIN markdown ni emojis, para leer en voz "
        "alta. Mantienes el hilo de la conversacion: si te piden ampliar da mas detalle "
        "pero sigue conciso; si preguntan de donde sale la info, di el tipo de fuente.")


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


def ask_gemini(question: str, timeout: int = 18, remember: bool = True) -> str:
    """Respuesta breve en espanol (con memoria del hilo), o '' si falla."""
    key = _load_key()
    if not key or not question:
        return ""
    hist = _load_hist() if remember else []
    contents = [{"role": t["role"], "parts": [{"text": t["text"]}]} for t in hist]
    contents.append({"role": "user", "parts": [{"text": question}]})
    body = {
        "system_instruction": {"parts": [{"text": _SYS}]},
        "contents": contents,
        # thinkingBudget=0: si no, el modelo se gasta los tokens 'pensando' y devuelve vacio
        "generationConfig": {"maxOutputTokens": 400, "temperature": 0.4,
                             "thinkingConfig": {"thinkingBudget": 0}},
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
                    if remember:
                        hist.append({"role": "user", "text": question})
                        hist.append({"role": "model", "text": txt})
                        _save_hist(hist)
                    return txt
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 503):   # error no transitorio
                return ""
        except Exception:
            pass
        time.sleep(0.6 * (attempt + 1))
    return ""
