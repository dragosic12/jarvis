import React, { useState } from 'react'
import { API_BASE } from '../config'
import { isMobile } from '../utils/audio'

export default function TextInput({ onResult, authHeaders, authFetch }) {
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (!text.trim() || loading) return
    setLoading(true)
    try {
      const platform = isMobile() ? 'mobile' : 'linux'
      const res = await authFetch(`${API_BASE}/api/command/text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text.trim(), platform }),
      })
      const data = await res.json()
      onResult(data)
      setText('')
    } catch (err) {
      if (err.message !== 'Sesion expirada') {
        onResult({ error: err.message })
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={submit} className="w-full max-w-md flex gap-2">
      <input
        type="text"
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder='Ej: "jarvis abre youtube"'
        className="flex-1 bg-jarvis-card border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder-jarvis-muted focus:outline-none focus:border-jarvis-primary"
      />
      <button
        type="submit"
        disabled={loading || !text.trim()}
        className="bg-jarvis-primary hover:bg-jarvis-primary/80 disabled:bg-jarvis-muted text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors"
      >
        {loading ? '...' : 'Enviar'}
      </button>
    </form>
  )
}
