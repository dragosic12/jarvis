from faster_whisper import WhisperModel
import json
import tempfile
import os
import time
import urllib.request

# Whisper del sobremesa (drale) por tunel SSH inverso. Ahora whisper.cpp con
# Vulkan sobre la GPU AMD RX 6600 (modelo small, ~1.2s, mucha mas precision).
# API estilo OpenAI: POST multipart /inference. Si el PC esta apagado, fallback CPU local.
REMOTE_WHISPER = os.environ.get("JARVIS_REMOTE_WHISPER", "http://127.0.0.1:9977/inference")
REMOTE_TIMEOUT = 12

# OJO: NO empezar el prompt con "Jarvis" — Whisper lo toma como contexto previo y
# tiende a escribir "Jarvis" al inicio aunque no se diga (falsos disparos de wake).
PROMPT = (
    "Comandos de voz en espanol: abre YouTube, abre WhatsApp, "
    "abre Instagram, abre Spotify, abre TikTok, abre la camara, busca en Google, "
    "envia un mensaje a, dile a, abre el chat de, llevame a, sube el volumen, "
    "baja el volumen, pon una alarma, pon un temporizador, que hora es, "
    "enciende el ordenador, apaga el ordenador, bloquea el movil, enciende la linterna, "
    "cuanta bateria queda. Contactos: Ale, Mama, Pablo, Florin, Mauro, Gabo, Michelina, Abuela."
)


def _load_groq_key():
    k = os.environ.get("GROQ_API_KEY")
    if k:
        return k.strip()
    try:
        with open(os.path.join(os.path.dirname(__file__), ".groq_key")) as f:
            return f.read().strip()
    except OSError:
        return None


# Groq: Whisper large-v3-turbo en su hardware (LPU) -> ~0.2-0.4s, muy preciso.
# Motor PRINCIPAL; si no hay key/internet o falla, cae al GPU del PC y luego a CPU.
GROQ_KEY = _load_groq_key()
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = os.environ.get("JARVIS_GROQ_MODEL", "whisper-large-v3-turbo")
GROQ_TIMEOUT = 10

_model = None


def _transcribe_groq(audio_bytes: bytes, filename: str):
    ext = (os.path.splitext(filename)[1] or ".wav").lstrip(".").lower()
    ctype = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4",
             "mp4": "audio/mp4", "ogg": "audio/ogg", "webm": "audio/webm",
             "flac": "audio/flac"}.get(ext, "application/octet-stream")
    boundary = "----jarvisgroq" + str(int(time.time() * 1000))
    b = boundary.encode()
    body = b"--" + b + b"\r\n"
    body += f'Content-Disposition: form-data; name="file"; filename="audio.{ext}"\r\n'.encode()
    body += f"Content-Type: {ctype}\r\n\r\n".encode() + audio_bytes + b"\r\n"
    # SIN prompt: large-v3-turbo es preciso de sobra y el prompt se "colaba" en la
    # transcripcion (salia "Contactos..."/"Jarvis" en clips cortos -> falsos disparos).
    for name, value in (("model", GROQ_MODEL), ("language", "es"),
                        ("response_format", "json"), ("temperature", "0")):
        body += b"--" + b + b"\r\n"
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    body += b"--" + b + b"--\r\n"
    req = urllib.request.Request(
        GROQ_URL, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Authorization": f"Bearer {GROQ_KEY}",
                 # Cloudflare (error 1010) bloquea el User-Agent por defecto de urllib
                 "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Jarvis/1.0",
                 "Accept": "application/json"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=GROQ_TIMEOUT) as r:
        out = json.loads(r.read().decode())
    text = (out.get("text") or "").strip()
    if not text:
        raise ValueError(f"groq vacio: {out}")
    return {"text": text, "language": "es", "duration": 0,
            "transcribe_time": round(time.time() - t0, 2), "engine": "groq-turbo"}


def _transcribe_remote(audio_bytes: bytes, filename: str):
    boundary = "----jarvis" + str(int(time.time() * 1000))
    b = boundary.encode()
    body = b"--" + b + b"\r\n"
    body += b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
    body += b"Content-Type: audio/wav\r\n\r\n" + audio_bytes + b"\r\n"
    for name, value in (("response_format", "json"), ("language", "es"),
                        ("temperature", "0"), ("prompt", PROMPT)):
        body += b"--" + b + b"\r\n"
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    body += b"--" + b + b"--\r\n"
    req = urllib.request.Request(
        REMOTE_WHISPER, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT) as r:
        out = json.loads(r.read().decode())
    text = (out.get("text") or "").strip()
    if not text:
        raise ValueError(f"respuesta vacia: {out}")
    return {"text": text, "language": "es", "duration": 0, "transcribe_time": 0, "engine": "gpu-small"}


def get_model():
    global _model
    if _model is None:
        print("[Jarvis] Cargando modelo Whisper (base)...")
        t0 = time.time()
        _model = WhisperModel("base", device="cpu", compute_type="int8")
        print(f"[Jarvis] Modelo cargado en {time.time()-t0:.1f}s")
    return _model


_HALLUCINATIONS = {
    "gracias", "gracias por ver", "gracias por ver el video", "gracias por verlo",
    "subtitulos realizados por la comunidad de amaraorg", "suscribete", "amen",
    "que es lo que se llama", "y", "eh", "ah", "oh", "mmm", "aha",
}


def _is_hallucination(text: str) -> bool:
    import unicodedata as _u, re as _re
    t = text.strip().lower()
    t = "".join(c for c in _u.normalize("NFD", t) if _u.category(c) != "Mn")
    t = _re.sub(r"[^\w\s]", "", t).strip()
    return (not t) or len(t) <= 1 or t in _HALLUCINATIONS


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> dict:
    res = _do_transcribe(audio_bytes, filename)
    if res and _is_hallucination(res.get("text", "")):
        res["text"] = ""   # descartar alucinacion: la app lo trata como "nada oido"
    return res


def _do_transcribe(audio_bytes: bytes, filename: str = "audio.webm") -> dict:
    """Transcribe: 1) Groq (rapido+preciso), 2) GPU del PC, 3) CPU local."""
    if GROQ_KEY:
        try:
            return _transcribe_groq(audio_bytes, filename)
        except Exception:
            pass  # sin internet, key mala o Groq caido: seguir con lo local
    try:
        return _transcribe_remote(audio_bytes, filename)
    except Exception:
        pass  # PC apagado o tunel caido: seguir con el modelo local

    model = get_model()

    ext = os.path.splitext(filename)[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        t0 = time.time()
        segments, info = model.transcribe(
            tmp_path,
            language="es",
            beam_size=1,          # greedy: 2-3x mas rapido, suficiente para comandos cortos
            vad_filter=True,
            condition_on_previous_text=False,  # menos alucinaciones en clips cortos
            # Sesga la transcripcion hacia el vocabulario de comandos en espanol
            initial_prompt=(
                "Jarvis, asistente de voz en español. Comandos: Jarvis, abre YouTube, "
                "abre WhatsApp, abre Instagram, abre Spotify, abre Telegram, abre Gmail, "
                "abre la cámara, busca en Google, busca en YouTube, envía un mensaje a, "
                "dile a, llévame a, enciende el ordenador, apaga el ordenador, "
                "suspende el ordenador, pon música."
            ),
        )
        text = " ".join(seg.text.strip() for seg in segments)
        elapsed = time.time() - t0
        return {
            "text": text.strip(),
            "language": info.language,
            "duration": info.duration,
            "transcribe_time": round(elapsed, 2),
            "engine": "servidor-base",
        }
    finally:
        os.unlink(tmp_path)
