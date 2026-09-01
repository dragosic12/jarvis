"""
Parser de intenciones: toma el texto transcrito y lo convierte en una accion.

Flujo:
1. Strip wake word "jarvis"
2. Detectar contexto (en el movil, en el servidor, en el ordenador)
3. Detectar si es una pregunta -> redirigir a Claude CLI
4. Normalizar texto (minusculas, quitar tildes y puntuacion)
5. Detectar categoria (verbo inicial o alias)
6. Buscar trigger_phrase en la BD (priorizar deep links en movil)
7. Para buscar: extraer query despues del target
8. Devolver accion a ejecutar
"""

import unicodedata
import re
import datetime as _dt
from database import get_db


# --- Hora, alarmas y temporizadores (numeros hablados en espanol) ---
_NUMS = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
    "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16,
    "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veinticinco": 25, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
    "sesenta": 60, "noventa": 90, "media": 30, "cuarto": 15,
}


def _word_num(s):
    s = (s or "").strip()
    if s.isdigit():
        return int(s)
    return _NUMS.get(s)


def _parse_spoken_time(s):
    """'8 y media de la tarde' -> (20, 30); '20:30' -> (20, 30)."""
    s = s.strip()
    m = re.match(r"^(\d{1,2})[:h\. ](\d{2})", s)
    if m:
        return int(m.group(1)) % 24, int(m.group(2))
    # "18:30" -> normalizacion quita el ':' -> "1830"; interpretar HHMM/HMM pegado
    m = re.match(r"^(\d{3,4})$", s)
    if m:
        v = m.group(1)
        hh, mm = int(v[:-2]), int(v[-2:])
        if hh < 24 and mm < 60:
            return hh, mm
    parts = s.split()
    if not parts:
        return None, None
    hh = _word_num(parts[0])
    if hh is None:
        return None, None
    rest = " ".join(parts[1:])
    mm = 0
    if "y media" in rest:
        mm = 30
    elif "y cuarto" in rest:
        mm = 15
    elif "menos cuarto" in rest:
        hh -= 1
        mm = 45
    else:
        m2 = re.search(r"y (\w+)", rest)
        if m2 and _word_num(m2.group(1)) is not None:
            mm = _word_num(m2.group(1))
    if any(w in rest for w in ("tarde", "noche")) and hh < 12:
        hh += 12
    if "manana" in rest and hh == 12:
        hh = 0
    return hh % 24, mm % 60


def _parse_duration(s):
    """'diez minutos', '1 hora y media', 'media hora', '30 segundos' -> segundos."""
    total = 0
    if "media hora" in s:
        total += 1800
        s = s.replace("media hora", " ")
    for num, unit in re.findall(r"(\d+|\w+)\s+(horas?|minutos?|segundos?)", s):
        n = _word_num(num)
        if n is None or num == "media":  # "media" no es un contador de horas
            continue
        if unit.startswith("hora"):
            total += n * 3600
        elif unit.startswith("minuto"):
            total += n * 60
        else:
            total += n
    if "y media" in s and "hora" in s:
        total += 1800
    return total


def _say_intent(raw, context, msg):
    return {
        "matched": True, "raw_text": raw, "category": "ayuda", "trigger": "ayuda",
        "action_type": "say", "action_value": msg, "command_id": None,
        "description": "Ayuda", "platform": "all", "query": None,
        "context": context, "silent": False,
    }


# Uso de Claude: "cuanto (porcentaje de) claude me queda", "uso semanal", "sesion actual"...
_USAGE_KW = re.compile(r"\b(uso|usado|gasto|porcentaje|por ?ciento|queda|quedan|"
                       r"gastad\w*|consumid\w*|limite|llevo|gastando|restante|"
                       r"renue\w*|renova\w*|reinici\w*|resetea\w*)\b")
_CLAUDE_RE = re.compile(r"\b(cl[oa]u?d\w*|clave)\b")   # claude y sus errores: claud/cloud/claudie/claudia/clave
_USAGE_PHRASES = re.compile(
    r"(uso semanal|limite semanal|porcentaje semanal|sesion actual|"
    r"cuant[oa] (me )?queda (de )?(la )?sesion|cuant[oa] (me )?queda (esta )?semana|"
    r"cuanto llevo (esta semana|de la semana|gastado))")


def _match_usage(text, raw, context):
    """Uso de la suscripcion de Claude (semanal + sesion de 5h)."""
    ctx = (_CLAUDE_RE.search(text) or "sesion" in text or "semanal" in text or "semana" in text)
    hit = (ctx and _USAGE_KW.search(text)) or _USAGE_PHRASES.search(text)
    if not hit:
        return None
    return {
        "matched": True, "raw_text": raw, "category": "claude_usage", "trigger": "usage",
        "action_type": "usage", "action_value": "", "command_id": None,
        "description": "Uso de Claude", "platform": "all", "query": None,
        "context": context, "silent": False,
    }


_TR_LANGS = {
    "ingles": "en", "english": "en", "frances": "fr", "aleman": "de", "italiano": "it",
    "portugues": "pt", "catalan": "ca", "japones": "ja", "chino": "zh-CN", "ruso": "ru",
    "arabe": "ar", "griego": "el", "holandes": "nl", "polaco": "pl", "turco": "tr",
    "espanol": "es", "castellano": "es",
}


def _tr_intent(raw, context, code, txt):
    txt = txt.strip()
    if not txt:
        return None
    return {"matched": True, "raw_text": raw, "category": "traducir", "trigger": "translate",
            "action_type": "translate", "action_value": txt, "command_id": None,
            "description": f"Traducir a {code}", "platform": "all", "query": code,
            "context": context, "silent": False}


def _match_translate(text, raw, context):
    """'traduce X al ingles', 'como se dice X en ingles', 'en ingles como se dice X'."""
    m = re.match(r"^traduce(?:me)?\s+(.+?)\s+al?\s+([a-z]+)$", text)
    if m and m.group(2) in _TR_LANGS:
        return _tr_intent(raw, context, _TR_LANGS[m.group(2)], m.group(1))
    m = re.match(r"^traduce(?:me)?(?: esto)?(?: al| a)\s+([a-z]+)\s+(.+)$", text)
    if m and m.group(1) in _TR_LANGS:
        return _tr_intent(raw, context, _TR_LANGS[m.group(1)], m.group(2))
    m = re.match(r"^como se (?:dice|escribe) (.+?) en ([a-z]+)$", text)
    if m and m.group(2) in _TR_LANGS:
        return _tr_intent(raw, context, _TR_LANGS[m.group(2)], m.group(1))
    m = re.match(r"^en ([a-z]+) como se (?:dice|escribe) (.+)$", text)
    if m and m.group(1) in _TR_LANGS:
        return _tr_intent(raw, context, _TR_LANGS[m.group(1)], m.group(2))
    return None


def _match_conversation(text, raw, context):
    """Modo conversacion (Iron Man): hablar seguido sin repetir 'Jarvis'."""
    if re.search(r"(modo conversacion|modo iron man|modo charla|hablemos|conversemos|"
                 r"vamos a hablar|charlemos)", text):
        return _dev_intent(raw, context, "jarvis-conv://on", "Modo conversacion",
                           category="conversacion", silent=False)
    if re.search(r"(sal del modo conversacion|salir del modo conversacion|modo normal|"
                 r"desactiva el modo conversacion|termina la conversacion)", text):
        return _dev_intent(raw, context, "jarvis-conv://off", "Salir de conversacion",
                           category="conversacion", silent=False)
    return None


def _claude_intent(raw, context, atype, val):
    return {"matched": True, "raw_text": raw, "category": "claude", "trigger": "claude",
            "action_type": atype, "action_value": val.strip(), "command_id": None,
            "description": "Claude", "platform": "all", "query": None,
            "context": context, "silent": False}


_CLW = r"(?:claude|claud|claudio|claudie|claudi|clau|cloud|clod)"  # claude y sus mishears

def _match_claude(text, raw, context):
    """Hablar con Claude por voz. 'dile/pidele a claude que...' = agente (hace tareas);
    'preguntale a claude...' / 'claude ...' = conversacion con memoria de hilo."""
    m = re.match(r"^(?:dile a %s que|pidele a %s que|encargale a %s que) (.+)$"
                 % (_CLW, _CLW, _CLW), text)
    if m:
        return _claude_intent(raw, context, "claude_agent", m.group(1))
    m = re.match(r"^(?:preguntale a %s|pregunta a %s|habla con %s|%s) (.+)$"
                 % (_CLW, _CLW, _CLW, _CLW), text)
    if m:
        return _claude_intent(raw, context, "claude_chat", m.group(1))
    return None


def _question_intent(raw, context, q):
    return {"matched": True, "raw_text": raw, "category": "pregunta", "trigger": "gemini",
            "action_type": "question", "action_value": q, "command_id": None,
            "description": "Pregunta", "platform": "all", "query": q,
            "context": context, "silent": False}


def _match_followup(text, raw, context):
    """Seguimientos de una explicacion (usan la memoria del hilo de Gemini)."""
    # Cambiar de tema -> reiniciar el hilo
    if re.search(r"cambia de tema|cambiemos de tema|olvida(lo| eso| el tema)?|otro tema|"
                 r"nuevo tema|borra el tema|empieza de cero|empecemos de nuevo", text):
        return {"matched": True, "raw_text": raw, "category": "conversacion", "trigger": "reset",
                "action_type": "chat_reset", "action_value": "", "command_id": None,
                "description": "Nuevo tema", "platform": "all", "query": None,
                "context": context, "silent": True}
    # Ampliar / preguntar por fuentes -> van al hilo de Gemini con el texto tal cual
    if re.match(r"^(amplia|ampliame|amplialo|ampliemos|profundiza|desarrolla|cuentame mas|"
                r"dime mas|y que mas|sigue con eso|dame mas detalle|explica(me)? mas)\b", text) \
       or re.search(r"de donde (lo |la |las )?(has )?sacad|de donde sacas eso|segun quien|"
                    r"de que fuente|que fuentes?|como lo sabes|quien lo dice|es fiable eso", text):
        return _question_intent(raw, context, text)
    return None


