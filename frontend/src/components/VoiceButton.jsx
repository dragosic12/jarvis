import React, { useState, useRef, useEffect, useCallback } from 'react'
import { API_BASE } from '../config'
import { beepStart, beepStop, beepError, isMobile, getAudioContext, getSupportedMimeType, isSpeaking } from '../utils/audio'
import { isNativeApp, ensureOverlayPermission, ensureBatteryUnrestricted, onAppResume,
         startNativeListening, stopNativeListening, onNativeLog } from '../utils/native'

const SILENCE_THRESHOLD = 0.010   // sensibilidad: mas bajo = oye voz mas floja
const SILENCE_TIMEOUT = 1200      // ms de silencio tras voz para cortar segmento
const MIN_SPEECH_MS = 500         // margen inicial antes de activar VAD
const MAX_SEGMENT_MS = 15000      // tope duro por segmento
const NO_SPEECH_WAKE_MS = 8000    // esperando "jarvis": reciclar segmento sin voz
const NO_SPEECH_ARMED_MS = 6000   // esperando comando tras "jarvis": desarmar
const MIN_BLOB_SIZE = 1000

// Cualquier palabra que suene a "Jarvis": (j/y/g/h/x/ch) + a/e + r + b/v/w + i + s/z
// Cubre jarvis, yarbis, garbis, harbis, jarbis, harvis, jervis, charvis, arvis...
const WAKE_RE = /^(?:ch|[jyghx])?[ae]+r+[bvw]+i+[sz]*$/

const isWakeWord = (w) => WAKE_RE.test(w)

// Busca la wake word al inicio de la frase (palabras sueltas o partidas en dos,
// p.ej. "Y Arvis" -> "yarvis"); devuelve el comando que la sigue
function matchWakeWord(text) {
  const norm = (text || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
  const words = norm.replace(/[^a-z0-9nñ ]+/g, ' ').split(/\s+/).filter(Boolean)
  const limit = Math.min(words.length, 3)
  for (let i = 0; i < limit; i++) {
    if (isWakeWord(words[i])) {
      return { wake: true, command: words.slice(i + 1).join(' ') }
    }
    if (i + 1 < words.length && isWakeWord(words[i] + words[i + 1])) {
      return { wake: true, command: words.slice(i + 2).join(' ') }
    }
  }
  return { wake: false, command: '' }
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms))

// Espera a que el TTS termine de hablar antes de reabrir el microfono
function waitTtsIdle(maxMs = 30000) {
  return new Promise((resolve) => {
    const t0 = Date.now()
    const check = () => {
      const speaking = isSpeaking()
      if (!speaking || Date.now() - t0 > maxMs) resolve()
      else setTimeout(check, 250)
    }
    setTimeout(check, 700)
  })
}

