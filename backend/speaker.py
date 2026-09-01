"""Verificacion de locutor (biometria de voz) con Resemblyzer.
Enrola la voz del dueño (varias muestras -> embedding medio) y comprueba cada
comando; si 'solo mi voz' esta activo y la voz no coincide, el comando se ignora.

La huella se guarda en .voiceprint.json (NO versionar: es dato biometrico)."""
import os
import json
import threading
import tempfile
import subprocess

import numpy as np

_DIR = os.path.dirname(os.path.abspath(__file__))
_PRINT_PATH = os.path.join(_DIR, ".voiceprint.json")
_DEFAULT_THRESHOLD = 0.76

_enc = None
_lock = threading.Lock()
_enroll_left = 0   # muestras que faltan por capturar en "modo aprendizaje"


def _encoder():
    global _enc
    if _enc is None:
        from resemblyzer import VoiceEncoder
        _enc = VoiceEncoder("cpu", verbose=False)
        try:  # pre-calienta numba para que la 1a de verdad no tarde
            _enc.embed_utterance(np.zeros(16000, dtype=np.float32) + 1e-3)
        except Exception:
            pass
    return _enc


def _embed_bytes(audio_bytes):
    """audio (webm/ogg/m4a/wav) -> embedding 256-d, o None si no hay voz util."""
    src = wavp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".in", delete=False) as f:
            f.write(audio_bytes)
            src = f.name
        wavp = src + ".wav"
        subprocess.run(["ffmpeg", "-y", "-i", src, "-ac", "1", "-ar", "16000", "-f", "wav", wavp],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        import soundfile as sf
        from resemblyzer import preprocess_wav
        wav, sr = sf.read(wavp, dtype="float32")
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        wav = preprocess_wav(wav, source_sr=sr)
        if len(wav) < int(16000 * 0.6):   # menos de ~0,6 s de voz -> no fiable
            return None
        with _lock:
            return _encoder().embed_utterance(wav)
    except Exception:
        return None
    finally:
        for p in (src, wavp):
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass


def _load():
    try:
        return json.load(open(_PRINT_PATH))
    except Exception:
        return {}


def _save(d):
    json.dump(d, open(_PRINT_PATH, "w"))


def is_enrolled():
    return len(_load().get("embs", [])) > 0


def status():
    d = _load()
    return {"enrolled": bool(d.get("embs")), "samples": len(d.get("embs", [])),
            "threshold": d.get("threshold", _DEFAULT_THRESHOLD)}


def enroll(audio_bytes):
    """Añade una muestra a la huella. Devuelve nº de muestras (0 si no valio)."""
    emb = _embed_bytes(audio_bytes)
    if emb is None:
        return 0
    d = _load()
    embs = d.get("embs", [])
    embs.append(emb.tolist())
    d["embs"] = embs[-8:]
    d.setdefault("threshold", _DEFAULT_THRESHOLD)
    _save(d)
    return len(d["embs"])


def clear():
    try:
        os.remove(_PRINT_PATH)
    except OSError:
        pass


def arm_enroll(n=3):
    """Empieza el 'modo aprendizaje': las proximas n locuciones (mismo micro que
    los comandos) se usan para crear la huella. Borra la huella anterior."""
    global _enroll_left
    clear()
    _enroll_left = max(1, min(6, int(n)))
    return _enroll_left


def enroll_pending():
    return _enroll_left


def do_enroll(audio_bytes):
    """Enrola una locucion capturada por el micro de comandos. Devuelve las que faltan."""
    global _enroll_left
    if _enroll_left <= 0:
        return 0
    emb = _embed_bytes(audio_bytes)
    if emb is None:
        return _enroll_left   # no valio (poca voz): que repita, no descuenta
    d = _load()
    embs = d.get("embs", [])
    embs.append(emb.tolist())
    d["embs"] = embs[-8:]
    d.setdefault("threshold", _DEFAULT_THRESHOLD)
    _save(d)
    _enroll_left -= 1
    return _enroll_left


def verify(audio_bytes):
    """(ok, similitud). Si no hay huella o no se pudo analizar -> ok=True (no bloquea)."""
    d = _load()
    embs = d.get("embs", [])
    if not embs:
        return True, 1.0
    emb = _embed_bytes(audio_bytes)
    if emb is None:
        return True, 1.0
    ref = np.mean(np.array(embs, dtype=np.float32), axis=0)
    ref = ref / (np.linalg.norm(ref) + 1e-9)
    e = emb / (np.linalg.norm(emb) + 1e-9)
    sim = float(np.dot(ref, e))
    thr = d.get("threshold", _DEFAULT_THRESHOLD)
    return sim >= thr, sim


def _warm():
    try:
        _encoder()
    except Exception:
        pass


# calienta el modelo en segundo plano al importar (no bloquea el arranque)
threading.Thread(target=_warm, daemon=True).start()
