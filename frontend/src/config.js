// Detectar entorno: dev, tunnel directo (jarvis.swapcar.app), o nginx proxy (/jarvis/)
const isDev = window.location.port === '5173'
const isTunnel = window.location.hostname === 'jarvis.swapcar.app'

export const API_BASE = isDev
  ? 'http://localhost:4040'
  : isTunnel
    ? window.location.origin
    : `${window.location.origin}/jarvis`

export const WS_BASE = isDev
  ? 'ws://localhost:4040'
  : isTunnel
    ? `wss://${window.location.host}`
    : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/jarvis`