def _match_pc_open(text, raw, context):
    """'en el ordenador abre X' / 'abre X en el ordenador' -> abrir en el sobremesa."""
    pc = r"(?:el )?(?:ordenador|ordenata|pc|sobremesa)"
    # "abre X en el ordenador"
    m = re.match(r"^(?:abre|abreme|pon|ponme) (.+?) en " + pc + r"$", text)
    if m:
        return _pc_intent(raw, context, m.group(1))
    # "en el ordenador abre X"
    m = re.match(r"^en " + pc + r" (?:abre|abreme|pon|ponme) (.+)$", text)
    if m:
        return _pc_intent(raw, context, m.group(1))
    # el prefijo "en el ordenador " ya lo pudo quitar CONTEXT_PREFIXES -> context=desktop
    if context == "desktop":
        m = re.match(r"^(?:abre|abreme|pon|ponme) (.+)$", text)
        if m:
            return _pc_intent(raw, context, m.group(1))
    return None


def _pc_intent(raw, context, val):
    return {"matched": True, "raw_text": raw, "category": "pc", "trigger": "pc_open",
            "action_type": "pc_open", "action_value": val.strip(), "command_id": None,
            "description": "Abrir en el PC", "platform": "all", "query": None,
            "context": context, "silent": False}


def _match_pc_control(text, raw, context):
    """Controlar el sobremesa por voz: volumen, media, apagar/bloquear, captura.
    Solo actua si el comando menciona el ordenador (o el contexto ya es 'desktop')."""
    is_pc = context == "desktop" or re.search(r"\b(ordenador|ordenata|pc|sobremesa)\b", text)
    if not is_pc:
        return None

    def out(action):
        return {"matched": True, "raw_text": raw, "category": "ordenador", "trigger": action,
                "action_type": "pc_ctrl", "action_value": action, "command_id": None,
                "description": f"PC: {action}", "platform": "all", "query": None,
                "context": context, "silent": True}

    if re.search(r"captura|pantallazo|screenshot|foto de la pantalla|captura de pantalla", text):
        return out("screenshot")
    if re.search(r"\breinicia|reiniciar|reinicio\b", text):
        return out("reboot")
    if re.search(r"suspende|suspender|hiberna|duerme el|ponlo a dormir", text):
        return out("suspend")
    if re.search(r"\bapaga|apagar\b", text) and not re.search(r"linterna|luz|pantalla", text):
        return out("shutdown")
    if re.search(r"bloquea|bloquear|bloqueo", text):
        return out("lock")
    if re.search(r"silencia|silencio|mutea|\bmute\b|quita el sonido", text):
        return out("mute")
    if re.search(r"\b(sube|subir|mas)\b", text) and re.search(r"volumen|sonido", text):
        return out("vol_up")
    if re.search(r"\b(baja|bajar|menos)\b", text) and re.search(r"volumen|sonido", text):
        return out("vol_down")
    if re.search(r"siguiente|proxima cancion|pasa (de |la )?cancion|salta la cancion|salta de cancion", text):
        return out("next")
    if re.search(r"cancion anterior|tema anterior|anterior cancion|\banterior\b|previa", text):
        return out("prev")
    if re.search(r"pausa|pausar|reanuda|reproduce|dale al play|pon la musica|quita la musica|"
                 r"\bplay\b|para la (musica|cancion|reproduccion)|para la peli", text):
        return out("playpause")
    return None


def _match_pc_clip(text, raw, context):
    """Portapapeles PC<->movil."""
    # Movil -> PC: "copia al ordenador X"
    if re.match(r"^copia(?:me)?(?: esto)? (?:al|en el|en) (?:ordenador|pc|portapapeles)", text):
        mr = re.search(r"copia(?:me)?(?:\s+esto)?\s+(?:al|en el|en)\s+"
                       r"(?:ordenador|pc|portapapeles(?:\s+del\s+(?:ordenador|pc))?)\s+(.+)$",
                       raw, re.IGNORECASE)
        payload = mr.group(1).strip() if (mr and mr.group(1).strip()) else ""
        if payload:
            return {"matched": True, "raw_text": raw, "category": "ordenador", "trigger": "pc_clip_set",
                    "action_type": "pc_clip_set", "action_value": payload, "command_id": None,
                    "description": "Copiar al PC", "platform": "all", "query": None,
                    "context": context, "silent": True}
    # PC -> movil: leer el portapapeles del PC
    if re.search(r"portapapeles|(lo|que) (has )?copiad", text) and re.search(r"ordenador|\bpc\b", text) \
       and re.search(r"lee|leeme|que (hay|pone|dice|copiaste|has copiado)|dime|trae|dame", text):
        return {"matched": True, "raw_text": raw, "category": "ordenador", "trigger": "pc_clip_get",
                "action_type": "pc_clip_get", "action_value": "", "command_id": None,
                "description": "Leer portapapeles PC", "platform": "all", "query": None,
                "context": context, "silent": False}
    return None


def _match_pc_read(text, raw, context):
    """Leer/resumir la pantalla del PC en alto."""
    if re.search(r"pantalla", text) and re.search(r"ordenador|\bpc\b", text) \
       and re.search(r"\b(lee|leeme|que pone|que dice|que hay|que sale|resume|resumeme|dime que)\b", text):
        return {"matched": True, "raw_text": raw, "category": "ordenador", "trigger": "pc_read",
                "action_type": "pc_read_screen", "action_value": "", "command_id": None,
                "description": "Leer pantalla PC", "platform": "all", "query": None,
                "context": context, "silent": False}
    return None


def _match_pc_type(text, raw, context):
    """'escribe en el ordenador X' -> teclea X en la ventana activa del sobremesa."""
    m = re.match(r"^(?:escribe|escribeme|teclea|dicta) en (?:el )?(?:ordenador|pc|sobremesa) (.+)$", text)
    if not m and context == "desktop":
        m = re.match(r"^(?:escribe|escribeme|teclea|dicta) (.+)$", text)
    if not m:
        return None
    # Sacar el texto real de raw (conserva mayusculas/acentos)
    mr = re.search(r"(?:escribe|escribeme|teclea|dicta)(?:\s+en\s+(?:el\s+)?(?:ordenador|pc|sobremesa))?\s+(.+)$",
                   raw, re.IGNORECASE)
    payload = (mr.group(1).strip() if (mr and mr.group(1).strip()) else m.group(1).strip())
    return {"matched": True, "raw_text": raw, "category": "ordenador", "trigger": "pc_type",
            "action_type": "pc_type", "action_value": payload, "command_id": None,
            "description": f"Escribir en el PC: {payload[:40]}", "platform": "all",
            "query": None, "context": context, "silent": True}


def _match_pc_shot(text, raw, context):
    """'haz una captura y mandamela' -> captura del PC y la abre en el movil.
    'mandamela/al movil' solo tiene sentido desde el PC, asi que no exige decir 'ordenador'."""
    if re.search(r"captura|pantallazo|screenshot|pantalla", text) and \
       re.search(r"mandamela|mandame|envia|enviamela|enviame|al movil|al telefono|ensename|muestrame|pasame|pasamela", text):
        return {"matched": True, "raw_text": raw, "category": "ordenador", "trigger": "pc_shot",
                "action_type": "pc_shot", "action_value": "", "command_id": None,
                "description": "Captura del PC al movil", "platform": "all",
                "query": None, "context": context, "silent": True}
    return None


def _match_football(text, raw, context):
    """Partidos de futbol: 'quien juega hoy', 'juega el madrid hoy',
    'a que hora juega el barsa', 'hay partido hoy', 'cuando juega el atleti'."""
    juega = re.search(r"\b(juega|juegan|jugaba|jugaban|jueguen|jugo|jugara)\b", text)
    partido = re.search(r"\bpartido[s]?\b", text)
    equipos = re.search(r"\b(madrid|barcelona|barca|barsa|barza|atletico|atleti|sevilla|"
                        r"betis|valencia|villarreal|athletic|bilbao|real sociedad|celta|"
                        r"getafe|girona|osasuna|rayo|espanyol|mallorca|alaves|psg|city|"
                        r"united|liverpool|chelsea|arsenal|bayern|juventus|milan|inter)\b", text)
    triggers = re.search(r"\b(hoy|manana|esta noche|champions|la liga|premier|futbol)\b", text)
    hay = re.search(r"\bhay\b.{0,15}\b(partido|futbol|champions|liga)\b", text)
    hora = re.search(r"(a que hora|cuando|contra quien) (juega|es el partido)|proximo partido", text)
    resultado = re.search(r"como quedo|que resultado|como (fue|quedaron|han quedado)|marcador", text)
    tabla = re.search(r"clasificacion|en que puesto|que puesto|posicion va|\btabla\b|"
                      r"lider de la liga|como va la liga|quien va primero", text)
    if (hora or hay or tabla or (resultado and equipos)
            or (juega and (triggers or equipos)) or (partido and (triggers or equipos))):
        return {"matched": True, "raw_text": raw, "category": "futbol", "trigger": "futbol",
                "action_type": "football", "action_value": "", "command_id": None,
                "description": "Futbol", "platform": "all", "query": text,
                "context": context, "silent": False}
    return None


def _match_music(text, raw, context):
    """Musica del movil (Spotify u otra app): play/pausa/siguiente/anterior o buscar tema."""
    from urllib.parse import quote_plus
    if re.search(r"\bordenador\b|\bpc\b|sobremesa", text):
        return None  # eso es control del PC (lo lleva _match_pc_control)
    m = re.search(r"(?:pon|ponme|reproduce|reproducir|escuchar)\s+(.+?)\s+en spotify", text)
    if not m:
        m = re.search(r"(?:pon|ponme|reproduce)\s+la cancion\s+(.+)$", text)
    if m and m.group(1).strip():
        return _dev_intent(raw, context, "jarvis-music://spotify?q=" + quote_plus(m.group(1).strip()), "Spotify")
    if re.search(r"(siguiente|proxima|pasa|salta|cambia).{0,12}(cancion|tema|pista|musica)|"
                 r"siguiente cancion|pon la siguiente|pasa de cancion", text):
        return _dev_intent(raw, context, "jarvis-music://next", "Siguiente")
    if re.search(r"(cancion|tema) anterior|pon la anterior|vuelve a la anterior|"
                 r"cancion de antes|pon la de antes", text):
        return _dev_intent(raw, context, "jarvis-music://prev", "Anterior")
    if re.search(r"pausa la musica|para la musica|deten la musica|quita la musica|"
                 r"para de sonar|pausa la cancion|pausa spotify", text):
        return _dev_intent(raw, context, "jarvis-music://pause", "Pausa")
    if re.search(r"pon (algo de )?musica|reproduce (algo de )?musica|ponme musica|"
                 r"quiero (escuchar )?musica|dale a la musica|reanuda la musica|sigue la musica|"
                 r"reanuda spotify|dale al play", text):
        return _dev_intent(raw, context, "jarvis-music://play", "Musica")
    return None


