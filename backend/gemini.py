"""Preguntas de conocimiento general via Gemini (asi liberamos el limite de Claude
para el agente/las tareas). Llamada REST directa, sin SDK. La clave se lee de
backend/.gemini_key (o de la variable de entorno GEMINI_API_KEY)."""
import os
import json
import urllib.request

_MODEL = "gemini-flash-latest"   # alias al ultimo flash; rapido, ideal para voz
_KEY = None


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


def ask_gemini(question: str, timeout: int = 18) -> str:
    """Devuelve una respuesta breve en espanol, o '' si falla (para hacer fallback)."""
    key = _load_key()
    if not key or not question:
        return ""
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{_MODEL}:generateContent?key={key}")
    sys = ("Eres Jarvis, un asistente de voz personal. Responde en espanol, muy breve "
           "(1 a 3 frases), claro y directo, SIN markdown, SIN emojis, pensado para leer "
           "en voz alta. Si no sabes algo, dilo en una frase.")
    body = {
        "system_instruction": {"parts": [{"text": sys}]},
        "contents": [{"parts": [{"text": question}]}],
        "generationConfig": {"maxOutputTokens": 300, "temperature": 0.4},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode("utf-8"))
        cands = resp.get("candidates", [])
        if not cands:
            return ""
        parts = cands[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts).strip()
    except Exception:
        return ""
