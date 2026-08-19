import { API_BASE } from '../config'

let audioCtx = null
let ttsAudio = null   // <audio> con la voz del servidor en curso

function getCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)()
  if (audioCtx.state === 'suspended') audioCtx.resume()
  return audioCtx
}

// Singleton compartido para beeps y analyser (evita limite de AudioContexts del navegador)
export function getAudioContext() {
  return getCtx()
}

export function getSupportedMimeType() {
  const types = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
  ]
  for (const t of types) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(t)) return t
  }
  return null
}

export function beep(freq = 800, duration = 120, volume = 0.2) {
  try {
    const ctx = getCtx()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.frequency.value = freq
    osc.type = 'sine'
    gain.gain.setValueAtTime(volume, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration / 1000)
    osc.start(ctx.currentTime)
    osc.stop(ctx.currentTime + duration / 1000)
  } catch {}
}

export function beepStart() {
  beep(600, 100, 0.15)
  setTimeout(() => beep(900, 100, 0.15), 120)
}

export function beepStop() {
  beep(900, 100, 0.15)
  setTimeout(() => beep(600, 100, 0.15), 120)
}

export function beepSuccess() {
  beep(800, 80, 0.1)
  setTimeout(() => beep(1200, 120, 0.1), 100)
}

export function beepError() {
  beep(300, 200, 0.15)
}

// Voz de Jarvis: primero la del servidor (masculina, natural, /api/tts). Si falla
// la red, cae a la voz del navegador. Asi no depende del motor TTS del movil.
export function speak(text, onEnd) {
  if (!text) { if (onEnd) onEnd(); return }
  let finished = false
  const finish = () => { if (finished) return; finished = true; if (onEnd) onEnd() }
  const fallback = () => { if (finished) return; finished = true; speakBrowser(text, onEnd) }
  try {
    stopSpeak()
    if ('speechSynthesis' in window) speechSynthesis.cancel()
    const audio = new Audio(`${API_BASE}/api/tts?text=${encodeURIComponent(text)}`)
    ttsAudio = audio
    audio.onended = finish
    audio.onerror = fallback
    const p = audio.play()
    if (p && p.catch) p.catch(fallback)
  } catch {
    fallback()
  }
}

function speakBrowser(text, onEnd) {
  if (!('speechSynthesis' in window)) { if (onEnd) onEnd(); return }
  speechSynthesis.cancel()
  const utt = new SpeechSynthesisUtterance(text)
  utt.lang = 'es-ES'
  utt.rate = 1.05
  utt.pitch = 1
  if (onEnd) utt.onend = onEnd
  utt.onerror = () => { if (onEnd) onEnd() }
  speechSynthesis.speak(utt)
}

export function stopSpeak() {
  try { if (ttsAudio) { ttsAudio.pause(); ttsAudio.currentTime = 0 } } catch {}
  ttsAudio = null
}

// true si Jarvis esta hablando ahora (voz del servidor o del navegador)
export function isSpeaking() {
  const synth = 'speechSynthesis' in window && (speechSynthesis.speaking || speechSynthesis.pending)
  const audio = !!(ttsAudio && !ttsAudio.paused && !ttsAudio.ended)
  return synth || audio
}

export function isMobile() {
  return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
}
