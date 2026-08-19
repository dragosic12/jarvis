module.exports = {
  apps: [{
    name: 'jarvis-backend',
    script: 'python3',
    args: 'backend/main.py',
    cwd: '/home/dragosic12/jarvis',
    interpreter: 'none',
    autorestart: true,
    max_restarts: 10,
    max_memory_restart: 0,
    env: {
      PYTHONUNBUFFERED: '1',
    }
  }]
}
