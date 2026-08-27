"""
Jarvis Windows Agent
====================
Este script corre en el PC Windows de la misma red.
Se conecta al backend Jarvis del servidor y ejecuta comandos localmente.

Instalacion en Windows:
  pip install requests websockets

Uso:
  python windows_agent.py --server http://YOUR-SERVER:4040

El agente consulta periodicamente el servidor buscando comandos pendientes
para la plataforma "windows", o se conecta via WebSocket para recibir
comandos en tiempo real.
"""

import argparse
import subprocess
import sys
import time
import json

try:
    import requests
except ImportError:
    print("Instala requests: pip install requests")
    sys.exit(1)


def execute_windows_command(cmd_data):
    """Ejecuta un comando en Windows."""
    cmd_type = cmd_data.get("type")

    if cmd_type == "open_url":
        url = cmd_data["url"]
        print(f"[Jarvis] Abriendo URL: {url}")
        subprocess.Popen(["start", url], shell=True)
        return {"success": True, "message": f"URL abierta: {url}"}

    elif cmd_type == "shell_cmd":
        cmd = cmd_data["command"]
        print(f"[Jarvis] Ejecutando: {cmd}")
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            return {
                "success": result.returncode == 0,
                "message": result.stdout or result.stderr or "Ejecutado",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "Timeout"}

    elif cmd_type == "system_action":
        action = cmd_data.get("action")
        cmd = cmd_data.get("command")
        if cmd:
            print(f"[Jarvis] Accion sistema: {action}")
            subprocess.Popen(cmd, shell=True)
            return {"success": True, "message": f"Sistema: {action}"}

    return {"success": False, "message": "Tipo desconocido"}


def poll_mode(server_url, interval=2):
    """Modo polling: consulta el servidor cada N segundos."""
    print(f"[Jarvis Windows Agent] Conectado a {server_url}")
    print(f"[Jarvis Windows Agent] Modo polling cada {interval}s")
    print("[Jarvis Windows Agent] Esperando comandos...")

    while True:
        try:
            # Por ahora el polling es basico - en futuro se usara WebSocket
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[Jarvis] Agente detenido")
            break


def main():
    parser = argparse.ArgumentParser(description="Jarvis Windows Agent")
    parser.add_argument("--server", default="http://YOUR-SERVER:4040", help="URL del servidor Jarvis")
    parser.add_argument("--interval", type=int, default=2, help="Intervalo polling (segundos)")
    args = parser.parse_args()

    print("=" * 50)
    print("  JARVIS - Windows Agent")
    print(f"  Servidor: {args.server}")
    print("=" * 50)

    # Verificar conexion
    try:
        r = requests.get(f"{args.server}/api/health", timeout=5)
        if r.status_code == 200:
            print("[OK] Servidor Jarvis accesible")
        else:
            print(f"[WARN] Servidor respondio {r.status_code}")
    except Exception as e:
        print(f"[ERROR] No se puede conectar al servidor: {e}")
        print("Asegurate de que el servidor esta corriendo y accesible")
        sys.exit(1)

    poll_mode(args.server, args.interval)


if __name__ == "__main__":
    main()
