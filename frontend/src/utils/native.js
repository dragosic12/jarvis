// Utilidades para cuando la web corre dentro de la APK (Capacitor)

export function isNativeApp() {
  const cap = window.Capacitor
  return !!(cap && cap.isNativePlatform && cap.isNativePlatform())
}

// Version instalada de la APK (versionName). null en navegador.
export async function getAppVersion() {
  if (!isNativeApp()) return null
  try {
    const info = await window.Capacitor?.Plugins?.App?.getInfo()
    return info?.version || null
  } catch {
    return null
  }
}

// Pide el permiso de camara (modo gestos). En navegador no hace falta (getUserMedia pregunta).
export async function requestCameraPermission() {
  if (!isNativeApp()) return true
  try {
    const r = await window.Capacitor?.Plugins?.BackgroundListening?.requestCamera()
    return !!(r && r.granted)
  } catch {
    return true
  }
}

// ---- Boss final: control por gestos a nivel de sistema ----
const bg = () => window.Capacitor?.Plugins?.BackgroundListening

export async function isAccessibilityEnabled() {
  try { const r = await bg()?.isAccessibilityEnabled(); return !!(r && r.enabled) } catch { return false }
}
export async function openAccessibilitySettings() {
  try { await bg()?.openAccessibilitySettings() } catch {}
}
export async function startFaceControl() {
  try { await bg()?.startFaceControl(); return true } catch { return false }
}
export async function stopFaceControl() {
  try { await bg()?.stopFaceControl(); return true } catch { return false }
}

// Abre una URL con el lanzador nativo de Android (ACTION_VIEW).
// Los enlaces https verificados (instagram, youtube, spotify...) abren su app
// nativa directamente; los intent:// se traducen a su esquema real.
export async function openNativeUrl(url) {
  if (!isNativeApp()) return false
  let target = url
  if (url.startsWith('intent://')) {
    const host = (url.match(/^intent:\/\/([^#]*)#Intent;/) || [])[1] || ''
    const scheme = (url.match(/;scheme=([^;]+);/) || [])[1] || 'https'
    target = `${scheme}://${host}`
  }
  const plugins = window.Capacitor?.Plugins
  // Preferir el trampolin nativo: funciona en segundo plano y con pantalla apagada
  try {
    await plugins?.BackgroundListening?.openUrl({ url: target })
    return true
  } catch {}
  const launcher = plugins?.AppLauncher
  if (!launcher) return false
  try {
    await launcher.openUrl({ url: target })
    return true
  } catch {
    const fb = url.match(/S\.browser_fallback_url=([^;]+)/)
    if (fb) {
      try {
        await launcher.openUrl({ url: decodeURIComponent(fb[1]) })
        return true
      } catch {}
    }
    return false
  }
}

// Comprueba (y pide si falta) el permiso "Mostrar sobre otras apps",
// necesario para abrir apps desde segundo plano en Android 10+
export async function ensureOverlayPermission() {
  if (!isNativeApp()) return true
  try {
    const r = await window.Capacitor?.Plugins?.BackgroundListening?.ensureOverlayPermission()
    return !!(r && r.granted)
  } catch {
    return true
  }
}

// Comprueba (y pide si falta) la exencion de ahorro de bateria: en Xiaomi,
// Samsung, etc. es lo que mata a Jarvis en segundo plano al abrir otra app
export async function ensureBatteryUnrestricted() {
  if (!isNativeApp()) return true
  try {
    const r = await window.Capacitor?.Plugins?.BackgroundListening?.ensureBatteryUnrestricted()
    return !!(r && r.granted)
  } catch {
    return true
  }
}

// Se dispara cuando la app vuelve a primer plano (tras abrir otra app, por
// ejemplo). onResume recibe true/false segun si Jarvis quedo realmente activa.
export function onAppResume(callback) {
  const appPlugin = window.Capacitor?.Plugins?.App
  if (!appPlugin) return () => {}
  const handle = appPlugin.addListener('appStateChange', ({ isActive }) => {
    if (isActive) callback()
  })
  return () => { handle?.remove?.() }
}

// ---- Escucha NATIVA (la graba el servicio Java, no el WebView) ----

// Arranca el servicio nativo de escucha con las credenciales para llamar al backend
export async function startNativeListening(apiBase, token) {
  try {
    await window.Capacitor?.Plugins?.BackgroundListening?.start({ apiBase, token })
    return true
  } catch {
    return false
  }
}

export async function stopNativeListening() {
  try {
    await window.Capacitor?.Plugins?.BackgroundListening?.stop()
  } catch {}
}

// Suscribe a las transcripciones que el servicio nativo va oyendo (para el log)
export function onNativeLog(callback) {
  const bg = window.Capacitor?.Plugins?.BackgroundListening
  if (!bg) return () => {}
  const handle = bg.addListener('log', (e) => callback(e))
  return () => { handle?.remove?.() }
}
