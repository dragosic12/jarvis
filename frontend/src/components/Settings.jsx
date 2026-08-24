import React, { useState, useEffect } from 'react'
import { API_BASE } from '../config'
import { reloadSettings, requestPhonePerms, enableDeviceAdmin } from '../utils/native'

// La "Sensibilidad" 0..100 mueve a la vez el umbral minimo y el factor sobre el
// ruido (el que manda con el VAD adaptativo). 100 = lo mas sensible posible.
const RMS_MIN = 0.0003, RMS_MAX = 0.0060
const MULT_MIN = 1.3, MULT_MAX = 3.5
const rmsToSens = (rms) => Math.round(((RMS_MAX - rms) / (RMS_MAX - RMS_MIN)) * 100)
const sensToRms = (s) => +(RMS_MAX - (s / 100) * (RMS_MAX - RMS_MIN)).toFixed(5)
const sensToMult = (s) => +(MULT_MAX - (s / 100) * (MULT_MAX - MULT_MIN)).toFixed(2)

export default function Settings({ authFetch }) {
  const [s, setS] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    fetch(`${API_BASE}/api/settings`).then((r) => r.json()).then(setS).catch(() => {})
  }, [])

  if (!s) return <div className="px-4 py-8 text-jarvis-muted text-sm text-center">Cargando ajustes…</div>

  const set = (k, v) => { setS({ ...s, [k]: v }); setSaved(false) }

  const save = async () => {
    setSaving(true)
    try {
      await authFetch(`${API_BASE}/api/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(s),
      })
      await reloadSettings()
      setSaved(true)
    } catch { /* noop */ }
    setSaving(false)
  }

  const slider = (val, min, max, step, onCh) => (
    <input type="range" min={min} max={max} step={step} value={val}
      onChange={(e) => onCh(+e.target.value)} className="w-full accent-jarvis-accent" />
  )

  return (
    <div className="px-4 py-5 max-w-md mx-auto">
      <h2 className="jarvis-title text-lg mb-1">AJUSTES</h2>
      <p className="text-[11px] text-jarvis-muted mb-5">Se aplican al instante en la escucha, sin reinstalar.</p>

      <div className="mb-5">
        <label className="text-sm font-display text-white/90">Sensibilidad del micro · {rmsToSens(s.silence_rms)}%</label>
        {slider(rmsToSens(s.silence_rms), 0, 100, 1,
          (v) => { setS({ ...s, silence_rms: sensToRms(v), speech_mult: sensToMult(v) }); setSaved(false) })}
        <p className="text-[11px] text-jarvis-muted mt-1">Más alta = oye voz más lejana o floja (pero también más ruido de fondo). Como solo actúa al oír "Jarvis", puedes ponerla al máximo.</p>
      </div>

      <div className="mb-5">
        <label className="text-sm font-display text-white/90">Amplificación de voz floja · {Math.round(s.norm_max_gain)}×</label>
        {slider(s.norm_max_gain, 4, 30, 1, (v) => set('norm_max_gain', v))}
        <p className="text-[11px] text-jarvis-muted mt-1">Sube la voz muy baja para que se transcriba mejor.</p>
      </div>

      <div className="mb-5">
        <label className="text-sm font-display text-white/90">Pausa para cortar · {Math.round(s.silence_ms)} ms</label>
        {slider(s.silence_ms, 300, 2000, 50, (v) => set('silence_ms', v))}
        <p className="text-[11px] text-jarvis-muted mt-1">Silencio que espera antes de dar por acabada la frase.</p>
      </div>

      <button onClick={save} disabled={saving}
        className="w-full mt-1 bg-jarvis-accent/20 text-jarvis-accent border border-jarvis-accent/40 rounded-xl py-2.5 font-display tracking-wide glow-border transition-colors">
        {saving ? 'GUARDANDO…' : saved ? '✓ GUARDADO Y APLICADO' : 'GUARDAR'}
      </button>

      <button onClick={() => requestPhonePerms()}
        className="w-full mt-4 bg-jarvis-card/60 text-jarvis-muted border border-white/10 rounded-xl py-2.5 text-sm font-display tracking-wide">
        📞 Permisos de llamadas y modo coche
      </button>
      <button onClick={() => enableDeviceAdmin()}
        className="w-full mt-2 bg-jarvis-card/60 text-jarvis-muted border border-white/10 rounded-xl py-2.5 text-sm font-display tracking-wide">
        🔒 Activar bloqueo de pantalla por voz
      </button>
      <p className="text-[11px] text-jarvis-muted mt-2 text-center">
        Para contestar/colgar por voz y el auto-modo-coche por Bluetooth.
      </p>

      <p className="text-[11px] text-jarvis-muted mt-4 text-center">
        Para reglas de comandos (frase → acción), usa la pestaña <span className="text-jarvis-accent">Comandos</span>.
      </p>
    </div>
  )
}
