import { useState, useCallback, useRef } from 'react'
import { API_BASE } from '../config'

const TOKEN_KEY = 'jarvis_token'

export function useAuth() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [error, setError] = useState(null)
  const tokenRef = useRef(token)
  tokenRef.current = token

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
  }, [])

  const login = useCallback(async (pin) => {
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin }),
      })
      if (!res.ok) {
        setError('PIN incorrecto')
        return false
      }
      const data = await res.json()
      localStorage.setItem(TOKEN_KEY, data.token)
      setToken(data.token)
      return true
    } catch (e) {
      setError('Error de conexion')
      return false
    }
  }, [])

  // Headers helper para fetch
  const authHeaders = useCallback(() => {
    const t = tokenRef.current
    return t ? { Authorization: `Bearer ${t}` } : {}
  }, [])

  // Fetch wrapper que detecta 401 y hace auto-logout
  const authFetch = useCallback(async (url, options = {}) => {
    const t = tokenRef.current
    const headers = { ...options.headers }
    if (t) headers['Authorization'] = `Bearer ${t}`
    const res = await fetch(url, { ...options, headers })
    if (res.status === 401) {
      logout()
      throw new Error('Sesion expirada')
    }
    return res
  }, [logout])

  return { token, login, logout, error, authHeaders, authFetch, isLoggedIn: !!token }
}
