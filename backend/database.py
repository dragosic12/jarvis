import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "jarvis.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            trigger_phrase TEXT NOT NULL,
            action_type TEXT NOT NULL,
            action_value TEXT NOT NULL,
            description TEXT,
            platform TEXT DEFAULT 'all',
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS command_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transcript TEXT,
            matched_command_id INTEGER,
            category TEXT,
            action_executed TEXT,
            result TEXT,
            success INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias TEXT NOT NULL,
            canonical TEXT NOT NULL
        )
    """)

    # Seed con comandos iniciales si la tabla esta vacia
    count = c.execute("SELECT COUNT(*) FROM commands").fetchone()[0]
    if count == 0:
        seed_commands(c)

    conn.commit()
    conn.close()


def seed_commands(c):
    commands = [
        # --- Categoria: abrir (programas/URLs) ---
        ("abrir", "google", "url", "https://www.google.com", "Abre Google en el navegador", "all"),
        ("abrir", "youtube", "url", "https://www.youtube.com", "Abre YouTube", "all"),
        ("abrir", "gmail", "url", "https://mail.google.com", "Abre Gmail", "all"),
        ("abrir", "whatsapp", "url", "https://web.whatsapp.com", "Abre WhatsApp Web", "all"),
        ("abrir", "github", "url", "https://github.com", "Abre GitHub", "all"),
        ("abrir", "chatgpt", "url", "https://chat.openai.com", "Abre ChatGPT", "all"),
        ("abrir", "twitter", "url", "https://x.com", "Abre X/Twitter", "all"),
        ("abrir", "spotify", "url", "https://open.spotify.com", "Abre Spotify Web", "all"),
        ("abrir", "netflix", "url", "https://www.netflix.com", "Abre Netflix", "all"),
        ("abrir", "calculator", "shell", "calc", "Abre la calculadora", "windows"),
        ("abrir", "calculadora", "shell", "calc", "Abre la calculadora", "windows"),
        ("abrir", "notepad", "shell", "notepad", "Abre Bloc de notas", "windows"),
        ("abrir", "bloc de notas", "shell", "notepad", "Abre Bloc de notas", "windows"),
        ("abrir", "terminal", "shell", "wt", "Abre Windows Terminal", "windows"),
        ("abrir", "explorador", "shell", "explorer", "Abre Explorador de archivos", "windows"),
        ("abrir", "swapcar", "url", "https://www.swapcar.app", "Abre SwapCar", "all"),
        ("abrir", "nexus", "url", "http://192.0.2.10/nexus/", "Abre Nexus Control", "all"),
        ("abrir", "immich", "url", "http://192.0.2.10:2283", "Abre Immich fotos", "all"),
        ("abrir", "nextcloud", "url", "http://192.0.2.10:8090", "Abre Nextcloud", "all"),
        ("abrir", "jellyfin", "url", "http://192.0.2.10:8096", "Abre Jellyfin", "all"),
        ("abrir", "qbittorrent", "url", "http://192.0.2.10:8085", "Abre qBittorrent", "all"),
        ("abrir", "finanzas", "url", "http://192.0.2.10/finanzas/", "Abre app Finanzas", "all"),
        ("abrir", "hive", "url", "http://192.0.2.10/hive/", "Abre Hive", "all"),
        ("abrir", "webcraft", "url", "http://192.0.2.10/webcraft/", "Abre WebCraft", "all"),
        ("abrir", "la gatta", "url", "http://192.0.2.10/lagatta/", "Abre La Gatta", "all"),

        # --- Categoria: buscar ---
        ("buscar", "google", "search", "https://www.google.com/search?q={query}", "Busca en Google", "all"),
        ("buscar", "youtube", "search", "https://www.youtube.com/results?search_query={query}", "Busca en YouTube", "all"),
        ("buscar", "amazon", "search", "https://www.amazon.es/s?k={query}", "Busca en Amazon", "all"),
        ("buscar", "wikipedia", "search", "https://es.wikipedia.org/wiki/Special:Search?search={query}", "Busca en Wikipedia", "all"),

        # --- Categoria: servidor ---
        ("servidor", "estado", "server_cmd", "pm2 list", "Muestra estado PM2", "linux"),
        ("servidor", "reiniciar backend", "server_cmd", "pm2 restart carswap-backend", "Reinicia backend SwapCar", "linux"),
        ("servidor", "reiniciar nexus", "server_cmd", "pm2 restart nexus-backend", "Reinicia Nexus", "linux"),
        ("servidor", "logs backend", "server_cmd", "pm2 logs carswap-backend --lines 30 --nostream", "Logs del backend", "linux"),
        ("servidor", "docker", "server_cmd", "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'", "Estado Docker containers", "linux"),
        ("servidor", "disco", "server_cmd", "df -h / /home", "Espacio en disco", "linux"),
        ("servidor", "memoria", "server_cmd", "free -h", "Uso de memoria RAM", "linux"),
        ("servidor", "cpu", "server_cmd", "top -bn1 | head -5", "Uso de CPU", "linux"),

        # --- Categoria: red ---
        ("red", "diagnostico", "server_cmd", "ping -c 3 8.8.8.8 && ping -c 3 google.com", "Diagnostico de red basico", "linux"),
        ("red", "ip", "server_cmd", "curl -s ifconfig.me && echo '' && ip addr show | grep 'inet '", "Muestra IPs", "linux"),
        ("red", "velocidad", "server_cmd", "speedtest-cli --simple 2>/dev/null || echo 'speedtest-cli no instalado'", "Test de velocidad", "linux"),
        ("red", "puertos", "server_cmd", "ss -tlnp | head -20", "Puertos abiertos", "linux"),
        ("red", "tailscale", "server_cmd", "tailscale status", "Estado de Tailscale", "linux"),

        # --- Categoria: sistema ---
        ("sistema", "suspender", "system", "suspend", "Suspender equipo", "all"),
        ("sistema", "apagar", "system", "shutdown", "Apagar equipo", "all"),
        ("sistema", "reiniciar", "system", "reboot", "Reiniciar equipo", "all"),
        ("sistema", "bloquear", "system", "lock", "Bloquear pantalla", "all"),

        # --- Categoria: claude ---
        ("claude", "nueva conversacion", "claude", "new", "Nueva conversacion Claude", "linux"),
        ("claude", "continuar", "claude", "continue", "Continuar ultima conversacion", "linux"),
    ]

    for cmd in commands:
        c.execute(
            "INSERT INTO commands (category, trigger_phrase, action_type, action_value, description, platform) VALUES (?, ?, ?, ?, ?, ?)",
            cmd
        )

    # Aliases comunes
    aliases = [
        ("abre", "abrir"),
        ("abreme", "abrir"),
        ("busca", "buscar"),
        ("buscame", "buscar"),
        ("dime", "servidor"),
        ("muestrame", "servidor"),
        ("muestra", "servidor"),
    ]
    for alias, canonical in aliases:
        c.execute("INSERT INTO aliases (alias, canonical) VALUES (?, ?)", (alias, canonical))
