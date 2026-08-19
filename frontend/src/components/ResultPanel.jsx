import React, { useState, useEffect, useRef } from 'react'
import { API_BASE } from '../config'
import { speak, beepSuccess, beepError } from '../utils/audio'
import { isNativeApp, openNativeUrl } from '../utils/native'

export default function ResultPanel({ result, authHeaders, authFetch }) {
  const [confirming, setConfirming] = useState(false)
  const [opened, setOpened] = useState(false)
  const linkRef = useRef(null)
  const cameraRef = useRef(null)

  const execResult = result?.result
  const intent = result?.intent
  const transcript = result?.transcript
  const hasUrl = execResult?.data?.type === 'open_url'
  const isDevice = execResult?.data?.type === 'device_action'
  const isSpoken = execResult?.data?.type === 'spoken_response'
  const isSilent = intent?.silent
  const url = execResult?.data?.url

  // Reset on new result
  useEffect(() => { setOpened(false) }, [result])

  // Auto-actions on result
  useEffect(() => {
    if (opened) return

    // Spoken response (question → TTS)
    if (isSpoken && execResult?.data?.text) {
      setOpened(true)
      beepSuccess()
      speak(execResult.data.text)
      return
    }

    // URL open
    if (hasUrl && url) {
      setOpened(true)
      if (isSilent) beepSuccess()
      if (isNativeApp()) {
        // Dentro de la APK: lanzador nativo, sin restricciones del navegador
        openNativeUrl(url)
      } else if (!url.startsWith('http')) {
        // Deep link nativo (intent://): navegar directo, sin pestana nueva
        window.location.href = url
      } else {
        const w = window.open(url, '_blank')
        if (!w && linkRef.current) linkRef.current.click()
      }
      return
    }

    // Camera
    if (isDevice && execResult?.data?.action === 'camera') {
      setOpened(true)
      beepSuccess()
      if (isNativeApp()) {
        // APK: abrir la app de camara nativa directamente (via trampolin)
        openNativeUrl('camera')
      } else {
        setTimeout(() => { if (cameraRef.current) cameraRef.current.click() }, 200)
      }
      return
    }

    // Server command result
    if (execResult?.data?.stdout !== undefined) {
      beepSuccess()
      setOpened(true)
    }

    // Error
    if (execResult && !execResult.success) {
      beepError()
      setOpened(true)
    }
  }, [hasUrl, url, isDevice, isSpoken, isSilent, opened])

  if (result.error) {
    return (
      <div className="w-full max-w-md bg-jarvis-danger/10 border border-jarvis-danger/30 rounded-xl p-3 animate-fade-in">
        <p className="text-jarvis-danger text-sm">{result.error}</p>
      </div>
    )
  }

  const needsConfirm = execResult?.data?.needs_confirm

  const confirmAction = async () => {
    setConfirming(true)
    try {
      await authFetch(`${API_BASE}/api/system/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: execResult.data.command }),
      })
    } catch {}
    setConfirming(false)
  }

  // Silent mode: minimal feedback for URLs that already opened
  if (isSilent && hasUrl && opened) {
    return (
      <div className="w-full max-w-md animate-fade-in">
        <div className="bg-jarvis-success/10 border border-jarvis-success/20 rounded-xl px-4 py-2.5 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-jarvis-success" />
          <p className="text-sm text-jarvis-success flex-1 truncate">{intent?.trigger}</p>
          {!isNativeApp() && (
            <a ref={linkRef} href={url} target="_blank" rel="noopener noreferrer"
              className="text-xs text-jarvis-accent hover:underline">Abrir</a>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="w-full max-w-md space-y-2 animate-fade-in">
      {/* Transcripcion */}
      {transcript && (
        <div className="bg-jarvis-card border border-white/10 rounded-xl px-4 py-2.5">
          <p className="text-xs text-jarvis-muted mb-0.5">Transcripcion ({transcript.transcribe_time}s)</p>
          <p className="text-white text-sm font-medium">"{transcript.text}"</p>
        </div>
      )}

      {/* Intent */}
      {intent && !isSilent && (
        <div className={`border rounded-xl px-4 py-2.5 ${
          intent.matched ? 'bg-jarvis-success/10 border-jarvis-success/30' : 'bg-yellow-500/10 border-yellow-500/30'
        }`}>
          {intent.matched ? (
            <div className="flex items-center gap-2">
              <span className="text-xs bg-jarvis-success/20 text-jarvis-success px-2 py-0.5 rounded-full">{intent.category}</span>
              <span className="text-xs text-jarvis-muted">{intent.trigger}</span>
              <span className="text-xs text-white flex-1 truncate">{intent.description}</span>
            </div>
          ) : (
            <p className="text-sm text-yellow-400">{intent.error || 'Comando no reconocido'}</p>
          )}
        </div>
      )}

      {/* Resultado */}
      {execResult && (
        <div className={`border rounded-xl p-4 ${
          execResult.success ? 'bg-jarvis-card border-white/10' : 'bg-jarvis-danger/10 border-jarvis-danger/30'
        }`}>
          {/* Respuesta hablada (pregunta) */}
          {isSpoken && (
            <div className="space-y-2">
              {execResult.data.question && (
                <p className="text-xs text-jarvis-muted italic">"{execResult.data.question}"</p>
              )}
              <p className="text-sm text-white leading-relaxed">{execResult.data.text}</p>
              <button
                onClick={() => speak(execResult.data.text)}
                className="text-xs text-jarvis-accent hover:underline flex items-center gap-1"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>
                </svg>
                Repetir
              </button>
            </div>
          )}

          {/* URL fallback button (solo web: en la APK todo se abre solo) */}
          {hasUrl && !isSilent && isNativeApp() && (
            <p className="text-sm text-white">{execResult.message}</p>
          )}
          {hasUrl && !isSilent && !isNativeApp() && (
            <>
              <p className="text-sm text-white mb-2">{execResult.message}</p>
              <a ref={linkRef} href={url} target="_blank" rel="noopener noreferrer"
                className="flex items-center justify-center gap-2 bg-jarvis-primary hover:bg-jarvis-primary/80 active:scale-95 text-white px-4 py-3 rounded-xl text-base font-semibold transition-all">
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                  <polyline points="15 3 21 3 21 9"/>
                  <line x1="10" y1="14" x2="21" y2="3"/>
                </svg>
                Abrir {intent?.trigger || ''}
              </a>
            </>
          )}

          {/* Camera (solo web: en la APK se abre la app de camara directamente) */}
          {isDevice && execResult.data.action === 'camera' && !isNativeApp() && (
            <>
              <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={() => {}} />
              <button onClick={() => cameraRef.current?.click()}
                className="flex items-center justify-center gap-2 bg-jarvis-primary hover:bg-jarvis-primary/80 active:scale-95 text-white px-4 py-3 rounded-xl text-base font-semibold transition-all w-full">
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
                  <circle cx="12" cy="13" r="4"/>
                </svg>
                Abrir camara
              </button>
            </>
          )}

          {/* Server output */}
          {execResult.data?.stdout && (
            <>
              <p className="text-sm text-white mb-2">{execResult.message?.substring(0, 60)}</p>
              <pre className="text-xs text-jarvis-accent bg-black/30 rounded-lg p-3 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
                {execResult.data.stdout}
              </pre>
            </>
          )}

          {/* Info */}
          {execResult.data?.type === 'info' && (
            <p className="text-xs text-jarvis-accent bg-black/30 rounded-lg p-3">
              {execResult.data.text}
            </p>
          )}

          {/* System confirm */}
          {needsConfirm && (
            <button onClick={confirmAction} disabled={confirming}
              className="mt-3 bg-jarvis-danger hover:bg-red-700 text-white px-4 py-2.5 rounded-lg text-sm font-medium w-full">
              {confirming ? 'Ejecutando...' : `Confirmar: ${execResult.data.action}`}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
