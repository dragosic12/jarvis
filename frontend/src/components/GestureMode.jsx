import React, { useRef, useState, useEffect } from 'react'
import { API_BASE } from '../config'
import { isMobile } from '../utils/audio'
import { openNativeUrl, isNativeApp, requestCameraPermission,
         isAccessibilityEnabled, openAccessibilitySettings, startFaceControl, stopFaceControl,
         ensureBatteryUnrestricted } from '../utils/native'

// Boss final: gesto -> accion del sistema (lo ejecuta el servicio nativo)
const SYS = [
  { name: 'Mirar arriba', act: 'Volumen + / scroll' },
  { name: 'Mirar abajo', act: 'Volumen − / scroll' },
  { name: 'Mirar derecha', act: 'Cambiar de app' },
  { name: 'Mirar izquierda', act: 'Inicio' },
  { name: 'Cejas ↑', act: 'Atrás' },
  { name: 'Ceño fruncido', act: 'Notificaciones' },
  { name: 'Boca abierta', act: 'WhatsApp' },
  { name: 'Sonrisa', act: 'YouTube' },
]

// MediaPipe Face Landmarker (Google) desde CDN — detecta 52 blendshapes de la cara
const MP_URL = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.20/vision_bundle.mjs'
const WASM_URL = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.20/wasm'
const MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'

// Gesto -> umbral, blendshapes que lo miden, y accion
const GESTURES = [
  { id: 'cejas',   name: 'Cejas ↑',       act: 'Abrir WhatsApp',      th: 0.45, keys: ['browOuterUpLeft', 'browOuterUpRight'], action: 'whatsapp' },
  { id: 'ceno',    name: 'Ceño fruncido', act: 'Abrir cámara',        th: 0.34, keys: ['browDownLeft', 'browDownRight'],       action: 'camera' },
  { id: 'der',     name: 'Mirar derecha', act: 'Pestaña siguiente',   th: 0.42, keys: ['eyeLookInLeft', 'eyeLookOutRight'],    action: 'tabNext' },
  { id: 'izq',     name: 'Mirar izq.',    act: 'Pestaña anterior',    th: 0.42, keys: ['eyeLookOutLeft', 'eyeLookInRight'],    action: 'tabPrev' },
  { id: 'boca',    name: 'Boca abierta',  act: 'Escucha ON/OFF',      th: 0.50, keys: ['jawOpen'],                              action: 'listen' },
  { id: 'sonrisa', name: 'Sonrisa',       act: 'Abrir YouTube',       th: 0.50, keys: ['mouthSmileLeft', 'mouthSmileRight'],   action: 'youtube' },
]

const avg = (map, keys) => {
  let s = 0, n = 0
  for (const k of keys) { if (map[k] != null) { s += map[k]; n++ } }
  return n ? s / n : 0
}

