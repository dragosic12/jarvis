"""Agente LangChain de respaldo (fallback) para comandos que ni las reglas ni
Gemini han sabido resolver en una accion concreta. Se usa como ULTIMO recurso
dentro de parse_intent: si no produce ninguna accion util, el llamador sigue
tratando el texto como una pregunta normal (comportamiento igual que antes).

Activar/desactivar sin tocar codigo: env JARVIS_LANGCHAIN_FALLBACK=0 lo apaga.

La API key NUNCA se versiona: backend/.anthropic_key (chmod 600, en .gitignore),
mismo patron que backend/.groq_key.
"""
import json
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
_AGENT = None


def _load_anthropic_key():
    k = os.environ.get("ANTHROPIC_API_KEY")
    if k:
        return k.strip()
    try:
        with open(os.path.join(_DIR, ".anthropic_key")) as f:
            return f.read().strip()
    except OSError:
        return None


def tool_consultar_tiempo() -> str:
    """Consulta el tiempo actual para responderlo por voz."""
    try:
        import weather
        texto = weather.weather_speech()
    except Exception:
        texto = "No he podido consultar el tiempo ahora mismo."
    return json.dumps({"kind": "say", "text": texto})


def tool_decir_hora() -> str:
    """Dice la hora actual para responderla por voz."""
    import datetime
    now = datetime.datetime.now()
    texto = f"Son las {now.hour}" + (" en punto" if now.minute == 0 else f" y {now.minute}")
    return json.dumps({"kind": "say", "text": texto})


def tool_control_volumen(direccion: str) -> str:
    """Sube, baja, silencia o pone al maximo el volumen de musica.

    direccion debe ser una de: 'subir', 'bajar', 'maximo', 'silenciar'.
    """
    mapa = {"subir": "up", "bajar": "down", "maximo": "max", "silenciar": "mute"}
    act = mapa.get((direccion or "").strip().lower())
    if not act:
        return json.dumps({"kind": "none"})
    return json.dumps({
        "kind": "action",
        "action_value": f"jarvis-volume://music/{act}",
        "category": "volumen",
        "description": f"Volumen: {direccion}",
    })


def tool_poner_alarma(hora: str) -> str:
    """Pone una alarma a una hora concreta. hora en formato 'HH:MM' (24 horas)."""
    import re
    m = re.match(r"^(\d{1,2}):(\d{2})$", (hora or "").strip())
    if not m:
        return json.dumps({"kind": "none"})
    hh, mm = int(m.group(1)), int(m.group(2))
    return json.dumps({
        "kind": "action",
        "action_value": f"jarvis-alarm://{hh}:{mm}",
        "category": "reloj",
        "description": f"Alarma a las {hh}:{mm:02d}",
    })


def tool_poner_temporizador(segundos: int) -> str:
    """Pone un temporizador / cuenta atras de N segundos."""
    try:
        segundos = int(segundos)
    except (TypeError, ValueError):
        return json.dumps({"kind": "none"})
    if segundos <= 0:
        return json.dumps({"kind": "none"})
    return json.dumps({
        "kind": "action",
        "action_value": f"jarvis-timer://{segundos}",
        "category": "reloj",
        "description": f"Temporizador de {segundos}s",
    })


def tool_sin_accion_disponible() -> str:
    """Usa esta tool cuando ninguna de las otras aplica: la peticion no es una
    accion que puedas ejecutar, debe tratarse como una pregunta normal."""
    return json.dumps({"kind": "none"})


def _agente():
    global _AGENT
    if _AGENT is None:
        key = _load_anthropic_key()
        if not key:
            raise RuntimeError("Sin ANTHROPIC_API_KEY ni backend/.anthropic_key")
        os.environ.setdefault("ANTHROPIC_API_KEY", key)

        from langchain.agents import create_agent

        _AGENT = create_agent(
            model="claude-haiku-5-5",
            tools=[
                tool_consultar_tiempo,
                tool_decir_hora,
                tool_control_volumen,
                tool_poner_alarma,
                tool_poner_temporizador,
                tool_sin_accion_disponible,
            ],
            system_prompt=(
                "Eres el motor de respaldo de Jarvis, un asistente de voz en espanol. "
                "Te llega una frase que el sistema de reglas de Jarvis NO ha sabido "
                "convertir en una accion. Si una de tus tools resuelve la peticion, "
                "llamala UNA sola vez con los argumentos correctos. Si ninguna aplica, "
                "usa tool_sin_accion_disponible. No inventes datos (p.ej. horas) que "
                "el usuario no haya dado."
            ),
        )
    return _AGENT


def resolver_con_agente(texto: str, raw: str, context: str) -> dict:
    """Intenta resolver con el agente LangChain. Devuelve None si no hay
    ninguna accion util (el llamador debe seguir con su fallback normal)."""
    if os.environ.get("JARVIS_LANGCHAIN_FALLBACK", "1") == "0":
        return None
    if not texto:
        return None
    try:
        resultado = _agente().invoke(
            {"messages": [{"role": "user", "content": texto}]},
            {"recursion_limit": 6},
        )
    except Exception:
        return None

    tool_msgs = [m for m in resultado.get("messages", []) if type(m).__name__ == "ToolMessage"]
    if not tool_msgs:
        return None
    try:
        data = json.loads(tool_msgs[-1].content)
    except Exception:
        return None

    if data.get("kind") == "say" and data.get("text"):
        return {
            "matched": True, "raw_text": raw, "category": "pregunta", "trigger": "langchain",
            "action_type": "say", "action_value": data["text"], "command_id": None,
            "description": "Respuesta (agente)", "platform": "all", "query": texto,
            "context": context, "silent": False,
        }
    if data.get("kind") == "action" and data.get("action_value"):
        return {
            "matched": True, "raw_text": raw, "category": data.get("category", "accion"),
            "trigger": "langchain", "action_type": "url", "action_value": data["action_value"],
            "command_id": None, "description": data.get("description", "Accion (agente)"),
            "platform": "all", "query": None, "context": context, "silent": True,
        }
    return None