export default function VoiceButton({ onResult, authFetch, continuous }) {
  // idle | wake (esperando "jarvis") | armed (grabando comando) | processing
  const [state, setState] = useState('idle')
  const [elapsed, setElapsed] = useState(0)
  const [log, setLog] = useState([])   // ultimas transcripciones oidas
  const volumeRef = useRef(0)
  const ringRef = useRef(null)
  const sessionRef = useRef(0)       // generacion: invalida bucles/segmentos viejos
  const streamRef = useRef(null)
  const sourceRef = useRef(null)
  const analyserRef = useRef(null)
  const segmentCtlRef = useRef(null) // { send, discard } del segmento en curso
  const armNextRef = useRef(false)   // boton pulsado en modo wake: armar ya
  const stateRef = useRef('idle')
  const continuousRef = useRef(continuous)
  continuousRef.current = continuous
  const runContinuousRef = useRef(null)
  const lastRestartRef = useRef(0)

  const setSt = (s) => { stateRef.current = s; setState(s) }

  const addLog = (text, status) => {
    const hora = new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    setLog(prev => [{ hora, text, status }, ...prev].slice(0, 5))
  }

  // Timer de grabacion (solo mientras se graba un comando)
  useEffect(() => {
    if (state !== 'armed') { setElapsed(0); return }
    const t0 = Date.now()
    const iv = setInterval(() => setElapsed(((Date.now() - t0) / 1000).toFixed(1)), 100)
    return () => clearInterval(iv)
  }, [state])

  // Anillo segun volumen real
  useEffect(() => {
    if (state !== 'wake' && state !== 'armed') return
    let raf
    const animate = () => {
      if (ringRef.current) {
        const v = volumeRef.current
        ringRef.current.style.transform = `scale(${1 + v * 0.6})`
        ringRef.current.style.opacity = 0.3 + v * 0.5
      }
      raf = requestAnimationFrame(animate)
    }
    raf = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(raf)
  }, [state])

  const release = useCallback(() => {
    try { if (sourceRef.current) sourceRef.current.disconnect() } catch {}
    if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop())
    streamRef.current = null
    sourceRef.current = null
    analyserRef.current = null
    volumeRef.current = 0
  }, [])

  // Fuerza un reinicio completo del bucle de escucha. Es la red de seguridad
  // para cuando el micrófono muere en silencio en segundo plano (Android
  // suspende/muta el audio sin lanzar ningun error de JS que podamos atrapar).
  // Con debounce: varias senales (mute, watchdog, resume) pueden dispararla casi a la vez.
  const restartListening = useCallback((reason) => {
    if (!continuousRef.current) return
    if (isNativeApp()) return  // en la APK el servicio nativo se autorregula
    const now = Date.now()
    if (now - lastRestartRef.current < 3000) return
    lastRestartRef.current = now
    addLog(`(reiniciando escucha: ${reason})`, 'sistema')
    release()
    const session = ++sessionRef.current
    runContinuousRef.current && runContinuousRef.current(session)
  }, [release])

  const acquire = useCallback(async () => {
    const track = streamRef.current && streamRef.current.getAudioTracks()[0]
    if (track && track.readyState === 'live') return
    release()
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    const ctx = getAudioContext()
    const source = ctx.createMediaStreamSource(stream)
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 512
    analyser.smoothingTimeConstant = 0.3
    source.connect(analyser)
    streamRef.current = stream
    sourceRef.current = source
    analyserRef.current = analyser

    // El sistema puede silenciar (mute) o cortar (ended) el track al perder
    // foco/pantalla apagada sin lanzar ningun error detectable de otro modo.
    const track2 = stream.getAudioTracks()[0]
    if (track2) {
      let muteTimer = null
      track2.onended = () => restartListening('microfono cortado')
      track2.onmute = () => {
        // Dar un margen: algunos silencios son transitorios (cambios de audio focus)
        muteTimer = setTimeout(() => restartListening('microfono silenciado'), 4000)
      }
      track2.onunmute = () => { if (muteTimer) { clearTimeout(muteTimer); muteTimer = null } }
    }
  }, [release, restartListening])

  // Graba un segmento con VAD; resuelve { blob, hadSpeech }
  const recordSegment = useCallback((noSpeechMs, session) => new Promise((resolve) => {
    const analyser = analyserRef.current
    const mimeType = getSupportedMimeType()
    let mr
    try { mr = new MediaRecorder(streamRef.current, mimeType ? { mimeType } : undefined) }
    catch { mr = new MediaRecorder(streamRef.current) }

    const chunks = []
    const t0 = Date.now()
    const dataArray = new Float32Array(analyser.fftSize)
    let hadSpeech = false
    let forced = false
    let discarded = false
    let silenceStart = null
    let finished = false

    const finalize = () => {
      segmentCtlRef.current = null
      const blob = chunks.length ? new Blob(chunks, { type: mr.mimeType || mimeType || 'audio/webm' }) : null
      resolve({ blob, hadSpeech: discarded ? false : (hadSpeech || forced) })
    }

    const finish = () => {
      if (finished) return
      finished = true
      clearInterval(iv)
      try {
        if (mr.state === 'recording') mr.stop()
        else finalize()
      } catch { finalize() }
    }

    const iv = setInterval(() => {
      if (session !== sessionRef.current) { discarded = true; return finish() }
      analyser.getFloatTimeDomainData(dataArray)
      let sum = 0
      for (let i = 0; i < dataArray.length; i++) sum += dataArray[i] * dataArray[i]
      const rms = Math.sqrt(sum / dataArray.length)
      volumeRef.current = Math.min(rms * 8, 1)

      const ms = Date.now() - t0
      if (ms < MIN_SPEECH_MS) return
      if (rms > SILENCE_THRESHOLD) {
        hadSpeech = true
        silenceStart = null
      } else if (hadSpeech) {
        if (!silenceStart) silenceStart = Date.now()
        else if (Date.now() - silenceStart > SILENCE_TIMEOUT) return finish()
      } else if (ms > noSpeechMs) {
        return finish()
      }
      if (ms > MAX_SEGMENT_MS) return finish()
    }, 80)

    segmentCtlRef.current = {
      send: () => { forced = true; finish() },
      discard: () => { discarded = true; finish() },
    }

    mr.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data) }
    mr.onstop = finalize
    mr.onerror = () => { discarded = true; finish() }
    mr.start(250)
  }), [])

  const sendCommandAudio = async (blob) => {
    const mt = blob.type || 'audio/webm'
    const ext = mt.includes('mp4') ? 'mp4' : mt.includes('ogg') ? 'ogg' : 'webm'
    const form = new FormData()
    form.append('audio', blob, `audio.${ext}`)
    const platform = isMobile() ? 'mobile' : 'linux'
    const res = await authFetch(`${API_BASE}/api/command?platform=${platform}`, { method: 'POST', body: form })
    const data = await res.json()
    if (data.transcript && data.transcript.text) {
      addLog(data.transcript.text, data.intent && data.intent.matched ? 'ejecutado' : 'no reconocido')
    }
    onResult(data)
  }

  const transcribeBlob = async (blob) => {
    const mt = blob.type || 'audio/webm'
    const ext = mt.includes('mp4') ? 'mp4' : mt.includes('ogg') ? 'ogg' : 'webm'
    const form = new FormData()
    form.append('audio', blob, `audio.${ext}`)
    const res = await authFetch(`${API_BASE}/api/transcribe`, { method: 'POST', body: form })
    return res.json()
  }

  const sendCommandText = async (text) => {
    const platform = isMobile() ? 'mobile' : 'linux'
    const res = await authFetch(`${API_BASE}/api/command/text`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, platform }),
    })
    const data = await res.json()
    addLog(text, data.intent && data.intent.matched ? 'ejecutado' : 'no reconocido')
    onResult(data)
  }

  // Bucle de escucha continua con wake word
  const runContinuous = async (session) => {
    let armed = false
    let micRetries = 0
    while (session === sessionRef.current) {
      // En navegador, el background corta el mic: soltar y esperar a volver.
      // En la APK el servicio en primer plano mantiene el mic con pantalla apagada.
      if (document.hidden && !isNativeApp()) {
        release()
        await sleep(800)
        continue
      }
      try {
        await acquire()
        micRetries = 0
      } catch (err) {
        micRetries++
        // En la APK, en segundo plano el sistema a veces niega temporalmente
        // getUserMedia (no es un fallo real): reintentar sin rendirse nunca,
        // con espera creciente, en vez de apagar la escucha con un error.
        if (isNativeApp()) {
          await sleep(Math.min(1000 * micRetries, 10000))
          continue
        }
        if (micRetries >= 3) {
          if (session === sessionRef.current) onResult({ error: `Error microfono: ${err.message}` })
          break
        }
        await sleep(1000)
        continue
      }
      if (session !== sessionRef.current) break

      if (armed) beepStart()
      setSt(armed ? 'armed' : 'wake')

      const seg = await recordSegment(armed ? NO_SPEECH_ARMED_MS : NO_SPEECH_WAKE_MS, session)
      if (session !== sessionRef.current) break

      // Boton pulsado durante la espera: armar directamente
      if (armNextRef.current) {
        armNextRef.current = false
        armed = true
        continue
      }

      if (!seg.blob || seg.blob.size < MIN_BLOB_SIZE || !seg.hadSpeech) {
        if (armed) { armed = false; beepError() } // no llego comando tras "jarvis"
        continue
      }

      setSt('processing')
      try {
        if (armed) {
          armed = false
          beepStop()
          await sendCommandAudio(seg.blob)
        } else {
          const transcript = await transcribeBlob(seg.blob)
          const { wake, command } = matchWakeWord(transcript.text)
          if (!wake) {
            // No iba dirigido a Jarvis: descartar (pero dejarlo en el log)
            if (transcript.text) addLog(transcript.text, 'ignorado')
            continue
          }
          if (command) {
            beepStop()
            await sendCommandText(command)
          } else {
            addLog(transcript.text, 'armado')
            armed = true               // solo "jarvis": esperar el comando
            continue
          }
        }
      } catch (err) {
        if (err.message === 'Sesion expirada') break
        onResult({ error: `Error: ${err.message}` })
      }
      await waitTtsIdle()
    }
    if (session === sessionRef.current) {
      release()
      setSt('idle')
    }
  }
  runContinuousRef.current = runContinuous

  // Grabacion manual de un solo comando (modo no continuo)
  const startOneShot = async () => {
    const session = ++sessionRef.current
    try {
      await acquire()
    } catch (err) {
      onResult({ error: `Error microfono: ${err.message}` })
      return
    }
    setSt('armed')
    beepStart()
    const seg = await recordSegment(MAX_SEGMENT_MS, session)
    if (session !== sessionRef.current) return
    release()
    if (!seg.blob || seg.blob.size < MIN_BLOB_SIZE || !seg.hadSpeech) {
      setSt('idle')
      return
    }
    beepStop()
    setSt('processing')
    try {
      await sendCommandAudio(seg.blob)
    } catch (err) {
      if (err.message !== 'Sesion expirada') onResult({ error: `Error: ${err.message}` })
    }
    setSt('idle')
  }

  // El toggle controla la sesion continua; leerlo en vivo evita closures obsoletos
  useEffect(() => {
    if (continuous && isNativeApp()) {
      // APK: la escucha la lleva el servicio NATIVO (sobrevive a la app cerrada
      // y a la pantalla apagada). El WebView solo muestra el log que emite.
      ensureOverlayPermission()
      ensureBatteryUnrestricted()
      const token = localStorage.getItem('jarvis_token') || ''
      startNativeListening(API_BASE, token)
      setSt('wake')
      const off = onNativeLog(({ text, status }) => addLog(text, status))
      return () => { off() }
    }
    if (continuous) {
      // Navegador/PWA: bucle de escucha en JS (solo con la pagina visible)
      const session = ++sessionRef.current
      runContinuous(session)
    } else {
      if (isNativeApp()) stopNativeListening()
      sessionRef.current++
      if (segmentCtlRef.current) segmentCtlRef.current.discard()
      release()
      setSt('idle')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [continuous])

  // Autocuracion 1: al volver Jarvis a primer plano (p.ej. si vuelves a abrirlo
  // tras usar Instagram), el audio puede haber quedado muerto sin avisar.
  useEffect(() => {
    return onAppResume(() => restartListening('app en primer plano'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Autocuracion 2 (la red de verdad): si sales de la otra app hacia el
  // escritorio en vez de volver a Jarvis, nunca llega el evento de "resume" -
  // este vigilante corre igualmente en segundo plano (gracias al servicio
  // foreground) y revisa cada 10s que el microfono siga vivo.
  useEffect(() => {
    const iv = setInterval(() => {
      if (!continuousRef.current) return
      const track = streamRef.current && streamRef.current.getAudioTracks()[0]
      if (!track || track.readyState !== 'live' || track.muted) {
        restartListening('vigilancia periodica')
      }
    }, 10000)
    return () => clearInterval(iv)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => () => {
    sessionRef.current++
    if (segmentCtlRef.current) segmentCtlRef.current.discard()
    release()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleClick = () => {
    // En la APK con escucha continua, el micro lo tiene el servicio nativo:
    // el boton no debe abrir una grabacion JS en paralelo.
    if (isNativeApp() && continuousRef.current) return
    if (state === 'processing') return
    if (state === 'idle') startOneShot()
    else if (state === 'wake') {
      // Saltar la wake word: armar grabacion de comando ya
      armNextRef.current = true
      if (segmentCtlRef.current) segmentCtlRef.current.discard()
    } else if (state === 'armed') {
      // Parar y enviar lo grabado
      if (segmentCtlRef.current) segmentCtlRef.current.send()
    }
  }

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative w-24 h-24">
        {(state === 'wake' || state === 'armed') && (
          <>
            {/* halo que respira detras del boton */}
            <div className={`mic-halo ${state === 'armed' ? 'armed' : ''}`} />
            {/* anillos de radar que se expanden */}
            <div className={`absolute inset-0 ${state === 'armed' ? 'text-red-400' : 'text-jarvis-accent'}`}>
              <span className="radar-ring" />
              <span className="radar-ring" style={{ animationDelay: '0.8s' }} />
              <span className="radar-ring" style={{ animationDelay: '1.6s' }} />
            </div>
            {/* anillo reactivo al volumen real de tu voz */}
            <div
              ref={ringRef}
              className={`absolute inset-0 rounded-full ${state === 'armed' ? 'bg-red-500/25' : 'bg-jarvis-accent/25'}`}
              style={{ transition: 'transform 0.1s ease-out, opacity 0.1s ease-out', transform: 'scale(1)', opacity: 0.3 }}
            />
          </>
        )}
        <button
          onClick={handleClick}
          disabled={state === 'processing'}
          className={`relative w-24 h-24 rounded-full flex items-center justify-center text-white transition-all duration-300 ${
            state === 'processing'
              ? 'bg-jarvis-muted cursor-wait'
              : state === 'armed'
                ? 'bg-gradient-to-br from-red-500 to-red-700 scale-110'
                : state === 'wake'
                  ? 'bg-gradient-to-br from-jarvis-accent to-jarvis-primary'
                  : 'bg-gradient-to-br from-jarvis-primary to-jarvis-accent hover:scale-105 active:scale-95'
          }`}
          style={{ boxShadow: state === 'armed'
            ? '0 0 22px rgba(239,68,68,0.6), 0 0 48px rgba(239,68,68,0.35), inset 0 2px 10px rgba(255,255,255,0.25)'
            : state === 'processing'
              ? 'none'
              : '0 0 22px rgba(34,211,238,0.5), 0 0 48px rgba(99,102,241,0.35), inset 0 2px 10px rgba(255,255,255,0.25)' }}
        >
          {state === 'processing' ? (
            <svg className="w-8 h-8 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4" strokeLinecap="round"/>
            </svg>
          ) : state === 'armed' ? (
            <svg className="w-8 h-8" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="2"/>
            </svg>
          ) : (
            <svg className="w-8 h-8" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 1a4 4 0 0 0-4 4v7a4 4 0 0 0 8 0V5a4 4 0 0 0-4-4z"/>
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
              <line x1="12" y1="19" x2="12" y2="23" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
            </svg>
          )}
        </button>
      </div>

      <p className="text-xs font-display tracking-wider h-4 flex items-center gap-1">
        {state === 'processing' ? (
          <span className="text-jarvis-accent/90">TRANSCRIBIENDO<span className="dot-flow"><span>.</span><span>.</span><span>.</span></span></span>
        ) : state === 'armed' ? (
          <span className="text-red-400">GRABANDO · {elapsed}s</span>
        ) : state === 'wake' ? (
          <span className="text-jarvis-accent/90">ESCUCHANDO · DI "JARVIS"<span className="dot-flow"><span>.</span><span>.</span><span>.</span></span></span>
        ) : (
          <span className="text-jarvis-muted">PULSA PARA HABLAR</span>
        )}
      </p>

      {log.length > 0 && (
        <div className="w-full max-w-md space-y-1 px-2">
          {log.map((e, i) => (
            <p key={`${e.hora}-${i}`} className="text-[11px] font-mono truncate" style={{ opacity: 1 - i * 0.15 }}>
              <span className="text-jarvis-muted">{e.hora}</span>{' '}
              <span className={
                e.status === 'ejecutado' ? 'text-jarvis-success'
                  : e.status === 'armado' ? 'text-jarvis-accent'
                    : e.status === 'no reconocido' ? 'text-yellow-400'
                      : 'text-jarvis-muted'
              }>[{e.status}]</span>{' '}
              <span className="text-white/80">"{e.text}"</span>
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