def _voice_intent(raw, context, directive):
    return {"matched": True, "raw_text": raw, "category": "voz", "trigger": "voz",
            "action_type": "voice_cfg", "action_value": directive, "command_id": None,
            "description": "Ajuste de voz", "platform": "all", "query": directive,
            "context": context, "silent": False}


def _match_voice(text, raw, context):
    """Ajustes de voz e idioma por comando (velocidad, genero, tono, robot, idioma)."""
    if re.search(r"habla (mas )?(rapido|deprisa|ligero)|mas rapido|acelera la voz|ve mas rapido", text):
        return _voice_intent(raw, context, "rate:+")
    if re.search(r"habla (mas )?(despacio|lento)|mas lento|mas despacio|ve mas despacio", text):
        return _voice_intent(raw, context, "rate:-")
    if re.search(r"voz de (mujer|chica|femenina)|voz femenina|ponte voz de mujer", text):
        return _voice_intent(raw, context, "gender:f")
    if re.search(r"voz de (hombre|chico|masculina)|voz masculina|ponte voz de hombre", text):
        return _voice_intent(raw, context, "gender:m")
    if re.search(r"voz (mas )?(grave|profunda)|mas grave|habla mas grave", text):
        return _voice_intent(raw, context, "pitch:-")
    if re.search(r"voz (mas )?(aguda|fina)|mas aguda|habla mas agudo", text):
        return _voice_intent(raw, context, "pitch:+")
    if re.search(r"quita(r)? el (efecto )?robot|voz natural|sin (efecto )?robot|quita lo robotico|voz humana", text):
        return _voice_intent(raw, context, "robot:off")
    if re.search(r"pon(er)? el (efecto )?robot|voz robotica|modo robot|suena como (un )?robot", text):
        return _voice_intent(raw, context, "robot:on")
    m = re.search(r"(habla|responde|contesta)(me)? en (ingles|frances|italiano|aleman|portugues|espanol|castellano)|"
                  r"cambia(te)? al (ingles|frances|italiano|aleman|portugues|espanol)", text)
    if m:
        w = m.group(m.lastindex)
        code = {"ingles": "en", "frances": "fr", "italiano": "it", "aleman": "de",
                "portugues": "pt", "espanol": "es", "castellano": "es"}.get(w)
        if code:
            return _voice_intent(raw, context, "lang:" + code)
    if re.search(r"voz por defecto|restablece la voz|resetea la voz|voz de siempre", text):
        return _voice_intent(raw, context, "reset")
    return None


def _match_seescreen(text, raw, context):
    """Analizar visualmente lo que hay en pantalla (captura + vision), tipo Google Lens."""
    if re.search(r"\bordenador\b|\bpc\b|sobremesa", text):
        return None
    if re.search(r"analiza (lo que veo|esto|la pantalla|esta pantalla|la imagen|la foto)|"
                 r"que es esto|que estoy viendo|identifica esto|que hay en (la |mi )?pantalla|"
                 r"escanea (esto|la pantalla)|analiza (esta )?(imagen|captura)|"
                 r"que producto es (este|esto)|"
                 r"explica(me)? (esta |la )?(imagen|pantalla|foto|captura)|"
                 r"\bque ves\b|describe(me)? (la |esta )?(pantalla|imagen|foto)|"
                 r"mira (la pantalla|esto|esta pantalla)|que (aparece|sale|pone) en (la )?pantalla", text):
        return _dev_intent(raw, context, "jarvis-seescreen://go", "Analizar pantalla (Lens)")
    return None


def _match_readscreen(text, raw, context):
    """Resumir la pagina/pantalla del MOVIL (no el PC) y dejar el contenido en el hilo."""
    if re.search(r"\bordenador\b|\bpc\b|sobremesa", text):
        return None
    if re.search(r"resume(me)? (esta |la |lo )?(pagina|pantalla|esto|web|articulo|noticia)|"
                 r"resume lo que (estoy|hay)|de que va (esta|esto)|de que trata (esta|esto)|"
                 r"que pone (aqui|en esta pagina|en la pagina)|que dice (esta |la )?(pagina|pantalla)|"
                 r"lee(me)? (esta |la )(pagina|pantalla)|resumeme esto|hazme un resumen de (esta|lo)", text):
        return _dev_intent(raw, context, "jarvis-readscreen://go", "Resumir pantalla del movil")
    return None


def _match_server(text, raw, context):
    """Estado del servidor draleserver."""
    if re.search(r"(como (esta|va|anda)|que tal|estado|salud|como esta) (el |del )?servidor|"
                 r"servidor (como|que tal|esta bien|va bien)|carga del servidor|"
                 r"cuanta (ram|memoria).{0,20}servidor|espacio (en disco|libre).{0,15}servidor|"
                 r"uptime del servidor|estado del sistema", text):
        return {"matched": True, "raw_text": raw, "category": "servidor", "trigger": "servidor",
                "action_type": "server_status", "action_value": "", "command_id": None,
                "description": "Estado servidor", "platform": "all", "query": text,
                "context": context, "silent": False}
    return None


def _match_uptime(text, raw, context):
    """Comprobar si una web/servicio esta arriba."""
    verbo = re.search(r"\b(arriba|funcionando|responde|caido|caida|online|operativo|se ha caido)\b", text)
    known = re.search(r"(lagatta|la gatta|jarvis|immich|fotos|finanzas|swapcar|petunia)", text)
    # el dominio con punto solo sobrevive en el texto original (normalize quita puntos)
    dom = re.search(r"[a-z0-9\-]+\.(es|com|app|net|org|io|dev)\b", (raw or "").lower())
    if verbo and (known or dom):
        return {"matched": True, "raw_text": raw, "category": "uptime", "trigger": "uptime",
                "action_type": "uptime_check", "action_value": "", "command_id": None,
                "description": "Uptime", "platform": "all", "query": (raw or text).lower(),
                "context": context, "silent": False}
    return None


def _match_devtools(text, raw, context):
    """Utilidades de dev: contrasena, uuid, ip publica, timestamp, base64, hash."""
    if re.search(r"genera(me)? (una |un )?(contrasena|contraseña|clave|password|uuid)|"
                 r"dame (una )?(contrasena|contraseña|clave|password)|\buuid\b|"
                 r"(cual es )?mi ip|ip publica|direccion ip|"
                 r"\btimestamp\b|marca de tiempo|hora unix|"
                 r"base ?64|\b(md5|sha256|sha1)\b|hash de", text):
        return {"matched": True, "raw_text": raw, "category": "devtools", "trigger": "devtools",
                "action_type": "devtools", "action_value": "", "command_id": None,
                "description": "Dev tools", "platform": "all", "query": text,
                "context": context, "silent": False}
    return None


def _match_finance(text, raw, context):
    """Cripto, acciones y conversion de moneda."""
    cripto = re.search(r"\b(bitcoin|btc|ethereum|ether|eth|cripto|criptomoneda|dogecoin|doge|"
                       r"cardano|solana|litecoin|ripple|xrp|binance coin|bnb|polkadot|monero|shiba)\b", text)
    accion = re.search(r"\b(accion|acciones|cotiza|cotizacion|bolsa|nasdaq)\b", text)
    cur_words = re.findall(r"\b(dolar|dolares|euro|euros|libra|libras|yen|yenes|franco|francos)\b", text)
    dos_monedas = re.search(r"\d", text) and len({w.rstrip("es") for w in cur_words}) >= 2
    moneda = (dos_monedas
              or re.search(r"cuanto[s]?.{0,40}\b(dolar|dolares|euro|euros|libra|libras|yen|yenes)\b", text)
              or re.search(r"a cuanto esta el (dolar|euro|libra)", text)
              or re.search(r"cambio (del |de )?(euro|dolar|libra)", text))
    if cripto or accion or moneda:
        return {"matched": True, "raw_text": raw, "category": "finanzas", "trigger": "finanzas",
                "action_type": "finance", "action_value": "", "command_id": None,
                "description": "Finanzas", "platform": "all", "query": text,
                "context": context, "silent": False}
    return None


def _match_news(text, raw, context):
    """Titulares de noticias."""
    if re.search(r"\b(noticias|titulares)\b|dame las noticias|que ha pasado (hoy|en el mundo)|ultima hora", text):
        return {"matched": True, "raw_text": raw, "category": "noticias", "trigger": "noticias",
                "action_type": "news", "action_value": "", "command_id": None,
                "description": "Noticias", "platform": "all", "query": text,
                "context": context, "silent": False}
    return None


def _match_weather(text, raw, context):
    """El tiempo / clima."""
    if re.search(r"(que tiempo (hace|va a hacer|hara|tenemos)|el tiempo( de (hoy|manana))?$|"
                 r"hace (mucho |bastante )?(frio|calor)|va a (llover|nevar)|"
                 r"que temperatura|cuantos grados|el clima)", text):
        return {"matched": True, "raw_text": raw, "category": "clima", "trigger": "tiempo",
                "action_type": "weather", "action_value": "", "command_id": None,
                "description": "El tiempo", "platform": "all", "query": None,
                "context": context, "silent": False}
    return None


def _match_briefing(text, raw, context):
    """Briefing: saludo + hora + tiempo + uso de Claude."""
    if re.search(r"(buenos dias|buenas tardes|buenas noches|dame el parte|^el parte|"
                 r"briefing|resumen del dia|dame el resumen|ponme al dia|informe del dia|"
                 r"que tal (el dia|va el dia|va todo))", text):
        return {"matched": True, "raw_text": raw, "category": "briefing", "trigger": "briefing",
                "action_type": "briefing", "action_value": "", "command_id": None,
                "description": "Briefing", "platform": "all", "query": None,
                "context": context, "silent": False}
    return None