export default function GestureMode({ authFetch, onTab, onToggleListen }) {
  const videoRef = useRef(null)
  const landmarkerRef = useRef(null)
  const streamRef = useRef(null)
  const rafRef = useRef(0)
  const gestRef = useRef({})       // estado por gesto: armed/last
  const lastUiRef = useRef(0)
  const actionsRef = useRef({})
  actionsRef.current = { authFetch, onTab, onToggleListen }

  const [running, setRunning] = useState(false)
  const [status, setStatus] = useState('Pulsa “Activar cámara”.')
  const [bars, setBars] = useState({})
  const [fire, setFire] = useState('')
  const [log, setLog] = useState([])
  const [bossOn, setBossOn] = useState(false)
  const [bossMsg, setBossMsg] = useState('')

  const startBoss = async () => {
    setBossMsg('Comprobando permisos…')
    await requestCameraPermission()
    await ensureBatteryUnrestricted()
    const a11y = await isAccessibilityEnabled()
    if (!a11y) {
      setBossMsg('Falta activar “Jarvis Gestos” en Accesibilidad. Te abro los ajustes…')
      openAccessibilitySettings()
      return
    }
    await startFaceControl()
    setBossOn(true)
    setBossMsg('CONTROL ACTIVO. Sal de Jarvis y usa gestos en cualquier app.')
  }
  const stopBoss = async () => {
    await stopFaceControl()
    setBossOn(false)
    setBossMsg('Control por gestos apagado.')
  }

  const runCmd = async (text) => {
    try {
      const platform = isMobile() ? 'mobile' : 'linux'
      const res = await actionsRef.current.authFetch(`${API_BASE}/api/command/text`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, platform }),
      })
      const data = await res.json()
      const d = data?.result?.data
      if (d?.type === 'open_url') await openNativeUrl(d.url)
      else if (d?.type === 'device_action' && d.action === 'camera') await openNativeUrl('camera')
    } catch {}
  }

  const dispatch = (action) => {
    const a = actionsRef.current
    if (action === 'whatsapp') runCmd('abre whatsapp')
    else if (action === 'camera') runCmd('abre la camara')
    else if (action === 'youtube') runCmd('abre youtube')
    else if (action === 'tabNext') a.onTab(1)
    else if (action === 'tabPrev') a.onTab(-1)
    else if (action === 'listen') a.onToggleListen()
  }

  const fireGesture = (g) => {
    setFire(g.act)
    clearTimeout(fireGesture._t)
    fireGesture._t = setTimeout(() => setFire(''), 800)
    const hora = new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    setLog((p) => [{ hora, txt: `${g.name} → ${g.act}` }, ...p].slice(0, 6))
    dispatch(g.action)
  }

  const loop = () => {
    const video = videoRef.current, lm = landmarkerRef.current
    if (lm && video && video.readyState >= 2) {
      const now = performance.now()
      let res = null
      try { res = lm.detectForVideo(video, now) } catch {}
      const cats = res?.faceBlendshapes?.[0]?.categories
      if (cats) {
        const map = {}
        for (const c of cats) map[c.categoryName] = c.score
        const nb = {}
        for (const g of GESTURES) {
          const v = avg(map, g.keys)
          nb[g.id] = { v, hot: v >= g.th }
          const st = gestRef.current[g.id] || (gestRef.current[g.id] = { armed: true, last: 0 })
          if (v >= g.th && st.armed && now - st.last > 1000) { st.armed = false; st.last = now; fireGesture(g) }
          if (v < g.th * 0.6) st.armed = true
        }
        if (now - lastUiRef.current > 90) { lastUiRef.current = now; setBars(nb) }
      }
    }
    rafRef.current = requestAnimationFrame(loop)
  }

  const start = async () => {
    try {
      setStatus('Pidiendo cámara…')
      if (isNativeApp()) await requestCameraPermission()
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false,
      })
      streamRef.current = stream
      videoRef.current.srcObject = stream
      await videoRef.current.play()
      if (!landmarkerRef.current) {
        setStatus('Cargando IA de la cara…')
        const { FaceLandmarker, FilesetResolver } = await import(/* @vite-ignore */ MP_URL)
        const vision = await FilesetResolver.forVisionTasks(WASM_URL)
        landmarkerRef.current = await FaceLandmarker.createFromOptions(vision, {
          baseOptions: { modelAssetPath: MODEL_URL, delegate: 'GPU' },
          outputFaceBlendshapes: true, runningMode: 'VIDEO', numFaces: 1,
        })
      }
      setRunning(true)
      setStatus('Detectando… mueve la cara 🙂')
      rafRef.current = requestAnimationFrame(loop)
    } catch (e) {
      setStatus('Error de cámara: ' + (e?.message || e))
    }
  }

  const stop = () => {
    cancelAnimationFrame(rafRef.current)
    if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    setRunning(false)
  }

  // Apagar la cámara al salir de la pestaña (ahorro de batería)
  useEffect(() => () => stop(), [])

  return (
    <div className="flex flex-col items-center px-4 py-4 gap-3">
      {/* ===== BOSS FINAL: control de todo el móvil ===== */}
      {isNativeApp() && (
        <div className={`w-full max-w-md rounded-2xl p-4 border ${bossOn ? 'glow-border border-jarvis-accent' : 'border-white/10'} bg-jarvis-card/70`}>
          <div className="flex items-center gap-2 mb-1">
            {bossOn && <span className="live-dot" />}
            <span className="font-display tracking-wider text-sm text-jarvis-accent">CONTROL TOTAL</span>
          </div>
          <p className="text-[12px] text-jarvis-muted leading-relaxed mb-3">
            Controla <b className="text-white/90">cualquier app</b> con la cara, aunque salgas de Jarvis.
            En TikTok/Reels/Shorts, mirar arriba/abajo hace <b className="text-white/90">scroll</b>; en el resto, sube/baja el <b className="text-white/90">volumen</b>.
            Requiere activar “Jarvis Gestos” en Accesibilidad. Gasta batería (cámara siempre activa).
          </p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 mb-3">
            {SYS.map((g) => (
              <div key={g.name} className="flex justify-between text-[11.5px]">
                <span className="text-white/80">{g.name}</span>
                <span className="font-mono text-jarvis-muted">{g.act}</span>
              </div>
            ))}
          </div>
          {!bossOn ? (
            <button onClick={startBoss}
              className="w-full py-3 rounded-xl font-display tracking-wide text-[#05121a]"
              style={{ background: 'linear-gradient(100deg,#22d3ee,#818cf8)' }}>
              ⚡  Activar control total
            </button>
          ) : (
            <button onClick={stopBoss}
              className="w-full py-3 rounded-xl font-display tracking-wide text-jarvis-danger border border-jarvis-danger/40 bg-jarvis-card/60">
              ⏹  Desactivar
            </button>
          )}
          {bossMsg && <p className="text-[11.5px] font-mono text-jarvis-accent/90 mt-2 leading-relaxed">{bossMsg}</p>}
        </div>
      )}

      <p className="text-[11px] font-display tracking-wider text-jarvis-muted mt-1">— Probar detección (preview) —</p>

      <div className="relative w-full max-w-[300px] rounded-2xl overflow-hidden border border-white/10 bg-black"
        style={{ aspectRatio: '3 / 4' }}>
        <video ref={videoRef} playsInline muted
          className="absolute inset-0 w-full h-full object-cover" style={{ transform: 'scaleX(-1)' }} />
        {fire && (
          <div className="absolute left-1/2 top-3 -translate-x-1/2 font-display text-sm tracking-wide px-4 py-2 rounded-full text-jarvis-accent"
            style={{ background: 'rgba(8,10,22,.72)', border: '1px solid #22d3ee', boxShadow: '0 0 18px rgba(34,211,238,.5)' }}>
            {fire}
          </div>
        )}
      </div>

      {!running ? (
        <button onClick={start}
          className="w-full max-w-[300px] py-3 rounded-xl font-display tracking-wide text-[#05121a]"
          style={{ background: 'linear-gradient(100deg,#22d3ee,#818cf8)' }}>
          ▶  Activar cámara
        </button>
      ) : (
        <button onClick={stop}
          className="w-full max-w-[300px] py-3 rounded-xl font-display tracking-wide text-jarvis-muted border border-white/10 bg-jarvis-card/60">
          ⏹  Apagar cámara
        </button>
      )}
      <p className="text-xs font-display tracking-wider text-jarvis-muted h-4">{status}</p>

      <div className="w-full max-w-md flex flex-col gap-2 mt-1">
        {GESTURES.map((g) => {
          const b = bars[g.id] || { v: 0, hot: false }
          return (
            <div key={g.id}
              className={`rounded-xl px-3 py-2 border ${b.hot ? 'glow-border border-jarvis-accent' : 'border-white/10'} bg-jarvis-card/60`}>
              <div className="flex justify-between items-baseline text-[13px] mb-1.5">
                <span className="font-medium">{g.name}</span>
                <span className="font-mono text-[11px] text-jarvis-muted">{g.act}</span>
              </div>
              <div className="h-2 rounded-full bg-black/40 overflow-hidden">
                <i className="block h-full rounded-full"
                  style={{ width: Math.min(100, b.v * 120) + '%',
                    background: b.hot ? 'linear-gradient(90deg,#22d3ee,#c084fc)' : 'linear-gradient(90deg,#818cf8,#22d3ee)',
                    transition: 'width .07s linear' }} />
              </div>
            </div>
          )
        })}
      </div>

      {log.length > 0 && (
        <div className="w-full max-w-md mt-1 space-y-1">
          {log.map((e, i) => (
            <p key={`${e.hora}-${i}`} className="text-[11px] font-mono truncate" style={{ opacity: 1 - i * 0.14 }}>
              <span className="text-jarvis-muted">{e.hora}</span>{'  '}
              <span className="text-white/85">{e.txt}</span>
            </p>
          ))}
        </div>
      )}

      <p className="text-[11px] text-jarvis-muted max-w-md leading-relaxed mt-1">
        Fase 1: funciona con Jarvis abierto. Al abrir otra app la cámara se pausa (vuelve al entrar en Jarvis).
        Si izquierda/derecha van al revés por el espejo, dímelo y lo giro.
      </p>
    </div>
  )
}
