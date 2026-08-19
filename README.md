# Jarvis — Asistente de voz personal

App Android nativa (Capacitor + React) con backend FastAPI en servidor propio.
Escucha continua con wake word "Jarvis", voz neuronal masculina, control del móvil,
gestos faciales, hablar con Claude por voz, etc.

## Estructura
- `backend/` — FastAPI: parser de intenciones, TTS (edge-tts), transcripción (Groq Whisper), comandos.
- `frontend/` — web (React+Vite) envuelta en Android nativo (Capacitor). Servicios nativos en
  `frontend/android/app/src/main/java/com/drale/jarvis/` (escucha, gestos, voz).
- `scripts/` — utilidades.

## Secretos NO incluidos (añadir tras clonar, ver .gitignore)
- `backend/.groq_key` — API key de Groq (transcripción).
- `android-keys/` — keystore de firma + keystore.properties (contraseñas).
- `*.db` — base de datos (contactos personales).
- OAuth del CLI de Claude en `~/.claude`.