def _match_help(text, raw, context):
    """'que comandos hay', 'que puedo abrir', 'que puedo buscar'."""
    if re.match(r"^(?:ayuda|que puedo decir|que comandos|que ordenes|que sabes hacer|"
                r"que puedes hacer|para que sirves|dame los comandos)", text):
        return _say_intent(raw, context,
            "Puedes decir: abre una aplicacion, busca algo, envia un mensaje a un contacto, "
            "abre un chat, pon una alarma o un temporizador, que hora es, abre la camara, "
            "y enciende, apaga o suspende el ordenador. Tambien puedes preguntarme que puedes abrir o buscar.")

    cat = verb = None
    if any(p in text for p in ("que puedo abrir", "que apps", "que aplicaciones", "que cosas puedo abrir")):
        cat, verb = "abrir", "abrir"
    elif any(p in text for p in ("que puedo buscar", "donde puedo buscar", "que busquedas")):
        cat, verb = "buscar", "buscar en"
    if not cat:
        return None
    db = get_db()
    rows = db.execute(
        "SELECT DISTINCT trigger_phrase FROM commands WHERE category=? AND enabled=1 "
        "AND trigger_phrase NOT LIKE '% app' ORDER BY trigger_phrase", (cat,)
    ).fetchall()
    db.close()
    names = [r["trigger_phrase"] for r in rows][:20]
    return _say_intent(raw, context, f"Puedes {verb}: " + ", ".join(names) + ".")


def _match_volume(text, raw, context):
    """'sube/baja el volumen', 'volumen al maximo', 'volumen al 30', 'sube el volumen de la alarma'."""
    if not re.search(r"volum|silenci|sonido|mutea", text):
        return None
    stream = "music"
    if "alarma" in text:
        stream = "alarm"
    elif re.search(r"llamada|tono|timbre", text):
        stream = "ring"
    elif "notificac" in text:
        stream = "notif"
    act = None
    if re.search(r"maximo|a tope|todo el volum", text):
        act = "max"
    elif re.search(r"silenci|mutea|quita (el )?(volum|sonido)|sin (volum|sonido)|a cero|al minimo", text):
        act = "mute"
    elif re.search(r"\b(sube|subir|subeme|mas|arriba|aumenta|mas alto|mas fuerte|abre)\b.*volum", text):
        act = "up"
    elif re.search(r"\b(baja|bajar|bajame|menos|reduce|abajo|mas bajo|mas flojo)\b", text):
        act = "down"
    elif re.search(r"\b(sube|subir|subeme|aumenta|abre)\b", text):
        act = "up"
    else:
        # "al 2 de 10" -> 2/10 = 20%
        m = re.search(r"(?:al?|a|a la)\s+(\d{1,3})\s+de\s+(\d{1,3})", text)
        if m:
            num, den = int(m.group(1)), int(m.group(2))
            act = f"set:{min(100, round(num / den * 100)) if den else 0}"
        else:
            m = re.search(r"(?:al?|a|a la)\s+(mitad|\d{1,3})", text)
            if m:
                if m.group(1) == "mitad":
                    v = 50
                else:
                    n = int(m.group(1))
                    # "por ciento"/"%" o numero >10 -> porcentaje; si no, escala 0-10
                    if re.search(r"por ?ciento|%", text) or n > 10:
                        v = min(n, 100)
                    else:
                        v = min(n * 10, 100)   # "al 2" = 2 de 10 = 20%
                act = f"set:{v}"
    if not act:
        return None
    return {
        "matched": True, "raw_text": raw, "category": "volumen", "trigger": "volumen",
        "action_type": "url", "action_value": f"jarvis-volume://{stream}/{act}", "command_id": None,
        "description": f"Volumen {stream} {act}", "platform": "all", "query": None,
        "context": context, "silent": True,
    }


def _match_brightness(text, raw, context):
    """Brillo de pantalla: sube/baja, maximo/minimo, 'al 5', 'al 50 por ciento'."""
    if not re.search(r"brillo|brightness|pantalla mas (clar|oscur|brillan)|ilumina la pantalla",
                     text):
        return None
    act = None
    if re.search(r"maxim|a tope|mas brillo al max", text):
        act = "max"
    elif re.search(r"minim|mas oscur|mas baj", text):
        act = "min"
    elif re.search(r"\b(sube|subir|aumenta|mas brillo|mas claro|mas alto)\b", text):
        act = "up"
    elif re.search(r"\b(baja|bajar|reduce|menos brillo|mas oscuro|mas bajo)\b", text):
        act = "down"
    else:
        m = re.search(r"(?:al?|a|a la)\s+(\d{1,3})\s+de\s+(\d{1,3})", text)
        if m:
            num, den = int(m.group(1)), int(m.group(2))
            act = f"set:{min(100, round(num / den * 100)) if den else 0}"
        else:
            m = re.search(r"(?:al?|a|a la)\s+(mitad|\d{1,3})", text)
            if m:
                if m.group(1) == "mitad":
                    v = 50
                else:
                    n = int(m.group(1))
                    v = min(n, 100) if (re.search(r"por ?ciento|%", text) or n > 10) else min(n * 10, 100)
                act = f"set:{v}"
    if not act:
        return None
    return _dev_intent(raw, context, f"jarvis-brightness://{act}", f"Brillo {act}")


def _match_ringer(text, raw, context):
    """'pon el movil en vibracion / en silencio / con sonido'."""
    mode = None
    if re.search(r"vibraci|en vibrar|modo vibra|que vibre", text):
        mode = "vibrate"
    elif re.search(r"modo silencio|en silencio|pon(lo)? en silencio|silencia el (movil|telefono)|no molestar", text):
        mode = "silent"
    elif re.search(r"modo (sonido|normal)|quita el silencio|activa el sonido|con sonido|"
                   r"sonido normal|quita la vibraci", text):
        mode = "normal"
    if not mode:
        return None
    return {
        "matched": True, "raw_text": raw, "category": "sonido", "trigger": "sonido",
        "action_type": "url", "action_value": f"jarvis-ringer://{mode}", "command_id": None,
        "description": f"Modo {mode}", "platform": "all", "query": None,
        "context": context, "silent": True,
    }


def _match_lock(text, raw, context):
    """'bloquea el movil / la pantalla / apaga la pantalla'."""
    if re.match(r"^(?:bloquea|bloquear|bloqueame|apaga)\s+(?:el |la |mi )?"
                r"(movil|telefono|celular|pantalla|dispositivo)\b", text):
        return {
            "matched": True, "raw_text": raw, "category": "sistema", "trigger": "bloquear",
            "action_type": "url", "action_value": "jarvis-lock://", "command_id": None,
            "description": "Bloquear el movil", "platform": "all", "query": None,
            "context": context, "silent": True,
        }
    return None


def _dev_intent(raw, context, value, desc, category="dispositivo", silent=True):
    return {
        "matched": True, "raw_text": raw, "category": category, "trigger": category,
        "action_type": "url", "action_value": value, "command_id": None,
        "description": desc, "platform": "all", "query": None,
        "context": context, "silent": silent,
    }


def _match_torch(text, raw, context):
    if not re.search(r"linterna|flash\b|luz del movil", text):
        return None
    if re.search(r"\bsos\b|parpad|intermitent|destell|discoteca", text):
        act = "sos"
    elif re.search(r"apag|quita|off", text):
        act = "off"
    elif re.search(r"encien|pon|activa|dale|enciende|on\b", text):
        act = "on"
    else:
        act = "toggle"
    return _dev_intent(raw, context, f"jarvis-torch://{act}", f"Linterna {act}")


def _match_battery(text, raw, context):
    if re.search(r"volum", text):
        return None
    if re.search(r"bateria|cuanta pila|cuanto (le )?queda de bateria|nivel de bateria", text):
        return _dev_intent(raw, context, "jarvis-battery://", "Bateria", category="info", silent=False)
    return None


def _calc_eval(expr):
    import ast, operator as op
    ops = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
           ast.Pow: op.pow, ast.Mod: op.mod, ast.USub: op.neg}

    def ev(n):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.BinOp):
            return ops[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp):
            return ops[type(n.op)](ev(n.operand))
        raise ValueError
    try:
        return ev(ast.parse(expr, mode="eval").body)
    except Exception:
        return None


def _match_calc(text, raw, context):
    """Calculadora por voz: 'cuanto es 15 por ciento de 240', '12 por 8', '100 entre 4'."""
    if not re.match(r"^(cuanto (es|son|da|vale|hacen|seria|serian)|calcula|calculame|"
                    r"resultado de|dime cuanto es)\b", text):
        return None
    e = " " + text + " "
    e = re.sub(r"(\d+(?:[.,]\d+)?)\s*(?:%|por ?ciento)\s+de\s+(\d+(?:[.,]\d+)?)",
               lambda m: f" (({m.group(1).replace(',', '.')})/100*({m.group(2).replace(',', '.')})) ", e)
    e = re.sub(r"\bpor ?ciento\b", "/100", e)
    e = re.sub(r"\b(multiplicado por|por|veces)\b", "*", e)
    e = re.sub(r"\b(mas|sumado a|y)\b", "+", e)
    e = re.sub(r"\b(menos|restado)\b", "-", e)
    e = re.sub(r"\b(dividido entre|dividido por|dividido|entre)\b", "/", e)
    e = re.sub(r"\b(elevado a|a la potencia de)\b", "**", e)
    e = re.sub(r"\bal cuadrado\b", "**2", e)
    e = re.sub(r"\bal cubo\b", "**3", e)
    e = e.replace(",", ".")
    m = re.search(r"[-+*/%.\d()][-+*/%.\d()\s]*", e)
    if not m:
        return None
    expr = m.group(0).strip()
    if not re.search(r"\d", expr) or not re.search(r"[-+*/]", expr):
        return None   # no es una operacion -> que lo responda Gemini
    val = _calc_eval(expr)
    if val is None:
        return None
    if isinstance(val, float):
        val = int(val) if val == int(val) else round(val, 4)
    return {"matched": True, "raw_text": raw, "category": "calculo", "trigger": "calc",
            "action_type": "say", "action_value": f"Son {val}.", "command_id": None,
            "description": f"Calculo: {val}", "platform": "all", "query": None,
            "context": context, "silent": False}


