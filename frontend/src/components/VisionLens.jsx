import React, { useState, useRef } from 'react'
import { API_BASE } from '../config'

// Reduce la imagen en el navegador (rapido de subir y suficiente para analizar).
function downscale(file, maxDim = 1280, quality = 0.85) {
  return new Promise((resolve) => {
    const img = new Image()
    const url = URL.createObjectURL(file)
    img.onload = () => {
      let { width, height } = img
      const scale = Math.min(1, maxDim / Math.max(width, height))
      width = Math.round(width * scale)
      height = Math.round(height * scale)
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      canvas.getContext('2d').drawImage(img, 0, 0, width, height)
      URL.revokeObjectURL(url)
      resolve(canvas.toDataURL('image/jpeg', quality))
    }
    img.onerror = () => { URL.revokeObjectURL(url); resolve(null) }
    img.src = url
  })
}

export default function VisionLens({ authFetch }) {
  const [img, setImg] = useState(null)
  const [msgs, setMsgs] = useState([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const fileRef = useRef(null)

  const ask = async (question, image) => {
    const im = image || img
    if (!im || busy) return
    setBusy(true)
    if (question) setMsgs((m) => [...m, { role: 'user', text: question }])
    try {
      const r = await authFetch(`${API_BASE}/api/vision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: im, question: question || undefined }),
      })
      const d = await r.json()
      setMsgs((m) => [...m, { role: 'jarvis', text: d.answer || 'No he podido analizarla.' }])
    } catch {
      setMsgs((m) => [...m, { role: 'jarvis', text: 'Error de conexión con el servidor.' }])
    }
    setBusy(false)
  }

  const onPick = async (e) => {
    const file = e.target.files && e.target.files[0]
    if (!file) return
    const data = await downscale(file)
    e.target.value = ''
    if (!data) return
    setImg(data)
    setMsgs([])
    ask('', data)
  }

  const send = () => { const t = q.trim(); if (t) { setQ(''); ask(t) } }

  return (
    <div className="px-4 py-5 max-w-md mx-auto">
      <h2 className="jarvis-title text-lg mb-1">LENS</h2>
      <p className="text-[11px] text-jarvis-muted mb-4">
        Haz o elige una foto y pregúntale lo que quieras: qué es, marca/modelo, para qué sirve, cómo se usa…
      </p>

      <input ref={fileRef} type="file" accept="image/*" onChange={onPick} className="hidden" />

      {!img ? (
        <button onClick={() => fileRef.current && fileRef.current.click()}
          className="w-full h-44 bg-jarvis-card/60 border border-dashed border-white/20 rounded-2xl flex flex-col items-center justify-center gap-2 text-jarvis-muted">
          <span className="text-4xl">📷</span>
          <span className="font-display tracking-wide text-sm">Hacer o elegir una foto</span>
        </button>
      ) : (
        <div className="mb-3">
          <img src={img} alt="" className="w-full max-h-64 object-contain rounded-2xl border border-white/10 bg-black/30" />
          <button onClick={() => fileRef.current && fileRef.current.click()}
            className="w-full mt-2 bg-jarvis-card/60 text-jarvis-muted border border-white/10 rounded-xl py-2 text-xs font-display tracking-wide">
            🔄 Cambiar foto
          </button>
        </div>
      )}

      <div className="mt-3 space-y-2">
        {msgs.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : 'text-left'}>
            <span className={`inline-block px-3 py-2 rounded-2xl text-sm max-w-[85%] ${
              m.role === 'user'
                ? 'bg-jarvis-accent/20 text-jarvis-accent'
                : 'bg-jarvis-card/70 text-white/90 border border-white/10'
            }`}>{m.text}</span>
          </div>
        ))}
        {busy && <div className="text-left"><span className="inline-block px-3 py-2 rounded-2xl text-sm bg-jarvis-card/70 text-jarvis-muted border border-white/10">Analizando…</span></div>}
      </div>

      {img && (
        <div className="flex gap-2 mt-4 sticky bottom-2">
          <input value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') send() }}
            placeholder="Pregunta algo sobre la foto…"
            className="flex-1 bg-jarvis-card/70 border border-white/10 rounded-xl py-2.5 px-3 text-sm text-white placeholder:text-jarvis-muted" />
          <button onClick={send} disabled={busy || !q.trim()}
            className="bg-jarvis-accent/20 text-jarvis-accent border border-jarvis-accent/40 rounded-xl px-4 font-display tracking-wide disabled:opacity-40">
            ➤
          </button>
        </div>
      )}
    </div>
  )
}
