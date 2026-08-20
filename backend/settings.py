"""Ajustes en caliente del asistente (sensibilidad del micro, etc.). Se guardan en
settings.json y el servicio nativo los lee al arrancar / cuando se recargan."""
import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "settings.json")

# valor por defecto + rango permitido (min, max) para validar
_SPEC = {
    "silence_rms":   (0.0020, 0.0004, 0.0060),   # umbral VAD: mas bajo = mas sensible
    "silence_ms":    (700,    300,    2000),      # ms de silencio para cortar
    "norm_max_gain": (18.0,   4.0,    30.0),      # tope de amplificacion de voz floja
    "min_speech_ms": (300,    150,    800),       # duracion minima para reaccionar
}


def load() -> dict:
    d = {k: v[0] for k, v in _SPEC.items()}
    try:
        if os.path.exists(_PATH):
            saved = json.load(open(_PATH))
            for k in _SPEC:
                if k in saved:
                    d[k] = saved[k]
    except Exception:
        pass
    return d


def save(new: dict) -> dict:
    d = load()
    for k, (default, lo, hi) in _SPEC.items():
        if k in new:
            try:
                val = float(new[k])
                d[k] = max(lo, min(hi, val))
            except (TypeError, ValueError):
                pass
    try:
        json.dump(d, open(_PATH, "w"))
    except Exception:
        pass
    return d
