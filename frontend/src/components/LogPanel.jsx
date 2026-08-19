import React, { useState, useEffect } from 'react'
import { API_BASE } from '../config'

export default function LogPanel({ authHeaders, authFetch }) {
  const [logs, setLogs] = useState([])

  useEffect(() => {
    authFetch(`${API_BASE}/api/logs`)
      .then(r => r.ok ? r.json() : [])
      .then(setLogs)
      .catch(() => {})
  }, [])

  return (
    <div className="p-4 space-y-2">
      <h3 className="text-sm font-semibold text-jarvis-muted mb-3">Ultimos comandos</h3>
      {logs.length === 0 && <p className="text-sm text-jarvis-muted">Sin historial</p>}
      {logs.map(log => (
        <div key={log.id} className="bg-jarvis-card border border-white/5 rounded-lg px-3 py-2">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${log.success ? 'bg-jarvis-success' : 'bg-jarvis-danger'}`} />
            <p className="text-sm text-white flex-1 truncate">"{log.transcript}"</p>
            <span className="text-[10px] text-jarvis-muted">{new Date(log.timestamp).toLocaleString('es')}</span>
          </div>
          {log.category && (
            <p className="text-xs text-jarvis-accent mt-1">{log.category} → {log.action_executed}</p>
          )}
        </div>
      ))}
    </div>
  )
}