def _match_camera(text, raw, context):
    """Foto silenciosa (Termux), foto con camara real (+disparo auto), selfie, video."""
    # CAMARA REAL + disparo automatico (max calidad, la sube la app de Immich):
    # "haz una foto con la camara", "abre la camara y hazme una foto", "foto buena"
    real_cam = ("con la camara" in text or "con mi camara" in text
                or re.search(r"abre(me)? la camara y (haz|hazme|saca|sacame|toma|tomame|echa|echame)", text)
                or re.search(r"\bfoto (buena|de calidad|en condiciones)\b", text))
    if real_cam:
        if re.search(r"selfie|frontal|de delante|de frente", text):
            return _dev_intent(raw, context, "jarvis-camera://selfie", "Foto camara real")
        return _dev_intent(raw, context, "jarvis-camera://photo", "Foto camara real")
    # Selfie -> foto silenciosa camara frontal (Termux)
    if re.search(r"\bselfie\b|camara frontal|autofoto|foto frontal|hazme un selfie", text):
        return _dev_intent(raw, context, "jarvis-termux://photo:1", "Selfie")
    if re.search(r"graba(r|me)? (un |el )?video|graba(r|me)? (un )?clip|modo video|"
                 r"ponte a grabar (un )?video|empieza a grabar (un )?video", text):
        return _dev_intent(raw, context, "jarvis-camera://video", "Grabar video")
    if re.search(r"abre(me)? la camara|abrir la camara|abre camara|pon la camara", text):
        return _dev_intent(raw, context, "jarvis-camera://open", "Abrir camara")
    # Hacer foto -> silenciosa via Termux (no abre la camara)
    if re.search(r"\b(haz|hazme|sacame|saca|hacer|toma|tomame|echame|sacate) (una |me una )?foto\b|"
                 r"tira(me)? una foto|dispara una foto|hazme una foto", text):
        return _dev_intent(raw, context, "jarvis-termux://photo:0", "Foto")
    return None


def _match_sms(text, raw, context):
    """Enviar un SMS por voz (via Termux). 'manda un SMS a X que Y'."""
    m = re.match(r"^(?:manda(?:le)?|envia(?:le)?|mandale) (?:un |el )?"
                 r"(?:sms|mensaje de texto|mensaje sms|un texto|texto) (?:a |al )(.+)$", text)
    if not m:
        return None
    rest = m.group(1).strip()
    name, msg = None, ""
    for marker in MSG_MARKERS:
        idx = rest.find(marker)
        if idx > 0:
            name = rest[:idx].strip()
            msg = rest[idx + len(marker):].strip()
            break
    if name is None:
        name = rest
    contact = _get_contact(name)
    if not contact:
        return _no_contact(raw, name)
    from urllib.parse import quote
    digits = re.sub(r"\D", "", contact["phone"])
    if len(digits) == 9:
        digits = "34" + digits
    return {"matched": True, "raw_text": raw, "category": "sms", "trigger": contact["name"],
            "action_type": "url", "action_value": f"jarvis-termux://sms?n=+{digits}&m={quote(msg)}",
            "command_id": None, "description": f"SMS a {contact['name']}", "platform": "all",
            "query": None, "context": context, "silent": True}


def _match_voicenote(text, raw, context):
    """Nota de voz (audio real) via Termux."""
    if re.search(r"(termina|guarda|para) (la |esta |una )?(nota de voz|grabacion de voz)|"
                 r"deja de grabar( la nota)?", text):
        return _dev_intent(raw, context, "jarvis-termux://recordstop", "Guardar nota de voz")
    if re.search(r"graba(me)? (una )?nota de voz|nota de voz nueva|empieza (una |a grabar una )nota de voz|"
                 r"grabame un audio para mi", text):
        return _dev_intent(raw, context, "jarvis-termux://record", "Grabar nota de voz")
    return None


def _match_connectivity(text, raw, context):
    """Bluetooth on/off y abrir ajustes de WiFi."""
    if re.search(r"bluetooth|blutu|blue ?tooth", text):
        if re.search(r"apag|desactiv|quit", text):
            return _dev_intent(raw, context, "jarvis-bt://off", "Bluetooth off")
        return _dev_intent(raw, context, "jarvis-bt://on", "Bluetooth on")
    if re.search(r"\bwifi\b|wi ?fi|wi-fi", text):
        return _dev_intent(raw, context, "jarvis-wifi://", "Ajustes WiFi")
    return None


def _match_read_notifs(text, raw, context):
    """Leer en alto las ultimas notificaciones."""
    if re.search(r"(lee(me)?|dime|que hay en) (las )?notificacion|que notificaciones tengo|"
                 r"que me ha (llegado|entrado)|leeme lo que me ha llegado", text):
        return _dev_intent(raw, context, "jarvis-notif://read", "Leer notificaciones")
    return None


def _match_location(text, raw, context):
    if re.search(r"donde estoy|mi ubicacion|en que (calle|sitio|lugar|parte|zona) estoy|"
                 r"donde me encuentro|que direccion es esta|localizame|mi posicion", text):
        return _dev_intent(raw, context, "jarvis-loc://", "Ubicacion", category="info", silent=False)
    return None


def _match_vibrate(text, raw, context):
    if re.search(r"\bvibra\b|haz(lo)? vibrar|vibra el movil|dale un toque de vibracion", text) \
       and not re.search(r"modo vibracion|en vibracion", text):
        return _dev_intent(raw, context, "jarvis-vibrate://", "Vibrar")
    return None


def _match_phoneclip(text, raw, context):
    """Copiar al portapapeles del MOVIL (via Termux)."""
    if re.search(r"ordenador|\bpc\b|sobremesa", text):
        return None
    if not re.search(r"copia.*\b(movil|telefono)\b", text):
        return None
    from urllib.parse import quote
    mr = re.search(r"copia(?:me)?(?:\s+esto)?\s+(?:al|en el|en)\s+(?:movil|telefono)\s+(.+)$",
                   raw, re.IGNORECASE)
    if not mr:
        mr = re.search(r"copia(?:me)?\s+(.+?)\s+(?:al|en el)\s+(?:movil|telefono)\s*$", raw, re.IGNORECASE)
    if not mr or not mr.group(1).strip():
        return None
    return _dev_intent(raw, context, f"jarvis-termux://clip?set={quote(mr.group(1).strip())}",
                       "Copiar al movil")


def _match_find_phone(text, raw, context):
    # "donde estas", "busca/encuentra/haz sonar el movil" -> hace sonar el telefono
    if re.search(r"\bdonde (estas|te has metido|te metiste|andas|te escondes)\b", text) \
       or re.search(r"\b(busca|encuentra|localiza|haz sonar|hazlo sonar|suena|donde esta|donde deje)\b.*\b(movil|movi|telefono|celular)\b", text):
        return _dev_intent(raw, context, "jarvis-findphone://", "Buscar el movil")
    return None


def _match_car(text, raw, context):
    # Aprender el bluetooth del coche (para auto-activar el modo coche)
    if re.search(r"(este|el) bluetooth (es )?(el )?del coche|aprende (el )?bluetooth del coche|"
                 r"memoriza (el )?bluetooth del coche|recuerda este bluetooth|este es el (bluetooth del )?coche",
                 text):
        return _dev_intent(raw, context, "jarvis-car://learn", "Aprender bluetooth del coche")
    # "activa/enciende el modo coche" / "modo coche" / "apaga el modo coche"
    if not re.search(r"modo coche|modo conducir|modo conduccion", text):
        return None
    if re.search(r"\b(apaga|desactiva|quita|sal del|salir del|termina|para el|desactivar)\b", text):
        return _dev_intent(raw, context, "jarvis-car://off", "Modo coche off")
    return _dev_intent(raw, context, "jarvis-car://on", "Modo coche on")


def _match_call_control(text, raw, context):
    """Manos libres: contestar / colgar una llamada por voz."""
    if re.match(r"^(contesta|descuelga|descolgar|contestar|acepta la llamada|"
                r"coge la llamada|responde (a )?la llamada)\b", text):
        return _dev_intent(raw, context, "jarvis-callctl://answer", "Contestar llamada")
    if re.match(r"^(cuelga|colgar|rechaza|rechazar|no contestes|corta la llamada|"
                r"cuelga la llamada|rechaza la llamada)\b", text):
        return _dev_intent(raw, context, "jarvis-callctl://reject", "Colgar llamada")
    return None


def _routine_slug(name):
    """Convierte un nombre hablado (texto YA normalizado por parse_intent:
    minusculas, sin tildes, sin puntuacion) en un slug estable, para poder
    casarlo luego por voz con 'haz la rutina X' aunque no se diga exactamente
    igual (espacios -> guion bajo)."""
    s = re.sub(r"\s+", "_", name.strip())
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s.strip("_")[:40]


def _match_routine(text, raw, context):
    """Grabador de rutinas.
    FASE 1: 'aprende esta rutina' / 'graba una rutina' (empezar a grabar).
    FASE 3: guardar CON nombre -- 'guarda la rutina como X', 'termina la
    rutina y llamala X', 'llama a esta rutina X' -- o SIN nombre -- 'termina
    la rutina' / 'guarda la rutina' (nombre automatico por fecha). Tambien
    'lista mis rutinas' (cuantas hay), 'analiza mis rutinas' (lo mas repetido,
    FASE 2) y 'haz/ejecuta/reproduce la rutina X' (reproducirla, FASE 3).
    La captura, el guardado, el analisis y la reproduccion ocurren enteramente
    en el movil (JarvisA11yService + RoutineRecorder); aqui solo se traduce la
    frase al esquema jarvis-routine://."""
    # Empezar a grabar
    if re.search(r"\b(aprende|aprender)\s+(esta\s+)?rutina\b", text) \
       or re.search(r"\b(graba|grabar|empieza a grabar|empezar a grabar)\s+(esta\s+|una\s+)?rutina\b", text):
        return _dev_intent(raw, context, "jarvis-routine://record-start", "Empezar a grabar rutina")

    # Parar y guardar CON nombre (varias formas de decirlo) -- van antes que
    # las variantes sin nombre para que "termina la rutina y llamala X" no
    # se quede corto en el "termina la rutina" generico.
    m = re.search(r"\bguarda(?:r)?\s+(?:la\s+)?rutina\s+como\s+(.+)$", text)
    if not m:
        m = re.search(r"\b(?:termina|terminar|para|parar)\s+(?:la\s+)?rutina\s+y\s+llama(?:la|le)?\s+(.+)$", text)
    if not m:
        m = re.search(r"\bllama\s+a\s+esta\s+rutina\s+(.+)$", text)
    if m:
        slug = _routine_slug(m.group(1))
        if slug:
            return _dev_intent(raw, context, f"jarvis-routine://record-stop:{slug}",
                                f"Guardar rutina como {slug}")

    # Parar y guardar SIN nombre (nombre automatico por fecha)
    if re.search(r"\b(termina|terminar|para|parar|deja|dejar)\s+(de\s+grabar\s+)?(la\s+)?rutina\b", text) \
       or re.search(r"\bguarda(r)?\s+(la\s+)?rutina\b", text):
        return _dev_intent(raw, context, "jarvis-routine://record-stop", "Terminar y guardar rutina")

    # Cuantas rutinas hay guardadas
    if re.search(r"\b(lista|listar|cuantas)\s+(mis\s+)?rutinas?\b", text):
        return _dev_intent(raw, context, "jarvis-routine://list", "Listar rutinas", category="info", silent=False)

    # Analizar lo mas repetido (FASE 2)
    if re.search(r"\banaliza(r)?\s+(mis\s+)?rutinas?\b", text) \
       or re.search(r"que (hago|repito) mas|patrones de uso|mis habitos", text):
        return _dev_intent(raw, context, "jarvis-routine://analyze", "Analizar rutinas", category="info", silent=False)

    # Reproducir una rutina guardada (FASE 3)
    m = re.search(r"\b(?:haz|hazme|ejecuta|ejecutar|reproduce|reproducir|lanza|lanzar)\s+la\s+rutina\s+(.+)$", text)
    if m:
        slug = _routine_slug(m.group(1))
        if slug:
            return _dev_intent(raw, context, f"jarvis-routine://play:{slug}", f"Reproducir rutina {slug}")

    return None


