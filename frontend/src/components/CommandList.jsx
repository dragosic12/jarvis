import React, { useState, useEffect } from 'react'
import { API_BASE } from '../config'

const CATEGORIES = [
  { id: 'abrir', label: 'Abrir', color: 'text-blue-400' },
  { id: 'buscar', label: 'Buscar', color: 'text-green-400' },
  { id: 'servidor', label: 'Servidor', color: 'text-yellow-400' },
  { id: 'red', label: 'Red', color: 'text-cyan-400' },
  { id: 'sistema', label: 'Sistema', color: 'text-red-400' },
  { id: 'claude', label: 'Claude', color: 'text-purple-400' },
  { id: 'llamar', label: 'Llamar', color: 'text-orange-400' },
]

export default function CommandList({ authHeaders, authFetch }) {
  const [commands, setCommands] = useState([])
  const [filter, setFilter] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [newCmd, setNewCmd] = useState({ category: 'abrir', trigger_phrase: '', action_type: 'url', action_value: '', description: '', platform: 'all' })

  useEffect(() => { loadCommands() }, [filter])

  const loadCommands = async () => {
    try {
      const url = filter ? `${API_BASE}/api/commands?category=${filter}` : `${API_BASE}/api/commands`
      const res = await authFetch(url)
      if (res.ok) setCommands(await res.json())
    } catch {}
  }

  const addCommand = async () => {
    if (!newCmd.trigger_phrase || !newCmd.action_value) return
    await authFetch(`${API_BASE}/api/commands`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newCmd),
    })
    setNewCmd({ category: 'abrir', trigger_phrase: '', action_type: 'url', action_value: '', description: '', platform: 'all' })
    setShowAdd(false)
    loadCommands()
  }

  const deleteCmd = async (id) => {
    await authFetch(`${API_BASE}/api/commands/${id}`, { method: 'DELETE' })
    loadCommands()
  }

  const grouped = {}
  commands.forEach(c => {
    if (!grouped[c.category]) grouped[c.category] = []
    grouped[c.category].push(c)
  })

  return (
    <div className="p-4 space-y-4">
      {/* Filtros */}
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={() => setFilter(null)}
          className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
            !filter ? 'bg-jarvis-primary text-white' : 'bg-jarvis-card text-jarvis-muted hover:text-white'
          }`}
        >Todos</button>
        {CATEGORIES.map(cat => (
          <button
            key={cat.id}
            onClick={() => setFilter(cat.id)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              filter === cat.id ? 'bg-jarvis-primary text-white' : 'bg-jarvis-card text-jarvis-muted hover:text-white'
            }`}
          >{cat.label}</button>
        ))}
      </div>

      {/* Boton agregar */}
      <button
        onClick={() => setShowAdd(!showAdd)}
        className="bg-jarvis-primary/20 hover:bg-jarvis-primary/30 text-jarvis-primary px-4 py-2 rounded-lg text-sm w-full"
      >
        {showAdd ? 'Cancelar' : '+ Nuevo comando'}
      </button>

      {/* Form agregar */}
      {showAdd && (
        <div className="bg-jarvis-card border border-white/10 rounded-xl p-4 space-y-3 animate-fade-in">
          <div className="grid grid-cols-2 gap-3">
            <select value={newCmd.category} onChange={e => setNewCmd({...newCmd, category: e.target.value})}
              className="bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm text-white">
              {CATEGORIES.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
            <select value={newCmd.action_type} onChange={e => setNewCmd({...newCmd, action_type: e.target.value})}
              className="bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm text-white">
              <option value="url">URL</option>
              <option value="shell">Shell</option>
              <option value="server_cmd">Servidor</option>
              <option value="search">Busqueda</option>
              <option value="system">Sistema</option>
            </select>
          </div>
          <input value={newCmd.trigger_phrase} onChange={e => setNewCmd({...newCmd, trigger_phrase: e.target.value})}
            placeholder="Frase trigger (ej: spotify)" className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-jarvis-muted" />
          <input value={newCmd.action_value} onChange={e => setNewCmd({...newCmd, action_value: e.target.value})}
            placeholder="Accion (URL o comando)" className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-jarvis-muted" />
          <input value={newCmd.description} onChange={e => setNewCmd({...newCmd, description: e.target.value})}
            placeholder="Descripcion (opcional)" className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-jarvis-muted" />
          <div className="flex gap-2">
            <select value={newCmd.platform} onChange={e => setNewCmd({...newCmd, platform: e.target.value})}
              className="bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm text-white">
              <option value="all">Todas</option>
              <option value="linux">Linux</option>
              <option value="windows">Windows</option>
            </select>
            <button onClick={addCommand} className="flex-1 bg-jarvis-success hover:bg-green-600 text-white py-2 rounded-lg text-sm font-medium">
              Guardar
            </button>
          </div>
        </div>
      )}

      {/* Lista */}
      {Object.entries(grouped).map(([cat, cmds]) => {
        const catInfo = CATEGORIES.find(c => c.id === cat)
        return (
          <div key={cat}>
            <h3 className={`text-sm font-semibold mb-2 ${catInfo?.color || 'text-white'}`}>
              {catInfo?.label || cat} ({cmds.length})
            </h3>
            <div className="space-y-1">
              {cmds.map(cmd => (
                <div key={cmd.id} className="bg-jarvis-card border border-white/5 rounded-lg px-3 py-2 flex items-center gap-3 group">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">
                      <span className="text-jarvis-accent font-mono">{cmd.category}</span>{' '}
                      {cmd.trigger_phrase}
                    </p>
                    <p className="text-xs text-jarvis-muted truncate">{cmd.action_value}</p>
                  </div>
                  {cmd.platform !== 'all' && (
                    <span className="text-[10px] bg-white/5 px-1.5 py-0.5 rounded text-jarvis-muted">{cmd.platform}</span>
                  )}
                  <button onClick={() => deleteCmd(cmd.id)}
                    className="opacity-0 group-hover:opacity-100 text-jarvis-danger text-xs hover:underline transition-opacity">
                    Borrar
                  </button>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
