"""Config de voz de Jarvis (idioma, genero, velocidad, tono, efecto robot).
La comparten tts.py (como suena) y gemini.py (en que idioma responde)."""
import os
import json

_PATH = os.path.join(os.path.dirname(__file__), ".voice_config.json")

DEFAULT = {"lang": "es", "gender": "m", "rate": 0, "pitch": -18, "robot": True,
           "only_my_voice": False}

# voces edge-tts por idioma: (masculina, femenina)
VOICES = {
    "es": ("es-ES-AlvaroNeural", "es-ES-ElviraNeural"),
    "en": ("en-US-GuyNeural", "en-US-JennyNeural"),
    "fr": ("fr-FR-HenriNeural", "fr-FR-DeniseNeural"),
    "it": ("it-IT-DiegoNeural", "it-IT-ElsaNeural"),
    "de": ("de-DE-ConradNeural", "de-DE-KatjaNeural"),
    "pt": ("pt-PT-DuarteNeural", "pt-PT-RaquelNeural"),
}
LANG_NAME = {"es": "espanol", "en": "ingles", "fr": "frances",
             "it": "italiano", "de": "aleman", "pt": "portugues"}


def load():
    try:
        c = json.load(open(_PATH))
    except Exception:
        c = {}
    d = dict(DEFAULT)
    for k in DEFAULT:
        if k in c:
            d[k] = c[k]
    try:
        d["rate"] = max(-50, min(80, int(d["rate"])))
        d["pitch"] = max(-40, min(40, int(d["pitch"])))
    except Exception:
        d["rate"], d["pitch"] = 0, -18
    d["robot"] = bool(d["robot"])
    d["only_my_voice"] = bool(d.get("only_my_voice", False))
    if d["lang"] not in VOICES:
        d["lang"] = "es"
    if d["gender"] not in ("m", "f"):
        d["gender"] = "m"
    return d


def save(patch):
    d = load()
    d.update({k: v for k, v in (patch or {}).items() if k in DEFAULT})
    json.dump(d, open(_PATH, "w"))
    return load()


def voice_id(d=None):
    d = d or load()
    return VOICES[d["lang"]][0 if d["gender"] == "m" else 1]
