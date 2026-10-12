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
from gtts import gTTS

import voicecfg

# Voz masculina, espanol de Espana. Alternativas: es-MX-JorgeNeural (chico, MX),
# es-ES-ElviraNeural (chica). Configurable por env o por query ?voice=
DEFAULT_VOICE = os.environ.get("JARVIS_TTS_VOICE", "es-ES-AlvaroNeural")
# Tono ligeramente mas grave (calmado, autoritario, NO caricaturesco). +0Hz = natural.
PITCH = os.environ.get("JARVIS_TTS_PITCH", "-8Hz")
# Toque "JARVIS de pelicula": nitido y con un leve brillo digital, SIN el buzz de
# robot barato (nada de tremolo/ring-mod ni flanger fuerte). JARVIS_TTS_ROBOT=0
# lo desactiva; JARVIS_TTS_ROBOT_AF permite afinar la cadena sin tocar el codigo.
ROBOT = os.environ.get("JARVIS_TTS_ROBOT", "1") != "0"
ROBOT_AF = os.environ.get(
    "JARVIS_TTS_ROBOT_AF",
    # chorus sutil = textura "sintetizada" sin sonar roto; treble = articulacion
    # nitida; band-limit suave = quita barro grave y aspereza aguda.
    "chorus=0.5:0.9:50:0.4:0.25:2,"
    "treble=g=4,"
    "highpass=f=90,lowpass=f=9500,"
    "volume=1.6",
)
MAX_LEN = 600  # tope de caracteres por peticion

# gTTS (fallback) no acepta pitch ni voz masculina: se le baja el tono con
# rubberband para que no suene tan distinta a Alvaro cuando Microsoft bloquea.
FALLBACK_AF = f"rubberband=pitch=0.85,{ROBOT_AF}" if ROBOT else "rubberband=pitch=0.85"

# Perfil: si cambia (voz, tono o efecto) el hash cambia y se regenera solo.
PROFILE = f"{PITCH}|{'robot:' + ROBOT_AF if ROBOT else 'plain'}"

CACHE_DIR = os.path.join(os.path.dirname(__file__), "tts_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(text: str, voice: str, rate: int) -> str:
    h = hashlib.sha1(f"{voice}|{PROFILE}|rate:{rate}::{text}".encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, h + ".mp3")


def _tempo(rate: int) -> float:
    """rate en % (-50..80, ver voicecfg.py) -> multiplicador seguro para el
    filtro atempo de ffmpeg (un solo paso soporta 0.5-2.0 sin perder calidad)."""
    return max(0.5, min(2.0, 1 + (rate or 0) / 100))


async def _robotize(src: str, dst: str, af: str = ROBOT_AF) -> bool:
    """Aplica el efecto robotico con ffmpeg. True si ok.

    dst suele terminar en ".part" (escritura atomica: se renombra al nombre
    final solo si todo fue bien) -- ffmpeg elige el formato de salida por la
    EXTENSION del archivo si no se le dice lo contrario, y ".part" no es una
    extension reconocida, asi que fallaba SIEMPRE en silencio (DEVNULL se
    tragaba el error) y el audio se servia crudo, sin atempo ni efectos.
    "-f mp3" fuerza el formato explicitamente, sin depender del nombre.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", src, "-af", af,
            "-codec:a", "libmp3lame", "-q:a", "4", "-f", "mp3", dst,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, serr = await proc.communicate()
        if proc.returncode != 0:
            import sys as _sys
            print(f"[tts] ffmpeg fallo (rc={proc.returncode}): {serr[-300:].decode(errors='replace')}", file=_sys.stderr)
        return proc.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0
    except Exception:
        return False


async def _synthesize_gtts_fallback(text: str, dst_path: str) -> None:
    """Respaldo cuando edge-tts (Microsoft) esta caido. gTTS es sincrono y pega
    a un servicio distinto (Google Translate), asi que corre en un hilo aparte
    para no bloquear el event loop."""
    def _run():
        gTTS(text=text, lang="es").save(dst_path)
    await asyncio.to_thread(_run)


async def synthesize(text: str, voice: str = None) -> str:
    """Devuelve la ruta a un MP3 con la frase hablada. Cachea; None si texto vacio."""
    text = (text or "").strip()
    if not text:
        return None
    text = text[:MAX_LEN]
    voice = (voice or DEFAULT_VOICE).strip() or DEFAULT_VOICE
    rate = voicecfg.load().get("rate", 0)
    tempo = _tempo(rate)

    path = _cache_path(text, voice, rate)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    # Cache aparte para el fallback de gTTS: NO cuenta como el cache "bueno"
    # de arriba, para que la proxima peticion siga intentando edge-tts primero
    # y la voz real (Alvaro) vuelva sola en cuanto Microsoft desbloquee, en vez
    # de quedarnos sirviendo gTTS para siempre por haberlo cacheado una vez.
    fallback_path = path + ".fallback.mp3"
    raw = path + ".raw.mp3"

    # edge-tts pega contra un endpoint no oficial de Microsoft que a veces
    # devuelve 403 (bloqueo intermitente). Un intento rapido primero; si ya
    # tenemos un fallback reciente cacheado, lo servimos de inmediato en vez
    # de machacar al usuario con reintentos lentos en cada frase.
    last_err = None
    try:
        communicate = edge_tts.Communicate(text, voice, pitch=PITCH)
        await communicate.save(raw)
        if not (os.path.exists(raw) and os.path.getsize(raw) > 0):
            last_err = RuntimeError("raw vacio")
    except Exception as e:
        last_err = e

    if last_err is not None and os.path.exists(fallback_path) and os.path.getsize(fallback_path) > 0:
        return fallback_path

    if last_err is not None:
        for espera in (0.8, 1.6):
            await asyncio.sleep(espera)
            try:
                communicate = edge_tts.Communicate(text, voice, pitch=PITCH)
                await communicate.save(raw)
                if os.path.exists(raw) and os.path.getsize(raw) > 0:
                    last_err = None
                    break
            except Exception as e:
                last_err = e

    is_fallback = last_err is not None
    if is_fallback:
        try:
            await _synthesize_gtts_fallback(text, raw)
            last_err = None
        except Exception as e2:
            raise RuntimeError(f"sintesis fallo (edge-tts: {last_err}; gtts: {e2})")

    if not os.path.exists(raw) or os.path.getsize(raw) == 0:
        raise RuntimeError("sintesis vacia")

    target = fallback_path if is_fallback else path
    base_af = FALLBACK_AF if is_fallback else (ROBOT_AF if ROBOT else None)
    af = f"atempo={tempo}" if base_af is None else f"atempo={tempo},{base_af}"
    if tempo != 1.0 or base_af is not None:
        part = target + ".part"
        if await _robotize(raw, part, af):
            os.replace(part, target)
            try: os.remove(raw)
            except OSError: pass
        else:
            # ffmpeg fallo: servir la voz cruda para no quedarnos sin audio
            os.replace(raw, target)
    else:
        os.replace(raw, target)
    return target