def _match_wa_audio(text, raw, context):
    # "envia/manda/graba un audio (o nota de voz) a X"
    m = re.match(
        r"^(?:envia(?:le)?|manda(?:le)?|graba(?:le)?) (?:un |una |el )?"
        r"(?:audio|nota de voz|mensaje de voz|nota) (?:a |al |para )(.+)$", text)
    if not m:
        return None
    name = m.group(1).strip()
    contact = _get_contact(name)
    if not contact:
        return _no_contact(raw, name)
    digits = re.sub(r"\D", "", contact["phone"])
    if len(digits) == 9:
        digits = "34" + digits
    return {
        "matched": True, "raw_text": raw, "category": "mensaje", "trigger": contact["name"],
        "action_type": "url", "action_value": f"jarvis-wa-audio://{digits}", "command_id": None,
        "description": f"Audio de WhatsApp a {contact['name']}", "platform": "all",
        "query": None, "context": context, "silent": True,
    }


_CALL_PHON = None


def _match_call(text, raw, context):
    global _CALL_PHON
    if _CALL_PHON is None:
        _CALL_PHON = {_phon(v) for v in ("llama", "llamar", "llamale", "telefonea", "marca")}
    m = re.match(r"^(?:llama|llamar|llamale|telefonea|haz una llamada|marca)\s+"
                 r"(?:a |al |por telefono a |por telefono al )?(.+)$", text)
    if m:
        name = m.group(1)
    else:
        # fallback fonetico del verbo: yama/yamar/yamale... = llama
        w = text.split()
        if len(w) >= 2 and _phon(w[0]) in _CALL_PHON:
            name = re.sub(r"^(?:a |al |por telefono a |por telefono al )", "",
                          " ".join(w[1:])).strip()
        else:
            return None
    name = re.sub(r"\bpor telefono\b", "", name).strip()
    contact = _get_contact(name)
    if not contact:
        return _no_contact(raw, name)
    digits = re.sub(r"\D", "", contact["phone"])
    # Espana: marcar los 9 digitos nacionales (el +34 no hace falta, y 'tel:34...'
    # sin '+' no marca bien). Numeros extranjeros: internacional con '+'.
    if digits.startswith("34") and len(digits) == 11:
        tel = digits[2:]
    elif len(digits) == 9:
        tel = digits
    else:
        tel = "+" + digits
    return _dev_intent(raw, context, f"tel:{tel}", f"Llamar a {contact['name']}", category="llamar")


def _match_time(text, raw, context):
    if re.match(r"^(?:que hora (?:es|sera)|dime la hora|la hora|que hora)$", text):
        now = _dt.datetime.now()
        txt = f"Son las {now.hour} y {now.minute}" if now.minute else f"Son las {now.hour} en punto"
        return {
            "matched": True, "raw_text": raw, "category": "hora", "trigger": "hora",
            "action_type": "time", "action_value": txt, "command_id": None,
            "description": "Hora actual", "platform": "all", "query": None,
            "context": context, "silent": False,
        }
    return None


def _clock_intent(raw, context, value, desc):
    return {
        "matched": True, "raw_text": raw, "category": "reloj", "trigger": "reloj",
        "action_type": "url", "action_value": value, "command_id": None,
        "description": desc, "platform": "all", "query": None,
        "context": context, "silent": True,
    }


def _match_timer(text, raw, context):
    m = re.match(r"^(?:pon(?:me)?|crea|programa|echa|activa)?\s*(?:un |una )?"
                 r"(?:temporizador|cuenta atras|timer|alarma|tempo) de (.+)$", text)
    if not m:
        return None
    secs = _parse_duration(m.group(1))
    if secs <= 0:
        return None
    return _clock_intent(raw, context, f"jarvis-timer://{secs}", f"Temporizador de {secs}s")


def _match_alarm(text, raw, context):
    m = re.match(r"^(?:pon(?:me)?|crea|programa|activa)?\s*(?:una )?alarma (?:a las?|para las?) (.+)$", text)
    if not m:
        m = re.match(r"^despiertame (?:a las?|para las?) (.+)$", text)
    if not m:
        return None
    hh, mm = _parse_spoken_time(m.group(1))
    if hh is None:
        return None
    return _clock_intent(raw, context, f"jarvis-alarm://{hh}:{mm}", f"Alarma a las {hh}:{mm:02d}")


def _match_alarm_in(text, raw, context):
    """Alarma relativa: 'una alarma dentro de media hora' -> ahora + duracion."""
    m = re.match(r"^(?:pon(?:me)?|crea|programa|activa)?\s*(?:una )?alarma (?:dentro de|en) (.+)$", text)
    if not m:
        m = re.match(r"^despiertame (?:dentro de|en) (.+)$", text)
    if not m:
        return None
    secs = _parse_duration(m.group(1))
    if secs <= 0:
        return None
    target = _dt.datetime.now() + _dt.timedelta(seconds=secs)
    return _clock_intent(raw, context, f"jarvis-alarm://{target.hour}:{target.minute}",
                         f"Alarma en {secs // 60} min ({target.hour}:{target.minute:02d})")


def _match_reminder(text, raw, context):
    """'recuerdame X en 10 minutos' / 'recuerdame X a las 6' -> alarma/timer con etiqueta."""
    if not re.match(r"^recuerda(?:\s*(?:me|te))?\b", text):
        return None
    from urllib.parse import quote
    body = re.sub(r"^recuerda(?:\s*(?:me|te))?\s+(?:que\s+)?", "", text).strip()
    if not body:
        return None
    # Relativo: "... en / dentro de <duracion>"
    m = re.search(r"^(.*?)\s+(?:en|dentro de)\s+(.+)$", body)
    if m:
        msg = m.group(1).strip()
        secs = _parse_duration(m.group(2))
        if msg and secs > 0:
            return _clock_intent(raw, context, f"jarvis-timer://{secs}?msg={quote(msg)}",
                                 f"Recordatorio: {msg}")
    # Absoluto: "... a las <hora>"
    m = re.search(r"^(.*?)\s+(?:a las?|para las?)\s+(.+)$", body)
    if m:
        msg = m.group(1).strip()
        hh, mm = _parse_spoken_time(m.group(2))
        if msg and hh is not None:
            return _clock_intent(raw, context, f"jarvis-alarm://{hh}:{mm}?msg={quote(msg)}",
                                 f"Recordatorio a las {hh}:{mm:02d}: {msg}")
    return None


def _list_intent(raw, context, value, desc):
    return {"matched": True, "raw_text": raw, "category": "lista", "trigger": "lista",
            "action_type": "list", "action_value": value, "command_id": None,
            "description": desc or "Lista", "platform": "all", "query": None,
            "context": context, "silent": False}


def _match_lists(text, raw, context):
    """Notas y lista de la compra por voz."""
    # --- Lista de la compra ---
    m = re.match(r"^(?:anade|anademe|apunta|apuntame|pon|agrega|mete|echa|escribe|"
                 r"agregame) (.+?) (?:a |en )(?:la )?(?:lista de (?:la )?)?compra$", text)
    if m:
        it = m.group(1).strip()
        return _list_intent(raw, context, "add:compra:" + it, f"Anadido a la compra: {it}")
    m = re.match(r"^(?:quita|borra|elimina|saca|tacha) (.+?) de (?:la )?(?:lista de (?:la )?)?compra$", text)
    if m:
        return _list_intent(raw, context, "remove:compra:" + m.group(1).strip(), "Quitar de la compra")
    if re.search(r"(borra|vacia|limpia|elimina|resetea)\b.*\bcompra", text):
        return _list_intent(raw, context, "clear:compra", "Vaciar la compra")
    if re.search(r"(que hay|que tengo|que me falta|que necesito|lee|dime|ensename|muestrame)"
                 r"\b.*\bcompra|que tengo que comprar|lista de la compra", text):
        return _list_intent(raw, context, "read:compra", "Leer la compra")

    # --- Notas ---
    m = re.match(r"^(?:apunta|apuntame|anota|anotame|toma nota)(?:\s+de)?(?:\s+que)?\s+(.+)$", text)
    if m and "compra" not in text:
        it = m.group(1).strip()
        return _list_intent(raw, context, "add:notas:" + it, f"Apuntado: {it}")
    if re.search(r"(borra|vacia|limpia|elimina)\b.*\bnotas", text):
        return _list_intent(raw, context, "clear:notas", "Vaciar notas")
    if re.search(r"(que notas|mis notas|lee(me)? las notas|que tenia apuntado|que apunte|"
                 r"dime las notas|que tengo apuntado)", text):
        return _list_intent(raw, context, "read:notas", "Leer notas")
    return None


