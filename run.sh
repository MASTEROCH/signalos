#!/usr/bin/env bash
# SignalOS — запуск одной командой. Ноль зависимостей, ноль ключей.
cd "$(dirname "$0")" || exit 1

# конфиг не копируем — при первом запуске дашборд сам проведёт настройку (мастер)

# (опц.) ключи из .env, если есть
[ -f .env ] && set -a && . ./.env && set +a

PORT="${SIGNALOS_PORT:-8000}"

# используем venv (там Telethon для Telegram), иначе системный python3
PY="python3"
[ -x .venv/bin/python ] && PY=".venv/bin/python"

( sleep 1.5 && open "http://localhost:${PORT}" >/dev/null 2>&1 ) &
echo "  Открываю http://localhost:${PORT} …"
exec "$PY" -m signalos.server
