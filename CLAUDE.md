# Jarvis — contexto para Claude

Asistente de voz personal (estilo "Jarvis") del usuario Dragos. App Android nativa + backend
en servidor propio. Este archivo da contexto a cualquier sesion de Claude (PC o movil).

## Arquitectura
- **backend/** — FastAPI (Python, sin venv, python3 del sistema). Corre en el servidor
  "draleserver" con pm2 como `jarvis-backend` (puerto 4040). Piezas:
  - `main.py` rutas API (/api/transcribe, /api/command, /api/command/text, /api/tts...).
  - `parser.py` detecta la intencion del texto (matchers + comandos en BD sqlite). Casa por
    FONETICA ademas de literal. Wake word "Jarvis".
  - `executor.py` ejecuta la accion (abrir url/app, whatsapp, alarmas, volumen, PC, Claude...).
  - `transcriber.py` transcribe audio: 1) Groq Whisper large-v3-turbo (rapido), 2) GPU del PC,
    3) CPU local. OJO: Groq necesita header User-Agent (Cloudflare) y el prompt NO debe empezar
    por "Jarvis" (se cuela y causa falsos disparos).
  - `tts.py` voz: edge-tts (es-ES-AlvaroNeural, masculina) + filtro robotico con ffmpeg.
  - `weather.py`, `claude_usage.py`, `translate.py`, scripts claude_chat.sh / claude_agent.sh.
- **frontend/** — web React+Vite envuelta en Android nativo con Capacitor 6 (server.url =
  https://jarvis.swapcar.app, la app carga la web viva; cada deploy web actualiza la app SIN
  reinstalar). Codigo nativo clave en `frontend/android/app/src/main/java/com/drale/jarvis/`:
  - `ListeningService.java` — escucha nativa continua (AudioRecord + VAD + wake word), reproduce
    la voz del servidor (MediaPipe/MediaPlayer), modo conversacion, barge-in "para".
  - `FaceGestureService.java` + `JarvisA11yService.java` — control por gestos faciales (MediaPipe
    + AccessibilityService). `BackgroundListeningPlugin.java` puente JS<->nativo.

## Como desplegar cambios (requiere acceso al servidor, no desde la nube)
- Web/backend: editar en ~/jarvis en el servidor. Web: `cd frontend && NODE_ENV=development npx
  vite build && cp -r dist/* /var/www/jarvis/`. Backend: `pm2 restart jarvis-backend`.
- APK (solo si cambia codigo NATIVO): docker build (mobiledevops/android-sdk-image:34.0.0-jdk17,
  montar TODA la carpeta frontend), firmar con android-keys, copiar a /var/www/jarvis/jarvis.apk.
- Una sesion de Claude en la NUBE (movil) puede EDITAR el codigo del repo, pero para aplicarlo al
  server/app hace falta `git pull` + build en el servidor (paso aparte).

## Secretos (NO estan en el repo, ver .gitignore)
backend/.groq_key, android-keys/ (keystore+contraseñas), *.db (contactos). Al clonar, re-anadir.

## Funciones actuales
Wake word "Jarvis" + escucha continua; abrir apps/webs; WhatsApp/llamadas a contactos (con
alias y matching fonetico); alarmas/temporizadores; volumen/silencio; hora/tiempo/briefing;
uso de Claude por voz; traductor; modo conversacion; control por gestos faciales (boss final);
abrir cosas en el PC por SSH; hablar con Claude por voz (hilo con contexto) y agente.