def normalize(text: str) -> str:
    """Normaliza: minusculas, sin tildes, sin puntuacion extra."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _phon(w: str) -> str:
    """Clave FONETICA aproximada del espanol: casa por SONIDO, no por letra
    (la transcripcion de Whisper falla por homofonos). Tolera b/v, ll/y, g/j ante
    e/i, c/z/s (seseo), qu/k, h muda, x, w, y letras repetidas por alargamiento
    (conserva 'rr' que es valida: perro, carro)."""
    s = re.sub(r"[^a-z]", "", normalize(w))
    if not s:
        return ""
    s = s.replace("ch", "1")                          # proteger 'ch' (sonido propio)
    s = s.replace("ll", "y")                          # yeismo: ll = y
    s = s.replace("qu", "k")
    s = s.replace("gue", "Ge").replace("gui", "Gi")   # g dura (u muda) -> token G
    s = s.replace("ge", "je").replace("gi", "ji")     # g suave -> j
    s = s.replace("G", "g")                           # restaurar g dura
    s = s.replace("v", "b")                           # b = v
    s = s.replace("z", "s")
    s = s.replace("ce", "se").replace("ci", "si")     # c ante e/i -> s
    s = s.replace("c", "k")                           # c dura -> k
    s = s.replace("h", "")                            # h muda ('ch' ya protegida)
    s = s.replace("w", "u")
    s = s.replace("x", "ks")
    s = s.replace("1", "c")                           # 'ch' -> simbolo unico /tʃ/
    return re.sub(r"(.)\1+", lambda m: (m.group(1) * 2 if m.group(1) == "r" else m.group(1)), s)


def _phonp(s: str) -> str:
    """Clave fonetica de una frase, palabra a palabra (conserva el numero de palabras)."""
    return " ".join(_phon(w) for w in normalize(s).split())


def _name_key(s: str) -> str:
    """Clave fonetica sin espacios para casar nombres de contacto (aleee->ale,
    peetuuniaa->petunia, y homofonos por sonido)."""
    return "".join(_phon(w) for w in normalize(s).split())


# Categorias reales (una palabra inicial que no resuelva a una de estas se
# reintenta por fonetica). Cacheado el mapa fonetico de verbos/alias.
_KNOWN_CATEGORIES = {"abrir", "buscar", "servidor", "red", "sistema", "claude",
                     "llamar", "encender", "apagar", "suspender"}
_VERB_PHON = None


def _verb_category(word: str):
    """Resuelve el verbo/primera palabra a una categoria por FONETICA (fallback):
    yama->llamar, ensiende->encender, habrre->abrir, etc."""
    global _VERB_PHON
    if _VERB_PHON is None:
        m = {}
        try:
            db = get_db()
            for r in db.execute("SELECT alias, canonical FROM aliases").fetchall():
                m[_phon(r["alias"])] = r["canonical"]
            db.close()
        except Exception:
            pass
        for c in _KNOWN_CATEGORIES:
            m.setdefault(_phon(c), c)
        _VERB_PHON = m
    return _VERB_PHON.get(_phon(word))


def resolve_alias(word: str) -> str:
    """Si la primera palabra es un alias, devuelve la forma canonica."""
    db = get_db()
    row = db.execute("SELECT canonical FROM aliases WHERE alias = ?", (word,)).fetchone()
    db.close()
    return row["canonical"] if row else word


# Cualquier palabra que suene a "Jarvis" (mismo patron que el frontend)
WAKE_RE = re.compile(r"^(?:ch|[jyghx])[ae]+r*[dt]?[bvw]+[ae]*i+[sz]*$")


# --- Navegacion / ubicaciones ---

def _match_navigation(text: str, raw: str, context: str):
    """'llevame a X', 'como llego a X', 'navega a X', 'ruta a X' -> Google Maps."""
    from urllib.parse import quote_plus
    m = re.match(r"^(?:llevame|navega|navegar|ruta|como llego|como voy) (?:a |al |a la |hasta |hacia )?(.+)$", text)
    if not m:
        return None
    dest = m.group(1).strip()
    return {
        "matched": True,
        "raw_text": raw,
        "category": "navegar",
        "trigger": "maps",
        "action_type": "url",
        "action_value": f"https://www.google.com/maps/dir/?api=1&destination={quote_plus(dest)}",
        "command_id": None,
        "description": f"Ruta a {dest}",
        "platform": "all",
        "query": None,
        "context": context,
        "silent": True,
    }


# --- Mensajes de WhatsApp por voz ---

MSG_MARKERS = [" que diga ", " que ponga ", " diciendo ", " que dice ", " de que ", " que "]


def _get_contact(name: str):
    try:
        name = name.strip()
        db = get_db()
        # 1) exacto (prioriza los contactos "limpios": ale, mama, pablo...)
        row = db.execute("SELECT * FROM contacts WHERE name = ?", (name,)).fetchone()
        if not row:
            # 2) coincidencia por palabra completa, el nombre mas corto = mas especifico
            row = db.execute(
                "SELECT * FROM contacts WHERE name LIKE ? OR name LIKE ? OR name LIKE ? "
                "ORDER BY LENGTH(name) LIMIT 1",
                (f"{name} %", f"% {name} %", f"% {name}")
            ).fetchone()
        if not row:
            # 3) subcadena (ultimo recurso)
            row = db.execute(
                "SELECT * FROM contacts WHERE name LIKE ? ORDER BY LENGTH(name) LIMIT 1",
                (f"%{name}%",)
            ).fetchone()
        if not row:
            # 4) clave colapsada: tolera letras repetidas (aleee->ale, peetuuniaa->
            #    petunia) y espacios; conserva rr. Compara nombre completo y por
            #    palabras; prefiere el nombre mas corto (mas especifico).
            key = _name_key(name)
            if len(key) >= 2:
                allc = db.execute("SELECT * FROM contacts").fetchall()

                def _keys(c):
                    ks = {_name_key(c["name"])}
                    ks.update(_name_key(w) for w in c["name"].split())
                    return ks

                exact = [c for c in allc if key in _keys(c)]
                if exact:
                    row = min(exact, key=lambda c: len(c["name"]))
                else:
                    subm = [c for c in allc
                            if any(len(k) >= 3 and (key in k or k in key) for k in _keys(c))]
                    if subm:
                        row = min(subm, key=lambda c: len(c["name"]))
        db.close()
        return row
    except Exception:
        return None


def _wa_link(phone: str, msg: str = "", mobile: bool = True) -> str:
    from urllib.parse import quote
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 9:
        digits = "34" + digits  # numero espanol sin prefijo
    if mobile:
        # Esquema nativo: abre WhatsApp DIRECTO en el chat (wa.me muestra un
        # selector "abrir con..." si el enlace no esta verificado en el movil)
        url = f"whatsapp://send?phone={digits}"
        if msg:
            url += f"&text={quote(msg)}"
    else:
        url = f"https://wa.me/{digits}"
        if msg:
            url += f"?text={quote(msg)}"
    return url


def _msg_intent(raw: str, contact, msg: str, context: str) -> dict:
    mobile = context in ("mobile", "auto")
    return {
        "matched": True,
        "raw_text": raw,
        "category": "mensaje",
        "trigger": contact["name"],
        "action_type": "url",
        "action_value": _wa_link(contact["phone"], msg, mobile),
        "command_id": None,
        "description": f"WhatsApp a {contact['name']}" + (f': "{msg[:40]}"' if msg else ""),
        "platform": "all",
        "query": None,
        "context": context,
        "silent": True,
    }


def _no_contact(raw: str, name: str) -> dict:
    return {"matched": False, "raw_text": raw,
            "error": f"No tengo el numero de '{name}' — anadelo a contactos"}


def _match_whatsapp(text: str, raw: str, context: str):
    """Detecta 'envia un mensaje a X que diga Y', 'dile a X que Y', 'abre el chat de X'."""
    # Abrir chat directo
    m = re.match(r"^(?:abre|abreme) (?:el |la )?(?:chat|conversacion|wasap|whatsapp|guasap) (?:de |con )(.+)$", text)
    if m:
        name = m.group(1).strip()
        contact = _get_contact(name)
        return _msg_intent(raw, contact, "", context) if contact else _no_contact(raw, name)

    # Enviar mensaje con texto
    m = re.match(r"^(?:envia(?:le)?|manda(?:le)?) (?:un |el )?(?:mensaje|wasap|whatsapp|guasap|texto) (?:a |al |para )(.+)$", text)
    if not m:
        m = re.match(r"^(?:dile|escribe(?:le)?) (?:a |al )(.+)$", text)
    if not m:
        return None

    rest = m.group(1).strip()
    name = None
    msg = ""
    for marker in MSG_MARKERS:
        idx = rest.find(marker)
        if idx > 0:
            name = rest[:idx].strip()
            msg = rest[idx + len(marker):].strip()
            break
    if name is None:
        parts = rest.split(None, 1)
        name = parts[0]
        msg = parts[1] if len(parts) > 1 else ""

    contact = _get_contact(name)
    return _msg_intent(raw, contact, msg, context) if contact else _no_contact(raw, name)


QUESTION_STARTERS = [
    "como ", "que es ", "que son ", "cual ", "cuales ", "por que ",
    "explica ", "explicame ", "cuentame ", "dime ", "dime como ", "que significa ",
    "que hace ", "que pasa ", "cuando ", "donde ", "quien ", "cuanto ",
    "hay alguna ", "se puede ", "es posible ", "sabes ", "me dices ",
    "me puedes decir ", "puedes decirme ", "que fue ", "que era ", "para que sirve ",
]

CONTEXT_PREFIXES = [
    ("en el movil ", "mobile"),
    ("en el telefono ", "mobile"),
    ("en el servidor ", "server"),
    ("en el ordenador ", "desktop"),
    ("en el pc ", "desktop"),
    ("en el portatil ", "desktop"),
]


def parse_intent(transcript: str, platform: str = "auto") -> dict:
    """Reglas primero (instantaneo y sin coste); si no entiende, Gemini interpreta la
    intencion y la traduce a un comando canonico que las reglas SI ejecutan. El wake
    word 'Jarvis' lo filtra el nativo: aqui solo llega lo que ya dijo 'Jarvis'."""
    r = _parse_rules(transcript, platform)
    if r.get("matched"):
        return r

    # Texto sin la wake word
    text = normalize(transcript)
    w0 = text.split()
    if w0 and WAKE_RE.match(w0[0]):
        text = " ".join(w0[1:])
    elif len(w0) >= 2 and WAKE_RE.match(w0[0] + w0[1]):
        text = " ".join(w0[2:])
    text = text.strip()
    if not text:
        return r

    # --- Fallback IA en UNA sola llamada: orden canonica o respuesta directa ---
    kind, val = "", ""
    try:
        from gemini import smart_reply
        contacts = []
        try:
            db = get_db()
            contacts = [row["name"] for row in db.execute("SELECT name FROM contacts").fetchall()]
            db.close()
        except Exception:
            pass
        kind, val = smart_reply(text, contacts)
    except Exception:
        kind, val = "", ""

    if kind == "cmd" and val:
        r2 = _parse_rules(val, platform)
        if r2.get("matched"):
            r2["llm_interpreted"] = True
            r2["raw_text"] = transcript
            return r2
    if kind == "say" and val:
        # Respuesta ya generada (con memoria): el executor solo la lee
        return {"matched": True, "raw_text": transcript, "category": "pregunta",
                "trigger": "gemini", "action_type": "say", "action_value": val,
                "command_id": None, "description": "Respuesta", "platform": "all",
                "query": text, "context": platform, "silent": False}

    # Ultimo recurso (Gemini fallo): pregunta clasica
    return {"matched": True, "raw_text": transcript, "category": "pregunta",
            "trigger": "gemini", "action_type": "question", "action_value": text,
            "command_id": None, "description": "Pregunta", "platform": "all",
            "query": text, "context": platform, "silent": False}


def _parse_rules(transcript: str, platform: str = "auto") -> dict:
    raw = transcript
    text = normalize(transcript)

    if not text:
        return {"matched": False, "raw_text": raw, "error": "Texto vacio"}

    # 1. Strip wake word (cualquier variante tipo "jarvis", incluso partida en dos)
    w0 = text.split()
    if w0 and WAKE_RE.match(w0[0]):
        text = " ".join(w0[1:])
    elif len(w0) >= 2 and WAKE_RE.match(w0[0] + w0[1]):
        text = " ".join(w0[2:])
    if not text:
        return {"matched": False, "raw_text": raw, "error": "Dime, te escucho"}

    # 1b. Normaliza el verbo "pon" y sus variantes/errores de voz (pone/ponme/ponle/
    # poner/pones) -> "pon", para que valga en todos los comandos que lo usan.
    text = re.sub(r"^pon(?:e|me|le|er|erme|es|gan?|go)?\b", "pon", text)

    # 2. Detectar contexto explicito
    context = platform  # "auto", "mobile", "linux", etc.
    for prefix, ctx in CONTEXT_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            context = ctx
            break

    # PRIORIDAD: un "recuerdame ... (en/a las) ..." es SIEMPRE un recordatorio,
    # aunque su texto contenga futbol/musica/etc ("recuerdame que juega el madrid
    # a las 9"), que si no seria capturado por _match_football y compania.
    if re.match(r"^recuerda(?:\s*(?:me|te))?\b", text):
        rem = _match_reminder(text, raw, context)
        if rem:
            return rem

    # 2a. Ayuda, dispositivo, sonido, bloqueo, volumen, hora, alarmas, temporizadores
    # _match_routine va el PRIMERO: siempre exige la palabra literal "rutina" en
    # el texto, asi que nunca puede robarle un comando a otro matcher; en
    # cambio si va detras, un nombre de rutina que contenga una frase comun
    # (p.ej. "termina la rutina y llamala buenos dias") puede ser interceptado
    # antes de tiempo por matchers mas sueltos (_match_briefing con "buenos
    # dias", _match_weather, etc.) que no exigen esa palabra.
    for matcher in (_match_routine, _match_pc_shot, _match_pc_type, _match_pc_clip, _match_phoneclip, _match_pc_read,
                    _match_pc_control, _match_pc_open,
                    _match_claude, _match_football, _match_finance, _match_news,
                    _match_server, _match_uptime, _match_devtools, _match_music,
                    _match_seescreen, _match_readscreen, _match_voice,
                    _match_conversation, _match_followup, _match_translate,
                    _match_usage, _match_briefing,
                    _match_weather, _match_help, _match_calc, _match_torch, _match_battery, _match_camera, _match_find_phone,
                    _match_connectivity, _match_read_notifs, _match_location, _match_vibrate,
                    _match_car, _match_sms, _match_voicenote, _match_wa_audio, _match_lists,
                    _match_call_control, _match_call, _match_lock, _match_ringer, _match_volume,
                    _match_brightness,
                    _match_reminder, _match_time, _match_alarm_in, _match_timer, _match_alarm):
        hit = matcher(text, raw, context)
        if hit:
            return hit

    # 2b. Mensajes de WhatsApp (antes que preguntas: "dile a X que..." lleva "que")
    wa = _match_whatsapp(text, raw, context)
    if wa:
        return wa

    # 2c. Navegacion (antes que preguntas: "como llego a..." parece pregunta)
    nav = _match_navigation(text, raw, context)
    if nav:
        return nav

    # 3. Detectar si es una pregunta -> Claude CLI
    is_question = any(text.startswith(q) for q in QUESTION_STARTERS)
    # Tambien detectar preguntas con signo de interrogacion en el texto original
    if not is_question and "?" in transcript:
        is_question = True

    if is_question:
        return {
            "matched": True,
            "raw_text": raw,
            "category": "pregunta",
            "trigger": "claude",
            "action_type": "question",
            "action_value": text,
            "command_id": None,
            "description": "Pregunta a Claude",
            "platform": "all",
            "query": text,
            "context": context,
            "silent": False,
        }

    words = text.split()
    if not words:
        return {"matched": False, "raw_text": raw, "error": "Sin palabras"}

    # 4. Detectar categoria (literal; si no es categoria conocida, por FONETICA)
    category = resolve_alias(words[0])
    if category not in _KNOWN_CATEGORIES:
        alt = _verb_category(words[0])
        if alt:
            category = alt
    rest = " ".join(words[1:])

    db = get_db()

    # 5. Buscar comando (greedy match)
    commands = db.execute(
        "SELECT * FROM commands WHERE category = ? AND enabled = 1 ORDER BY LENGTH(trigger_phrase) DESC",
        (category,)
    ).fetchall()

    best_match = None
    remaining_text = rest

    for cmd in commands:
        trigger_norm = normalize(cmd["trigger_phrase"])
        if rest.startswith(trigger_norm):
            best_match = cmd
            remaining_text = rest[len(trigger_norm):].strip()
            break
        if trigger_norm in rest:
            best_match = cmd
            remaining_text = rest.replace(trigger_norm, "", 1).strip()
            break

    db.close()

    if not best_match and rest:
        # Pase FONETICO: casa el trigger por sonido (ordenadó->ordenador,
        # yutub->youtube...). Compara secuencias de palabras fonetizadas; asi
        # recupera bien el texto restante (la query en 'buscar').
        rwords = rest.split()
        rp = [_phon(w) for w in rwords]
        for cmd in commands:
            tp = [t for t in (_phon(w) for w in normalize(cmd["trigger_phrase"]).split()) if t]
            n = len(tp)
            if not n or n > len(rp):
                continue
            for i in range(0, len(rp) - n + 1):
                if rp[i:i + n] == tp:
                    best_match = cmd
                    remaining_text = " ".join(rwords[:i] + rwords[i + n:]).strip()
                    break
            if best_match:
                break

    if not best_match:
        # Fuzzy match (solo palabras >2 chars) — SOLO categorias inofensivas:
        # nunca apagar/suspender/sistema/servidor por una palabra suelta mal oida
        db = get_db()
        for word in words[1:]:
            if len(word) < 4:            # solo palabras significativas (evita 'fin'->jellyfin)
                continue
            fuzzy = db.execute(
                "SELECT * FROM commands WHERE (trigger_phrase = ? OR trigger_phrase LIKE ?)"
                " AND enabled = 1 AND category IN ('abrir', 'buscar') LIMIT 1",
                (word, f"{word}%")       # exacta o que EMPIECE por la palabra (no substring)
            ).fetchone()
            if fuzzy:
                best_match = fuzzy
                remaining_text = " ".join(w for w in words[1:] if w != word)
                category = fuzzy["category"]
                break
        db.close()

    # Default buscar -> Google
    if not best_match and category == "buscar" and rest:
        db = get_db()
        google = db.execute(
            "SELECT * FROM commands WHERE category = 'buscar' AND trigger_phrase = 'google' AND enabled = 1"
        ).fetchone()
        db.close()
        if google:
            best_match = google
            remaining_text = rest

    if not best_match:
        return {
            "matched": False,
            "raw_text": raw,
            "category": category,
            "context": context,
            "error": f"No se encontro comando para '{rest}' en categoria '{category}'"
        }

    # 6. En movil, buscar variante deep link/app si existe (tanto abrir como buscar)
    is_mobile = context in ("mobile", "auto") and platform in ("mobile", "auto")
    if is_mobile and best_match["action_type"] in ("url", "search"):
        db = get_db()
        deep = db.execute(
            "SELECT * FROM commands WHERE category = ? AND trigger_phrase = ? AND enabled = 1",
            (category, best_match["trigger_phrase"] + " app")
        ).fetchone()
        db.close()
        if deep:
            best_match = deep

    # Determinar si es accion silenciosa (abrir URL, deep link)
    silent = best_match["action_type"] in ("url", "device")

    result = {
        "matched": True,
        "raw_text": raw,
        "category": category,
        "trigger": best_match["trigger_phrase"],
        "action_type": best_match["action_type"],
        "action_value": best_match["action_value"],
        "command_id": best_match["id"],
        "description": best_match["description"],
        "platform": best_match["platform"],
        "query": None,
        "context": context,
        "silent": silent,
    }

    if best_match["action_type"] == "search":
        # Limpiar conectores sobrantes: "busca en youtube X" deja query "en X"
        q = re.sub(r"\s+", " ", remaining_text).strip()
        for prefijo in ("en ", "de ", "el ", "la ", "los ", "las ", "sobre ", "un ", "una "):
            if q.startswith(prefijo):
                q = q[len(prefijo):].strip()
                break
        result["query"] = q if q else None
        result["silent"] = True

    return result
