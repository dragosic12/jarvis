#!/bin/bash
# Wrapper para Claude CLI - bloquea SIGINT y SIGHUP, aísla completamente
trap '' INT HUP TERM
unset ANTHROPIC_API_KEY
export TERM=dumb
exec setsid claude -p --model claude-haiku-4-5-20251001 "$@" </dev/null
