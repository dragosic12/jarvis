import React, { useState } from 'react'

export default function LoginScreen({ onLogin, error }) {
  const [pin, setPin] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (!pin.trim() || loading) return
    setLoading(true)
    await onLogin(pin.trim())
    setLoading(false)
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-jarvis-dark px-4">
      <div className="w-full max-w-xs space-y-6">
        <div className="text-center">
          <div className="w-16 h-16 mx-auto rounded-full bg-gradient-to-br from-jarvis-primary to-jarvis-accent flex items-center justify-center text-white font-bold text-2xl mb-4">
            J
          </div>
          <h1 className="text-xl font-semibold bg-gradient-to-r from-jarvis-primary to-jarvis-accent bg-clip-text text-transparent">
            Jarvis
          </h1>
          <p className="text-sm text-jarvis-muted mt-1">Introduce tu PIN</p>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <input
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            value={pin}
            onChange={e => setPin(e.target.value)}
            placeholder="PIN"
            autoFocus
            className="w-full bg-jarvis-card border border-white/10 rounded-xl px-4 py-3 text-center text-2xl text-white tracking-[0.5em] placeholder-jarvis-muted focus:outline-none focus:border-jarvis-primary"
          />
          {error && (
            <p className="text-jarvis-danger text-sm text-center">{error}</p>
          )}
          <button
            type="submit"
            disabled={loading || !pin.trim()}
            className="w-full bg-gradient-to-r from-jarvis-primary to-jarvis-accent hover:opacity-90 disabled:opacity-40 text-white py-3 rounded-xl text-sm font-semibold transition-opacity"
          >
            {loading ? 'Verificando...' : 'Entrar'}
          </button>
        </form>
      </div>
    </div>
  )
}
