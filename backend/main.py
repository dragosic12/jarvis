"""
Jarvis — Asistente de voz con transcripcion y ejecucion de comandos.
Backend FastAPI con WebSocket para audio en tiempo real.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import json
import os
import sys
import hashlib
import hmac
import secrets
import subprocess
import time

# Asegurar que el directorio del backend esta en el path
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, get_db
from transcriber import transcribe_audio, get_model
from parser import parse_intent, normalize
from executor import execute_action
from tts import synthesize as tts_synthesize, DEFAULT_VOICE

app = FastAPI(title="Jarvis", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")

# --- Autenticacion simple con PIN ---
JARVIS_PIN = os.environ.get("JARVIS_PIN", "66379715")
TOKEN_TTL = 86400 * 7  # 7 dias

security = HTTPBearer(auto_error=False)


def _init_tokens_table():
    db = get_db()
    db.execute("CREATE TABLE IF NOT EXISTS auth_tokens (token TEXT PRIMARY KEY, expires_at REAL)")
    db.execute("DELETE FROM auth_tokens WHERE expires_at < ?", (time.time(),))
    db.commit()
    db.close()


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials is None:
        raise HTTPException(401, "Token requerido")
    token = credentials.credentials
    db = get_db()
    row = db.execute("SELECT expires_at FROM auth_tokens WHERE token = ?", (token,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(401, "Token invalido")
    if time.time() > row["expires_at"]:
        db = get_db()
        db.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
        db.commit()
        db.close()
        raise HTTPException(401, "Token expirado")
    return token


@app.post("/api/auth/login")
async def login(body: dict):
    pin = body.get("pin", "")
    if pin != JARVIS_PIN:
        raise HTTPException(403, "PIN incorrecto")
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + TOKEN_TTL
    db = get_db()
    db.execute("INSERT INTO auth_tokens (token, expires_at) VALUES (?, ?)", (token, expires_at))
    db.commit()
    db.close()
    return {"token": token, "expires_in": TOKEN_TTL}


@app.on_event("startup")
def startup():
    init_db()
    _init_tokens_table()
    import threading
    threading.Thread(target=get_model, daemon=True).start()


# --- REST API ---

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "jarvis"}


@app.post("/api/deploy")
async def deploy(request: Request):
    """Webhook de GitHub: valida la firma HMAC y lanza el auto-deploy en 2o plano."""
    body = await request.body()
    try:
        with open(os.path.join(os.path.dirname(__file__), ".deploy_secret")) as f:
            secret = f.read().strip()
    except OSError:
        raise HTTPException(500, "deploy no configurado")
    sig = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(403, "firma invalida")
    # solo desplegar en push a main
    if request.headers.get("X-GitHub-Event") == "push":
        try:
            if json.loads(body).get("ref") not in (None, "refs/heads/main"):
                return {"status": "ignorado (no es main)"}
        except Exception:
            pass
    script = os.path.join(os.path.dirname(__file__), "..", "deploy.sh")
    subprocess.Popen(["bash", script], start_new_session=True)
    return {"status": "desplegando"}


@app.get("/api/tts")
async def tts(text: str = Query(...), voice: str = Query(None)):
    """Sintetiza la voz de Jarvis (voz masculina) y devuelve un MP3.
    Sin auth a proposito: lo consumen <audio> del navegador y MediaPlayer nativo,
    que no pueden mandar cabecera Bearer facilmente. Tope de longitud en tts.py.
    """
    try:
        path = await tts_synthesize(text, voice)
    except Exception as e:
        raise HTTPException(503, f"TTS no disponible: {e}")
    if not path:
        raise HTTPException(400, "Texto vacio")
    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...), _t=Depends(verify_token)):
    """Transcribir audio sin ejecutar comando."""
    data = await audio.read()
    if len(data) < 100:
        raise HTTPException(400, "Audio demasiado corto")
    result = transcribe_audio(data, audio.filename or "audio.webm")
    return result


@app.post("/api/command")
async def process_command(audio: UploadFile = File(...), platform: str = Query("linux"), _t=Depends(verify_token)):
    """Transcribir audio y ejecutar el comando detectado."""
    data = await audio.read()
    if len(data) < 100:
        raise HTTPException(400, "Audio demasiado corto")

    # 1. Transcribir
    transcript = transcribe_audio(data, audio.filename or "audio.webm")

    # 2. Parsear intencion
    intent = parse_intent(transcript["text"], platform=platform)

    # 3. Ejecutar
    result = execute_action(intent, target_platform=platform)

    return {
        "transcript": transcript,
        "intent": intent,
        "result": result,
    }


@app.post("/api/command/text")
async def process_text_command(body: dict, _t=Depends(verify_token)):
    """Procesar un comando por texto (sin audio)."""
    text = body.get("text", "").strip()
    platform = body.get("platform", "linux")
    if not text:
        raise HTTPException(400, "Texto vacio")

    intent = parse_intent(text, platform=platform)
    result = execute_action(intent, target_platform=platform)
    return {"intent": intent, "result": result}


@app.post("/api/system/confirm")
async def confirm_system_action(body: dict, _t=Depends(verify_token)):
    """Confirmar y ejecutar accion de sistema (apagar/reiniciar/suspender)."""
    import subprocess
    cmd = body.get("command")
    if not cmd:
        raise HTTPException(400, "No command")
    # Solo permitir comandos de sistema conocidos o de la categoria apagar en BD
    allowed = ["systemctl suspend", "shutdown -h now", "reboot", "loginctl lock-session"]
    if cmd not in allowed:
        db = get_db()
        row = db.execute(
            "SELECT id FROM commands WHERE action_value = ? AND category = 'apagar' AND enabled = 1",
            (cmd,)
        ).fetchone()
        db.close()
        if not row:
            raise HTTPException(403, "Comando no permitido")
    subprocess.Popen(cmd, shell=True)
    return {"success": True, "message": f"Ejecutando: {cmd}"}


# --- Comandos CRUD ---

@app.get("/api/commands")
def list_commands(category: str = None, _t=Depends(verify_token)):
    db = get_db()
    if category:
        rows = db.execute("SELECT * FROM commands WHERE category = ? ORDER BY trigger_phrase", (category,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM commands ORDER BY category, trigger_phrase").fetchall()
    db.close()
    return [dict(r) for r in rows]


@app.post("/api/commands")
async def add_command(body: dict, _t=Depends(verify_token)):
    required = ["category", "trigger_phrase", "action_type", "action_value"]
    for f in required:
        if f not in body:
            raise HTTPException(400, f"Falta campo: {f}")
    db = get_db()
    db.execute(
        "INSERT INTO commands (category, trigger_phrase, action_type, action_value, description, platform) VALUES (?, ?, ?, ?, ?, ?)",
        (body["category"], body["trigger_phrase"], body["action_type"], body["action_value"],
         body.get("description", ""), body.get("platform", "all"))
    )
    db.commit()
    db.close()
    return {"success": True}


@app.put("/api/commands/{cmd_id}")
async def update_command(cmd_id: int, body: dict, _t=Depends(verify_token)):
    db = get_db()
    fields = []
    values = []
    for f in ["category", "trigger_phrase", "action_type", "action_value", "description", "platform", "enabled"]:
        if f in body:
            fields.append(f"{f} = ?")
            values.append(body[f])
    if not fields:
        raise HTTPException(400, "Nada que actualizar")
    values.append(cmd_id)
    db.execute(f"UPDATE commands SET {', '.join(fields)} WHERE id = ?", values)
    db.commit()
    db.close()
    return {"success": True}


@app.delete("/api/commands/{cmd_id}")
async def delete_command(cmd_id: int, _t=Depends(verify_token)):
    db = get_db()
    db.execute("DELETE FROM commands WHERE id = ?", (cmd_id,))
    db.commit()
    db.close()
    return {"success": True}


# --- Logs ---

@app.get("/api/logs")
def get_logs(limit: int = 50, _t=Depends(verify_token)):
    db = get_db()
    rows = db.execute("SELECT * FROM command_log ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    db.close()
    return [dict(r) for r in rows]


# --- Aliases ---

@app.get("/api/aliases")
def list_aliases(_t=Depends(verify_token)):
    db = get_db()
    rows = db.execute("SELECT * FROM aliases ORDER BY alias").fetchall()
    db.close()
    return [dict(r) for r in rows]


@app.post("/api/aliases")
async def add_alias(body: dict, _t=Depends(verify_token)):
    db = get_db()
    db.execute("INSERT INTO aliases (alias, canonical) VALUES (?, ?)", (body["alias"], body["canonical"]))
    db.commit()
    db.close()
    return {"success": True}


# --- Ajustes en caliente (sensibilidad del micro, etc.) ---

@app.get("/api/settings")
def get_settings():
    # publico: el servicio nativo lo lee sin auth para aplicar la sensibilidad
    from settings import load
    return load()


@app.post("/api/settings")
async def set_settings(body: dict, _t=Depends(verify_token)):
    from settings import save
    return save(body)


# --- Contactos (para mensajes de WhatsApp por voz) ---

@app.get("/api/contacts")
def list_contacts(_t=Depends(verify_token)):
    db = get_db()
    rows = db.execute("SELECT name, phone FROM contacts ORDER BY name").fetchall()
    db.close()
    return [dict(r) for r in rows]


@app.post("/api/contacts")
async def add_contact(body: dict, _t=Depends(verify_token)):
    name = normalize(body.get("name", ""))
    phone = body.get("phone", "").strip()
    if not name or not phone:
        raise HTTPException(400, "Faltan name/phone")
    db = get_db()
    db.execute("INSERT OR REPLACE INTO contacts (name, phone) VALUES (?, ?)", (name, phone))
    db.commit()
    db.close()
    return {"success": True, "name": name}


@app.delete("/api/contacts/{name}")
async def delete_contact(name: str, _t=Depends(verify_token)):
    db = get_db()
    db.execute("DELETE FROM contacts WHERE name = ?", (normalize(name),))
    db.commit()
    db.close()
    return {"success": True}


# --- WebSocket para audio en tiempo real ---

@app.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_bytes()
            # Transcribir
            transcript = transcribe_audio(data, "audio.webm")
            # Parsear
            intent = parse_intent(transcript["text"])
            # Ejecutar
            result = execute_action(intent)

            await websocket.send_json({
                "transcript": transcript,
                "intent": intent,
                "result": result,
            })
    except WebSocketDisconnect:
        pass


# --- Servir frontend (SPA) cuando se accede via tunnel directo ---
if os.path.exists(FRONTEND_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="static-assets")

    @app.get("/manifest.json")
    async def manifest():
        return FileResponse(os.path.join(FRONTEND_DIR, "manifest.json"))

    @app.get("/favicon.svg")
    async def favicon():
        return FileResponse(os.path.join(FRONTEND_DIR, "favicon.svg"))

    @app.get("/{path:path}")
    async def spa_catchall(path: str):
        # Servir archivo si existe, si no index.html (SPA)
        file_path = os.path.join(FRONTEND_DIR, path)
        if path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4040)
