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

const LANGS = [['es', 'Español'], ['en', 'English'], ['fr', 'Français'],
  ['it', 'Italiano'], ['de', 'Deutsch'], ['pt', 'Português']]
const VOICE_SAMPLE = { es: 'Hola, soy Jarvis. Así sueno ahora.', en: 'Hi, I am Jarvis. This is how I sound.',
  fr: 'Bonjour, je suis Jarvis.', it: 'Ciao, sono Jarvis.', de: 'Hallo, ich bin Jarvis.', pt: 'Olá, sou o Jarvis.' }

export default function Settings({ authFetch }) {
  const [s, setS] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [vc, setVc] = useState(null)
  const [vp, setVp] = useState(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/settings`).then((r) => r.json()).then(setS).catch(() => {})
    authFetch(`${API_BASE}/api/voice_config`).then((r) => r.json()).then(setVc).catch(() => {})
    authFetch(`${API_BASE}/api/voice_status`).then((r) => r.json()).then(setVp).catch(() => {})
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

  const updVc = async (patch) => {
    setVc({ ...vc, ...patch })
    try {
      const r = await authFetch(`${API_BASE}/api/voice_config`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      setVc(await r.json())
    } catch { /* noop */ }
  }

  const testVoice = () => {
    const txt = VOICE_SAMPLE[vc?.lang] || VOICE_SAMPLE.es
    try { new Audio(`${API_BASE}/api/tts?text=${encodeURIComponent(txt)}&_=${Date.now()}`).play() } catch { /* noop */ }
  }

  const refreshVp = () =>
    authFetch(`${API_BASE}/api/voice_status`).then((r) => r.json()).then(setVp).catch(() => {})

  const startEnroll = async () => {
    try { await authFetch(`${API_BASE}/api/voice_enroll_start?n=3`, { method: 'POST' }) } catch { /* noop */ }
    await refreshVp()
    const iv = setInterval(async () => {
      try {
        const r = await authFetch(`${API_BASE}/api/voice_status`)
        const d = await r.json()
        setVp(d)
        if (!d.enrolling) clearInterval(iv)
      } catch { /* noop */ }
    }, 1500)
    setTimeout(() => clearInterval(iv), 90000)
  }

  const clearVoice = async () => {
    try { await authFetch(`${API_BASE}/api/voice_clear`, { method: 'POST' }) } catch { /* noop */ }
    if (vc?.only_my_voice) updVc({ only_my_voice: false })
    refreshVp()
  }

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

      {vc && (
        <div className="mt-6 border-t border-white/10 pt-5">
          <h3 className="jarvis-title text-base mb-1">VOZ E IDIOMA</h3>
          <p className="text-[11px] text-jarvis-muted mb-4">Se aplica al momento. También por voz: "habla más rápido", "voz de mujer", "quita el efecto robot", "háblame en inglés".</p>

          <label className="text-sm font-display text-white/90">Idioma de respuesta</label>
          <select value={vc.lang} onChange={(e) => updVc({ lang: e.target.value })}
            className="w-full mt-1 mb-4 bg-jarvis-card/60 border border-white/10 rounded-lg py-2 px-2 text-sm text-white">
            {LANGS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>

          <label className="text-sm font-display text-white/90 block mb-1">Tipo de voz</label>
          <div className="flex gap-2 mb-4">
            {[['m', 'Hombre'], ['f', 'Mujer']].map(([g, n]) => (
              <button key={g} onClick={() => updVc({ gender: g })}
                className={`flex-1 rounded-lg py-2 text-sm font-display border ${vc.gender === g ? 'bg-jarvis-accent/20 text-jarvis-accent border-jarvis-accent/40' : 'bg-jarvis-card/60 text-jarvis-muted border-white/10'}`}>
                {n}
              </button>
            ))}
          </div>

          <label className="text-sm font-display text-white/90">Velocidad · {vc.rate > 0 ? '+' : ''}{vc.rate}%</label>
          {slider(vc.rate, -50, 80, 5, (v) => updVc({ rate: v }))}
          <div className="h-3" />
          <label className="text-sm font-display text-white/90">Tono · {vc.pitch > 0 ? '+' : ''}{vc.pitch} Hz</label>
          {slider(vc.pitch, -40, 40, 2, (v) => updVc({ pitch: v }))}

          <div className="flex items-center justify-between mt-4">
            <label className="text-sm font-display text-white/90">Efecto robot</label>
            <button onClick={() => updVc({ robot: !vc.robot })}
              className={`rounded-full px-4 py-1.5 text-xs font-display border ${vc.robot ? 'bg-jarvis-accent/20 text-jarvis-accent border-jarvis-accent/40' : 'bg-jarvis-card/60 text-jarvis-muted border-white/10'}`}>
              {vc.robot ? 'ON' : 'OFF'}
            </button>
          </div>

          <button onClick={testVoice}
            className="w-full mt-4 bg-jarvis-card/60 text-jarvis-muted border border-white/10 rounded-xl py-2.5 text-sm font-display tracking-wide">
            🔊 Probar voz
          </button>
        </div>
      )}

      {vp && vc && (
        <div className="mt-6 border-t border-white/10 pt-5">
          <h3 className="jarvis-title text-base mb-1">SOLO MI VOZ</h3>
          <p className="text-[11px] text-jarvis-muted mb-4">Que Jarvis solo obedezca a tu voz. No es infalible al 100%, pero filtra a otras personas aunque haya gente alrededor.</p>

          <div className="flex items-center justify-between mb-3">
            <label className="text-sm font-display text-white/90">Activar "solo mi voz"</label>
            <button onClick={() => vp.enrolled && updVc({ only_my_voice: !vc.only_my_voice })}
              disabled={!vp.enrolled}
              className={`rounded-full px-4 py-1.5 text-xs font-display border ${vc.only_my_voice && vp.enrolled ? 'bg-jarvis-accent/20 text-jarvis-accent border-jarvis-accent/40' : 'bg-jarvis-card/60 text-jarvis-muted border-white/10'} ${!vp.enrolled ? 'opacity-40' : ''}`}>
              {vc.only_my_voice ? 'ON' : 'OFF'}
            </button>
          </div>

          {vp.enrolling > 0 ? (
            <div className="text-sm text-jarvis-accent mb-2">
              Di <b>"Jarvis, ..."</b> {vp.enrolling} {vp.enrolling === 1 ? 'vez más' : 'veces más'} (una frase distinta cada vez).
            </div>
          ) : (
            <div className="text-[12px] text-jarvis-muted mb-2">
              {vp.enrolled ? `✓ Voz aprendida (${vp.samples} muestras).` : 'Aún no has enseñado tu voz. Primero apréndela para poder activar el filtro.'}
            </div>
          )}

          <button onClick={startEnroll}
            className="w-full bg-jarvis-card/60 text-jarvis-muted border border-white/10 rounded-xl py-2.5 text-sm font-display tracking-wide">
            🎤 {vp.enrolled ? 'Volver a aprender mi voz' : 'Aprende mi voz'}
          </button>
          {vp.enrolled && (
            <button onClick={clearVoice}
              className="w-full mt-2 text-red-300/80 border border-red-400/25 rounded-xl py-2 text-xs font-display tracking-wide">
              Borrar mi voz
            </button>
          )}
        </div>
      )}

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
