#!/bin/bash
# Voz -> Claude CONVERSACIONAL con hilo persistente (recuerda contexto). Arg: $1=prompt
trap "" INT HUP TERM
unset ANTHROPIC_API_KEY
export TERM=dumb
SIDFILE="$HOME/jarvis/backend/.claude_voice_session"
SP="Eres Jarvis, un asistente de voz personal. Responde SIEMPRE muy breve (1 o 2 frases), en espanol de Espana, sin markdown, sin listas ni emojis, pensado para leer en voz alta."
cd /tmp || exit 1
if [ -f "$SIDFILE" ]; then
  SID=$(cat "$SIDFILE")
  setsid claude -p "$1" --resume "$SID" --model claude-haiku-4-5-20251001 --append-system-prompt "$SP" </dev/null
else
  SID=$(python3 -c "import uuid;print(uuid.uuid4())")
  echo "$SID" > "$SIDFILE"
  setsid claude -p "$1" --session-id "$SID" --model claude-haiku-4-5-20251001 --append-system-prompt "$SP" </dev/null
fi
