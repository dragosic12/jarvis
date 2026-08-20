import React, { useState, useEffect } from 'react'
import { useAuth } from './hooks/useAuth'
import LoginScreen from './components/LoginScreen'
import VoiceButton from './components/VoiceButton'
import ResultPanel from './components/ResultPanel'
import CommandList from './components/CommandList'
import TextInput from './components/TextInput'
import LogPanel from './components/LogPanel'
import GestureMode from './components/GestureMode'
import Settings from './components/Settings'
import Cheatsheet from './components/Cheatsheet'
import { getAppVersion, stopSpeaking } from './utils/native'
import { API_BASE } from './config'

const TABS = [
  { id: 'voice', label: 'Voz' },
  { id: 'guia', label: 'Guía' },
  { id: 'commands', label: 'Comandos' },
  { id: 'ajustes', label: 'Ajustes' },
  { id: 'gestos', label: 'Gestos' },
  { id: 'logs', label: 'Historial' },
]

export default function App() {
  const { isLoggedIn, login, logout, error, authHeaders, authFetch } = useAuth()
  const [tab, setTab] = useState('voice')
  const [lastResult, setLastResult] = useState(null)
  // La escucha continua se recuerda: si estaba activada, sigue activa al reabrir
  const [continuous, setContinuous] = useState(() => localStorage.getItem('jarvis_continuous') === '1')
  const [installPrompt, setInstallPrompt] = useState(null)
  const [ver, setVer] = useState(null)        // version instalada de la APK
  const [latest, setLatest] = useState(null)  // ultima version publicada

  useEffect(() => {
    getAppVersion().then(setVer)
    fetch(`${API_BASE}/version.json?t=${Date.now()}`)
      .then((r) => r.json()).then((d) => setLatest(d && d.version)).catch(() => {})
  }, [])

  useEffect(() => {
    localStorage.setItem('jarvis_continuous', continuous ? '1' : '0')
  }, [continuous])

  useEffect(() => {
    const handler = (e) => { e.preventDefault(); setInstallPrompt(e) }
    window.addEventListener('beforeinstallprompt', handler)
    return () => window.removeEventListener('beforeinstallprompt', handler)
  }, [])

  const handleInstall = async () => {
    if (!installPrompt) return
    installPrompt.prompt()
    const r = await installPrompt.userChoice
    if (r.outcome === 'accepted') setInstallPrompt(null)
  }

  if (!isLoggedIn) {
    return <LoginScreen onLogin={login} error={error} />
  }

  // Cambiar de pestaña con un gesto (mirar izquierda/derecha)
  const cycleTab = (dir) => {
    const i = TABS.findIndex((t) => t.id === tab)
    const n = (i + dir + TABS.length) % TABS.length
    setTab(TABS[n].id)
  }

  return (
    <div className="relative min-h-[100dvh] flex flex-col">
      {/* Fondo futurista animado (rejilla HUD + orbes) */}
      <div className="jarvis-bg-fx">
        <div className="jarvis-orb" style={{ width: 260, height: 260, top: '-40px', left: '-40px',
          background: 'radial-gradient(circle, rgba(34,211,238,0.55), transparent 70%)' }} />
        <div className="jarvis-orb" style={{ width: 320, height: 320, bottom: '-80px', right: '-60px',
          animationDelay: '6s', background: 'radial-gradient(circle, rgba(168,85,247,0.5), transparent 70%)' }} />
      </div>

      <div className="relative z-10 flex flex-col min-h-[100dvh]">
        {/* Header */}
        <header className="glass border-b border-white/10 px-4 py-2.5 flex items-center gap-3">
          <div className="jarvis-core w-9 h-9">
            <span className="font-display text-[11px] font-bold text-white/95" style={{ letterSpacing: 0 }}>J</span>
          </div>
          <h1 className="jarvis-title text-xl">JARVIS</h1>
          {ver && <span className="font-mono text-[10px] text-jarvis-muted self-end mb-1">v{ver}</span>}
          {ver && latest && latest !== ver && (
            <a href={`${API_BASE}/jarvis.apk`}
              className="font-display text-[10px] tracking-wide text-jarvis-accent border border-jarvis-accent/50 rounded-full px-2 py-0.5 glow-border"
              style={{ animation: 'live-pulse 1.6s ease-in-out infinite' }}>
              ⬆ v{latest}
            </a>
          )}
          <div className="ml-auto flex items-center gap-2">
            {installPrompt && (
              <button onClick={handleInstall}
                className="text-[11px] bg-jarvis-primary/20 text-jarvis-primary px-2.5 py-1 rounded-lg border border-jarvis-primary/30">
                Instalar
              </button>
            )}
            <button onClick={logout}
              className="text-[11px] font-display text-jarvis-muted hover:text-jarvis-danger transition-colors">
              SALIR
            </button>
          </div>
        </header>

        {/* Tabs */}
        <nav className="flex glass border-b border-white/5 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`relative flex-shrink-0 px-4 py-2.5 text-xs font-display font-semibold tracking-wide whitespace-nowrap transition-colors ${
                tab === t.id ? 'text-jarvis-accent' : 'text-jarvis-muted hover:text-white'
              }`}
            >
              {t.label}
              {tab === t.id && (
                <span className="absolute bottom-0 left-1/2 -translate-x-1/2 h-[2px] w-3/5 rounded-full"
                  style={{ background: 'linear-gradient(90deg, transparent, #22d3ee, transparent)',
                    boxShadow: '0 0 8px #22d3ee' }} />
              )}
            </button>
          ))}
        </nav>

        {/* Content */}
        <main className="flex-1 overflow-auto">
          {tab === 'voice' && (
            <div className="flex flex-col items-center px-4 py-5 gap-4">
              {/* Toggle continuo */}
              <button
                onClick={() => setContinuous(!continuous)}
                className={`flex items-center gap-2 text-xs font-display tracking-wide px-4 py-2 rounded-full transition-all ${
                  continuous
                    ? 'text-jarvis-accent bg-jarvis-accent/10 glow-border'
                    : 'bg-jarvis-card/60 text-jarvis-muted border border-white/10'
                }`}
              >
                {continuous && <span className="live-dot" />}
                {continuous ? 'ESCUCHA CONTINUA · DI "JARVIS"' : 'ACTIVAR ESCUCHA CONTINUA'}
              </button>

              <VoiceButton
                onResult={setLastResult}
                authHeaders={authHeaders}
                authFetch={authFetch}
                continuous={continuous}
              />
              {/* Botón para cortar la voz de Jarvis al instante (100% fiable) */}
              <button
                onClick={() => stopSpeaking()}
                className="flex items-center gap-2 text-sm font-display font-semibold tracking-wide px-6 py-2.5 rounded-full bg-jarvis-danger/15 text-jarvis-danger border border-jarvis-danger/40 active:scale-95 transition-transform"
              >
                ⏹ PARAR
              </button>
              <TextInput onResult={setLastResult} authHeaders={authHeaders} authFetch={authFetch} />
              {lastResult && <ResultPanel result={lastResult} authHeaders={authHeaders} authFetch={authFetch} />}
            </div>
          )}
          {tab === 'commands' && <CommandList authHeaders={authHeaders} authFetch={authFetch} />}
          {tab === 'logs' && <LogPanel authHeaders={authHeaders} authFetch={authFetch} />}
          {tab === 'gestos' && (
            <GestureMode
              authFetch={authFetch}
              onTab={cycleTab}
              onToggleListen={() => setContinuous((c) => !c)}
            />
          )}
          {tab === 'ajustes' && <Settings authFetch={authFetch} />}
          {tab === 'guia' && <Cheatsheet />}
        </main>
      </div>
    </div>
  )
}
