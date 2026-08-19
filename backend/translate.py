"""
Traduccion para Jarvis (endpoint gratis de Google Translate, sin API key).
Mapea el idioma destino a una voz de edge-tts para que Jarvis lo hable en ese idioma.
"""
import json
import urllib.request
import urllib.parse

# nombre en espanol (normalizado, sin tildes) -> (codigo, voz edge-tts masculina)
LANGS = {
    "ingles": ("en", "en-US-GuyNeural"),
    "english": ("en", "en-US-GuyNeural"),
    "frances": ("fr", "fr-FR-HenriNeural"),
    "aleman": ("de", "de-DE-ConradNeural"),
    "italiano": ("it", "it-IT-DiegoNeural"),
    "portugues": ("pt", "pt-BR-AntonioNeural"),
    "catalan": ("ca", "ca-ES-EnricNeural"),
    "japones": ("ja", "ja-JP-KeitaNeural"),
    "chino": ("zh-CN", "zh-CN-YunxiNeural"),
    "ruso": ("ru", "ru-RU-DmitryNeural"),
    "arabe": ("ar", "ar-SA-HamedNeural"),
    "griego": ("el", "el-GR-NestorasNeural"),
    "holandes": ("nl", "nl-NL-MaartenNeural"),
    "polaco": ("pl", "pl-PL-MarekNeural"),
    "turco": ("tr", "tr-TR-AhmetNeural"),
    "espanol": ("es", "es-ES-AlvaroNeural"),
    "castellano": ("es", "es-ES-AlvaroNeural"),
}
CODE = {name: c for name, (c, v) in LANGS.items()}
VOICE_BY_CODE = {c: v for (c, v) in LANGS.values()}


def translate(text, code):
    url = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl="
           + urllib.parse.quote(code) + "&dt=t&q=" + urllib.parse.quote(text))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode())
    return "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()
