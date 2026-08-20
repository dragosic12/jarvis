import React, { useState } from 'react'

const GROUPS = [
  {
    title: 'Preguntas e info',
    items: [
      ['qué es X · explícame Y · dime Z', 'Responde Gemini'],
      ['Claude, [pregunta]', 'Claude, con memoria del hilo'],
      ['dile a Claude que [tarea]', 'Claude en modo agente'],
      ['cuánto me queda de Claude', 'Tu uso + cuándo se renueva'],
      ['qué hora es · qué tiempo hace · batería', 'Info rápida'],
      ['tradúceme X al inglés', 'Traducción'],
    ],
  },
  {
    title: 'Móvil',
    items: [
      ['enciende / apaga la linterna', ''],
      ['sube / baja el volumen · modo silencio', ''],
      ['bloquea el móvil', ''],
      ['dónde estás · busca el móvil', 'Suena aunque esté en silencio'],
      ['pon una alarma a las 8 · temporizador de 5 minutos', ''],
      ['recuérdame [algo] en 10 minutos / a las 6', ''],
      ['abre [app o web]', ''],
    ],
  },
  {
    title: 'WhatsApp',
    items: [
      ['dile a [contacto] que [mensaje]', 'Escribe y envía solo'],
      ['manda un audio a [contacto]', 'Graba tu voz y la envía'],
      ['abre el chat de [contacto]', ''],
    ],
  },
  {
    title: 'Ordenador',
    items: [
      ['abre X en el ordenador', ''],
      ['sube / baja el volumen del ordenador · pausa · siguiente', ''],
      ['apaga / reinicia / suspende / bloquea el ordenador', ''],
      ['escribe en el ordenador [texto]', 'Teclea en la ventana activa'],
      ['haz una captura y mándamela', 'Captura el PC y te la abre en el móvil'],
    ],
  },
  {
    title: 'Modos y rutinas',
    items: [
      ['activa el modo coche', 'Lee los WhatsApp en alto'],
      ['modo conversación', 'Habla sin repetir "Jarvis"'],
      ['aprende esta rutina → guarda la rutina como X', 'Graba tus toques'],
      ['haz la rutina X', 'Reproduce una rutina guardada'],
      ['analiza mis rutinas', 'Qué haces más repetido'],
    ],
  },
]

export default function Cheatsheet() {
  const [q, setQ] = useState('')
  const nq = q.trim().toLowerCase()
  const groups = GROUPS
    .map((g) => ({
      ...g,
      items: g.items.filter(
        ([cmd, desc]) =>
          !nq ||
          cmd.toLowerCase().includes(nq) ||
          desc.toLowerCase().includes(nq) ||
          g.title.toLowerCase().includes(nq),
      ),
    }))
    .filter((g) => g.items.length)

  return (
    <div className="px-4 py-4">
      <p className="text-[11px] text-jarvis-muted mb-3">
        Di <span className="text-jarvis-accent">"Jarvis"</span> y luego cualquiera de estas.
      </p>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Buscar comando…"
        className="w-full mb-4 bg-jarvis-card/60 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-jarvis-muted focus:outline-none focus:border-jarvis-accent/50"
      />
      {groups.map((g) => (
        <div key={g.title} className="mb-5">
          <h3 className="font-display text-xs tracking-widest text-jarvis-accent/80 mb-2 uppercase">{g.title}</h3>
          <div className="space-y-1.5">
            {g.items.map(([cmd, desc], i) => (
              <div key={i} className="glass rounded-lg px-3 py-2 border border-white/5">
                <div className="text-sm text-white/90">“{cmd}”</div>
                {desc && <div className="text-[11px] text-jarvis-muted mt-0.5">{desc}</div>}
              </div>
            ))}
          </div>
        </div>
      ))}
      {groups.length === 0 && <p className="text-jarvis-muted text-sm text-center py-6">Nada encontrado.</p>}
    </div>
  )
}
