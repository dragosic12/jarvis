#!/bin/bash
# Voz -> Claude AGENTE (hace tareas en el repo jarvis, autonomo). Arg: $1=tarea
trap "" INT HUP TERM
unset ANTHROPIC_API_KEY
export TERM=dumb
cd "$HOME/jarvis" || exit 1
setsid claude -p "$1" --dangerously-skip-permissions --model sonnet >> "$HOME/jarvis/backend/claude_agent.log" 2>&1 &
