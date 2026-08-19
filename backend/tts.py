"""
TTS del lado servidor: sintetiza la voz de Jarvis con edge-tts (Microsoft Neural).
Voz masculina en espanol de Espana por defecto (es-ES-AlvaroNeural), con un toque
ROBOTICO aplicado por ffmpeg (buzz tipo modulador + flanger metalico + graves).

Motivo: en el movil ColorOS congela/desactiva Google TTS constantemente, asi que la
voz nativa fallaba. Generandola aqui y reproduciendola como audio normal en la app,
la voz funciona SIEMPRE e igual en cualquier telefono. Cachea por texto+voz+perfil.
"""
import os
import hashlib
import asyncio

import edge_tts

# Voz masculina, espanol de Espana. Alternativas: es-MX-JorgeNeural (chico, MX),
# es-ES-ElviraNeural (chica). Configurable por env o por query ?voice=
DEFAULT_VOICE = os.environ.get("JARVIS_TTS_VOICE", "es-ES-AlvaroNeural")
# Tono un poco mas grave (mas "maquina"). +0Hz = natural.
PITCH = os.environ.get("JARVIS_TTS_PITCH", "-18Hz")
# Toque robotico via ffmpeg. JARVIS_TTS_ROBOT=0 lo desactiva; JARVIS_TTS_ROBOT_AF
# permite afinar la cadena de filtros sin tocar el codigo.
ROBOT = os.environ.get("JARVIS_TTS_ROBOT", "1") != "0"
ROBOT_AF = os.environ.get(
    "JARVIS_TTS_ROBOT_AF",
    # tremolo ~62Hz = bandas laterales tipo ring-mod (lo mas "robot") sin perder
    # inteligibilidad; flanger = brillo metalico; band-limit = timbre de "aparato".
    "tremolo=f=62:d=0.55,"
    "flanger=delay=2:depth=4:regen=9:speed=0.5,"
    "highpass=f=110,lowpass=f=7000,"
    "volume=2.0",
)
MAX_LEN = 600  # tope de caracteres por peticion

# Perfil: si cambia (voz, tono o efecto) el hash cambia y se regenera solo.
PROFILE = f"{PITCH}|{'robot:' + ROBOT_AF if ROBOT else 'plain'}"

CACHE_DIR = os.path.join(os.path.dirname(__file__), "tts_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(text: str, voice: str) -> str:
    h = hashlib.sha1(f"{voice}|{PROFILE}::{text}".encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, h + ".mp3")


async def _robotize(src: str, dst: str) -> bool:
    """Aplica el efecto robotico con ffmpeg. True si ok."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", src, "-af", ROBOT_AF,
            "-codec:a", "libmp3lame", "-q:a", "4", dst,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0
    except Exception:
        return False


async def synthesize(text: str, voice: str = None) -> str:
    """Devuelve la ruta a un MP3 con la frase hablada. Cachea; None si texto vacio."""
    text = (text or "").strip()
    if not text:
        return None
    text = text[:MAX_LEN]
    voice = (voice or DEFAULT_VOICE).strip() or DEFAULT_VOICE

    path = _cache_path(text, voice)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    raw = path + ".raw.mp3"
    communicate = edge_tts.Communicate(text, voice, pitch=PITCH)
    await communicate.save(raw)
    if not os.path.exists(raw) or os.path.getsize(raw) == 0:
        raise RuntimeError("sintesis vacia")

    if ROBOT:
        part = path + ".part"
        if await _robotize(raw, part):
            os.replace(part, path)
            try: os.remove(raw)
            except OSError: pass
        else:
            # ffmpeg fallo: servir la voz cruda para no quedarnos sin audio
            os.replace(raw, path)
    else:
        os.replace(raw, path)
    return path
